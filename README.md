# MatCalcAgent — 材料计算科研助手（工程代码）

基于 MCP 的确定性材料计算工具层（pymatgen / ASE / VASP），**不绑定特定智能体**。

## English summary

MatCalcAgent is an agent-agnostic [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server for computational materials science. It exposes **63 deterministic tools** covering structure building (pymatgen / ASE), VASP input generation and validation, HPC job submission and monitoring, output parsing, property workflows (DOS, bands, EOS, Bader, optics, interfaces, NEB, XRD) and Materials Project thermodynamics. Any MCP client — Codex, Claude Code, Cursor or a custom agent — can use it.

The design goal is **reproducible science with LLMs**: the model orchestrates but never free-generates physical parameters; VASP inputs are validated, placeholder structures are blocked from cluster submission, failures use structured `E_*` error codes, and workflow state is idempotent and persisted on disk. The repository contains ~17k lines of Python, a 333-case offline regression suite and GitHub Actions CI. Tool contracts: [`MCP.md`](MCP.md); agent-facing rules: [`AGENTS.md`](AGENTS.md). Released under the [MIT License](LICENSE); VASP binaries, POTCAR pseudopotentials and cluster credentials are not distributed.

中文文档见下文。

---

| 你是谁 | 先看 |
|--------|------|
| 任意支持 MCP 的 Agent（Claude Code / Cursor / 自建…） | 本文「四步上手」+ [`MCP.md`](MCP.md) |
| Claude Code / Cursor 配置片段 | [`adapters/`](adapters/) |
| 编码/协作 Agent | [`AGENTS.md`](AGENTS.md)（路径禁区、工具契约、自检） |
| 使用 DSH 会话隔离 | 本文后半「独立 MatCalcAgent Web」（可选） |
| 私密集群/密钥交接 | [`adapters/HANDOFF_PRIVATE.template.md`](adapters/HANDOFF_PRIVATE.template.md)（填好勿提交） |
| 项目知识与进度 | Obsidian Vault `20_项目/MatCalcAgent/`（工程仓库外） |
| 想看一个完整科研案例 | [`docs/024_CuFeMn_案例总结.md`](docs/024_CuFeMn_案例总结.md)（024_CuFeMn V/Cu 两条线：协议 · 结果 · Cu-V 对比 · 可靠性） |


---

## 四步上手（新机器）

```bat
REM 1) 依赖
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

REM 2) 集群配置（可先不填，离线工具仍可用）
copy clusters.example.json clusters.json

REM 3) 离线验收（不连集群、不装 DSH）
powershell -ExecutionPolicy Bypass -File scripts\smoke_local.ps1
REM   期望：SMOKE PASS 且 tool_count=63

REM 3b) 静态检查（可选；CI 里会跑）
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m ruff check .

REM 3c) 快速回路（跳过两个 ZSL 界面慢用例，约 22 s）
.venv\Scripts\python.exe -m pytest tests -q -m "not slow" --basetemp=.pytest_tmp

REM 4) 接入你的 Agent（MCP stdio）
scripts\run_mcp.bat
REM   客户端配置片段见 MCP.md
```

通过第 3 步后，任意 MCP 客户端挂上即可调用 63 个工具。

---

## 目录结构

```
matcalc-agent/
├── AGENTS.md              # 所有 Agent 项目规矩
├── MCP.md                 # 工具接入与场景调用顺序
├── server/
│   ├── main.py            # 入口：63 个 @mcp.tool 注册
│   ├── remote.py          # ssh/scp 单点
│   ├── matcalc/           # 功能模块包
│   └── outputs/           # 生成产物（不入 git）
├── tests/                 # 离线回归（CI 同源）
├── dsh-plugin/            # 可选：DSH 会话连续性
├── scripts/
│   ├── run_mcp.bat        # 启动 MCP（Agent 无关）
│   ├── smoke_local.ps1    # 离线验收
│   └── start_matcalc_web.bat  # 可选 DSH Web
├── clusters.example.json
└── requirements.txt
```

## 里程碑状态（2026-08-27 全数达成）

- [x] **M0**：环境搭建 —— MCP Server 骨架 + pymatgen 连通（08-23）
- [x] **M1**：VASP 建模 + 输入生成 + 校验（08-23 提前；3D 预览经用户决策移除）
- [x] **M2**：远程提交 + 监控 + 失败诊断 + 结果解析（08-24~25 提前；调度器实为 Torque/PBS，双族白名单兼容；smoke-r4 终验 TOTEN 与锚点 Δ≈0.5 meV）
- [x] **M3**：性质工作流（DOS/能带/EOS/Bader/光学）+ 报告导出（08-26 提前；超额：界面建模、LAMMPS 链路、NEB 插值）
- [x] **M4**：原计划 LAMMPS → 实战变阵为作业守护（submit_and_watch/check_job 反查/LAMMPS 已由 S3 提前补齐）
- [x] **M5**：自动化闭环 —— workflow 状态机 + auto_submit 三态开关 + params_json 结构注入（08-27 摘冠：真实 POSCAR 注入 → 3712.master 自动 qsub 实演认证）

**当前规模**：63 个 MCP 工具 · 离线回归 + CI · NEB 支持 IDPP · 会话 binding/outbox/CAS · MP 热力学栈 · AIMD 输入生成 · XRD 模拟

## 运行 MCP Server

```bat
scripts\run_mcp.bat
```

默认 stdio，供任意 MCP 客户端以 subprocess 拉起。详见 [`MCP.md`](MCP.md)。

## Materials Project（可选联网）

MP 在本仓库里是**结构 + 热力学数据源**，也是 `mp_*` 工作流模板的参照；真正的计算仍由本机/集群 VASP 执行。
依赖 `mp-api[contribs]`（已在 `requirements.txt`），首次使用设置一次 key（也可在单次调用传 `api_key=`，但不要写进代码或文档）：

```powershell
$env:MP_API_KEY = "<your-key>"     # https://next-gen.materialsproject.org/api
```

### 能做什么

| 需求 | 工具 | 联网 | 说明 |
|---|---|---|---|
| 按 mp-id / 化学式取结构 | `fetch_mp_structure` | 是 | 转成 VASP5 POSCAR，落盘 `outputs/<project>/structures/`；可直接接 `generate_vasp_inputs` |
| 看体系凸包与稳定相 | `mp_phase_diagram` | 是 | 拉 MP 条目后用 pymatgen 现算稳定相与形成能（eV/atom） |
| 算指定反应的 ΔE | `mp_reaction_energy` | 是 | 按书写系数给 ΔE（eV）；负值代表放热倾向 |
| 两相接触会生成什么 | `mp_interface_reactions` | 是 | 0 K 凸包近似，按反应驱动力排序；可加 `open_circuit="Li"` 这类第三组元 |
| 电位–pH 稳定性 | `mp_pourbaix_diagram` | 是 | MP aqueous 条目 + pymatgen；可查 `(ph, v)` 单点稳定相 |
| 把 MP/atomate2 链映射到本仓库 | `mp_workflow_guide` | 否 | 纯离线知识库；topic = structure / relax / electronic / dielectric / elastic / phonon / neb / settings / makers |
| 跑 MP 风格 VASP 链 | 模板 `mp_relax_static` / `mp_relax_band` | 否 | 本仓库状态机 + VASP；结构可来自 `fetch_mp_structure`，不需要 MP key |

- `mp_relax_static`：relax → static/DOS → 提取 → 报告 → 笔记
- `mp_relax_band`：relax → static → band → DOS → 提取 → 报告 → 笔记

### 典型链路

```python
# 1) 取结构（mp-id 或化学式）
fetch_mp_structure("mp-22862", project="demo")

# 2) 热力学初筛
mp_phase_diagram("Na-V-O-F")
mp_reaction_energy("2 Fe2O3 + 3 C -> 4 Fe + 3 CO2")
mp_interface_reactions("NaF", "V2O5")
mp_pourbaix_diagram("Fe", ph=0, v=0)

# 3) 真算：MP 风格模板（本机/集群 VASP）
start_workflow(
    "mp_relax_band",
    project="demo",
    params_json='{"auto_submit": true, "node": "master", "ppn": 8, "poscar_path": "..."}',
)
```

### 边界（避免误用）

- **无 key 时**：只有 `mp_workflow_guide` 可用；其余 5 个 MP 工具返回 `E_PARAM`，不影响离线建模/解析。
- **MP 数值是 MP 的 DFT 结果**：相图/反应/界面为 0 K 近似（不含有限温熵），Pourbaix 为 25 °C 稀溶液近似；这些都不是你的 VASP 结果，适合趋势、凸包与副产物初筛，最终结论以自己计算为准。
- **不做实验数据检索**：MP 的 synthesis 配方、实验 XRD/PDF 不在封装内；`fetch_mp_structure` 只取结构。
- **未封装的 MP 取数**：声子、弹性张量、介电、分子/MOF、电池、实验合成配方等仍需到 MP 网站查询，或自行用 `mp-api` 扩展。
- **不自动匹配结构到 mp-id**：需要自己提供 mp-id 或化学式。
- **不缓存全库**：每次按需联网拉取，受网络与 MP 配额影响。
- 工具数仍为 **63**；MP 工具在既有名额内，不额外增加。

无 key 又想快速看结构时，可以手工查 MP 的公开 OPTIMADE 端点
（`https://optimade.materialsproject.org/v1/structures`）；它不是 MCP 工具，且化学式过滤按字母序（如 NaF → `FNa`），请求需带 `User-Agent`。

## 使用说明

### 1. 首次配置（一次性）

```bat
copy clusters.example.json clusters.json   REM 填写自己的机器字段（见下）
pip install -r requirements.txt
```

`clusters.json` 关键字段（脱敏模板见 `clusters.example.json`）：

| 字段 | 含义 |
|---|---|
| `default_node` | 默认节点名 |
| `local_potcar_lib` | 本地 POTCAR 库目录（VASP 版权，不随仓库分发） |
| `nodes.<名>.host` | `user@host` 形式 |
| `nodes.<名>.ssh_key` / `scheduler` / `queue` / `max_ppn` | 密钥路径 / 调度器（torque 或 slurm）/ 队列 / 最大核数 |
| `nodes.<名>.vasp_setup` / `vasp_exe` / `workroot` | 集群 VASP 环境加载命令 / 可执行名 / 作业根目录 |

### 2. 交互式用法（对话逐步调工具）

> 化学式 → 建模 → 输入 → 远程提交 → 解析 → 报告

```text
build_structure("NaCl", ...)          # 建模 + 结构校验
generate_vasp_inputs(...)             # 生成 INCAR/KPOINTS/POSCAR
submit_and_watch(node="master", ...)  # 提交集群并守望
analyze_vasprun(...) / plot_dos(...)  # 性质解析与绘图
export_report(...)                    # 汇总成 "材料性质报告.md"
```

### 3. 全自动工作流（推荐，跨天无人值守）

三条模板都使用同一套控制方式：先 `start_workflow`，取得返回的 `wf_id`；之后反复调用 `advance_workflow`。调用是幂等的，中途停止后可从同一个 `wf_id` 继续。

#### 示例 A：离线冒烟链（不提交集群）

适合首次安装后验证状态机、报告和笔记落盘。

```python
start_workflow("smoke_local_chain", project="demo_smoke")
# 返回：工作流 ID: smoke_local_chain_<时间戳>
advance_workflow("smoke_local_chain_<时间戳>", "demo_smoke")
workflow_status("smoke_local_chain_<时间戳>", "demo_smoke")
```

#### 示例 B：NMO 母相对比链（弛豫 + DOS + 形成能）

`E_O2` 供 `formation_energy` 步骤使用；打开 `auto_submit` 后，真实 POSCAR 会自动提交。

```python
start_workflow(
    "nmo_parent_compare",
    project="NMO_NaBattery",
    params_json='{"E_O2": 4.9, "auto_submit": true, "node": "master", "ppn": 8,
                  "poscar_path": "D:/path/to/CONTCAR"}',
)
advance_workflow("<wf_id>", "NMO_NaBattery")
# 作业完成后将 OUTCAR 放回对应步骤目录，再次 advance
workflow_status("<wf_id>", "NMO_NaBattery")
```

#### 示例 C：通用标准链（推荐日常使用）

最普遍的“弛豫 → 静态 DOS → 提取能量/DOS/带隙 → 报告 → 笔记”流程，不含 NMO 专属形成能语义。

```python
start_workflow(
    "relax_dos_standard",
    project="NaCl_standard",
    params_json='{"auto_submit": true, "node": "master", "ppn": 8,
                  "poscar_path": "D:/path/to/POSCAR"}',
)
advance_workflow("<wf_id>", "NaCl_standard")
# relax 和 dos 完成并回填 OUTCAR 后继续 advance
# extract 步骤写入 TOTEN_eV、dos_png、gap_eV_est
workflow_status("<wf_id>", "NaCl_standard")
```

- 模板 A `smoke_local_chain`：三步全离线，验证状态机
- 模板 B `nmo_parent_compare`：`parent_relax` → `parent_dos` → `formation_energy` → 报告 → 笔记
- 模板 C `relax_dos_standard`：`relax` → `dos` → `extract` → 报告 → 笔记
- VASP 步骤可用 `auto_submit=true` 自动提交，也可人工提交后将 `OUTCAR` 放回对应步骤目录
- 占位结构（未注入真实 POSCAR）会被护栏拦截，不会误提交集群

### 4. 工具族速查（63 个）

| 族 | 工具 |
|---|---|
| 建模 | build_structure · parse_poscar · make_supercell · cleave_surface · import_structure · build_from_spacegroup · edit_structure · primitive_cell · symmetry_report · view_structure_ase |
| 输入生成 | generate_vasp_inputs · generate_band/dos/optical/elastic/eos/bader_inputs · generate_sbatch |
| 解析诊断 | parse_vasp_output · analyze_vasprun · diagnose_vasp_error · parse_bader_acf |
| 绘图分析 | plot_dos · plot_pdos · plot_band · fit_eos · simulate_xrd |
| 远程作业 | configure_remote · check_connection · ssh_run · upload · download · submit_and_watch · check_job |
| 监控 | monitor_relax · monitor_aimd |
| 界面/LAMMPS/NEB | build_interface · inspect_interface_match · stack_slabs · build_lammps_data · generate_lammps_inputs · parse_lammps_log · generate_neb_endpoints/images/incar |
| 工作流 | start_workflow · advance_workflow · workflow_status |
| 智能建议 | suggest_u · suggest_magnetism · analyze_structure · compare_structures · record_feedback |
| Materials Project | fetch_mp_structure · mp_workflow_guide · mp_phase_diagram · mp_reaction_energy · mp_interface_reactions · mp_pourbaix_diagram · 模板 mp_relax_static / mp_relax_band |
| 治理报告 | organize_outputs · export_report · export_result_note |

### 5. 错误码约定

所有失败返回统一格式：`错误：[E_XXX] 中文说明`（兼容旧前缀"错误："）

| 码 | 含义 |
|---|---|
| `E_PARAM` | 参数非法（元素不存在、数值越界、结构缺失等） |
| `E_PARSE` | 文件/JSON 解析失败 |
| `E_CLUSTER` | 集群配置问题（节点未配置、不支持等） |
| `E_SSH` | 远程通道失败（连接、命令、产物回传） |

### 6. 测试与 CI

```bat
.venv\Scripts\python.exe -m pytest tests\ -q
```

GitHub Actions 自动跑同一套离线回归（当前实测 333 passed / 1 skipped），绿码才合入 main。

### 7. 长任务连续性与会话隔离

MatCalcAgent 采用“**聊天是视图，workflow 是任务，HPC job 是执行，产物是证据**”的边界：

```text
DSH session  ≠  workflow_id  ≠  scheduler job_id  ≠  scientific result
```

workflow 的权威状态保存在 `outputs/<project>/workflows/<wf_id>/state.json`；聊天只保存近期对话和任务引用，不承担任务状态。任务恢复原语是服务端内部函数，不额外占用 MCP 工具名额，因此 MCP 契约仍为 **63 个工具**：

```python
list_active_workflows(project=None)                          # 显式任务中心查询
startup_recovery_summary(project, workflow_ids)               # 仅按焦点生成摘要
route_workflow_request("继续", project, wf_id, workflow_ids)  # 只读寻址
```

路由与召回规则：

- **普通聊天默认零召回**：不注入全局 active workflow，也不写入 workflow；
- **新任务直接交给 DSH 智能体**：`NaCl VASP relax_dos_standard` 等消息不被 bridge 改写，模型可以调用已有 `build_structure`、`start_workflow` 等工具；
- **控制面按需读取**：只有明确的状态/继续请求才查询任务；裸“继续”还要求当前 session 仍有唯一、有效的任务焦点；
- **多任务拒绝猜测**：同一 session 绑定多个 active workflow 时返回 `choose`，必须指定 `wf_id` 或项目；
- **会话焦点从 DSH 持久化 `tool/call` / `tool/result` 事件重建**，重启不依赖进程内存；普通话题发生后，裸控制词不会自动劫持旧任务；
- 状态查询、路由和恢复摘要均为只读；真正推进仍由模型明确调用 `advance_workflow`，提交由 workflow 的 `auto_submit` 与幂等护栏控制。

DSH bridge 位于 `dsh-plugin/`：它现在是**控制面门卫/定向召回器**，不是第二个任务编排器；`agent/pre-step` 对普通消息和新任务 no-op，只在任务控制请求需要消歧时注入短上下文。配置中的 `matcalcRoot` 由 Web profile 层覆盖为本机仓库路径。这样既保留 63 个 MCP 工具，也避免未相关任务污染当前会话。

相关成熟模式：LangGraph 的 thread/checkpoint、Temporal 的 Workflow ID/Run ID 与 Query/Signal/Update、OpenAI Agents SDK 的 Session、Letta 的上下文层级。它们共同说明：**会话历史不是长任务状态，任务状态也不应广播到每个会话**。

本地 Web 验证（当前 `http://127.0.0.1:3080`）：重启后 `web` profile 成功加载 `@matcalc/dsh-continuity`；隔离会话的普通 Python 话题未产生 continuity 注入；UTF-8 材料任务真实调用了 `mcp__matcalc__build_structure` 与 `mcp__matcalc__start_workflow`，说明 bridge 没有拦截新任务。

### 独立 MatCalcAgent Web

专用入口：`http://127.0.0.1:3081`，启动脚本 `scripts/start_matcalc_web.bat`。

**必须使用独立 `DSH_HOME`**，否则两个实例会共用会话与工作区：

```bat
set "DSH_HOME=C:\Users\dell\.dsh-matcalc"
node C:\Users\dell\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh\lib\bin.js --profile matcalc-web --port 3081 --no-open
```

DSH 的家目录优先级为：显式配置 > `$DSH_HOME` > `~/.dsh`。会话（`sessions/`）、工作区与界面状态（`storages/`）、凭据（`.credentials.yaml`）都归属 `DSH_HOME`，**不按端口或 profile 区分**。因此仅创建新 profile 并不能隔离会话，只有换 `DSH_HOME` 才是真隔离。

独立 home 的组成：

```text
C:\Users\dell\.dsh-matcalc\
├── settings.yaml          模型与预设设置
├── .credentials.yaml      凭据（复制自 ~/.dsh）
├── .agent-presets\        自定义 agent 预设
└── profiles\
    ├── node_modules       指向 ~/.dsh 的 junction（共享已装依赖）
    └── matcalc-web\       专用 profile（含 MCP 与 continuity 插件）
```

隔离验证结果：`3080` 见 74 个会话、5 个工作区；`3081` 见 0 个会话（独立存储），其会话真实调用 `mcp__matcalc__parse_poscar`，且 `3080` 会话数不受影响。两个实例共享同一份 `server/outputs/<project>/workflows/` 任务真相与 63 个 MCP 工具。

## 许可证

本仓库代码采用 [MIT License](LICENSE)。第三方依赖各自遵循其原有许可证（pymatgen / ASE / mp-api / MCP SDK 等）。

**不包含、也不分发**：VASP 可执行程序与 POTCAR 赝势库（受 VASP 许可约束）、`clusters.json` 集群配置、SSH 私钥与任何凭据——相关路径均已列入 `.gitignore`。使用者需自行取得相应授权并填写本地配置。

