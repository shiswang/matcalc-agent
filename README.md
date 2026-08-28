# MatCalcAgent — 材料计算科研助手（工程代码）

基于 DeepSeek Harness（DSH）扩展层实现的个人材料计算科研助手。

- 项目知识文档与进度：见 Obsidian Vault `20_项目/MatCalcAgent/`
- 本目录为工程代码（Vault 外），含 MCP Server 骨架、Skills、profile 配置

## 目录结构

```
matcalc-agent/
├── server/
│   ├── main.py          # 入口：49 个 @mcp.tool 薄封装（按模块 TOOLS 清单注册）
│   ├── remote.py        # ssh/scp 单点（双节点白名单 + 诊断侧日志）
│   ├── matcalc/         # 13 个功能模块包（structures/interfaces/lammps/neb/
│   │                    #   parsing/plotting/analysis/workflows/jobs/...）
│   └── outputs/         # 生成产物（POSCAR/OUTCAR/报告/workflow 状态）
├── tests/               # 176 项离线回归（CI 同源）
├── .github/workflows/   # pytest 门禁
├── clusters.example.json
├── scripts/run_server.bat
└── .venv/               # pymatgen / pymatgen-analysis-diffusion / ase / fastmcp
```

## 里程碑状态（2026-08-27 全数达成）

- [x] **M0**：环境搭建 —— MCP Server 骨架 + pymatgen 连通（08-23）
- [x] **M1**：VASP 建模 + 输入生成 + 校验（08-23 提前；3D 预览经用户决策移除）
- [x] **M2**：远程提交 + 监控 + 失败诊断 + 结果解析（08-24~25 提前；调度器实为 Torque/PBS，双族白名单兼容；smoke-r4 终验 TOTEN 与锚点 Δ≈0.5 meV）
- [x] **M3**：性质工作流（DOS/能带/EOS/Bader/光学）+ 报告导出（08-26 提前；超额：界面建模、LAMMPS 链路、NEB 插值）
- [x] **M4**：原计划 LAMMPS → 实战变阵为作业守护（submit_and_watch/check_job 反查/LAMMPS 已由 S3 提前补齐）
- [x] **M5**：自动化闭环 —— workflow 状态机 + auto_submit 三态开关 + params_json 结构注入（08-27 摘冠：真实 POSCAR 注入 → 3712.master 自动 qsub 实演认证）

**当前规模**：49 个 MCP 工具 · 183 项测试 · GitHub Actions CI 门禁 · NEB 支持 IDPP 弹性插值（pymatgen-analysis-diffusion）

## 运行 MCP Server

```bat
scripts\run_server.bat
```

或直接：

```bat
.venv\Scripts\python.exe server\main.py
```

默认以 stdio 传输运行，供 DSH 的 MCP 客户端（`dsh-mcp-client`）以
subprocess 方式拉起连接。DSH 侧连接配置见 Vault 项目笔记 / `dsh.profile`。

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

### 4. 工具族速查（49 个）

| 族 | 工具 |
|---|---|
| 建模 | build_structure · parse_poscar · make_supercell · cleave_surface |
| 输入生成 | generate_vasp_inputs · generate_band/dos/optical/elastic/eos/bader_inputs · generate_sbatch |
| 解析诊断 | parse_vasp_output · analyze_vasprun · diagnose_vasp_error · parse_bader_acf |
| 绘图分析 | plot_dos · plot_pdos · plot_band · fit_eos |
| 远程作业 | configure_remote · check_connection · ssh_run · upload · download · submit_and_watch · check_job |
| 监控 | monitor_relax · monitor_aimd |
| 界面/LAMMPS/NEB | build_interface · inspect_interface_match · stack_slabs · build_lammps_data · generate_lammps_inputs · parse_lammps_log · generate_neb_endpoints/images/incar |
| 工作流 | start_workflow · advance_workflow · workflow_status |
| 智能建议 | suggest_u · suggest_magnetism · analyze_structure · compare_structures · record_feedback |
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

GitHub Actions 自动跑同一套 185 项离线回归，绿码才合入 main。
