"""结果解析与错误诊断：OUTCAR / vasprun.xml / ACF.dat(Bader) 与错误模式库。

（R2 自 main.py 原样迁移，函数体未改动）"""

from __future__ import annotations

import os
import re
from typing import Optional

from .common import OUTPUTS_DIR as _OUTPUTS_DIR

# ─────────────────────────── M2: 结果解析 / 错误诊断 / 远程 ───────────────────────────

# VASP 错误模式库：正则 → (问题说明, 修复建议)
_VASP_ERROR_PATTERNS: list[tuple[str, str, str]] = [
    (r"ZBRENT: fatal error", "电子自洽迭代不收敛（ZBRENT 求根失败）",
     "尝试：增大 NBANDS 20~50%；调节 AMIX/BMIX（如 0.2/0.05）；检查 ISMEAR 与 SIGMA；"
     "使用更小混合步长或 IALGO=48；确认初始磁矩（MAGMOM）合理"),
    (r"TOO FEW BANDS", "能带数不足",
     "在 INCAR 中显式增大 NBANDS（通常 1.5× 价带数）或设置 NBANDS 自动倍率"),
    (r"Error EDDDAV: Call to ZHEGV failed", "EDDDAV 对角化失败（常为内存/线性代数问题）",
     "减少并行核数或改 LPLANE=.FALSE.；增大内存；检查是否有 NaN（初值异常）"),
    (r"internal error in subroutine PACK", "PACK 内部错误",
     "检查 POSCAR/晶格是否合理（原子过近或坐标越界）；减少 k 点数尝试"),
    (r"reached required accuracy", "（信息）离子步已收敛", "正常结果，无需处理"),
    (r"Error reading item .* from file INCAR", "INCAR 参数解析失败",
     "检查 INCAR 中是否有拼写错误、非法取值或重复键"),
    (r"does not match the type of POTCAR", "POSCAR 元素与 POTCAR 顺序不匹配",
     "按 POSCAR 的元素顺序重新拼接 POTCAR"),
    (r"Fatal error", "VASP 致命错误（通用）",
     "查看 Fatal error 上方数行定位具体原因；常见为内存不足、参数非法、结构异常"),
    (r"Segmentation fault|segmentation fault", "段错误（内存访问违规）",
     "检查内存分配（SLURM 内存限制）、并行数；尝试单节点单核复现定位"),
    (r"(?:The job has been killed|Killed|killed)", "任务被杀（常见 OOM 或被调度系统清理）",
     "查看 SLURM 日志的 sacct -j <jobid> -o state；增大内存/缩短 walltime；减少并行核数"),
    (r"Error: integer\*4 overflow", "整数溢出（k 点或网格过大）",
     "减小 KPOINTS 网格或 NPAR 相关设置"),
    (r"^ERROR: ", "（LAMMPS 错误，M4 待完善）",
     "LAMMPS 错误请提供 error 行上下文"),
]


def parse_vasp_output(outcar_text: str) -> str:
    """解析 VASP OUTCAR 文本，提取能量、力、收敛与错误信息。

    Args:
        outcar_text: OUTCAR 文件内容（可传全文或 tail 截断部分）。

    Returns:
        结构化结果摘要（总能、离子步、收敛状态、力、压力、错误）。
    """

    lines = outcar_text.splitlines()

    # 电子总能（最后一个 TOTEN；OUTCAR 格式: "free  energy   TOTEN  = ..."）
    toten_re = re.compile(r"free\s+energy\s+TOTEN\s*=\s*([-\d.eE+]+)")
    energies = []
    for ln in lines:
        m = toten_re.search(ln)
        if m:
            energies.append(float(m.group(1)))

    # 离子步数（每个离子步一个 F= 行）
    n_ionic = sum(1 for ln in lines if re.search(r"\bF=\s*[-\d.eE+]+", ln))

    # 收敛
    converged = any("reached required accuracy" in ln for ln in lines)
    is_ediffg = any("EDIFFG" in ln and "=" in ln for ln in lines[:30])

    # 最大力（FORCES: max atom, force 行）
    forces = []
    fm_re = re.compile(r"FORCES:\s+max atom, force\s*=\s*([-\d.eE+]+)\s+([-\d.eE+]+)")
    for ln in lines:
        m = fm_re.search(ln)
        if m:
            forces.append((float(m.group(1)), float(m.group(2))))

    # 兜底：static 计算（NSW=0/IBRION=-1）无 FORCES 行，从 TOTAL-FORCE 表解析最大原子受力
    if not forces:
        for i, ln in enumerate(lines):
            if "TOTAL-FORCE" in ln and "(eV/Angst)" in ln:
                max_f = 0.0
                for body in lines[i + 1 :]:
                    parts = body.split()
                    if len(parts) >= 6:
                        try:
                            fx_, fy_, fz_ = (
                                float(parts[3]),
                                float(parts[4]),
                                float(parts[5]),
                            )
                        except ValueError:
                            break
                        mag = (fx_ * fx_ + fy_ * fy_ + fz_ * fz_) ** 0.5
                        max_f = max(max_f, mag)
                    elif len(parts) == 1 and set(parts[0]) <= {"-"}:
                        continue  # 分隔线
                    else:
                        break  # total drift 或块结束
                forces.append((max_f, max_f))
                break

    # 压力
    pressure = None
    pr_re = re.compile(r"external pressure\s*=\s*([-\d.eE+]+)")
    for ln in lines:
        m = pr_re.search(ln)
        if m:
            pressure = float(m.group(1))

    # 错误
    errors = [ln.strip()[:200] for ln in lines if re.search(r"Fatal error|Error", ln)][:5]

    # 终止信息
    finished = any("General timing and accounting informations" in ln for ln in lines)

    out = []
    if energies:
        out.append(f"最终电子总能 (TOTEN): {energies[-1]:.6f} eV")
        out.append(f"记录到的电子能量点数: {len(energies)}")
    else:
        out.append("未找到 free energy TOTEN（可能计算未完成或文本不完整）")
    out.append(f"离子步数: {n_ionic}")
    out.append(f"离子收敛 (reached required accuracy): {'是' if converged else '否'}")
    if is_ediffg and n_ionic > 0 and not converged:
        out.append("注意: 使用 EDIFFG 判据，可能尚未达到力收敛阈值")
    if forces:
        fx, fy = forces[-1]
        out.append(f"最后离子步最大力: {fx:.4f} eV/Å（力判据值 {fy:.4f}）")
    if pressure is not None:
        out.append(f"外部压力: {pressure:.4f} kbar")
    out.append(f"计算正常结束: {'是' if finished else '否（日志截断或中断）'}")
    if errors:
        out.append(f"检测到错误行（前 5 条）: {' | '.join(errors)}")
    else:
        out.append("未检测到明显错误关键字")
    return "\n".join(out)


def diagnose_vasp_error(log_text: str) -> str:
    """诊断 VASP 日志/输出中的错误模式，返回原因与修复建议。

    Args:
        log_text: OUTCAR / slurm 日志 / 终端输出的文本。

    Returns:
        匹配到的错误模式 + 修复建议（未匹配时给出提示）。
    """

    found = []
    for pattern, reason, advice in _VASP_ERROR_PATTERNS:
        if re.search(pattern, log_text, re.IGNORECASE):
            found.append((pattern, reason, advice))
    if not found:
        return (
            "未识别到已知 VASP 错误模式。\n"
            "建议：1) 提供日志中 'Fatal error' / 'Error' 附近的完整上下文；"
            "2) 检查作业状态 sacct -j <jobid> -o state；3) 确认内存与 walltime 充足。"
        )
    parts = [f"匹配到 {len(found)} 条错误模式："]
    for _, reason, advice in found:
        parts.append(f"- {reason}\n  修复建议: {advice}")
    return "\n".join(parts)

def analyze_vasprun(file_path: str) -> str:
    """解析本地 vasprun.xml，输出计算摘要：能量/带隙/费米能/磁矩/最大力/关键参数。

    Args:
        file_path: 本地 vasprun.xml 路径（可先用 download 从远程拉回）。

    Returns:
        结构化摘要文本。
    """
    import numpy as np  # noqa: F401  pymatgen 依赖链自带

    from pymatgen.io.vasp.outputs import Vasprun

    if not os.path.isabs(file_path) and not os.path.exists(file_path):
        cand = os.path.join(_OUTPUTS_DIR, file_path)
        if os.path.exists(cand):
            file_path = cand
    v = Vasprun(file_path, parse_projected_eigen=False, exception_on_bad_xml=False)
    rows = []
    rows.append(f"文件: {file_path}")
    try:
        gap, cbm, vbm, is_direct = v.eigenvalue_band_properties
        d = "直接" if is_direct else "间接"
        rows.append(f"带隙: {gap:.4f} eV（{d}；CBM {cbm:.4f} / VBM {vbm:.4f}）")
    except Exception as exc:  # noqa: BLE001
        rows.append(f"带隙: 未能解析（{type(exc).__name__}: 可能金属或数据不完整）")
    rows.append(f"最终总能 E0: {v.final_energy:.6f} eV")
    try:
        rows.append(f"费米能: {v.efermi:.4f} eV")
    except Exception:  # noqa: BLE001
        pass
    nelect = v.parameters.get("NELECT")
    if nelect:
        rows.append(f"电子数 NELECT: {nelect}")
    encut = v.incar.get("ENCUT") or v.parameters.get("ENCUT")
    ediff = v.incar.get("EDIFF") or v.parameters.get("EDIFF")
    ismear = v.incar.get("ISMEAR", v.parameters.get("ISMEAR", "N/A"))
    rows.append(f"参数: ENCUT={encut}, EDIFF={ediff}, ISMEAR={ismear}")
    steps = v.ionic_steps
    rows.append(f"离子步数: {len(steps)}")
    if steps:
        last = steps[-1]
        f_arr = last.get("forces")
        if f_arr is not None:
            import math as _m

            max_f = max(_m.sqrt(sum(c * c for c in row)) for row in f_arr)
            rows.append(f"最后一步最大原子力: {max_f:.4f} eV/Å")
        e_fr = last.get("e_fr_energy")
        if e_fr is not None:
            rows.append(f"最后一步自由能 F: {e_fr:.6f} eV")
    try:
        tmag = getattr(v, "total_mag", None)
        if tmag is not None and abs(tmag) > 1e-8:
            rows.append(f"总磁矩: {tmag:.4f} μB")
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(rows)

def parse_bader_acf(
    acf_path: str,
    potcar_path: Optional[str] = None,
    composition: Optional[str] = None,
) -> str:
    """解析 Bader 分析输出 ACF.dat：各原子 Bader 电子数 / 最小距离 / 原子体积。

    支持三种模式：
    1. 仅给 ACF（不传 potcar_path）：只列出各原子的 Bader 电子数等信息；
    2. ACF + POTCAR（composition 未给定，旧模式）：沿用「原子序号 idx → POTCAR 中
       第 idx 个 ZVAL」的历史映射，仅为兼容旧调用保留——真实 POTCAR 每个元素段只有
       一个 ZVAL 行，多元素多原子体系下该映射只能覆盖前 N_元素 个原子且对应关系错误；
    3. ACF + POTCAR + composition（推荐）：化学式（如 "Na2Cl2"、"Na20Mn23Ni7O64"）
       经 pymatgen Composition 得到元素块顺序与各元素原子数，与 POTCAR 各段 TITEL 的
       元素符号做顺序敏感的一致性校验后，按「元素块 × 该元素原子数」展开逐原子 ZVAL，
       为全部原子计算净电荷 Δq = ZVAL − n_Bader（ACF 原子行序即 POSCAR 元素块序）。

    Args:
        acf_path: 本地 ACF.dat 路径（可先用 download 拉回）。
        potcar_path: 可选 POTCAR 路径——提取各元素段的 ZVAL 价电子数。
        composition: 可选化学式字符串（pymatgen Composition 可解析），给定后启用模式 3
            的正确逐原子映射；不传则维持模式 2 的旧行为（兼容旧调用）。

    Returns:
        原子电荷表与汇总。
    """
    def _resolve(p: str) -> str:
        if not os.path.isabs(p) and not os.path.exists(p):
            cand = os.path.join(_OUTPUTS_DIR, p)
            if os.path.exists(cand):
                return cand
        return p

    path = _resolve(acf_path)
    atoms = []  # (idx, charge, min_dist, vol)
    vacuum_charge = None
    total_electrons = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            t = ln.split()
            if len(t) >= 7 and t[0].isdigit():
                try:
                    atoms.append((int(t[0]), float(t[4]), float(t[5]), float(t[6])))
                except ValueError:
                    continue
            elif "VACUUM CHARGE" in ln:
                vacuum_charge = float(ln.split(":")[1])
            elif "NUMBER OF ELECTRONS" in ln:
                total_electrons = float(ln.split(":")[1])
    if not atoms:
        return f"错误: [E_PARSE] {path} 中未解析到原子行（确认是 bader 输出的 ACF.dat）"

    # ── POTCAR 解析：逐段提取 ZVAL 价电子数与 TITEL 元素符号（按段序排列）──
    zvals: list[float] = []
    pot_symbols: list[str] = []  # 每个元素段的 TITEL 元素符号，如 ["Na", "Cl"]
    if potcar_path:
        import re as _re

        pp = _resolve(potcar_path)
        with open(pp, encoding="utf-8", errors="replace") as f:
            for ln in f:
                m_ = _re.search(r"ZVAL\s*=\s*([-\d.]+)", ln)
                if m_:
                    try:
                        zvals.append(float(m_.group(1)))
                    except ValueError:
                        continue
                # TITEL 行形如 "  TITEL  = PAW_PBE Na_pv 06Sep2000"：
                # 取等号后第 2 个空白分隔 token（"Na_pv"），去掉 "_" 及其后缀得 "Na"
                m_t = _re.search(r"TITEL\s*=\s*(\S+)\s+(\S+)", ln)
                if m_t:
                    pot_symbols.append(m_t.group(2).split("_")[0])

    # composition 模式必须依赖 POTCAR 的逐段 ZVAL
    if composition and not potcar_path:
        return "错误：[E_PARAM] 按化学式计算净电荷需同时提供 POTCAR 路径（potcar_path）"

    # ── 模式判定：composition 给定 → 元素块展开的正确映射；否则维持旧映射（兼容）──
    per_atom_zvals: Optional[list[float]] = None
    if composition:
        from pymatgen.core import Composition

        try:
            comp = Composition(composition)
        except Exception as exc:  # noqa: BLE001
            return f"错误：[E_PARSE] 化学式 '{composition}' 无法被 Composition 解析（{type(exc).__name__}: {exc}）"
        formula_blocks = [(sp.symbol, int(round(comp[sp]))) for sp in comp.elements]

        # 一致性校验（顺序敏感）：POTCAR 段数须等于元素种数，且段序符号逐一对应
        if len(pot_symbols) != len(formula_blocks) or pot_symbols != [
            s for s, _ in formula_blocks
        ]:
            return (
                f"错误：[E_PARAM] POTCAR 元素序 {pot_symbols} 与化学式 "
                f"{[s for s, _ in formula_blocks]} 不符"
                "（请确认 POTCAR 拼接顺序与 POSCAR/化学式的元素块序一致）"
            )
        if len(zvals) != len(pot_symbols):
            return (
                f"错误：[E_PARSE] POTCAR 中 ZVAL 数({len(zvals)})与 TITEL 段数({len(pot_symbols)})不一致，无法按段配对"
            )

        # 按「元素块 × 该元素原子数」展开逐原子 ZVAL 序列（ACF 原子行序即 POSCAR 元素块序）
        sym2zval = dict(zip(pot_symbols, zvals))
        per_atom_zvals = []
        for sym, n_atoms in formula_blocks:
            per_atom_zvals.extend([sym2zval[sym]] * n_atoms)

    seq = per_atom_zvals if per_atom_zvals is not None else zvals
    rows = ["原子   Bader电子数   最小距离(Å)   原子体积(Å³)" + ("   ZVAL   净电荷Δq" if seq else "")]
    net_all: list[float] = []
    for idx, q, dmin, vol in atoms:
        line = f"{idx:>4}   {q:>10.4f}   {dmin:>10.4f}   {vol:>10.4f}"
        if seq and idx <= len(seq):
            z = seq[idx - 1]
            dq = z - q
            net_all.append(dq)
            line += f"   {z:>5.2f}   {dq:>+7.4f}"
        rows.append(line)
    summary = [
        "",
        f"共 {len(atoms)} 个原子; 总电子数: {total_electrons if total_electrons is not None else 'N/A'}"
        f"; 真空电荷: {vacuum_charge if vacuum_charge is not None else 'N/A'}",
    ]
    if net_all:
        cation = max(net_all)
        anion = min(net_all)
        summary.append(f"失电子最多: +{cation:.4f} e; 得电子最多: {anion:.4f} e（净电荷=ZVAL−n_Bader，正为失电子）")
        # composition 模式下全体原子均有 Δq，补充整体统计：ΣZVAL−Σn_Bader 应≈−真空电荷
        if per_atom_zvals is not None and len(net_all) == len(per_atom_zvals):
            summary.append(
                f"全体原子总净电荷 ΣΔq: {sum(net_all):+.4f} e"
                f"（ΣZVAL−Σn_Bader，应≈−真空电荷；偏离过大提示电荷泄漏或元素块序有误）"
            )
    return "\n".join(rows + summary)
