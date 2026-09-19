$ErrorActionPreference = "Stop"

if (-not (Test-Path .venv)) {
    py -3 -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -e ".[packaging]"
& .\.venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name comfycluster-agent `
    --paths src `
    src\comfycluster_agent\__main__.py

Write-Host "Built dist\comfycluster-agent.exe"
