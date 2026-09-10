@echo off
chcp 65001 >nul
REM ============================================================
REM  启动独立 MatCalcAgent Web（专用 DSH_HOME，端口 3081）
REM  与普通 DSH Web（3080）完全隔离：独立会话、独立工作区、
REM  独立界面状态；但共享同一份 workflow 状态与 MCP 工具。
REM  路径为本机配置，换机时按需修改下面三行。
REM ============================================================

set "DSH_HOME=C:\Users\dell\.dsh-matcalc"
set "NODE_EXE=E:\Soft\node\node.exe"
set "DSH_BIN=C:\Users\dell\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh\lib\bin.js"

if not exist "%DSH_HOME%" (
  echo [错误] 未找到独立 DSH_HOME: %DSH_HOME%
  exit /b 1
)

echo 正在启动 MatCalcAgent Web ...
start "" "%NODE_EXE%" "%DSH_BIN%" --profile matcalc-web --port 3081 --no-open
echo 入口: http://127.0.0.1:3081
