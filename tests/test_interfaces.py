"""界面建模模块回归：ZSL 预检 / 自动构建 / 手动堆叠（全离线）。

样本用固定晶格常数的 LiCl(a=3.54)/NaCl(a=5.64) 构造，保证断言确定性。
"""
import re
import shutil
from pathlib import Path

from pymatgen.core import Lattice, Structure

from server.matcalc import interfaces as mi
from server.matcalc import structures as mc_st


def _direct_poscar(st: Structure) -> str:
    """手写 VASP5 分组格式 POSCAR（与项目 _to_vasp5_poscar 同构，测试内自足）。"""
    lines = [st.composition.formula, "1.0"]
    for row in st.lattice.matrix:
        lines.append(" ".join(f"{x:.8f}" for x in row))
    syms: list[str] = []
    counts: list[int] = []
    for site in st:
        s = str(site.specie.symbol)
        if syms and syms[-1] == s:
            counts[-1] += 1
        else:
            syms.append(s)
            counts.append(1)
    lines.append(" ".join(syms))
    lines.append(" ".join(str(c) for c in counts))
    lines.append("Direct")
    for site in st:
        lines.append(" ".join(f"{x:.8f}" for x in site.frac_coords))
    return "\n".join(lines) + "\n"


def _rocksalt(formula_pair: tuple[str, str], a: float) -> str:
    cation, anion = formula_pair
    st = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(a), [cation, anion], [[0, 0, 0], [0.5, 0.5, 0.5]],
    )
    return _direct_poscar(st)


def _fence(text: str) -> str:
    """提取返回文本中第一个 ``` 围栏内的内容。"""
    segs = text.split("```")
    return segs[1].removeprefix("\n") if len(segs) >= 2 else ""


LICL = _rocksalt(("Li", "Cl"), 3.54)
NACL = _rocksalt(("Na", "Cl"), 5.64)


# ---------- inspect_interface_match ----------

def test_inspect_lists_terminations():
    out = mi.inspect_interface_match(LICL, NACL, "0 0 1", "0 0 1")
    assert out.startswith("ZSL 匹配成功")
    assert "端型组合" in out
    assert "[0]" in out
    assert re.search(r"10 Å ≈ \d+ 层", out)   # 层数换算建议行


def test_inspect_bad_miller_rejected():
    out = mi.inspect_interface_match(LICL, NACL, "0 0", "0 0 1")
    assert out.startswith("错误") and "米勒指数" in out


def test_bad_poscar_rejected():
    out = mi.inspect_interface_match("not a poscar", NACL)
    assert out.startswith("错误") and "POSCAR 解析失败" in out


# ---------- build_interface ----------

def test_build_interface_full_pipeline():
    out = mi.build_interface(
        LICL, NACL, film_miller="0,0,1", substrate_miller="0 0 1",
        film_thickness=8.0, substrate_thickness=8.0, save=False,
    )
    assert "界面模型: LiCl(0 0 1) / NaCl(0 0 1)" in out
    assert "端型 [0]:" in out
    assert re.search(r"薄膜 8\.0 Å ≈ \d+ 层", out)     # Å→层数换算生效
    body = _fence(out)
    assert body.count("\n") > 20                        # 界面结构规模合理
    assert "\ndirect\n" in body                         # 项目统一 POSCAR 格式（小写关键字）
    assert mc_st.parse_poscar(body).startswith("## 结构摘要")  # 自家解析器可读回


def test_build_interface_save(tmp_path, monkeypatch):
    proj_root = tmp_path / "proj"

    def fake_out_dir(project, kind):
        d = proj_root / kind
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    monkeypatch.setattr(mi, "_out_dir", fake_out_dir)
    out = mi.build_interface(LICL, NACL, save=True, project="whatever")
    assert "已保存: " in out
    saved = list(Path(str(proj_root / "structure")).glob("interface_*.vasp"))
    assert len(saved) == 1 and saved[0].stat().st_size > 500


def test_build_interface_bad_term_index():
    out = mi.build_interface(LICL, NACL, termination_index=99, save=False)
    assert out.startswith("错误") and "termination_index=99" in out


# ---------- stack_slabs ----------

def _slab_of(poscar_text: str) -> str:
    from server.matcalc import structures as mc_st

    out = mc_st.cleave_surface(poscar_text, "0 0 1", slab_height=6.0, vacuum=10.0)
    return _fence(out)


def test_stack_slabs_same_material_no_warning():
    top, bot = _slab_of(NACL), _slab_of(NACL)
    out = mi.stack_slabs(top, bot, gap=2.0, vacuum=12.0)
    assert "总原子数" in out
    assert "面内失配检查通过" in out          # 同材料同超胞 → 无失配警告
    body = _fence(out)
    assert "\ndirect\n" in body
    assert mc_st.parse_poscar(body).startswith("## 结构摘要")


def test_stack_slabs_mismatch_warns():
    top, bot = _slab_of(LICL), _slab_of(NACL)
    out = mi.stack_slabs(top, bot)
    assert "- 警告: 面内 a 失配" in out       # |3.54−5.64|/5.64 ≈ 37% >> 3%
