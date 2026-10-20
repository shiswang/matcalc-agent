"""DOS/PDOS/能带绘图与 Origin 数据导出（numpy 2.x trapezoid 积分）。

（R2 自 main.py 原样迁移，函数体未改动）"""

from __future__ import annotations

import os
import time
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: F401

from .common import OUTPUTS_DIR as _OUTPUTS_DIR, out_dir as _out_dir


def _export_origin_txt(base_path: str, header: list[str], x_vals, columns: list) -> str:
    """导出 Origin 友好的 tab 分隔数据文件（# 注释表头 + 数值列），返回路径。"""
    p = base_path + ".txt"
    lines = ["# " + "\t".join(header)]
    for i in range(len(x_vals)):
        rows = [f"{x_vals[i]:.4f}"] + [f"{col[i]:.6f}" for col in columns]
        lines.append("\t".join(rows))
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return p

def plot_dos(vasprun_path: str, spin_polarized: bool = True, emin: float = -10.0, emax: float = 10.0, save: bool = True, project: Optional[str] = None) -> str:
    """从本地 vasprun.xml 绘制总态密度（TDOS）图（PNG）。

    Args:
        vasprun_path: 本地 vasprun.xml 路径。
        spin_polarized: 是否区分自旋通道（非极化体系自动忽略）。
        emin/emax: 相对费米能的能量窗口 (eV)。
        save: 是否保存到 outputs 目录。

    Returns:
        图片路径与图内容说明。
    """
    from pymatgen.electronic_structure.core import Spin
    from pymatgen.io.vasp.outputs import Vasprun

    v = Vasprun(vasprun_path, parse_projected_eigen=False, exception_on_bad_xml=False)
    tdos = v.tdos
    ef = tdos.efermi
    fig, ax = plt.subplots(figsize=(6, 4.5), dpi=150)
    up_mask = (tdos.energies - ef >= emin) & (tdos.energies - ef <= emax)
    en = tdos.energies[up_mask] - ef
    ax.plot(en, tdos.densities[Spin.up][up_mask], color="#2b6cb0", lw=1.4, label="spin-up")
    has_dn = Spin.down in tdos.densities
    if has_dn:
        ax.plot(en, -tdos.densities[Spin.down][up_mask], color="#c53030", lw=1.4, label="spin-down")
        ax.axhline(0, color="gray", lw=0.6)
    else:
        ax.fill_between(en, tdos.densities[Spin.up][up_mask], alpha=0.25, color="#2b6cb0")
    ax.axvline(0, color="black", ls="--", lw=0.9)
    ax.text(0.15, ax.get_ylim()[1] * 0.92, "$E_F$", fontsize=10)
    ax.set_xlabel("E - E$_F$ (eV)")
    ax.set_ylabel("DOS (states/eV)")
    formula = v.final_structure.composition.reduced_formula
    ax.set_title(f"Total DOS — {formula}")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    out_png = ""
    out_txt = ""
    if save:
        stamp = int(time.time())
        out_png = os.path.join(_out_dir(project, "dos"), f"tdos_{formula}_{stamp}.png")
        fig.savefig(out_png)
        cols = [tdos.densities[Spin.up][up_mask]]
        heads = ["TDOS_up"]
        if has_dn:
            cols.append(tdos.densities[Spin.down][up_mask])
            heads.append("TDOS_down(取负后为-DOS)")
        out_txt = _export_origin_txt(
            os.path.join(_out_dir(project, "dos"), f"tdos_{formula}_{stamp}"),
            ["E-EF(eV)"] + heads,
            en,
            cols,
        )
    plt.close(fig)
    note = "上下自旋分别绘制（下旋取负值）" if has_dn else "非极化，单自旋通道"
    msg = f"DOS 图已生成: {out_png}\n内容: {note}; 费米能 {ef:.3f} eV; 能量窗口 [{emin}, {emax}] eV"
    if out_txt:
        msg += f"\n数据文件（Origin 可直接导入）: {out_txt}"
    return msg


def plot_band(vasprun_path: str, kpoints_path: str, save: bool = True, project: Optional[str] = None) -> str:
    """从本地 vasprun.xml + line-mode KPOINTS 绘制能带结构图（PNG）。

    Args:
        vasprun_path: NSCF 步的 vasprun.xml 路径。
        kpoints_path: 对应的 line-mode KPOINTS 路径。
        save: 是否保存到 outputs。

    Returns:
        图片路径与摘要（含带隙）。
    """
    from pymatgen.electronic_structure.plotter import BSPlotter
    from pymatgen.io.vasp.outputs import Vasprun

    def _resolve(p: str) -> str:
        if not os.path.isabs(p) and not os.path.exists(p):
            cand = os.path.join(_OUTPUTS_DIR, p)
            if os.path.exists(cand):
                return cand
        return p

    vp, kp = _resolve(vasprun_path), _resolve(kpoints_path)
    v = Vasprun(vp, parse_projected_eigen=False, exception_on_bad_xml=False)
    bs = v.get_band_structure(kpoints_filename=kp)
    plotter = BSPlotter(bs)
    ax = plotter.get_plot(ylim=None)
    fig = ax.figure
    formula = v.final_structure.composition.reduced_formula
    fig.suptitle(f"Band Structure — {formula}", fontsize=12)
    fig.tight_layout()
    out_png = ""
    if save:
        out_png = os.path.join(_out_dir(project, "result"), f"bands_{formula}_{int(time.time())}.png")
        fig.savefig(out_png)
    plt.close(fig)
    try:
        gap = bs.get_band_gap()
        direct = "直接" if gap.get("direct") else "间接"
        gap_e = gap.get("energy", 0.0)
        gap_note = f"带隙 {gap_e:.4f} eV（{direct}），CBM/VBM 见图"
    except Exception:  # noqa: BLE001
        gap_note = "带隙信息未能提取（可能金属）"
    return f"能带图已生成: {out_png}\n{gap_note}"

def plot_pdos(
    vasprun_path: str,
    split: str = "valence",
    elements: Optional[str] = None,
    emin: float = -10.0,
    emax: float = 10.0,
    min_contrib: float = 0.05,
    top_n: Optional[int] = None,
    stack: bool = False,
    save: bool = True,
    project: Optional[str] = None,
) -> str:
    """绘制投影态密度 PDOS（PNG），自动只画主要贡献轨道。

    spin-up 向上、spin-down 取负号向下（VASPKIT 惯例）。要求 vasprun.xml 含
    投影数据（计算 INCAR 需 LORBIT=11，可用 generate_dos_inputs 生成）。

    Args:
        vasprun_path: 本地 vasprun.xml 路径。
        split: "valence"=每元素一条主价壳层曲线（自动判别并标注 Mn3d/O2p/Na3s 等,
            默认）; "element"=每元素总量; "orbitals"=粗粒度 s/p/d;
            "fine"=细分轨道（p→px/py/pz, d→dxy/dyz/dxz/dx2-y2/dz2）。
        elements: 逗号分隔元素符号（如 "Mn,Ni,O"）；缺省画全部元素。
        emin/emax: 相对费米能的能量窗口 (eV)。
        min_contrib: 主要贡献阈值——窗口内积分占比低于此值的轨道不画（默认 5%）。
        top_n: 显式只画贡献最大的前 N 条曲线（给出时覆盖 min_contrib）。
        stack: True 时分轨曲线以堆叠面积图呈现（↑向上堆叠、↓负向向下堆叠）。
        save: 是否保存到 outputs（图 + Origin 数据 .txt）。

    Returns:
        图片路径、保留/忽略的轨道及内容说明。
    """
    from types import SimpleNamespace

    from pymatgen.electronic_structure.core import Spin
    from pymatgen.io.vasp.outputs import Vasprun

    def _resolve(p: str) -> str:
        if not os.path.isabs(p) and not os.path.exists(p):
            cand = os.path.join(_OUTPUTS_DIR, p)
            if os.path.exists(cand):
                return cand
        return p

    v = Vasprun(_resolve(vasprun_path), parse_projected_eigen=True, exception_on_bad_xml=False)
    cdos = v.complete_dos
    ef = cdos.efermi
    formula = v.final_structure.composition.reduced_formula

    all_syms: list[str] = []
    for site in v.final_structure:
        if site.specie.symbol not in all_syms:
            all_syms.append(site.specie.symbol)
    want = [s.strip() for s in elements.split(",")] if elements else all_syms
    unknown = [s for s in want if s not in all_syms]
    if unknown:
        return f"错误: [E_PARAM] 元素 {unknown} 不在体系中（含 {all_syms}）"

    # ---- 窗口积分工具（曲线组装与筛选共用）----
    def _integral(dos_like) -> float:
        m = (np.asarray(dos_like.energies) - ef >= emin) & (np.asarray(dos_like.energies) - ef <= emax)
        trapz_fn = getattr(np, "trapezoid", None) or np.trapz
        tot = 0.0
        for arr in dos_like.densities.values():
            a = np.asarray(arr)[m]
            tot += float(trapz_fn(a, np.asarray(dos_like.energies)[m]))
        return abs(tot)

    # ---- 组装候选曲线 ----
    def _shell_n(sym: str, shell: str) -> int:
        """由原子序数推断价壳层主量子数 n（用于 Mn3d/O2p 式标注）。"""
        from pymatgen.core import Element as _E2

        z = _E2(sym).Z
        if shell == "d":
            return 3 if z <= 30 else 4 if z <= 48 else 5 if z <= 80 else 6
        if z <= 2:
            return 1
        if z <= 10:
            return 2
        if z <= 18:
            return 3
        if z <= 36:
            return 4
        if z <= 54:
            return 5
        return 6

    curves: list[tuple[str, object]] = []  # (label, dos-like)
    if split == "valence":
        # 每元素取窗口内积分贡献最大的粗壳层作为其"主价层"，标注如 Mn3d / O2p / Na3s
        for sym in want:
            spd = cdos.get_element_spd_dos(_elem(sym))
            best_name, best_ot, best_w = None, None, -1.0
            for name in ("s", "p", "d", "f"):
                ot = getattr(OrbitalType_safe(), name, None)
                if ot is not None and ot in spd:
                    w = _integral(spd[ot])
                    if w > best_w:
                        best_name, best_ot, best_w = name, ot, w
            if best_ot is not None:
                curves.append((f"{sym}{_shell_n(sym, best_name)}{best_name}", spd[best_ot]))
    elif split == "element":
        for sym in want:
            edos = cdos.get_element_dos().get(_elem(sym))
            if edos is not None:
                curves.append((sym, edos))
    elif split == "orbitals":
        for sym in want:
            spd = cdos.get_element_spd_dos(_elem(sym))
            for oname in ("s", "p", "d", "f"):
                ot = getattr(OrbitalType_safe(), oname, None)
                if ot is not None and ot in spd:
                    curves.append((f"{sym}-{oname}", spd[ot]))
    elif split == "fine":
        fine_labels = {"s": "s", "px": "px", "py": "py", "pz": "pz",
                       "dxy": "dxy", "dyz": "dyz", "dz2": "dz2", "dxz": "dxz",
                       "dx2": "dx2-y2"}
        _shell_of = {"s": "s", "px": "p", "py": "p", "pz": "p",
                     "dxy": "d", "dyz": "d", "dz2": "d", "dxz": "d", "dx2": "d"}
        for sym in want:
            sites = [s for s in v.final_structure if s.specie.symbol == sym]
            agg: dict[str, dict] = {}
            for site in sites:
                for ot, arr in cdos.pdos.get(site, {}).items():
                    name = getattr(ot, "name", str(ot))
                    bucket = agg.setdefault(name, {})
                    for sp, vals in arr.items():
                        bucket[sp] = bucket.get(sp, 0) + vals
            # 自动限定在该元素的主价壳层内细分（与 valence 判定一致）
            spd_all = cdos.get_element_spd_dos(_elem(sym))
            best_shell, best_w = None, -1.0
            for name in ("s", "p", "d", "f"):
                ot = getattr(OrbitalType_safe(), name, None)
                if ot is not None and ot in spd_all:
                    w = _integral(spd_all[ot])
                    if w > best_w:
                        best_shell, best_w = name, w
            for raw, disp in fine_labels.items():
                if raw in agg and (best_shell is None or _shell_of.get(raw) == best_shell):
                    curves.append((f"{sym}-{disp}", SimpleNamespace(energies=cdos.energies, densities=agg[raw])))
    else:
        return f"错误: [E_PARAM] split 仅支持 valence|element|orbitals|fine，收到 '{split}'"

    if not curves:
        return "错误: [E_PARSE] 未生成任何 PDOS 曲线（确认 vasprun.xml 含投影数据，即计算时 LORBIT=11）"

    # ---- 主要贡献筛选（窗口积分占比）----
    weights = [(label, _integral(d)) for label, d in curves]
    total_w = sum(w for _, w in weights) or 1.0
    ranked = sorted(weights, key=lambda t: t[1], reverse=True)
    if top_n:
        kept_labels = {lb for lb, _ in ranked[: max(1, int(top_n))]}
    else:
        kept_labels = {lb for lb, w in ranked if w / total_w >= min_contrib}
    if not kept_labels:
        kept_labels = {ranked[0][0]}
    dropped = [(lb, w / total_w * 100) for lb, w in ranked if lb not in kept_labels]

    selected = [(lb, d) for lb, d in curves if lb in kept_labels]

    export_headers: list[str] = []
    export_cols: list = []
    export_x = None

    def _plot_curve(ax, dos, label: str, color=None, linestyle="-") -> None:
        nonlocal export_x
        m = (np.asarray(dos.energies) - ef >= emin) & (np.asarray(dos.energies) - ef <= emax)
        en = np.asarray(dos.energies)[m] - ef
        up = dos.densities.get(Spin.up)
        dn = dos.densities.get(Spin.down)
        kw = {"lw": 1.4, "linestyle": linestyle}
        if color is not None:
            kw["color"] = color
        if up is not None:
            up_arr = np.asarray(up)[m]
            ax.plot(en, up_arr, label=label + " (↑)", **kw)
            export_headers.append(f"{label}_up")
            export_cols.append(list(up_arr))
            export_x = list(en)
        if dn is not None:
            dn_arr = np.asarray(dn)[m]
            kwd = dict(kw)
            kwd["alpha"] = 0.85
            ax.plot(en, -dn_arr, label=label + " (↓)", **kwd)
            export_headers.append(f"{label}_down")
            export_cols.append(list(-dn_arr))

    fig, ax = plt.subplots(figsize=(7.2, 5.0), dpi=150)
    palette = plt.rcParams["axes.prop_cycle"].by_key().get("color", ["#2b6cb0", "#c53030", "#2f855a", "#b7791f"])
    has_dn = Spin.down in cdos.densities
    en0 = np.asarray(cdos.energies)
    m0 = (en0 - ef >= emin) & (en0 - ef <= emax)
    export_x = list(en0[m0] - ef)

    def _chan(dos, spin):
        a = dos.densities.get(spin)
        if a is None:
            return np.zeros(m0.sum())
        return np.asarray(a)[m0]

    if stack and len(selected) > 1:
        # ---- 每元素一个子图；子图内各分轨 ↑ 向上堆叠、↓ 取负向下堆叠 ----
        import re as _re

        groups: dict[str, list] = {}
        order: list[str] = []
        for lb, d in selected:
            mm = _re.match(r"([A-Z][a-z]?)", lb)
            sym = mm.group(1) if mm else lb
            if sym not in groups:
                order.append(sym)
                groups[sym] = []
            groups[sym].append((lb, d))

        import math as _math

        ncols = 2 if len(order) > 3 else 1
        nrows = _math.ceil(len(order) / ncols)
        fig, axes = plt.subplots(nrows, ncols, figsize=(6.5 * ncols, 2.9 * nrows), dpi=150,
                                 sharex=True, squeeze=False)
        y_top, y_bot = 1e-9, 0.0
        for gi, sym in enumerate(order):
            axp = axes[gi // ncols][gi % ncols]
            base = np.zeros(m0.sum())  # 共享累积基线: up 向上、down 镜像向下
            for i, (lb, d) in enumerate(groups[sym]):
                col = palette[i % len(palette)]
                up_arr = _chan(d, Spin.up)
                top = base + up_arr
                axp.fill_between(en0[m0] - ef, base, top, color=col, alpha=0.6, linewidth=0, label=lb)
                axp.plot(en0[m0] - ef, top, color=col, lw=1.0)
                export_headers.append(f"{lb}_up")
                export_cols.append(list(up_arr))
                if has_dn:
                    dn_arr = _chan(d, Spin.down)
                    bot = -(base + dn_arr)
                    axp.fill_between(en0[m0] - ef, -base, bot, color=col, alpha=0.4, linewidth=0)
                    axp.plot(en0[m0] - ef, bot, color=col, lw=1.0, linestyle="--")
                    export_headers.append(f"{lb}_down")
                    export_cols.append(list(-dn_arr))
                    y_bot = min(y_bot, float(bot.min()))
                base = top
            y_top = max(y_top, float(base.max()))
            axp.axvline(0, color="black", ls="--", lw=0.9)
            axp.axhline(0, color="gray", lw=0.6)
            axp.text(
                0.015, 0.93, sym, transform=axp.transAxes, fontsize=13, fontweight="bold",
                ha="left", va="top", bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, boxstyle="round,pad=0.25"),
            )
            axp.legend(loc="upper right", fontsize=8, frameon=False,
                       handlelength=1.4, borderpad=0.2, labelspacing=0.25,
                       ncol=max(1, len(groups[sym]) // 4))
        # 统一 y 刻度（全图可比）
        pad_y = (y_top - y_bot) * 0.05
        for r in range(nrows):
            for c in range(ncols):
                a = axes[r][c]
                if a.get_visible():
                    a.set_ylim((y_bot - pad_y) if y_bot < 0 else 0.0, y_top + pad_y)
        # 隐藏多余子图; 最底行标 x 轴
        for gi in range(len(order), nrows * ncols):
            axes[gi // ncols][gi % ncols].set_visible(False)
        for c in range(ncols):
            axes[nrows - 1][c].set_xlabel("E - E$_F$ (eV)")
        try:
            fig.supylabel("PDOS (states/eV)", fontsize=11, x=0.015)
        except AttributeError:
            fig.text(0.015, 0.5, "PDOS (states/eV)", rotation=90, va="center", fontsize=11)
    else:
        for i, (lb, d) in enumerate(selected):
            _plot_curve(ax, d, lb, color=palette[i % len(palette)])
        ax.axvline(0, color="black", ls="--", lw=0.9)
        ax.axhline(0, color="gray", lw=0.6)
        ax.set_xlabel("E - E$_F$ (eV)")
        # 图例自动落在曲线稀疏的空白处，半透明底保证可读；两栏排布
        ax.legend(loc="best", fontsize=9, framealpha=0.75, edgecolor="0.85",
                  handlelength=1.6, borderpad=0.5, labelspacing=0.35, ncol=2)
    if not (stack and len(selected) > 1):
        ax.set_ylabel("PDOS (states/eV)")
    mode_name = {"valence": "valence shells", "element": "by element", "orbitals": "s/p/d", "fine": "fine orbitals"}[split]
    stack_note = ", stacked panels" if (stack and len(selected) > 1) else ""
    fig.suptitle(
        f"PDOS ({mode_name}{stack_note}, major contributions) — {formula}",
        fontsize=12, y=0.995,
    )

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out_png = ""
    out_txt = ""
    if save:
        stamp = int(time.time())
        out_png = os.path.join(_out_dir(project, "dos"), f"pdos_{split}_{formula}_{stamp}.png")
        fig.savefig(out_png)
        if export_cols:
            out_txt = _export_origin_txt(
                os.path.join(_out_dir(project, "dos"), f"pdos_{split}_{formula}_{stamp}"),
                ["E-EF(eV)"] + export_headers,
                export_x,
                export_cols,
            )
    plt.close(fig)

    spin_note = "自旋极化（↓ 已取负号绘制" + ("，堆叠形式" if (stack and len(selected) > 1) else "") + "）" if has_dn else "非极化（无 ↓ 数据；需要自旋分辨请在 INCAR 加 ISPIN=2 重算）"
    msg = (
        f"PDOS 图已生成: {out_png}\n"
        f"模式: {mode_name}; 保留 {len(selected)} 条主要贡献曲线"
        f"（阈值 {min_contrib:.0%}" + (f"，top {top_n}" if top_n else "") + f"）; {spin_note}; 费米能 {ef:.3f} eV\n"
        f"保留曲线: {', '.join(lb for lb, _ in selected)}"
    )
    if dropped:
        msg += "\n已忽略（贡献占比）: " + ", ".join(f"{lb} {pc:.1f}%" for lb, pc in dropped[:8])
    if out_txt:
        msg += f"\n数据文件（Origin 可直接导入）: {out_txt}"
    return msg


def OrbitalType_safe():
    """延迟导入 OrbitalType（集中维护点）。"""
    from pymatgen.electronic_structure.core import OrbitalType as _OT

    return _OT


def _elem(symbol: str):
    """Element 快捷构造（集中导入点便于维护）。"""
    from pymatgen.core import Element as _E

    return _E(symbol)
