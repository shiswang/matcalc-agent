"""Materials Project 对接回归（全离线：无 key / guide / 模板与步骤类型）。"""
from server.matcalc import materials_project as mp
from server.matcalc import workflows as mw


def test_fetch_mp_structure_without_key(monkeypatch):
    monkeypatch.delenv("MP_API_KEY", raising=False)
    monkeypatch.delenv("MAPI_KEY", raising=False)
    out = mp.fetch_mp_structure("mp-22862")
    assert out.startswith("错误")
    assert "MP_API_KEY" in out


def test_mp_workflow_guide_topics():
    all_txt = mp.mp_workflow_guide("all")
    assert "fetch_mp_structure" in all_txt
    assert "mp_relax_static" in all_txt
    assert "Maker" in all_txt
    for topic in ("structure", "relax", "electronic", "elastic", "makers", "settings"):
        out = mp.mp_workflow_guide(topic)
        assert out and not out.startswith("错误")
    assert mp.mp_workflow_guide("nope").startswith("错误")


def test_mp_relax_static_template_registered():
    assert "mp_relax_static" in mw.WF_TEMPLATES
    names = [s["name"] for s in mw.WF_TEMPLATES["mp_relax_static"]]
    assert names[0] == "relax" and "static_dos" in names


def test_mp_relax_band_template_and_handlers():
    assert "mp_relax_band" in mw.WF_TEMPLATES
    types = [s["type"] for s in mw.WF_TEMPLATES["mp_relax_band"]]
    assert "vasp_static" in types and "vasp_band" in types
    for h in ("vasp_static", "vasp_band"):
        assert h in mw._STEP_HANDLERS


def test_mp_band_kpoints_from_poscar():
    from pymatgen.core import Lattice, Structure

    from server.matcalc.structures import _to_vasp5_poscar

    st = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    k = mw._band_kpoints_from_poscar(_to_vasp5_poscar(st))
    assert k and len(k.splitlines()) >= 3


def test_mp_tools_registered():
    assert mp.TOOLS == [mp.fetch_mp_structure, mp.mp_workflow_guide]
