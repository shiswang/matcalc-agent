"""任务状态监控层（S4.3）：弛豫/AIMD 进度与收敛质量的确定性解读。

设计要点：
- 解析器全部基于真机 vasp5.4.4 OUTCAR/OSZICAR 标本锚定（见 tests 锚点），
  纯文本进纯文本出，离线可测；
- 与 check_job 的分工：check_job 回答"作业到哪了"（队列层），
  本模块回答"算得怎么样了"（物理层：能量走势/受力/温度/磁矩）。
"""

from __future__ import annotations

import re
from typing import Optional

# ── 真机锚定的格式常量 ──
_RE_ION_ENERGY = re.compile(r"energy  without entropy=\s*(-?\d+\.\d+)")
_RE_TOTEN = re.compile(r"TOTEN\s*=\s*(-?\d+\.\d+)")
_RE_AIMD_TEMP = re.compile(r"\bT=?\s*(\d+\.\d+)")
_RE_MAG_OSZ = re.compile(r"mag=\s*(-?\d+\.\d+)")
_RE_E0 = re.compile(r"E0=\s*(-?\d+\.\d+)")


def monitor_relax(outcar_text: str, nsw_hint: Optional[int] = None) -> str:
    """【MCP 工具】弛豫进度与收敛质量解读：离子步走势 / 最新 TOTEN / 收敛判定。

    Args:
        outcar_text: OUTCAR 文本全文或尾部片段（≥1 个完整离子步即可）。
        nsw_hint: 可选，INCAR 的 NSW 值用于显示百分比；不给则只报步数。

    Returns:
        分级报告：🟢 正常推进 / 🟡 停滞(近3步ΔE均<1e-4 eV 但未达 EDIFFG) /
        🔴 异常(无离子步能量行且含 aborting/BOOM 关键词)。
        未发现离子步时返回"错误：..."开头文本。
    """
    text = outcar_text or ""
    energies = [float(x) for x in _RE_ION_ENERGY.findall(text)]
    totens = [float(x) for x in _RE_TOTEN.findall(text)]
    reached = ("reached required accuracy" in text) or ("aborting loop because EDIFF" in text)

    if not energies and not totens:
        if "aborting" in text or "BOZAI" in text or "exceeded" in text.lower():
            return "🔴 异常：OUTCAR 无任何离子步能量行且含中断关键词——计算很可能未正常开始（参数/势文件问题），建议 diagnose_vasp_error 深查。"
        return "错误：[E_PARSE] 文本中未找到离子步能量行（energy without entropy）与 TOTEN——请确认传入的是 VASP 的 OUTCAR。"

    cur = energies[-1] if energies else totens[-1]
    series = energies if len(energies) >= 2 else totens[-3:]
    lines: list[str] = []

    # 能量走势
    head = f"弛豫监控 · 离子步 {len(energies)} 步"
    if nsw_hint:
        head += f"/目标 {nsw_hint} ({len(energies) * 100 // max(1, nsw_hint)}%)"
    lines.append(head)
    last3 = series[-3:] if len(series) >= 3 else series
    for i, e in enumerate(last3):
        lines.append(f"  近端第{len(last3) - i}步前 E={e:.6f} eV")
    lines.append(f"  最新能量 E={cur:.6f} eV")

    # ΔE 走势分级
    grade = "🟢"
    deltas = [abs(series[i + 1] - series[i]) for i in range(len(series) - 1)] if len(series) >= 2 else []
    if deltas:
        d_last = deltas[-1]
        lines.append(f"  最近一步 |ΔE|={d_last:.2e} eV")
        if reached:
            pass  # 已收敛自然是绿
        elif len(deltas) >= 2 and all(d < 1e-4 for d in deltas[-2:]):
            grade = "🟡"
            lines.append("  ⚠ 连续两步 |ΔE|<1e-4 eV 但未见收敛标记——疑似停滞在噪声水平，考虑换算法(IBRION=1)/放宽EDIFFG")
    else:
        lines.append("  (仅一个离子步，无法评估走势)")

    if reached:
        lines.append("  ✅ 收敛标记已出现（reached required accuracy / EDIFF aborting loop）")
    elif grade == "🟢":
        lines.append("  尚未收敛，正常推进中")
    lines.append(f"{grade} 判定：{'已收敛' if reached else ('停滞嫌疑' if grade == '🟡' else '正常推进')}")

    # TOTEN 补充（若与能量行不一致说明文件被续写过）
    if totens and abs(totens[-1] - cur) > 1e-6:
        lines.append(f"  备注: 文件尾另见 TOTEN={totens[-1]:.6f} eV（可能为 Nsw 后追加的 static 段）")

    mag_line = _RE_MAG_OSZ.findall(text)
    if mag_line:
        lines.append(f"  最新磁矩(取自OSZICAR式行): mag={mag_line[-1]} μB")

    return "\n".join(lines)


def monitor_aimd(outcar_text: str, oscar_text: str = "", target_steps: int = 0,
                 target_temp: float = 0.0) -> str:
    """【MCP 工具】AIMD 运行状态解读：MD 步数 / 温度曲线 / 磁矩漂移 / 平台期判断。

    Args:
        outcar_text: OUTCAR 全文或片段。
        oscar_text: OSZICAR 文本（推荐提供，离子行含 F=/E0=/mag=）；缺省仅用 OUTCAR。
        target_steps: 目标 MD 总步数（INCAR NSW），>0 时输出百分比。
        target_temp: 目标温度 K（如 300），>0 时输出平均温度偏差。

    Returns:
        报告：步数/占比、平均温度±std、E0 平台期判断、磁矩漂移幅度、分级徽标。
        无法解析时返回"错误：..."。
    """
    text = outcar_text or ""
    ion_rows = _RE_E0.findall(oscar_text or "") or _RE_E0.findall(text)
    temps = [float(t) for t in _RE_AIMD_TEMP.findall(oscar_text or "")]
    mags = [float(m) for m in _RE_MAG_OSZ.findall(oscar_text or text)]

    if not ion_rows and not temps:
        return "错误：[E_PARSE] 未找到 AIMD 痕迹（需 OSZICAR 的离子行 E0= 或温度列 T）。"

    lines = ["AIMD 监控"]
    n_done = len(ion_rows) or len(temps)
    if target_steps > 0:
        pct = min(100, n_done * 100 // target_steps)
        lines.append(f"  进度: {n_done}/{target_steps} 步 ({pct}%)")
    else:
        lines.append(f"  已完成离子步: {n_done}")

    if temps:
        mean_t = sum(temps) / len(temps)
        std_t = (sum((t - mean_t) ** 2 for t in temps) / len(temps)) ** 0.5
        line = f"  温度: 平均 {mean_t:.1f} ± {std_t:.1f} K（采样 {len(temps)} 点）"
        if target_temp > 0:
            dev = (mean_t - target_temp) / target_temp * 100
            flag = "" if abs(dev) <= 10 else " ⚠ 偏离目标温超过 10%"
            line += f"，相对目标 {target_temp:g}K 偏差 {dev:+.1f}%{flag}"
        lines.append(line)

    if ion_rows:
        e_arr = [float(e) for e in ion_rows]
        tail = e_arr[-min(20, len(e_arr)):]
        span = max(tail) - min(tail)
        plat = "平台期" if span < 0.05 else f"仍在漂移(近20步跨度{span:.3f} eV)"
        lines.append(f"  E0 走势: 首值 {e_arr[0]:.4f} → 最新 {e_arr[-1]:.4f} eV；近端判 {plat}")
        drift = ""
        if mags and len(mags) >= 2:
            dm = max(mags) - min(mags)
            drift = f"；磁矩波动 {dm:.2f} μB"
            if dm > 2.0:
                drift += " ⚠ 磁性态可能有相变/重排，建议用 magmom 复核初值"
        lines.append(f"  磁矩: {mags[-1] if mags else '无'} μB{drift}")

    # 总体分级：异常关键字 > 温度偏离 > 正常
    if "SpanningTree" in text or "BOZAI" in text:
        overall = "🔴 异常"
    elif temps and target_temp > 0 and abs(mean_t - target_temp) > 0.1 * target_temp:
        overall = "🟡 温度偏离"
    else:
        overall = "🟢 正常"
    lines.append(overall)
    return "\n".join(lines)


TOOLS = [monitor_relax, monitor_aimd]
