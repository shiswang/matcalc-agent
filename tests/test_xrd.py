"""XRD 模拟工具回归：离线、确定性、不依赖 outputs/ 真机样本。

锚点：岩盐 NaCl（a=5.64 Å）在 Cu Kα 下 (200) ≈ 31.7°（最强）、(111) ≈ 27.3°、(220) ≈ 45.4°。
"""
import re
from pathlib import Path

import pytest

from server.matcalc import xrd as xr
from server.matcalc.common import OUTPUTS_DIR

NACL_POSCAR = """NaCl rocksalt
1.0
5.6400 0.0 0.0
0.0 5.6400 0.0
0.0 0.0 5.6400
Na Cl
4 4
Direct
0.0 0.0 0.0
0.0 0.5 0.5
0.5 0.0 0.5
0.5 0.5 0.0
0.5 0.5 0.5
0.5 0.0 0.0
0.0 0.5 0.0
0.0 0.0 0.5
"""


def _peaks(text: str) -> list[tuple[float, float]]:
    """从主峰表里抓 (2θ, I%) 对。"""
    return [
        (float(a), float(b))
        for a, b in re.findall(r"^\s+(\d+\.\d{3})\s+\d+\.\d{4}\s+(\d+\.\d)\s+\(", text, re.M)
    ]


def test_simulate_xrd_nacl_anchor():
    out = xr.simulate_xrd(NACL_POSCAR, save=False)
    assert out.startswith("## 结构"), out[:200]
    assert "NaCl" in out
    assert "反射数" in out

    peaks = _peaks(out)
    assert peaks, out
    strongest = max(peaks, key=lambda p: p[1])[0]
    assert abs(strongest - 31.7) < 0.6, peaks          # (200)
    two_thetas = [p[0] for p in peaks]
    assert any(abs(t - 27.3) < 0.6 for t in two_thetas)  # (111)
    assert any(abs(t - 45.4) < 0.8 for t in two_thetas)  # (220)
    assert "说明:" in out


def test_simulate_xrd_wavelength_and_range():
    cu = xr.simulate_xrd(NACL_POSCAR, wavelength="CuKa", save=False)
    mo = xr.simulate_xrd(NACL_POSCAR, wavelength="MoKa", save=False)
    assert "CuKa" in cu and "MoKa" in mo
    assert min(p[0] for p in _peaks(mo)) < min(p[0] for p in _peaks(cu))

    narrow = xr.simulate_xrd(NACL_POSCAR, two_theta_range="25,35", save=False)
    ts = [p[0] for p in _peaks(narrow)]
    assert ts and all(25 <= t <= 35 for t in ts), ts

    custom = xr.simulate_xrd(NACL_POSCAR, wavelength="1.5406", save=False)
    assert "1.5406" in custom


def test_simulate_xrd_writes_png_and_csv(clean_test_project):
    out = xr.simulate_xrd(NACL_POSCAR, save=True, project=clean_test_project)
    assert "已保存" in out
    d = Path(OUTPUTS_DIR) / clean_test_project / "xrd"
    assert any(p.suffix == ".png" for p in d.iterdir())
    csv_files = list(d.glob("*.csv"))
    assert csv_files
    header = csv_files[0].read_text(encoding="utf-8").splitlines()[0]
    assert header == "two_theta_deg,d_A,intensity_pct,hkl"


def test_simulate_xrd_reference_overlay(clean_test_project):
    """参考晶胞大 0.5% → 参考峰整体在小角，Δ2θ = 参考 − 本结构 应为负。"""
    scaled = NACL_POSCAR.replace("5.6400", "5.6682")
    out = xr.simulate_xrd(
        NACL_POSCAR, reference_text=scaled, reference_label="exp +0.5%",
        save=True, project=clean_test_project,
    )
    assert "与参考谱对照" in out
    deltas = [float(x) for x in re.findall(r"([+-]\d+\.\d{3})\s+\(", out)]
    assert len(deltas) >= 5, out
    assert all(d < 0 for d in deltas), deltas
    assert "体积差" in out


def test_simulate_xrd_reference_superstructure_extra_peaks():
    """c 轴加倍的参考结构会多出奇 l 反射 → 应被列为"参考谱独有峰"。"""
    lines = NACL_POSCAR.strip().splitlines()
    lines[4] = "0.0 0.0 11.2800"
    long_c = "\n".join(lines) + "\n"
    out = xr.simulate_xrd(NACL_POSCAR, reference_text=long_c, save=False)
    assert "参考谱独有峰" in out


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"structure_text": ""}, "E_PARAM"),
        ({"structure_text": "not a structure"}, "E_PARSE"),
        ({"structure_text": NACL_POSCAR, "wavelength": "XxKa"}, "E_PARAM"),
        ({"structure_text": NACL_POSCAR, "two_theta_range": "90,10"}, "E_PARAM"),
        ({"structure_text": NACL_POSCAR, "two_theta_range": "5"}, "E_PARAM"),
        ({"structure_text": NACL_POSCAR, "reference_text": "garbage"}, "E_PARSE"),
    ],
)
def test_simulate_xrd_errors(kwargs, code):
    out = xr.simulate_xrd(**kwargs)
    assert out.startswith("错误："), out
    assert f"[{code}]" in out, out


def test_simulate_xrd_accepts_file_path(tmp_path):
    p = tmp_path / "POSCAR"
    p.write_text(NACL_POSCAR, encoding="utf-8")
    out = xr.simulate_xrd(str(p), save=False)
    assert out.startswith("## 结构"), out[:200]
    assert "NaCl" in out
