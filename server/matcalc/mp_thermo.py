"""MP 热力学对齐：相图 / 反应能 / 界面反应（需 MP_API_KEY 联网）。

基于 Materials Project 条目 + pymatgen PhaseDiagram/Reaction：
- 不把 MP 数值硬编码进仓库（会过时）；
- 无 key / 无网时返回可操作错误；
- 离线单测覆盖解析与错误路径，联网路径用假 key 测失败分支。
"""
from __future__ import annotations

import os
import re
from typing import Optional

from pymatgen.core import Composition


def _mp_key() -> Optional[str]:
    return os.environ.get("MP_API_KEY") or os.environ.get("MAPI_KEY") or None


def _require_key() -> Optional[str]:
    key = _mp_key()
    if not key:
        return (
            "错误：[E_PARAM] 需要环境变量 MP_API_KEY。"
            "相图/反应/界面反应依赖 Materials Project 在线条目；"
            "离线可用 suggest_u / generate_vasp_inputs。"
        )
    return None


def _open_mpr(key: str):
    from mp_api.client import MPRester

    return MPRester(key)


def _parse_chemsys(formula_or_chemsys: str) -> str:
    """'Li-Fe-O' 或 'LiFeO2' → 'Fe-Li-O'（pymatgen chemsys 排序）。"""
    raw = (formula_or_chemsys or "").strip()
    if not raw:
        raise ValueError("chemsys 为空")
    if "-" in raw and not re.search(r"\d", raw):
        els = {e.strip().capitalize() for e in raw.split("-") if e.strip()}
        return "-".join(sorted(els))
    comp = Composition(raw)
    els = {el.symbol for el in comp.elements}
    return "-".join(sorted(els))


def mp_phase_diagram(
    chemsys: str,
    api_key: Optional[str] = None,
) -> str:
    """拉取化学体系条目并构建相图摘要（稳定相 / 形成能范围）。

    Args:
        chemsys: 如 "Li-Fe-O" 或化合物 "LiFeO2"（自动取元素集）。
        api_key: 可选；缺省 MP_API_KEY。

    Returns:
        稳定相列表与形成能(eV/atom)；失败"错误："。
    """
    err = _require_key() if not api_key else None
    if err:
        return err
    try:
        cs = _parse_chemsys(chemsys)
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARAM] 无法解析化学体系 '{chemsys}'（{e}）"

    try:
        from pymatgen.analysis.phase_diagram import PhaseDiagram
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] pymatgen PhaseDiagram 不可用（{e}）"

    try:
        with _open_mpr(api_key or _mp_key() or "") as mpr:
            entries = mpr.get_entries_in_chemsys(cs)
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_CLUSTER] MP 条目拉取失败（{type(e).__name__}: {e}）"
    if not entries:
        return f"错误：[E_PARAM] 体系 {cs} 在 MP 中无条目"

    try:
        pd = PhaseDiagram(entries)
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] 相图构建失败（{e}）"

    stable = pd.stable_entries
    rows = []
    for e in sorted(stable, key=lambda x: x.composition.reduced_formula):
        try:
            ef = pd.get_e_above_hull(e)  # 稳定相应≈0；用形成能更直观
            form = pd.get_form_energy_per_atom(e)
        except Exception:  # noqa: BLE001
            form = float("nan")
        rows.append((e.composition.reduced_formula, form))

    lines = [
        f"化学体系: {cs} | 条目数 {len(entries)} | 稳定相 {len(stable)}",
        "## 稳定相（形成能 eV/atom，相对单质）",
    ]
    for formula, form in rows:
        lines.append(f"  {formula:20s}  {form:+.4f}" if form == form else f"  {formula}")
    lines.append(
        "说明: 由 MP 条目 + pymatgen PhaseDiagram 现算；"
        "可用于判断化合物是否落在凸包上、估算分解驱动力。"
    )
    return "\n".join(lines)


def mp_reaction_energy(
    reaction: str,
    api_key: Optional[str] = None,
) -> str:
    """计算反应能（基于 MP 形成能条目）。

    Args:
        reaction: 反应式，如 "2 Fe2O3 + 3 C -> 4 Fe + 3 CO2" 或 "NaCl -> Na + 0.5 Cl2"。
            箭头可用 -> 或 = ；系数可为小数。

    Returns:
        反应能 ΔE (eV，按书写系数) 与每 mol 产物参考；失败"错误："。
    """
    err = _require_key() if not api_key else None
    if err:
        return err
    text = (reaction or "").strip()
    if not text:
        return "错误：[E_PARAM] reaction 不能为空"
    # 规范化箭头
    text = re.sub(r"<[-=]+>|=+|→|⟶", "->", text)
    if "->" not in text:
        return "错误：[E_PARAM] reaction 需包含 '->'（或 = / →）"

    try:
        from pymatgen.analysis.reaction_calculator import Reaction

        rxn = Reaction.from_str(text)
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] 无法解析反应式（{e}）。示例: 2 Fe2O3 + 3 C -> 4 Fe + 3 CO2"

    chemsys_set = set()
    for comp in list(rxn.reactants) + list(rxn.products):
        chemsys_set.update(el.symbol for el in comp.elements)
    cs = "-".join(sorted(chemsys_set))

    try:
        from pymatgen.analysis.phase_diagram import PhaseDiagram

        with _open_mpr(api_key or _mp_key() or "") as mpr:
            entries = mpr.get_entries_in_chemsys(cs)
        if not entries:
            return f"错误：[E_PARAM] 体系 {cs} 无 MP 条目"
        pd = PhaseDiagram(entries)

        def _ef(comp: Composition) -> float:
            # 取该约化组成在凸包上的稳定条目形成能（eV/atom）
            reduced = comp.reduced_composition
            cands = [
                e for e in pd.stable_entries
                if e.composition.reduced_composition.almost_equals(reduced)
            ]
            if not cands:
                # 不稳定则用能量最低条目
                cands = [
                    e for e in entries
                    if e.composition.reduced_composition.almost_equals(reduced)
                ]
            if not cands:
                raise KeyError(str(reduced.formula))
            e0 = min(cands, key=lambda x: x.energy_per_atom)
            return float(pd.get_form_energy_per_atom(e0))

        delta = 0.0
        detail = []
        for comp in rxn.products:
            amt = float(rxn.products_coeffs[comp])
            ef = _ef(comp)
            delta += amt * ef * comp.num_atoms
            detail.append(f"  + {amt:g} {comp.formula}: Ef={ef:.4f} eV/atom")
        for comp in rxn.reactants:
            amt = float(rxn.reactants_coeffs[comp])
            ef = _ef(comp)
            delta -= amt * ef * comp.num_atoms
            detail.append(f"  - {amt:g} {comp.formula}: Ef={ef:.4f} eV/atom")
    except KeyError as e:
        return f"错误：[E_PARAM] MP 缺少物种条目: {e}"
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_CLUSTER] 反应能计算失败（{type(e).__name__}: {e}）"

    lines = [
        f"反应: {rxn}",
        f"化学体系: {cs}",
        f"ΔE = {delta:+.4f} eV（按方程系数；负=放热倾向）",
        "条目形成能贡献:",
        *detail,
        "说明: ΔE≈Σ n·Ef(产物)−Σ n·Ef(反应物)；未含有限温熵/溶液项。",
    ]
    return "\n".join(lines)


def mp_interface_reactions(
    material_a: str,
    material_b: str,
    api_key: Optional[str] = None,
    open_circuit: Optional[str] = None,
) -> str:
    """两材料界面可能反应（基于 MP 相图凸包分解，0 K 近似）。

    思路对齐 MP 旧版 InterfaceReaction：将 A/B 视为可反应组元，
    枚举凸包上的产物并给出反应驱动力（相对反应物）。

    Args:
        material_a / material_b: 化学式或 mp-id（mp-id 会拉取约化式）。
        open_circuit: 可选第三组元（如 "Li"）表示开路条件。
        api_key: 可选。

    Returns:
        可能产物与估算反应能排序表；失败"错误："。
    """
    err = _require_key() if not api_key else None
    if err:
        return err

    def _formula(q: str) -> str:
        q = (q or "").strip()
        if q.lower().startswith("mp-"):
            with _open_mpr(api_key or _mp_key() or "") as mpr:
                st = mpr.get_structure_by_material_id(q)
            return st.composition.reduced_formula
        return Composition(q).reduced_formula

    try:
        fa = _formula(material_a)
        fb = _formula(material_b)
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] 无法解析材料（{e}）"

    els = set()
    for f in (fa, fb):
        els.update(el.symbol for el in Composition(f).elements)
    if open_circuit:
        try:
            els.update(el.symbol for el in Composition(open_circuit).elements)
        except Exception as e:  # noqa: BLE001
            return f"错误：[E_PARAM] open_circuit 无法解析（{e}）"
    cs = "-".join(sorted(els))

    try:
        from pymatgen.analysis.phase_diagram import PhaseDiagram
        from pymatgen.analysis.reaction_calculator import Reaction

        with _open_mpr(api_key or _mp_key() or "") as mpr:
            entries = mpr.get_entries_in_chemsys(cs)
        if not entries:
            return f"错误：[E_PARAM] 体系 {cs} 无 MP 条目"
        pd = PhaseDiagram(entries)
        # 反应物形成能
        def ef_of(formula: str) -> float:
            reduced = Composition(formula).reduced_composition
            cands = [
                e for e in pd.stable_entries
                if e.composition.reduced_composition.almost_equals(reduced)
            ]
            if not cands:
                cands = [
                    e for e in entries
                    if e.composition.reduced_composition.almost_equals(reduced)
                ]
            if not cands:
                raise KeyError(formula)
            return float(pd.get_form_energy_per_atom(min(cands, key=lambda x: x.energy_per_atom)))

        host = els
        products = []
        for e in pd.stable_entries:
            pf = e.composition.reduced_formula
            if pf in (fa, fb):
                continue
            p_els = {el.symbol for el in e.composition.elements}
            if not p_els.issubset(host):
                continue
            try:
                rxn = Reaction.from_str(f"{fa} + {fb} -> {pf}")
                dE = 0.0
                for comp in rxn.products:
                    dE += float(rxn.products_coeffs[comp]) * ef_of(comp.reduced_formula) * comp.num_atoms
                for comp in rxn.reactants:
                    dE -= float(rxn.reactants_coeffs[comp]) * ef_of(comp.reduced_formula) * comp.num_atoms
                products.append((dE, str(rxn), pf))
            except Exception:  # noqa: BLE001
                products.append(
                    (ef_of(pf) * e.composition.num_atoms
                     - ef_of(fa) * Composition(fa).num_atoms
                     - ef_of(fb) * Composition(fb).num_atoms,
                     f"{fa}+{fb}→{pf}", pf)
                )
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_CLUSTER] 界面反应分析失败（{type(e).__name__}: {e}）"

    products.sort(key=lambda x: x[0])
    lines = [
        f"界面: {fa} | {fb}" + (f" | 开路组元 {open_circuit}" if open_circuit else ""),
        f"化学体系: {cs}",
        "## 可能反应（ΔE 越负越易发生；0 K 凸包近似）",
    ]
    for dE, rxn, pf in products[:15]:
        lines.append(f"  {dE:+8.4f} eV  {rxn}")
    if not products:
        lines.append("  (无额外稳定产物)")
    lines.append(
        "说明: 0 K 相图近似，非有限温界面能；开路条件用 open_circuit 传入第三组元。"
    )
    return "\n".join(lines)


def mp_pourbaix_diagram(
    chemsys: str,
    conc: float = 1e-6,
    ph: Optional[float] = None,
    v: Optional[float] = None,
    api_key: Optional[str] = None,
) -> str:
    """Pourbaix 图（电位–pH）稳定性分析：MP 离子/固相条目 + pymatgen。

    Args:
        chemsys: 金属体系，如 "Fe"、"Zn"、"Fe-Ni" 或化合物 "Fe2O3"（取金属集）。
        conc: 水溶液离子浓度 (mol/kg，默认 1e-6，对齐 MP 常用默认)。
        ph / v: 可选；给定时额外报告该点的稳定相。
        api_key: 可选 MP_API_KEY。

    Returns:
        Pourbaix 稳定区域物种列表；可选单点稳定相；失败"错误："。
    """
    err = _require_key() if not api_key else None
    if err:
        return err
    try:
        from pymatgen.analysis.pourbaix_diagram import PourbaixDiagram

        with _open_mpr(api_key or _mp_key() or "") as mpr:
            entries = mpr.get_pourbaix_entries(chemsys)
        if not entries:
            return f"错误：[E_PARAM] Pourbaix 体系 '{chemsys}' 无 MP 条目"
        # 离子浓度：默认全部离子用同一 conc
        conc_dict = {}
        for e in entries:
            ion = getattr(e, "ion_phase", None) or getattr(e, "phase", "")
            if str(ion).lower() in ("ion", "aq") or hasattr(e, "conc"):
                conc_dict[str(e.name if hasattr(e, "name") else e)] = float(conc)
        try:
            pbx = PourbaixDiagram(entries, conc_dict=conc_dict or None)
        except TypeError:
            pbx = PourbaixDiagram(entries)
        stable = pbx.stable_entries
        labels = []
        for e in stable:
            name = getattr(e, "name", None) or str(getattr(e, "entry", e))
            labels.append(name)
        lines = [
            f"Pourbaix 体系: {chemsys} | conc={conc:g} mol/kg",
            f"稳定相/离子数: {len(stable)}",
            "## 稳定物种",
        ]
        for lab in sorted(set(labels)):
            lines.append(f"  {lab}")
        if ph is not None and v is not None:
            try:
                # get_decomposition_energy 或 get_hull_energy 视版本
                entry = pbx.find_stable_entry(float(ph), float(v))
                name = getattr(entry, "name", None) or str(entry)
                lines += ["", f"## 单点 (pH={ph}, V={v} vs SHE)", f"  稳定: {name}"]
            except Exception as e:  # noqa: BLE001
                lines += ["", f"单点查询失败: {type(e).__name__}: {e}"]
        lines.append(
            "说明: 基于 MP aqueous/Pourbaix 条目 + pymatgen PourbaixDiagram；"
            "为 25°C 稀溶液近似，不含配合物/有机配体。"
        )
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_CLUSTER] Pourbaix 构建失败（{type(e).__name__}: {e}）"


TOOLS = [mp_phase_diagram, mp_reaction_energy, mp_interface_reactions, mp_pourbaix_diagram]
