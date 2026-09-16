@echo off
REM MatCalcAgent MCP Server（stdio）— 不绑定 DSH
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m server.main
) else (
  python -m server.main
)
