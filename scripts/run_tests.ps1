# PayInsight AI - run all automated checks.
#   powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1 [-E2E] [-Benchmark]
# -E2E requires the app to be running (scripts\start.ps1) and requirements-dev.txt installed.
param([switch]$E2E, [switch]$Benchmark)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$failed = 0

Set-Location "$root\backend"
Write-Host "== Backend: pytest (unit + 18 progressive iterations)"
& .\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { $failed++ }

Set-Location "$root\frontend"
Write-Host "== Frontend: typecheck"
npx tsc --noEmit -p .
if ($LASTEXITCODE -ne 0) { $failed++ }
Write-Host "== Frontend: vitest"
npx vitest run
if ($LASTEXITCODE -ne 0) { $failed++ }
Write-Host "== Frontend: production build"
npx vite build
if ($LASTEXITCODE -ne 0) { $failed++ }

Set-Location "$root\backend"
if ($E2E) {
  Write-Host "== Browser journeys (Playwright + installed Microsoft Edge)"
  & .\.venv\Scripts\python.exe tests\e2e\browser_journey.py
  if ($LASTEXITCODE -ne 0) { $failed++ }
}
if ($Benchmark) {
  Write-Host "== Performance benchmark (30k and 100k rows)"
  & .\.venv\Scripts\python.exe scripts\benchmark.py
  if ($LASTEXITCODE -ne 0) { $failed++ }
}
Set-Location $root
if ($failed -gt 0) { Write-Host "`n$failed check group(s) FAILED" -ForegroundColor Red; exit 1 }
Write-Host "`nAll checks passed" -ForegroundColor Green
