"""Compute 0 K convex-hull stability (E_hull) of a target compound from Materials Project.

A thin companion script for skills/mat-ehull-stability/SKILL.md. The MCP tool
`mp_phase_diagram` lists stable phases but does not return E_hull for a chosen
compound; this script fills that gap locally with pymatgen.

Only uses dependencies already in requirements.txt (numpy / pymatgen / mp-api).
All outputs go under --out (default: server/outputs/<project>/ehull).

Usage:
    .venv/Scripts/python.exe compute_ehull.py \
        --chemsys "Li-Fe-P-O" --target "LiFePO4" \
        --thermo-type R2SCAN --out server/outputs/li_fe_p_o/ehull
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Windows console UTF-8 for Chinese / Å output (see AGENTS.md)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass


def _parse_chemsys(text: str) -> str:
    """Accept 'Li-Fe-P-O' or a formula like 'LiFePO4' -> element chemsys."""
    from pymatgen.core import Composition

    text = (text or "").strip()
    if "-" in text and all(len(p) > 0 for p in text.split("-")):
        return "-".join(sorted({p.strip() for p in text.split("-")}))
    comp = Composition(text)
    return "-".join(sorted(el.symbol for el in comp.elements))


def _target_formula(text: str) -> str:
    from pymatgen.core import Composition

    return Composition(text).reduced_formula


def compute(chemsys: str, target: str, thermo_type: str, api_key: str | None) -> dict:
    try:
        from mp_api.client import MPRester
        from pymatgen.analysis.phase_diagram import PhaseDiagram
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"错误：[E_PARSE] 依赖不可用（{exc}）") from exc

    key = api_key or os.environ.get("MP_API_KEY") or os.environ.get("MAPI_KEY")
    if not key:
        raise RuntimeError("错误：[E_PARAM] 未配置 MP_API_KEY，无法查询凸包")

    cs = _parse_chemsys(chemsys)
    tgt = _target_formula(target)

    with MPRester(key) as mpr:
        entries = mpr.get_entries_in_chemsys(
            cs,
            additional_criteria={"thermo_types": [thermo_type]} if thermo_type else None,
        )
    if not entries:
        raise RuntimeError(
            f"错误：[E_PARAM] 体系 {cs} 在 thermo_type={thermo_type or '默认'} 下无条目；"
            "可试 --thermo-type GGA+U 或留空"
        )

    pd = PhaseDiagram(entries)

    # Find target entries by reduced formula.
    hits = [e for e in entries if e.composition.reduced_formula == tgt]
    if not hits:
        stable = sorted({e.composition.reduced_formula for e in pd.stable_entries})
        raise RuntimeError(
            f"错误：[E_PARAM] 目标 {tgt} 不在体系 {cs} 条目中；稳定相有: {', '.join(stable)}"
        )

    best = min(hits, key=lambda e: pd.get_e_above_hull(e))
    ehull = pd.get_e_above_hull(best)
    form = pd.get_form_energy_per_atom(best)
    stable_rows = sorted(
        (
            (e.composition.reduced_formula, pd.get_form_energy_per_atom(e))
            for e in pd.stable_entries
        ),
        key=lambda r: r[0],
    )

    verdict = "稳定（落在凸包上）" if ehull < 1e-4 else (
        "接近稳定（DFT 误差范围内）" if ehull < 0.025 else "亚稳（存在分解驱动力）"
    )
    return {
        "chemsys": cs,
        "target": tgt,
        "thermo_type": thermo_type or "MP default",
        "n_entries": len(entries),
        "E_hull_eV_per_atom": round(float(ehull), 6),
        "formation_energy_eV_per_atom": round(float(form), 6),
        "verdict": verdict,
        "stable_phases": [
            {"formula": f, "formation_energy_eV_per_atom": round(float(v), 6)}
            for f, v in stable_rows
        ],
        "note": "0 K、基于 Materials Project DFT 条目；不含有限温熵，非用户自有 VASP 结果。",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute 0 K E_hull from Materials Project")
    ap.add_argument("--chemsys", required=True, help="'Li-Fe-P-O' or a formula like 'LiFePO4'")
    ap.add_argument("--target", required=True, help="Target compound formula, e.g. 'LiFePO4'")
    ap.add_argument("--thermo-type", default="R2SCAN", help="MP thermo type filter (default: R2SCAN)")
    ap.add_argument("--api-key", default=None, help="MP API key (default: MP_API_KEY env)")
    ap.add_argument(
        "--out",
        default=None,
        help="Output directory (default: server/outputs/<target>/ehull)",
    )
    args = ap.parse_args()

    out_dir = args.out or os.path.join("server", "outputs", args.target.replace("/", "_"), "ehull")
    os.makedirs(out_dir, exist_ok=True)

    try:
        result = compute(args.chemsys, args.target, args.thermo_type, args.api_key)
    except Exception as exc:  # noqa: BLE001
        print(str(exc))
        return 2

    json_path = os.path.join(out_dir, "ehull_result.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    md_path = os.path.join(out_dir, "ehull_result.md")
    lines = [
        f"# E_hull 稳定性: {result['target']}",
        "",
        f"- 化学体系: {result['chemsys']}",
        f"- 理论级别: {result['thermo_type']}",
        f"- 条目数: {result['n_entries']}",
        f"- **E_hull (eV/atom) = {result['E_hull_eV_per_atom']}**",
        f"- 形成能 (eV/atom) = {result['formation_energy_eV_per_atom']}",
        f"- 判定: {result['verdict']}",
        "",
        "## 稳定相清单",
        "",
        "| 相 | 形成能 (eV/atom) |",
        "|---|---|",
    ]
    lines += [f"| {r['formula']} | {r['formation_energy_eV_per_atom']:+.4f} |" for r in result["stable_phases"]]
    lines += ["", f"> {result['note']}", ""]
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print(f"E_hull (eV/atom) = {result['E_hull_eV_per_atom']}  [{result['verdict']}]")
    print(f"体系 {result['chemsys']} | {result['thermo_type']} | {result['n_entries']} 条目")
    print(f"已保存: {json_path}")
    print(f"已保存: {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
