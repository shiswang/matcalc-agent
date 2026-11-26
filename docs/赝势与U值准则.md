# 赝势（POTCAR）与 Hubbard U 值——本项目强制准则

> 来源：Materials Project 官方方法学文档（[Calculation Details](https://docs.materialsproject.org/methodology/materials-methodology/calculation-details)、
> [GGA/GGA+U](https://docs.materialsproject.org/methodology/materials-methodology/calculation-details/gga+u-calculations)、
> [Hubbard U Values](https://docs.materialsproject.org/methodology/materials-methodology/calculation-details/gga+u-calculations/hubbard-u-values)、
> [Pseudopotentials (GGA)](https://docs.materialsproject.org/methodology/materials-methodology/calculation-details/gga+u-calculations/pseudopotentials)、
> [Parameters and Convergence](https://docs.materialsproject.org/methodology/materials-methodology/calculation-details/gga+u-calculations/parameters-and-convergence)、
> [r2SCAN](https://docs.materialsproject.org/methodology/materials-methodology/calculation-details/r2scan-calculations)、
> [r2SCAN Pseudopotentials](https://docs.materialsproject.org/methodology/materials-methodology/calculation-details/r2scan-calculations/pseudopotentials)），
> 访问日期 2026-11-24。本文把 MP 的做法**转写为本项目必须遵守的准则**；凡标 `[必须]` 的条目，违反即视为计算不可信。

---

## 0. 适用范围与一句话原则

- **对接 MP 数据 / 与 MP 结果对比 / 算形成能·凸包·E_hull 时** → 必须按 MP 的赝势与 U 值方案，否则数值不可直接比较。
- **纯自有体系探索**（不对比 MP）→ 可自定参数，但必须在报告里写明与 MP 方案不同，且 U 值只能来自 `suggest_u` 的建议 + 人工确认，不得模型自由生成。
- **通用铁律**：赝势一经选定，**同一研究内不再更换**（换 POTCAR = 换计算基准，能量不可比）。

---

## 1. 赝势（POTCAR）准则

### 1.1 基本原则 `[必须]`

MP 用 VASP 官方 **PAW-PBE** 赝势库，选择策略是：**在满足收敛、且 ENMAX 不过高的前提下，选价电子数最多（high-e）的赝势**。排序准则：

1. 优先 high-e（如 `_sv` / `_pv` / `_d` / `_3` 后缀）；
2. 但该赝势若在本项目测试集或既往经验中**收敛困难**，或 ENMAX 过高（≈700 eV，如 `Na_sv`）→ 退回标准版；
3. 同一元素在所有计算中保持一致；改版本必须重算整条链并注明。

### 1.2 元素 → POTCAR 目录名（本项目必用对照表）`[必须]`

本项目的 POTCAR 由目录名拼接（`jobs.py`：`LOCAL_POTCAR_LIB/<目录>/POTCAR`），目录名**不是裸元素符号**，而是带后缀的。
下表是 MP GGA/GGA+U 方案对应的目录名；`potcar_elements` 参数必须按此表填写（顺序与 POSCAR 元素行一致）：

| 元素 | 目录名 | 元素 | 目录名 | 元素 | 目录名 |
|---|---|---|---|---|---|
| Li | `Li_sv` | Na | `Na_pv` | K | `K_sv` |
| Rb | `Rb_sv` | Cs | `Cs_sv` | Be | `Be_sv` |
| Mg | `Mg_pv` | Ca | `Ca_sv` | Sr | `Sr_sv` |
| Ba | `Ba_sv` | Sc | `Sc_sv` | Y | `Y_sv` |
| Ti | `Ti_pv` | Zr | `Zr_sv` | Hf | `Hf_pv` |
| V | `V_pv` | Nb | `Nb_pv` | Ta | `Ta_pv` |
| Cr | `Cr_pv` | Mo | `Mo_pv` | W | `W_pv` |
| Mn | `Mn_pv` | Fe | `Fe_pv` | Co | `Co` |
| Ni | `Ni_pv` | Cu | `Cu_pv` | Zn | `Zn` |
| Ru | `Ru_pv` | Rh | `Rh_pv` | Pd | `Pd` |
| Os | `Os_pv` | Al | `Al` | Ga | `Ga_d` |
| Ge | `Ge_d` | In | `In_d` | Sn | `Sn_d` |
| Tl | `Tl_d` | Pb | `Pb_d` | Bi | `Bi`（见 1.3） |
| Ce | `Ce` | Pr | `Pr_3` | Nd | `Nd_3` |
| Pm | `Pm_3` | Sm | `Sm_3` | Eu | `Eu` |
| Gd | `Gd` | Tb | `Tb_3` | Dy | `Dy_3` |
| Ho | `Ho_3` | Er | `Er_3` | Tm | `Tm_3` |
| Yb | `Yb_3` | Lu | `Lu_3` | La | `La` |
| H | `H` | B/C/N/O/F | `B`/`C`/`N`/`O`/`F`（标准版，不用 `_s`/`_h`） | Si/P/S/Cl | `Si`/`P`/`S`/`Cl`（标准版） |

主族其余（As/Se/Br/I/Te 等）用标准版；锕系 U/Ac/Th/Pa/Np/Pu 用标准版（不用 soft）。

### 1.3 赝势相关的已知陷阱 `[必须]`

- **顺序**：POTCAR 段序必须与 POSCAR 元素行**完全一致**。本项目 `jobs.py` 已校验 `potcar_elements` 与 POSCAR 元素行一致；`parse_bader_acf` 也校验 TITEL 序与化学式序一致。报错时按元素序重拼，不要改 POSCAR。
- **Yb**：MP 于 2023-05-02 把全部输入集的 `Yb_2` 改为 `Yb_3`（`Yb_2` 对 Yb³⁺ 热力学错误）。本项目一律用 `Yb_3`。
- **Bi**：`Bi_d` 有收敛问题，MP 决定搁置；本项目默认用标准 `Bi`，若用 `_d` 必须单独做收敛测试并记录。
- **Tb**：只有 `Tb_3` 赝势，但 Tb 可有 +4（如 TbO₂）；此类体系该赝势不可信，须人工评估并标注。
- **硬赝势**：`Al_h`/`Ge_h` 等在能带中出现"ghost state"，`_h` 一般不用；`Na_sv` ENMAX≈700 eV 性价比低，不用。
- **本地库状态**：本机 `potcars/potpaw_PBE` 中 `W_pv` 目录缺失（r2SCAN 的 `W_sv` 可能存在）；需要 W 的 MP 对接计算前先补齐赝势库，否则提交会在 `jobs.py` 处 `E_CLUSTER` 失败。
- **版权**：POTCAR 受 VASP 许可约束，库不入 git、不分发（见 `AGENTS.md`）。

### 1.4 两套能量方案的赝势不同 `[必须]`

| 方案 | 赝势来源 | ENCUT | k 点 | 备注 |
|---|---|---|---|---|
| GGA / GGA+U | 旧 PBE 库（部分为 2002 年前） | **520 eV**（≈1.3×最高 ENMAX） | 1000/原子（Monkhorst-Pack，六角 Γ 中心，四面体积分） | 见 1.2 表 |
| r2SCAN | **PBE PAW datasets v54**（2015-09） | **680 eV** | KSPACING 0.22–0.44 Å⁻¹（按 GGA 带隙定） | 无 SCAN 专用赝势，沿用 PBE；部分目录名不同，如 `W_sv`、`Na_pv`(19Sep2006)、`Cl`(06Sep2000) |

**关键**：GGA 与 r2SCAN 的 POTCAR TITEL 日期不同，**不可混用同一份 POTCAR 跑两套方案**；mp-api 的 `thermo_type` 混合 hull（默认 `GGA_GGA+U_R2SCAN`）背后是两套独立计算。

---

## 2. Hubbard U 准则

### 2.1 MP 官方 U 值表（校准自氧化物形成焓，仅 d 轨道）`[必须·对接 MP 时]`

| 元素 | 体系 | 氧化还原对 | 校准 U (eV) | 拟合反应要点 |
|---|---|---|---|---|
| Co | 氧化物 | Co²⁺→Co²·⁶⁷⁺ | **3.32** | 6CoO+O₂→2Co₃O₄ |
| Cr | 氧化物 | Cr³⁺→Cr⁶⁺ | **3.70** | 2/3Cr₂O₃+O₂→4/3CrO₃ |
| Fe | 氧化物 | Fe²⁺→Fe²·⁶⁷⁺ / Fe²·⁶⁷⁺→Fe³⁺ | **5.30** | FeO/Fe₃O₄/Fe₂O₃ 两反应 |
| Mn | 氧化物 | Mn²⁺→Mn²·⁶⁷⁺ / Mn²·⁶⁷⁺→Mn⁴⁺ | **3.90** | MnO/Mn₃O₄/MnO₂（Mn₂O₃ 排除） |
| Mo | 氧化物 | Mo⁴⁺→Mo⁶⁺ | **4.38** | MoO₂→MoO₃ |
| Ni | 氧化物 | Ni²⁺→Ni³⁺ | **6.20** | Li₂O+2NiO+½O₂→2LiNiO₂（三元校准） |
| V | 氧化物 | V³⁺→V⁴⁺ / V⁴⁺→V⁵⁺ | **3.25** | V₂O₃/VO₂/V₂O₅（VO 排除） |
| W | 氧化物 | W⁴⁺→W⁶⁺ | **6.20** | WO₂→WO₃ |

**这是校准值,不是物理常数**。对接 MP 时,上表元素在**氧化物/氟化物**中必须用这些值;其余元素在 MP 方案里**不加 U**。

### 2.2 何时加 U `[必须]`

- **加 U 条件**（MP 规则）：材料是**氧化物或氟化物** 且 含上表 8 种过渡金属之一 → **只对这些元素的 d 轨道加 U**。
- **氟化物**：MP 用氧化物校准的 U 值套用在氟化物上（架构允许分别设定但当前如此）。
- **不加 U**：硫化物、氮化物、碳化物、纯金属、主族化合物——MP 方案不加 U。若研究体系确需 +U，必须说明来源并标注"偏离 MP 方案"。
- **不能按位点给不同 U**：MP 的做法是对该元素**所有位点**加同一个 U；本项目 `LDAUU` 按元素展开，天然符合此约定。
- **U 依赖赝势**：换 POTCAR 后 U 值需重新评估，不能照搬。

### 2.3 VASP 参数写法 `[必须]`

用 Dudarev 方案（`LDAUTYPE=2`），本项目 `generate_vasp_inputs(ldau_u=...)` 已按此生成：

```
LDAU = .TRUE.
LDAUTYPE = 2          ! Dudarev，只依赖 U-J
LDAUL = ...           ! 按 POSCAR 元素序：加 U 元素=2(d)，其余=-1；f 元素=3
LDAUU = ...           ! 按元素序：加 U 元素=表中值，其余=0
LDAUJ = ...           ! 全 0（并入 U_eff）
LMAXMIX = 4           ! 含 f 电子体系必须改 6
```

- **长度铁律**：`LDAUL/LDAUU/LDAUJ` 三项长度**必须等于 POSCAR 物种数**，且与元素序一一对应（见 `AGENTS.md` 环境陷阱）。本项目由 `vasp_inputs.py` 按 `comp.elements` 自动展开，不要手写覆盖。
- **f 电子**：Ce/Pr/Nd 等稀土若加 U，须显式 `ldau_l="Ce=3,..."` 指定 f 通道，并把 `LMAXMIX` 改为 6；MP 官方 U 表**未校准稀土**，建议值只能来自文献，且不可声称"对齐 MP"。

### 2.4 本项目的 U 值来源分层（避免与 MP 标准混淆）`[必须]`

| 来源 | 定位 | 使用场景 |
|---|---|---|
| 本文 2.1 表（MP 官方） | **对接 MP 的唯一标准** | 算形成能/凸包/E_hull、与 MP 对比 |
| `suggest_u` 的 `_U_TABLE` | **建议值，非 MP 标准** | 自有体系起点；须人工确认后使用 |
| 用户确认回流（`record_feedback`） | 项目私有经验 | sidecar 持久化，优先于默认表 |

**必须注意的差异**：本项目 `suggest_u` 的默认锚点与 MP 官方表**有意不同**（来源于本库实战或文献区间，如 Ti=4.5、Fe=4.3、Mn=4.0、W=4.0、Cu=4.0 等，而 MP 的 Fe=5.30、Mn=3.90、W=6.20，且 MP 没有 Ti/Cu/Nb/稀土的校准 U）。
因此：

- 调用 `suggest_u` 得到的值**不得直接声称是 MP 值**；
- 写报告时若用非 MP 值，必须标注 `source=本库建议/文献/用户确认`，不能写 `MP`；
- 对接 MP 时**以 2.1 表为准**，覆盖 `suggest_u` 的建议。

### 2.5 适用性与免责 `[必须]`

- MP 的 U 是**为相稳定性（形成焓）校准**的；**用于能带/带隙要谨慎**，可能给出错误的带隙或能级位置——报告里必须提示这一点。
- U 值不应跨体系照搬：同一元素在不同化合物/价态/配位下最优 U 不同；MP 因高通量才统一按元素给值。
- 自旋极化必须开启（`ISPIN=2`），磁性离子高自旋 FM 初始化（系统可在弛豫中降低自旋）；本项目 `generate_vasp_inputs` 传 `magmom=` 会自动开 `ISPIN=2`。

---

## 3. 与本项目现有实现的对应（自检清单）

提交任何 VASP 作业前，逐项确认：

- [ ] `potcar_elements` 用的是**带后缀的目录名**（按 1.2 表），不是裸元素符号；顺序与 POSCAR 元素行一致。
- [ ] POTCAR TITEL 元素序与 POSCAR 一致（`parse_bader_acf` 会校验；提交后 30 秒四查也含此项）。
- [ ] ENCUT：GGA 方案 520 eV、r2SCAN 方案 680 eV（或 ≥1.3×实际 POTCAR 最大 ENMAX，取大者）。
- [ ] 若对接 MP 且含 8 元素之一且为氧化物/氟化物：`ldau_u` 用 **2.1 表**的精确值，`ldau_l` 不传（默认 d 通道=2）。
- [ ] `LDAUL/LDAUU/LDAUJ` 由工具生成且长度=物种数（人工改 INCAR 后必须复核）。
- [ ] 含 f 电子体系：`ldau_l` 指定 f=3 且 `LMAXMIX=6`。
- [ ] `ISPIN=2` 且给了 `magmom`（或明确说明为何非磁性）。
- [ ] 报告中注明赝势方案（GGA-旧库 / r2SCAN-v54）、U 值来源（MP 标准 / 本库建议 / 用户确认）。

---

## 4. 变更记录

- 2026-11-24 初版：依据 MP 官方方法学文档整理；含 GGA/r2SCAN 两套赝势方案、8 元素 U 值表、与 `suggest_u` 默认值的差异说明、提交前自检清单。
