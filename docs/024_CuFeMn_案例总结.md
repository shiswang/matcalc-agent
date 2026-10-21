# 024_CuFeMn 案例总结（V 系列 v2 / Cu 系列）

> **状态**：两条线都已完成并各自复核通过（2026-10-20 收尾）。本文是**结论汇总**；
> 协议细节见 `HANDOFF.md` §7.2–§7.5，脚本见 `scripts/campaigns/024_CuFeMn_V/`，
> 数据与数据包在 `server/outputs/024_CuFeMn_V/`（不入 git）。
> 文中每个数字都能在对应文件里复核，命令见 §8。

## 0. 一页速览

| 项 | 内容 |
|---|---|
| 科学问题 | P2 型 Na 层状氧化物里，**氧空位**与**N 取代氧位**的形成能怎么分布？把金属位从 **V 换成 Cu** 会怎样？ |
| 体系 | 母体 Na₁₀Ti₂Mn₁₀Fe₁**X**₁Ni₄O₃₆（X = V / Cu），64 原子；12 个局部环境位点 × 2 个分支（N-O / O-van）= 24 个缺陷 × 2 条线 |
| 计算量 | 每条线：1 次母体弛豫 + 24 次缺陷弛豫 + 25 次统一静态 = 50 个作业（bkzhang / Slurm） |
| 主结论 1 | **Cu 相对 V 全面更不利**：共同 8 位点上 O 空位平均 **+1.023 eV**、N 取代平均 **+0.700 eV** |
| 主结论 2 | **位点偏好强烈依赖替代元素**：V 里最稳的 O 空位位点 MnFeTi（1.282 eV）在 Cu 里是**最不稳**的（3.685 eV，12/12）→ 位点排序不能跨替代元素搬用 |
| 主结论 3 | **静态单点不能省**：静态与弛豫末态总磁矩有 13/24（V）、17/24（Cu）个缺陷跳变（整数 μB），能量差最大 1.74 eV → **差值 < 0.1 eV 的位点排序不可作结论** |
| 主结论 4 | **+U 逐元素键控 + 逐 OUTCAR 反解校验**：两批 50 个 OUTCAR 全部通过约定校验，24 个形成能独立复核零偏差 |

## 1. 体系与两条线

- **母体**：P2 型 Na 层状氧化物 `Na10 Ti2 Mn10 Fe1 X1 Ni4 O36`（64 原子）。V 系列的唯一差别是把唯一的 V 位换成 Cu。
- **母体物种序**：`Na Ti Ni Mn Fe X O`（X 在 0 基第 27 位）；**缺陷统一用** `Na Ti Mn Fe X Ni [N] O` 重排。
- **位点标签**：12 个局部环境标签（邻接金属组合），两条线里 8 个共有、4 个各自独有
  （V 独有：VMnTi / VNiMn / VTiNi / MnMnV；Cu 独有：CuMnTi / CuNiMn / CuTiNi / MnMnCu）。
- **两条线**：

| | V 系列（v2） | Cu 系列 |
|---|---|---|
| workflow | `v2_u_convention_20261016` | `cu_u_convention_20261017` |
| 母体静态 | −410.77517624 eV | −402.41000035 eV |
| 约定 +U | Ti 5.2 / Mn 3.9 / Fe 4.0 / **V 3.25** / Ni 6.2 | Ti 5.2 / Mn 3.9 / Fe 4.0 / Ni 6.2 / **Cu 1.9** |
| 结果目录 | `defect_formation_comparison_v2/` | `defect_formation_comparison_cu/` |
| 数据包 | `package/024_CuFeMn_V_VASP_data.zip`（46 MB） | `package/024_CuFeMn_Cu_VASP_data.zip`（84.3 MB） |

> 两条线的**绝对能量不可直接比较**（元素不同、+U 组合不同）——只有**形成能**可以横向比。

## 2. 协议（两条线完全一致，所以可比）

| 项 | 设置 |
|---|---|
| 程序 | VASP 6.6.0（build Jun 02 2026），PAW_PBE，IVDW = 11（D3），ISPIN 2，NCORE 4 |
| 截断与网格 | ENCUT 520 eV，Γ 中心 5×5×1（13 个不可约 k 点），ISMEAR = −5 |
| 弛豫 | NSW 200 / IBRION 2 / ISIF 3，EDIFFG −0.02，POTIM 0.5，ISYM 2 |
| 静态 | NSW 0 / IBRION −1 / ISIF 2，LWAVE = LCHARG = .FALSE. |
| +U | Dudarev LDAUTYPE = 2、UJ = 0，**逐元素**赋值：Ti 5.2 / Mn 3.9 / Fe 4.0 / Ni 6.2 / V 3.25（或 Cu 1.9），Na / N / O 不加 U |
| 赝势 | 全 `_pv`（`Na_pv Ti_pv Mn_pv Fe_pv V_pv Ni_pv [N] O`；Cu 线换 `Cu_pv`） |
| 元素参考 | O2 / N2 分子静态（15 Å 盒、Γ 单点、ISMEAR 0、σ 0.01，**LDAU = .FALSE.**，两条线共用） |

**形成能公式**（中性缺陷，原始 PBE-D3 分子能量，未加经验氧修正 / 零点能 / 温压修正）：

```
Ef(O 空位)   = E(O35)   − E(parent O36) + 0.5 E(O2)
Ef(N 取代 O) = E(N1O35) − E(parent O36) + 0.5 E(O2) − 0.5 E(N2)
```

参考值（两条线共用）：E(O2) = −9.85924862 eV，E(N2) = −16.63493877 eV，μO = −4.92962431 eV，μN = −8.317469385 eV。

## 3. 执行

| | V 系列 | Cu 系列 |
|---|---|---|
| 母体弛豫 | ISIF=3，6 离子步 | ISIF=3，6 离子步，E₀ = −402.39308967 eV，747.296 Å³，29 μB |
| 缺陷弛豫 | 24/24 收敛 | 24/24 收敛（22–150 离子步，中位数 74） |
| 统一静态 | 25/25 通过协议核对 | 25/25 通过协议核对 |
| 作业号 | 1059427–1059599 段 | 1059634（母体）/ 1061585–1061831 段 |

SCF 振荡的处理阶梯写在 `cu/run_cu_campaign.py`：第 1 次 NELM=100 → 第 2 次 NELM=240 → 第 3 次
NELM=240 + AMIX 0.2 / BMIX 1e−4 / AMIX_MAG 0.8 / BMIX_MAG 1e−4，仍失败则硬停。
最后两个缺陷（`MnTiNi_O-van` 1061830 / `TiMnMn_O-van` 1061831）靠第 3 级配方各跑 66 min 收敛。

## 4. 结果

### 4.1 V 系列（v2）形成能（eV）

| 位点 | O 空位 | N 取代 O | 静态作业号 |
|---|---:|---:|---:|
| VMnTi | 2.403 | 3.100 | 1059427 |
| VNiMn | 2.020 | 3.208 | 1059429 |
| VTiNi | 2.606 | 3.101 | 1059431 |
| FeTiNi | 1.327 | 3.548 | 1059433 |
| MnFeNi | 2.132 | 3.329 | 1059435 |
| MnFeTi | **1.282** | 3.444 | 1059436 |
| MnMnV | 1.972 | 3.128 | 1059599 |
| MnMnFe | 1.306 | 3.853 | 1059439 |
| MnMnMn | 1.463 | 3.432 | 1059440 |
| MnMnNi | 1.474 | 3.314 | 1059442 |
| MnTiNi | 2.636 | 3.656 | 1059444 |
| TiMnMn | 2.683 | 3.741 | 1059446 |

- O 空位：最低 **MnFeTi 1.282**，最高 TiMnMn 2.683，极差 1.401
- N 取代：最低 **VMnTi 3.100**（VTiNi 3.101、MnMnV 3.128 紧随），最高 MnMnFe 3.853，极差仅 0.753

### 4.2 Cu 系列形成能（eV）

| 位点 | O 空位 | N 取代 O | 静态作业号 |
|---|---:|---:|---:|
| CuMnTi | 2.049 | 3.856 | 1061585 |
| CuNiMn | **1.524** | 5.587 | 1061587 |
| CuTiNi | 2.184 | 4.357 | 1061589 |
| FeTiNi | 2.687 | 5.323 | 1061814 |
| MnFeNi | 2.034 | 3.705 | 1061593 |
| MnFeTi | 3.685 | 4.100 | 1061595 |
| MnMnCu | 1.626 | **3.397** | 1061597 |
| MnMnFe | 1.956 | 5.465 | 1061599 |
| MnMnMn | 2.613 | 3.444 | 1061601 |
| MnMnNi | 3.234 | 3.801 | 1061603 |
| MnTiNi | 2.629 | 4.149 | 1061830 |
| TiMnMn | 3.644 | 3.930 | 1061831 |

- O 空位：最低 **CuNiMn 1.524**，最高 MnFeTi 3.685，极差 2.161
- N 取代：最低 **MnMnCu 3.397**，最高 CuNiMn 5.587，极差 2.190

### 4.3 Cu vs V（共同 8 位点）

| 位点 | V O-van | Cu O-van | Δ(O-van) | V N-O | Cu N-O | Δ(N-O) |
|---|---:|---:|---:|---:|---:|---:|
| FeTiNi | 1.327 | 2.687 | **+1.360** | 3.548 | 5.323 | **+1.775** |
| MnFeNi | 2.132 | 2.034 | −0.097 | 3.329 | 3.705 | +0.376 |
| MnFeTi | 1.282 | 3.685 | **+2.403** | 3.444 | 4.100 | +0.657 |
| MnMnFe | 1.306 | 1.956 | +0.650 | 3.853 | 5.465 | +1.612 |
| MnMnMn | 1.463 | 2.613 | +1.150 | 3.432 | 3.444 | +0.012 |
| MnMnNi | 1.474 | 3.234 | +1.760 | 3.314 | 3.801 | +0.488 |
| MnTiNi | 2.636 | 2.629 | −0.007 | 3.656 | 4.149 | +0.493 |
| TiMnMn | 2.683 | 3.644 | +0.962 | 3.741 | 3.930 | +0.189 |
| **平均** | | | **+1.023** | | | **+0.700** |
| **极差** | | | 2.500 | | | 1.764 |

**三条结论**：

1. **Cu 系统性更不利**：O 空位平均 +1.023 eV、N 取代平均 +0.700 eV（N 取代分支 8/8 位点都变差，其中 MnMnMn 的 +0.012 eV 在噪声内；O 空位分支只有 MnFeNi（−0.097）与 MnTiNi（−0.007）持平或略好）。
2. **位点偏好随替代元素翻转**：V 里最稳的 O 空位位点 MnFeTi（1.282）在 Cu 里变成最不稳（3.685，**12/12 倒挂**）；反过来 Cu 里最稳的 CuNiMn（1.524）在 V 体系里没有对应位点。→ **"哪个位点最稳"不能跨替代元素搬用**。
3. **平均值会掩盖掉真正的结论**：Δ 的极差（O 空位 2.500 eV）比平均值（1.023 eV）大一倍以上——只报平均会让人以为"换元素整体抬一点"，实际是**重新排序**。

## 5. 可靠性（读结论时必须一起看）

| 检查 | V 系列 | Cu 系列 |
|---|---|---|
| 静态 vs 弛豫末态：总磁矩差 > 1 μB 的缺陷数 | 13/24 | 17/24 |
| 磁矩跳变幅度 | 最大 6.0 μB | 最大 10.0 μB（集中在整数 μB） |
| 静态 − 弛豫末态能量差 | 0.002–1.460 eV（均值 0.253） | 0.001–1.742 eV（均值 0.444） |
| 逐 OUTCAR 反解 +U | 通过（容差 0.06，VASP 只印一位小数） | 通过 |
| 独立复核 | `verify_defect_energies.py v2` 零偏差 | `verify_cu_defect_energies.py` 零偏差（直读 50 个 OUTCAR） |
| 协议核对 | 以 OUTCAR 为准（回传数据里有 8/24 个目录的 INCAR 写错 ISMEAR） | 同 |

**因此**：形成能的**绝对量级**是可靠的（几十 meV 以内），但**位点之间的细小差距不可信**——
凡结论依赖 < 0.1 eV 的差值，都必须先用静态单点独立复算（账本 #78）。

## 6. 口径与局限

- **+U 逐元素键控**，并从每个 OUTCAR 反解校验（容差 0.06，VASP 在 OUTCAR 里只印一位小数）。
- **磁性基态未验证**：只用单一初始磁矩序列，电子收敛 ≠ 找到磁性全局基态。
- **弛豫为 restart**：若某位点在不同势能面盆地间跳变，本方法发现不了。
- **参考态系统误差**：μO/μN 取原始 PBE-D3 分子能量，未加经验修正；两类缺陷的绝对形成能随之整体平移。
- **未做**：零点能与温压效应、带电缺陷与有限尺寸（Madelung）修正、缺陷间相互作用与浓度依赖、磁构型枚举。
- **单一超胞**：全部结果基于一个 64 原子胞，位点差异属于同一胞内的位点效应。

## 7. 结论（可直接引用）

1. 在同一协议下，用 Cu 替代 V 会**全面抬高缺陷形成能**（O 空位 ~ +1 eV，N 取代 ~ +0.7 eV），
   即 Cu 体系对氧空位与 N 取代**更稳定**（缺陷更难形成）。
2. **位点排序不具可迁移性**：换元素会重排位点稳定性（V 最稳位点在 Cu 里最不稳）。
3. **静态单点是形成能口径的必需步骤**，不是可选优化。
4. **+U 必须逐元素键控并从 OUTCAR 反解校验**（VASP 只印一位小数，容差取 0.06）。

## 8. 复现与归档

```powershell
cd D:\personal_files\pycharm\Ai_model\matcalc-agent\scripts\campaigns\024_CuFeMn_V

# 独立复核（直读 OUTCAR 重算形成能，不碰集群）
..\..\..\.venv\Scripts\python.exe cu\verify_cu_defect_energies.py
..\..\..\.venv\Scripts\python.exe verify_defect_energies.py v2

# 协议审计 / Cu-V 对比
..\..\..\.venv\Scripts\python.exe cu\audit_cu_statics.py
..\..\..\.venv\Scripts\python.exe cu\audit_cu_statics_returned.py
..\..\..\.venv\Scripts\python.exe cu\analyze_cu_vs_v.py
..\..\..\.venv\Scripts\python.exe cu\compare_cu_v.py

# 重新打包（VCALC_CAMPAIGN=v1|v2|cu）
$env:VCALC_CAMPAIGN='cu'; ..\..\..\.venv\Scripts\python.exe package_vasp_data.py

# 重新生成交付清单 + 校验和
..\..\..\.venv\Scripts\python.exe make_delivery_index.py
```

### 交付物（在 `server/outputs/024_CuFeMn_V/package/`，**整个目录拷走即可**）

| 文件 | 内容 | 入 git |
|---|---|---|
| `024_CuFeMn_V_VASP_data.zip` | **V 系列数据包**，48.2 MB / 333 条目 | ❌ |
| `024_CuFeMn_Cu_VASP_data.zip` | **Cu 系列数据包**，88.4 MB / 333 条目 | ❌ |
| `案例总结.md` | 本文的交付副本（跨线汇总，**不在包里**） | ❌ |
| `cu_vs_v/` | Cu 与 V 逐位点对照（跨线数据，**不在包里**） | ❌ |
| `交付清单.md` | 目录结构、校验和、接收方怎么验 | ❌ |
| `SHA256SUMS.txt` | 全部交付文件的 sha256（`sha256sum -c` 可验） | ❌ |

> **每个包只含自己那条线的数据**；跨线的东西一律在交付层，不塞进任何一个包。

**包内结构（两个包同构）**：

```text
<包名>/
├── README.md            包说明：协议、参考能、形成能表、误差提示
├── METHODS.md           完整计算方法书
├── manifest.csv         每个计算目录：文件数 / 物种 / 原子数 / TOTEN / sigma0
├── relax/parent/        母体结构优化（64 原子，ISIF=3）
├── relax/defects/<位点>/<分支>/    24 个缺陷结构优化（ISIF=3）
├── relax/references/    O2_relax、N2_relax（分子参考态）
├── static/defects/<位点>/<分支>/   24 个统一静态单点（NSW=0, IBRION=-1, ISIF=2）
├── static/references/   parent_static、O2_static、N2_static
└── results/                 只放本线能量数据
    ├── formation_energies.csv / .json     形成能（24 行）
    ├── defect_formation_comparison.png/.svg 对比图
    └── O2_reference_results.json / N2_reference_results.json  参考态能量
```

**跨线内容不进任何一个包**，放在交付层：`案例总结.md`（本文的交付副本）与 `cu_vs_v/`
（Cu 与 V 逐位点对照）。

**每个计算目录只保留 6 个文件**：`INCAR` `KPOINTS` `POSCAR` `CONTCAR` `OUTCAR` `XDATCAR`。

| 位置 | 内容 | 入 git |
|---|---|---|
| `scripts/campaigns/024_CuFeMn_V/` | 全部脚本（驱动 / 复核 / 打包 / 对比 / 审计） | ✅ |
| `server/outputs/024_CuFeMn_V/package/` | **交付目录**：两个 zip + 交付清单 + 校验和 | ❌ |
| `server/outputs/024_CuFeMn_V/workflows/` | 两条线的 workflow 状态与算例 | ❌ |
| `server/outputs/024_CuFeMn_V/defect_formation_comparison_v2/` | V 结果（csv/json/png/svg） | ❌ |
| `server/outputs/024_CuFeMn_V/defect_formation_comparison_cu/` | Cu 结果（csv/json/png/svg） | ❌ |
| `server/outputs/024_CuFeMn_V/package/*.zip` | 两个交付数据包 | ❌ |
| `server/outputs/024_CuFeMn_V/cu/` | Cu 线过程记录、Cu-V 对比三件套、只读原始 OUTCAR | ❌ |
| `server/outputs/024_CuFeMn_V/METHODS.md`、`cu/METHODS.md` | 两条线各自的完整方法书 | ❌ |

> ⚠️ 数据目录**不在 git 里**——换机前请整份备份 `server/outputs/024_CuFeMn_V/`（数据 + 结果 + zip）。

## 9. 索引

| 想看 | 去哪 |
|---|---|
| 协议与不变量 | `HANDOFF.md` §7.2 / §7.3 / §7.5 |
| 事故与教训（必读） | `HANDOFF.md` §7.8 |
| 脚本用法与变量 | `scripts/campaigns/024_CuFeMn_V/README.md` |
| V 完整方法书 | `server/outputs/024_CuFeMn_V/METHODS.md` |
| Cu 完整方法书 | `server/outputs/024_CuFeMn_V/cu/METHODS.md` |
| +U 约定的确定记录 | `server/outputs/024_CuFeMn_V/U_CONVENTION_RECOMPUTE.md`（数据目录内，**不随包分发**） |
| 跨项目陷阱与判据 | 第二大脑账本 #65–#91（`orbitos/20_项目/MatCalcAgent/决策与陷阱账本.md`） |
