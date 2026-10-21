# MatCalcAgent 交接文档

> 版本：**2026-10-20 11:30**（Cu 系列收尾；上一提交 `46c749b`，本次提交只改本文）
> 面向：**接手本项目的工程师 / 任意 Agent**。读完本文应能独立跑通离线验收、看懂集群提交链路、接手 024_CuFeMn 这条科研线。
>
> ⚠️ **本文可入库**，因此**不含**集群地址、用户名、密钥路径、内网 IP，也不含 Slurm 分区名/账户名。
> 那些在三个不入 git 的文件里，三者的分工不要混：
>
> | 文件 | 内容 | 是否入库 |
> |---|---|---|
> | `clusters.json` | 机器字段唯一真源（host/port/key 路径/scheduler/queue/vasp_exe…），MCP 直接读它 | ❌ |
> | `CLUSTERS.md` | 人类运维档案：每台机的实测坑、历史事故、别人回传数据的甄别 | ❌ |
> | `adapters/HANDOFF_PRIVATE.md` | 填好的私密交接清单（本次已填），把项目连机器一起交出去 | ❌ |
> | `clusters.example.json` | 脱敏模板，CI / 新机初始化用 | ✅ |

---

## 0. 三分钟摘要

- **是什么**：个人材料计算科研助手。**LLM 只做调度，参数由确定性工具层校验**；交付主体是 MCP Server（`server/`），不是某个聊天壳。
- **能干什么**：VASP / LAMMPS 建模 → 生成输入 → 远程提交（ssh + scp + `sbatch`/`qsub`）→ 解析 OUTCAR/DOSCAR → 出图出表；带 workflow 状态机（`state.json` 是唯一真相）。
- **规模约定**：MCP 工具 **62 个**，由 `tests/test_registry.py` 断言锁定。
- **当前科研线**：`024_CuFeMn`（P2 型 Na 层状氧化物，V 与 Cu 两条替代系列）——
  **V 系列按约定 +U 重算已全部完成并打包；Cu 系列 24 个缺陷同样已完成（弛豫 + 统一静态 + 形成能 + 复核 + 与 V 对比）**。
- **验证状态**：全量 `pytest tests` **307 passed**（2026-10-20）；`scripts/smoke_local.ps1` 报 `SMOKE PASS` / 62 tools。

---

## 1. 项目定位与边界

| 维度 | 说明 |
|---|---|
| 主交付物 | `server/` 下的 MCP Server（stdio）。任意支持 MCP 的宿主（DSH / Claude Code / Cursor / 自建）都能挂 |
| 不做的事 | 不做聊天产品；不做第二套长期记忆；不让模型自由生成 ENCUT / U / K 点 / MAGMOM |
| 数据落位 | 所有产物只写 `server/outputs/<project>/...`（不入 git） |
| 版权红线 | 不分发 VASP 二进制与 POTCAR；`potcars/` 不入 git |

---

## 2. 新机器四步上手

```bat
cd D:\personal_files\pycharm\Ai_model\matcalc-agent
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy clusters.example.json clusters.json        REM 先不填也能跑离线工具
powershell -ExecutionPolicy Bypass -File scripts\smoke_local.ps1   REM 期望 SMOKE PASS + tool_count=62
```

已验证环境：**Python 3.13.5**、**Node v22.19.0**（Node 仅 `dsh-plugin/` 需要）。

---

## 3. 目录与入口

| 项 | 值 |
|---|---|
| 仓库 | `D:\personal_files\pycharm\Ai_model\matcalc-agent` |
| 远程 | `git@github.com:shiswang/matcalc-agent.git`（私有） |
| 分支 | `main`（当前锚点见 §9）；`wip/finish-uncommitted` 仅留历史，**禁止整支合并** |
| Python | `.venv\Scripts\python.exe` |
| MCP 启动 | `scripts\run_mcp.bat`（stdio） |
| 离线验收 | `scripts\smoke_local.ps1`（内部调 `scripts\smoke_local.py`） |
| 集群配置 | `clusters.json`（模板 `clusters.example.json`） |
| 赝势库 | `potcars/potpaw_PBE/<变体>/POTCAR`（343 个变体，不入 git） |
| 科研产物 | `server/outputs/<project>/`（不入 git） |
| 项目知识 | Obsidian Vault `20_项目/MatCalcAgent/`（见 §8） |

### 3.1 outputs 目录治理（2026-10-20 新增）

| 项 | 做法 |
|---|---|
| 落盘入口 | 统一走 `common.out_dir(project, kind)`；`kind` → `structures/ inputs/ dos_pdos/ results/ reports/`，workflow 落 `workflows/<wf_id>/` |
| 写盘重定向 | `MATCALC_OUTPUTS_DIR` 环境变量可整体改写 outputs 根；`tests/conftest.py` 在导入 `server.main` **之前**把它指到临时沙箱，并在会话首尾清空 |
| 输入集归属 | `generate_vasp_inputs(..., project=...)` 写到 `outputs/<project>/inputs/<formula>_<type>_<ts>/`；`project` 缺省仍写 outputs 根（旧行为，仅兼容） |
| 项目登记 | 首次创建项目目录时自动写 `outputs/projects.json`（**索引，不是真相**；`_` 前缀与 `pytest_*` 不登记）。人工查看用 `common.list_projects()` |
| 历史遗留 | 140 个 `<Formula>_<type>_<ts>` 测试目录 → `server/outputs/_archive_test_runs/legacy_20261020/`；另有 5 个「结构 + 未跑完输入」的早期 demo 目录（NaCl / NaCl_case / NaCl_demo / M5_crown / NaMnO2_O3）→ `server/outputs/_archive_legacy_projects/`。**均未删除**；脚本 `scripts/migrate_outputs_registry.py`（支持 `--dry-run`）可重跑 |

顶层目录 **163 → 15**：9 个真实项目（清单见 `outputs/projects.json`）+ `demos/ knowledge/ mp_gallery/ _tools/` 四个功能性目录 + `_archive_test_runs/ _archive_legacy_projects/` 两个归档目录。

> **脚本不许住在 outputs 里**（2026-10-20 血的教训）：`server/outputs/` 被 `.gitignore` 排除，
> 住在里面的脚本 = 没有版本控制 = 换机即丢。024 campaign 的驱动 / 复核 / 打包脚本已迁到
> `scripts/campaigns/024_CuFeMn_V/`（入 git），数据留在 outputs，两者用 `campaign_paths.py` 连接。

---

## 4. 架构

### 4.1 数据流

```text
MCP 宿主（DSH Web / Claude Code / …）
        │ stdio
        ▼
server/main.py            组装点：循环注册各模块 TOOLS（不含实现）
        │
        ├── server/matcalc/*.py   功能模块（薄函数 + TOOLS 清单）
        ├── server/remote.py      ssh/scp 单点（节点白名单 + 诊断日志）
        └── server/outputs/       结构 / 输入 / 结果 / workflow 状态
```

### 4.2 模块表（`server/matcalc/`）

| 模块 | 职责 |
|---|---|
| `structures.py` | 结构生成、超胞/表面/缺陷；**统一出口 `_to_vasp5_poscar()`** |
| `vasp_inputs.py` | INCAR / KPOINTS / POTCAR 拼接与参数校验（+U、IVDW、磁矩） |
| `parsing.py` | OUTCAR / vasprun / DOSCAR / ACF 解析 |
| `plotting.py` | DOS / PDOS / band 出图（图 + Origin 数据 txt） |
| `jobs.py` | 远程提交、`submit_and_watch`、`check_job` |
| `workflows.py` | workflow 状态机（start / advance / status）、路由与恢复摘要 |
| `conversation.py` | 对话层分类：普通聊天 / 新任务 / 继续 / 状态查询 |
| `session_binding.py` | session→workflow 绑定（sidecar，不入 git） |
| `workflow_events.py` | 事件 outbox / inbox / reconciler |
| `materials_project.py` | MP 结构拉取与工作流建议（mp-api） |
| `mp_thermo.py` | 相图 / 反应能 / 界面反应 / Pourbaix |
| `analysis.py` / `analysis_ext.py` | 结构分析、内聚能、对比 |
| `interfaces.py` / `lammps.py` / `neb.py` / `monitor.py` | 界面、LAMMPS、NEB、弛豫监控 |
| `organize.py` | 产物分类与 vacuum（移到 trash，不永久删） |
| `vault_note.py` | 生成 note 候选片段（**不直接写 Vault**） |
| `dsh_bridge.py` | JSON-lines bridge（UTF-8 显式 reconfigure） |

`dsh-plugin/` 是 DSH 的会话连续性插件（控制面门卫，**不是任务编排器**）。

### 4.3 workflow 状态机

- 位置：`server/outputs/<project>/workflows/<wf_id>/state.json`，字段 `revision` 每次落盘 +1。
- 推进：`advance_workflow(wf_id, project, expected_revision=N)`，从 `current` 指针起**级联**推进，遇等待态即停。
- 步骤状态：`pending` / `waiting_submit` / `waiting_run` / `waiting_confirm` / `done`。
- 内置模板：`smoke_local_chain`、`nmo_parent_compare`、`relax_dos_standard`、`mp_relax_static`、`mp_relax_band`、`relax_aimd_short`；
  科研线可自注册（本项目用了 `v2_campaign` / `cu_campaign`，见 §7）。
- **查询/恢复只读**：只有 `advance_workflow` 能写状态。

---

## 5. 不可破坏的不变量

1. **MCP 工具数锁 62**（`tests/test_registry.py` 断言）。加/删工具必须三处同步：模块 `TOOLS`、`server/main.py` 注册循环、registry 测试。
2. **`state.json` 是任务唯一真相**；查询/路由/恢复摘要一律只读，不得自动推进或提交。
3. **MCP 不直接写 Vault**：只产 `outputs/<project>/reports/note_*.md` 候选片段，由 Agent 按门禁归档。
4. **禁止按 mtime 猜任务**：多任务必须显式选择，`wf_id` / project 优先于会话历史。
5. **不新增第二套长期记忆**。
6. **会话与任务分离**：普通聊天零注入，只有明确控制请求才定向召回。
7. **跨层导入**用「相对 → 绝对包路径回退」（兼容 `python server/main.py` 与 `python -m`）。
8. **含中文/Å 的输出先设 `PYTHONIOENCODING=utf-8`**。

---

## 6. 集群与远程提交

> 具体 host / 用户名 / 密钥路径 / 分区名见 `clusters.json` 与 `adapters/HANDOFF_PRIVATE.md`（均不入 git）。本节只讲**选型与坑**。

### 6.1 三台机器一览（按别名）

| 别名 | 调度 | 定位 | 结论 |
|---|---|---|---|
| `master` | Torque | 大内存 AMD 节点，VASP 5.4.4（module）+ 自建 6.6 | 可跑，但**换 6.6 + AVX2/MKL_CBWR**，且内存是硬约束 |
| `hzw` | Torque | 新节点，VASP 6.6（oneAPI） | **不要派 VASP 作业**：批处理下全 rank SIGSEGV，原因未查明 |
| `bkzhang` | **Slurm** | 50 节点 / 3200 核，单分区 | **当前主力**，024 全部作业跑在这台 |

另有一台**不在 `clusters.json` 里**的对方集群：024 的 3 个缺陷弛豫是对方回传的——见 §7.8 的"多机拼数据"教训。

### 6.2 每台的硬约束

**master**

- vasp 5.4.4 + MKL 在 114 原子 / ENCUT 520 上会挂在 `mkl_dft` → 改用 6.6（`vasp6_exe`），并 `export MKL_ENABLE_INSTRUCTIONS=AVX2` / `MKL_CBWR=AUTO`，mpirun 用配套版本（字段见 `clusters.json`）。
- 内存 251 GB 但 **swap 只有 4 GB**：两个常驻 CPMD 作业占 ~120 GB，每个 32 rank VASP 约 25 GB → **同时最多 3~4 个 32 核作业**。超发会疯狂抖动（看起来像卡死）。提交前 `free -g` 看 available。

**hzw**

- `/opt` 的 vasp5.4.4 缺 MKL；6.6 必须先 `source /data/intel/oneapi/setvars.sh`。
- **即使 source 了 oneAPI，同样输入登录节点直跑能过第一个 SCF，`qsub` 提交却 100% 全 rank SIGSEGV**（已排除 conda libstdc++、MKL_CBWR、FABRICS、HYDRA_BOOTSTRAP、PIN、ppn=32/96）。结论：**不要往 hzw 派 VASP**，除非先跑通最小批处理算例。

**bkzhang**（重点）

- `sbatch job.pbs`（不是 `qsub`）；分区/账户见 `clusters.json`，节点 comput5–50。
- **必须显式把 `$HOME/.conda/envs/casm/lib` 加进 `LD_LIBRARY_PATH`**：系统 `/lib64/libstdc++.so.6` 缺 `GLIBCXX_3.4.21`，否则一进 DFT+U 的 `SETDIJ` 就全 rank SIGSEGV。
- **指定 `-n` 后必须同时给 `--mem`**：Slurm 会按节点内存推导 MinMemoryCPU(≈3862M)，32 核要 ~123 GB，作业永远 PENDING 且原因只显示 Priority。实测 32 rank 用 23.6 GB、16 rank 用 16–24 GB。
- 提交前看空闲核：`sinfo -p <分区名> -N -o '%N %t %C'`；分区常被占满，槽不够就一直排队（024 的 16 核 `--mem=16G` 是这么定出来的）。
- **时钟比本地慢约 4 分钟**：scp 上传的 tar 解包必须 `tar -xzmf`（`-m` 忽略 mtime），否则被判"未来时间戳"而中断。
- **不要在远端上传 POTCAR**：远端赝势库已有 346 个变体，`cat` 拼接即可（上传 80 MB 曾触发 home 配额截断）。

### 6.3 通用提交纪律

1. 文本文件本地写好（UTF-8 / LF）→ `scp` → 远端 `dos2unix` 兜底。
2. **POTCAR 段序 = POSCAR 物种序**，`LDAUL/LDAUU/LDAUJ` 长度必须等于物种数。
3. **提交后 30 秒四查**：① 实际核数（vasp.out 的 `running N mpi-ranks`）；
   ② `LDAUL` 长度与取值；③ POTCAR `TITEL` 段序；④ 队列里的 ppn/mem。
4. 多核必须 `mpirun -np $N`（PBS 再带 `-machinefile $PBS_NODEFILE`）；裸 `vasp_std` 只会单核。
5. 覆盖式操作（`cp` / `tar` / `scp`）前先确认目标路径；下载别用管道截断（会拿到半个文件）。

### 6.4 作业脚本模板（Slurm）

```bash
#!/bin/bash
#SBATCH -J <name>
#SBATCH -p <分区名>          # 真实值见 clusters.json
#SBATCH -A <账户名>
#SBATCH -N 1
#SBATCH -n 16
#SBATCH --mem=24G
#SBATCH --time=48:00:00
#SBATCH -o scheduler-%j.out
#SBATCH -e scheduler-%j.err
set -eo pipefail
cd "$SLURM_SUBMIT_DIR"
module load compiler/intel/2021.3.0
module load mpi/intelmpi/2021.3.0
export LD_LIBRARY_PATH=$MKLROOT/lib/intel64:$I_MPI_ROOT/lib/release:$I_MPI_ROOT/lib:$HOME/.conda/envs/casm/lib:$LD_LIBRARY_PATH
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
mpirun -np "$SLURM_NTASKS" <vasp_exe> > vasp.out 2>&1
```

---

## 7. 科研线：024_CuFeMn（V / Cu 缺陷形成能）

> **结论汇总在 `docs/024_CuFeMn_案例总结.md`**（一页速览 / 协议 / 两条线结果表 / Cu-V 对比 /
> 可靠性 / 旧 Cu 项目的坑 / 复现命令与归档位置）。本节是工程细节与不变量。

### 7.1 科学问题与模型

P2 型 Na 层状氧化物超胞 **Na₁₀Ti₂Mn₁₀Fe₁X₁Ni₄O₃₆**（X = V 或 Cu，64 原子）。
研究**同一位点的两种缺陷**，每个位点两个分支：

- **O 空位（O-van）**：删 O → 63 原子；
- **N 取代 O（N-O）**：O 换 N → 64 原子。

12 个位点 × 2 分支 = **24 个缺陷结构 / 系列**。位点标签 = 该 O 周围 3 个过渡金属（如 `MnFeTi`），
覆盖 4 个 O 层，到 V/Cu 的距离约 1.9–6.4 Å。V 与 Cu 两条线**各有 12 个位点，其中 8 个重合**
（FeTiNi、MnFeNi、MnFeTi、MnMnFe、MnMnMn、MnMnNi、MnTiNi、TiMnMn），因此可直接横向比较。

### 7.2 约定 +U（这条一定要守）

元素键控（**不是**按 POSCAR 顺序），Dudarev `LDAUTYPE=2`、`LDAUJ=0`：

| 元素 | Ti | Mn | Fe | Ni | V | Cu | Na / N / O |
|---|---|---|---|---|---|---|---|
| `LDAUU` | 5.2 | 3.9 | 4.0 | 6.2 | 3.25 | 1.9 | 0（`LDAUL=-1`） |

> **历史事故**：第一轮（v1）把 Mn/Fe/Ni 的 U 映射错了（Mn 6.2 / Fe 3.9 / Ni 4.0），导致整批 V 数据作废、
> 最稳位点结论完全反转。证据链与数据状态表见 `024_CuFeMn_V/U_CONVENTION_RECOMPUTE.md`。
> 因此**任何新算例都必须从自己的 OUTCAR 里反解 U 并逐元素比对**，容差 0.06（VASP 在 OUTCAR 里把 `LDAUU` 只印一位小数，3.25 会印成 3.2）。

### 7.3 参数表（弛豫与静态共用电子结构部分）

| 项目 | 设置 |
|---|---|
| 程序 | VASP 6.6.0（PAW，PBE） |
| 赝势 | 全 `_pv`：`Na_pv Ti_pv Mn_pv Fe_pv V_pv/Cu_pv Ni_pv [N] O` |
| ENCUT / PREC | 520 eV / Accurate |
| ISPIN | 2 |
| EDIFF / NELM | 1E-5 / 100（不收敛时 240，见 §7.8） |
| IVDW | 11（DFT-D3） |
| k 点 | Γ 中心 5×5×1 → **13 个不可约 k 点**，`ISMEAR=-5`（四面体），`SIGMA=0.05` |
| 其他 | `LREAL=.FALSE.` `LASPH=.FALSE.` `LMAXMIX=4` `LORBIT=11` `NCORE=4` `ISYM=2` |
| 弛豫 | `NSW=200` `IBRION=2` `ISIF=3` `EDIFFG=-0.02` `POTIM=0.5` |
| 静态 | `NSW=0` `IBRION=-1` `ISIF=2` `ISTART=0` `ICHARG=2` `LWAVE=LCHARG=.FALSE.` |

**为什么静态单点不能省**：同一缺陷的"弛豫末态能量"与"重新起算的静态能量"实测可差 **0.002–1.460 eV（平均 0.253）**，
因为静态 `ISTART=0/ICHARG=2` 从零起算可能落到不同电子/磁态。**所有能量比较一律用统一静态。**

### 7.4 形成能口径与参考态

```
Ef(O 空位)   = E(O35)   − E(parent) + ½E(O2)
Ef(N 取代 O) = E(N1O35) − E(parent) + ½E(O2) − ½E(N2)
```

- 中性缺陷、氧富（N 富）、以分子为参考；总能取该次**静态末态**的 `energy(sigma->0)`。
- **不含**零点能、温度/压力修正，也**未加**经验分子校正。
- 参考态（V/Cu 两系列共用，`LDAU=.FALSE.` 因而不受 U 影响）：
  `E(O₂)=−9.85924862`、`E(N₂)=−16.63493877`、`μO=−4.92962431`、`μN=−8.31746939` eV。

### 7.5 V 系列（v2，**已完成**）

- 工作流 `024_CuFeMn_V/workflows/v2_u_convention_20261016/`，5/5 步 `done`（rev 221）。
- 母体弛豫 job 1059130（32 核，20 离子步，E₀=−411.34760592 eV）；**母体静态 −410.77517624 eV**（与弛豫末态差 0.572 eV）。
- 形成能（eV）：O 空位最低 **MnFeTi 1.282**（MnMnFe 1.306、FeTiNi 1.327），最高 TiMnMn 2.683；
  N 取代最低 **VMnTi 3.100**（VTiNi 3.101、MnMnV 3.128），最高 MnMnFe 3.853。
- 与 v1 相比**最稳位点全部改变**（O-vac FeTiNi→MnFeTi；N-O MnFeNi→VMnTi）→ v1 位点偏好结论不可沿用。
- 24 个缺陷中 **13 个**静态与弛豫落在不同磁态（`moment_shift_uB` 逐项标注）。
- 独立复核 `verify_defect_energies.py v2`：直读 50 个 OUTCAR，24 个形成能与 CSV **零偏差**。
- 产物：`defect_formation_comparison_v2/`（csv/json/png/svg）、`METHODS.md`、`README.md`、
  `package/024_CuFeMn_V_VASP_data.zip`（48.2 MB，54 算例 × 6 文件，**不含 POTCAR**）。

### 7.6 Cu 系列（**已完成**，2026-10-20）

- 工作流 `024_CuFeMn_V/workflows/cu_u_convention_20261017/`（脚本在 `024_CuFeMn_V/cu/`），5/5 步 `done`，rev 189。
- 母体弛豫 job 1059634（6 离子步，E₀=−402.39308967 eV，V=747.296 Å³，29 μB）；**母体静态 −402.41000035 eV**（与弛豫末态只差 −0.017 eV）。
- 24/24 缺陷弛豫收敛（22–150 离子步，中位数 74）；25/25 静态通过协议核对。
  最后两个（`MnTiNi_O-van` 1061830 / `TiMnMn_O-van` 1061831）用第 3 级配方（NELM=240 + 混合）各跑 66 min 收敛，
  `rms(c)` 逐步步降、无反弹——**这是"第 3 级配方真的有效"的反面证据：默认混合下 rms(c) 卡死两小时不动**。
- **形成能（eV）**：O 空位最低 **CuNiMn 1.524**（MnMnCu 1.626、MnMnFe 1.956），最高 MnFeTi 3.685，极差 2.161；
  N 取代最低 **MnMnCu 3.397**（MnMnMn 3.444、MnFeNi 3.705），最高 CuNiMn 5.587，极差 2.190。
- **与 V 的对比（8 个共同位点）**：Cu 相对 V，O 空位平均 **+1.023 eV**、N 取代平均 **+0.700 eV**（Cu 系统性更不利）。
  **位点偏好强烈依赖替代元素**：V 的 O 空位最稳位点 MnFeTi（1.282）在 Cu 里是最不稳（3.685，12/12）。
- **磁态**：17/24 个缺陷静态与弛豫的总磁矩差 > 1 μB（集中在整数 μB），静态与弛豫末态能量差 0.001–1.742 eV
  （平均 0.444）→ **< 0.1 eV 的位点排序不可信**。
- 独立复核 `verify_cu_defect_energies.py`：直读 50 个 OUTCAR，24 个形成能**零偏差**。`compare_cu_v.py` 输出 `cu_vs_v_comparison.csv`。
- **数据包已出**：`package/024_CuFeMn_Cu_VASP_data.zip`（88.4 MB / 349 条目，每个计算目录只留 6 个文件；
  manifest.csv 带物种/原子数/能量，README 用 Cu 约定与 Cu 位点表；`results/` 内含
  `formation_energies.json|csv`、Cu–V 对比三件套、`cu_results_audit.json`、**案例总结副本**与 **7 个复核脚本**）。
  V 包同结构重建（48.2 MB / 341 条目，`results/scripts/` 2 个）。交付清单与 sha256：`package/交付清单.md`、`package/SHA256SUMS.txt`。
  打包命令：`VCALC_CAMPAIGN=cu python package_vasp_data.py`；清单：`python make_delivery_index.py`。
- 与旧 Cu 项目的本质差别：**旧项目 24 个缺陷只做过静态、从未弛豫，且没留 INCAR**；本批以旧静态几何为起点**从零弛豫**，
  旧项目还混用了 `Fe_sv` 与 `_pv` 赝势，本批统一为全 `_pv`。

### 7.7 目录与脚本地图

```text
scripts/campaigns/024_CuFeMn_V/      # 代码（2026-10-20 从 outputs/ 迁出，已入 git）
├── README.md                        # 布局 / 变量 / 命令
├── campaign_paths.py                # 唯一定义"数据在哪"（DATA_ROOT / CU_DATA / REPO）
├── run_bk_unified.py                # 共享 helper（ROOT/CFG/SSH/SCP/moments）
├── run_v2_campaign.py               # V 驱动
├── monitor_v2_campaign.py           # V 轮询
├── verify_defect_energies.py        # V 独立复核（v1|v2）
├── package_vasp_data.py             # 打包（VCALC_CAMPAIGN=v1|v2|cu）
├── check_packaging_channels.py      # 三条打包通道的回归检查
├── compare_v1_v2.py
└── cu/                              # Cu 线代码
    ├── run_cu_campaign.py           # Cu 驱动（import run_v2_campaign 复用 helper）
    ├── monitor_cu_campaign.py       # 轮询（interval / max_iter / gate）
    ├── audit_cu_statics.py          # 提交前本地 INCAR 协议审计
    ├── audit_cu_statics_returned.py # 回收后四查：核数/段序/U/k 点
    ├── verify_cu_defect_energies.py # 独立复核（直读 OUTCAR）
    ├── compare_cu_v.py              # Cu vs V 共同 8 位点对比
    ├── analyze_cu_vs_v.py           # Cu 能量表与相对排名
    ├── site_table.py                # 12 位点表
    ├── compare_u_assignment.py / audit_cu_results.py

server/outputs/024_CuFeMn_V/          # 数据与结果（不入 git）
├── workflows/
│   ├── v2_u_convention_20261016/     # V 系列（done）
│   ├── cu_u_convention_20261017/     # Cu 系列（done）
│   ├── oxygen_formation_refs_20261015/   # O2 参考态
│   └── nitrogen_formation_ref_20261015/  # N2 参考态
├── defect_formation_comparison_v2/   # V 结果（csv/json/png/svg）
├── defect_formation_comparison_cu/   # Cu 结果（csv/json/png/svg）
├── package/                            # **交付目录：整个目录拷走即可**
│   ├── 024_CuFeMn_V_VASP_data.zip     # V 系列数据包（48.2 MB / 333 条目，只含 V 自己的数据）
│   ├── 024_CuFeMn_Cu_VASP_data.zip   # Cu 系列数据包（88.4 MB / 333 条目，只含 Cu 自己的数据）
│   ├── 案例总结.md                    # 跨线汇总（两线协议/逐位点表/对照/可靠性）——不在包里
│   ├── cu_vs_v/                       # 跨线逐位点对照（Cu vs V）——不在包里
│   ├── 交付清单.md                    # 目录结构、校验和、接收方怎么验
│   └── SHA256SUMS.txt                 # 全部交付文件的 sha256
├── METHODS.md / README.md / U_CONVENTION_RECOMPUTE.md
├── cu/                               # Cu 线的过程记录与旧项目原始输入
│   ├── cu_original/                  # 旧 Cu 项目的 OUTCAR（只读原始输入）
│   ├── METHODS.md                    # §6 结果已填
│   ├── cu_vs_v_comparison.csv / cu_vs_v_relative.csv / cu_vs_v.json
│   └── _archive_20261020/            # 一次性脚本与日志（只归档，不删除）
└── （v1 时代的一次性脚本 21 个仍留在此目录，**故意不入 git**，清单见 scripts/campaigns/024_CuFeMn_V/README.md）
```

每个算例在本地 `workflows/<wf>/00_*/<stage>/collected/<name>/` 与远端 `$HOME/matcalc/<project>/<wf>/<stage>/<name>/` 一一对应。

> **代码与数据分开**（2026-10-20 定）：脚本在 `scripts/campaigns/024_CuFeMn_V/`（入 git），
> 数据在 `server/outputs/024_CuFeMn_V/`（不入 git）。脚本一律通过 `campaign_paths.py` 取数据根目录，
> **不要把 `__file__` 的父目录当数据目录**——那正是当初脚本随磁盘一起消失的原因。

### 7.8 事故与教训（必读）

1. **U 映射按错了键**（v1）→ 整批作废重算。教训：U 必须**元素键控**，且从 OUTCAR 反解校验。
2. **`LDAUU` 只印一位小数** → 1e-9 比对永远失败，改用容差 0.06。
3. **INCAR 不可信**：回传数据里有 8/24 个目录 INCAR 写 `ISMEAR=-5` 而 OUTCAR 实际是 `1` → **协议核对以 OUTCAR 为准**。
4. **"返回的数据"可能是多台机器拼的**：看调度日志头部的 host / submit dir / cores。
5. **静态处理器重复提交 bug**（本项目已修）：`todo = [n for n in items if n not in submitted]` 而 `submitted` 当时是 `(name, job_id)` **列表**，
   判断恒为真 → 每次进入都把**全部目录重新 sbatch**，同一远端目录里出现两个 VASP 同时写。
   修法：`_read_submission()` 返回 **dict**，远端 `submitted.tsv` 去重成唯一一批，旧批次全部 `scancel` 并清理。
   → **接手后改动增量提交逻辑时，先确认"已提交集合"是 dict 还是 list 的语义**。
6. **SCF 不收敛的三级阶梯**（写在 `run_cu_campaign.py`）：第 1 次 `NELM=100`；第 2 次 `NELM=240`；
   第 3 次 `NELM=240 + AMIX=0.2 / BMIX=1e-4 / AMIX_MAG=0.8 / BMIX_MAG=1e-4`（纯 SCF 算法参数，不改泛函/k 点/展宽）。
   仍失败则硬停报错，不无限重投。63 原子 O 空位（奇数电子）最容易振荡，`rms(c)` 可冲到 2.0。
7. **失败日志必须归档而非删除**：早期重投会清空目录，导致 `MnMnMn_N-O` 连续两次 Slurm FAILED（68 min / 55 min，两台不同节点）
   却查不到原因。现改为移到远端 `prev/`。
8. **清目录时注意作业是否在跑**：本次曾把两个正在 RUNNING 的作业的输出文件删掉（已 unlink），只能取消重投。
9. **重启 monitor 前先杀旧进程**：`advance_workflow` 会级联推进，旧进程用旧代码继续跑会做出与当前代码不一致的动作。
10. **跨驱动复用 helper 时别改别人的模块级常量**（2026-10-20 已修）：`cu/run_cu_campaign.py` 曾写 `v2.CONVENTION = CONVENTION`
    想"把 v2 的 helper 指向 Cu 的约定"。两个驱动在同一进程共享模块，这一行把 v2 的 V 3.25 覆盖成 Cu 1.9，
    v2 再生成 V 体系直接 `KeyError: 'V'`。修法：**各自定义常量**，只复用无状态函数；
    并在 import 时加断言（`assert v2.CONVENTION['V'] == 3.25 and 'Cu' not in v2.CONVENTION`）做哨兵。
    → **判断依据：`v2.<常量>` 在 v2 里被读的位置，是否真的被 Cu 调用过**（本例中 3 个常量全无读取点，属纯污染）。
11. **重构搬家后，未定义名要靠工具查而不是靠想**（2026-10-20 接入 ruff 抓到的）：把 outputs 常量搬进
    `server/matcalc/common.py` 时，`parsing.py` / `plotting.py` 里"相对路径 → 去 outputs 根找"的调用点没跟着改，
    `_OUTPUTS_DIR` 在这两个模块**根本不存在** → 走到那条分支就 `NameError`（`analyze_vasprun` / `parse_bader_acf` /
    `plot_band` / `plot_pdos` 四条路径）。pyflakes 的 **F821** 一秒定位；`tests/test_outputs_path_fallback.py` 已把它钉住
    （红/绿都验过）。→ **搬常量/改模块边界后，用静态检查过一遍，别靠"应该没漏"**。
12. **两驱动的"重复"没有想象的大**（2026-10-20 实测修正）：初判"15/16 同名函数、298 行逐字相同"是按**行级 diff**
    算的（相似度 34%），容易高估。改用 **AST 归一化逐函数比较**后：15 个同名函数里**只有 2 个真正逐字相同**
    （`_assert_incar_stage`、`handle`），其余 13 个已按各自体系的约定/路径改写。
    → 结论：**"抽公共模块"的收益比估计小、风险比估计大**（这些是提交集群作业、又无法离线验证的代码），
    改为把同构关系显式钉住：`tests/test_campaign_driver_parity.py`（共享函数名不许消失、协议级函数必须保持一致、
    两套 +U 约定必须覆盖同一批元素）。→ **判断重复度要用 AST，不要用行级 diff**。

---

## 8. 第二大脑（Obsidian Vault）

### 8.1 契约（代码层面，必须守）

- **MCP 不直接写 Vault**：`server/matcalc/vault_note.py` 只生成候选片段到 `server/outputs/<project>/reports/note_*.md`，
  由 Agent 按门禁归档进 Vault。
- **不新增第二套长期记忆**：知识沉淀只走 Vault，不在仓库里另建笔记目录。
- 项目进度/决策的正式位置：Vault `20_项目/MatCalcAgent/`
  - `决策与陷阱账本.md`：非显而易见的坑与决策（编号条目，`[已验证]` / `[候选]`）
  - `MatCalcAgent交接.md`：§1 真相源路由、§2 DSH 接入、§3 Vault 写回约定、§5 下一步
  - `MatCalcAgent.md`：项目目标与里程碑

### 8.2 位置与结构（2026-10-20 实测）

早期交接在 `D:\personal_files\Obsidianfile\`、`D:\personal_files\obsidianopt\` 只找到空壳，误判为"本机没有 Vault"。
真实路径记录在 `%APPDATA%\obsidian\obsidian.json`：

```text
D:\personal_files\pycharm\Ai_model\orbitos          ← 主 Vault（唯一记忆系统）
└── 20_项目\MatCalcAgent\
    ├── MatCalcAgent.md            # 项目目标 / 里程碑 / 阶段结论
    ├── MatCalcAgent交接.md        # Vault 独有部分：DSH 接入、写回约定、真相源路由
    ├── 决策与陷阱账本.md          # 编号条目，[已验证] / [候选]
    ├── M5架构设计_v1.md
    └── NaCl_材料计算案例.md
```

交接页自己写明"工程事实的真相在仓库，不在本文"——**工程细节只改仓库 `HANDOFF.md`，不要在 Vault 再写一份**。

### 8.3 写回门禁

**规则唯一真源：Vault 根目录的 `AGENTS.md`**（状态链 `candidate → provisional → active`、五道门、检索纪律都在那里）。
本文**不复述**这些规则——副本一定会过期，而读副本的人不会知道自己读的是副本。

只记一条与 MCP 边界直接相关的：

> **MCP 只产 candidate 片段**（`outputs/<project>/reports/note_*.md`），**不写 Vault、不晋升、不检索**。

---

## 9. 当前状态与待办（2026-10-20 11:00）

| 项 | 状态 |
|---|---|
| Git | `main @ 9fc150b`（CI 依赖修复）；本次提交 `HANDOFF.md` |
| 工具数 | 62（`tests/test_registry.py` 通过） |
| 全量回归 | `pytest tests` **307 passed / 1 skipped**（写盘已重定向到临时沙箱，`server/outputs/` 不再被测试污染） |
| 冒烟 | `smoke_local.ps1` PASS / 62 tools（重定向输出须 UTF-8，否则报 UnicodeEncodeError 假失败） |
| CI | ✅ 2026-10-20 恢复绿色（此前 2026-08-30 之后 **36 次连续红**，根因 `requirements.txt` 缺 `mcp<2`，见 §11 依赖红线） |
| V 系列 | ✅ 完成（statics 25/25、形成能 24 行、METHODS/README/zip 齐） |
| Cu 系列 | ✅ 完成（静态 25/25、形成能 24 行、复核零偏差、与 V 对比已出、**zip 已出** 84.3 MB） |
| 集群队列 | 本项目作业已全部收；**剩 1 个非本项目作业** `DVoBstatic`(1061378, comput41, 32 核) |
| 文档 | `024_CuFeMn_V/cu/METHODS.md` §6 已填（结果 / Cu-V 对比 / 磁态诊断 / 产物） |
| 清理 | 一次性脚本与日志已移入 `cu/_archive_20261020/`（未删除） |
| 第二大脑 | Vault 已定位（§8.2），账本补了 024 条目（#65–#68） |
| 目录治理 | outputs 顶层 **163 → 15**（140 个测试遗留 + 5 个早期 demo 目录归档，未删除）；`outputs/projects.json` 登记 9 个真实项目；Cu 线脚本并入 `024_CuFeMn_V/cu/`（见 §3.1、§7.7） |
| campaign 脚本入 git | ✅ 2026-10-20：`scripts/campaigns/024_CuFeMn_V/`（**代码入 git、数据留在 outputs**）。迁移后 9 个可离线脚本输出**逐字节一致**、Cu 包重建的 manifest/README 与旧包相同；v1 时代 21 个一次性脚本仍留 outputs（故意不入 git，清单见该目录 README） |

**接手后第一优先**：

1. ✅ Cu 系列已收尾（`energies` → `METHODS.md` §6 → `verify_cu_defect_energies.py` → `compare_cu_v.py` 全部完成）。
2. ✅ Cu 系列打包已完成（`package_vasp_data.py` 现支持 `VCALC_CAMPAIGN=v1|v2|cu`；
   顺带修掉 manifest 的 species/atoms 空列与 README 目录计数，三条通道用 `check_packaging_channels.py` 回归）。
3. 待定：`DVoBstatic`(1061378) 不属于本项目，需与作业所有者确认是否该收。
4. ✅ 已清理一次性脚本与日志（移入 `cu/_archive_20261020/`，未删除）。

---

## 10. 高频陷阱

| 症状 | 原因 / 处理 |
|---|---|
| 改完 MCP 代码不生效 | 服务端不热载，需杀进程；可能有多对新旧进程 |
| ssh/scp 报错 | 用绝对路径 `C:\Windows\System32\OpenSSH\ssh.exe` + `ssh -n` |
| POSCAR 物种行错位 | pymatgen `Poscar.get_str()` 的老问题 → 统一 `_to_vasp5_poscar()` |
| pytest 报 Temp ACL 拒绝 | 固定 `--basetemp=.pytest_tmp_xxx` |
| VASP 单核跑 | 漏了 `mpirun -np`（PBS 还要 `-machinefile $PBS_NODEFILE`） |
| `SETDIJ` 段 SIGSEGV | 系统 libstdc++ 太旧 → 换节点或补 `LD_LIBRARY_PATH` |
| 作业永远 PENDING（原因只写 Priority） | Slurm 的 MinMemoryCPU 推导 → 必须显式 `--mem`；或分区无足够空闲核 |
| tar 解包只出一半 | 远端时钟慢 ~4 min → `tar -xzmf` |
| 上传 POTCAR 触发配额 | 不要传，远端 `cat` 拼接 |
| OUTCAR 里没有 `running on N total cores` | v6.6 只在 `vasp.out` 印 `running N mpi-ranks` → 核数从 vasp.out 查 |
| `NKPTS` 正则抓不到 | 行首是 `k-points NKPTS = 13`，不是 `NKPTS =` 开头 |
| 形成能取错能量 | OUTCAR 有两套能量；取 `energy(sigma->0)` / `FREE ENERGIE TOTEN` |
| 中文乱码 | 先 `$env:PYTHONIOENCODING='utf-8'` |
| `.gitignore` 非纯 UTF-8 | 不要整文件重写编码，按字节定位插入 |
| PowerShell 里 `python -c` 带 `$`/引号 | 一律改写成小 `.py` 文件再执行（本会话踩了多次） |

---

## 11. 验证与提交

```powershell
cd D:\personal_files\pycharm\Ai_model\matcalc-agent

# 全量离线回归（固定 basetemp，避开系统 Temp ACL）
.venv\Scripts\python.exe -m pytest tests -q --basetemp=.pytest_tmp_handoff

# 快速回路（跳过两个 ZSL 界面慢用例，约 22 s；改完代码先跑这个）
.venv\Scripts\python.exe -m pytest tests -q -m "not slow" --basetemp=.pytest_tmp_handoff

# 只验工具数契约
.venv\Scripts\python.exe -m pytest tests/test_registry.py -q --basetemp=.pytest_tmp_handoff

# Node 插件测试（改了 dsh-plugin 才需要）
node --test tests/test_dsh_plugin.mjs

# 离线冒烟（期望 SMOKE PASS + 62 tools）
powershell -ExecutionPolicy Bypass -File scripts\smoke_local.ps1

# 静态检查（ruff：E9 语法错 + pyflakes；首次接入时它抓到了 3 个真 NameError）
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m ruff check .

# 024 campaign 脚本的离线复核（不碰集群；改了 scripts/campaigns/ 就要跑）
cd scripts\campaigns\024_CuFeMn_V
..\..\..\.venv\Scripts\python.exe cu\verify_cu_defect_energies.py
..\..\..\.venv\Scripts\python.exe verify_defect_energies.py v2
..\..\..\.venv\Scripts\python.exe check_packaging_channels.py v2   # 导临时目录，不覆盖已交付 zip

# Git 卫生
git status --short; git diff --check
```

**提交前**：测试全绿 · 工具数 62 · 未提交 `outputs/`、`.venv/`、`potcars/`、`clusters.json`、`node_modules/` · 无凭据。

> 2026-10-20 复测：全量 `pytest tests` **307 passed / 1 skipped**（76 s，`--basetemp=.pytest_tmp`）；
> `smoke_local.ps1` `SMOKE PASS` / `tool_count=62`；工作树干净。
>
> **依赖红线**：`requirements.txt` 固定 `mcp>=1.29,<2`。代码用 `mcp.server.fastmcp.FastMCP`，
> 2.x 已改名 `MCPServer`，升级会让 server 与 CI 同时起不来（2026-09 起 CI 连续 36 次红就是这个原因）。
> 注意 `scripts/smoke_local.ps1` 已固定 `PYTHONIOENCODING=utf-8`——输出重定向到文件时若不设，
> Python 会退回 GBK，遇到 `Å` 直接抛 `UnicodeEncodeError`，表现为"验收假失败"。

---

## 12. 多 Agent 协作

**同一文件同一时刻只有一个主写 Agent。**

| 角色 | 职责 | 可写范围 |
|---|---|---|
| 总装 Agent | 拆需求、审查、验收、合并 | 全部 |
| 开发 Agent | 功能开发、测试、第二意见 | 自己的分支 / worktree |

- 共享文件（`server/main.py`、`tests/test_registry.py`、`README.md`、`AGENTS.md`）只由总装者写。
- 并行开发用独立 worktree：`git worktree add ../matcalc-agent-<name> -b <name>/<feature>`。
- 结束前：跑 §11 → 更新 Vault 交接页与账本 → 再提交。

---

## 13. 接手清单

**30 分钟**

- [ ] 建 venv、装依赖、跑 `smoke_local.ps1`（期望 62 tools）
- [ ] 跑 `pytest tests -q --basetemp=.pytest_tmp_handoff`，确认与 §11 一致的基线
- [ ] 读 §5 不变量 + §10 陷阱表

**半天**

- [ ] 从 `adapters/HANDOFF_PRIVATE.md` 填好本机 `clusters.json`（或直接向原作者要 `clusters.json`）
- [ ] 用 `check_connection('<别名>')` 验证连通；`sinfo -p <分区名> -N -o '%N %t %C'` 看空闲核
- [ ] 挑一个已完成算例，从 `state.json` → `_collect_one` → `OUTCAR` 走一遍，理解"状态—远端目录—本地 collected"的对应
- [ ] 跑 `verify_defect_energies.py v2`，确认自己在本地能复现 V 的 24 个数字

**一周**

- [x] 收尾 Cu 系列（§9 第一优先）
- [ ] 决定是否把 `statics` 的增量提交逻辑抽成 `run_v2_campaign.py` 的公共函数（当前两份驱动各一份，是 bug 温床）
- [x] 把 Cu 线一次性脚本归档（`cu/_archive_20261020/`）
- [x] 补 Vault 索引（§8.2 路径已定位，§8.3 门禁已写入）

---

## 附：相关文档

| 内容 | 位置 |
|---|---|
| 使用说明 / 接入 | `README.md`、`MCP.md`（本次已把两处过期的"61 个工具"改为 62） |
| Agent 硬规则 | `AGENTS.md` |
| 集群运维档案（不入 git） | `CLUSTERS.md` |
| 私密交接清单（不入 git） | `adapters/HANDOFF_PRIVATE.md` |
| 宿主配置样例 | `adapters/claude-code/`、`adapters/cursor/` |
| V 系列方法 | `server/outputs/024_CuFeMn_V/METHODS.md` |
| U 约定事故链 | `server/outputs/024_CuFeMn_V/U_CONVENTION_RECOMPUTE.md` |
| Cu 系列方法（§6 已填） | `server/outputs/024_CuFeMn_V/cu/METHODS.md` |
