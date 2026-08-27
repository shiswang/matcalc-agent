"""EOS 拟合回归：BM3 合成数据精确复原 + 输入校验。"""
import re

from server.matcalc import analysis as mc


def _bm3(v, v0, e0, b0, bp):
    """三阶 Birch-Murnaghan 正向曲线（与 pymatgen 实现同式）。"""
    eta = (v0 / v) ** (2.0 / 3.0)
    return e0 + 9.0 * v0 * b0 / 16.0 * ((eta - 1.0) ** 3 * bp + (eta - 1.0) ** 2 * (6.0 - 4.0 * eta))


EV_A3_TO_GPA = 160.21766208


def test_fit_eos_recovers_exact_parameters():
    v0, e0, b0, bp = 25.0, -1.0, 0.5, 4.0
    volumes = [v0 * f for f in (0.96, 0.97, 0.98, 0.99, 1.0, 1.01, 1.02)]
    energies = [_bm3(v, v0, e0, b0, bp) for v in volumes]

    out = mc.fit_eos(volumes, energies)

    m_v0 = re.search(r"平衡体积 V0 = ([\d.]+) Å", out)
    m_bp = re.search(r"B0' = ([\d.]+)", out)
    m_e0 = re.search(r"最小能量 E0 = (-?[\d.]+) eV", out)
    m_gp = re.search(r"B0 = ([\d.]+) GPa", out)
    m_rms = re.search(r"RMS 残差 = ([\d.eE+-]+) eV", out)
    assert all([m_v0, m_bp, m_e0, m_gp, m_rms]), out

    assert abs(float(m_v0.group(1)) - v0) < 0.01
    assert abs(float(m_bp.group(1)) - bp) < 0.02
    assert abs(float(m_e0.group(1)) - e0) < 1e-4
    assert abs(float(m_gp.group(1)) - b0 * EV_A3_TO_GPA) < 0.5
    assert float(m_rms.group(1)) < 1e-4  # 完美数据残差≈机器精度


def test_fit_eos_length_mismatch():
    assert mc.fit_eos([1.0, 2.0, 3.0, 4.0], [1.0, 2.0]).startswith("错误")


def test_fit_eos_too_few_points():
    out = mc.fit_eos([20.0, 21.0, 22.0], [-1.0, -1.01, -1.02])
    assert out.startswith("错误")
