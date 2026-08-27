# MatCalcAgent — 材料计算科研助手（工程代码）

基于 DeepSeek Harness（DSH）扩展层实现的个人材料计算科研助手。

- 项目知识文档与进度：见 Obsidian Vault `20_项目/MatCalcAgent/`
- 本目录为工程代码（Vault 外），含 MCP Server 骨架、Skills、profile 配置

## 目录结构

```
matcalc-agent/
├── server/            # Python MCP Server（确定性工具层）
│   ├── main.py        # 入口：build_structure / parse_poscar
│   └── outputs/       # 生成的结构文件（POSCAR）
├── scripts/
│   └── run_server.bat # MCP Server 启动脚本
└── .venv/             # Python 虚拟环境（pymatgen / ase / mcp）
```

## 里程碑状态

- [x] **M0**：环境搭建 —— MCP Server 骨架 + pymatgen 连通（本目录）
- [ ] **M1**：VASP 建模 + 输入生成 + 校验 + 3D 预览
- [ ] **M2**：SSH/Slurm 远程提交 + 监控 + 失败诊断 + 基础结果解析
- [ ] **M3**：性质工作流（能带/DOS、弹性常数）+ 报告生成与导出
- [ ] **M4**：LAMMPS 链路
- [ ] **M5**：批量扫描 Workflow + 错误自愈 + 知识沉淀

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
