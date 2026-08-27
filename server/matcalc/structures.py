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
