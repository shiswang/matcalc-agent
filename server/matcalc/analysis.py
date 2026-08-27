"""性质分析：状态方程拟合等纯计算（后续追加形成能等）。

（R2 自 main.py 原样迁移，函数体未改动）"""

from __future__ import annotations

from typing import Union, List

def fit_eos(volumes: list[float], energies: list[float]) -> str:
    """Birch-Murnaghan 三阶状态方程拟合 E(V) 数据。

    Args:
        volumes: 体积列表 (Å³)，与 energies 一一对应。
        energies: 总能列表 (eV)。

    Returns:
        平衡体积 V0 / 体模量 B0 / 压强导数 B0' / 最小能量 E0 与拟合质量。
    """
    from pymatgen.analysis.eos import BirchMurnaghan

    if len(volumes) != len(energies) or len(volumes) < 4:
        return "错误: [E_PARAM] 需要 ≥4 组 (V, E) 数据且长度一致"
    eos = BirchMurnaghan(list(volumes), list(energies))
    eos.fit()
    rows = [
        "Birch-Murnaghan 三阶 EOS 拟合结果:",
        f"平衡体积 V0 = {eos.v0:.4f} Å³",
        f"体模量 B0 = {eos.b0_GPa:.2f} GPa ({eos.b0:.6f} eV/Å³)",
        f"B0' = {eos.b1:.3f}",
        f"最小能量 E0 = {eos.e0:.6f} eV",
    ]
    # 拟合残差
    e_fit = [eos.func(v_) for v_ in volumes]
    rms = (sum((e - ef) ** 2 for e, ef in zip(energies, e_fit)) / len(volumes)) ** 0.5
    rows.append(f"拟合 RMS 残差 = {rms:.6f} eV（< 1 meV/atom 为佳）")
    return "\n".join(rows)
