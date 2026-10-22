"""XRD 模拟与实验谱对照（pymatgen XRDCalculator，纯离线）。

- 只从结构出发算运动学粉末衍射谱，不触碰任何 VASP 输入；
- 支持 POSCAR / CIF 文本或文件路径；
- 可选给一条参考结构（如实验 CIF），叠加出图并逐峰报告 Δ2θ。
"""
from __future__ import annotations

import csv
import os
import time
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import out_dir as _out_dir

try:  # 兼容 python server/main.py（脚本）与 python -m server.main 两种入口
    from .structures import _parse_any_structure
except ImportError:  # pragma: no cover
    from matcalc.structures import _parse_any_structure

# 常用靶材（pymatgen XRDCalculator 的 WAVELENGTHS 键）
_DEFAULT_WAVELENGTH = "CuKa"


def _err(code: str, msg: str) -> str:
    return f"错误：[{code}] {msg}"


def _read_input(text_or_path: str) -> str:
    """接受原文或本地文件路径（单行且文件存在时按路径读取）。"""
    raw = (text_or_path or "").strip()
    if raw and "\n" not in raw and os.path.isfile(raw):
        with open(raw, encoding="utf-8", errors="replace") as f:
            return f.read()
    return raw


def _resolve_wavelength(wavelength: str) -> tuple[Optional[float], str]:
    """'CuKa' / 'MoKa' / 数值(Å) → (λ, 说明)。"""
    from pymatgen.analysis.diffraction.xrd import WAVELENGTHS

    s = str(wavelength or "").strip()
    try:
        val = float(s)
        if val <= 0:
            return None, f"波长必须为正，收到 {val}"
        return val, f"{val:.4f} Å（自定义）"
    except ValueError:
        pass
    key = next((k for k in WAVELENGTHS if k.lower() == s.lower()), None)
    if key is None:
        return None, (
            f"未知波长 '{wavelength}'；可选 {sorted(WAVELENGTHS)}，或直接给数值(Å)"
        )
    return float(WAVELENGTHS[key]), f"{key}（λ={WAVELENGTHS[key]:.4f} Å）"


def _parse_range(spec: str) -> tuple[Optional[tuple], str]:
    """'5,90' → (5.0, 90.0)。"""
    raw = str(spec or "").replace("，", ",").strip()
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) != 2:
        return None, f"two_theta_range 需为 \"min,max\"，收到 '{spec}'"
    try:
        lo, hi = float(parts[0]), float(parts[1])
    except ValueError:
        return None, f"two_theta_range 含非数值（'{spec}'）"
    if not (0 < lo < hi <= 180):
        return None, f"two_theta_range 需满足 0<min<max<=180，收到 {lo},{hi}"
    return (lo, hi), ""


def _peaks(structure, wavelength: float, rng: tuple, symprec: float):
    from pymatgen.analysis.diffraction.xrd import XRDCalculator

    calc = XRDCalculator(wavelength=wavelength, symprec=symprec)
    pat = calc.get_pattern(structure, two_theta_range=rng, scaled=True)
    rows = []
    for tt, inten, hkls, d in zip(pat.x, pat.y, pat.hkls, pat.d_hkls):
        parts = []
        for h in hkls:
            s = str(h["hkl"]).strip()
            if s.startswith("(") and s.endswith(")"):
                s = s[1:-1]
            parts.append(s.replace(", ", ","))
        rows.append(
            {
                "tt": float(tt),
                "d": float(d),
                "i": float(inten),
                "hkl": ";".join(parts),
            }
        )
    return rows


def _write_csv(path: str, peaks: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["two_theta_deg", "d_A", "intensity_pct", "hkl"])
        for p in peaks:
            w.writerow([f"{p['tt']:.3f}", f"{p['d']:.4f}", f"{p['i']:.2f}", p["hkl"]])


def _table(peaks: list[dict], top_n: int) -> list[str]:
    lines = [f"  {'2θ(°)':>7} {'d(Å)':>8} {'I(%)':>6}  hkl"]
    for p in sorted(peaks, key=lambda x: -x["i"])[:top_n]:
        lines.append(
            f"  {p['tt']:7.3f} {p['d']:8.4f} {p['i']:6.1f}  ({p['hkl']})"
        )
    return lines


def _spacegroup(structure) -> str:
    try:
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

        sga = SpacegroupAnalyzer(structure, symprec=0.02)
        return f"{sga.get_space_group_symbol()} (No.{sga.get_space_group_number()})"
    except Exception:  # noqa: BLE001
        return "未识别"


def simulate_xrd(
    structure_text: str,
    fmt: str = "auto",
    wavelength: str = _DEFAULT_WAVELENGTH,
    two_theta_range: str = "5,90",
    reference_text: str = "",
    reference_label: str = "reference",
    match_tol: float = 0.5,
    top_n: int = 12,
    save: bool = True,
    project: Optional[str] = None,
) -> str:
    """由结构模拟粉末 XRD（运动学近似），可选与参考结构（如实验 CIF）对照。

    与 VASP 无关，纯 pymatgen 计算；用于实验谱定峰、多晶型判别、
    DFT 晶胞与实验晶胞的 2θ 偏差评估。

    Args:
        structure_text: POSCAR / CIF 原文，或本地文件路径。
        fmt: auto | poscar | cif（auto 按内容嗅探）。
        wavelength: 靶材名 CuKa/CuKa1/MoKa/CoKa/FeKa/CrKa/AgKa…，或数值（Å）。
        two_theta_range: "min,max"，如 "5,90"。
        reference_text: 可选参考结构（同样支持原文或路径）；给出时叠加出图并报 Δ2θ。
        reference_label: 图例里参考谱的名字，如 "exp P2_1/c 295K"。
        match_tol: 峰匹配容差（°）；DFT 与实验体积差 3–4% 时 2θ 会差 0.3–0.5°，可放宽到 0.8。
        top_n: 正文明细列出多少个最强峰（CSV 始终是全部峰）。
        save: 是否把 PNG/CSV 写入 outputs/<project>/xrd/。
        project: 项目名（缺省散放在 outputs/xrd/ 下）。

    Returns:
        波长/晶胞/最强峰表；给出参考时附 Δ2θ 与参考独有峰；失败返回"错误："。
    """
    raw = _read_input(structure_text)
    if not raw:
        return _err("E_PARAM", "结构输入为空：给 POSCAR/CIF 原文或本地文件路径")
    st, kind = _parse_any_structure(raw, fmt)
    if st is None:
        return kind  # 已带 "错误：" 前缀

    lam, lam_note = _resolve_wavelength(wavelength)
    if lam is None:
        return _err("E_PARAM", lam_note)
    rng, range_err = _parse_range(two_theta_range)
    if rng is None:
        return _err("E_PARAM", range_err)
    top_n = max(1, min(int(top_n), 50))

    try:
        peaks = _peaks(st, lam, rng, symprec=0.01)
    except Exception as e:  # noqa: BLE001
        return _err("E_PARSE", f"XRD 计算失败（{type(e).__name__}: {e}）")
    if not peaks:
        return _err(
            "E_PARAM",
            f"{rng[0]}–{rng[1]}° 内无反射（晶胞过大或范围过窄？）",
        )

    ref_peaks, ref_st = None, None
    if (reference_text or "").strip():
        ref_raw = _read_input(reference_text)
        ref_st, ref_kind = _parse_any_structure(ref_raw, fmt)
        if ref_st is None:
            return _err("E_PARSE", f"参考结构解析失败：{ref_kind}")
        try:
            ref_peaks = _peaks(ref_st, lam, rng, symprec=0.01)
        except Exception as e:  # noqa: BLE001
            return _err("E_PARSE", f"参考结构 XRD 计算失败（{type(e).__name__}: {e}）")

    lines = [
        "## 结构",
        f"  化学式: {st.composition.reduced_formula}（{st.composition.formula}）| 原子数 {st.num_sites}"
        f" | 识别为 {kind}",
        f"  空间群: {_spacegroup(st)}",
        f"  晶胞: a={st.lattice.a:.4f}, b={st.lattice.b:.4f}, c={st.lattice.c:.4f} Å | "
        f"α={st.lattice.angles[0]:.2f}, β={st.lattice.angles[1]:.2f}, γ={st.lattice.angles[2]:.2f}°"
        f" | V={st.volume:.2f} Å³",
        "## 条件",
        f"  波长: {lam_note} | 2θ 范围: {rng[0]:g}–{rng[1]:g}° | 反射数: {len(peaks)}",
        f"## 最强峰（前 {top_n}，按强度排序）",
        *_table(peaks, top_n),
    ]

    if ref_peaks is not None and ref_st is not None:
        tol = abs(float(match_tol)) or 0.5
        # 一对一贪心匹配：先按 |Δ2θ| 升序占位，避免一个参考峰被重复匹配
        pairs = sorted(
            (
                (abs(q["tt"] - p["tt"]), pi, qi)
                for pi, p in enumerate(peaks)
                for qi, q in enumerate(ref_peaks)
                if abs(q["tt"] - p["tt"]) <= tol
            ),
            key=lambda t: t[0],
        )
        used_p: set[int] = set()
        used_q: set[int] = set()
        matched = []
        for _, pi, qi in pairs:
            if pi in used_p or qi in used_q:
                continue
            used_p.add(pi)
            used_q.add(qi)
            matched.append((peaks[pi], ref_peaks[qi], ref_peaks[qi]["tt"] - peaks[pi]["tt"]))
        matched.sort(key=lambda t: -t[0]["i"])

        lines += [
            f"## 与参考谱对照（{reference_label}）",
            f"  参考: {ref_st.composition.reduced_formula} | 空间群 {_spacegroup(ref_st)} | "
            f"a={ref_st.lattice.a:.4f}, b={ref_st.lattice.b:.4f}, c={ref_st.lattice.c:.4f} Å | "
            f"V={ref_st.volume:.2f} Å³",
            f"  匹配容差 ±{tol:g}°；Δ2θ = 参考 − 本结构（负值表示本结构峰偏右/参考峰偏左）",
            f"  {'本结构 2θ':>10} {'参考 2θ':>9} {'Δ2θ':>7}  hkl(本)  hkl(参考)",
        ]
        for p, q, d in matched[:top_n]:
            lines.append(
                f"  {p['tt']:10.3f} {q['tt']:9.3f} {d:+7.3f}  ({p['hkl']})  ({q['hkl']})"
            )
        if not matched:
            lines.append("  （容差内无可匹配峰：两条谱差异较大，注意晶胞/多晶型是否对得上）")

        only_ref = [
            q for qi, q in enumerate(ref_peaks)
            if qi not in used_q and q["i"] >= 1.0
        ]
        only_ref.sort(key=lambda q: -q["i"])
        if only_ref:
            lines.append("  参考谱独有峰（本结构无对应；可能是超结构/多晶型/杂质相）：")
            for q in only_ref[:8]:
                lines.append(f"    {q['tt']:7.3f}°  I={q['i']:5.1f}%  ({q['hkl']})")

        only_main = [
            p for pi, p in enumerate(peaks)
            if pi not in used_p and p["i"] >= 1.0
        ]
        only_main.sort(key=lambda p: -p["i"])
        if only_main:
            lines.append("  本结构独有峰（参考谱无对应；可能是参考缺相/取向或结构差异）：")
            for p in only_main[:8]:
                lines.append(f"    {p['tt']:7.3f}°  I={p['i']:5.1f}%  ({p['hkl']})")

        if abs(st.volume - ref_st.volume) > 1e-6:
            fu = st.num_sites / st.composition.reduced_composition.num_atoms
            fu_ref = ref_st.num_sites / ref_st.composition.reduced_composition.num_atoms
            if abs(fu - fu_ref) < 1e-6:
                lines.append(
                    f"  体积差: 本结构 {st.volume:.2f} vs 参考 {ref_st.volume:.2f} Å³ "
                    f"({(st.volume / ref_st.volume - 1) * 100:+.2f}%)"
                )
            else:
                v1, v2 = st.volume / fu, ref_st.volume / fu_ref
                lines.append(
                    f"  体积/化学式单元: 本结构 {v1:.2f} vs 参考 {v2:.2f} Å³ "
                    f"({(v1 / v2 - 1) * 100:+.2f}%)"
                    f"（原子数 {st.num_sites} vs {ref_st.num_sites}，按 f.u. 归一后可比；"
                    "hkl 不可直接对应，只比 2θ 位置）"
                )

    lines.append(
        "说明: 运动学近似、无择优取向/仪器展宽/洛伦兹-偏振以外的修正；"
        "晶胞偏大（DFT 常见 +1~4%）时 2θ 整体偏低。"
    )

    if save:
        try:
            stamp = int(time.time())
            base = os.path.join(_out_dir(project, "xrd"), f"xrd_{st.composition.reduced_formula}_{stamp}")
            png, csv_path = base + ".png", base + ".csv"
            _write_csv(csv_path, peaks)
            saved = [png, csv_path]

            fig, ax = plt.subplots(figsize=(9, 4.4), dpi=180)
            ax.vlines([p["tt"] for p in peaks], 0, [p["i"] for p in peaks],
                      lw=1.2, color="#1f4e79", label=f"{st.composition.reduced_formula} (input)")
            for p in peaks:
                if p["i"] >= 20:
                    ax.annotate(f"({p['hkl']})", (p["tt"], p["i"]),
                                textcoords="offset points", xytext=(0, 3),
                                ha="center", fontsize=6, rotation=90)
            if ref_peaks:
                ax.vlines([q["tt"] for q in ref_peaks], 0, [-q["i"] for q in ref_peaks],
                          lw=1.2, color="#c53030", label=reference_label)
                _write_csv(base + "_ref.csv", ref_peaks)
                saved.append(base + "_ref.csv")
                ax.axhline(0, color="gray", lw=0.6)
                ax.set_ylim(-110, 118)
            ax.set_xlim(*rng)
            ax.set_xlabel(r"2$\theta$ (degree)")
            ax.set_ylabel("Intensity (%)" if not ref_peaks else "Intensity (input ↑ / ref ↓)")
            ax.set_title(f"Simulated XRD — {st.composition.reduced_formula}")
            ax.grid(alpha=0.2, ls=":")
            ax.legend(loc="upper right", fontsize=7)
            fig.tight_layout()
            fig.savefig(png)
            plt.close(fig)
            lines.append("已保存: " + " | ".join(saved))
        except Exception as e:  # noqa: BLE001
            lines.append(_err("E_IO", f"落盘失败（{type(e).__name__}: {e}）"))

    return "\n".join(lines)


TOOLS = [simulate_xrd]
