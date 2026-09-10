"""Workflow 状态机 MVP：模板驱动的多步计算流程（全离线、断点续跑）。

设计要点（刻意保持简单）：
- 状态持久化到 outputs/<project>/workflows/<wf_id>/state.json，
  每次调用读取→推进→写回，天然支持断点续跑与跨会话查询；
- 每个步骤有独立目录（如 00_parent_relax/），vasp 类步骤在此生成
  INCAR/KPOINTS/POSCAR 输入集；人工提交集群计算后把 OUTCAR 放回
  同一目录，再调 advance_workflow 即可结算 TOTEN；
- 推进语义：advance_workflow 从当前指针级联推进——步骤自动完成就
  继续前移执行下一步，遇到需要人工介入的状态（waiting_submit /
  waiting_confirm）即停；全部步骤 done 则收尾 status="done"；
- 纪律：全离线实现，不做任何 ssh / 远端提交；只读写 outputs/ 下
  自己的产物，不修改任何既有文件。
"""
from __future__ import annotations

import importlib
import json
import os
import re
import time
from typing import Callable, Dict, List, Optional, Union

from .common import OUTPUTS_DIR, out_dir
from . import organize

try:
    from pymatgen.core import Structure as _Structure
except ImportError:  # pragma: no cover
    from pymatgen.core.structure import Structure as _Structure

__all__ = ["start_workflow", "advance_workflow", "workflow_status",
           "list_workflows", "list_active_workflows", "WF_TEMPLATES", "TOOLS"]

SCHEMA_VERSION = 1  # state.json 结构版本；后续字段变更须递增


# ==================== 内置模板 ====================

# 模板 = 有序步骤列表；name 在工作流内唯一，type 决定处理器。
WF_TEMPLATES: Dict[str, List[dict]] = {
    # 冒烟链：三步全离线，用于验证状态机本身能跑通
    "smoke_local_chain": [
        {"name": "demo_calc", "type": "local_calc"},
        {"name": "summary_report", "type": "report"},
        {"name": "final_note", "type": "note"},
    ],
    # NMO 母相对比链：两步 VASP 人工提交 + 本地形成能 + 报告 + 笔记
    "nmo_parent_compare": [
        {"name": "parent_relax", "type": "vasp_relax"},
        {"name": "parent_dos", "type": "vasp_static_dos"},
        {"name": "formation_energy", "type": "local_calc"},
        {"name": "compare_report", "type": "report"},
        {"name": "result_note", "type": "note"},
    ],
    # 通用标准链：弛豫 → 静态 DOS → 能量/DOS/带隙提取 → 报告 → 笔记
    # （S5 用户确认：最普遍的计算模式，无 NMO 专属语义）
    "relax_dos_standard": [
        {"name": "relax", "type": "vasp_relax"},
        {"name": "dos", "type": "vasp_static_dos"},
        {"name": "extract", "type": "local_analysis"},
        {"name": "summary_report", "type": "report"},
        {"name": "final_note", "type": "note"},
    ],
}


# ==================== 占位输入常量 ====================

# 占位 POSCAR：NaCl 岩盐常规胞。MVP 用固定结构保证离线确定性；
# 由 start_workflow 的 params_json 后续版本注入真实结构。
_PLACEHOLDER_POSCAR = """\
NaCl 岩盐占位结构 (MVP占位; 真实结构将由 start_workflow 的 params_json 后续版本注入)
1.0
5.640000000 0.000000000 0.000000000
0.000000000 5.640000000 0.000000000
0.000000000 0.000000000 5.640000000
Na Cl
4 4
Direct
0.000000000 0.000000000 0.000000000
0.500000000 0.500000000 0.000000000
0.500000000 0.000000000 0.500000000
0.000000000 0.500000000 0.500000000
0.500000000 0.000000000 0.000000000
0.000000000 0.500000000 0.000000000
0.000000000 0.000000000 0.500000000
0.500000000 0.500000000 0.500000000
"""

# 最小弛豫 INCAR 模板（手写；完整参数化留待后续版本）
_INCAR_RELAX = """\
# workflows MVP 最小弛豫模板
SYSTEM = relax
IBRION = 2
ISIF = 3
NSW = 100
"""

# 最小静态 DOS INCAR 模板（手写）
_INCAR_STATIC_DOS = """\
# workflows MVP 最小静态DOS模板
SYSTEM = static_dos
NSW = 0
LORBIT = 11
"""

# Gamma 中心 K 点网格（占位密度，够 MVP 用）
_KPOINTS_GAMMA = """\
K-Points
0
Gamma
4 4 4
0 0 0
"""

# OUTCAR 中 TOTEN 行解析（如 "  free energy   TOTEN  =  -123.45 eV"）
_TOTEN_RE = re.compile(r"TOTEN.*=\s*(-?\d+\.\d+)")
# 从 organize.export_report / vault_note.save_result_note 返回文本中提取落盘路径
_SAVED_PATH_RE = re.compile(r"(?:报告)?已保存:\s*(.+)")


# ==================== 存储 ====================

def _read_base(project: str) -> str:
    """只读路径基座：与 common.out_dir 同规则但绝不创建目录（供只读查询用）。"""
    return os.path.join(OUTPUTS_DIR, project.strip("/\\"))


def _wf_root(project: str) -> str:
    """某项目的工作流根目录（只读视角）。"""
    return os.path.join(_read_base(project), "workflows")


def _wf_dir(wf_id: str, project: str) -> str:
    """单个工作流的目录（写入时配合 out_dir 自动创建）。"""
    return os.path.join(out_dir(project), "workflows", wf_id)


def _step_dir(wf_id: str, project: str, index: int, name: str) -> str:
    """步骤目录：<wf_dir>/<序号>_<name>/，输入集与 OUTCAR 都放这里。"""
    return os.path.join(_wf_dir(wf_id, project), f"{index:02d}_{name}")


def _state_path(wf_id: str, project: str) -> str:
    """state.json 完整路径。"""
    return os.path.join(_read_base(project), "workflows", wf_id, "state.json")


def _save_state(state: dict) -> None:
    """原子写回 state.json，避免进程中断留下半截 JSON。

    每次落盘递增 ``revision``，供 expected_revision CAS 与并发陈旧检测。
    """
    state["revision"] = int(state.get("revision", 0) or 0) + 1
    path = os.path.join(_wf_dir(state["wf_id"], state["project"]), "state.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _emit_wf_event(event_type: str, state: dict, **payload) -> None:
    """尽力写 outbox；失败不阻断状态机（延迟导入避免循环依赖）。"""
    try:
        from . import workflow_events
    except ImportError:  # pragma: no cover
        try:
            from matcalc import workflow_events
        except ImportError:
            return
    try:
        workflow_events.emit_event(
            event_type,
            state.get("wf_id", ""),
            state.get("project", ""),
            revision=state.get("revision"),
            status=state.get("status"),
            **payload,
        )
    except Exception:  # noqa: BLE001
        pass


def _load_state(wf_id: str, project: str) -> Optional[dict]:
    """读取 state.json；不存在返回 None（只读，无副作用）。"""
    path = _state_path(wf_id, project)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _iter_workflow_states(project: Optional[str] = None):
    """只读遍历 workflow state，返回 (state, state_path, mtime)。"""
    roots = [_wf_root(project)] if project else []
    if project is None and os.path.isdir(OUTPUTS_DIR):
        roots = [os.path.join(OUTPUTS_DIR, name, "workflows")
                 for name in os.listdir(OUTPUTS_DIR)]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for d in sorted(os.listdir(root)):
            sp = os.path.join(root, d, "state.json")
            if not os.path.isfile(sp):
                continue
            try:
                with open(sp, "r", encoding="utf-8") as f:
                    state = json.load(f)
                yield state, sp, os.path.getmtime(sp)
            except (OSError, ValueError, TypeError):
                continue


def _active_workflow_records(project: Optional[str] = None,
                             workflow_ids: Optional[list[str]] = None) -> list[dict]:
    """构造未完成 workflow 的结构化只读记录（state.json 是唯一真源）。"""
    wanted = set(workflow_ids or [])
    records = []
    for st, sp, mtime in _iter_workflow_states(project):
        if st.get("status") == "done" or (wanted and st.get("wf_id") not in wanted):
            continue
        steps = st.get("steps") or []
        current = st.get("current", 0)
        current_step = steps[current] if isinstance(current, int) and 0 <= current < len(steps) else {}
        records.append({
            "wf_id": st.get("wf_id", ""),
            "project": st.get("project", ""),
            "template": st.get("template", ""),
            "status": st.get("status", ""),
            "progress": f"{sum(1 for s in steps if s.get('status') == 'done')}/{len(steps)}",
            "current_step": current_step.get("name", "-"),
            "current_status": current_step.get("status", "-"),
            "job_id": current_step.get("submitted_job", ""),
            "auto_submit": bool((st.get("params") or {}).get("auto_submit", False)),
            # 兼容旧 state；新状态可用 revision 做并发/陈旧请求标记。
            "revision": int(st.get("revision", 0) or 0),
            "state_path": sp,
            "mtime": mtime,
        })
    return sorted(records, key=lambda x: x["mtime"], reverse=True)


def list_active_workflows(project: Optional[str] = None,
                          workflow_ids: Optional[list[str]] = None) -> str:
    """列出所有未完成工作流，作为跨聊天任务恢复入口（内部只读原语）。

    只读扫描 outputs/*/workflows/*/state.json；不推进、不提交、不修改状态。
    project 可选：给出时只扫描指定项目；不提供时扫描全部项目。
    """
    rows = _active_workflow_records(None if workflow_ids else project, workflow_ids)
    if not rows:
        scope = f"项目 {project}" if project and not workflow_ids else "当前会话焦点" if workflow_ids else "全部项目"
        return f"暂无未完成工作流（范围：{scope}）"
    lines = ["== 未完成工作流（只读恢复清单） =="]
    for r in rows:
        lines.append(
            f"  {r['wf_id']} | project={r['project']} | template={r['template']} | "
            f"status={r['status']} | progress={r['progress']} | "
            f"current={r['current_step']}/{r['current_status']} | job={r['job_id'] or '-'} | "
            f"auto_submit={r['auto_submit']} | rev={r['revision']}"
        )
    lines.append("下一步：仅一个候选时可继续；多个候选必须先按 wf_id/project 选择，再调用 advance_workflow（可带 expected_revision 做 CAS）。")
    return "\n".join(lines)


def startup_recovery_summary(project: Optional[str] = None,
                             workflow_ids: Optional[list[str]] = None) -> str:
    """按作用域生成恢复摘要；默认全局仅供显式控制台查询使用。"""
    rows = _active_workflow_records(None if workflow_ids else project, workflow_ids)
    if not rows:
        return "启动恢复：未发现未完成工作流。"
    lines = [f"启动恢复：发现 {len(rows)} 个未完成工作流；未自动提交或推进。"]
    for r in rows:
        lines.append(
            f"- {r['project']} / {r['wf_id']}：{r['progress']}，"
            f"当前 {r['current_step']}({r['current_status']})，"
            f"作业 {r['job_id'] or '未提交'}"
        )
    return "\n".join(lines)


def _mentioned_workflows(request: str, rows: list[dict]) -> list[dict]:
    """从已发现的记录中做显式、边界敏感的文本寻址。"""
    text = request or ""
    matched = []
    for record in rows:
        wf = str(record.get("wf_id") or "")
        project = str(record.get("project") or "")
        wf_hit = bool(wf and re.search(r"(?<![A-Za-z0-9])" + re.escape(wf) +
                       r"(?![A-Za-z0-9])", text, re.I))
        project_hit = bool(project and re.search(r"(?<![A-Za-z0-9])" + re.escape(project) +
                            r"(?![A-Za-z0-9])", text, re.I))
        if wf_hit or project_hit:
            matched.append(record)
    return matched


def route_workflow_request(request: str = "", project: Optional[str] = None,
                           wf_id: Optional[str] = None,
                           workflow_ids: Optional[list[str]] = None) -> dict:
    """安全解析“继续/查看状态”类请求，返回选择结果，不执行推进。

    显式写在当前消息里的 workflow ID/项目名优先于历史 session 焦点；
    其次才使用调用方明确传入的 wf_id/project 或唯一 foreground 候选。
    当显式文本跨越当前 session 作用域时，允许从全局只读任务索引解析，
    但永远不按 mtime 猜测目标。返回 ``selected``/``choose``/``none``。
    """
    scoped_rows = _active_workflow_records(None if workflow_ids else project, workflow_ids)
    addressed = _mentioned_workflows(request, scoped_rows)
    # 明确写出目标即可跨 session 激活定向读取；不把全局结果用于裸控制词。
    if not addressed and request:
        # 这是显式文本寻址的第二次尝试，不能被旧 session project 截断；
        # 若仍未命中，后续只使用原有 scoped_rows，不做全局回退选择。
        global_rows = _active_workflow_records(None)
        addressed = _mentioned_workflows(request, global_rows)
    if len(addressed) == 1:
        return {"action": "selected", "reason": "explicit_text_target", "workflow": addressed[0]}
    if len(addressed) > 1:
        return {"action": "choose", "reason": "multiple_text_targets", "candidates": addressed,
                "message": "消息命中了多个工作流，请提供完整 wf_id 后再继续。"}

    if wf_id:
        exact = [r for r in scoped_rows if r["wf_id"] == wf_id]
        if exact:
            return {"action": "selected", "reason": "explicit_wf_id", "workflow": exact[0]}
        return {"action": "none", "reason": "wf_id_not_found", "wf_id": wf_id}

    rows = scoped_rows
    if project:
        project_rows = [r for r in rows if r.get("project") == project]
        if project_rows:
            rows = project_rows
    if len(rows) == 1:
        reason = "single_project_candidate" if project else "single_active_candidate"
        return {"action": "selected", "reason": reason, "workflow": rows[0]}
    if len(rows) > 1:
        return {"action": "choose", "reason": "multiple_active_candidates", "candidates": rows,
                "message": "发现多个未完成工作流，请提供 wf_id 或 project 后再继续。"}
    return {"action": "none", "reason": "no_active_workflow", "message": "暂无可继续的未完成工作流。"}


def list_workflows(project: str) -> str:
    """列出某项目下的全部工作流概要（存储层辅助函数，非 MCP 工具）。

    只读扫描 outputs/<project>/workflows/*/state.json；
    目录缺失或个别 state.json 损坏时跳过对应条目，不抛异常。
    """
    root = _wf_root(project)
    if not os.path.isdir(root):
        return f"（项目 {project} 下暂无工作流）"
    lines = [f"== 项目 {project} 的工作流 =="]
    found = 0
    for d in sorted(os.listdir(root)):
        sp = os.path.join(root, d, "state.json")
        if not os.path.isfile(sp):
            continue
        try:
            with open(sp, "r", encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            continue  # 损坏条目跳过，不影响其余列举
        done = sum(1 for s in st.get("steps", []) if s.get("status") == "done")
        lines.append(
            f"  {st.get('wf_id', d)} · {st.get('template', '?')} · "
            f"{st.get('status', '?')} · {done}/{len(st.get('steps', []))} · 创建于 {st.get('created', '?')}"
        )
        found += 1
    if not found:
        return f"（项目 {project} 下暂无工作流）"
    return "\n".join(lines)


# ==================== 步骤类型处理器（签名统一 (state, step) -> 进展文本） ====================

def _step_index(state: dict, step: dict) -> int:
    """定位 step 在 steps 列表中的下标（兜底返回当前指针）。"""
    for i, s in enumerate(state["steps"]):
        if s is step:
            return i
    return state["current"]


def _step_local_calc(state: dict, step: dict) -> str:
    """local_calc：纯本地轻量步骤，直接置 done。

    特例：步骤名为 formation_energy 且工作流参数提供了 E_O2 时，
    从已完成步骤的 key_results 收集 toten_eV 计算形成能
    E_f = E_def − E_perfect + 0.5*E_O2（首个含 toten 的步骤视为母相
    参考 E_perfect，最后一个视为缺陷/子体系 E_def）；
    引用不足两个则写明缺数据并照样放行 done（不阻塞流程）。
    其余情形一律 key_results={"demo": "ok"}。
    """
    params = state.get("params") or {}
    if step["name"] == "formation_energy" and "E_O2" in params:
        e_o2 = float(params["E_O2"])
        refs = [  # [(步骤名, toten)] 按步骤顺序收集
            (s["name"], float(s["key_results"]["toten_eV"]))
            for s in state["steps"]
            if s["status"] == "done" and "toten_eV" in s.get("key_results", {})
        ]
        if len(refs) >= 2:
            e_perfect, e_def = refs[0][1], refs[-1][1]
            e_f = e_def - e_perfect + 0.5 * e_o2
            step["key_results"] = {
                "formation_energy_eV": round(e_f, 6),
                "e_def_eV": e_def,
                "e_perfect_eV": e_perfect,
                "e_o2_eV": e_o2,
            }
            step["status"] = "done"
            step["note"] = (
                f"E_f={e_f:.4f} eV = E_def({refs[-1][0]}) - "
                f"E_perfect({refs[0][0]}) + 0.5*E_O2"
            )
            return f"[{step['name']}] 形成能计算完成: E_f = {e_f:.4f} eV"
        step["status"] = "done"
        step["note"] = (
            f"缺少参考能量：需要至少 2 个含 toten_eV 的已完成步骤，实际 {len(refs)} 个；"
            "跳过形成能计算，照样放行"
        )
        return f"[{step['name']}] 缺少参考能量数据，已跳过形成能计算（不阻塞）"

    # 普通演示路径
    if step["name"] == "formation_energy":
        step["note"] = "未提供参数 E_O2，按演示步骤处理"
    step["key_results"] = {"demo": "ok"}
    step["status"] = "done"
    return f"[{step['name']}] 本地计算完成（演示）"


def _vasp_prepare(state: dict, step: dict, incar_text: str, label: str) -> str:
    """vasp 类步骤 pending 态：在步骤目录生成输入集，转入 waiting_submit。

    POSCAR 取舍：params._poscar_validated_text 存在（S5 结构注入）→ 用真实结构；
    否则回退 NaCl 占位结构（auto_submit 护栏将拦截其上集群）。
    """
    d = _step_dir(state["wf_id"], state["project"], _step_index(state, step), step["name"])
    os.makedirs(d, exist_ok=True)
    real_poscar = (state.get("params") or {}).get("_poscar_validated_text") or ""
    poscar_final = real_poscar or _PLACEHOLDER_POSCAR
    for fname, text in (("INCAR", incar_text), ("KPOINTS", _KPOINTS_GAMMA),
                        ("POSCAR", poscar_final)):
        with open(os.path.join(d, fname), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    src = "真实结构" if real_poscar else "占位结构"
    step["status"] = "waiting_submit"
    step["note"] = f"输入目录: {d}（{src}）；提交后把 OUTCAR 放回本目录再 advance"
    tail = ("已注入真实结构，可 auto_submit 直提集群" if real_poscar
            else "请人工提交后把 OUTCAR 放回该目录，再调 advance_workflow 结算")
    return f"[{step['name']}] 已生成 {label} 输入集(INCAR/KPOINTS/POSCAR·{src}): {d}\n       {tail}"


def _vasp_settle(state: dict, step: dict) -> str:
    """vasp 类步骤 waiting_submit 态：查 OUTCAR 结算；无产物时按 params.auto_submit 尝试自动提交。"""
    d = _step_dir(state["wf_id"], state["project"], _step_index(state, step), step["name"])
    outcar = os.path.join(d, "OUTCAR")
    if not os.path.isfile(outcar):
        # 幂等护栏：本步骤已提交过集群，安心等结果回填（防止重复 qsub）
        if step.get("submitted_job"):
            return (f"[{step['name']}] 已提交作业 {step['submitted_job']}，"
                    f"仍在等待 OUTCAR 回填（{d}）")
        params = state.get("params") or {}
        if params.get("auto_submit"):
            return _auto_submit_step(state, step, d)
        return (f"[{step['name']}] 未发现 OUTCAR（{d}），保持 waiting_submit，"
                "继续等待人工提交")
    with open(outcar, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    m = _TOTEN_RE.search(text)
    if not m:
        step["note"] = "OUTCAR 已存在但未能解析出 TOTEN 行，请检查文件内容"
        return f"[{step['name']}] OUTCAR 无法解析 TOTEN，保持 waiting_submit"
    toten = float(m.group(1))
    step["key_results"] = {"toten_eV": toten}
    step["status"] = "done"
    step["note"] = f"已从 OUTCAR 结算 TOTEN = {toten} eV"
    return f"[{step['name']}] OUTCAR 结算完成: TOTEN = {toten} eV"


def _auto_submit_step(state: dict, step: dict, step_dir: str) -> str:
    """params.auto_submit=True 且无 OUTCAR 时：调 jobs.submit_only 直提集群。

    幂等性依赖调用方先查 step['submitted_job']；成功即写入该字段。
    占位结构（POSCAR 标题含 '占位'）拒绝真机提交——真实结构注入前的护栏。
    """
    try:
        poscar_text = open(os.path.join(step_dir, "POSCAR"), encoding="utf-8").read()
        species = poscar_text.splitlines()[5].split()
    except (OSError, IndexError):
        return f"[{step['name']}] 自动提交失败：无法从 POSCAR 读取元素行"
    if "占位" in poscar_text.splitlines()[0]:
        return (f"[{step['name']}] auto_submit 拒绝：当前是占位结构；"
                "注入真实 POSCAR 后再开启（见 start_workflow params_json 待办）")

    try:
        from .jobs import submit_only
    except ImportError:  # pragma: no cover
        from matcalc.jobs import submit_only

    params = state.get("params") or {}
    idx = _step_index(state, step)
    job_name = f"{idx}_{step['name']}"
    ok, payload = submit_only(
        state["project"], step_dir,
        node=str(params.get("node", "master")),
        ppn=int(params.get("ppn", 8)),
        job_name=job_name,
        potcar_elements=",".join(species),
    )
    if not ok:
        step["note"] = f"auto_submit 失败：{payload[:120]}"
        return f"[{step['name']}] 自动提交失败：{payload}"
    step["submitted_job"] = payload
    step["note"] = f"已自动提交 {payload} @ {params.get('node', 'master')}；等待 OUTCAR 回填"
    return (f"[{step['name']}] 已自动提交: {payload} "
            f"(ppn={params.get('ppn', 8)})；后续 advance 将幂等等待结果")


def _vasp_flow(state: dict, step: dict, incar_text: str, label: str) -> str:
    """vasp 类步骤统一流转：pending → 备输入；waiting_submit → 查产物。"""
    if step["status"] == "pending":
        return _vasp_prepare(state, step, incar_text, label)
    if step["status"] == "waiting_submit":
        return _vasp_settle(state, step)
    return f"[{step['name']}] 状态 {step['status']} 无需处理"


def _step_vasp_relax(state: dict, step: dict) -> str:
    """vasp_relax：结构弛豫（IBRION=2 / ISIF=3 / NSW=100），人工提交+回填 OUTCAR。"""
    return _vasp_flow(state, step, _INCAR_RELAX, "弛豫")


def _step_vasp_static_dos(state: dict, step: dict) -> str:
    """vasp_static_dos：静态自洽 + DOS(NSW=0 / LORBIT=11)，人工提交+回填 OUTCAR。"""
    return _vasp_flow(state, step, _INCAR_STATIC_DOS, "静态DOS")


def _step_report(state: dict, step: dict) -> str:
    """report：汇总已完成步骤的关键结果，经 organize.export_report 落盘报告。"""
    lines = [f"## 工作流 {state['wf_id']} 步骤结果汇总", ""]
    for i, s in enumerate(state["steps"]):
        if s["status"] == "done":
            krs = ", ".join(f"{k}={v}" for k, v in s["key_results"].items()) or "-"
            lines.append(f"- [{i}] {s['name']} ({s['type']}): {krs}")
    ret = organize.export_report(
        title=f"工作流报告 · {state['wf_id']}",
        sections="\n".join(lines),
        project=state["project"],
    )
    m = _SAVED_PATH_RE.search(ret)
    path = m.group(1).strip() if m else ""
    step["key_results"] = {"report_path": path}
    step["status"] = "done"
    step["note"] = ret.splitlines()[0] if ret else ""
    return f"[{step['name']}] 报告已导出: {path}"


def _step_note(state: dict, step: dict) -> str:
    """note：优先写 Vault 标准候选笔记；vault_note 缺失时降级自写简化片段。"""
    wf_id, project = state["wf_id"], state["project"]
    try:
        # 函数内经 importlib 惰性导入：生产环境行为与 from-import 一致，
        # 且测试可通过 sys.modules 置 None 可靠模拟 ImportError
        vault_note = importlib.import_module(".vault_note", __package__)
        ret = vault_note.save_result_note(
            project=project, source_job=wf_id, rows=[["工作流", wf_id]],
        )
        m = _SAVED_PATH_RE.search(ret)
        path = m.group(1).strip() if m else ""
        where = f"Vault 结果笔记: {path}"
    except ImportError:
        # 兜底：vault_note 不可用时，在工作流目录自写简化片段 note.md
        d = _wf_dir(wf_id, project)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "note.md")
        body = (
            f"# 工作流结果片段（简化版）\n\n"
            f"- 工作流: {wf_id}\n"
            f"- 模板: {state['template']}\n"
            f"- 项目: {project}\n"
            f"- 完成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- 说明: vault_note 模块不可用，此为本地简化片段\n"
        )
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        where = f"简化片段: {path}"
    step["key_results"] = {"note_path": path}
    step["status"] = "done"
    step["note"] = where
    return f"[{step['name']}] 笔记已保存（{where}）"


def _estimate_gap_from_doscar(path: str) -> float:
    """DOSCAR 简易带隙估计：在费米能两侧找 DOS 首超阈值的能量边界。

    阈值取窗口内最大 DOS 的 0.1%（对态密度绝对量纲不敏感）。
    金属（两侧无带隙区间）或解析失败返回 0.0，调用方标注为估计值。
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        if len(lines) < 8:
            return 0.0
        ef = float(lines[5].split()[0])
        n = int(lines[6].split()[0])
        energies, dos = [], []
        for ln in lines[7:7 + n]:
            tok = ln.split()
            if len(tok) >= 2:
                energies.append(float(tok[0]))
                dos.append(float(tok[1]))
        if len(energies) < 2:
            return 0.0
        win = [(e, d) for e, d in zip(energies, dos) if -8 <= e - ef <= 8]
        if not win:
            return 0.0
        thr = max(d for _, d in win) * 1e-3 or 1e-12
        v_edges = [e for e, d in win if e <= ef and d >= thr]
        c_edges = [e for e, d in win if e >= ef and d >= thr]
        if not v_edges or not c_edges:
            return 0.0  # 金属/半金属：费米能一侧恒有态
        gap = (c_edges[0] - v_edges[-1]) / 1.0
        return max(gap, 0.0)
    except (OSError, ValueError, IndexError):
        return 0.0


def _step_local_analysis(state: dict, step: dict) -> str:
    """local_analysis：从上一 VASP 步骤目录提取 TOTEN + DOS 图 + 带隙估计。

    读取 dos 步骤（类型 vasp_static_dos）的 OUTCAR（TOTEN）与 DOSCAR/vasprun.xml
    （绘图与带隙），结果写入 key_results；任何单件失败不阻塞整链，
    缺什么就在备注里如实说明。
    """
    prev = None
    for s in reversed(state["steps"][: state["current"]]):
        if s.get("type") in ("vasp_static_dos", "vasp_relax"):
            prev = s
            break
    if prev is None:
        return "错误：[E_PARAM] local_analysis 步骤缺少前置 VASP 步骤"
    i = state["steps"].index(prev)
    d = _step_dir(state["wf_id"], state["project"], i, prev["name"])
    results: dict = {}
    notes: list[str] = []

    # 1) TOTEN（OUTCAR，容错 static 段多行）
    outcar = os.path.join(d, "OUTCAR")
    if os.path.isfile(outcar):
        toten_m = _TOTEN_RE.findall(open(outcar, encoding="utf-8", errors="replace").read())
        if toten_m:
            results["TOTEN_eV"] = float(toten_m[-1])
        else:
            notes.append("OUTCAR 无 TOTEN 行")

    # 2) DOS 图 + 带隙（复用 plotting.plot_dos；失败降级为备注）
    try:
        from . import plotting as _plotting
        msg = _plotting.plot_dos(
            os.path.join(d, "vasprun.xml"), project=state["project"], save=True)
        m = re.search(r"DOS 图已生成: (\S+)", msg)
        if m:
            results["dos_png"] = m.group(1)
        notes.append(msg.splitlines()[0])
    except Exception as e:  # noqa: BLE001
        notes.append(f"DOS 绘图失败: {type(e).__name__}: {e}")

    # 3) 带隙（DOSCAR 估计值，与 DOS 图独立）
    doscar = os.path.join(d, "DOSCAR")
    if os.path.isfile(doscar):
        gap = _estimate_gap_from_doscar(doscar)
        results["gap_eV_est"] = round(gap, 4)
        notes.append("带隙为 DOSCAR 阈值估计值（0.0 表示金属/无法估计）")

    if not results:
        return (f"错误：[E_PARSE] {step['name']} 未能在 {d} 提取到任何结果"
                f"（缺 OUTCAR/vasprun.xml/DOSCAR）")
    step["key_results"] = results
    step["status"] = "done"
    step["note"] = "；".join(notes)
    return (f"[{step['name']}] 能量与 DOS 提取完成: TOTEN={results.get('TOTEN_eV', '?')} eV, "
            f"带隙(估)={results.get('gap_eV_est', '?')} eV, DOS 图={results.get('dos_png', '?')}")


# 类型 → 处理器注册表；新增步骤类型只需加一个同签名的函数
_STEP_HANDLERS: Dict[str, Callable[[dict, dict], str]] = {
    "local_calc": _step_local_calc,
    "vasp_relax": _step_vasp_relax,
    "vasp_static_dos": _step_vasp_static_dos,
    "local_analysis": _step_local_analysis,
    "report": _step_report,
    "note": _step_note,
}


# ==================== 视图渲染 ====================

def _render_steps(state: dict) -> str:
    """步骤列表视图：→ 标记当前指针位置。"""
    lines = []
    for i, s in enumerate(state["steps"]):
        mark = "→" if i == state["current"] else " "
        krs = ", ".join(f"{k}={v}" for k, v in s["key_results"].items()) or "-"
        lines.append(f" {mark} [{i}] {s['name']} ({s['type']}) · {s['status']} · 结果: {krs}")
        if s["note"]:
            lines.append(f"        备注: {s['note']}")
    return "\n".join(lines)


def _next_action(state: dict) -> str:
    """根据当前指针处的步骤状态给出下一步动作提示。"""
    if state["status"] == "done":
        return "工作流已全部完成，无需再推进（advance 为幂等调用）。"
    if state["current"] >= len(state["steps"]):
        return "所有步骤已完成，再次 advance 即收尾。"
    s = state["steps"][state["current"]]
    rev = int(state.get("revision", 0) or 0)
    call = (f"advance_workflow(wf_id='{state['wf_id']}', project='{state['project']}'"
            + (f", expected_revision={rev}" if rev else "") + ")")
    if s["status"] == "waiting_submit":
        idx = state["current"]
        d = _step_dir(state["wf_id"], state["project"], idx, s["name"])
        return f"人工提交 {s['name']} 后，把 OUTCAR 放回 {d}，再调 {call}"
    if s["status"] == "waiting_confirm":
        return f"人工核对 {s['name']} 无误后，带 confirm=True 调 {call}"
    return f"调用 {call} 继续推进 {s['name']}"


def _render_view(state: dict, headline: str) -> str:
    """统一的完整视图：标题行 + 元信息 + 步骤表 + 下一步提示。"""
    total = len(state["steps"])
    done = sum(1 for s in state["steps"] if s["status"] == "done")
    return "\n".join([
        headline,
        "",
        f"工作流 ID: {state['wf_id']}",
        f"项目: {state['project']} | 模板: {state['template']} | "
        f"状态: {state['status']} | 进度: {done}/{total} | "
        f"revision: {int(state.get('revision', 0) or 0)}",
        "",
        "== 步骤 ==",
        _render_steps(state),
        "",
        "== 下一步 ==",
        _next_action(state),
    ])


# ==================== 单步状态迁移 ====================

def _apply_one(state: dict, step: dict, confirm: bool) -> str:
    """对单个步骤做一次状态迁移，返回人类可读进展文本。

    - pending         → 按类型分发处理器（local/report/note 直接 done；
                         vasp 类转 waiting_submit）
    - waiting_submit  → 再次进入处理器查产物（OUTCAR 结算或继续等待）
    - waiting_confirm → 需 confirm=True 才置 done，否则仅提示
    """
    if step["status"] == "waiting_confirm":
        if not confirm:
            return (f"[{step['name']}] 该步骤处于人工确认态(waiting_confirm)；"
                    "确认无误请带 confirm=True 再调 advance_workflow")
        step["status"] = "done"
        step["note"] = ((step["note"] + "；" if step["note"] else "") + "人工确认通过").strip("； ")
        return f"[{step['name']}] 人工确认通过，标记完成"

    handler = _STEP_HANDLERS.get(step["type"])
    if handler is None:
        step["note"] = f"未知步骤类型: {step['type']}，无法推进"
        return f"错误：步骤 {step['name']} 类型未知({step['type']})，已暂停"
    return handler(state, step)


# ==================== 对外三个 MCP 工具 ====================

def start_workflow(template: str, project: str, params_json: Optional[Union[str, dict]] = None) -> str:
    """【MCP 工具】按内置模板启动一个新的多步工作流，并立即准备第一步。

    内置模板（WF_TEMPLATES）：
    - smoke_local_chain : demo_calc(local_calc) → summary_report(report)
      → final_note(note)，三步全离线，用于验证状态机跑通；
    - nmo_parent_compare: parent_relax(vasp_relax) → parent_dos(vasp_static_dos)
      → formation_energy(local_calc) → compare_report(report)
      → result_note(note)，两步 VASP 需人工提交集群；
    - relax_dos_standard: relax(vasp_relax) → dos(vasp_static_dos)
      → extract(local_analysis) → summary_report(report) → final_note(note)，通用标准链。

    状态落盘于 outputs/<project>/workflows/<wf_id>/state.json，
    wf_id = "<template>_<unix秒>"；随后对第一步执行一次状态迁移
    （local_calc 直接完成；vasp 类生成 INCAR/KPOINTS/POSCAR 输入集并
    进入 waiting_submit 等待人工提交）。

    Args:
        template: 模板名，必须是 WF_TEMPLATES 中的键。
        project: 项目名，决定输出目录 outputs/<project>/workflows/。
        params_json: 可选 JSON 对象字符串或已解析的 JSON 对象，作为全工作流参数透传给各步骤。支持键：
            - "E_O2": <float> —— formation_energy 步骤的氧参考化学势；
            - "auto_submit": true —— vasp 步骤就绪后自动提交集群；
            - "node"/"ppn": 自动提交目标节点与核数（默认 master/8）；
            - "poscar_path": "<路径>" 或 "poscar_text": "<POSCAR 全文>" ——
              【S5 结构注入】启动期即校验解析；两者同给时 text 优先。
              注入后所有 vasp 步骤使用真实结构，auto_submit 的占位护栏自动放行。
            示例: '{"E_O2": 2.0, "auto_submit": true, "ppn": 8}'

    Returns:
        成功：启动摘要 + 步骤列表视图（→ 标记当前步）+ 下一步动作提示，
        其中含 "工作流 ID: <wf_id>" 一行供后续调用引用。
        失败：以 "错误：" 开头的提示——未知模板 / params_json 非法 JSON
        或不是 JSON 对象；此时不产生任何文件。
    """
    if template not in WF_TEMPLATES:
        avail = ", ".join(sorted(WF_TEMPLATES))
        return f"错误：[E_PARAM] 未知模板 '{template}'；可用模板: {avail}"
    params: dict = {}
    if params_json:
        if isinstance(params_json, dict):
            params = dict(params_json)
        elif isinstance(params_json, str):
            try:
                parsed = json.loads(params_json)
            except (TypeError, ValueError) as e:
                return f"错误：[E_PARSE] params_json 不是合法 JSON（{e}）；示例: '{{\"E_O2\": 2.0}}'"
            if not isinstance(parsed, dict):
                return "错误：[E_PARAM] params_json 需为 JSON 对象；示例: '{\"E_O2\": 2.0}'"
            params = parsed
        else:
            return "错误：[E_PARAM] params_json 需为 JSON 对象或 JSON 字符串；示例: '{\"E_O2\": 2.0}'"

    # 真实结构注入（S5）：poscar_path / poscar_text 双通道，启动期即校验。
    # 验证后的文本归一存入 params["_poscar_validated_text"]（随 state.json 落盘），
    # _vasp_prepare 用它替换占位结构——auto_submit 的占位护栏随即自然放行。
    if "poscar_text" in params or "poscar_path" in params:
        if "poscar_text" in params:
            cand = str(params["poscar_text"])
            try:
                _Structure.from_str(cand, fmt="poscar")
                species_line = cand.splitlines()[5].split()
            except Exception as e:  # noqa: BLE001
                return f"错误：[E_PARSE] poscar_text 无法解析为 POSCAR：{e}"
        else:
            p = os.path.expanduser(str(params["poscar_path"]))
            if not os.path.isfile(p):
                return f"错误：[E_PARAM] poscar_path 不存在：{p}"
            cand = open(p, encoding="utf-8", errors="replace").read()
            try:
                _Structure.from_str(cand, fmt="poscar")
                species_line = cand.splitlines()[5].split()
            except Exception as e:  # noqa: BLE001
                return f"错误：[E_PARSE] poscar_path 文件内容无法解析为 POSCAR（{p}）：{e}"
        if len(species_line) < 1 or not all(x.isalpha() for x in species_line):
            return (f"错误：[E_PARSE] POSCAR 第 6 行不是合法元素行：{species_line}——"
                    "VASP5 格式需形如 'Na Cl'")
        params["_poscar_validated_text"] = cand          # 单一真源：随 state 落盘供各步骤取用
        params["_poscar_source"] = ("inline-text" if "poscar_text" in params
                                    else os.path.abspath(os.path.expanduser(str(params["poscar_path"]))))
        params.pop("poscar_text", None)                  # 归一化：原键不重复留存大文本
        params.pop("poscar_path", None)

    wf_id = f"{template}_{int(time.time())}"
    state = {
        "schema_version": SCHEMA_VERSION,
        "wf_id": wf_id,
        "template": template,
        "project": project,
        "status": "running",           # running | done
        "revision": 0,                 # _save_state 落盘时 +1
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "params": params,              # 全工作流参数（来自 params_json）
        "current": 0,                  # 当前步骤下标；收尾时等于 len(steps)
        "steps": [
            {"name": s["name"], "type": s["type"],
             "status": "pending", "key_results": {}, "note": ""}
            for s in WF_TEMPLATES[template]
        ],
    }
    _save_state(state)
    first_msg = _apply_one(state, state["steps"][0], confirm=False)  # prepare 第一步
    _save_state(state)
    _emit_wf_event("workflow.started", state, step=state["steps"][0].get("name"),
                   note=first_msg)
    src_note = (f"；结构来源: {params.get('_poscar_source')}" if params.get("_poscar_source")
                else "")
    return _render_view(state, f"工作流已启动（第一步：{first_msg}{src_note}）")


def advance_workflow(wf_id: str, project: str, confirm: bool = False,
                     auto_submit: Optional[bool] = None,
                     expected_revision: Optional[int] = None) -> str:
    """【MCP 工具】幂等地推进指定工作流：从当前指针起尽量往前走，遇人工介入即停。

    推进规则（对当前指针处的步骤做一次迁移）：
    - pending        → 执行：local_calc/report/note 直接 done；
                       vasp 类生成输入集转 waiting_submit；
    - waiting_submit → 检查步骤目录是否出现 OUTCAR：有则解析 TOTEN 存入
                       key_results 并置 done；无则保持等待并提示；
                       若 params.auto_submit 开启且尚未提交过，将自动 qsub；
    - waiting_confirm→ 需 confirm=True 才置 done，否则仅提示等待确认；
    - done           → 前移指针并继续执行下一步的推进逻辑。
    以上自动级联，直到停在 waiting_submit/waiting_confirm 或全部完成；
    全部完成后置 status="done" 并输出总结。重复调用安全幂等：已完成
    的工作流直接返回摘要，不产生任何副作用；自动提交有 submitted_job
    幂等护栏，不会重复 qsub。

    Args:
        wf_id: 工作流 id（start_workflow 返回中的 "工作流 ID:" 行）。
        project: 项目名，必须与启动时一致（决定查找目录）。
        confirm: 仅对 waiting_confirm 状态的步骤有意义；True 表示人工
            确认通过、允许标记完成。
        auto_submit: 三态开关（持久化进 params）。True=后续 vasp 步骤在
            输入就绪时自动提交集群（node/ppn 取自 params）；False=关闭；
            缺省 None=维持现状。
        expected_revision: 可选 CAS。给定时必须等于当前 state.revision，
            否则拒绝本次推进（防止基于陈旧快照写入）。

    Returns:
        成功：本次推进记录 + 实时步骤视图 + 下一步动作提示；
        工作流收尾时附 "全部步骤完成" 总结。
        失败：以 "错误：" 开头（未找到工作流 / revision CAS 失败）。
    """
    state = _load_state(wf_id, project)
    if state is None:
        return (f"错误：[E_PARAM] 未找到工作流 '{wf_id}'（project='{project}'）；"
                "可用 list_workflows(project) 核对已有工作流")
    if expected_revision is not None:
        try:
            from . import session_binding as _sb
        except ImportError:  # pragma: no cover
            from matcalc import session_binding as _sb
        cas = _sb.check_revision(state, expected_revision)
        if not cas.get("ok"):
            return cas.get("error", "错误: [E_PARAM] revision CAS 失败")
    if state["status"] == "done":
        # 幂等出口：不再触碰磁盘上的任何产物
        return _render_view(state, "工作流已完成（本次为幂等调用，无副作用）")
    if auto_submit is not None:
        state.setdefault("params", {})["auto_submit"] = bool(auto_submit)

    log: List[str] = []
    guard = 0
    guard_max = 4 * len(state["steps"]) + 8  # 防御性护栏，正常逻辑触达不到
    while state["current"] < len(state["steps"]):
        guard += 1
        if guard > guard_max:
            return "错误：推进循环异常终止，请检查 state.json 是否被外部改动"
        step = state["steps"][state["current"]]
        if step["status"] == "done":
            state["current"] += 1        # 当前步已完成 → 前移并推进下一步
            continue
        log.append(_apply_one(state, step, confirm))
        if step["status"] == "done":
            continue                     # 本步刚完成 → 回到循环头继续前移
        break                            # 停在等待人工动作的状态
    if state["current"] >= len(state["steps"]):
        state["current"] = len(state["steps"])
        state["status"] = "done"         # 收尾
    _save_state(state)
    _emit_wf_event(
        "workflow.done" if state["status"] == "done" else "workflow.advanced",
        state,
        step=state["steps"][state["current"] - 1].get("name") if state["current"] else None,
        log=("\n".join(log) if log else None),
    )

    head = "== 本次推进 ==\n" + ("\n".join(log) if log else "（无可执行动作）")
    if state["status"] == "done":
        head += "\n✔ 全部步骤完成，工作流收尾。关键结果见各步骤 key_results 与 reports/ 产物。"
    return _render_view(state, head)


def workflow_status(wf_id: str, project: str) -> str:
    """【MCP 工具】只读查看工作流当前状态（绝不产生副作用）。

    展示：整体状态与进度、逐步骤的类型/状态/关键结果/备注（→ 标记当前
    指针）、以及下一步建议动作。不创建目录、不改任何文件。

    Args:
        wf_id: 工作流 id。
        project: 项目名，必须与启动时一致。

    Returns:
        成功：格式化状态视图文本。
        失败：以 "错误：" 开头（未找到对应工作流）。
    """
    state = _load_state(wf_id, project)
    if state is None:
        return f"错误：[E_PARAM] 未找到工作流 '{wf_id}'（project='{project}'）；可用 list_workflows(project) 核对"
    return _render_view(state, "工作流状态（只读视图）")


# 面向 main.py 注册 MCP 工具的导出清单
# list_active_workflows 是内部恢复/路由原语，不新增 MCP 工具，保持 49 工具契约。
TOOLS = [start_workflow, advance_workflow, workflow_status]
