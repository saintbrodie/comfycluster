$ErrorActionPreference = "Stop"

if (-not (Test-Path .venv)) {
    # Respect the interpreter selected by the caller (for example actions/setup-python)
    # instead of asking the Windows py launcher to choose a different Python version.
    python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[packaging]"
& .\.venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name comfycluster-agent `
    --paths src `
    src\comfycluster_agent\__main__.py

Write-Host "Built dist\comfycluster-agent.exe"
