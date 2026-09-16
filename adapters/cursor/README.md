# Cursor MCP 配置示例

在 Cursor 的 MCP 设置中添加 server（或合并 `mcp.json`）：

```json
{
  "mcpServers": {
    "matcalc": {
      "command": "REPLACE_WITH_ABS_PATH/.venv/Scripts/python.exe",
      "args": ["-m", "server.main"],
      "cwd": "REPLACE_WITH_ABS_PATH/matcalc-agent"
    }
  }
}
```

改路径 → 保存 → 重启 Cursor → 确认 62 工具。
详见根目录 [`MCP.md`](../../MCP.md)。
