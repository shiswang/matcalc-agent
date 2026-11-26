---
name: mat-ehull-stability
description: Calculate 0 K convex-hull thermodynamic stability (E_hull) of a compound; decide if it is stable or will decompose. Use when asked whether a material is stable, on hull, or its decomposition driving force.
metadata:
  category: [materials]
  tools: [fetch_mp_structure, mp_phase_diagram, mp_reaction_energy, export_report, export_result_note]
  scripts: [scripts/compute_ehull.py]
---

# E_hull 稳定性计算

## Goal

判断一个化合物在 0 K 是否落在凸包上（热力学稳定），并给出 **E_hull**（energy above convex hull，eV/atom）。
E_hull = 0 表示稳定；E_hull > 0 表示相对凸包有能量盈余，存在分解为稳定相组合的热力学驱动力。数值越小越接近稳定。

> 本技能用 **Materials Project 的 r2SCAN/GGA DFT 数据**在 0 K 近似，不是用户自己 VASP 计算的结果。
> 适合趋势判断、凸包位置和分解副产物初筛；最终结论以自己体系的计算为准。

## 何时使用 / 不适用

- **适用**：问「LiFePO4 稳定吗」「这个化合物会不会分解」「E_hull 多少」「有哪些竞争相」。
- **不适用**：
  - 有限温稳定性（要振动自由能 / 声子）——本技能是 0 K，见「能力边界」。
  - 电化学稳定窗口（对 Li/Li+ 的电位窗口）——那是另一套方法，本技能不做。
  - 无 MP key 时——`fetch_mp_structure` / `mp_phase_diagram` 都会返回 `E_PARAM`，改用离线建模但无法算 MP 凸包。

## 前置条件

- 设置 `MP_API_KEY`（https://next-gen.materialsproject.org/api）；不要把 key 写进代码或文档。
- 用法级别一致性：MP 默认 r2SCAN 与 GGA+U 条目混用会抬高凸包；脚本默认按 `thermo_type` 过滤。

## 步骤

1. **先看体系稳定相清单**（确认目标是否在凸包上的候选里）

   ```
   mcp__matcalc__mp_phase_diagram(chemsys="Li-Fe-P-O")
   ```

   返回该化学体系的稳定相列表与形成能（eV/atom）。若目标化合物出现在稳定相清单中，E_hull ≈ 0，可直接进入第 5 步下结论。若不在，继续第 2 步精确算 E_hull。

2. **取目标化合物的结构**（作为 E_hull 计算的目标条目）

   ```
   mcp__matcalc__fetch_mp_structure(query="LiFePO4", project="li_fe_p_o", save=True)
   ```

   返回归一化的 VASP5 POSCAR 并落盘 `server/outputs/li_fe_p_o/structures/`。若无 key 或 MP 无此条目，返回 `E_PARAM`——此时停止，改用离线建模无法继续本技能。

3. **查分解反应的驱动力**（可选，给出副产物层面的直观解释）

   ```
   mcp__matcalc__mp_reaction_energy(reaction="LiFePO4 -> LiFeO2 + FePO4")
   ```

   ΔE < 0 表示按书写方向放热，可作为分解倾向的旁证。反应式要自己配平、用真实化学式。

4. **精确计算 E_hull**（本技能的核心；工具层没有直接的 E_hull 工具，用本地脚本补上）

   在仓库根目录执行（Windows 用 `.venv\Scripts\python.exe`）：

   ```bash
   .venv\Scripts\python.exe skills/mat-ehull-stability/scripts/compute_ehull.py \
     --chemsys "Li-Fe-P-O" --target "LiFePO4" --thermo-type R2SCAN \
     --out server/outputs/li_fe_p_o/ehull
   ```

   脚本做三件事：用 `mp-api` 拉该体系全部条目 → 过滤 `thermo_type` → 用 pymatgen `PhaseDiagram.get_e_above_hull()` 对目标条目算 E_hull，并把竞争相与结果写成 JSON+Markdown 到 `--out` 目录（默认落 outputs 内）。
   成功标志：输出含 `E_hull (eV/atom) = ...` 且退出码 0；失败会打印 `错误：` 并以非 0 退出。

5. **下结论 + 归档**（结论必须含数值、体系和理论级别三要素）

   ```
   mcp__matcalc__export_report(
     title="LiFePO4 的 0 K 稳定性",
     sections="## E_hull\n<第4步数值> eV/atom (R2SCAN, MP)\n## 稳定相\n<第1步清单>\n## 分解驱动力\n<第3步 ΔE>",
     project="li_fe_p_o"
   )
   ```

   若要把结论沉淀进知识库，用 `export_result_note` 生成 `status: candidate` 笔记（不要直写 Vault）：

   ```
   mcp__matcalc__export_result_note(
     project="li_fe_p_o", source_job="MP-R2SCAN",
     rows_json="[[\"E_hull(eV/atom)\",\"0.000\"],[\"thermo_type\",\"R2SCAN\"],[\"chemsys\",\"Li-Fe-P-O\"]]",
     params_chain_json="[\"fetch_mp_structure\",\"mp_phase_diagram\",\"compute_ehull\"]"
   )
   ```

## 示例：LiFePO4 是否稳定

```text
1) mp_phase_diagram(chemsys="Li-Fe-P-O")
   → 稳定相清单若含 LiFePO4，则 E_hull≈0（稳定），跳到 5）

2) 若不含：fetch_mp_structure(query="LiFePO4", project="li_fe_p_o")
   → outputs/li_fe_p_o/structures/ 下得到 POSCAR

3) compute_ehull.py --chemsys "Li-Fe-P-O" --target "LiFePO4" \
     --thermo-type R2SCAN --out server/outputs/li_fe_p_o/ehull
   → E_hull (eV/atom) = 0.0xxx

4) export_report(...) + export_result_note(...) 归档
```

## 能力边界与常见坑

- **0 K、无熵**：E_hull 不含有限温振动熵；高温稳定性需声子/QHA（本仓库未封装，见 `mp_workflow_guide(topic="phonon")`）。
- **理论级别混用**：MP 同时有 GGA/GGA+U 与 r2SCAN 条目。不按 `thermo_type` 过滤会让凸包偏高、E_hull 失真。脚本默认 `R2SCAN`，与 MP 生产链一致。
- **E_hull 数值量级**：> 0.1 eV/atom 通常认为明显亚稳；< 0.025 eV/atom 常落入 DFT 误差范围，不要过度解读。
- **不是自己的 DFT 结果**：MP 是别人的计算；若研究体系有强关联/特殊磁态，应以自己 VASP 计算重算凸包。
- **`mp_phase_diagram` 的返回**：它只列稳定相与形成能，**不直接输出指定化合物的 E_hull**——这是本技能自带脚本的原因，别把「稳定相清单」当成 E_hull 结果。
- **key 与网络**：无 key 或 MP 配额耗尽时全部 MP 工具返回 `E_PARAM`/`E_CLUSTER`；离线时本技能不可完成。

## 相关技能

- [AIMD 扩散系数](../mat-diffusion-aimd/SKILL.md)：得到稳定相后进一步算离子迁移。
- `mcp__matcalc__mp_workflow_guide(topic="phonon")`：有限温稳定性的延伸方向（知识对照，不执行）。
