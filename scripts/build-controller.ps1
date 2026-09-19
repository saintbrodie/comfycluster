$ErrorActionPreference = "Stop"

if (-not (Test-Path .venv)) {
    python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[packaging]"
& .\.venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name comfycluster-controller `
    --paths src `
    --add-data "src\comfycluster_controller\static;comfycluster_controller\static" `
    src\comfycluster_controller\__main__.py

Write-Host "Built dist\comfycluster-controller.exe"
