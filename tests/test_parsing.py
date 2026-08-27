"""解析与诊断回归：真实 OUTCAR / vasprun 锚点 + 合成 ACF（Bader）。

Bader 相关样例在本文件内自行构造（tmp_path fixture），不依赖 conftest.py：
- acf_pair      : 电荷交替分布样例（内容沿用原 conftest 的 acf_pair），用于锁定
                  不传 composition 时的旧映射行为；
- acf_pair_block: 电荷按元素块分组样例（Na 块在前、Cl 块在后，与 POSCAR 元素块序
                  一致），用于验证 composition 模式下逐原子 Δq 的正确展开。
"""
import re

import pytest

from server.matcalc import parsing as mc


# ---------- parse_vasp_output（真实 master OUTCAR） ----------

def test_outcar_toten_anchor(nacl_outcar_text):
    # 样本为 static 计算（NSW=0）：无 "reached required accuracy" 行、无 F= 行，
    # 最大力走 TOTAL-FORCE 兜底解析 —— 如实锁定该行为。
    out = mc.parse_vasp_output(nacl_outcar_text)
    assert "最终电子总能 (TOTEN): -27.248126 eV" in out
    assert "离子步数: 0" in out
    assert "最后离子步最大力: 0.0000 eV/Å" in out
    assert "计算正常结束: 是" in out
    assert "未检测到明显错误关键字" in out


def test_outcar_pressure_anchor(nacl_outcar_text):
    out = mc.parse_vasp_output(nacl_outcar_text)
    m = re.search(r"外部压力: (-?[\d.]+) kbar", out)
    assert m, out
    assert abs(float(m.group(1)) - 6.77) < 0.05  # 项目档案值 6.77 kbar


def test_outcar_garbage_input():
    out = mc.parse_vasp_output("nothing here")
    assert "未找到 free energy TOTEN" in out
    assert "计算正常结束: 否" in out


# ---------- diagnose_vasp_error ----------

def test_diagnose_zbrent():
    out = mc.diagnose_vasp_error("ZBRENT: fatal error in bracketing interval")
    assert "电子自洽迭代不收敛" in out
    assert "修复建议:" in out


def test_diagnose_multiple_patterns():
    log = "TOO FEW BANDS\nError EDDDAV: Call to ZHEGV failed"
    out = mc.diagnose_vasp_error(log)
    assert "匹配到 2 条错误模式" in out
    assert "能带数不足" in out


def test_diagnose_unknown_log():
    out = mc.diagnose_vasp_error("hello world, all fine")
    assert "未识别到已知 VASP 错误模式" in out


# ---------- analyze_vasprun（真实 static vasprun） ----------

def test_analyze_vasprun_gap_anchor(nacl_vasprun):
    out = mc.analyze_vasprun(str(nacl_vasprun))
    m = re.search(r"带隙: ([\d.]+) eV", out)
    assert m, out
    assert 5.0 <= float(m.group(1)) <= 5.4  # 档案锚点 5.18 eV
    assert re.search(r"最终总能 E0: -27\.2[\d]* eV", out), out


def test_analyze_vasprun_params_line(nacl_vasprun):
    out = mc.analyze_vasprun(str(nacl_vasprun))
    assert re.search(r"参数: ENCUT=\d+", out)
    assert "离子步数: " in out


# ---------- parse_bader_acf（合成格式忠实样例，样例构造在本文件内） ----------
# 映射语义说明：
# - 不传 composition：旧映射「原子序号 idx → POTCAR 第 idx 个 ZVAL」，只有前
#   N_元素 个原子拿到 Δq —— 该旧行为被如实保留并锁定；
# - 传 composition="Na2Cl2"：按「元素块 × 原子数」展开逐原子 ZVAL，全部原子拿到 Δq。

_ACF_TEXT = """\
    #         X           Y           Z        CHARGE     MIN DIST   ATOMIC VOL
 ------------------------------------------------------------
    1      0.0000      0.0000      0.0000      7.5000      1.5000     15.0000
    2      2.8030      2.8030      2.8030      7.6000      1.4000     14.0000
    3      0.0000      2.8030      2.8030      7.5000      1.5000     15.0000
    4      2.8030      0.0000      0.0000      7.6000      1.4000     14.0000
  VACUUM CHARGE:               0.0000
  VACUUM VOLUME:               0.0000
  NUMBER OF ELECTRONS:        30.2000
"""

# 电荷按元素块分组的变体：原子 1-2 为 Na 块（n_Bader=7.5 → Δq=+0.5），
# 原子 3-4 为 Cl 块（n_Bader=7.6 → Δq=-0.6）；总电子数与真空电荷保持自洽。
_ACF_TEXT_BLOCK = """\
    #         X           Y           Z        CHARGE     MIN DIST   ATOMIC VOL
 ------------------------------------------------------------
    1      0.0000      0.0000      0.0000      7.5000      1.5000     15.0000
    2      2.8030      2.8030      2.8030      7.5000      1.4000     14.0000
    3      0.0000      2.8030      2.8030      7.6000      1.5000     15.0000
    4      2.8030      0.0000      0.0000      7.6000      1.4000     14.0000
  VACUUM CHARGE:               0.0000
  VACUUM VOLUME:               0.0000
  NUMBER OF ELECTRONS:        30.2000
"""

_POTCAR_FAKE = """\
  TITEL  = PAW_PBE Na_pv 06Sep2000
POMASS = 22.990; ZVAL = 8.000
  TITEL  = PAW_PBE Cl 06Sep2000
POMASS = 35.453; ZVAL = 7.000
"""


@pytest.fixture()
def acf_pair(tmp_path):
    """合成 ACF/POTCAR 对（交替电荷版；本模块同名 fixture 覆盖 conftest，保持自包含）。"""
    acf = tmp_path / "ACF.dat"
    acf.write_text(_ACF_TEXT, encoding="utf-8")
    pot = tmp_path / "POTCAR_fake"
    pot.write_text(_POTCAR_FAKE, encoding="utf-8")
    return acf, pot


@pytest.fixture()
def acf_pair_block(tmp_path):
    """合成 ACF/POTCAR 对（电荷按 Na 块/Cl 块分组版，对应 POSCAR 元素块序）。"""
    acf = tmp_path / "ACF.dat"
    acf.write_text(_ACF_TEXT_BLOCK, encoding="utf-8")
    pot = tmp_path / "POTCAR_fake"
    pot.write_text(_POTCAR_FAKE, encoding="utf-8")
    return acf, pot


def _atom_rows(out: str) -> list[str]:
    """从解析输出中筛出 ACF 原子数据行（行首为整数编号）。"""
    return [ln for ln in out.splitlines() if re.match(r"\s*\d+\s", ln)]


def _row_dq(row: str) -> str | None:
    """取原子行末尾的净电荷 Δq 列（带符号四位小数）；无 Δq 列时返回 None。"""
    m = re.search(r"([+-]\d+\.\d{4})\s*$", row)
    return m.group(1) if m else None


def test_bader_acf_net_charges(acf_pair_block):
    """composition 模式：按元素块展开 ZVAL，4 个原子全部拿到正确的 Δq。"""
    acf, pot = acf_pair_block
    out = mc.parse_bader_acf(str(acf), str(pot), composition="Na2Cl2")
    assert "共 4 个原子" in out
    # 逐原子核对：Na 块（1-2 号，ZVAL=8）Δq=+0.5/+0.5；Cl 块（3-4 号，ZVAL=7）Δq=-0.6/-0.6
    dqs = [_row_dq(ln) for ln in _atom_rows(out)]
    assert dqs == ["+0.5000", "+0.5000", "-0.6000", "-0.6000"]
    # 汇总统计正确（全体原子）
    assert "失电子最多: +0.5000" in out
    assert "得电子最多: -0.6000" in out
    assert "总电子数: 30.2" in out
    assert "真空电荷: 0.0" in out
    # 整体守恒：ΣΔq = ΣZVAL(30) − Σn_Bader(30.2) = −0.2
    assert "全体原子总净电荷 ΣΔq: -0.2000" in out


def test_bader_acf_without_potcar(acf_pair):
    acf, pot = acf_pair
    out = mc.parse_bader_acf(str(acf))
    assert "共 4 个原子" in out
    assert "净电荷" not in out  # 无 POTCAR 不算 Δq


def test_bader_acf_composition_mismatch(acf_pair):
    """composition 元素序与 POTCAR 段序不符时应报错，而不是产出错误的 Δq。"""
    acf, pot = acf_pair
    out = mc.parse_bader_acf(str(acf), str(pot), composition="MnO")
    assert out.startswith("错误：[E_PARAM] POTCAR 元素序")


def test_bader_acf_legacy_mapping_still_works(acf_pair):
    """不传 composition 时维持旧映射：仅前 N_元素 个原子拿到 Δq（兼容旧调用）。"""
    acf, pot = acf_pair
    out = mc.parse_bader_acf(str(acf), str(pot))
    assert "共 4 个原子" in out
    assert "+0.5000" in out   # 原子1 → 第 1 个 ZVAL(8) − n_Bader 7.5
    assert "-0.6000" in out   # 原子2 → 第 2 个 ZVAL(7) − n_Bader 7.6
    # 旧缺陷如实锁定：只有前 2 个原子行带 Δq 列（真实 POTCAR 每元素段仅一个 ZVAL）
    rows_with_dq = [ln for ln in _atom_rows(out) if _row_dq(ln) is not None]
    assert len(rows_with_dq) == 2
    assert "失电子最多: +0.5000" in out
    assert "得电子最多: -0.6000" in out
