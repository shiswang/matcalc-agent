# skills/ — MatCalcAgent 教程层

> 这是**教程层（中间层）**，不是工具层。它告诉 Agent「怎么组合现有 MCP 工具 + 本地脚本完成一个科研任务」。
> 灵感来自 [Agent Skills](https://agentskills.io) 规范与 MIT `AtomisticSkills` 的三层结构（Workflow → Skills → Tools）。

## 为什么有这一层

`server/` 暴露的是**确定性原子操作**（63 个 MCP 工具，单次调用、固定输入输出）。但一个真实科研任务——
比如「算某材料的 E_hull」或「从 AIMD 轨迹拟合扩散系数」——需要多步编排 + 少量数据后处理。
过去这些编排逻辑只能写死在 workflow 状态机模板里，新增一个任务就要改 Python。

教程层把这类「配方」写成 Agent 可读的 `SKILL.md`：**加科研能力不改一行工具代码**。

## 三层对应关系

| 层 | 本仓库位置 | 职责 | 是否占 MCP 名额 |
|---|---|---|---|
| Tools | `server/matcalc/` + `server/main.py` | 确定性原子操作 | 是（锁定 63） |
| **Skills（本层）** | `skills/<name>/SKILL.md` | 任务导向的配方：组合哪些工具、什么顺序、注意什么 | **否** |
| Workflow | `server/matcalc/workflows.py` 的 `WF_TEMPLATES` | 跨天的持久化状态机、幂等推进、报告笔记 | 否（3 个编排工具内） |

## 硬性约束（必须遵守）

1. **不占 MCP 名额**：`skills/` 下的任何内容都**不得**注册进 `server/main.py`，`tests/test_registry.py` 仍断言 63 个工具。
2. **不改 `server/`**：教程层只增不改；若发现确实是工具缺口，先在本文件底部「能力缺口」登记，走正常加工具流程（三处同步）。
3. **产物只写 `server/outputs/<project>/`**：脚本用 `--out` 指定输出目录，默认落该项目目录；严禁写到仓库其它位置（见 `AGENTS.md`）。
4. **知识沉淀走候选片段**：脚本产出的是数据与结论草稿；要入库必须经 `export_result_note` 生成 `status: candidate` 笔记，MCP 不直写 Vault。
5. **护栏不绕过**：VASP 关键参数必须经工具校验或人工确认；占位结构不得提交；失败码解释以工具返回的 `E_*` 为准。教程里的参数建议是**推荐值**，不是自动执行的凭据。
6. **依赖只用已装包**：脚本仅依赖 `requirements.txt` 中已有的 numpy / pymatgen / matplotlib，不引入新 pip 依赖。

## 目录结构规范

```text
skills/<skill-name>/              # kebab-case，材料类用 mat- 前缀
├── SKILL.md                      # 必需：教程正文
└── scripts/                      # 可选：辅助脚本（工具层没有的数据后处理）
    └── <script>.py               # 自带 --help，依赖已有包，产物写 outputs/
```

## SKILL.md 写作规范

### Frontmatter

只使用 Agent Skills 规范允许的顶层键：`name` / `description` / `license` / `compatibility` / `metadata` / `allowed-tools`。
项目特有信息（分类、依赖脚本、所需工具）放 `metadata`（自由 map），避免 claude.ai 上传/Skills API 因多余键报错。

```yaml
---
name: mat-example
description: 一句话说明「这个技能用来做什么」，要足够清楚让 Agent 判断是否相关；写用途不写原理。
metadata:
  category: [materials]
  tools: [tool_a, tool_b]
  scripts: [scripts/foo.py]
---
```

- `description` 用「what」不用「how」，不要在未加引号的值里用冒号+空格（会破坏 YAML 解析）。
- `category` 恒为 YAML 列表：`materials` / `chemistry` / `mcp-tool-usage` / `general`。

### 正文结构

1. `# 标题` — 与 name 对应
2. `## Goal` — 精确的技术目标，可含数学记号（如 $E_{hull}$）
3. `## 何时使用 / 不适用` — 触发条件与边界，避免 Agent 误用（本项目尤其重要：已有明确的方法分工）
4. `## 前置条件` — 需要的 key、结构来源、环境
5. `## 步骤` — 编号步骤；每步写清：调用哪个工具/脚本、真实参数示例（非占位符）、产出什么、如何判断成功
6. `## 能力边界与常见坑` — 工具做不到什么、数值近似的适用范围、已知陷阱
7. `## 示例` — 一段完整可跑的调用序列
8. `## 相关技能` — 相对链接互引

### 写作原则

- **参数用真实值**：写 `temperature=600.0, nsw=5000`，不写 `temperature=<你的值>`。示例值要给量级说明。
- **标注工具 vs 脚本**：`mcp__matcalc__xxx` 是 MCP 工具；`python skills/.../scripts/xxx.py` 是本地脚本。
- **每个脚本都有退出判据**：什么返回算成功、什么 `E_*` 码该停、什么情况要人工确认。
- **跨技能用相对链接**：`[相关技能](../mat-diffusion-aimd/SKILL.md)`。

## 当前技能

| 技能 | 目标 | 依赖工具 | 本地脚本 |
|---|---|---|---|
| [mat-ehull-stability](mat-ehull-stability/SKILL.md) | 0 K 凸包稳定性 / E_hull | `fetch_mp_structure`、`mp_phase_diagram`、`mp_reaction_energy` | `compute_ehull.py` |
| [mat-diffusion-aimd](mat-diffusion-aimd/SKILL.md) | AIMD 轨迹 → 扩散系数与激活能 | `build_structure`、`make_supercell`、`generate_aimd_inputs`、`monitor_aimd` | `msd_diffusivity.py` |

## 能力缺口（想加但不该靠教程硬凑的）

- **E_hull 直接查询**：`mp_phase_diagram` 只列稳定相清单，不给指定化合物的 E_hull；现由 `compute_ehull.py` 本地补上。若高频使用，应正式加 MCP 工具（三处同步）。
- **扩散系数拟合**：新版 pymatgen（2026.5.4）已移除 `DiffusionAnalyzer`；现由 `msd_diffusivity.py` 用 numpy 自算 MSD + Einstein 关系补上。
- **有限温相图 / 电化学窗口**：尚未封装，需要时先查 `mp_workflow_guide`，再决定是否加工具。
