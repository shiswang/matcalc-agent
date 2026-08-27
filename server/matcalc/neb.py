"""NEB（弹性势垒 / CI-NEB 过渡态搜索）计算输入生成工具集。

提供三个工具：
- generate_neb_endpoints : 起点/终点（端点）结构一致性体检；
- generate_neb_images    : 生成 00..0N 共 images+2 个 image 目录（linear 或 IDPP 插值）；
- generate_neb_incar     : NEB 专用 INCAR 文本。

关于 IDPP 与 DiffusionAnalyzer 的重要备注（实现前已在本地环境核实）：
- pymatgen==2026.5.4 核心包已整体移除扩散分析模块：`pymatgen.analysis.diffusion`
  导入即报 ModuleNotFoundError，且全库（site-packages/pymatgen 递归）检索
  "DiffusionAnalyzer" / "IDPP" 关键字均 0 命中；该功能自 2023 年起拆分至
  独立扩展包 pymatgen-analysis-diffusion，本环境未安装该包。
- 公开资料语义（无法在本环境直接验证，故实现上全部按失败兜底处理）：
  IDPPSolver.run(nimages=N) 返回的插值结构列表【包含首尾两个端点】，
  即总数等于 nimages；因此调用时应传 nimages=images+2 才能得到 images 个中间像。
- 因此本模块对 IDPP 采用防御式实现：运行期延迟导入 + 全程 try/except，
  任何一步失败（扩展包未安装 / API 变动 / 构造或收敛异常 / 返回数量不符）
  都自动回退 linear 插值，并在返回文本中注明"IDPP 失败已回退 linear"。
"""

from __future__ import annotations

import os
import time
from typing import Optional

from pymatgen.core import Structure
from pymatgen.io.vasp import Poscar

from .common import out_dir as _out_dir
from .structures import _to_vasp5_poscar

# 晶格常数差异警告阈值（百分比）：超过则提示用户先统一端点晶格
_LATTICE_WARN_PCT = 2.0


# ─────────────────────────── 内部辅助 ───────────────────────────

def _parse_structure(poscar_text: str, tag: str) -> tuple[Optional[Structure], Optional[str]]:
    """解析 POSCAR 文本；成功返回 (结构, None)，失败返回 (None, 中文错误说明)。"""
    try:
        return Poscar.from_str(poscar_text).structure, None
    except Exception as e:  # noqa: BLE001
        return None, f"{tag} POSCAR 解析失败（{e}）"


def _species_line_tokens(poscar_text: str) -> list[str]:
    """取 POSCAR 第 6 行（VASP5 species 行）的元素 token 列表。

    标准 VASP5 格式：第 1 行注释、第 2 行缩放因子、第 3~5 行晶格矢量、
    第 6 行元素种类及顺序、第 7 行对应计数。文件过短时返回空列表。
    """
    lines = poscar_text.strip().splitlines()
    if len(lines) < 7:
        return []
    return lines[5].split()


def _per_atom_symbols(structure: Structure) -> list[str]:
    """结构的逐原子元素符号序列（插值时按此顺序一一对应）。"""
    return [str(site.specie.symbol) for site in structure]


def _endpoint_check(
    poscar_init: str, poscar_final: str
) -> tuple[list[str], list[str], list[str], Optional[Structure], Optional[Structure]]:
    """端点一致性体检核心逻辑。

    Returns:
        (errors, warnings, info_lines, s_init, s_final)：
        - errors   ：阻断性问题（存在则无法做 NEB）；
        - warnings ：非阻断警告（如晶格差异超阈值）；
        - info_lines：摘要信息行；
        - 结构仅在无阻断错误时有值，否则为 None。
    """
    s_init, err_i = _parse_structure(poscar_init, "起点")
    s_final, err_f = _parse_structure(poscar_final, "终点")
    errors = [e for e in (err_i, err_f) if e]
    warnings: list[str] = []
    info: list[str] = []

    if errors:
        return errors, warnings, info, None, None

    # ---- ① 原子数一致 ----
    n_init, n_final = len(s_init), len(s_final)
    if n_init != n_final:
        errors.append(
            f"原子数不一致: 起点 {n_init} 个 vs 终点 {n_final} 个"
            "（NEB 要求两端点逐原子一一对应）"
        )
    info.append(f"原子数: {n_init} / {n_final}")

    # ---- ② 元素种类与顺序（POSCAR 第 6 行 species 行 + 逐原子序列双重校验）----
    tok_init = _species_line_tokens(poscar_init)
    tok_final = _species_line_tokens(poscar_final)
    if tok_init and tok_final and tok_init != tok_final:
        errors.append(
            "POSCAR 第 6 行元素种类/顺序不一致: "
            f"起点 '{' '.join(tok_init)}' vs 终点 '{' '.join(tok_final)}'"
        )
    info.append(
        "元素种类与顺序（POSCAR 第 6 行）: "
        f"起点 '{' '.join(tok_init)}' / 终点 '{' '.join(tok_final)}'"
    )
    # 逐原子元素序列：分组格式下第 6 行可能相同但组内原子排序不同，仍会导致错位插值
    if n_init == n_final:
        seq_init = _per_atom_symbols(s_init)
        seq_final = _per_atom_symbols(s_final)
        if seq_init != seq_final:
            errors.append(
                "逐原子元素顺序不一致（插值按原子序号一一对应）: "
                f"起点 {''.join(seq_init)} vs 终点 {''.join(seq_final)}"
            )
        else:
            info.append(f"逐原子元素序列: 一致（{''.join(seq_init)}）")

    # ---- ③ 晶格常数差异（>2% 给警告，不阻断）----
    abc_init, abc_final = s_init.lattice.abc, s_final.lattice.abc
    max_pct = 0.0
    for name, a_i, a_f in zip(("a", "b", "c"), abc_init, abc_final):
        pct = abs(a_f - a_i) / a_i * 100.0
        max_pct = max(max_pct, pct)
        if pct > _LATTICE_WARN_PCT:
            warnings.append(
                f"晶格常数 {name} 差异 {pct:.2f}% > {_LATTICE_WARN_PCT:g}% "
                f"（起点 {a_i:.4f} Å → 终点 {a_f:.4f} Å）: 建议先统一两端点晶格再做 NEB"
            )
    info.append(
        f"晶格常数 a,b,c (Å): 起点 "
        f"{abc_init[0]:.4f}, {abc_init[1]:.4f}, {abc_init[2]:.4f} / "
        f"终点 {abc_final[0]:.4f}, {abc_final[1]:.4f}, {abc_final[2]:.4f}"
        f"（最大差异 {max_pct:.2f}%，警告阈值 {_LATTICE_WARN_PCT:g}%）"
    )

    # ---- ④ 体积差异（仅报告，不设阈）----
    vol_init, vol_final = s_init.volume, s_final.volume
    vol_pct = abs(vol_final - vol_init) / vol_init * 100.0
    info.append(
        f"晶胞体积 (Å³): 起点 {vol_init:.4f} / 终点 {vol_final:.4f}（差异 {vol_pct:.2f}%）"
    )

    return errors, warnings, info, s_init, s_final


# ─────────────────────────── MCP 工具 ───────────────────────────

def generate_neb_endpoints(poscar_init: str, poscar_final: str) -> str:
    """NEB 端点体检：校验起点/终点结构是否满足 NEB 插值前提。

    校验项：
    1. 两端点 POSCAR 均可解析（阻断）；
    2. 原子数一致（阻断）：NEB 插值要求两端点逐原子一一对应；
    3. 元素种类与顺序一致（阻断）：同时核对 POSCAR 第 6 行 species 行
       与解析后的逐原子元素序列（防止分组格式下组内排序错位）；
    4. 晶格常数差异百分比（非阻断）：任一方向差异 >2% 给出警告；
    5. 体积差百分比（仅报告，不设阈值）。

    Args:
        poscar_init: 起点结构 POSCAR 文件内容（多行文本，建议用充分弛豫的 CONTCAR）。
        poscar_final: 终点结构 POSCAR 文件内容（多行文本，晶格须与起点一致）。

    Returns:
        结构化中文体检报告；存在不一致项时以"错误："开头并列出全部问题，
        否则为通过报告（可含警告行），可直接用于判断是否继续生成 image。
    """
    errors, warnings, info, _, _ = _endpoint_check(poscar_init, poscar_final)

    if errors:
        lines = [f"错误：[E_PARSE] NEB 端点体检发现 {len(errors)} 处不一致，无法生成 image："]
        lines.extend(f"{i}. {msg}" for i, msg in enumerate(errors, 1))
        lines.append("请修正端点结构（同超胞、同原子序、同晶格）后重试。")
        return "\n".join(lines)

    lines = ["## NEB 端点体检报告"]
    lines.extend(info)
    lines.extend(f"- 警告: {w}" for w in warnings)
    lines.append(
        f"结论: 体检通过（0 处错误，{len(warnings)} 处警告），可进行 NEB 插值"
    )
    return "\n".join(lines)


def _load_idpp_class():
    """延迟加载 pymatgen 扩展包中的 DiffusionAnalyzer（IDPP 插值引擎）。

    单独抽成函数便于测试 monkeypatch：模拟"扩展包未安装"或
    "类构造抛异常"两种失败场景，验证回退 linear 的路径。
    """
    from pymatgen.analysis.diffusion.neb.pathfinder import DiffusionAnalyzer

    return DiffusionAnalyzer


def _idpp_intermediate_structures(
    s_init: Structure, s_final: Structure, images: int
) -> list[Structure]:
    """用 IDPP 方法生成中间 image 结构列表（不含两端点，长度恰为 images）。

    语义备注（详见模块 docstring）：
    - 扩展包 pymatgen-analysis-diffusion 中插值器的 nimages 语义是
      【含首尾端点的总结构数】；故此处传 nimages=images+2，使中间恰好
      images 个，并在剥离端点后二次校验数量，不符立即抛错回退。
    - 任何一步失败（导入失败/API 变动/构造或收敛异常/数量不符）都向上抛
      异常，由调用方捕获后回退 linear 并注明。
    """
    DA = _load_idpp_class()
    da = DA(s_init, s_final, nimages=images + 2)  # 含两端点 → 中间恰为 images 个
    paths = da.get_flattened_path()  # 预期含首尾端点共 images+2 个结构
    mids = list(paths)[1:-1]  # 剥离首尾端点，只留中间段
    if len(mids) != images:
        raise RuntimeError(
            f"IDPP 返回结构数不符: 期望中段 {images} 个，实得 {len(mids)} 个"
        )
    return mids


def generate_neb_images(
    poscar_init: str,
    poscar_final: str,
    images: int = 5,
    method: str = "linear",
    project: Optional[str] = None,
    save: bool = True,
) -> str:
    """生成 NEB image 目录集：00..0N 共 images+2 个目录。

    目录约定：
    - 00          ：起点副本；
    - 0{N}（末位） ：终点副本；
    - 中间 images 个：按 method 插值生成的中间像。
    目录名两位数字零填充（00、01、…、06 对应 images=5）。

    插值方法：
    - "linear"：分数坐标线性插值（自实现，逐原子一一对应，最可靠）；
    - "idpp" ：调用 pymatgen 扩展包的 DiffusionAnalyzer 做 IDPP 弹性插值；
      该扩展包本环境未安装（核心包 2026.x 已移除扩散模块），故实现为
      延迟导入 + 全程 try/except，任何失败都自动回退 linear 并在返回文本
      注明"IDPP 失败已回退 linear"。

    Args:
        poscar_init: 起点结构 POSCAR 文本（建议充分弛豫的 CONTCAR）。
        poscar_final: 终点结构 POSCAR 文本（须先通过端点体检）。
        images: 中间 image 数量（>=1）；总目录数 = images + 2，
            写入 INCAR 的 IMAGES 标签应等于该值。
        method: 插值方法 "linear" 或 "idpp"，默认 "linear"。
        project: 可选项目名——产物保存到 outputs/<project>/inputs/neb_<方法>_<时间戳>/。
        save: 是否落盘（默认 True）；落盘时每个子目录写一个
            VASP5 分组格式 POSCAR（与 server.matcalc.structures 保持一致）。

    Returns:
        中文摘要：目录数、IMAGES 应设值、插值方法、（save 时）落盘根路径。
        images<1、method 非法或端点体检不通过时返回以"错误："开头的文本。
    """
    # ---- 参数校验 ----
    if not isinstance(images, int) or isinstance(images, bool) or images < 1:
        return f"错误：[E_PARAM] images 需为 >=1 的整数（当前值 {images!r}）"
    method_l = (method or "").strip().lower()
    if method_l not in ("linear", "idpp"):
        return f"错误：[E_PARAM] method 仅支持 'linear' / 'idpp'，收到 '{method}'"

    # ---- 端点体检（不通过直接透传错误报告）----
    check_report = generate_neb_endpoints(poscar_init, poscar_final)
    if check_report.startswith("错误"):
        return check_report

    s_init, err_i = _parse_structure(poscar_init, "起点")
    s_final, err_f = _parse_structure(poscar_final, "终点")
    if err_i or err_f:  # 理论上已被端点体检拦截，双保险
        return "\n".join(e for e in (err_i, err_f) if e)

    # ---- 插值：先生成中间像文本（失败回退 linear）----
    method_note = ""
    effective = method_l
    mid_texts: list[str] = []
    if method_l == "idpp":
        try:
            mids = _idpp_intermediate_structures(s_init, s_final, images)
            mid_texts = [_to_vasp5_poscar(m) for m in mids]
            method_note = "idpp（pymatgen DiffusionAnalyzer，IDPP 弹性插值）"
        except Exception as e:  # noqa: BLE001 —— 包未安装/API 变动/收敛失败一律回退
            method_note = f"idpp → IDPP 失败已回退 linear（原因: {type(e).__name__}: {e}）"
            effective = "linear"
            mid_texts = []  # 清空，走下方 linear 分支重新生成
    if not mid_texts:
        # linear：分数坐标线性插值 c(t) = (1-t)*c_init + t*c_final
        f_init = s_init.frac_coords
        f_final = s_final.frac_coords
        lattice = s_init.lattice
        species = list(s_init.species)
        mids = [
            Structure(
                lattice,
                species,
                [(1.0 - t) * a + t * b for a, b in zip(f_init, f_final)],
            )
            for t in (i / (images + 1) for i in range(1, images + 1))
        ]
        mid_texts = [_to_vasp5_poscar(m) for m in mids]
        if not method_note:
            method_note = "linear（分数坐标线性插值，自实现最可靠）"

    # ---- 落盘：<root>/00..0N/POSCAR ----
    save_note = ""
    root = ""
    if save:
        root = os.path.join(
            _out_dir(project, "input"), f"neb_{effective}_{int(time.time())}"
        )
        os.makedirs(root, exist_ok=True)
        all_texts = [_to_vasp5_poscar(s_init)] + mid_texts + [_to_vasp5_poscar(s_final)]
        for idx, txt in enumerate(all_texts):
            d = os.path.join(root, f"{idx:02d}")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "POSCAR"), "w", encoding="utf-8", newline="\n") as f:
                f.write(txt)
        save_note = (
            f"\n落盘根路径: {root}（共 {len(all_texts)} 个子目录，各含 VASP5 分组格式 POSCAR）"
        )

    # ---- 中文摘要 ----
    total = images + 2
    lines = [
        "## NEB image 集",
        f"目录数: {total}（00=起点副本, {total - 1:02d}=终点副本, 中间 {images} 个插值 image）",
        f"插值方法: {method_note}",
        f"IMAGES 应设值: {images}（写入 NEB INCAR 的 IMAGES 标签；MPI 核数须被其整除）",
    ]
    if save:
        lines.append(save_note.lstrip("\n"))
    lines.append(
        "后续步骤: 用 generate_neb_incar 生成 INCAR；各目录放同一份 KPOINTS/POTCAR 后提交"
    )
    return "\n".join(lines)


def generate_neb_incar(
    images: int = 5,
    ci: bool = True,
    ediffg: float = -0.03,
    potim: float = 0.2,
    ismear: int = 0,
    sigma: float = 0.05,
    encut: int = 400,
) -> str:
    """生成 NEB（CI-NEB）专用 INCAR 文本。

    参数取 VASP/VTST 社区常用惯例：IBRION=3 阻尼分子动力学弛豫、
    SPRING=-5 默认弹簧刚度、ICHAIN=0 选择 NEB 方案、ISYM=0 关闭对称性。

    Args:
        images: 中间 image 数量（>=1），写入 IMAGES 标签；MPI 核数须被其整除。
        ci: 是否开启 CI 爬坡（LCLIMB=.TRUE.，默认 True）；
            注意 CI 爬坡需要 VTST 编译版 VASP，普通 NEB 可去掉该行。
        ediffg: 收敛判据 (eV/Å)，负值表示按原子最大力收敛（默认 -0.03）。
        potim: IBRION=3 的初始步长（默认 0.2）。
        ismear: 展宽方式（默认 0，配合 SIGMA）。
        sigma: 展宽宽度 (eV)（默认 0.05）。
        encut: 平面波截断能 (eV)（默认 400）。

    Returns:
        NEB 专用 INCAR 文本（含头两行注释说明与尾部使用提示注释块）；
        images<1 时返回以"错误："开头的文本。
    """
    if not isinstance(images, int) or isinstance(images, bool) or images < 1:
        return f"错误：[E_PARAM] images 需为 >=1 的整数（当前值 {images!r}）"

    lines = [
        "### MatCalcAgent 生成的 NEB INCAR（弹性势垒 / 过渡态搜索）###",
        "# 配合 generate_neb_images 生成的 00..0N image 目录使用；VTST 编译版 VASP 支持全部标签",
        "SYSTEM = NEB",
        f"ENCUT = {encut}",
        "PREC = Accurate",
        "EDIFF = 1E-5",
        "IBRION = 3           # 阻尼分子动力学式离子弛豫（NEB 惯例）",
        f"POTIM = {potim:g}",
        "NSW = 200",
        f"EDIFFG = {ediffg:g}",
        f"ISMEAR = {ismear}",
        f"SIGMA = {sigma:g}",
        "ISYM = 0             # NEB 必须关闭对称性",
        f"IMAGES = {images}",
        "SPRING = -5",
        "ICHAIN = 0           # 0 = 普通 NEB",
    ]
    if ci:
        lines.append(
            "LCLIMB = .TRUE.      # CI 爬坡需 VTST 编译版 VASP；普通 NEB 可去掉此行"
        )
    lines += [
        "",
        "# ===== 使用提示 =====",
        "# ① MPI 核数必须能被 IMAGES 整除（每个 image 分配相同核数）",
        "# ② 大超胞体系 k 点可用 Gamma 点以节省算力",
        "# ③ 收敛与否看各 image 的最大原子力（EDIFFG），而非总能变化",
    ]
    return "\n".join(lines) + "\n"


# MCP 工具注册清单（main.py 按此挂载）
TOOLS = [generate_neb_endpoints, generate_neb_images, generate_neb_incar]
