param(
    [int]$UiPort = 5173,
    [int]$BackendPort = 8787
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root "tia-lib\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "TIA virtual environment was not found at $python"
}

$env:TIA_PORT = $BackendPort
Start-Process -FilePath $python -ArgumentList "backend_service.py" -WorkingDirectory $root
Set-Location (Join-Path $root "ui")
$env:VITE_TIA_API_URL = "http://127.0.0.1:$BackendPort"
npm run dev -- --host 127.0.0.1 --port $UiPort