"""S5 通用标准链回归：relax_dos_standard 模板 + local_analysis 提取器。"""
import os

import pytest

from server.matcalc import workflows as wf


OUTCAR_TOTEN = "  free energy   TOTEN  =  -27.25 eV\n"


def _doscar(ef: float, nedos: int, rows: list[tuple[float, float]]) -> str:
    """构造 DOSCAR：6 行头（第 6 行含费米能）+ NEDOS 行 + 数据行。"""
    head = ["Na   Cl\n"] * 6
    head[5] = f"{ef:.6f}   100.0\n"
    body = "".join(f"{e:.4f} {d:.6f} 0.0 0.0 0.0\n" for e, d in rows)
    return "".join(head) + f"{nedos}\n" + body


def _fake_doscar_insulator(path: str):
    # 价带峰在 -1 eV、导带峰在 +1 eV，中间 DOS=0 → 带隙 ≈ 2 eV
    rows = []
    for i in range(41):
        e = -2.0 + 0.1 * i
        d = 1.0 if abs(e + 1.0) < 0.001 or abs(e - 1.0) < 0.001 else 0.0
        rows.append((e, d))
    with open(path, "w", encoding="utf-8") as f:
        f.write(_doscar(0.0, 41, rows))


def _fake_doscar_metal(path: str):
    # 全窗口恒定 DOS → 费米能两侧无带隙 → 0.0
    rows = [(e, 0.1) for e in (i * 0.1 - 2.0 for i in range(41))]
    with open(path, "w", encoding="utf-8") as f:
        f.write(_doscar(0.0, 41, rows))


class TestTemplate:
    def test_registered_with_five_steps(self):
        t = wf.WF_TEMPLATES["relax_dos_standard"]
        assert [s["name"] for s in t] == ["relax", "dos", "extract", "summary_report", "final_note"]
        assert [s["type"] for s in t] == [
            "vasp_relax", "vasp_static_dos", "local_analysis", "report", "note"]

    def test_start_message_lists_template(self, clean_test_project):
        out = wf.start_workflow("relax_dos_standard", project=clean_test_project)
        assert "工作流 ID:" in out and "relax" in out


class TestGapHeuristic:
    def test_insulator_gap_about_2ev(self, tmp_path):
        p = tmp_path / "DOSCAR"
        _fake_doscar_insulator(p)
        gap = wf._estimate_gap_from_doscar(str(p))
        assert 1.8 <= gap <= 2.2

    def test_metal_gap_zero(self, tmp_path):
        p = tmp_path / "DOSCAR"
        _fake_doscar_metal(p)
        assert wf._estimate_gap_from_doscar(str(p)) == 0.0

    def test_garbage_file_safe(self, tmp_path):
        p = tmp_path / "DOSCAR"
        p.write_text("junk", encoding="utf-8")
        assert wf._estimate_gap_from_doscar(str(p)) == 0.0


class TestFullChainOffline:
    def _run_to_dos(self, clean_test_project, monkeypatch):
        out = wf.start_workflow("relax_dos_standard", project=clean_test_project)
        wf_id = out.split("工作流 ID:")[1].split()[0].strip()
        state = wf._load_state(wf_id, clean_test_project)
        # relax 目录塞入 OUTCAR → 结算
        d0 = wf._step_dir(wf_id, clean_test_project, 0, "relax")
        with open(os.path.join(d0, "OUTCAR"), "w", encoding="utf-8") as f:
            f.write(OUTCAR_TOTEN)
        wf.advance_workflow(wf_id, clean_test_project)
        # dos 目录塞入 OUTCAR + DOSCAR + vasprun → 结算
        d1 = wf._step_dir(wf_id, clean_test_project, 1, "dos")
        with open(os.path.join(d1, "OUTCAR"), "w", encoding="utf-8") as f:
            f.write(OUTCAR_TOTEN)
        _fake_doscar_insulator(os.path.join(d1, "DOSCAR"))
        with open(os.path.join(d1, "vasprun.xml"), "w", encoding="utf-8") as f:
            f.write("<modeling/>")
        monkeypatch.setattr("server.matcalc.plotting.plot_dos",
                            lambda *a, **k: "DOS 图已生成: C:/fake/tdos.png\n内容: x")
        return wf_id, clean_test_project

    def test_chain_reaches_done_with_extracted_results(self, clean_test_project, monkeypatch):
        wf_id, proj = self._run_to_dos(clean_test_project, monkeypatch)
        msgs = [wf.advance_workflow(wf_id, proj) for _ in range(4)]  # 提取→报告→笔记→收尾
        joined = "\n".join(msgs)
        assert "TOTEN=-27.25" in joined and "带隙(估)=2.0" in joined
        state = wf._load_state(wf_id, proj)
        assert state["status"] == "done"
        ext = state["steps"][2]
        assert ext["key_results"]["TOTEN_eV"] == -27.25
        assert abs(ext["key_results"]["gap_eV_est"] - 2.0) < 0.3
        assert ext["key_results"]["dos_png"] == "C:/fake/tdos.png"

    def test_missing_artifacts_rejected(self, tmp_path, monkeypatch):
        # E_PARSE 防御分支经公开 API 不可达（dos 须有 TOTEN 才结算），
        # 故对处理器直接单测：前置 vasp 步骤目录全空 → 报 E_PARSE
        monkeypatch.setattr(wf, "_step_dir", lambda *a, **k: str(tmp_path))
        state = {
            "wf_id": "x", "project": "p", "current": 2,
            "steps": [
                {"name": "relax", "type": "vasp_relax", "status": "done"},
                {"name": "dos", "type": "vasp_static_dos", "status": "done"},
                {"name": "extract", "type": "local_analysis", "status": "pending"},
            ],
        }
        msg = wf._step_local_analysis(state, state["steps"][2])
        assert msg.startswith("错误：[E_PARSE]")
