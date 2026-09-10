"""Workflow 状态机 MVP 回归：冒烟链全程 / 幂等 / 报错分支 / VASP 人工结算（全离线）。

覆盖点：
- smoke_local_chain 从 start 到 status=done 的完整生命周期与产物落地；
- advance 幂等：done 后多推不报错、不重复产生副作用；
- 未知模板 / 未知 wf_id / 非法 params_json 的报错分支；
- vasp 步骤 waiting_submit → 人工放置假 OUTCAR → 结算 toten_eV；
- nmo 模板 start 后第一步即 waiting_submit；
- formation_energy 有/无参考数据两条路径；waiting_confirm 确认门；
- vault_note 缺失时的简化片段兜底。

纪律：测试用独立项目名 wf_test_proj，前后清理，绝不触碰既有项目数据。
"""
import re
import shutil
import sys
from pathlib import Path

import pytest

from server.matcalc import workflows as mw
from server.matcalc.common import OUTPUTS_DIR

PROJ = "wf_test_proj"


# ---------- fixtures 与小工具 ----------

@pytest.fixture()
def clean_wf():
    """测试专用项目目录：开始前清空、结束后删除。"""
    base = Path(OUTPUTS_DIR) / PROJ
    shutil.rmtree(base, ignore_errors=True)
    yield
    shutil.rmtree(base, ignore_errors=True)


def _extract_wfid(text: str) -> str:
    """从启动返回文本中提取 "工作流 ID:" 行的 id。"""
    m = re.search(r"工作流 ID:\s*(\S+)", text)
    assert m, f"返回文本中缺少工作流 ID 行:\n{text}"
    return m.group(1)


def _load(wf_id: str) -> dict:
    """按测试项目名加载 state.json。"""
    st = mw._load_state(wf_id, PROJ)
    assert st is not None, f"state.json 不存在: {wf_id}"
    return st


def _proj_dir(*parts) -> Path:
    """outputs/wf_test_proj/<parts> 路径。"""
    return Path(OUTPUTS_DIR).joinpath(PROJ, *parts)


# ---------- 冒烟链全程 ----------

def test_smoke_chain_full_run(clean_wf):
    out = mw.start_workflow("smoke_local_chain", PROJ)
    wf = _extract_wfid(out)
    st = _load(wf)
    assert st["schema_version"] == 1
    assert st["status"] == "running"
    # 第一步 local_calc 在启动时即完成
    assert st["steps"][0]["status"] == "done"
    assert st["steps"][0]["key_results"] == {"demo": "ok"}

    # 一次 advance 应级联完成 report/note 两步并收尾
    out2 = mw.advance_workflow(wf, PROJ)
    assert "全部步骤完成" in out2
    st = _load(wf)
    assert st["status"] == "done"
    assert all(s["status"] == "done" for s in st["steps"])
    assert st["current"] == len(st["steps"])

    # 产物真实落地：报告文件与 Vault 笔记文件均存在
    rp = st["steps"][1]["key_results"].get("report_path", "")
    np_ = st["steps"][2]["key_results"].get("note_path", "")
    assert rp and Path(rp).is_file(), rp
    assert np_ and Path(np_).is_file(), np_
    assert "report_" in Path(rp).name and "note_" in Path(np_).name


def test_advance_idempotent_after_done(clean_wf):
    wf = _extract_wfid(mw.start_workflow("smoke_local_chain", PROJ))
    mw.advance_workflow(wf, PROJ)  # 一次推完
    before = (_proj_dir("workflows", wf, "state.json")).read_text(encoding="utf-8")

    # 多推一次：不报错、状态文件逐字节不变（幂等）
    out = mw.advance_workflow(wf, PROJ)
    assert "幂等" in out
    after = (_proj_dir("workflows", wf, "state.json")).read_text(encoding="utf-8")
    assert before == after

    # 无重复副作用：报告与笔记各只有一份
    assert len(list(_proj_dir("reports").glob("report_*.md"))) == 1
    assert len(list(_proj_dir("reports").glob("note_*.md"))) == 1


def test_list_workflows_reports_entries(clean_wf):
    wf = _extract_wfid(mw.start_workflow("smoke_local_chain", PROJ))
    listing = mw.list_workflows(PROJ)
    assert wf in listing and "smoke_local_chain" in listing
    # 空项目名下应给出友好提示而非异常
    assert "暂无工作流" in mw.list_workflows("no_such_proj_for_wf")


# ---------- 报错分支 ----------

def test_params_object_accepted(clean_wf):
    out = mw.start_workflow("smoke_local_chain", PROJ, params_json={"auto_submit": False})
    assert "工作流 ID:" in out


def test_unknown_template_rejected(clean_wf):
    out = mw.start_workflow("no_such_tpl", PROJ)
    assert out.startswith("错误") and "未知模板" in out
    assert "smoke_local_chain" in out  # 提示里列出可用模板


def test_invalid_params_json_rejected(clean_wf):
    out = mw.start_workflow("smoke_local_chain", PROJ, params_json="{bad json")
    assert out.startswith("错误") and "params_json" in out


def test_unknown_wf_id_errors(clean_wf):
    o1 = mw.advance_workflow("ghost_42", PROJ)
    o2 = mw.workflow_status("ghost_42", PROJ)
    for out in (o1, o2):
        assert out.startswith("错误") and "未找到" in out


# ---------- nmo 模板与 vasp 人工结算 ----------

def test_nmo_start_first_step_waits_submit(clean_wf):
    out = mw.start_workflow("nmo_parent_compare", PROJ)
    wf = _extract_wfid(out)
    st = _load(wf)
    assert len(st["steps"]) == 5
    assert st["current"] == 0
    assert st["steps"][0]["status"] == "waiting_submit"
    assert "waiting_submit" in out
    # 输入集三件套已生成在步骤目录
    d0 = Path(mw._step_dir(wf, PROJ, 0, "parent_relax"))
    for fname in ("INCAR", "KPOINTS", "POSCAR"):
        assert (d0 / fname).is_file(), fname
    incar = (d0 / "INCAR").read_text(encoding="utf-8")
    assert "IBRION = 2" in incar and "ISIF = 3" in incar and "NSW = 100" in incar


def test_vasp_settle_then_full_nmo_chain(clean_wf):
    out = mw.start_workflow("nmo_parent_compare", PROJ, params_json='{"E_O2": 2.0}')
    wf = _extract_wfid(out)
    d0 = Path(mw._step_dir(wf, PROJ, 0, "parent_relax"))
    d1 = Path(mw._step_dir(wf, PROJ, 1, "parent_dos"))

    # 未提交 OUTCAR 时：连续两次 advance 都只提示等待（幂等，不重复生成输入）
    o1 = mw.advance_workflow(wf, PROJ)
    o2 = mw.advance_workflow(wf, PROJ)
    assert "等待" in o1 and "等待" in o2
    st = _load(wf)
    assert st["steps"][0]["status"] == "waiting_submit"
    assert sorted(p.name for p in d0.iterdir()) == ["INCAR", "KPOINTS", "POSCAR"]

    # 人工放置含 TOTEN 的假 OUTCAR → 结算 toten_eV ≈ -123.45，指针前移
    (d0 / "OUTCAR").write_text(
        "  free  energy   TOTEN  =        -123.45 eV\n", encoding="utf-8")
    mw.advance_workflow(wf, PROJ)
    st = _load(wf)
    assert st["steps"][0]["status"] == "done"
    assert st["steps"][0]["key_results"]["toten_eV"] == pytest.approx(-123.45)
    assert st["current"] == 1
    assert st["steps"][1]["status"] == "waiting_submit"  # 第二步已备好输入等提交

    # 第二步也结算 → 之后级联完成 formation/report/note 并收尾
    (d1 / "OUTCAR").write_text("  TOTEN  =     -100.00 eV\n", encoding="utf-8")
    out_final = mw.advance_workflow(wf, PROJ)
    st = _load(wf)
    assert st["status"] == "done"
    ef = st["steps"][2]["key_results"]
    expect = (-100.00) - (-123.45) + 0.5 * 2.0   # E_def − E_perfect + 0.5*E_O2
    assert ef["formation_energy_eV"] == pytest.approx(expect)
    assert "全部步骤完成" in out_final
    assert len(list(_proj_dir("reports").glob("report_*.md"))) == 1


def test_formation_energy_missing_refs_degrades(clean_wf):
    wf = _extract_wfid(mw.start_workflow("nmo_parent_compare", PROJ,
                                         params_json='{"E_O2": 2.0}'))
    # 外科手术式构造：前两步 done 但没有 toten 数据，指针指向 formation_energy
    st = _load(wf)
    st["steps"][0].update(status="done", note="测试直改")
    st["steps"][1].update(status="done", note="测试直改")
    st["current"] = 2
    mw._save_state(st)

    mw.advance_workflow(wf, PROJ)
    st = _load(wf)
    fe = st["steps"][2]
    assert fe["status"] == "done"                 # 缺数据照样放行，不阻塞
    assert "缺少" in fe["note"]
    assert "formation_energy_eV" not in fe["key_results"]
    assert st["status"] == "done"                 # 后续 report/note 级联照常收尾


# ---------- waiting_confirm 确认门 ----------

def test_waiting_confirm_gate(clean_wf):
    wf = _extract_wfid(mw.start_workflow("smoke_local_chain", PROJ))
    st = _load(wf)
    st["steps"][0]["status"] = "done"
    st["steps"][1]["status"] = "waiting_confirm"  # 模拟人工复核关卡
    mw._save_state(st)

    # 不带 confirm：仅提示，状态不变
    refuse = mw.advance_workflow(wf, PROJ)
    assert "confirm" in refuse
    assert _load(wf)["steps"][1]["status"] == "waiting_confirm"

    # 带 confirm=True：放行并级联收尾
    ok = mw.advance_workflow(wf, PROJ, confirm=True)
    st = _load(wf)
    assert st["status"] == "done"
    assert st["steps"][1]["note"].endswith("人工确认通过")
    assert "全部步骤完成" in ok


# ---------- vault_note 缺失时的兜底 ----------

def test_note_fallback_without_vault_note(clean_wf, monkeypatch):
    wf = _extract_wfid(mw.start_workflow("smoke_local_chain", PROJ))
    # 模拟 vault_note 模块不可用（sys.modules 中置 None → import 抛 ImportError）
    monkeypatch.setitem(sys.modules, "server.matcalc.vault_note", None)
    out = mw.advance_workflow(wf, PROJ)
    st = _load(wf)
    assert st["status"] == "done"
    fallback = _proj_dir("workflows", wf, "note.md")
    assert fallback.is_file(), out
    text = fallback.read_text(encoding="utf-8")
    assert wf in text and "工作流" in text
