---
name: mat-diffusion-aimd
description: Compute ionic diffusion coefficient and activation energy from AIMD trajectories (MSD + Einstein relation, multi-temperature Arrhenius fit). Use when asked for diffusivity, ionic conductivity, or migration barriers from molecular dynamics.
metadata:
  category: [materials]
  tools: [build_structure, make_supercell, generate_aimd_inputs, submit_and_watch, monitor_aimd, analyze_vasprun, export_report]
  scripts: [scripts/msd_diffusivity.py]
---

# AIMD 扩散系数计算

## Goal

从 AIMD（从头算分子动力学）轨迹计算离子的**扩散系数 D**（Å²/ps 或 m²/s），并可由多温度点拟合**激活能 E_a**（Arrhenius）。
方法：对选定离子求均方位移 MSD → Einstein 关系 `D = slope / (2·d)`（d 为扩散维度）→ 多温度 `ln D` vs `1/T` 线性拟合得 E_a。

> 新版本 pymatgen（2026.5.4）已移除 `DiffusionAnalyzer`，63 个 MCP 工具也没有扩散拟合工具，
> 因此本技能用自带脚本 `msd_diffusivity.py`（仅 numpy）完成 MSD→D→E_a 后处理。AIMD 输入仍走确定性 MCP 工具。

## 何时使用 / 不适用

- **适用**：问「Li/Na 离子扩散系数多少」「从 AIMD 算迁移能垒」「离子电导率趋势」「不同温度 D 的比较」。
- **不适用**：
  - 固态 NEB 迁移能垒（那是 `generate_neb_*` 工具，静态路径，不是热涨落轨迹）。
  - 极短轨迹（< 10 ps）或单温度点求 E_a——统计不足，结果不可信。
  - 含 H 的体系用 POTIM ≤ 0.5 fs；本技能默认 1.0 fs 仅适用于不含轻元素的氧化物。

## 前置条件

- 一个**已弛豫的超胞** CONTCAR（建议 ≥ 2×2×2，原子数 ≥ 数十）——有限尺寸效应会严重低估 D。
- AIMD 轨迹：VASP 的 `XDATCAR`（含每步坐标）或 `vasprun.xml`。脚本优先用 XDATCAR。
- 远程作业需已 `configure_remote` / `check_connection`；离线只做输入生成与后处理。

## 步骤

1. **准备超胞结构**（从已弛豫结构出发，别用粗建模胞直接跑 MD）

   ```
   mcp__matcalc__build_structure(composition="Na2ZrCl6", prototype="fluorite", project="na_zr_cl6")
   mcp__matcalc__make_supercell(poscar_text="<上一步POSCAR>", a=2, b=2, c=2)
   ```

   先把该超胞做一次弛豫（走 `relax_dos_standard` 或 `generate_vasp_inputs(calc_type="relax")`），拿收敛的 CONTCAR 作 AIMD 起点。

2. **生成 AIMD 输入**（NVT，Nosé-Hoover，恒温）

   ```
   mcp__matcalc__generate_aimd_inputs(
     poscar_text="<已弛豫CONTCAR>",
     temperature=600.0, nsw=5000, potim=1.0, encut=520,
     ldau_u="Zr=0", project="na_zr_cl6"
   )
   ```

   总时长 ≈ nsw × potim = 5000 × 1 fs = 5 ps。**温度真实值由你定**（氧化物常用 600–1200 K 以在有限时间内看到跳迁）；参数建议不自动执行，需你确认。含 H 体系务必 `potim=0.5`。

3. **提交并监控**（远程；半自动，占位结构会被护栏拒绝）

   ```
   mcp__matcalc__submit_and_watch(project="na_zr_cl6", local_dir="<输入目录>", node="master", ppn=48, potcar_elements="Na,Zr,Cl")
   mcp__matcalc__monitor_aimd(outcar_text="<OUTCAR>", oscar_text="<OSZICAR>", target_steps=5000, target_temp=600.0)
   ```

   `monitor_aimd` 看进度/温度是否漂移/E0 是否进入平台期；温度偏离目标 > 10% 或磁矩剧烈漂移要先诊断再继续。

4. **回收轨迹并算 D**（本地脚本，读 XDATCAR）

   ```bash
   .venv\Scripts\python.exe skills/mat-diffusion-aimd/scripts/msd_diffusivity.py \
     --xdatcar server/outputs/na_zr_cl6/XDATCAR --species Na \
     --timestep-fs 1.0 --temp 600 --dim 3 \
     --out server/outputs/na_zr_cl6/diffusion
   ```

   输出：MSD 曲线数据、线性拟合区间斜率、D（Å²/ps 与 m²/s）。成功标志：打印 `D = ... Å²/ps` 且退出码 0。
   **拟合区间**：默认跳过前 20% 轨迹（平衡期），用中段线性区；若 MSD 明显弯曲，用 `--fit-start/--fit-end` 手动指定分数区间。

5. **多温度拟合 E_a**（可选，需 ≥ 3 个温度点）

   ```bash
   .venv\Scripts\python.exe skills/mat-diffusion-aimd/scripts/msd_diffusivity.py \
     --arrhenius "600:0.0012,800:0.0045,1000:0.0110" \
     --out server/outputs/na_zr_cl6/diffusion
   ```

   （`600:0.0012` 表示 T=600 K、D=0.0012 Å²/ps，D 来自第 4 步各温度的结果）
   输出 `E_a = ... eV` 与拟合 R²。

6. **归档**

   ```
   mcp__matcalc__export_report(
     title="Na2ZrCl6 中 Na 离子扩散",
     sections="## D(600K)\n<第4步>\n## E_a\n<第5步>\n## 轨迹长度\n5 ps / 5000 步",
     project="na_zr_cl6"
   )
   ```

## 示例：Na2ZrCl6 中 Na 扩散（600 K 单点）

```text
1) build_structure("Na2ZrCl6", prototype="fluorite", project="na_zr_cl6") → POSCAR
2) make_supercell(POSCAR, 2,2,2) → 超胞；先弛豫取 CONTCAR
3) generate_aimd_inputs(CONTCAR, temperature=600, nsw=5000, potim=1.0, project="na_zr_cl6")
4) submit_and_watch(...) → 完成后把 XDATCAR 放回 outputs/na_zr_cl6/
5) monitor_aimd(OUTCAR, OSZICAR, target_steps=5000, target_temp=600) → 温度稳、E0 平台
6) msd_diffusivity.py --xdatcar .../XDATCAR --species Na --timestep-fs 1.0 --temp 600
   → D = 0.0012 Å²/ps = 1.2e-7 m²/s
```

## 能力边界与常见坑

- **轨迹长度决定可信度**：5 ps 常只能看到少数跳迁，D 的统计误差可达一个量级。生产级建议 ≥ 20–50 ps 或做多个独立种子。
- **有限尺寸效应**：原胞算 D 会系统性偏低；必须超胞。原子数翻倍、D 显著变化说明尺寸仍不够。
- **POTIM 与轻元素**：含 H 用 1 fs 会丢高频振动，必须 ≤ 0.5 fs。
- **温度选择**：室温下跳迁事件稀少，D 可能小到拟合不出斜率；高温加速采样再用 Arrhenius 外推是常规做法，但外推要说明。
- **MSD 拟合区间**：初始弹道段（非线性）和末端统计噪声段都要避开；默认跳过前 20%，复杂体系要人工检查 MSD 曲线。
- **维度 d**：体相用 `--dim 3`；层状材料二维迁移用 `--dim 2`，选错 D 会差 1.5 倍。
- **XDATCAR 必需**：脚本按 XDATCAR 的逐帧坐标算 MSD；只有 OUTCAR/OSZICAR 无法算 D，需重跑时设 `XDATCAR` 输出。
- **不使用已移除的 API**：不要尝试 `pymatgen.analysis.diffusion.aimd.DiffusionAnalyzer`（2026.5.4 已无此类）。

## 相关技能

- [E_hull 稳定性](../mat-ehull-stability/SKILL.md)：先确认相稳定，再研究其中的离子迁移。
- `mcp__matcalc__mp_workflow_guide(topic="neb")`：静态迁移能垒的对照方法（NEB 工具）。
- `mcp__matcalc__generate_neb_images`：已有扩散路径端点时，用 NEB 算能垒。
