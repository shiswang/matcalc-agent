"""S8 建模栈一期回归：CIF 导入 / 空间群 / 缺陷编辑 / 原胞与对称性。"""
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from server.matcalc import structures as mc_st
from server.matcalc.common import OUTPUTS_DIR

PROJ = "s8_model_test"


@pytest.fixture()
def clean_proj():
    import shutil

    base = Path(OUTPUTS_DIR) / PROJ
    shutil.rmtree(base, ignore_errors=True)
    yield
    shutil.rmtree(base, ignore_errors=True)


def _nacl_poscar() -> str:
    st = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    return mc_st._to_vasp5_poscar(st)


def _min_cif() -> str:
    st = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    return st.to(fmt="cif")


def test_import_poscar_and_cif(clean_proj):
    out = mc_st.import_structure(_nacl_poscar(), fmt="auto", project=PROJ)
    assert "识别格式: poscar" in out
    assert "NaCl" in out
    out2 = mc_st.import_structure(_min_cif(), fmt="auto", project=PROJ)
    assert "识别格式: cif" in out2
    assert "结构摘要" in out2
    assert mc_st.import_structure("not a structure", fmt="poscar").startswith("错误")


def test_build_from_spacegroup(clean_proj):
    out = mc_st.build_from_spacegroup("NaCl", 225, project=PROJ)
    assert "空间群: 225" in out
    assert "NaCl" in out
    assert "```" in out
    bad = mc_st.build_from_spacegroup("NaCl", 999)
    assert bad.startswith("错误")


def test_edit_substitute_vacancy_insert_scale(clean_proj):
    pos = _nacl_poscar()
    # 批量 Na→K
    out = mc_st.edit_structure(
        pos, op="substitute", element_from="Na", element_to="K", project=PROJ
    )
    assert "批量代位" in out
    assert "K" in out
    # 单点代位
    out2 = mc_st.edit_structure(
        pos, op="substitute", site_index=0, element_to="Li", project=PROJ
    )
    assert "代位 site 0" in out2
    # 空位
    out3 = mc_st.edit_structure(pos, op="vacancy", site_index=1, project=PROJ)
    assert "空位" in out3
    assert "剩余" in out3
    # 间隙
    out4 = mc_st.edit_structure(
        pos, op="insert", element="Li", frac_coords="0.25,0.25,0.25", project=PROJ
    )
    assert "插入 Li" in out4
    # 缩放
    out5 = mc_st.edit_structure(pos, op="scale", scale=1.02, project=PROJ)
    assert "缩放" in out5
    # 参数错误
    assert mc_st.edit_structure(pos, op="vacancy").startswith("错误")
    assert mc_st.edit_structure(pos, op="nope").startswith("错误")


def test_primitive_and_symmetry(clean_proj):
    # 常规岩盐胞（8 原子）应可约化或至少报告空间群
    out = mc_st.primitive_cell(_nacl_poscar(), project=PROJ)
    assert "原胞约化" in out or out.startswith("错误")
    if not out.startswith("错误"):
        assert "225" in out or "Fm-3m" in out
    rep = mc_st.symmetry_report(_nacl_poscar())
    assert "空间群" in rep
    assert "225" in rep or "Fm-3m" in rep


class _FakeAseProc:
    """假 ASE 进程：走"已启动"分支，但绝不真弹窗口。"""

    returncode = 0
    stderr = None

    def wait(self, timeout=None):
        return 0


def test_view_structure_ase_success_without_gui(clean_proj, monkeypatch):
    """成功分支零副作用：替换 ase 二进制与 Popen，测试期间不启动真实 GUI。

    直接调真函数时，每次跑回归都会弹一个 ase gui 窗口且无人关闭（本机实测：
    `D:\python\Scripts\ase.EXE` 在 PATH 上，`_find_ase_cli()` 必命中）。
    """
    import subprocess as _sp

    monkeypatch.setattr(mc_st, "_find_ase_cli", lambda: r"C:\fake\ase.exe")
    monkeypatch.setattr(_sp, "Popen", lambda *args, **kwargs: _FakeAseProc())

    out = mc_st.view_structure_ase(poscar_text=_nacl_poscar(), project=PROJ)
    assert isinstance(out, str) and out
    assert not out.startswith("错误"), out
    assert "已请求 ASE GUI 打开" in out
    # 预览副本必须真的写盘
    assert list((Path(OUTPUTS_DIR) / PROJ).rglob("ase_view_*.vasp"))


def test_view_structure_ase_clean_error_when_ase_missing(clean_proj, monkeypatch):
    """没装 ASE 时必须返回"错误："并点名 ASE，不能抛异常。"""
    monkeypatch.setattr(mc_st, "_find_ase_cli", lambda: None)
    out = mc_st.view_structure_ase(poscar_text=_nacl_poscar(), project=PROJ)
    assert out.startswith("错误") and "ASE" in out
