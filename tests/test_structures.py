"""建模工具回归：七大原型 / 化学计量比校验 / 空间群校验 / 超胞 / 切面。"""
import pytest

from server.matcalc import structures as mc

# (化学式, 原型) —— 覆盖全部 7 种内置原型
PROTOS = [
    ("NaCl", "rocksalt"),
    ("ZnS", "zincblende"),
    ("CaTiO3", "perovskite"),
    ("CaF2", "fluorite"),
    ("Fe", "bcc"),
    ("Cu", "fcc"),
    ("Mg", "hcp"),
]


@pytest.mark.parametrize("composition,proto", PROTOS)
def test_seven_prototypes_build(composition, proto):
    out = mc.build_structure(composition, prototype=proto, save=False)
    assert out.startswith("请求化学式"), out[:200]
    assert "错误" not in out, out[:300]
    assert "## 结构摘要" in out
    assert "## POSCAR" in out


def test_wrong_stoichiometry_rejected():
    """rocksalt 是 AB 型，NaCl2 必须被拒（M1 已验证 Li2ZrCl6 同类报错）。"""
    out = mc.build_structure("NaCl2", prototype="rocksalt", save=False)
    assert out.startswith("错误"), out[:200]


def test_unparseable_formula():
    out = mc.build_structure("Xx2Yy99", prototype=None, save=False)
    assert out.startswith("错误")


def test_invalid_spacegroup():
    out = mc.build_structure("NaCl", spacegroup=999, save=False)
    assert out.startswith("错误")
    assert "空间群" in out


def test_parse_poscar_roundtrip(nacl_poscar_text):
    out = mc.parse_poscar(nacl_poscar_text)
    assert out.startswith("## 结构摘要")
    assert "NaCl" in out


def test_make_supercell_222(nacl_poscar_text):
    out = mc.make_supercell(nacl_poscar_text, 2, 2, 2)
    assert "超胞 2x2x2: 8 原子 → 64 原子" in out
    body = out.split("```")[1]
    lines_ = body.strip().splitlines()
    # VASP5 分组格式: 0 公式名 / 1 scale / 2-4 晶格 / 5 元素行 / 6 计数行
    assert lines_[0] == "NaCl2" or lines_[0].startswith("NaCl")
    assert lines_[5].split() == ["Na", "Cl"]
    assert lines_[6].split() == ["32", "32"]  # Na4Cl4 ×8 → 每元素 32


def test_cleave_surface_110(nacl_poscar_text):
    out = mc.cleave_surface(nacl_poscar_text, "1 1 0")
    assert "(1 1 0) 表面:" in out
    assert "对称端型" in out
    assert "```" in out  # 含 POSCAR 代码块


def test_cleave_surface_bad_miller(nacl_poscar_text):
    out = mc.cleave_surface(nacl_poscar_text, "1 2")
    assert out.startswith("错误")
    assert "三个整数" in out
