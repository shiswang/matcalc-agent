"""workflow auto_submit 接线回归（全离线：submit_only 经 monkeypatch 模拟）。"""
import json
import os

import pytest

from server.matcalc import jobs as jobs_mod
from server.matcalc import workflows as wf


@pytest.fixture()
def nmo_wf(clean_test_project):
    """启动双 vasp 步模板，指针停在 parent_relax 的 waiting_submit。"""
    out = wf.start_workflow(
        "nmo_parent_compare", project=clean_test_project,
        params_json=json.dumps({"E_O2": 4.9}),
    )
    assert "工作流 ID:" in out
    wf_id = out.split("工作流 ID:")[1].split()[0].strip()
    return wf_id, clean_test_project


def _step_dir(project: str, wf_id: str) -> str:
    state = wf._load_state(wf_id, project)
    return wf._step_dir(wf_id, project, state["current"], state["steps"][state["current"]]["name"])


def test_auto_submit_refuses_placeholder(nmo_wf):
    wf_id, proj = nmo_wf
    out = wf.advance_workflow(wf_id, proj, auto_submit=True)
    assert "占位结构" in out            # 护栏生效，不碰集群
    state = wf._load_state(wf_id, proj)
    assert state["params"]["auto_submit"] is True          # 开关已持久化
    assert not state["steps"][0].get("submitted_job")


def test_auto_submit_happy_path_and_idempotent(nmo_wf, monkeypatch):
    wf_id, proj = nmo_wf
    d = _step_dir(proj, wf_id)
    # 用真实感 NaCl POSCAR 替换占位结构（首行不含"占位"）
    open(os.path.join(d, "POSCAR"), "w", newline="\n").write(
        "NaCl rocksalt\n1.0\n5.64 0 0\n0 5.64 0\n0 0 5.64\nNa Cl\n4 4\ndirect\n"
        "0 0 0\n0.5 0.5 0\n0.5 0 0.5\n0 0.5 0.5\n"
    )
    calls = []

    def fake_submit(project, local_dir, node="master", ppn=8,
                    job_name=None, potcar_elements=None):
        calls.append((project, job_name, potcar_elements))
        return True, "9999.master"

    monkeypatch.setattr(jobs_mod, "submit_only", fake_submit)
    out = wf.advance_workflow(wf_id, proj, auto_submit=True)
    assert "已自动提交: 9999.master" in out
    assert calls == [(proj, "0_parent_relax", "Na,Cl")]   # potcar 序取自元素行

    # 二次推进：幂等护栏——不再调用 submit_only，也不再重复 qsub
    out2 = wf.advance_workflow(wf_id, proj)
    assert "9999.master" in out2 and "等待 OUTCAR" in out2
    assert len(calls) == 1


def test_auto_submit_off_keeps_manual_semantic(nmo_wf):
    wf_id, proj = nmo_wf
    out = wf.advance_workflow(wf_id, proj)               # 不开开关
    assert "继续等待人工提交" in out


def test_mp_relax_band_auto_submit_with_injected_poscar(clean_test_project, monkeypatch):
    """MP 模板 + 真实 POSCAR 注入 + auto_submit：relax 步应走 submit_only。"""
    from pymatgen.core import Lattice, Structure

    from server.matcalc.structures import _to_vasp5_poscar

    st = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    poscar = _to_vasp5_poscar(st)
    out = wf.start_workflow(
        "mp_relax_band",
        project=clean_test_project,
        params_json=json.dumps({
            "poscar_text": poscar,
            "auto_submit": True,
            "node": "master",
            "ppn": 8,
        }),
    )
    assert "工作流 ID:" in out
    wf_id = out.split("工作流 ID:")[1].split()[0].strip()
    calls = []

    def fake_submit(project, local_dir, node="master", ppn=8,
                    job_name=None, potcar_elements=None):
        calls.append((project, job_name, potcar_elements, node))
        return True, "7777.master"

    monkeypatch.setattr(jobs_mod, "submit_only", fake_submit)
    adv = wf.advance_workflow(wf_id, clean_test_project)
    assert "已自动提交: 7777.master" in adv
    assert len(calls) == 1
    assert "relax" in calls[0][1]
    # MP INCAR 应出现在步骤目录
    d = _step_dir(clean_test_project, wf_id)
    incar = open(os.path.join(d, "INCAR"), encoding="utf-8").read()
    assert "EDIFFG" in incar or "mp_relax" in incar
