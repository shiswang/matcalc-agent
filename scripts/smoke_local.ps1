# smoke_local.ps1 — 离线验收入口（逻辑在 smoke_local.py，避免 PS 编码问题）
# 用法：仓库根执行  .\scripts\smoke_local.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "== Python ==" -ForegroundColor Cyan
& $py -c "import sys; print(sys.version)"
if ($LASTEXITCODE -ne 0) { throw "python failed" }

Write-Host "== Offline smoke ==" -ForegroundColor Cyan
& $py "$root\scripts\smoke_local.py"
if ($LASTEXITCODE -ne 0) { throw "smoke_local.py failed" }

Write-Host "== pytest sample ==" -ForegroundColor Cyan
& $py -m pytest tests/test_registry.py tests/test_structures.py -q --basetemp=.pytest_tmp_smoke
if ($LASTEXITCODE -ne 0) { throw "pytest sample failed" }

Write-Host ""
Write-Host "SMOKE PASS - see MCP.md for client config" -ForegroundColor Green
