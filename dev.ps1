# Starts the API (port 8000) and the Vite dev server (port 5173) in two windows.
$root = $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; uv run uvicorn app.main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"
Write-Host "API:      http://localhost:8000/docs"
Write-Host "Frontend: http://localhost:5173"
