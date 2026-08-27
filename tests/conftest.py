"""MatCalcAgent S0 回归基线 —— 公共 fixtures 与真实数据锚点。

原则（见 Vault《M5架构设计_v1》§8）：
- 全部离线运行，不连集群、不访问网络；
- outputs/ 下真实计算产物只读作锚点，绝不修改源文件；
- 绘图类测试产物统一落 outputs/pytest_tmp/，用后即删。

数据锚点：
- NaCl_master_OUTCAR   : TOTEN = -27.248126 eV（master 作业 3657）
- NaCl_vasprun.xml     : 带隙 ≈ 5.18 eV
- NaCl_dos2_vasprun.xml: ISPIN=2 自旋极化 DOS
"""
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# matplotlib 无头后端必须在导入 server.main 之前设定
os.environ.setdefault("MPLBACKEND", "Agg")

import server.main as mc  # noqa: E402

OUTPUTS = ROOT / "server" / "outputs"
RESULTS = OUTPUTS / "NaCl_project" / "results"
STRUCTS = OUTPUTS / "NaCl_project" / "structures"

TEST_PROJECT = "pytest_tmp"


# ---------- 真实数据 fixtures（session 级只读） ----------
# 缺样本策略：真机产物锚点在 outputs/（不入库红线）——本机全量覆盖；
# 无样本环境(CI)对应测试优雅跳过，而非硬失败。

_MISSING_NOTE = "真机锚样本缺失（outputs/ 不入库红线）；本机全量回归仍覆盖该锚点"


@pytest.fixture(scope="session")
def nacl_poscar_text() -> str:
    files = sorted(STRUCTS.glob("NaCl_*.vasp"))
    if not files:
        pytest.skip(_MISSING_NOTE)
    return files[0].read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def nacl_outcar_text() -> str:
    p = RESULTS / "NaCl_master_OUTCAR"
    if not p.exists():
        pytest.skip(_MISSING_NOTE)
    return p.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="session")
def nacl_vasprun() -> Path:
    p = RESULTS / "NaCl_vasprun.xml"
    if not p.exists():
        pytest.skip(_MISSING_NOTE)
    return p


@pytest.fixture(scope="session")
def nacl_vasprun_sp() -> Path:
    p = RESULTS / "NaCl_dos2_vasprun.xml"
    if not p.exists():
        pytest.skip(_MISSING_NOTE)
    return p


@pytest.fixture(scope="session")
def nacl_vasprun_nospin() -> Path:
    p = RESULTS / "NaCl_dos_vasprun.xml"
    if not p.exists():
        pytest.skip(_MISSING_NOTE)
    return p


@pytest.fixture(scope="session")
def nacl_pdos_export() -> Path:
    p = OUTPUTS / "NaCl_project" / "dos_pdos" / "pdos_element_NaCl_1787713973.txt"
    if not p.exists():
        pytest.skip(_MISSING_NOTE)
    return p


# ---------- 绘图产物隔离 ----------

@pytest.fixture()
def clean_test_project():
    """绘图测试专用 project 目录：开始前清空、结束后删除，不污染正式项目数据。"""
    base = OUTPUTS / TEST_PROJECT
    shutil.rmtree(base, ignore_errors=True)
    yield TEST_PROJECT
    shutil.rmtree(base, ignore_errors=True)


# ---------- 合成 Bader 样例（格式忠实于 Henkelman ACF.dat；无真实 ACF 存档） ----------
# 注意：parse_bader_acf 当前按「原子序号 → 第 idx 个 ZVAL」映射，
# 多原子体系中只有前 N_element 个原子能拿到净电荷 —— 本样例如实锁定该现状。

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

_POTCAR_FAKE = """\
  TITEL  = PAW_PBE Na_pv 06Sep2000
POMASS = 22.990; ZVAL = 8.000
  TITEL  = PAW_PBE Cl 06Sep2000
POMASS = 35.453; ZVAL = 7.000
"""


@pytest.fixture()
def acf_pair(tmp_path):
    acf = tmp_path / "ACF.dat"
    acf.write_text(_ACF_TEXT, encoding="utf-8")
    pot = tmp_path / "POTCAR_fake"
    pot.write_text(_POTCAR_FAKE, encoding="utf-8")
    return acf, pot
