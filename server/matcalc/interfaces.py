"""界面/异质结建模（体相与表面模型见 structures.py；本模块负责双材料外延堆叠）。

参考主流第一性原理界面建模流程（VASPKIT/QuantumATK 惯例）：
1. ZSL 晶格匹配：CoherentInterfaceBuilder 自动搜索两晶面的公度超胞组合；
2. 端型选择：不同 termination 表面能不同，先 inspect 再按索引构建；
3. 堆叠参数：界面间隙 gap + 真空层，厚度按 Å 给出、内部换算为原子层数。

产出 Interface 为 pymatgen Structure 子类，直接走项目统一的 VASP5 分组
POSCAR 输出（structures._to_vasp5_poscar），与全链工具格式一致。
"""

from __future__ import annotations

import math
import os
import time
from typing import Optional

from pymatgen.analysis.interfaces import CoherentInterfaceBuilder
from pymatgen.core import Structure
from pymatgen.io.vasp import Poscar

try:  # 兼容包导入与脚本直跑两种方式（与其他 matcalc 子模块一致）
    from .common import out_dir as _out_dir
    from .structures import _to_vasp5_poscar
except ImportError:  # pragma: no cover
    from matcalc.common import out_dir as _out_dir
    from matcalc.structures import _to_vasp5_poscar


def _parse_structure(poscar_text: str, tag: str):
    """解析 POSCAR 文本；失败时返回错误字符串（调用方检查 startswith("错误")）。"""
    try:
        return Poscar.from_str(poscar_text).structure
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] {tag} POSCAR 解析失败（{e}）"


def _parse_miller(miller: str, tag: str):
    """"0 0 1"/"0,0,1" -> (0,0,1)；格式非法返回错误字符串。"""
    parts = str(miller).replace(",", " ").split()
    if len(parts) != 3:
        return f"错误：[E_PARAM] {tag} 米勒指数需三个整数，收到 '{miller}'"
    try:
        return tuple(int(x) for x in parts)
    except ValueError:
        return f"错误：[E_PARAM] {tag} 米勒指数需三个整数，收到 '{miller}'"


def _layers_for(structure: Structure, miller: tuple[int, int, int], thickness_a: float) -> int:
    """把 Å 厚度换算成该晶面的原子层数（至少 1 层）。"""
    d = float(structure.lattice.d_hkl(miller))
    if d <= 0:
        return 1
    return max(1, math.ceil(float(thickness_a) / d))


def inspect_interface_match(
    film_poscar: str,
    substrate_poscar: str,
    film_miller: str = "0 0 1",
    substrate_miller: str = "0 0 1",
) -> str:
    """界面预检：ZSL 公度匹配搜索 + 可用端型清单（不生成结构）。

    Args:
        film_poscar: 薄膜（上层材料）体相 POSCAR 文本。
        substrate_poscar: 基底（下层材料）体相 POSCAR 文本。
        film_miller: 薄膜晶面米勒指数，如 "0 0 1"。
        substrate_miller: 基底晶面米勒指数，如 "1 1 0"。

    Returns:
        端型数量与清单（供 build_interface 的 termination_index 选择），
        以及两侧晶面间距与 10 Å 厚度的建议层数；无公度匹配时报错误提示。
    """
    film = _parse_structure(film_poscar, "薄膜")
    if isinstance(film, str):
        return film
    subs = _parse_structure(substrate_poscar, "基底")
    if isinstance(subs, str):
        return subs
    fm = _parse_miller(film_miller, "薄膜")
    if isinstance(fm, str):
        return fm
    sm = _parse_miller(substrate_miller, "基底")
    if isinstance(sm, str):
        return sm

    builder = CoherentInterfaceBuilder(
        substrate_structure=subs, film_structure=film, film_miller=fm, substrate_miller=sm,
    )
    terms = sorted(builder.terminations)
    if not terms:
        return (
            "错误：未找到公度界面匹配（ZSL 无解）。\n"
            "建议：① 换一对米勒指数；② 检查两材料晶格常数是否差距过大"
            "（面积失配超过默认容差即无解）；③ 对极端失配体系考虑手动 stack_slabs 方案。"
        )
    lines = [
        f"ZSL 匹配成功：共 {len(terms)} 个端型组合（termination_index 从 0 开始）：",
        *[f"  [{i}] {t[0]} / {t[1]}" for i, t in enumerate(terms)],
        "",
        f"薄膜 ({fm[0]} {fm[1]} {fm[2]}): 面间距 d={film.lattice.d_hkl(fm):.3f} Å,"
        f" 10 Å ≈ {_layers_for(film, fm, 10.0)} 层",
        f"基底 ({sm[0]} {sm[1]} {sm[2]}): 面间距 d={subs.lattice.d_hkl(sm):.3f} Å,"
        f" 10 Å ≈ {_layers_for(subs, sm, 10.0)} 层",
        "提示: 不同端型表面悬挂键不同，建议逐一 build 后比较界面能与电荷转移。",
    ]
    return "\n".join(lines)


def build_interface(
    film_poscar: str,
    substrate_poscar: str,
    film_miller: str = "0 0 1",
    substrate_miller: str = "0 0 1",
    film_thickness: float = 10.0,
    substrate_thickness: float = 10.0,
    gap: float = 2.5,
    vacuum_over_film: float = 15.0,
    termination_index: int = 0,
    project: Optional[str] = None,
    save: bool = True,
) -> str:
    """自动构建两材料的公度界面/异质结模型（ZSL 匹配 + 外延堆叠）。

    流程：两侧按米勒指数切面 → ZSL 搜索公度超胞 → 选端型 → 按 Å 厚度换算层数 →
    以 gap 间隔堆叠并在薄膜上方留真空层。

    Args:
        film_poscar: 薄膜（上层材料）体相 POSCAR 文本。
        substrate_poscar: 基底（下层材料）体相 POSCAR 文本。
        film_miller: 薄膜晶面米勒指数，如 "0 0 1"。
        substrate_miller: 基底晶面米勒指数，如 "0 0 1"。
        film_thickness: 薄膜板层厚度 (Å)，内部换算为整数层数。
        substrate_thickness: 基底板层厚度 (Å)。
        gap: 界面间隙 (Å)，初建后应弛豫优化。
        vacuum_over_film: 薄膜上方的真空层厚度 (Å)。
        termination_index: 端型编号（见 inspect_interface_match 清单），默认 0。
        project: 可选项目名——产物保存到 outputs/<project>/structure/。
        save: 是否保存 POSCAR 到 outputs（默认 True）。

    Returns:
        界面摘要（层数/原子数/c 长/端型）+ POSCAR 文本（VASP5 分组格式）。
    """
    film = _parse_structure(film_poscar, "薄膜")
    if isinstance(film, str):
        return film
    subs = _parse_structure(substrate_poscar, "基底")
    if isinstance(subs, str):
        return subs
    fm = _parse_miller(film_miller, "薄膜")
    if isinstance(fm, str):
        return fm
    sm = _parse_miller(substrate_miller, "基底")
    if isinstance(sm, str):
        return sm

    builder = CoherentInterfaceBuilder(
        substrate_structure=subs, film_structure=film, film_miller=fm, substrate_miller=sm,
    )
    terms = sorted(builder.terminations)
    if not terms:
        return "错误：未找到公度界面匹配（先用 inspect_interface_match 预检或更换米勒指数）。"
    if not 0 <= int(termination_index) < len(terms):
        return (
            f"错误：termination_index={termination_index} 超出范围"
            f"（可用 0..{len(terms) - 1}，用 inspect_interface_match 查看清单）。"
        )

    term = terms[int(termination_index)]
    fl_layers = _layers_for(film, fm, float(film_thickness))
    sl_layers = _layers_for(subs, sm, float(substrate_thickness))
    ifaces = list(
        builder.get_interfaces(
            termination=term,
            gap=float(gap),
            vacuum_over_film=float(vacuum_over_film),
            film_thickness=fl_layers,
            substrate_thickness=sl_layers,
            in_layers=True,
        )
    )
    if not ifaces:
        return f"错误：端型 {term} 未生成界面（尝试增大厚度或更换端型）。"
    iface = ifaces[0]

    poscar_str = _to_vasp5_poscar(iface)
    save_note = ""
    if save:
        fname = f"interface_{film.composition.reduced_formula}_{subs.composition.reduced_formula}_{int(time.time())}.vasp"
        fpath = os.path.join(_out_dir(project, "structure"), fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(poscar_str)
        save_note = f"\n已保存: {fpath}"

    info = [
        f"界面模型: {film.composition.reduced_formula}({fm[0]} {fm[1]} {fm[2]}) / "
        f"{subs.composition.reduced_formula}({sm[0]} {sm[1]} {sm[2]})",
        f"端型 [{int(termination_index)}]: {term[0]} / {term[1]}",
        f"厚度: 薄膜 {float(film_thickness):.1f} Å ≈ {fl_layers} 层, "
        f"基底 {float(substrate_thickness):.1f} Å ≈ {sl_layers} 层",
        f"堆叠: gap={float(gap):.2f} Å, 真空={float(vacuum_over_film):.2f} Å, "
        f"总原子数 {len(iface)}, c 轴长 {iface.lattice.c:.2f} Å",
        "提醒: 初建界面含未优化的 gap 与外延应变——先做基底底部固定弛豫，再看界面结合能。",
        "## POSCAR\n```\n" + poscar_str + "\n```" + save_note,
    ]
    return "\n".join(info)


def stack_slabs(top_poscar: str, bottom_poscar: str, gap: float = 2.5, vacuum: float = 15.0) -> str:
    """手动堆叠两块已准备好的 slab 为界面（跳过 ZSL 自动匹配）。

    适用场景：用户已用 cleave_surface + make_supercell 自备了匹配的上下板。
    约定：两块板的 a/b 面内格子直接沿用下板的 a/b 向量；上板整体沿 z 平移。

    Args:
        top_poscar: 上板 slab 的 POSCAR 文本（含真空层的切面模型即可）。
        bottom_poscar: 下板 slab 的 POSCAR 文本。
        gap: 两板之间的初始间隙 (Å)。
        vacuum: 顶部额外真空层 (Å)。

    Returns:
        摘要 + 合成结构的 POSCAR 文本；面内失配超 3% 或 c 轴明显非正交时给警告行。
    """
    top = _parse_structure(top_poscar, "上板")
    if isinstance(top, str):
        return top
    bot = _parse_structure(bottom_poscar, "下板")
    if isinstance(bot, str):
        return bot

    mt, mb = top.lattice.matrix, bot.lattice.matrix
    warnings: list[str] = []
    for name, va, vb in (("a", mb[0], mt[0]), ("b", mb[1], mt[1])):
        na, nb = float(math.sqrt(va.dot(va))), float(math.sqrt(vb.dot(vb)))
        if na > 0 and abs(nb - na) / na > 0.03:
            warnings.append(
                f"- 警告: 面内 {name} 失配 {(nb - na) / na * 100:.1f}% (>3%)，"
                "请先对齐超胞再堆叠，否则界面将带大应变。"
            )
    ct = float(math.sqrt(mt[2].dot(mt[2])))
    cb = float(math.sqrt(mb[2].dot(mb[2])))
    z_norm = mt[2] / ct
    if abs(float(z_norm.dot([0.0, 0.0, 1.0]))) < 0.995:
        warnings.append("- 警告: 上板 c 轴与表面法向夹角偏大（非正交 c），堆叠前建议先重定向晶胞。")

    gap = float(gap)
    vac = float(vacuum)
    c_total = cb + ct + gap + vac
    new_matrix = [
        [mb[0][0], mb[0][1], mb[0][2]],
        [mb[1][0], mb[1][1], mb[1][2]],
        [0.0, 0.0, c_total],
    ]
    from pymatgen.core.lattice import Lattice

    lat = Lattice(new_matrix)
    species: list = []
    coords: list[list[float]] = []
    for site in bot:
        species.append(site.specie)
        coords.append(list(site.coords))
    z_shift = cb + gap
    for site in top:
        species.append(site.specie)
        c = list(site.coords)
        coords.append([c[0], c[1], c[2] + z_shift])
    iface = Structure(lat, species, coords, coords_are_cartesian=True)

    head = [
        f"手动堆叠: 下板 {len(bot)} 原子 (c={cb:.2f} Å) + 上板 {len(top)} 原子 (c={ct:.2f} Å)",
        f"gap={gap:.2f} Å, 真空={vac:.2f} Å → 总 c={c_total:.2f} Å, 总原子数 {len(iface)}",
        *(warnings if warnings else ["面内失配检查通过（<3%）"]),
        "## POSCAR\n```\n" + _to_vasp5_poscar(iface) + "\n```",
    ]
    return "\n".join(head)


TOOLS = [inspect_interface_match, build_interface, stack_slabs]
