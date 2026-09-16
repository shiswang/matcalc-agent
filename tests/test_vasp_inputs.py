"""输入生成回归：INCAR 模板 / KPOINTS 网格 / POTCAR 拼接顺序 / 参数校验警告。"""
import math
import re
import shutil
from pathlib import Path

from pymatgen.io.vasp import Poscar

from server.matcalc import vasp_inputs as mc


def _expected_grid(poscar_text: str, density: float = 0.04) -> list[int]:
    """复算 KPOINTS 自动网格公式（与实现保持一致，锁定行为）。"""
    st = Poscar.from_str(poscar_text).structure
    return [max(1, int(math.ceil(2.0 * math.pi / (density * abc)))) for abc in st.lattice.abc]


def test_relax_defaults_and_metal_heuristic(nacl_poscar_text):
    out = mc.generate_vasp_inputs(nacl_poscar_text, calc_type="relax")
    assert "IBRION = 2" in out
    assert "ISIF = 3" in out
    assert "EDIFFG = -0.02" in out
    assert "ENCUT = 500" in out
    # Na 在金属元素表内 → 默认 ISMEAR=1 且无警告
    assert "ISMEAR = 1" in out
    g = _expected_grid(nacl_poscar_text)
    assert f"{g[0]} {g[1]} {g[2]}" in out  # KPOINTS 网格行
    assert "Monkhorst-Pack" in out


def test_static_defaults(nacl_poscar_text):
    out = mc.generate_vasp_inputs(nacl_poscar_text, calc_type="static")
    assert "NSW = 0" in out
    assert "LCHARG = .TRUE." in out
    assert "SIGMA = 0.05" in out


def test_ismear_override_triggers_metal_warning(nacl_poscar_text):
    out = mc.generate_vasp_inputs(nacl_poscar_text, calc_type="static", ismear=-5)
    assert "ISMEAR = -5" in out
    assert "不建议用于金属" in out


def test_insulator_ismear1_warning():
    """非金属体系显式 ISMEAR=1 → 给出提示警告（用 O2 分子样本）。"""
    p = Path(mc._OUTPUTS_DIR) / "NMO_NaBattery" / "inputs" / "mol_O2" / "POSCAR"
    if not p.exists():
        import pytest
        pytest.skip("缺少 mol_O2 样本")
    out = mc.generate_vasp_inputs(p.read_text(encoding="utf-8"), calc_type="static", ismear=1)
    assert "ISMEAR = 1" in out
    assert "更精确" in out


def test_dos_template(nacl_poscar_text):
    out = mc.generate_vasp_inputs(nacl_poscar_text, calc_type="dos")
    assert "LORBIT = 11" in out
    assert "NEDOS = 2000" in out


def test_bands_template(nacl_poscar_text):
    out = mc.generate_vasp_inputs(nacl_poscar_text, calc_type="bands")
    assert "ICHARG = 11" in out
    assert "两段" in out  # 两段式说明注释


def test_elastic_template(nacl_poscar_text):
    out = mc.generate_vasp_inputs(nacl_poscar_text, calc_type="elastic")
    assert "IBRION = 6" in out
    assert "NFREE = 4" in out


def test_potcar_concat_order(nacl_poscar_text):
    out = mc.generate_vasp_inputs(nacl_poscar_text, calc_type="static")
    i_na = out.index("POTCAR.Na")
    i_cl = out.index("POTCAR.Cl")
    assert i_na < i_cl  # 按 POSCAR 元素顺序拼接


def test_invalid_calc_type(nacl_poscar_text):
    out = mc.generate_vasp_inputs(nacl_poscar_text, calc_type="hfen")
    assert out.startswith("错误")
    assert "不支持的 calc_type" in out


def test_encut_out_of_range_warning(nacl_poscar_text):
    out = mc.generate_vasp_inputs(nacl_poscar_text, calc_type="static", encut=150)
    assert "ENCUT = 150" in out
    assert "超出常见范围" in out


def test_save_writes_four_files(nacl_poscar_text):
    out = mc.generate_vasp_inputs(nacl_poscar_text, calc_type="static", save=True)
    m = re.search(r"输入文件已保存到目录: (.+?)（", out)
    assert m, out[-300:]
    d = Path(m.group(1))
    try:
        for fname in ("INCAR", "KPOINTS", "POSCAR", "make_potcar.sh"):
            assert (d / fname).exists(), f"{fname} 未生成"
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------- 高级参数：+U / IVDW / MAGMOM / ISPIN（NMO 实战接口补齐） ----------

def _fence_poscar(composition: str, prototype: str) -> str:
    """离线构造样本结构并取出 POSCAR 文本。"""
    from server.matcalc import structures as mc_st

    out = mc_st.build_structure(composition, prototype=prototype, save=False)
    assert out.startswith("请求化学式"), out[:200]
    return out.split("## POSCAR\n```\n")[1].split("\n```")[0]


def test_ldau_block_perovskite_ti():
    poscar = _fence_poscar("CaTiO3", "perovskite")
    out = mc.generate_vasp_inputs(poscar, calc_type="static", ldau_u="Ti=4.5")
    assert "LDAU = .TRUE." in out
    assert "LDAUTYPE = 2" in out
    # 元素序无关断言：按实际 POSCAR 元素序构造期望向量
    syms = [el.symbol for el in Poscar.from_str(poscar).structure.composition.elements]
    exp_l = " ".join("2" if s == "Ti" else "-1" for s in syms)
    exp_u = " ".join("4.50" if s == "Ti" else "0.00" for s in syms)
    assert f"LDAUL = {exp_l}" in out
    assert f"LDAUU = {exp_u}" in out
    assert "LDAUJ = " + " ".join("0.00" for _ in syms) in out
    assert "LMAXMIX = 4" in out
    assert "+U(Dudarev): Ti=4.5 eV" in out


def test_ldau_l_override(nacl_poscar_text):
    out = mc.generate_vasp_inputs(
        nacl_poscar_text, calc_type="static", ldau_u="Na=1.0", ldau_l="Na=1",
    )
    syms = [el.symbol for el in Poscar.from_str(nacl_poscar_text).structure.composition.elements]
    exp_l = " ".join("1" if s == "Na" else "-1" for s in syms)
    assert f"LDAUL = {exp_l}" in out


def test_magmom_expansion_and_auto_ispin():
    poscar = _fence_poscar("MnO", "rocksalt")  # 常规胞 Mn4O4
    out = mc.generate_vasp_inputs(poscar, calc_type="relax", magmom="Mn=5")
    assert "ISPIN = 2" in out
    assert "MAGMOM = 4*5.00 4*0.60" in out  # Mn 块 5μB，O 块默认 0.6
    assert "已根据 magmom 自动设置 ISPIN=2" in out


def test_ivdw_line_and_report(nacl_poscar_text):
    out = mc.generate_vasp_inputs(nacl_poscar_text, calc_type="static", ivdw=11)
    assert "IVDW = 11  # 11=Grimme D3, 12=D3(BJ)" in out
    assert "色散校正: IVDW=11" in out


def test_ldau_unknown_symbol_rejected(nacl_poscar_text):
    out = mc.generate_vasp_inputs(nacl_poscar_text, calc_type="static", ldau_u="Xx=3.0")
    assert out.startswith("错误")
    assert "不在体系中" in out


def test_default_output_has_no_advanced_blocks(nacl_poscar_text):
    """不传高级参数时行为与旧版完全一致：不得出现任何新块。"""
    out = mc.generate_vasp_inputs(nacl_poscar_text, calc_type="static")
    for token in ("LDAU", "IVDW", "MAGMOM", "ISPIN"):
        assert token not in out, f"默认输出不应包含 {token}"


# ---------- 专项生成器执行路径回归（R2 拆包后曾潜伏断链：_to_vasp5_poscar / Element 未导入） ----------
# 这六个生成器此前只有注册名被锁定、执行路径零覆盖，本组测试强制走通端到端。

_GEN_PROJECT = "pytest_gen_tmp"


def _gen_inputs_root() -> Path:
    from server.matcalc.common import OUTPUTS_DIR as _OUTS

    return Path(str(_OUTS)) / _GEN_PROJECT / "inputs"


def _cleanup_gen_project():
    shutil.rmtree(_gen_inputs_root().parent, ignore_errors=True)


def test_band_inputs_executes_end_to_end(nacl_poscar_text):
    try:
        out = mc.generate_band_inputs(nacl_poscar_text, encut=None, project=_GEN_PROJECT)
        assert not out.startswith("错误"), out[:300]
        saved = list(_gen_inputs_root().rglob("POSCAR"))
        assert saved and saved[0].stat().st_size > 200      # 执行链真正走过 _to_vasp5_poscar
        assert "direct" in saved[0].read_text(encoding="utf-8")
    finally:
        _cleanup_gen_project()


def test_dos_inputs_executes_end_to_end(nacl_poscar_text):
    try:
        out = mc.generate_dos_inputs(nacl_poscar_text, project=_GEN_PROJECT)
        assert not out.startswith("错误"), out[:300]
        assert list(_gen_inputs_root().rglob("INCAR"))
    finally:
        _cleanup_gen_project()


def test_optical_inputs_executes(nacl_poscar_text):
    try:
        out = mc.generate_optical_inputs(nacl_poscar_text, project=_GEN_PROJECT)
        assert not out.startswith("错误"), out[:300]
        assert "已保存到目录" in out
        incars = list(_gen_inputs_root().rglob("INCAR_step2_optics"))
        assert incars and "LOPTICS" in incars[0].read_text(encoding="utf-8")
    finally:
        _cleanup_gen_project()


def test_elastic_inputs_executes(nacl_poscar_text):
    try:
        out = mc.generate_elastic_inputs(nacl_poscar_text, project=_GEN_PROJECT)
        assert not out.startswith("错误"), out[:300]
        incars = list(_gen_inputs_root().rglob("INCAR"))
        assert incars and "IBRION" in incars[0].read_text(encoding="utf-8")
    finally:
        _cleanup_gen_project()


def test_eos_inputs_scale_sweep(nacl_poscar_text):
    try:
        out = mc.generate_eos_inputs(
            nacl_poscar_text, scale_min=0.96, scale_max=1.04, n_points=7, project=_GEN_PROJECT,
        )
        assert not out.startswith("错误"), out[:300]
        poscars = list(_gen_inputs_root().parent.rglob("POSCAR"))
        assert len(poscars) == 7                            # 七个缩放点目录各一份
    finally:
        _cleanup_gen_project()


def test_bader_inputs_executes(nacl_poscar_text):
    try:
        out = mc.generate_bader_inputs(nacl_poscar_text, project=_GEN_PROJECT)
        assert not out.startswith("错误"), out[:300]
        incars = list(_gen_inputs_root().rglob("INCAR"))
        assert incars and "LAECHG" in incars[0].read_text(encoding="utf-8")
    finally:
        _cleanup_gen_project()


def test_aimd_inputs_executes(nacl_poscar_text):
    try:
        out = mc.generate_aimd_inputs(
            nacl_poscar_text, temperature=300, nsw=100, potim=1.0,
            project=_GEN_PROJECT, ldau_u=None,
        )
        assert not out.startswith("错误"), out[:300]
        incars = list(_gen_inputs_root().rglob("INCAR"))
        assert incars
        text = incars[0].read_text(encoding="utf-8")
        assert "IBRION = 0" in text and "MDALGO" in text and "TEBEG" in text
    finally:
        _cleanup_gen_project()
