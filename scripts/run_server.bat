@echo off
REM MatCalcAgent MCP Server 启动脚本（stdio 传输，供 DSH 的 MCP 客户端连接）
cd /d "%~dp0.."
".venv\Scripts\python.exe" server\main.py
