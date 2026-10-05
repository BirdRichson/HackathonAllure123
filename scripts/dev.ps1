# Запуск в режиме разработки на Windows (PowerShell): бэкенд (8000) + фронтенд (5173).
# Проще всего — двойной щелчок по scripts\dev.cmd (обходит запрет на запуск сценариев PowerShell).
# Файл сохранён в UTF-8 с BOM: иначе Windows PowerShell 5.1 искажает русский текст в строках.
# Перед первым запуском:  python -m venv .venv ; .venv\Scripts\pip install -r backend\requirements-dev.txt ; cd frontend ; npm install ; cd ..
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

$back = Start-Process -PassThru -NoNewWindow -WorkingDirectory (Join-Path $Root "backend") -FilePath $Py `
  -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"
$front = Start-Process -PassThru -NoNewWindow -WorkingDirectory (Join-Path $Root "frontend") -FilePath "npm.cmd" `
  -ArgumentList "run", "dev"

Write-Host ""
Write-Host "  Интерфейс:  http://localhost:5173"
Write-Host "  API:        http://localhost:8000/api/health"
Write-Host "  Остановка:  Ctrl+C"
try { Wait-Process -Id $back.Id, $front.Id } finally {
  Stop-Process -Id $back.Id, $front.Id -ErrorAction SilentlyContinue
}
