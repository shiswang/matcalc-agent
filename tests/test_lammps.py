"""LAMMPS 基础链路回归：POSCAR→data 转换 / in.lammps 模板生成 / log thermo 解析。

样本结构全部离线构造：用 server.matcalc.structures.build_structure 造
rocksalt/hcp 结构后从 ``` 围栏取 POSCAR（不依赖 outputs 存档与网络）。
"""
import re

import pytest

from server.matcalc import lammps as ml
from server.matcalc.structures import build_structure


# ---------- 公共辅助 ----------

def _poscar_of(text: str) -> str:
    """从 build_structure 返回文本中提取 ``` 围栏内的 POSCAR 内容。"""
    return text.split("```")[1].strip() + "\n"


def _count_atom_rows(data_text: str) -> tuple[int, int]:
    """解析 data 文本，返回 (header 声明的原子数, Atoms 区实际数据行数)。"""
    m = re.search(r"^(\d+) atoms$", data_text, flags=re.M)
    assert m is not None, f"data 文件缺少原子数声明行:\n{data_text[:300]}"
    declared = int(m.group(1))
    marker = re.search(r"^Atoms # \w+\s*$", data_text, flags=re.M)
    assert marker is not None, "data 文件缺少 'Atoms #' 区块标记"
    rows = [ln for ln in data_text[marker.end():].splitlines() if ln.strip()]
    return declared, len(rows)


# ---------- 离线样本 ----------

@pytest.fixture(scope="module")
def nacl_poscar() -> str:
    """NaCl 岩盐结构（8 原子立方胞），无氧化态标签。"""
    return _poscar_of(build_structure("NaCl", prototype="rocksalt", save=False))


@pytest.fixture(scope="module")
def mno_poscar() -> str:
    """MnO 岩盐结构（8 原子立方胞）。"""
    return _poscar_of(build_structure("MnO", prototype="rocksalt", save=False))


@pytest.fixture(scope="module")
def mg_hcp_poscar() -> str:
    """Mg 六方密堆结构（2 原子六方胞，非正交盒）。"""
    return _poscar_of(build_structure("Mg", prototype="hcp", save=False))


# 位点行带氧化态标签的 POSCAR（pymatgen 可解析为带 oxi_state 的 Species）
_NACL_CHARGED_POSCAR = """\
decorated NaCl
1.0
5.6000000000 0.0000000000 0.0000000000
0.0000000000 5.6000000000 0.0000000000
0.0000000000 0.0000000000 5.6000000000
Na+ Cl-
4 4
direct
0.0000000000 0.0000000000 0.0000000000 Na+
0.5000000000 0.0000000000 0.0000000000 Na+
0.0000000000 0.5000000000 0.0000000000 Na+
0.0000000000 0.0000000000 0.5000000000 Na+
0.5000000000 0.5000000000 0.5000000000 Cl-
0.0000000000 0.5000000000 0.5000000000 Cl-
0.5000000000 0.0000000000 0.5000000000 Cl-
0.5000000000 0.5000000000 0.0000000000 Cl-
"""

# 合成 LAMMPS log：两个 thermo 区块，验证「取最后一个」逻辑
_SYN_LOG = """\
LAMMPS (29 Oct 2024)
OMP is using 1 OpenMP thread(s) per task
Reading data file from disk ...
  orthogonal box = (0 0 0) to (5.6 5.6 5.6)

Per MPI rank memory allocation (min/avg/max) = 3.2 | 3.5 | 4.1 Mbytes
   Step         Temp         PotEng         TotEng        Press
        0        300            -6.77          -4.62         -5.02
      100        298.5          -6.80          -4.63         -5.01
Loop time of 0.00231 on 1 procs for 100 steps with 64 atoms

Setting up Verlet run ...
   Step         Temp         PotEng         TotEng        Press
        0        310            -6.77          -4.62         -5.02
      100        309.5          -6.80          -4.63         -5.01
      200        308.1          -6.90          -4.64         -5.00
Total wall time: 0:00:03
"""


# ---------- build_lammps_data：正常路径 ----------

@pytest.mark.parametrize("fixture_name,els", [("nacl_poscar", ("# Na", "# Cl")),
                                              ("mno_poscar", ("# Mn", "# O"))])
def test_rocksalt_to_data_atoms_conserved(fixture_name, els, request):
    """NaCl/MnO 岩盐胞转换：原子数守恒（8→8）且含按元素序排列的 Masses 区。"""
    poscar = request.getfixturevalue(fixture_name)
    out = ml.build_lammps_data(poscar)
    assert out.startswith("## LAMMPS data 转换摘要"), out[:120]
    assert "错误" not in out, out[:300]

    body = out.split("```")[1]
    declared, n_rows = _count_atom_rows(body)
    assert declared == 8 and n_rows == 8, "原子数不守恒"

    assert "Masses" in body, "缺少 Masses 区（温度初始化需要真实质量）"
    mass_part = body.split("Masses", 1)[1].split("Atoms", 1)[0]
    idx = [mass_part.index(e) for e in els]
    assert idx == sorted(idx), f"Masses 元素顺序应与 POSCAR 一致: {els}"

    assert "原子总数: 8" in out
    assert "正交盒" in out  # 立方岩盐 → 无 tilt


def test_hex_cell_writes_tilt(mg_hcp_poscar):
    """六方 Mg（gamma=120°）→ 必须写出 xy/xz/yz tilt 因子的非正交盒。"""
    out = ml.build_lammps_data(mg_hcp_poscar)
    assert out.startswith("## LAMMPS data 转换摘要")
    body = out.split("```")[1]
    declared, n_rows = _count_atom_rows(body)
    assert declared == 2 and n_rows == 2
    assert "xy xz yz" in body, "非正交晶胞缺少 tilt 行"
    assert "非正交三斜盒" in out


def test_charge_style_with_decorated_poscar():
    """位点行带 Na+/Cl- 价态标签时，atom_style='charge' 写出电荷列。"""
    out = ml.build_lammps_data(_NACL_CHARGED_POSCAR, atom_style="charge")
    assert out.startswith("## LAMMPS data 转换摘要"), out[:200]
    body = out.split("```")[1]
    declared, n_rows = _count_atom_rows(body)
    assert declared == 8 and n_rows == 8
    assert "Atoms # charge" in body
    assert re.search(r"^\s*1\s+1\s+1\.0\s", body, flags=re.M), "首原子（Na+）应为 +1 电荷"
    assert re.search(r"^\s*5\s+2\s+-1\.0\s", body, flags=re.M), "第 5 原子（Cl-）应为 -1 电荷"


# ---------- build_lammps_data：错误路径 ----------

def test_bad_poscar_rejected():
    out = ml.build_lammps_data("这不是一个 POSCAR 文件")
    assert out.startswith("错误")


def test_invalid_atom_style_rejected(nacl_poscar):
    out = ml.build_lammps_data(nacl_poscar, atom_style="molecular")
    assert out.startswith("错误")
    assert "atom_style" in out


def test_charge_without_oxidation_rejected(nacl_poscar):
    """普通 POSCAR 无电荷信息 → charge 样式必须报错提示而非写零电荷。"""
    out = ml.build_lammps_data(nacl_poscar, atom_style="charge")
    assert out.startswith("错误")
    assert "charge" in out and "atomic" in out  # 报错里给出两个可选样式


# ---------- generate_lammps_inputs：公共设置 + 四种 calc_type ----------

def test_inputs_common_settings(nacl_poscar):
    """统一包含 units/boundary/read_data/neighbor/timestep/thermo/potential 区。"""
    out = ml.generate_lammps_inputs(calc_type="min",
                                    potential_line="pair_style eam/alloy")
    for pat in (
        r"^units\s+metal$",
        r"^dimension\s+3$",
        r"^boundary\s+p\s+p\s+p$",
        r"^read_data\s+data\.structure$",
        r"^neighbor\s+2\.0\s+bin$",
        r"^neigh_modify\s+every\s+1\s+delay\s+5\s+check\s+yes$",
        r"^timestep\s+0\.001$",
        r"^thermo\s+100$",
        r"^thermo_modify\s+flush\s+yes$",
        r"^pair_style\s+eam/alloy$",  # potential_line 原样嵌入
    ):
        assert re.search(pat, out, flags=re.M), f"缺少设置: {pat}"
    assert "```" in out  # 脚本在代码块中


def test_inputs_min():
    out = ml.generate_lammps_inputs(calc_type="min")
    assert not out.startswith("错误")
    assert "minimize" in out
    assert len(re.findall(r"^minimize\s", out, flags=re.M)) >= 2, \
        "应为两轮 minimize 循环（粗收敛 + 精修）"
    assert re.search(r"^write_data\s+data\.minimized$", out, flags=re.M)


def test_inputs_nvt():
    out = ml.generate_lammps_inputs(calc_type="nvt")
    assert re.search(
        r"^velocity\s+all\s+create\s+300\s+\d+\s+dist\s+gaussian\s+mom\s+yes\s+mag\s+yes$",
        out, flags=re.M,
    ), "速度初始化须用 T 且 mom/mag yes"
    assert re.search(
        r"^fix\s+\w+\s+all\s+nvt\s+temp\s+300\s+300\s+0\.1$", out, flags=re.M
    ), "fix nvt 温度设定错误（tdamp=100*dt=0.1）"
    assert re.search(r"^run\s+", out, flags=re.M)


def test_inputs_npt():
    out = ml.generate_lammps_inputs(calc_type="npt")
    assert re.search(
        r"^fix\s+\w+\s+all\s+npt\s+temp\s+300\s+300\s+0\.1\s+iso\s+0\.0\s+0\.0\s+1$",
        out, flags=re.M,
    ), "fix npt 应含温控与 iso 零压控压（pdamp=1000*dt=1）"
    assert re.search(
        r"^velocity\s+all\s+create\s+300\b", out, flags=re.M
    )
    assert re.search(r"^run\s+", out, flags=re.M)


def test_inputs_nve_msd():
    """MSD 必须由 compute msd 经 fix ave/time 直出文件，不做 dump 后处理。"""
    out = ml.generate_lammps_inputs(calc_type="nve_msd")
    assert re.search(r"^compute\s+\w+\s+all\s+msd\b", out, flags=re.M), "缺少 compute msd"
    assert re.search(
        r"^fix\s+\w+\s+all\s+ave/time\s+1\s+1\s+1000\s+v_msdt\s+"
        r"c_msd\[1\]\s+c_msd\[2\]\s+c_msd\[3\]\s+c_msd\[4\]\s+file\s+msd\.out",
        out, flags=re.M,
    ), "fix ave/time 应把 MSD 各分量直出到 msd.out"
    assert re.search(r"^fix\s+\w+\s+all\s+nve$", out, flags=re.M), "缺少 NVE 积分器"
    assert re.search(r"^dump\s+\w+\s+all\s+custom\s+1000\b", out, flags=re.M)


def test_inputs_invalid_calc_type():
    out = ml.generate_lammps_inputs(calc_type="vcsgc")
    assert out.startswith("错误")
    assert "calc_type" in out


def test_inputs_custom_params_embedded():
    """potential_line 原样保留；T/timestep/dump_every/data_file 全部生效。"""
    pot = "pair_style lj/cut 10.0\npair_coeff * * 1.0 3.4"
    out = ml.generate_lammps_inputs(
        calc_type="nvt", potential_line=pot,
        T=500.0, timestep=0.002, dump_every=250, data_file="my.data",
    )
    assert pot in out, "potential_line 必须原样嵌入"
    assert re.search(r"^read_data\s+my\.data$", out, flags=re.M)
    assert re.search(r"^velocity\s+all\s+create\s+500\b", out, flags=re.M)
    assert re.search(r"^timestep\s+0\.002$", out, flags=re.M)
    assert re.search(r"^dump\s+\w+\s+all\s+custom\s+250\b", out, flags=re.M)


# ---------- parse_lammps_log ----------

def test_parse_log_last_block_tab_table():
    """多区块 log 取最后一段；行列数正确且数值按原值 tab 分隔。"""
    out = ml.parse_lammps_log(_SYN_LOG)
    assert not out.startswith("错误"), out
    lines_ = out.splitlines()
    assert lines_[0] == "# Step\tTemp\tPotEng\tTotEng\tPress", "首行应为 '# ' + 列名"
    assert len(lines_) == 1 + 3, "应只含最后一个区块的 3 条数据行"
    for ln in lines_[1:]:
        assert len(ln.split("\t")) == 5, f"每行应为 5 列 tab 分隔: {ln!r}"
    assert any(ln.startswith("0\t310") for ln in lines_), "取的应是第二个区块"
    assert not any(ln.startswith("0\t300") for ln in lines_), "不应混入第一个区块"
    assert lines_[-1] == "200\t308.1\t-6.90\t-4.64\t-5.00", "数值按原值保留"


def test_parse_log_no_thermo():
    out = ml.parse_lammps_log("LAMMPS (29 Oct 2024)\nTotal wall time: 0:00:01\n")
    assert out.startswith("错误")
    assert "未找到 thermo" in out


def test_parse_log_header_only_block():
    """只有表头没有数据行的区块不算有效 thermo 数据。"""
    log = "   Step    Temp\nLoop time of 0.1 on 1 procs for 0 steps\n"
    out = ml.parse_lammps_log(log)
    assert out.startswith("错误")
