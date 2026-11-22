# PayInsight AI - one-time setup (Windows PowerShell). Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env from .env.example" }

Write-Host "== Backend: virtual environment + dependencies"
Set-Location "$root\backend"
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip -q
& .\.venv\Scripts\pip.exe install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "== Backend: generate deterministic demo databases"
& .\.venv\Scripts\python.exe scripts\seed.py
if ($LASTEXITCODE -ne 0) { throw "seeding failed" }

Write-Host "== Frontend: npm dependencies"
Set-Location "$root\frontend"
npm install --no-fund --no-audit
if ($LASTEXITCODE -ne 0) { throw "npm install failed" }

Set-Location $root
Write-Host "`nSetup complete. Start the app with:  powershell -ExecutionPolicy Bypass -File scripts\start.ps1"
