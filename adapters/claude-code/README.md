# Claude Code / 通用 MCP 客户端适配

将 `.mcp.json.example` 中的 `REPLACE_WITH_ABS_PATH` 改为本机绝对路径后：

1. 复制为项目根 `.mcp.json`（或合并进已有 mcpServers）
2. 重启 Claude Code / 客户端
3. 确认出现 `matcalc` 服务器与 62 个工具

验收：在客户端里调用 `build_structure`，或仓库根执行 `scripts\smoke_local.ps1`。

DSH 用户请改用仓库根 README「独立 MatCalcAgent Web」，不必使用本目录。
