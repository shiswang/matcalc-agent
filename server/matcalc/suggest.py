"""U 值与磁性智能推断（S4.2）：本地知识表驱动，输出永远是"建议"，用户拍板。

铁律（本项目人机边界）：本模块只产生候选值与格式化建议字符串；
最终是否写入 INCAR 由用户决定。知识表以账本可回流的条目为基础，
随使用增长——用户确认过的 U/磁矩经 record_feedback 持久化到
server/outputs/knowledge/suggest_feedback.json（sidecar，不入 git、不碰代码表），
合并视图立即对后续建议生效。
"""

from __future__ import annotations

import json
import os
import time

from pymatgen.core import Composition
from pymatgen.io.vasp import Poscar

try:
    from .structures import _to_vasp5_poscar  # noqa: F401
except ImportError:  # pragma: no cover
    from matcalc.structures import _to_vasp5_poscar  # noqa: F401

# ─────────────────────────── 知识表 ───────────────────────────

# 3d 过渡金属 Dudarev U(d) 推荐值：{元素: (锚点值, 区间下限, 区间上限, 来源)}
_U_TABLE: dict[str, tuple[float, float, float, str]] = {
    "Ti": (4.5, 3.9, 5.0, "文献惯例; 本库 CaTiO3 演示锚点"),
    "V":  (3.25, 3.1, 3.6, "文献惯例区间"),
    "Cr": (3.5, 3.0, 4.0, "文献惯例区间"),
    "Mn": (4.0, 3.9, 4.2, "本库 NMO 实战锚点"),
    "Fe": (4.0, 3.5, 4.6, "文献惯例区间"),
    "Co": (3.4, 3.0, 4.0, "文献惯例区间"),
    "Ni": (6.2, 6.0, 6.45, "本库 NMO 实战锚点"),
    "Cu": (4.0, 3.5, 5.0, "文献惯例区间"),
    "Mo": (4.5, 4.0, 5.0, "文献惯例(d 视体系)"),
    "Ce": (4.5, 4.0, 5.0, "文献惯例(f 通道 LDAUL=3)"),
}

# 高自旋初始磁矩建议(μB)：{元素(典型氧化态): μB}
_MAGMOM_TABLE: dict[str, float] = {
    "Cr": 4.0, "Mn": 5.0, "Fe": 5.0, "Co": 3.0, "Ni": 1.5,
    "Ti": 2.0, "V": 3.0, "Cu": 1.0, "Mo": 4.0,
}
_RARE_EARTH = {"Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb"}
_TM_D = set(_MAGMOM_TABLE)


# ───────────── 用户确认回流（知识随使用增长；sidecar 不入库） ─────────────

def _feedback_path() -> str:
    """回流 sidecar 路径（测试通过 monkeypatch 本函数重定向到临时目录）。"""
    try:
        from .clusters import ROOT as _ROOT
    except ImportError:  # pragma: no cover
        from matcalc.clusters import ROOT as _ROOT
    return os.path.join(_ROOT, "server", "outputs", "knowledge", "suggest_feedback.json")


def _load_overrides() -> dict:
    p = _feedback_path()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _u_table_merged() -> dict:
    """基础文献/锚点表 + 用户确认覆盖层（后者优先并在来源列标注）。"""
    merged = dict(_U_TABLE)
    for el, entry in (_load_overrides().get("u") or {}).items():
        v = float(entry["value"])
        lo = float(entry.get("lo", max(0.0, v - 0.5)))
        hi = float(entry.get("hi", v + 0.5))
        merged[el] = (v, lo, hi, f"用户确认回流({entry.get('source', 'user')}@{entry.get('ts', '?')})")
    return merged


def _magmom_merged() -> dict:
    """基础高自旋初值表 + 用户确认覆盖层。"""
    merged = dict(_MAGMOM_TABLE)
    for el, entry in (_load_overrides().get("magmom") or {}).items():
        merged[el] = float(entry["value"])
    return merged


def record_feedback(kind: str, element: str, value: float,
                    lo: float = 0.0, hi: float = 0.0,
                    source: str = "user-confirmed",
                    project: str = "", note: str = "") -> str:
    """【MCP 工具】记录一条经用户拍板的知识回流（U 值 / 初始磁矩），立即可被建议层使用。

    Args:
        kind: "u"（DFT+U 有效值 eV）或 "magmom"（高自旋初值 μB）。
        element: 元素符号，如 "Ni"。
        value: 确认数值。
        lo / hi: 仅 kind=u 时有效的不确定区间；缺省取 value±0.5。
        source: 来源标签（默认 user-confirmed；可写 "文献:xxx"）。
        project: 可选关联项目名。
        note: 可选备注。

    Returns:
        写入确认 + 生效说明；参数非法返回"错误："开头文本。
    """
    el = (element or "").strip().capitalize()
    if kind not in ("u", "magmom"):
        return f"错误：[E_PARAM] kind 必须是 'u' 或 'magmom'，收到 '{kind}'"
    if not el or not el.isalpha():
        return f"错误：[E_PARAM] element 形如 'Ni'，收到 '{element}'"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"错误：[E_PARAM] value 需为数字，收到 {value!r}"
    if v <= 0:
        return f"错误：[E_PARAM] value 应为正数，收到 {v}"
    if kind == "u" and v > 12:
        return f"错误：[E_PARAM] U={v} eV 异常偏大（>12 eV），疑似单位错填"

    path = _feedback_path()
    data = _load_overrides()
    bucket = data.setdefault(kind, {})
    rec: dict = {"value": v, "source": source,
                 "ts": time.strftime("%Y-%m-%d %H:%M")}
    if kind == "u":
        if lo and hi:
            rec["lo"], rec["hi"] = round(float(lo), 3), round(float(hi), 3)
    if project:
        rec["project"] = project
    if note:
        rec["note"] = note
    bucket[el] = rec

    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

    where = os.path.relpath(path)
    effect = ("下次 suggest_u 将直接采用该值"
              if kind == "u" else "下次 suggest_magnetism 将把该元素初值更新为此 μB")
    return (f"已回流: {kind}[{el}] = {v}"
            f"{' ∈ [' + str(rec['lo']) + ', ' + str(rec['hi']) + ']' if 'lo' in rec else ''}"
            f"（来源 {source}）→ {where}\n{effect}。")


def suggest_u(poscar_text: str = "", formula: str = "") -> str:
    """【MCP 工具】按体系中 d/f 元素给出 DFT+U(Dudarev) 建议——仅供拍板的候选。

    Args:
        poscar_text: POSCAR 文本（优先）。
        formula: 备选化学式，如 "Na2MnNi3O8"（poscar_text 为空时使用）。

    Returns:
        每个 d/f 元素的 [推荐 U / 常见区间 / 来源] + 可直接使用的
        ldau_u="..." 字符串；纯主族体系提示无需 +U。末尾必附免责行。
    """
    if poscar_text:
        try:
            comp = Poscar.from_str(poscar_text).structure.composition
        except Exception as e:  # noqa: BLE001
            return f"错误：[E_PARSE] POSCAR 解析失败（{e}）"
    elif formula:
        try:
            comp = Composition(formula)
        except Exception as e:  # noqa: BLE001
            return f"错误：[E_PARSE] 化学式解析失败（{e}）"
    else:
        return "错误：[E_PARAM] poscar_text 与 formula 至少提供一个"

    hits: list[str] = []
    u_parts: list[str] = []
    merged_u = _u_table_merged()
    for el in comp.elements:
        sym = el.symbol
        if sym in merged_u:
            u, lo, hi, src = merged_u[sym]
            hits.append(f"  {sym}(d): 推荐 U={u} eV（常见 {lo}–{hi}；来源: {src}）")
            u_parts.append(f"{sym}={u}")
        elif sym in _RARE_EARTH:
            hits.append(f"  {sym}(f): 表中暂无精确锚点，请人工查文献（f 通道记得 ldau_l=3）")
        # 其余主族/阴离子：无需 +U，直接跳过
    if not hits:
        lines = [
            "无 d/f 过渡金属——该体系无需 DFT+U。",
            "免责: 此为基于组成的初步判断；若涉及缺陷态/极化子等特殊场景请人工复核。",
        ]
        return "\n".join(lines)

    ldau_str = ",".join(u_parts)
    return "\n".join([
        f"检测到 {len(hits)} 个需要 +U 的元素：",
        *hits,
        "",
        f"采用方式: generate_vasp_inputs(..., ldau_u=\"{ldau_str}\")",
        "免责: 以上为文献惯例/本库经验的候选值，最终取值请结合具体体系核验后拍板。",
    ])


def suggest_magnetism(poscar_text: str) -> str:
    """【MCP 工具】磁性初值智能建议：ISPIN / MAGMOM 字符串 / AFM 提醒。

    Args:
        poscar_text: POSCAR 文本。

    Returns:
        三件套：ISPIN 建议、可直接传 generate_vasp_inputs(magmom=...) 的
        字符串、近邻同种 TM ≥2 个时的 FM/AFM 对比提醒；纯主族给 ISPIN=1。
        末尾必附免责行。
    """
    try:
        st = Poscar.from_str(poscar_text).structure
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] POSCAR 解析失败（{e}）"

    tm_present = sorted({s.specie.symbol for s in st if s.specie.symbol in _TM_D},
                        key=lambda x: list(_TM_D).index(x))
    has_re = any(s.specie.symbol in _RARE_EARTH for s in st)

    if not tm_present and not has_re:
        return "\n".join([
            "体系不含常见 d/f 磁性元素 → 建议非磁计算: ispin=1 即可（省一半算力）。",
            "免责: 缺陷态/小带隙体系如遇磁坍缩假象请人工复核。",
        ])

    # 每个 TM 元素在结构中的原子数 → MAGMOM 向量(N*μB 元素块语法)
    mag_tbl = _magmom_merged()
    mag_parts: list[str] = []
    afm_hint = ""
    for sym in tm_present:
        n = sum(1 for s in st if s.specie.symbol == sym)
        mu = mag_tbl[sym]
        mag_parts.append(f"{n}*{mu:g}")
        near = st.get_all_neighbors(r=4.0)
        same_near = sum(
            1 for i, s in enumerate(st) if s.specie.symbol == sym
            for nb in near[i] if nb.specie.symbol == sym
        )
        if n >= 2 and same_near > 0:
            afm_hint = (
                f"⚠ AFM 提醒: {sym} 有 {n} 个近邻位(<4Å)——FM 初值仅是起点，"
                "建议 FM/AFM 两套 MAGMOM 各跑一次对比能量。"
            )

    mu_txt = ", ".join(f"{s}≈{mag_tbl[s]:g} μB(高自旋)" for s in tm_present)
    re_note = "；含稀土元素请再人工评估自旋-轨道耦合" if has_re else ""

    body = [
        f"检测到磁性候选元素: {', '.join(tm_present)}（{mu_txt}）",
        "建议 ISPIN=2（自旋极化必须开）",
        f"MAGMOM 建议: magmom=\"{' '.join(mag_parts)}\"（其余元素默认 0.6 μB）",
    ]
    if afm_hint:
        body.append(afm_hint)
    body.append(f"采用方式: generate_vasp_inputs(..., magmom=\"{' '.join(mag_parts)}\", ispin=2){re_note}")
    body.append("免责: 高自旋初值仅为收敛起点，终态磁矩以计算结果为准；氧化态差异会影响最佳初值。")
    return "\n".join(body)


def suggest_all(poscar_text: str) -> str:
    """综合建议文本 = U + 磁性拼接（工作流级联用，非 MCP 工具）。"""
    return suggest_u(poscar_text=poscar_text) + "\n\n" + "-" * 30 + "\n\n" + suggest_magnetism(poscar_text)


TOOLS = [suggest_u, suggest_magnetism, record_feedback]
