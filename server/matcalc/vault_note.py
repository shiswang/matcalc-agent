"""计算结果 → Obsidian 标准笔记片段生成器。

把一次 VASP 计算的关键数据渲染成 Obsidian Flavored Markdown 片段，
落盘到 outputs/<project>/reports/note_<unix时间戳>.md，供人工搬运进 Vault。

设计要点：
- 状态固定 status: candidate（候选知识；未经核验不得晋升，见 OrbitOS 记忆分级规则）；
- 结构固定五段：YAML frontmatter / 计算摘要 / 参数链 / 复现指引 / 经验候选；
- 纯函数优先：render_result_note 只产文本不碰文件系统，save/export 才落盘；
- 表格单元格中的 '|' 与换行自动转义，防止破坏 Markdown 表格。

纪律：全离线；只写 outputs/ 下自己的产物，不改任何既有文件。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Optional, Sequence, Tuple

from .common import out_dir


# ---------- 内部小工具（不进 TOOLS） ----------

def _esc_cell(v: Any) -> str:
    """表格单元格安全化：换行转 <br>、竖线转 \\|，防止破坏 Markdown 表格。"""
    s = "" if v is None else str(v)
    s = s.replace("\r\n", "<br>").replace("\r", "<br>").replace("\n", "<br>")
    s = s.replace("|", "\\|")
    return s


def _yaml_str(s: Any) -> str:
    """YAML 双引号字符串（最小转义反斜杠与双引号），防止标题/作业号含特殊字符时破版。"""
    t = str(s).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{t}"'


def _bullets(items: Sequence[Any]) -> str:
    """序列 → '- ' bullet 多行文本。"""
    return "\n".join(f"- {i}" for i in items)


# ---------- 纯函数：渲染 ----------

def render_result_note(
    project: str,
    source_job: str,
    rows: Sequence[Tuple[Any, Any]],
    params_chain: Optional[Sequence[Any]] = None,
    wf_id: Optional[str] = None,
    extra_experience: Optional[Sequence[str]] = None,
) -> str:
    """渲染 Obsidian 结果笔记片段（纯函数，只返回文本，不落盘）。

    Args:
        project: 项目名；进入 title 与复现指引。
        source_job: 来源作业号，如 "3687.master"；写入 frontmatter 的 source_job。
        rows: [(量, 值), ...] 摘要行；量与值中的 '|' 与换行均自动转义防破表
            （量列同样处理是防御性的超集，规格只强制要求值列）。
        params_chain: 参数链（继承链路），逐条 bullet 输出；
            None 或空列表输出占位"（未提供）"。
        wf_id: 工作流 id；有则复现指引指向 workflows/<wf_id>/，
            否则指向 outputs/<project>/。
        extra_experience: 经验候选条目列表，逐条 bullet；
            缺省输出占位"（待补写；未经核验不晋升）"。

    Returns:
        完整 Markdown 片段文本（UTF-8、LF 行尾、结尾带换行）。
    """
    today = time.strftime("%Y-%m-%d")

    # --- YAML frontmatter：status 固定 candidate，tags 固定 candidate/result-note ---
    fm = (
        "---\n"
        f"title: {_yaml_str(f'{project} · 计算结果笔记')}\n"
        "type: result-note\n"
        "status: candidate\n"
        f"created: {today}\n"
        'project: "[[MatCalcAgent]]"\n'
        f"source_job: {_yaml_str(source_job)}\n"
        "tags:\n"
        "  - candidate\n"
        "  - result-note\n"
        "---\n"
    )

    # --- ## 计算摘要：两列表格，单元格转义防破表 ---
    tbl = ["| 量 | 值 |", "| --- | --- |"]
    for k, v in rows:
        tbl.append(f"| {_esc_cell(k)} | {_esc_cell(v)} |")
    summary = "\n".join(tbl)

    # --- ## 参数链 ---
    if params_chain:
        chain_txt = _bullets(params_chain)
    else:
        chain_txt = "（未提供）"

    # --- ## 复现指引：有 wf_id 指向 workflows/，否则指向 outputs/<project>/ ---
    if wf_id:
        repro = (
            f"- 工作流目录: workflows/{wf_id}/（含输入集与日志，可按原参数复跑）\n"
            f"- 备用本地目录: outputs/{project}/"
        )
    else:
        repro = (
            f"- 本地结果目录: outputs/{project}/\n"
            "- inputs/ 计算输入集 · results/ 解析产物 · reports/ 报告与本笔记"
        )

    # --- ## 经验候选：默认占位，未经核验不晋升 ---
    if extra_experience:
        exp_txt = _bullets(extra_experience)
    else:
        exp_txt = "（待补写；未经核验不晋升）"

    body = (
        f"## 计算摘要\n\n{summary}\n\n"
        f"## 参数链\n\n{chain_txt}\n\n"
        f"## 复现指引\n\n{repro}\n\n"
        f"## 经验候选\n\n{exp_txt}\n"
    )
    return fm + "\n" + body


# ---------- 落盘 ----------

def save_result_note(
    project: str,
    source_job: str,
    rows: Sequence[Tuple[Any, Any]],
    params_chain: Optional[Sequence[Any]] = None,
    wf_id: Optional[str] = None,
    extra_experience: Optional[Sequence[str]] = None,
) -> str:
    """渲染结果笔记并写入 outputs/<project>/reports/note_<unix时间戳>.md。

    目录经 common.out_dir(project, "report") 自动创建；
    同秒重名直接覆盖（与 export_report 的 report_<时间戳> 行为一致）。

    Args:
        参数含义同 render_result_note。

    Returns:
        形如 "已保存: <路径>" 的确认文本，附片段前 8 行预览。
    """
    note = render_result_note(
        project, source_job, rows,
        params_chain=params_chain, wf_id=wf_id, extra_experience=extra_experience,
    )
    path = os.path.join(out_dir(project, "report"), f"note_{int(time.time())}.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(note)
    head = "\n".join(note.splitlines()[:8])
    return f"已保存: {path}\n片段预览（前 8 行）:\n{head}"


# ---------- MCP 包装 ----------

def export_result_note(
    project: str,
    source_job: str,
    rows_json: str,
    params_chain_json: Optional[str] = None,
    wf_id: Optional[str] = None,
) -> str:
    """【MCP 工具】把一次计算的结果摘要写成 Obsidian 标准候选笔记并保存。

    笔记固定 status: candidate（未经核验不得晋升），结构为：
    YAML frontmatter → 计算摘要表格 → 参数链 → 复现指引 → 经验候选。

    Args:
        project: 项目名；决定落盘目录 outputs/<project>/reports/ 与笔记标题。
        source_job: 来源作业号字符串（如 "3687.master"）；写入 frontmatter 的 source_job 字段。
        rows_json: JSON 数组字符串，每项为 [量, 值] 两元素数组，
            如 '[["TOTEN","-27.25"],["带隙(eV)","5.18"]]'；
            量/值中的竖线与换行会自动转义防止破坏表格。
        params_chain_json: 可选 JSON 字符串数组（参数继承链），
            如 '["bulk-Si-relax","eos-scan","bands"]'；缺省时笔记记为（未提供）。
        wf_id: 可选工作流 id；有则复现指引指向 workflows/<wf_id>/，否则指向 outputs/<project>/。

    Returns:
        成功返回 "已保存: <路径>" 加片段前几行预览；
        rows_json / params_chain_json 解析失败或形状非法时返回以 "错误：" 开头的提示，
        此时不产生任何文件。
    """
    try:
        raw_rows = json.loads(rows_json)
    except (TypeError, ValueError) as e:
        return f"错误：rows_json 不是合法 JSON（{e}）；示例：'[[\"TOTEN\",\"-27.25\"]]'"

    try:
        raw_chain = json.loads(params_chain_json) if params_chain_json else None
    except (TypeError, ValueError) as e:
        return f"错误：params_chain_json 不是合法 JSON（{e}）；示例：'[\"scf\",\"dos\"]'"

    # 形状校验：rows 必须是 [[量, 值], ...]
    if not isinstance(raw_rows, list) or not all(
        isinstance(r, (list, tuple)) and len(r) == 2 for r in raw_rows
    ):
        return "错误：rows_json 需为 [[量, 值], ...] 形状的 JSON 数组；示例：'[[\"TOTEN\",\"-27.25\"]]'"
    rows = [(str(r[0]), r[1]) for r in raw_rows]

    if raw_chain is not None:
        if not isinstance(raw_chain, list):
            return "错误：params_chain_json 需为 JSON 字符串数组；示例：'[\"scf\",\"dos\"]'"
        params_chain: Optional[list[str]] = [str(x) for x in raw_chain]
    else:
        params_chain = None

    return save_result_note(project, source_job, rows, params_chain=params_chain, wf_id=wf_id)


# 面向 main.py 注册 MCP 工具的导出清单；render/save 为内部实现，不进 TOOLS。
TOOLS = [export_result_note]
