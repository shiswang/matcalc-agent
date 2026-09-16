# MCP.md — MatCalcAgent 工具接入指南（Agent 无关）

本 Server 通过 **Model Context Protocol (stdio)** 暴露 **62 个工具**。  
任何支持 MCP 的客户端（Claude Code、Cursor、DSH、自建 Agent）都可直接挂载。

---

## 1. 启动 MCP Server

仓库根目录：

```bat
scripts\run_mcp.bat
```

或：

```bat
.venv\Scripts\python.exe -m server.main
```

Windows 上若无 venv，用系统 Python 且已 `pip install -r requirements.txt`。

---

## 2. 客户端配置片段

把 `cwd` 换成你的仓库绝对路径。

### 通用（OpenAI 兼容 / 多数 MCP 客户端）

```json
{
  "mcpServers": {
    "matcalc": {
      "command": "C:/path/to/matcalc-agent/.venv/Scripts/python.exe",
      "args": ["-m", "server.main"],
      "cwd": "C:/path/to/matcalc-agent"
    }
  }
}
```

### Claude Code（`.mcp.json` 示例）

见 [`adapters/claude-code/.mcp.json.example`](adapters/claude-code/.mcp.json.example)。

### Cursor

见 [`adapters/cursor/README.md`](adapters/cursor/README.md)。

### DSH（可选，仅会话连续性）

见仓库 `dsh-plugin/` 与 README「独立 MatCalcAgent Web」。  
**非 DSH 用户可忽略**——MCP 工具本身不依赖 DSH。

### 首次配置集群（本地文件，不进 Git）

```bat
copy clusters.example.json clusters.json
REM 编辑 nodes：host=user@ip、ssh_key、scheduler、queue、vasp_setup...
```

未配置集群时，建模/输入/本地解析/绘图/离线 workflow 仍可用；SSH 类工具会报错提示。

私密字段（IP/账号/密钥）用 [`adapters/HANDOFF_PRIVATE.template.md`](adapters/HANDOFF_PRIVATE.template.md) 单独交接；填好后的 `HANDOFF_PRIVATE.md` 已被 gitignore。

---

## 3. 场景 → 调用顺序

| 目标 | 顺序 |
|------|------|
| 化学式 → 可提交 VASP 输入 | `build_structure` → `generate_vasp_inputs` |
| 能带 / DOS / 光学 / 弹性 / EOS / Bader | 对应 `generate_*_inputs` → 集群跑 → `parse_*` / `plot_*` |
| 标准弛豫+DOS 链 | `start_workflow(template="relax_dos_standard", project=...)` → 人工或 auto_submit → `advance_workflow` |
| 查进度 | `workflow_status` 或 `list_active` 文本；状态含 **revision** |
| 推进（建议 CAS） | `advance_workflow(wf_id, project, expected_revision=N)` |
| 远程作业 | `configure_remote` / `check_connection` / `submit_and_watch` / `check_job` |
| 结构体检 | `analyze_structure` / `compare_structures` / `monitor_relax` |
| 整理磁盘 | `organize_outputs(action="vacuum", dry_run=True)` 先报告 |

---

## 4. 工具清单（61）

### Materials Project
`fetch_mp_structure` · `mp_workflow_guide` · `mp_phase_diagram` · `mp_reaction_energy` · `mp_interface_reactions` · `mp_pourbaix_diagram`
模板：`mp_relax_static` · `mp_relax_band`（relax→static→bands→dos）
自动提交：`params_json=`{`poscar_text`: "...", `auto_submit`: true, `node`: "master"}

### 建模与结构
`build_structure` · `parse_poscar` · `make_supercell` · `cleave_surface` ·
`import_structure`（CIF/POSCAR） · `build_from_spacegroup`（Wyckoff 级） ·
`edit_structure`（代位/空位/间隙/缩放） · `primitive_cell` · `symmetry_report` ·
`view_structure_ase`

### VASP 输入生成
`generate_vasp_inputs` · `generate_band_inputs` · `generate_dos_inputs` · `generate_optical_inputs` · `generate_elastic_inputs` · `generate_eos_inputs` · `generate_bader_inputs` · `generate_sbatch` · `generate_aimd_inputs`

### 解析与诊断
`parse_vasp_output` · `analyze_vasprun` · `diagnose_vasp_error` · `parse_bader_acf`

### 绘图与拟合
`plot_dos` · `plot_pdos` · `plot_band` · `fit_eos`

### 远程与作业
`configure_remote` · `check_connection` · `ssh_run` · `upload` · `download` · `submit_and_watch` · `check_job`

### 数据治理与报告
`organize_outputs` · `export_report`

### 界面建模
`inspect_interface_match` · `build_interface` · `stack_slabs`

### LAMMPS
`build_lammps_data` · `generate_lammps_inputs` · `parse_lammps_log`

### NEB
`generate_neb_endpoints` · `generate_neb_images` · `generate_neb_incar`

### 知识沉淀
`export_result_note`

### 工作流
`start_workflow` · `advance_workflow` · `workflow_status`

### 结构后处理
`analyze_structure` · `compare_structures`

### 参数建议与回流
`suggest_u` · `suggest_magnetism` · `record_feedback`

### 计算监控
`monitor_relax` · `monitor_aimd`

参数细节以各工具 **MCP description / schema** 为准（客户端会自动注入）。

---

## 5. 最小可运行示例（伪会话）

```text
1) build_structure(formula="NaCl", prototype="rocksalt")
   → 返回 POSCAR 文本摘要与保存路径

2) generate_vasp_inputs(poscar_text=..., calc_type="relax", project="demo")
   → outputs/demo/inputs/ 下 INCAR/KPOINTS/POSCAR/make_potcar.sh

3) （可选连集群）check_connection(node="master")
   → 通过后再 submit_and_watch / start_workflow

4) 无集群时用本地链：
   start_workflow(template="smoke_local_chain", project="demo")
   → 反复 advance_workflow 直至 status=done
```

---

## 6. 验收（不连集群）

```powershell
.\scripts\smoke_local.ps1
```

通过标准见脚本输出：依赖 OK、**62 tools**、离线 NaCl 冒烟 PASS。

---

## 7. 相关文档

| 文件 | 用途 |
|------|------|
| `AGENTS.md` | 编码/协作规矩（所有 Agent） |
| `README.md` | 安装、架构、DSH 可选入口 |
| `clusters.example.json` | 集群配置模板 |
