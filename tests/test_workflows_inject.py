"""S5 结构注入回归：params_json 的 poscar_text/poscar_path 双通道 + 护栏联动。"""
import json
import os

import pytest

from server.matcalc import jobs as jobs_mod
from server.matcalc import workflows as wf


REAL_NACL = (
    "NaCl rocksalt real structure\n1.0\n"
    "5.64 0 0\n0 5.64 0\n0 0 5.64\nNa Cl\n1 1\ndirect\n"
    "0 0 0\n0.5 0.5 0\n"
)


@pytest.fixture()
def started(clean_test_project):
    out = wf.start_workflow("nmo_parent_compare", project=clean_test_project,
                            params_json=json.dumps({
                                "E_O2": 4.9, "auto_submit": True, "ppn": 8,
                                "poscar_text": REAL_NACL}))
    assert "工作流 ID:" in out and "inline-text" in out     # 来源标注可见
    wf_id = out.split("工作流 ID:")[1].split()[0].strip()
    return wf_id, clean_test_project


def test_inject_reaches_step_dir(started):
    wf_id, proj = started
    state = wf._load_state(wf_id, proj)
    d = wf._step_dir(wf_id, proj, state["current"], state["steps"][state["current"]]["name"])
    head = open(os.path.join(d, "POSCAR"), encoding="utf-8").read().splitlines()[0]
    assert head == REAL_NACL.splitlines()[0]               # 占位被真实结构替换
    assert state["params"]["_poscar_validated_text"]       # 归一化仓在
    assert "poscar_text" not in state["params"]            # 原键已清理


def test_inject_plus_auto_submit_passes_guard(started, monkeypatch):
    wf_id, proj = started
    monkeypatch.setattr(jobs_mod, "submit_only",
                        lambda *a, **k: (True, "7777.master"))
    out = wf.advance_workflow(wf_id, proj, auto_submit=True)
    assert "已自动提交: 7777.master" in out                # 占位护栏放行 → 直提


def test_inject_bad_text_rejected(clean_test_project):
    out = wf.start_workflow("nmo_parent_compare", project=clean_test_project,
                            params_json=json.dumps({"poscar_text": "not a poscar"}))
    assert out.startswith("错误：[E_PARSE] poscar_text")


def test_inject_missing_path_rejected(clean_test_project):
    out = wf.start_workflow("nmo_parent_compare", project=clean_test_project,
                            params_json=json.dumps({"poscar_path": "Z:/no/such.vasp"}))
    assert out.startswith("错误：[E_PARAM] poscar_path 不存在")


def test_inject_species_line_guard(clean_test_project):
    # 元素行含数字：pymatgen 拒解析在前（list index out of range 由计数失配引发），
    # 我们的自有元素行校验兜后——两者同属 E_PARSE 拒绝，此处锁定前缀契约
    bad = REAL_NACL.replace("Na Cl\n1 1", "Na1 Cl2\n1 1")
    out = wf.start_workflow("nmo_parent_compare", project=clean_test_project,
                            params_json=json.dumps({"poscar_text": bad}))
    assert out.startswith("错误：[E_PARSE]")


def test_inject_via_path(tmp_path, clean_test_project):
    p = tmp_path / "struct.vasp"
    p.write_text(REAL_NACL, encoding="utf-8")
    out = wf.start_workflow("nmo_parent_compare", project=clean_test_project,
                            params_json=json.dumps({"poscar_path": str(p)}))
    assert str(p).lower() in out.lower()                   # 来源回显为绝对路径
