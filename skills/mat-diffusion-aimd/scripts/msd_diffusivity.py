"""Compute ionic diffusivity from a VASP XDATCAR (MSD + Einstein relation).

Companion script for skills/mat-diffusion-aimd/SKILL.md. Uses only numpy
(already in requirements.txt); does NOT rely on pymatgen's removed
DiffusionAnalyzer. Outputs are written under --out (default inside outputs/).

Two modes:
  1) Single trajectory: --xdatcar FILE --species Na --timestep-fs 1.0 --temp 600
  2) Arrhenius fit from (T, D) pairs: --arrhenius "600:0.0012,800:0.0045,1000:0.0110"

Usage:
    .venv/Scripts/python.exe msd_diffusivity.py \
        --xdatcar server/outputs/na_zr_cl6/XDATCAR --species Na \
        --timestep-fs 1.0 --temp 600 --dim 3 --out server/outputs/na_zr_cl6/diffusion
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

KB_EV_PER_K = 8.617333262e-5  # Boltzmann constant, eV/K


def parse_xdatcar(path: str) -> tuple[list[str], np.ndarray, np.ndarray, float | None]:
    """Parse XDATCAR -> (species labels, frames fractional coords [nframes,natoms,3], lattice, scale).

    Lattice is stored as scaling factor * the 3 lattice vectors (Cartesian Å).
    """
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        lines = [ln.rstrip("\n") for ln in fh]

    i = 0
    # skip comment
    i += 1
    scale = float(lines[i].split()[0])
    i += 1
    lattice_rows = []
    for _ in range(3):
        lattice_rows.append([float(x) for x in lines[i].split()[:3]])
        i += 1
    lattice = np.asarray(lattice_rows, dtype=float)  # 3x3 rows = lattice vectors
    species = lines[i].split()
    i += 1
    counts = [int(x) for x in lines[i].split()]
    i += 1
    natoms = sum(counts)
    labels = []
    for sp, n in zip(species, counts):
        labels.extend([sp] * n)

    frames = []
    while i < len(lines):
        if lines[i].strip().lower().startswith("direct"):
            i += 1
        coords = []
        for _ in range(natoms):
            if i >= len(lines) or not lines[i].strip():
                break
            coords.append([float(x) for x in lines[i].split()[:3]])
            i += 1
        if len(coords) == natoms:
            frames.append(coords)
        # next frame may start with 'Direct configuration=' line; skip until 'Direct'
        while i < len(lines) and not lines[i].strip().lower().startswith("direct"):
            i += 1
    if not frames:
        raise RuntimeError("错误：[E_PARSE] XDATCAR 中未找到任何 Direct 坐标帧")
    return labels, np.asarray(frames, dtype=float), lattice, scale


def unwrap_and_msd(
    frac: np.ndarray, indices: np.ndarray, lattice: np.ndarray, scale: float | None
) -> np.ndarray:
    """Unwrap minimum-image displacements and compute MSD [nframes] for selected atoms."""
    # Minimum image must be applied in fractional coordinates before scaling to Cartesian.
    fsel = frac[:, indices, :]
    fdisp = np.diff(fsel, axis=0)
    fdisp -= np.round(fdisp)
    cd = fdisp @ (lattice * (scale if scale is not None else 1.0))
    unwrapped = np.concatenate([np.zeros_like(cd[:1]), np.cumsum(cd, axis=0)], axis=0)
    sq = np.sum(unwrapped**2, axis=2)  # [nframes, nsel]
    return sq.mean(axis=1)


def linear_slope(msd: np.ndarray, timestep_ps: float, start: float, end: float) -> tuple[float, float]:
    """Fit MSD vs time in [start,end] fraction; return (slope Å²/ps, R²)."""
    n = len(msd)
    lo = max(1, int(n * start))
    hi = min(n, int(n * end))
    if hi - lo < 3:
        raise RuntimeError("错误：[E_PARAM] 拟合区间太短，轨迹帧数不足或 fit-start/end 过窄")
    t = np.arange(lo, hi, dtype=float) * timestep_ps
    y = msd[lo:hi]
    A = np.vstack([t, np.ones(len(t))]).T
    slope, intercept = np.linalg.lstsq(A, y, rcond=None)[0]
    pred = slope * t + intercept
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return float(slope), float(r2)


def single_trajectory(args) -> dict:
    labels, frac, lattice, scale = parse_xdatcar(args.xdatcar)
    idx = [i for i, s in enumerate(labels) if s == args.species]
    if not idx:
        raise RuntimeError(
            f"错误：[E_PARAM] XDATCAR 中无元素 {args.species}；可用: {sorted(set(labels))}"
        )
    msd = unwrap_and_msd(frac, np.asarray(idx), lattice, scale)
    dt_ps = args.timestep_fs / 1000.0
    slope, r2 = linear_slope(msd, dt_ps, args.fit_start, args.fit_end)
    d_ang2_ps = slope / (2.0 * args.dim)
    # 1 Å = 1e-10 m -> Å² = 1e-20 m²; 1 ps = 1e-12 s -> 1e-20/1e-12 = 1e-12 m²/s
    d_m2_s = d_ang2_ps * 1e-12
    return {
        "xdatcar": args.xdatcar,
        "species": args.species,
        "n_ions": len(idx),
        "n_frames": len(msd),
        "timestep_fs": args.timestep_fs,
        "temperature_K": args.temp,
        "dimension": args.dim,
        "fit_window": [args.fit_start, args.fit_end],
        "msd_slope_A2_per_ps": round(slope, 6),
        "fit_R2": round(r2, 4),
        "D_A2_per_ps": round(d_ang2_ps, 8),
        "D_m2_per_s": float(f"{d_m2_s:.6e}"),
        "msd_last_A2": round(float(msd[-1]), 4),
        "note": "D=slope/(2d); MSD 拟合跳过初始平衡段。轨迹长度/有限尺寸误差需人工评估。",
        "_msd": msd,
    }


def arrhenius_fit(spec: str) -> dict:
    pts = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise RuntimeError(f"错误：[E_PARAM] Arrhenius 项格式应为 T:D，收到 '{chunk}'")
        t, d = chunk.split(":", 1)
        t, d = float(t), float(d)
        if t <= 0 or d <= 0:
            raise RuntimeError("错误：[E_PARAM] Arrhenius 的 T 与 D 必须为正")
        pts.append((t, d))
    if len(pts) < 3:
        raise RuntimeError("错误：[E_PARAM] Arrhenius 拟合至少需要 3 个温度点")
    inv_t = np.array([1.0 / t for t, _ in pts])
    ln_d = np.log(np.array([d for _, d in pts]))
    A = np.vstack([-inv_t / KB_EV_PER_K, np.ones(len(pts))]).T
    slope, intercept = np.linalg.lstsq(A, ln_d, rcond=None)[0]
    pred = slope * inv_t / (-KB_EV_PER_K) + intercept
    ss_res = float(np.sum((ln_d - pred) ** 2))
    ss_tot = float(np.sum((ln_d - ln_d.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    ea = float(slope)  # ln D = ln D0 - Ea/(kB T) -> slope of (-1/kB T) is Ea
    return {
        "points": [{"T_K": t, "D_A2_per_ps": d} for t, d in pts],
        "Ea_eV": round(ea, 4),
        "D0_A2_per_ps": float(f"{math.exp(intercept):.6e}"),
        "fit_R2": round(r2, 4),
        "note": "Arrhenius: ln D = ln D0 - Ea/(kB T)。外推需谨慎，需说明温度范围。",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Diffusivity from AIMD XDATCAR / Arrhenius fit")
    ap.add_argument("--xdatcar", help="VASP XDATCAR path")
    ap.add_argument("--species", help="Element symbol to track, e.g. Na")
    ap.add_argument("--timestep-fs", type=float, default=1.0, help="MD timestep in fs")
    ap.add_argument("--temp", type=float, default=0.0, help="Temperature K (metadata)")
    ap.add_argument("--dim", type=int, default=3, choices=[1, 2, 3], help="Diffusion dimension")
    ap.add_argument("--fit-start", type=float, default=0.2, help="MSD fit start fraction")
    ap.add_argument("--fit-end", type=float, default=0.8, help="MSD fit end fraction")
    ap.add_argument("--arrhenius", help="T:D pairs, e.g. '600:0.0012,800:0.0045,1000:0.0110'")
    ap.add_argument("--out", default="server/outputs/diffusion", help="Output directory")
    args = ap.parse_args()

    if not args.xdatcar and not args.arrhenius:
        ap.error("provide --xdatcar or --arrhenius")

    os.makedirs(args.out, exist_ok=True)
    try:
        if args.xdatcar:
            result = single_trajectory(args)
            msd = result.pop("_msd")
            msd_path = os.path.join(args.out, "msd.csv")
            with open(msd_path, "w", encoding="utf-8") as fh:
                fh.write("frame,time_ps,msd_A2\n")
                for i, v in enumerate(msd):
                    fh.write(f"{i},{i*args.timestep_fs/1000.0:.6f},{v:.6f}\n")
            print(f"已保存: {msd_path}")
            print(
                f"D = {result['D_A2_per_ps']:.6g} Å²/ps = {result['D_m2_per_s']} m²/s "
                f"(物种 {result['species']}, T={result['temperature_K']:.0f} K, R²={result['fit_R2']})"
            )
            json_path = os.path.join(args.out, "diffusivity.json")
        else:
            result = arrhenius_fit(args.arrhenius)
            print(f"E_a = {result['Ea_eV']} eV  (D0={result['D0_A2_per_ps']} Å²/ps, R²={result['fit_R2']})")
            json_path = os.path.join(args.out, "arrhenius.json")

        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        print(f"已保存: {json_path}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
