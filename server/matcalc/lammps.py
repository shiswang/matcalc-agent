"""LAMMPS 基础链路：POSCAR→data 转换 / in.lammps 模板生成 / log thermo 解析。

面向 hzw 节点 ~/.dp1s/envs/dp1s/bin/lmp 的离线前置工具：
本模块全部离线运行，只做文本与结构转换，不调用 lmp 可执行文件、不访问网络。
"""
from __future__ import annotations

import io

from ase.data import atomic_numbers
from ase.io.lammpsdata import write_lammps_data
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.io.vasp import Poscar

# 支持的 atom_style 与 calc_type 白名单
_ATOM_STYLES = ("atomic", "charge")
_CALC_TYPES = ("min", "nvt", "npt", "nve_msd")

# velocity create 固定随机种子（可复现；用户可在生成的脚本里自行修改）
_VELOCITY_SEED = 4928459


# ─────────────────────────── 内部辅助 ───────────────────────────

def _extract_charges(structure) -> list[float] | None:
    """从结构位点提取氧化态电荷；任一位点缺失则返回 None。

    pymatgen 中只有 Species（如 Na+）携带 oxi_state，
    普通 Element 位点无该属性或为 None。
    """
    charges: list[float] = []
    for site in structure:
        ox = getattr(site.specie, "oxi_state", None)
        if ox is None:
            return None
        charges.append(float(ox))
    return charges


def _fmt(x: float) -> str:
    """数值转简洁文本：%g 去掉多余的尾零（300.0→300，0.001→0.001）。"""
    return f"{x:g}"


def _common_head(calc_label: str, data_file: str, timestep: float) -> str:
    """in.lammps 公共头部：初始化 / read_data / 近邻 / 时间步长。"""
    return (
        "# ============================================================\n"
        f"# MatCalcAgent 自动生成 —— LAMMPS 输入脚本\n"
        f"# calc_type : {calc_label}\n"
        f"# 单位制    : metal（Å / eV / ps）| 边界: p p p | 数据文件: {data_file}\n"
        f"# 提示      : 势函数区需自行核对 pair_style 与 atom type 编号顺序的对应关系\n"
        "# ============================================================\n"
        "\n"
        "# ---------- 初始化 ----------\n"
        "units           metal\n"
        "dimension       3\n"
        "boundary        p p p\n"
        "atom_style      atomic\n"
        "\n"
        "# ---------- 读入结构 ----------\n"
        f"read_data       {data_file}\n"
        "\n"
        "# ---------- 近邻列表 ----------\n"
        "neighbor        2.0 bin\n"
        "neigh_modify    every 1 delay 5 check yes\n"
        "\n"
        "# ---------- 时间步长 ----------\n"
        f"timestep        {_fmt(timestep)}\n"
    )


def _potential_block(potential_line: str) -> str:
    """势函数区：potential_line 原样嵌入；为空时给出占位示例注释。"""
    body = potential_line.rstrip()
    if body:
        text = f"{body}\n"
    else:
        text = (
            "# TODO: 在此填入 pair_style / pair_coeff 设置，例如：\n"
            "#   pair_style     eam/alloy\n"
            "#   pair_coeff     * *  FeCu.eam.alloy Fe Cu\n"
        )
    return (
        "\n# ---------- 势函数（pair 风格区，potential_line 原样嵌入） ----------\n"
        + text
    )


_THERMO_BLOCK = (
    "\n# ---------- 热力学输出 ----------\n"
    "thermo          100\n"
    "thermo_modify   flush yes\n"
)

_RUN_LINE = "run             100000        # TODO: 总步数按需修改"


# ─────────────────────────── MCP 工具 ───────────────────────────

def build_lammps_data(poscar_text: str, atom_style: str = "atomic") -> str:
    """把 POSCAR 结构转换为 LAMMPS data 文件文本。

    内部用 pymatgen 解析 POSCAR，再经 ase.io.lammpsdata.write_lammps_data
    （ase 3.29）写出：三斜晶胞会由 Prism 正确旋转并写出 xy/xz/yz tilt 因子，
    坐标同步变换到 LAMMPS 盒坐标系，无需手工处理倾斜盒。
    Masses 区总是写出（masses=True），保证温度/速度初始化可用真实质量。

    Args:
        poscar_text: POSCAR 文件内容（多行文本）。位点行支持带氧化态标签
            （如 "Na+"、"Cl-"），配合 atom_style="charge" 使用。
        atom_style: LAMMPS 原子样式，支持 "atomic"（默认）与 "charge"。
            选 "charge" 时要求每个位点都带氧化态电荷信息（POSCAR 位点行写
            元素价态标签即可）；若结构未提供电荷信息则返回错误提示，
            不猜测、不回退为零电荷。

    Returns:
        成功时返回「转换摘要（原子总数 / 元素种类及 type 编号顺序 /
        盒子类型 / atom_style）+ data 文件全文的 ``` 代码块」，可直接整块
        保存为 data.structure；
        失败时返回以"错误："开头的说明文本（POSCAR 无法解析、结构无原子、
        元素符号无法映射 LAMMPS type、atom_style 不支持、charge 缺电荷等）。
    """
    # 1. atom_style 合法性
    atom_style = (atom_style or "").strip().lower()
    if atom_style not in _ATOM_STYLES:
        return (
            f"错误：[E_PARAM] 不支持的 atom_style '{atom_style}'（可选: atomic / charge）"
        )

    # 2. 解析 POSCAR
    try:
        structure = Poscar.from_str(poscar_text).structure
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] POSCAR 解析失败（{e}）"
    n_atoms = len(structure)
    if n_atoms == 0:
        return "错误：[E_PARAM] 结构不含任何原子，无法生成 LAMMPS data 文件"

    # 3. 元素序（LAMMPS type 编号顺序）：沿用 POSCAR 元素出现顺序，
    #    并校验每个符号都能被识别（防元素序异常导致势函数类型错位）
    els = [el.symbol for el in structure.composition.elements]
    for s in els:
        if s not in atomic_numbers:
            return f"错误：[E_PARAM] 元素序异常——无法识别元素 '{s}'，无法建立 LAMMPS type 映射"

    # 4. pymatgen Structure → ase Atoms
    try:
        atoms = AseAtomsAdaptor.get_atoms(structure)
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] Structure 转 ASE Atoms 失败（{e}）"

    # 5. charge 样式需要显式电荷来源（位点氧化态），缺失即报错提示
    if atom_style == "charge":
        charges = _extract_charges(structure)
        if charges is None:
            return (
                "错误：atom_style='charge' 需要每个原子携带氧化态电荷信息"
                "（当前结构未提供）；请在 POSCAR 位点行使用价态标签"
                "（如 'Na+'/'Cl-'），或改用 atom_style='atomic'"
            )
        atoms.set_initial_charges(charges)

    # 6. 经 ase 写出（StringIO 捕获文本；masses=True 显式写质量区）
    buf = io.StringIO()
    try:
        write_lammps_data(
            buf,
            atoms,
            specorder=els,
            masses=True,
            atom_style=atom_style,
            units="metal",
        )
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] LAMMPS data 写出失败（{e}）"
    data_text = buf.getvalue()

    # 7. 盒子类型判定：ASE 仅在需要时写 "xy xz yz" tilt 行
    skewed = "xy xz yz" in data_text

    summary = [
        "## LAMMPS data 转换摘要",
        f"原子总数: {n_atoms}（与 POSCAR 一致）",
        f"元素种类: {', '.join(els)}"
        "（LAMMPS atom type 按此顺序从 1 编号，请与势函数文件的类型顺序核对）",
        "盒子类型: "
        + (
            "非正交三斜盒（含 xy/xz/yz tilt 因子，坐标已旋转到 LAMMPS 盒坐标系）"
            if skewed
            else "正交盒（orthogonal）"
        ),
        f"atom_style: {atom_style}",
    ]
    return "\n".join(summary) + "\n\n## data 文件全文\n```\n" + data_text + "```"


def generate_lammps_inputs(
    calc_type: str = "min",
    potential_line: str = "",
    T: float = 300.0,
    timestep: float = 0.001,
    dump_every: int = 1000,
    data_file: str = "data.structure",
) -> str:
    """生成 in.lammps 输入脚本模板文本（metal 单位，周期性边界）。

    四种计算类型：
    - min    : 两轮 minimize 循环（粗收敛 + 紧判据精修）后 write_data 导出；
    - nvt    : velocity create（温度 T，mom/mag yes）+ fix nvt + dump + run；
    - npt    : 同 nvt，但用 fix npt（Nose-Hoover 温控 + iso 零压控压）；
    - nve_msd: velocity create + compute msd + fix ave/time 把 MSD 直接
               写入 msd.out 文件（含时间列与 dx/dy/dz/总 MSD 四列）+
               fix nve 积分 + dump 轨迹。MSD 走 compute 直出，
               不做 dump 后处理，可直接导入 Origin 作图。

    统一包含：units metal / boundary p p p / read_data / neighbor 与
    neigh_modify / timestep / 势函数区（potential_line 原样嵌入）/ thermo 输出。
    温度阻尼 tdamp=100×timestep、压力阻尼 pdamp=1000×timestep（经验值，
    已写入脚本，可自行调整）。

    Args:
        calc_type: 计算类型，min / nvt / npt / nve_msd 四选一；
            非法值返回"错误：不支持的 calc_type ..."开头文本。
        potential_line: 势函数设置原文（pair_style / pair_coeff 等行），
            原样嵌入脚本的势函数区；留空则生成 TODO 占位注释。
            注意 pair_coeff 中元素的排列顺序必须与 data 文件的
            atom type 编号顺序一致（见 build_lammps_data 返回摘要）。
        T: 目标温度 (K)，用于 velocity create 与恒温器设定（仅 md 类型生效）。
        timestep: 时间步长 (ps，metal 单位)；min 类型同样写出但不影响结果。
        dump_every: 轨迹 dump 及 MSD 文件输出的间隔步数（仅 md 类型生效）。
        data_file: read_data 读取的数据文件名（应与上传的结构文件同名，
            默认 "data.structure"，与 build_lammps_data 的产物对应）。

    Returns:
        成功时返回简短说明 + 完整 in.lammps 脚本的 ``` 代码块
        （总步数以 TODO 注释标出，请按体系自行修改后再提交集群）；
        calc_type 非法时返回"错误：不支持的 calc_type ..."开头文本。
    """
    calc_type = (calc_type or "").strip().lower()
    if calc_type not in _CALC_TYPES:
        return (
            f"错误：[E_PARAM] 不支持的 calc_type '{calc_type}'"
            f"（可选: {' / '.join(_CALC_TYPES)}）"
        )

    label = {
        "min": "min（能量极小化）",
        "nvt": "nvt（正则系综分子动力学）",
        "npt": "npt（等温等压系综分子动力学）",
        "nve_msd": "nve_msd（NVE 积分 + compute msd 直出均方位移）",
    }[calc_type]

    t_str, dt_str = _fmt(T), _fmt(timestep)
    tdamp, pdamp = _fmt(100.0 * timestep), _fmt(1000.0 * timestep)

    parts: list[str] = [_common_head(label, data_file, timestep)]
    parts.append(_potential_block(potential_line))
    parts.append(_THERMO_BLOCK)

    if calc_type == "min":
        parts.append(
            "\n# ---------- 能量极小化：两轮 minimize 循环（粗收敛 + 紧判据精修） ----------\n"
            "min_style       cg\n"
            "minimize        1.0e-6 1.0e-8 5000 50000\n"
            "minimize        1.0e-8 1.0e-10 20000 200000\n"
            "\n# ---------- 收敛结构导出 ----------\n"
            "write_data      data.minimized\n"
        )
    else:
        parts.append(
            "\n# ---------- 速度初始化"
            f"（T={t_str} K，dist gaussian，消整体动量/角动量） ----------\n"
            f"velocity        all create {t_str} {_VELOCITY_SEED}"
            " dist gaussian mom yes mag yes\n"
        )

    if calc_type in ("nvt", "npt"):
        tag = calc_type
        if calc_type == "nvt":
            fix_line = (
                f"fix             integrator all nvt temp {t_str} {t_str} {tdamp}\n"
            )
            fix_note = ""
        else:
            fix_line = (
                f"fix             integrator all npt temp {t_str} {t_str} {tdamp}"
                f" iso 0.0 0.0 {pdamp}\n"
            )
            fix_note = (
                "# 提示: 控压方式 iso 为各向同性零压，"
                "可改为 aniso / tri 保持更多形变自由度\n"
            )
        parts.append(
            f"\n# ---------- {tag.upper()} 系综积分与轨迹输出 ----------\n"
            f"dump            traj all custom {dump_every}"
            f" traj_{tag}.lammpstrj id type x y z\n"
            "dump_modify     traj sort id\n"
            + fix_note
            + fix_line
            + _RUN_LINE
            + "\n"
        )
    elif calc_type == "nve_msd":
        parts.append(
            "\n# ---------- MSD 直接输出（compute msd + fix ave/time 直出文件，不做 dump 后处理） ----------\n"
            "compute         msd all msd com yes\n"
            f"variable        msdt equal step*{_fmt(timestep)}\n"
            f"fix             msd_out all ave/time 1 1 {dump_every}"
            " v_msdt c_msd[1] c_msd[2] c_msd[3] c_msd[4]"
            " file msd.out mode scalar\n"
            "# msd.out 各列: 步数 | 时间(ps) | dx² | dy² | dz² | 总MSD(Å²)，可直接导入 Origin\n"
            "\n# ---------- NVE 积分与轨迹输出 ----------\n"
            "fix             integrator all nve\n"
            f"dump            traj all custom {dump_every}"
            " traj_msd.lammpstrj id type x y z\n"
            "dump_modify     traj sort id\n"
            + _RUN_LINE
            + "\n"
        )

    notes = [
        f"已生成 in.lammps 模板（calc_type={calc_type} | 数据文件={data_file}）",
        "提交前请确认：① 势函数区已填好且类型顺序与 data 文件一致；"
        "② 总步数 TODO 已按体系修改。",
    ]
    if calc_type == "min":
        pass  # min 无额外提示
    elif calc_type == "nve_msd":
        notes.insert(1, "MSD 由 compute msd 经 fix ave/time 直出到 msd.out"
                        "（含时间列），无需对 dump 轨迹做事后统计。")
    else:
        notes.insert(1, f"T={t_str} K，tdamp={tdamp} ps"
                        + (f"，pdamp={pdamp} ps" if calc_type == "npt" else "")
                        + "（Nose-Hoover 经验阻尼，可在脚本中调整）。")

    return "\n".join(notes) + "\n```" + "".join(parts) + "\n```"


def parse_lammps_log(log_text: str) -> str:
    """从 LAMMPS log 文本提取最后一个 thermo 表格，转为 Origin 友好的 tab 分隔文本。

    LAMMPS 每次 run/minimize 都会在 log 里打印一段以 "Step" 开头的
    thermo 列标题 + 若干数值行 + "Loop time" 结尾的热力学表格；
    多段 run（如先 min 再 MD）会产生多个区块，本工具只取最后一个区块。

    解析规则：列名取自 "Step ..." 行；其下与列数相同且能全部解析为数值的
    连续行为数据区，遇到首个不符合的行（如 Loop time / WARNING）即结束。
    数值按原字符串原样保留，不做重排版。已知局限：超过 8 列时 LAMMPS 会把
    表头折行打印，此类折行表头暂不支持。

    Args:
        log_text: LAMMPS 日志内容（log.lammps 全文或片段均可）。

    Returns:
        tab 分隔文本：首行为 "# " 前缀 + tab 分隔列名（Origin 可直接识别
        备注头），其后每行一条数据记录（tab 分隔，原值字符串）；
        未找到任何含数据行的 thermo 表格时返回
        "错误：未找到 thermo 数据"开头文本。
    """
    lines = log_text.splitlines()
    blocks: list[tuple[list[str], list[str]]] = []
    i, n = 0, len(lines)
    while i < n:
        tokens_head = lines[i].split()
        # thermo 列标题行：首 token 必须恰为 "Step"
        if tokens_head[:1] != ["Step"]:
            i += 1
            continue
        cols = tokens_head
        j = i + 1
        rows: list[str] = []
        while j < n:
            parts = lines[j].split()
            if len(parts) != len(cols):
                break  # 列数不符（空行 / Loop time / 下个区块）→ 数据区结束
            try:
                [float(p) for p in parts]
            except ValueError:
                break
            rows.append(lines[j].rstrip())
            j += 1
        if rows:
            blocks.append((cols, rows))
        i = j  # 从数据区结束处继续扫描后续可能的区块

    if not blocks:
        return "错误：[E_PARSE] 未找到 thermo 数据（log 中没有含数据行的 \"Step\" 表格）"

    cols, rows = blocks[-1]
    out = ["# " + "\t".join(cols)]
    out.extend("\t".join(r.split()) for r in rows)
    return "\n".join(out)


# MCP 工具清单（供 main.py 注册消费）
TOOLS = [build_lammps_data, generate_lammps_inputs, parse_lammps_log]
