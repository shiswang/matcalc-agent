"""结构后处理层（S4.1）：键长/配位/晶格质量报告与前后对比。

物理锚点：弛豫质量的核心目测指标=键长分布是否炸裂；本模块把目测变数字。
实现基于 pymatgen 近邻分析，键长截断 = 共价半径和 × bond_cutoff_factor。
"""

from __future__ import annotations

from collections import defaultdict
from math import sqrt
from typing import Optional

from pymatgen.core import Structure
from pymatgen.io.vasp import Poscar

try:  # 兼容包导入与脚本直跑
    from .structures import _to_vasp5_poscar  # noqa: F401  (统一写出器占位引用)
except ImportError:  # pragma: no cover
    from matcalc.structures import _to_vasp5_poscar  # noqa: F401


def _parse(poscar_text: str, tag: str) -> Optional[Structure]:
    try:
        return Poscar.from_str(poscar_text).structure
    except Exception as e:  # noqa: BLE001
        print(f"错误：{tag} POSCAR 解析失败（{e}）")
        return None


def _err(msg: str) -> str:
    """统一解析域错误出口（E_PARSE 族；格式契约：'错误：'在前、错误码随后）。"""
    return f"错误：[E_PARSE] {msg}"


def analyze_structure(poscar_text: str, bond_cutoff_factor: float = 1.2) -> str:
    """【MCP 工具】结构质量报告：晶格 / 分元素对键长统计(带异常预警) / 配位数。

    Args:
        poscar_text: POSCAR/CONTCAR 文本（典型用途：弛豫后的 CONTCAR 质量体检）。
        bond_cutoff_factor: 键搜索截断 = 共价半径和 × 该系数（默认 1.2）。

    Returns:
        晶格参数、按元素对的键长 min/max/mean±std 与 ⚠ 偏离预警、各元素平均配位数、
        总结行；解析失败返回"错误："开头文本。
    """
    st = _parse(poscar_text, "结构")
    if st is None:
        return _err("POSCAR 解析失败，无法分析")

    abc, angles = st.lattice.abc, st.lattice.angles
    vpa = st.volume / len(st)
    lines = [
        "## 结构质量报告",
        f"组成: {st.composition.formula}  |  原子数 {len(st)}",
        f"晶格: a={abc[0]:.4f} b={abc[1]:.4f} c={abc[2]:.4f} Å; "
        f"α={angles[0]:.2f} β={angles[1]:.2f} γ={angles[2]:.2f}°",
        f"体积 {st.volume:.2f} Å³ ({vpa:.3f} Å³/原子)",
        "",
        "## 键长统计（截断 = Σ共价半径 × %.2f）" % bond_cutoff_factor,
    ]

    cutoffs: dict[tuple[str, str], float] = {}
    radii = {sp.symbol: float(sp.atomic_radius or 0.0) for sp in st.composition.elements}
    syms = sorted(radii)
    for i, a in enumerate(syms):
        for b in syms[i:]:
            cutoffs[(a, b)] = (radii[a] + radii[b]) * bond_cutoff_factor

    try:
        all_nb = st.get_all_neighbors(r=max((cutoffs.values() or [3.0])))
    except Exception as e:  # noqa: BLE001
        return _err(f"近邻分析失败：{e}")

    pair_dists: dict[tuple[str, ...], list[float]] = defaultdict(list)
    cn_by_el: dict[str, list[int]] = defaultdict(list)

    # 成键判定（化合物 vs 单质两套语义）：
    #   多元体系(化合物)：只统计异种元素对——岩盐中 Na⁺…Na⁺ 接触非化学键，
    #     用 Σ原子半径×1.2 判同类对会系统性误报；
    #   单质(金属等)：全部元素对参与（金属键本来就是同类成键）。
    multi_component = len(syms) > 1
    for site, nbrs in zip(st, all_nb):
        cn = 0
        sym = site.specie.symbol
        for n in nbrs:
            d = float(n.nn_distance)
            key = tuple(sorted((sym, n.specie.symbol)))
            if d <= cutoffs.get(key, 0.0) and d > 1e-6:
                if multi_component and key[0] == key[1]:
                    continue  # 化合物中的同类接触不视为键
                pair_dists[key].append(d)
                cn += 1
        cn_by_el[sym].append(cn)

    warnings = []
    if not pair_dists:
        lines.append("(截断内未发现任何近邻——可能是分子晶体或截断过小)")
    for pair in sorted(pair_dists):
        ds = pair_dists[pair]
        mean = sum(ds) / len(ds)
        std = (sum((d - mean) ** 2 for d in ds) / len(ds)) ** 0.5
        tag = f"{pair[0]}-{pair[1]}"
        line = (f"  {tag:>8}: N={len(ds):<4} d = {min(ds):.3f} / {mean:.3f} ± {std:.3f} / {max(ds):.3f} Å"
                f" (min/mean±std/max)")
        exp = radii[pair[0]] + radii[pair[1]]
        if pair[0] != pair[1] and abs(mean - exp) > 0.15 * exp:
            warn = f"  ⚠ {tag} 平均键长偏离共价半径和({exp:.2f}Å)超过15%——请人工复核该对相互作用"
            warnings.append(warn)
        lines.append(line)

    lines.append("")
    lines.append("## 配位数")
    for el in sorted(cn_by_el):
        cns = [c for c in cn_by_el[el]]
        lines.append(f"  {el}: 平均 CN={sum(cns) / len(cns):.2f}（范围 {min(cns)}–{max(cns)}）")

    lines.append("")
    if warnings:
        lines.append("## 总结")
        lines.extend(warnings)
        lines.append(f"🔴 结论: 存在 {len(warnings)} 类异常键，建议人工复核后再用于生产计算。")
    else:
        lines.append("## 总结")
        lines.append("🟢 结论: 键长分布紧凑合理，未见异常预警。")

    return "\n".join(lines)


def compare_structures(poscar_a: str, poscar_b: str,
                       label_a: str = "A(前)", label_b: str = "B(后)") -> str:
    """【MCP 工具】对比两个结构（典型：弛豫前 vs 后）：键长变化 / 体积变化 / 最大位移。

    Args:
        poscar_a: 弛豫前 POSCAR 文本。
        poscar_b: 弛豫后 CONTCAR 文本。
        label_a / label_b: 报告中的标签。

    Returns:
        各元素对平均键长 Δd、体积变化百分比、最大原子位移（原子数一致时）；
        解析失败返回"错误："开头。
    """
    sa, sb = _parse(poscar_a, label_a), _parse(poscar_b, label_b)
    if sa is None or sb is None:
        return _err("至少一个结构解析失败")

    def _pair_means(st: Structure):
        radii = {sp.symbol: float(sp.atomic_radius or 0.0) for sp in st.composition.elements}
        syms = sorted(radii)
        cuts: dict[tuple[str, str], float] = {}
        for i, a in enumerate(syms):
            for b in syms[i:]:
                cuts[(a, b)] = (radii[a] + radii[b]) * 1.2
        out: dict[tuple[str, str], float] = {}
        acc: dict[tuple[str, str], list[float]] = defaultdict(list)
        all_nb = st.get_all_neighbors(r=max(cuts.values(), default=3.0))
        for site, nbrs in zip(st, all_nb):
            for n in nbrs:
                d = float(n.nn_distance)
                key = tuple(sorted((site.specie.symbol, n.specie.symbol)))
                if d <= cuts.get(key, 0.0) and d > 1e-6:
                    acc[key].append(d)
        for k, v in acc.items():
            out[k] = sum(v) / len(v)
        return out

    ma, mb = _pair_means(sa), _pair_means(sb)
    common = sorted(set(ma) & set(mb))
    vol_pct = (sb.volume - sa.volume) / sa.volume * 100

    lines = [
        f"## 结构对比：{label_a} vs {label_b}",
        f"体积变化: {sa.volume:.2f} → {sb.volume:.2f} Å³（{vol_pct:+.2f}%）",
    ]
    disp_line = ""
    if len(sa) == len(sb):
        dmax, idx_at = 0.0, -1
        for i, (p, q) in enumerate(zip(sa, sb)):
            dv = q.coords - p.coords
            dist = float(sqrt(dv.dot(dv)))
            if dist > dmax:
                dmax, idx_at = dist, i
        disp_line = f"\n最大原子位移: {dmax:.4f} Å（#{idx_at} {sa[idx_at].specie.symbol}）"
        lines.append(disp_line.strip())
    else:
        lines.append(f"(原子数不一致 {len(sa)} vs {len(sb)}，跳过位移项)")

    lines.append("")
    lines.append("元素对平均键长变化:")
    lost = [k for k in ma if k not in mb]
    gained = [k for k in mb if k not in ma]
    if lost:
        lines.append("  ⚠ 键断裂预警（A 有而 B 超出截断判据）:")
        for k in sorted(lost):
            lines.append(f"    {k[0]}-{k[1]} 平均 {ma[k]:.3f} Å 在 {label_b} 中已不存在成键——"
                         f"可能过度膨胀/塌缩/重构，务必人工核查")
    if gained:
        lines.append(f"  ⚠ 新生成键: {', '.join(f'{k[0]}-{k[1]}' for k in sorted(gained))}")
    if not common and not lost and not gained:
        lines.append("  (无共同元素对——组成差异过大？)")
    for k in common:
        dd = mb[k] - ma[k]
        flag = " ⚠ 显式变化>10%" if abs(dd) > 0.1 * ma[k] else ""
        lines.append(f"  {k[0]}-{k[1]}: {ma[k]:.3f} → {mb[k]:.3f} Å （Δ{dd:+.4f}{flag}）")

    big = sum(1 for k in common if abs(mb[k] - ma[k]) > 0.1 * ma[k])
    if lost:
        verdict = f"🔴 {len(lost)} 类键在 {label_b} 中断裂——结构完整性存疑"
    elif big == 0:
        verdict = "🟢 骨架稳定"
    else:
        verdict = f"🟡 {big} 类键长显著变化，检查是否合理弛豫"
    lines.append(verdict)
    return "\n".join(lines)


TOOLS = [analyze_structure, compare_structures]
