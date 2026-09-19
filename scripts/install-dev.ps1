$ErrorActionPreference = "Stop"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' was not found. Install Python 3.11+ for the development build."
}

py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -e ".[dev]"
Write-Host "ComfyCluster development environment is ready."
Write-Host "Controller: .\.venv\Scripts\comfycluster-controller.exe serve"
Write-Host "Agent:      .\.venv\Scripts\comfycluster-agent.exe run --mock-gpus 2"
