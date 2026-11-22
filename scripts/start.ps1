# PayInsight AI - start backend (port 8000) and frontend (port 5173) in two new windows.
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1
$root = Split-Path -Parent $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\frontend'; npm run dev"
Write-Host "Backend:  http://127.0.0.1:8000/health   (API docs: http://127.0.0.1:8000/docs)"
Write-Host "Frontend: http://localhost:5173"
