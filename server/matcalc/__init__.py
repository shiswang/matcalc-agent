"""MatCalcAgent 工具函数包（M5 拆分重构，见 Vault《M5架构设计_v1》§2）。

设计原则：
1. 工具函数与 MCP 注册解耦——各模块导出纯函数 + TOOLS 清单，
   main.py 仅做组装注册；内部逻辑以普通函数形式可独立 import。
2. 入口与启动方式不变：DSH profile 仍以 server/main.py 唯一入口。
"""

__all__ = ["common", "clusters"]
