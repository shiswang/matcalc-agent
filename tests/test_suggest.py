"""S4.1/S4.2 回归：结构质量报告 + U/磁性智能建议。"""
import re

from pymatgen.core import Lattice, Structure

from server.matcalc import analysis_ext as ax
from server.matcalc import suggest as sg


def _rocksalt(cation: str, anion: str, a: float) -> str:
    st = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(a), [cation, anion], [[0, 0, 0], [0.5, 0.5, 0.5]],
    )
    lines = [st.composition.formula, "1.0"]
    for row in st.lattice.matrix:
        lines.append(" ".join(f"{x:.8f}" for x in row))
    syms, counts = [], []
    for site in st:
        s = site.specie.symbol
        if syms and syms[-1] == s:
            counts[-1] += 1
        else:
            syms.append(s)
            counts.append(1)
    lines += [" ".join(syms), " ".join(map(str, counts)), "direct"]
    lines += [" ".join(f"{x:.8f}" for x in s.frac_coords) for s in st]
    return "\n".join(lines) + "\n"


NACL_564 = _rocksalt("Na", "Cl", 5.64)
NACL_570 = _rocksalt("Na", "Cl", 5.70)   # +1% 热膨胀（物理合理微扰）
NACL_700 = _rocksalt("Na", "Cl", 7.00)   # 极端膨胀：键按截断判据真实断裂
CAO = _rocksalt("Ca", "O", 4.81)


def _mn2o4_bixbyite_like() -> str:
    """两个相邻 Mn 的简易氧化物（触发 AFM 提醒）。"""
    lat = Lattice.cubic(8.0)
    species = ["Mn", "Mn", "O"] * 2
    coords = [[0, 0, 0], [0.31, 0, 0], [0.5, 0.5, 0.5], [0.75, 0.25, 0.1], [0.6, 0.6, 0.2], [0.15, 0.7, 0.35]]
    st = Structure(lat, species, coords)
    out_lines = ["Mn4O4-like test", "1.0"]
    for row in lat.matrix:
        out_lines.append(" ".join(f"{x:.6f}" for x in row))
    out_lines += ["Mn O", "4 4", "direct"]
    for c in coords:
        out_lines.append(" ".join(f"{x:.6f}" for x in c))
    # 上面的 species 与坐标顺序不一致——直接手写分组格式防误导：
    return (
        "Mn4O4-like test\n1.0\n"
        "8.0000000000 0.0000000000 0.0000000000\n"
        "0.0000000000 8.0000000000 0.0000000000\n"
        "0.0000000000 0.0000000000 8.0000000000\n"
        "Mn O\n4 4\ndirect\n"
        "0.0000000000 0.0000000000 0.0000000000\n"
        "0.3100000000 0.0000000000 0.0000000000\n"
        "0.5000000000 0.5000000000 0.5000000000\n"
        "0.7500000000 0.2500000000 0.1000000000\n"
        "0.5000000000 0.5000000000 0.0000000000\n"
        "0.6000000000 0.6000000000 0.2000000000\n"
        "0.1500000000 0.7000000000 0.3500000000\n"
        "0.2500000000 0.1500000000 0.7000000000\n"
    )


# ---------- analyze_structure ----------

def test_nacl_bond_length_and_cn():
    out = ax.analyze_structure(NACL_564)
    assert "结构质量报告" in out and "键长统计" in out
    # 元素对标签按字母序 → Cl-Na；岩盐最近邻 = a/2 = 2.820 Å
    assert "Cl-Na" in out
    assert re.search(r"2\.8[12]", out)
    # 多元体系配位数只数异种成键 → Na/Cl 均为标准岩盐 CN=6
    assert out.count("CN=6.00") == 2
    assert "Cl-Cl" not in out and "Na-Na" not in out
    assert "🟢" in out


def test_analyze_rejects_garbage():
    assert ax.analyze_structure("junk").startswith("错误")


# ---------- compare_structures ----------

def test_compare_volume_expansion():
    out = ax.compare_structures(NACL_564, NACL_570)     # +1% 物理合理膨胀
    # V 比例 ≈ +3.03%；键长 2.820→2.850，Δ=+0.03 Å
    assert "体积变化" in out
    assert re.search(r"\+3\.\d+%?", out)
    assert re.search(r"Δ\+0\.03\d*", out)
    assert "🟢 骨架稳定" in out


def test_compare_extreme_flags_bond_loss():
    out = ax.compare_structures(NACL_564, NACL_700)     # +24% 晶格：键判据性断裂
    assert "键断裂预警" in out
    assert "超出截断判据" in out
    assert "🔴" in out


# ---------- suggest_u ----------

def test_suggest_u_catio3():
    poscar = _rocksalt("Ca", "Ti", 3.80)   # 含 Ti 即可触发建议逻辑
    out = sg.suggest_u(poscar_text=poscar)
    assert "Ti(d)" in out and "推荐 U=4.5" in out
    assert 'ldau_u="Ti=4.5"' in out
    assert "免责" in out


def test_suggest_u_main_group_no_u():
    out = sg.suggest_u(poscar_text=NACL_564)
    assert "无需 DFT+U" in out


def test_suggest_u_formula_path():
    out = sg.suggest_u(formula="NaNiO2")
    assert "Ni(d)" in out and "6.2" in out       # NMO 锚点


# ---------- suggest_magnetism ----------

def test_magnetism_nonmagnetic():
    out = sg.suggest_magnetism(NACL_564)
    assert "ispin=1" in out


def test_magnetism_tm_with_afm_hint():
    out = sg.suggest_magnetism(_mn2o4_bixbyite_like())
    assert "ISPIN=2" in out
    assert 'magmom="' in out
    assert re.search(r"Mn≈5 μB", out)
    assert "AFM 提醒" in out                      # 同种 TM 近邻位共存


def test_anchors_precise():
    assert sg._U_TABLE["Mn"][0] == 4.0
    assert sg._U_TABLE["Ni"][0] == 6.2


# ---------- record_feedback 回流闭环 ----------

def test_record_feedback_roundtrip(tmp_path, monkeypatch):
    fake = tmp_path / "fb.json"
    monkeypatch.setattr(sg, "_feedback_path", lambda: str(fake))
    out = sg.record_feedback(kind="u", element="Zr", value=3.1,
                             source="user-confirmed", project="LiZrCl")
    assert out.startswith("已回流") and fake.exists()
    # 合并视图立即生效：基础表没有 Zr，回流后建议层可直接给出
    sug = sg.suggest_u(formula="ZrO2")
    assert "推荐 U=3.1" in sug and "用户确认回流" in sug


def test_record_feedback_magmom_override(tmp_path, monkeypatch):
    fake = tmp_path / "fb.json"
    monkeypatch.setattr(sg, "_feedback_path", lambda: str(fake))
    sg.record_feedback(kind="magmom", element="Ni", value=1.2)
    # 合并视图立即生效（基础表 Ni≈1.5 → 覆盖为 1.2）
    assert sg._magmom_merged()["Ni"] == 1.2
    base = dict(sg._MAGMOM_TABLE)
    assert base["Ni"] == 1.5        # 代码内基础表不被 sidecar 污染


def test_record_feedback_param_guard():
    assert sg.record_feedback(kind="bad", element="Ni", value=1.0).startswith("错误：[E_PARAM]")
    assert sg.record_feedback(kind="u", element="7", value=1.0).startswith("错误：[E_PARAM]")
    assert sg.record_feedback(kind="u", element="Ni", value=-3).startswith("错误：[E_PARAM]")
    assert sg.record_feedback(kind="u", element="Ni", value=99).startswith("错误：[E_PARAM]")
