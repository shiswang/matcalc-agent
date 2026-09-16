"""MP 热力学工具回归：无 key 错误路径 + 反应式解析 + 注册。"""
from server.matcalc import mp_thermo as th
from server.matcalc import suggest


def test_thermo_requires_api_key(monkeypatch):
    monkeypatch.delenv("MP_API_KEY", raising=False)
    monkeypatch.delenv("MAPI_KEY", raising=False)
    for fn, args in (
        (th.mp_phase_diagram, ("Fe-O",)),
        (th.mp_reaction_energy, ("NaCl -> Na + 0.5 Cl2",)),
        (th.mp_interface_reactions, ("NaCl", "Fe")),
        (th.mp_pourbaix_diagram, ("Fe",)),
    ):
        out = fn(*args)
        assert out.startswith("错误") and "MP_API_KEY" in out


def test_parse_chemsys():
    assert th._parse_chemsys("Fe-O") == "Fe-O"
    assert th._parse_chemsys("LiFeO2") == "Fe-Li-O"


def test_reaction_parse_error_paths():
    # 无 key 时仍先做格式检查
    assert th.mp_reaction_energy("no arrow").startswith("错误")


def test_u_table_has_mp_like_coverage():
    merged = suggest._u_table_merged()
    for el in ("Ti", "Mn", "Fe", "Ni", "Zn", "Gd"):
        assert el in merged


def test_thermo_tools_registered():
    assert th.TOOLS == [
        th.mp_phase_diagram, th.mp_reaction_energy,
        th.mp_interface_reactions, th.mp_pourbaix_diagram,
    ]
