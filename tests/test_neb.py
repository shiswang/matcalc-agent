"""NEB 输入生成回归测试：端点体检 / image 目录集 / NEB INCAR 标签。

原则与 conftest 一致：全部离线运行，样本结构用 build_structure 现场合成，
落盘类测试把 outputs 根目录重定向到 pytest 临时目录，不污染正式数据。
"""
import re
import shutil
from pathlib import Path

import pytest
from pymatgen.core import Structure
from pymatgen.io.vasp import Poscar

from server.matcalc import common as mc_common
from server.matcalc import neb
from server.matcalc import structures as mc_st


# ---------- 样本构造（全离线） ----------

def _poscar_of(composition: str, prototype: str) -> str:
    """用 structures.build_structure 离线合成样本并取出 POSCAR 文本。"""
    out = mc_st.build_structure(composition, prototype=prototype, save=False)
    assert out.startswith("请求化学式"), out[:200]
    return out.split("## POSCAR\n```\n")[1].split("\n```")[0]


def _normalize(poscar_text: str) -> str:
    """统一为 VASP5 分组格式（保证两端点逐原子元素顺序一致，插值才有意义）。"""
    return mc_st._to_vasp5_poscar(Poscar.from_str(poscar_text).structure)


@pytest.fixture(scope="module")
def nacl_pair() -> tuple[str, str]:
    """一致的 NaCl 端点对：起点不动，终点平移一个 Na 原子（模拟扩散末态）。"""
    init_raw = _poscar_of("NaCl", "rocksalt")
    st = Poscar.from_str(init_raw).structure
    fin_st = st.copy()
    fin_st.translate_sites([0], [0.05, 0.05, 0.05], frac_coords=True)
    # 两端点都过一遍 VASP5 分组归一化，锁定相同逐原子元素顺序
    return _normalize(init_raw), mc_st._to_vasp5_poscar(fin_st)


@pytest.fixture()
def isolated_outputs(tmp_path, monkeypatch):
    """把 outputs 根目录重定向到临时目录，测试结束自动清理。"""
    monkeypatch.setattr(mc_common, "OUTPUTS_DIR", str(tmp_path))
    return tmp_path


# ---------- 端点体检 ----------

class TestEndpoints:
    def test_consistent_pair_passes(self, nacl_pair):
        """一致端点应通过体检且给出原子数/元素/体积摘要。"""
        out = neb.generate_neb_endpoints(*nacl_pair)
        assert not out.startswith("错误")
        assert "体检通过" in out
        assert "原子数" in out
        assert "晶胞体积" in out
        assert "差异" in out

    def test_atom_count_mismatch_rejected(self, nacl_pair):
        """故意错开原子数的端点必须被拒。"""
        p_init, p_final = nacl_pair
        st = Poscar.from_str(p_init).structure
        broken = mc_st._to_vasp5_poscar(st.copy().remove_sites([0]))
        out = neb.generate_neb_endpoints(broken, p_final)
        assert out.startswith("错误")
        assert "原子数不一致" in out

    def test_species_order_mismatch_rejected(self, nacl_pair):
        """同组成但逐原子元素顺序错位（Cl 提到最前）必须被拒。"""
        p_init, p_final = nacl_pair
        st = Poscar.from_str(p_init).structure
        syms = [s.specie for s in st]
        coords = [list(s.frac_coords) for s in st]
        reordered = [syms[4]] + syms[0:4] + syms[5:]
        rcoords = [coords[4]] + coords[0:4] + coords[5:]
        broken = mc_st._to_vasp5_poscar(Structure(st.lattice, reordered, rcoords))
        out = neb.generate_neb_endpoints(broken, p_final)
        assert out.startswith("错误")
        assert "元素" in out

    def test_lattice_diff_warning_not_error(self, nacl_pair):
        """晶格常数差 3% 只给警告、不阻断（体积差异同时报告）。"""
        p_init, _ = nacl_pair
        st = Poscar.from_str(p_init).structure
        fin_st = st.copy()
        fin_st.scale_lattice(fin_st.volume * 1.03**3)  # 各方向 +3%
        out = neb.generate_neb_endpoints(p_init, mc_st._to_vasp5_poscar(fin_st))
        assert not out.startswith("错误")
        assert "警告" in out
        assert "2%" in out

    def test_unparsable_poscar_rejected(self):
        """POSCAR 解析失败属于阻断错误。"""
        out = neb.generate_neb_endpoints("这不是 POSCAR", "同样不是")
        assert out.startswith("错误")


# ---------- image 目录集 ----------

class TestImages:
    def test_linear_midpoint_is_exact_average(
        self, nacl_pair, isolated_outputs
    ):
        """linear 插值中点坐标 ≈ 两端点分数坐标平均（容差 1e-6）。"""
        p_init, p_final = nacl_pair
        out = neb.generate_neb_images(
            p_init, p_final, images=1, method="linear", project="nebtest", save=True
        )
        m = re.search(r"落盘根路径: (.+?)（", out)
        assert m, f"未找到落盘路径:\n{out}"
        root = Path(m.group(1))
        try:
            c00 = Poscar.from_str((root / "00" / "POSCAR").read_text(encoding="utf-8")).structure.frac_coords
            c01 = Poscar.from_str((root / "01" / "POSCAR").read_text(encoding="utf-8")).structure.frac_coords
            c02 = Poscar.from_str((root / "02" / "POSCAR").read_text(encoding="utf-8")).structure.frac_coords
            avg = (c00 + c02) / 2.0
            assert abs(c01 - avg).max() < 1e-6
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_dir_count_and_images_label(self, nacl_pair, isolated_outputs):
        """目录数 = images+2 且摘要的 IMAGES 值与入参一致；00/0N 为端点原文。"""
        p_init, p_final = nacl_pair
        images = 3
        out = neb.generate_neb_images(
            p_init, p_final, images=images, method="linear", project="nebtest"
        )
        m = re.search(r"落盘根路径: (.+?)（", out)
        assert m, f"未找到落盘路径:\n{out}"
        root = Path(m.group(1))
        try:
            names = sorted(d.name for d in root.iterdir())
            assert names == ["%02d" % i for i in range(images + 2)]  # 00..04
            for d in root.iterdir():
                assert (d / "POSCAR").exists(), f"{d.name}/POSCAR 缺失"
            # 00 与 04 分别是起/终点副本（VASP5 分组格式一致）
            assert (root / "00" / "POSCAR").read_text(encoding="utf-8") == p_init
            assert (root / "04" / "POSCAR").read_text(encoding="utf-8") == p_final
            # IMAGES 应设值与入参一致
            m_img = re.search(r"IMAGES 应设值: (\d+)", out)
            assert m_img and int(m_img.group(1)) == images
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_idpp_import_error_falls_back_to_linear(
        self, nacl_pair, monkeypatch
    ):
        """DiffusionAnalyzer 导入失败（扩展包未安装）→ 回退 linear 并注明。"""
        def _boom():
            raise ImportError("No module named 'pymatgen.analysis.diffusion'")

        monkeypatch.setattr(neb, "_load_idpp_class", _boom)
        out = neb.generate_neb_images(
            *nacl_pair, images=2, method="idpp", save=False
        )
        assert not out.startswith("错误")
        assert "IDPP 失败已回退 linear" in out
        assert "目录数: 4" in out  # 插值照常完成

    def test_idpp_constructor_crash_falls_back_to_linear(
        self, nacl_pair, monkeypatch
    ):
        """DiffusionAnalyzer 类构造抛异常 → 同样回退 linear 并注明。"""
        class ExplodingAnalyzer:
            def __init__(self, *args, **kwargs):
                raise ValueError("模拟 DiffusionAnalyzer 构造失败")

        monkeypatch.setattr(neb, "_load_idpp_class", lambda: ExplodingAnalyzer)
        out = neb.generate_neb_images(
            *nacl_pair, images=2, method="idpp", save=False
        )
        assert "IDPP 失败已回退 linear" in out
        assert "模拟 DiffusionAnalyzer 构造失败" in out

    def test_invalid_method_rejected(self, nacl_pair):
        out = neb.generate_neb_images(*nacl_pair, method="quadratic", save=False)
        assert out.startswith("错误")
        assert "method" in out

    def test_invalid_images_zero_rejected(self, nacl_pair):
        out = neb.generate_neb_images(*nacl_pair, images=0, save=False)
        assert out.startswith("错误")

    def test_endpoint_failure_short_circuits(self, nacl_pair):
        """端点体检不通过时直接透传错误，不做任何插值/落盘。"""
        p_init, p_final = nacl_pair
        st = Poscar.from_str(p_init).structure
        broken = mc_st._to_vasp5_poscar(st.copy().remove_sites([0]))
        out = neb.generate_neb_images(broken, p_final, save=False)
        assert out.startswith("错误")
        assert "原子数不一致" in out


# ---------- NEB INCAR ----------

class TestIncar:
    def test_defaults_ci_enabled(self):
        out = neb.generate_neb_incar()  # images=5, ci=True
        assert "SYSTEM = NEB" in out
        assert "ENCUT = 400" in out
        assert "PREC = Accurate" in out
        assert "EDIFF = 1E-5" in out
        assert "IBRION = 3" in out
        assert "POTIM = 0.2" in out
        assert "NSW = 200" in out
        assert "EDIFFG = -0.03" in out
        assert "ISMEAR = 0" in out
        assert "SIGMA = 0.05" in out
        assert "ISYM = 0" in out
        assert "IMAGES = 5" in out
        assert "SPRING = -5" in out
        assert "ICHAIN = 0" in out
        assert "LCLIMB = .TRUE." in out
        # CI 需 VTST 编译版的提示注释
        assert "CI 爬坡需 VTST 编译版 VASP" in out
        # 尾部使用提示注释块（①核数整除 ②Gamma ③看力）
        assert "整除" in out and "Gamma" in out and "最大原子力" in out

    def test_ci_disabled_omits_lclimb(self):
        out = neb.generate_neb_incar(images=4, ci=False)
        assert "LCLIMB" not in out
        assert "IMAGES = 4" in out

    def test_invalid_images_rejected(self):
        for bad in (0, -3):
            out = neb.generate_neb_incar(images=bad)
            assert out.startswith("错误")
            assert "images" in out


# ---------- TOOLS 导出 ----------

def test_tools_export():
    """模块导出清单须包含三个工具函数本体。"""
    assert neb.TOOLS == [
        neb.generate_neb_endpoints,
        neb.generate_neb_images,
        neb.generate_neb_incar,
    ]
