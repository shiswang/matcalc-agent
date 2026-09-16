"""结构建模：化学式/原型建模、POSCAR 解析与摘要、超胞扩展、表面切面。

（R2 自 main.py 原样迁移，函数体未改动）"""

from __future__ import annotations

import math
import os
import time
from typing import Optional

from pymatgen.core import Composition, Element, Structure
from pymatgen.core.lattice import Lattice
from pymatgen.io.vasp import Poscar
from pymatgen.symmetry.groups import SpaceGroup

from .common import out_dir as _out_dir

# 常见元素原子体积近似（Å³/原子），用于无晶格参数时估算初始晶格
_ATOMIC_VOLUME: dict[str, float] = {
    "Li": 21.0, "Na": 39.0, "K": 75.0, "Mg": 23.0, "Ca": 43.0,
    "Zr": 23.0, "Ti": 17.0, "V": 16.0, "Cr": 12.0, "Mn": 12.0,
    "Fe": 12.0, "Co": 11.0, "Ni": 11.0, "Cu": 12.0, "Zn": 15.0,
    "Al": 16.0, "Ga": 18.0, "Ge": 27.0, "Si": 20.0, "P": 18.0,
    "S": 26.0, "Cl": 35.0, "F": 18.0, "O": 14.0, "N": 14.0,
    "C": 11.0, "Se": 30.0, "Br": 40.0, "I": 55.0, "Ba": 63.0,
    "Sr": 56.0, "Sn": 36.0, "Nb": 18.0, "Mo": 16.0, "W": 16.0,
    "Ag": 17.0, "Au": 17.0, "Pt": 15.0, "Pd": 15.0,
}
_DEFAULT_VOLUME = 20.0

# Jmol 风格常用元素配色（RGB 0-1），fallback 灰色
_JMOL_COLORS: dict[str, tuple[float, float, float]] = {
    "Li": (0.42, 0.53, 0.62), "Na": (0.27, 0.36, 0.81), "K": (0.55, 0.31, 0.73),
    "Mg": (0.54, 0.60, 0.60), "Ca": (0.36, 0.60, 0.60), "Sr": (0.37, 0.66, 0.66),
    "Ba": (0.00, 0.72, 0.72), "Ti": (0.48, 0.48, 0.51), "Zr": (0.59, 0.59, 0.63),
    "Fe": (0.89, 0.42, 0.45), "Co": (0.60, 0.64, 0.73), "Ni": (0.47, 0.62, 0.78),
    "Cu": (0.82, 0.51, 0.25), "Zn": (0.49, 0.62, 0.71), "Mn": (0.62, 0.44, 0.67),
    "Al": (0.52, 0.57, 0.63), "Si": (0.62, 0.62, 0.67), "Ge": (0.38, 0.38, 0.44),
    "Sn": (0.67, 0.67, 0.70), "P": (0.80, 0.47, 0.15), "S": (0.95, 0.82, 0.24),
    "Cl": (0.22, 0.80, 0.16), "F": (0.55, 0.77, 0.91), "O": (0.91, 0.24, 0.20),
    "N": (0.28, 0.45, 0.89), "C": (0.32, 0.32, 0.32), "Se": (0.63, 0.36, 0.16),
    "Br": (0.53, 0.20, 0.10), "I": (0.42, 0.15, 0.53), "Ag": (0.47, 0.47, 0.51),
    "Au": (0.90, 0.70, 0.20), "Pt": (0.67, 0.67, 0.67), "Pd": (0.47, 0.47, 0.51),
    "Nb": (0.37, 0.44, 0.66), "Mo": (0.39, 0.39, 0.51), "W": (0.35, 0.43, 0.61),
}
_DEFAULT_COLOR = (0.6, 0.6, 0.6)

# ─────────────────────────── 建模辅助 ───────────────────────────

def _estimate_lattice(composition: Composition) -> Lattice:
    """按元素原子体积之和估算简单立方初始晶格（粗略，仅作初始猜测）。"""
    total_volume = sum(
        _ATOMIC_VOLUME.get(el.symbol, _DEFAULT_VOLUME) * int(comp)
        for el, comp in composition.items()
    )
    a = round(total_volume ** (1.0 / 3.0), 4)
    return Lattice.cubic(a)


def _fcc_basis() -> list[list[float]]:
    return [[0.0, 0.0, 0.0], [0.5, 0.5, 0.0], [0.5, 0.0, 0.5], [0.0, 0.5, 0.5]]


def _bcc_basis() -> list[list[float]]:
    return [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]


def _structure_summary(structure: Structure) -> str:
    """生成结构摘要文本（预览用）。"""
    lines = [
        f"化学式（约化）: {structure.composition.reduced_formula}",
        f"化学式（原胞）: {structure.composition.formula}",
        f"原子总数: {structure.num_sites}",
        f"晶格参数 a,b,c (Å): {structure.lattice.abc[0]:.4f}, {structure.lattice.abc[1]:.4f}, {structure.lattice.abc[2]:.4f}",
        f"晶格角度 α,β,γ (°): {structure.lattice.angles[0]:.2f}, {structure.lattice.angles[1]:.2f}, {structure.lattice.angles[2]:.2f}",
        f"晶胞体积 (Å³): {structure.volume:.4f}",
        f"密度 (g/cm³): {structure.density:.4f}",
        "元素占比: "
        + ", ".join(
            f"{el.symbol}×{int(structure.composition[el])}" for el in structure.composition
        ),
    ]
    return "\n".join(lines)


def _to_vasp5_poscar(structure: Structure) -> str:
    """构造 VASP5 标准分组 POSCAR（按元素分组物种行与计数行）。

    注意：pymatgen 2026 新版 Poscar.get_str() 逐原子输出物种行
    （Na Cl Na Cl ...），不符合 VASP 要求，故手动构造。
    """
    from collections import defaultdict

    comp = structure.composition
    els = [el.symbol for el in comp.elements]
    counts = [int(comp[el]) for el in els]

    by_el: dict[str, list] = defaultdict(list)
    for site in structure:
        by_el[site.species_string].append(site.frac_coords)

    lines = [
        structure.composition.reduced_formula,
        "1.0",
    ]
    for row in structure.lattice.matrix:
        lines.append(" ".join(f"{x:.10f}" for x in row))
    lines.append(" ".join(els))
    lines.append(" ".join(str(c) for c in counts))
    lines.append("direct")
    for el in els:
        for fc in by_el[el]:
            lines.append(" ".join(f"{x:.10f}" for x in fc) + f" {el}")
    return "\n".join(lines) + "\n"


def _elements_of(composition: Composition) -> list[str]:
    return [el.symbol for el in composition.elements]


def _check_ratio(composition: Composition, expected: dict[str, int], proto: str) -> Optional[str]:
    """校验组成是否符合原型化学计量比。"""
    actual = {el.symbol: int(composition[el]) for el in composition.elements}
    expected_str = " ".join(f"{k}{v}" for k, v in expected.items())
    if sorted(actual.values()) != sorted(expected.values()):
        return (
            f"错误：原型 {proto} 要求化学计量比 {expected_str}，"
            f"实际为 {' '.join(f'{k}{v}' for k, v in actual.items())}"
        )
    return None


def _build_prototype(
    prototype: str, composition: Composition, lattice_params: Optional[str]
) -> tuple[Structure, str]:
    """按原型模板构建真实晶体结构。返回 (structure, 说明文本)。"""
    els = _elements_of(composition)
    cubic_a: Optional[float] = None
    lattice: Lattice
    note_lines: list[str] = []

    # 解析用户提供的晶格参数
    if lattice_params:
        vals = [float(x) for x in lattice_params.replace(" ", "").split(",")]
        if len(vals) == 6:
            lattice = Lattice.from_parameters(*vals)
            note_lines.append(f"使用用户提供的晶格参数: {lattice_params}")
        else:
            raise ValueError("lattice_parameters 需为 6 个数值（a,b,c,alpha,beta,gamma）")
    else:
        # 估算晶格：按原型经验公式（粗略，建议从文献核实））
        r = {el: float(Element(el).atomic_radius or 1.0) for el in els}
        if prototype in ("rocksalt", "zincblende"):
            cubic_a = round(2.0 * (r[els[0]] + r[els[1]]), 3)
        elif prototype == "perovskite":
            cubic_a = round(2.0 * (r[els[0]] + r[els[2]]), 3)
        elif prototype == "fluorite":
            cubic_a = round(2.0 * (r[els[0]] + r[els[1]]), 3)
        elif prototype in ("bcc", "fcc"):
            cubic_a = round(2.0 * r[els[0]], 3)
        elif prototype == "hcp":
            cubic_a = round(2.0 * r[els[0]], 3)
        else:  # pragma: no cover
            raise ValueError(f"未知原型: {prototype}")
        lattice = Lattice.cubic(cubic_a) if prototype != "hcp" else Lattice.hexagonal(cubic_a, round(1.633 * cubic_a, 3))
        note_lines.append(f"晶格参数按元素半径估算（{prototype} 经验公式）: a={cubic_a} Å，建议从文献核实")

    species: list[str] = []
    coords: list[list[float]] = []
    bases: list[list[float]] = [[0.0, 0.0, 0.0]]

    if prototype == "rocksalt":
        err = _check_ratio(composition, {els[0]: 1, els[1]: 1}, "rocksalt")
        if err:
            raise ValueError(err)
        bases = _fcc_basis()
        for b in bases:
            species.append(els[0])
            coords.append(b)
            species.append(els[1])
            coords.append([b[0] + 0.5, b[1] + 0.5, b[2] + 0.5])
        note_lines.append(f"岩盐结构（{els[0]} 在 FCC 位点，{els[1]} 在 (0.5,0.5,0.5) 偏移位点）")
    elif prototype == "zincblende":
        err = _check_ratio(composition, {els[0]: 1, els[1]: 1}, "zincblende")
        if err:
            raise ValueError(err)
        bases = _fcc_basis()
        for b in bases:
            species.append(els[0])
            coords.append(b)
            species.append(els[1])
            coords.append([b[0] + 0.25, b[1] + 0.25, b[2] + 0.25])
        note_lines.append(f"闪锌矿结构（{els[0]} FCC + {els[1]} (0.25,0.25,0.25) 偏移）")
    elif prototype == "perovskite":
        err = _check_ratio(composition, {els[0]: 1, els[1]: 1, els[2]: 3}, "perovskite")
        if err:
            raise ValueError(err)
        species = [els[0], els[1], els[2], els[2], els[2]]
        coords = [
            [0.0, 0.0, 0.0],
            [0.5, 0.5, 0.5],
            [0.5, 0.5, 0.0],
            [0.5, 0.0, 0.5],
            [0.0, 0.5, 0.5],
        ]
        note_lines.append(f"理想钙钛矿结构（A={els[0]} 角位，B={els[1]} 体心，O={els[2]} 面心；未考虑 tilting）")
    elif prototype == "fluorite":
        err = _check_ratio(composition, {els[0]: 1, els[1]: 2}, "fluorite")
        if err:
            raise ValueError(err)
        bases = _fcc_basis()
        for b in bases:
            species.append(els[0])
            coords.append(b)
            species.append(els[1])
            coords.append([b[0] + 0.25, b[1] + 0.25, b[2] + 0.25])
            species.append(els[1])
            coords.append([b[0] + 0.75, b[1] + 0.75, b[2] + 0.75])
        note_lines.append(f"萤石结构（{els[0]} FCC + {els[1]} 在 (0.25,0.25,0.25)/(0.75,0.75,0.75)）")
    elif prototype == "bcc":
        if len(els) != 1:
            raise ValueError(f"错误：bcc 原型要求单一元素，实际为 {els}")
        bases = _bcc_basis()
        for b in bases:
            species.append(els[0])
            coords.append(b)
        note_lines.append("体心立方（bcc）")
    elif prototype == "fcc":
        if len(els) != 1:
            raise ValueError(f"错误：fcc 原型要求单一元素，实际为 {els}")
        bases = _fcc_basis()
        for b in bases:
            species.append(els[0])
            coords.append(b)
        note_lines.append("面心立方（fcc）")
    elif prototype == "hcp":
        if len(els) != 1:
            raise ValueError(f"错误：hcp 原型要求单一元素，实际为 {els}")
        species = [els[0], els[0]]
        coords = [[0.0, 0.0, 0.0], [1.0 / 3.0, 2.0 / 3.0, 0.5]]
        note_lines.append("六方密堆（hcp），c/a=1.633（理想值）")
    else:  # pragma: no cover
        raise ValueError(f"未知原型: {prototype}")

    structure = Structure(lattice, species, coords, coords_are_cartesian=False)
    return structure, "\n".join(note_lines)


# ─────────────────────────── MCP 工具 ───────────────────────────

def build_structure(
    composition: str,
    lattice_parameters: Optional[str] = None,
    spacegroup: Optional[int] = None,
    prototype: Optional[str] = None,
    save: bool = True,
    project: Optional[str] = None,
) -> str:
    """由化学式生成晶体结构。

    Args:
        composition: 化学式，如 "Li2ZrCl6"、"NaCl"、"Fe2O3"。
        lattice_parameters: 可选，格式 "a,b,c,alpha,beta,gamma"
            （a/b/c 单位为 Å，角度为度），如 "10.2,10.2,10.2,90,90,90"；
            缺省时按原型经验公式或原子体积估算。
        spacegroup: 可选，空间群编号（1-230）；M1 仅做合法性校验，
            Wyckoff 位点级建模在后续里程碑实现。
        prototype: 可选，原型模板：rocksalt（岩盐 AB）/ zincblende（闪锌矿 AB）/
            perovskite（钙钛矿 ABO3）/ fluorite（萤石 AB2）/ bcc / fcc / hcp。
        save: 是否将 POSCAR 保存到 outputs 目录（默认 True）。
        project: 可选项目名——产物保存到 outputs/<project>/structures/。

    Returns:
        结构摘要 + 建模说明 + POSCAR 文本（含保存路径）。
    """
    # 1. 解析化学式
    try:
        comp = Composition(composition)
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] 无法解析化学式 '{composition}'（{e}）"
    comp = comp.reduced_composition
    if comp.num_atoms == 0:
        return "错误：化学式不包含任何原子"

    # 2. 构建结构
    structure: Structure
    proto_note = ""
    try:
        if prototype:
            prototype = prototype.strip().lower()
            structure, proto_note = _build_prototype(prototype, comp, lattice_parameters)
        else:
            # 初始粗略结构（M0 逻辑）：每元素一个位点
            if lattice_parameters:
                vals = [float(x) for x in lattice_parameters.replace(" ", "").split(",")]
                if len(vals) != 6:
                    return "错误：[E_PARAM] lattice_parameters 需为 6 个数值（a,b,c,alpha,beta,gamma）"
                lattice = Lattice.from_parameters(*vals)
            else:
                lattice = _estimate_lattice(comp)
            species: list[str] = []
            coords: list[list[float]] = []
            n_el = len(comp.elements)
            for i, el in enumerate(comp.elements):
                species.append(el.symbol)
                t = 0.125 + 0.25 * i / max(n_el - 1, 1)
                coords.append([t, t, t])
            structure = Structure(lattice, species, coords, coords_are_cartesian=False)
            proto_note = "初始粗略结构（每元素 1 个位点），正式建模请用 prototype 参数"
    except ValueError as e:
        return f"错误：[E_PARAM] {e}"
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] 结构构建失败（{e}）"

    # 3. 空间群校验（仅合法性）
    sg_note = "未指定"
    if spacegroup is not None:
        try:
            sg = SpaceGroup.from_int_number(spacegroup)
            sg_note = f"{spacegroup}（{sg.symbol}）— 仅校验，未做 Wyckoff 填充"
        except Exception as e:  # noqa: BLE001
            return f"错误：[E_PARAM] 空间群编号 {spacegroup} 不合法（{e}）"

    poscar_str = _to_vasp5_poscar(structure)

    # 4. 保存
    save_note = ""
    if save:
        fpath = os.path.join(_out_dir(project, "structure"), f"{comp.reduced_formula}_{int(time.time())}.vasp")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(poscar_str)
        save_note = f"\n已保存: {fpath}"

    return (
        f"请求化学式: {comp.reduced_formula}（约化）\n"
        f"建模方式: {proto_note}\n\n"
        f"## 结构摘要\n{_structure_summary(structure)}\n"
        f"空间群: {sg_note}\n"
        f"## POSCAR\n```\n{poscar_str}\n```{save_note}"
    )


def parse_poscar(poscar_text: str) -> str:
    """解析 POSCAR 文本，返回结构摘要。

    Args:
        poscar_text: POSCAR 文件内容（多行文本）。

    Returns:
        结构摘要（晶格、元素、原子数、密度等）。
    """
    try:
        structure = Poscar.from_str(poscar_text).structure
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] POSCAR 解析失败（{e}）"
    return f"## 结构摘要\n{_structure_summary(structure)}"

def make_supercell(poscar_text: str, a: int = 2, b: int = 2, c: int = 2) -> str:
    """将结构扩展为 a×b×c 超胞并输出 POSCAR。

    Args:
        poscar_text: POSCAR 文本。
        a/b/c: 各方向扩胞倍数。

    Returns:
        新 POSCAR 文本（可直接保存或上传）。
    """
    st = Poscar.from_str(poscar_text).structure
    sup = st.copy()
    sup.make_supercell([a, b, c])
    head = (
        f"超胞 {a}x{b}x{c}: {len(st)} 原子 → {len(sup)} 原子, "
        f"V={sup.volume:.2f} Å³\n```\n"
    )
    return head + _to_vasp5_poscar(sup) + "```"


def cleave_surface(poscar_text: str, miller: str, slab_height: float = 12.0, vacuum: float = 12.0) -> str:
    """切表面模型（Slab）：按米勒指数生成表面板层 + 真空层（借鉴 VASPKIT 28x）。

    Args:
        poscar_text: 体相 POSCAR 文本。
        miller: 米勒指数，如 "1 1 0" 或 "-1 -1 1"。
        slab_height: 板层最小厚度 (Å)。
        vacuum: 真空层厚度 (Å)。

    Returns:
        生成的 slab 数量与第一个端型的 POSCAR 文本。
    """
    from pymatgen.core.surface import SlabGenerator

    st = Poscar.from_str(poscar_text).structure
    hkl = tuple(int(x) for x in miller.replace(",", " ").split())
    if len(hkl) != 3:
        return f"错误: [E_PARAM] miller 需要三个整数，收到 '{miller}'"
    gen = SlabGenerator(st, hkl, min_slab_size=slab_height, min_vacuum_size=vacuum, primitive=False)
    slabs = gen.get_slabs(symmetrize=True)
    if not slabs:
        return f"错误: ({hkl[0]} {hkl[1]} {hkl[2]}) 未生成对称 slab，尝试调整厚度或关闭对称化"
    first = slabs[0]
    info = [
        f"({hkl[0]} {hkl[1]} {hkl[2]}) 表面: 共 {len(slabs)} 个对称端型",
        f"slab 原子数: {len(first)}, 板层 {slab_height} Å + 真空 {vacuum} Å",
        "提示: 不同端型表面能不同，建议分别计算后比较。",
    ]
    return "\n".join(info) + "\n```\n" + _to_vasp5_poscar(first) + "```"


# ─────────────────── S8：ASE/MP 向建模栈（一期） ───────────────────

def _parse_any_structure(text: str, fmt: str = "auto") -> tuple[Optional[Structure], str]:
    """解析 POSCAR / CIF 文本；返回 (structure, 识别格式) 或 (None, 错误)。"""
    raw = (text or "").strip()
    if not raw:
        return None, "错误：[E_PARAM] 结构文本为空"
    candidates: list[str]
    if fmt in ("auto", "", None):
        head = raw.lstrip()[:80].lower()
        if head.startswith("data_") or "_cell_length_a" in raw[:2000].lower():
            candidates = ["cif", "poscar"]
        else:
            candidates = ["poscar", "cif"]
    elif str(fmt).lower() in ("poscar", "vasp"):
        candidates = ["poscar"]
    elif str(fmt).lower() == "cif":
        candidates = ["cif"]
    else:
        return None, f"错误：[E_PARAM] format 仅支持 auto|poscar|cif，收到 '{fmt}'"

    last_err = ""
    for kind in candidates:
        try:
            if kind == "poscar":
                st = Poscar.from_str(raw).structure
            else:
                from pymatgen.io.cif import CifParser

                parser = CifParser.from_str(raw)
                structs = parser.parse_structures(primitive=False)
                if not structs:
                    last_err = "CIF 无结构"
                    continue
                st = structs[0]
            if st is None or len(st) == 0:
                last_err = "解析结果为空结构"
                continue
            return st, kind
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            continue
    return None, f"错误：[E_PARSE] 无法解析结构文本（{last_err}）"


def import_structure(
    structure_text: str,
    fmt: str = "auto",
    save: bool = True,
    project: Optional[str] = None,
) -> str:
    """导入 POSCAR 或 CIF，归一为项目统一 VASP5 POSCAR。

    Args:
        structure_text: POSCAR 或 CIF 原文。
        fmt: auto | poscar | cif（auto 按内容嗅探）。
        save: 是否写入 outputs/<project>/structures/。
        project: 项目名。

    Returns:
        摘要 + 归一 POSCAR；解析失败返回"错误："开头。
    """
    st, kind = _parse_any_structure(structure_text, fmt)
    if st is None:
        return kind
    poscar_str = _to_vasp5_poscar(st)
    save_note = ""
    if save:
        fname = f"import_{st.composition.reduced_formula}_{int(time.time())}.vasp"
        fpath = os.path.join(_out_dir(project, "structure"), fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(poscar_str)
        save_note = f"\n已保存: {fpath}"
    return (
        f"识别格式: {kind}\n"
        f"## 结构摘要\n{_structure_summary(st)}\n"
        f"## POSCAR\n```\n{poscar_str}\n```{save_note}"
    )


def build_from_spacegroup(
    composition: str,
    spacegroup: int,
    lattice_parameters: Optional[str] = None,
    save: bool = True,
    project: Optional[str] = None,
) -> str:
    """按空间群 + 化学式用对称操作展开晶体（Wyckoff 级建模）。

    与 build_structure 的区别：真正按 SpaceGroup 生成多原子晶胞，
    而非仅校验编号。适用于岩盐/萤石/钙钛矿等常见原型之外的对称建模。

    Args:
        composition: 化学式，如 "NaCl"、"TiO2"。
        spacegroup: 空间群编号 1–230。
        lattice_parameters: 可选 "a,b,c,alpha,beta,gamma"；缺省按原子体积估算。
        save/project: 落盘控制。

    Returns:
        摘要 + POSCAR；失败返回"错误："。
    """
    try:
        comp = Composition(composition).reduced_composition
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] 无法解析化学式 '{composition}'（{e}）"
    els = _elements_of(comp)
    if not els:
        return "错误：[E_PARAM] 化学式不含元素"

    if lattice_parameters:
        vals = [float(x) for x in lattice_parameters.replace(" ", "").split(",")]
        if len(vals) != 6:
            return "错误：[E_PARAM] lattice_parameters 需 6 个数值"
        lattice = Lattice.from_parameters(*vals)
    else:
        lattice = _estimate_lattice(comp)

    # 常见原型的高对称位点（0,0,0）起；多元素时在等价位点上铺开
    # Structure.from_spacegroup 需要 (specie, coords) 列表
    try:
        sg = SpaceGroup.from_int_number(int(spacegroup))
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARAM] 空间群 {spacegroup} 不合法（{e}）"

    # 为每个元素分配一个初始分数坐标（沿体对角线），由对称操作展开
    coords = []
    n_el = len(els)
    for i, sym in enumerate(els):
        t = 0.0 if n_el == 1 else i * 0.5 / max(n_el - 1, 1)
        coords.append([t, t, t])
    try:
        st = Structure.from_spacegroup(int(spacegroup), lattice, els, coords)
    except Exception as e:  # noqa: BLE001
        return (
            f"错误：[E_PARSE] 空间群 {spacegroup}({sg.symbol}) 与组成 "
            f"{comp.reduced_formula} 无法自动展开（{e}）；"
            "请改用 prototype 建模或提供 CIF/POSCAR"
        )

    poscar_str = _to_vasp5_poscar(st)
    save_note = ""
    if save:
        fpath = os.path.join(
            _out_dir(project, "structure"),
            f"{comp.reduced_formula}_sg{spacegroup}_{int(time.time())}.vasp",
        )
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(poscar_str)
        save_note = f"\n已保存: {fpath}"
    return (
        f"空间群: {spacegroup}（{sg.symbol}）\n"
        f"## 结构摘要\n{_structure_summary(st)}\n"
        f"## POSCAR\n```\n{poscar_str}\n```{save_note}"
    )


def edit_structure(
    poscar_text: str,
    op: str,
    site_index: Optional[int] = None,
    element_from: Optional[str] = None,
    element_to: Optional[str] = None,
    element: Optional[str] = None,
    frac_coords: Optional[str] = None,
    cart_coords: Optional[str] = None,
    scale: Optional[float] = None,
    save: bool = True,
    project: Optional[str] = None,
) -> str:
    """结构编辑：代位 / 空位 / 间隙插入 / 等比缩放（ASE 缺陷工程常用操作）。

    Args:
        poscar_text: 输入 POSCAR。
        op: substitute | vacancy | insert | scale。
        site_index: 0 起始的位点下标（substitute/vacancy）。
        element_from / element_to: 代位时源/目标元素；site_index 省略则替换全部 from。
        element: insert 时插入的元素。
        frac_coords / cart_coords: insert 坐标，格式 "x,y,z"（二选一）。
        scale: op=scale 时的晶格缩放因子（体积变为 factor³）。
        save/project: 落盘。

    Returns:
        新 POSCAR + 摘要；失败"错误："。
    """
    st, err = _parse_any_structure(poscar_text, "poscar")
    if st is None:
        return err
    op_n = (op or "").strip().lower()
    note = ""
    try:
        if op_n == "substitute":
            if not element_to:
                return "错误：[E_PARAM] substitute 需要 element_to"
            if site_index is not None:
                idx = int(site_index)
                if not 0 <= idx < len(st):
                    return f"错误：[E_PARAM] site_index={idx} 越界（0..{len(st)-1}）"
                old = st[idx].specie.symbol
                if element_from and old != element_from:
                    return f"错误：[E_PARAM] site {idx} 是 {old}，不是 {element_from}"
                st.replace(idx, element_to)
                note = f"代位 site {idx}: {old} → {element_to}"
            else:
                if not element_from:
                    return "错误：[E_PARAM] 无 site_index 时需要 element_from"
                n = 0
                for i in range(len(st) - 1, -1, -1):
                    if st[i].specie.symbol == element_from:
                        st.replace(i, element_to)
                        n += 1
                if n == 0:
                    return f"错误：[E_PARAM] 结构中无元素 {element_from}"
                note = f"批量代位 {element_from}→{element_to}：{n} 个位点"
        elif op_n == "vacancy":
            if site_index is None:
                return "错误：[E_PARAM] vacancy 需要 site_index"
            idx = int(site_index)
            if not 0 <= idx < len(st):
                return f"错误：[E_PARAM] site_index={idx} 越界（0..{len(st)-1}）"
            old = st[idx].specie.symbol
            st.remove_sites([idx])
            note = f"空位: 移除 site {idx}（{old}）；剩余 {len(st)} 原子"
        elif op_n == "insert":
            if not element:
                return "错误：[E_PARAM] insert 需要 element"
            if frac_coords:
                xyz = [float(x) for x in frac_coords.replace(" ", "").split(",")]
                st.append(element, xyz, coords_are_cartesian=False)
                note = f"插入 {element} @ frac {xyz}"
            elif cart_coords:
                xyz = [float(x) for x in cart_coords.replace(" ", "").split(",")]
                st.append(element, xyz, coords_are_cartesian=True)
                note = f"插入 {element} @ cart {xyz} Å"
            else:
                return "错误：[E_PARAM] insert 需要 frac_coords 或 cart_coords"
        elif op_n == "scale":
            if scale is None:
                return "错误：[E_PARAM] scale 需要 scale 因子"
            f = float(scale)
            if f <= 0:
                return "错误：[E_PARAM] scale 必须 > 0"
            st.scale_lattice(st.volume * (f ** 3))
            note = f"晶格等比缩放 ×{f}（体积 ×{f**3:.4f}）"
        else:
            return "错误：[E_PARAM] op 仅支持 substitute|vacancy|insert|scale"
    except (ValueError, IndexError, KeyError) as e:
        return f"错误：[E_PARAM] 编辑失败（{e}）"
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] 编辑失败（{type(e).__name__}: {e}）"

    poscar_str = _to_vasp5_poscar(st)
    save_note = ""
    if save:
        fpath = os.path.join(
            _out_dir(project, "structure"),
            f"edit_{op_n}_{int(time.time())}.vasp",
        )
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(poscar_str)
        save_note = f"\n已保存: {fpath}"
    return (
        f"{note}\n## 结构摘要\n{_structure_summary(st)}\n"
        f"## POSCAR\n```\n{poscar_str}\n```{save_note}"
    )


def primitive_cell(
    poscar_text: str,
    save: bool = True,
    project: Optional[str] = None,
) -> str:
    """约化为对称性意义下的原胞（SpacegroupAnalyzer primitive）。

    Args:
        poscar_text: POSCAR 文本。
        save/project: 落盘。

    Returns:
        原胞 POSCAR + 前后原子数；失败"错误："。
    """
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    st, err = _parse_any_structure(poscar_text, "poscar")
    if st is None:
        return err
    try:
        sga = SpacegroupAnalyzer(st, symprec=0.1)
        prim = sga.get_primitive_standard_structure()
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] 原胞约化失败（{e}）"
    poscar_str = _to_vasp5_poscar(prim)
    save_note = ""
    if save:
        fpath = os.path.join(_out_dir(project, "structure"), f"primitive_{int(time.time())}.vasp")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(poscar_str)
        save_note = f"\n已保存: {fpath}"
    return (
        f"原胞约化: {len(st)} → {len(prim)} 原子\n"
        f"空间群: {sga.get_space_group_symbol()} ({sga.get_space_group_number()})\n"
        f"## 结构摘要\n{_structure_summary(prim)}\n"
        f"## POSCAR\n```\n{poscar_str}\n```{save_note}"
    )


def symmetry_report(poscar_text: str, symprec: float = 0.1) -> str:
    """对称性报告：空间群、点群、是否原胞、Wyckoff 等（只读，不改结构）。"""
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    st, err = _parse_any_structure(poscar_text, "poscar")
    if st is None:
        return err
    try:
        sga = SpacegroupAnalyzer(st, symprec=float(symprec))
        sg_num = sga.get_space_group_symbol()
        sg_int = sga.get_space_group_number()
        crystal = sga.get_crystal_system()
        lattice_type = sga.get_lattice_type()
        point = sga.get_point_group_symbol()
        prim = sga.get_primitive_standard_structure()
        conv = sga.get_conventional_standard_structure()
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] 对称性分析失败（{e}）"
    return "\n".join([
        f"## 对称性报告（symprec={symprec}）",
        f"组成: {st.composition.reduced_formula} | 原子数 {len(st)}",
        f"空间群: {sg_num} (#{sg_int})",
        f"晶系: {crystal} | 点阵: {lattice_type} | 点群: {point}",
        f"原胞原子数: {len(prim)} | 常规胞原子数: {len(conv)}",
        f"体积: {st.volume:.4f} Å³",
    ])


def _find_ase_cli() -> Optional[str]:
    """定位 ASE 命令行（优先 PATH，其次 venv/系统 Scripts）。"""
    import shutil
    import sys

    for name in ("ase", "ase.exe", "ase-gui", "ase-gui.exe"):
        p = shutil.which(name)
        if p:
            return p
    scripts = os.path.join(os.path.dirname(sys.executable), "Scripts")
    for name in ("ase.exe", "ase", "ase-gui.exe"):
        p = os.path.join(scripts, name)
        if os.path.isfile(p):
            return p
    return None


def view_structure_ase(
    poscar_text: Optional[str] = None,
    structure_path: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """用本机 ASE GUI（ase-gui）打开结构做 3D 查看（需图形环境）。

    Args:
        poscar_text: POSCAR 文本（与 structure_path 二选一）。
        structure_path: 已有结构文件路径（.vasp/.cif/POSCAR 等）。
        project: 存放预览副本的项目名（默认 outputs/ase_preview）。

    Returns:
        打开的文件路径与进程说明；失败返回"错误："（无 DISPLAY/未装 ase 时）。
    """
    import subprocess

    ase_bin = _find_ase_cli()
    if not ase_bin:
        return (
            "错误：[E_PARAM] 未找到 ASE 命令行（ase/ase-gui）。"
            "请确认已 pip install ase，且 Scripts 目录在 PATH 中"
        )

    preview_dir = _out_dir(project or "ase_preview", "structure")
    if structure_path:
        src = os.path.expanduser(str(structure_path))
        if not os.path.isfile(src):
            return f"错误：[E_PARAM] structure_path 不存在: {src}"
        target = src
    elif poscar_text:
        st, err = _parse_any_structure(poscar_text, "auto")
        if st is None:
            return err
        target = os.path.join(preview_dir, f"ase_view_{int(time.time())}.vasp")
        with open(target, "w", encoding="utf-8") as f:
            f.write(_to_vasp5_poscar(st))
    else:
        return "错误：[E_PARAM] 需要 poscar_text 或 structure_path"

    # ase gui 子命令；无 shell，独立进程，不阻塞 MCP stdio
    try:
        proc = subprocess.Popen(
            [ase_bin, "gui", target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(os.path.abspath(target)) or None,
        )
    except OSError as e:
        return f"错误：[E_PARAM] 启动 ASE GUI 失败（{e}）"

    # 立刻失败（例如无显示）时读 stderr
    try:
        proc.wait(timeout=1.5)
        err = (proc.stderr.read() if proc.stderr else b"")[:400].decode("utf-8", "replace")
        if proc.returncode not in (0, None):
            return (
                f"错误：[E_PARAM] ASE GUI 立即退出（code={proc.returncode}）。"
                f"文件已保存: {target}。{err}"
            )
    except subprocess.TimeoutExpired:
        pass  # 仍在运行 = 窗口已打开

    return (
        f"已请求 ASE GUI 打开: {target}\n"
        f"命令: {ase_bin} gui <file>\n"
        "提示: 远程/无头会话无法弹出窗口；可手动在本机执行同命令。"
    )


TOOLS = [
    build_structure,
    parse_poscar,
    make_supercell,
    cleave_surface,
    import_structure,
    build_from_spacegroup,
    edit_structure,
    primitive_cell,
    symmetry_report,
    view_structure_ase,
]


