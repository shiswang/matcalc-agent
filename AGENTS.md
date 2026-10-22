# AGENTS.md — MatCalcAgent 项目规矩（所有 Agent 必读）

> 本文件给**任意编码/对话智能体**（Claude Code、Cursor、Codex、自建 Agent、MiMo 等）。
> 与具体宿主无关。DSH 专用细节见 `README.md` / `adapters/`（若存在）。

## 项目是什么

个人材料计算科研助手：**LLM 调度 + 确定性 MCP 工具层**（pymatgen / ASE / VASP 输入与解析）。
主交付物是 **MCP Server**（`server/`），不是某个聊天壳。

## 路径与产物

| 路径 | 规则 |
|------|------|
| `server/matcalc/` | 功能实现；`server/main.py` 只组装注册 |
| `server/outputs/` | **唯一**产物目录；测试与工具不得写到仓库其它位置 |
| `server/outputs/<project>/workflows/<wf_id>/state.json` | 工作流唯一真相 |
| `clusters.json` | 本地集群配置（**不入 git**）；模板见 `clusters.example.json` |
| `potcars/` | 赝势版权库（**不入 git、不分发**） |

## 禁止

1. 不要把 `clusters.json`、SSH 私钥、密码、内网 IP 写进代码/README/测试。
2. 不要提交 `server/outputs/`、`.venv/`、`potcars/`、`dsh-plugin/node_modules/`。
3. 不要让模型「自由生成」VASP 关键参数污染计算——参数必须经工具校验或人工确认。
4. 不要绕过 workflow：查询/恢复只读；真正推进用 `advance_workflow`。
5. 不要新增第二套长期记忆；知识沉淀走 candidate 片段 + Agent 归档，MCP 不直写 Vault。

## 工具契约

- MCP 工具数 **锁定 63**，由 `tests/test_registry.py` 断言。
- 加工具必须三处同步：模块 `TOOLS` 清单、`server/main.py` 注册循环、registry 测试。
- 包内跨层导入用 try「相对 → 绝对包路径」回退（脚本直跑与 `python -m` 双模式）。

## 工作流约定

- 模板：`smoke_local_chain` / `nmo_parent_compare` / `relax_dos_standard`。
- VASP 步骤默认**半自动**：生成输入 → 人工（或 `auto_submit`）提交 → OUTCAR 放回步骤目录 → `advance_workflow` 结算。
- `auto_submit`：占位结构会被拒绝；需真实 POSCAR 注入。
- `state.revision` 每次落盘 +1；并发写用 `advance_workflow(..., expected_revision=N)`。

## 会话连续性（可选，DSH）

- 普通聊天**零注入**；仅显式控制请求才路由。
- session 绑定 / outbox / inbox 见 `server/matcalc/session_binding.py`、`workflow_events.py`。
- 未绑定任务的事件不得广播到无关会话。

## 环境陷阱（摘要）

- Windows 无头 SSH：用绝对路径 `C:\Windows\System32\OpenSSH\ssh.exe` + `-n`。
- pymatgen `Poscar.get_str()` 物种行可能错位 → 统一 `structures._to_vasp5_poscar()`。
- 改 `server/main.py` 后 MCP 进程**不热载**，需重启后由下次调用拉起。
- pytest 用 `--basetemp=.pytest_tmp_<标识>`（系统 Temp 可能 ACL 拒绝）。
- 控制台中文/Å 输出前设 `PYTHONIOENCODING=utf-8`。
- **VASP 多核 PBS 必须 `mpirun -np $NPROC -machinefile $PBS_NODEFILE`**；裸 `vasp_std` 会单核。开跑后查 `running on N total cores`。
- **LDAUL/LDAUU/LDAUJ 长度必须等于 POSCAR 物种数**，且与物种序一一对应。
- **提交后 30 秒四查**：total cores / LDAU 长度 / POTCAR TITEL 序 / qstat ppn。

## 提交前自检

```text
1. .venv\Scripts\python.exe -m pytest tests -q --basetemp=.pytest_tmp_self
2. node --test tests/test_dsh_plugin.mjs   （若改了 dsh-plugin）
3. 工具数仍为 63
4. git status：无 outputs/ potcars/ clusters.json 密钥
```

## 验收（交付/接手）

```powershell
.\scripts\smoke_local.ps1
```

期望：依赖可 import、**63 tools**、离线结构冒烟 PASS。
