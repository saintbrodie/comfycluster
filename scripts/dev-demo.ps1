$ErrorActionPreference = "Stop"
Start-Process powershell -ArgumentList "-NoExit", "-Command", ".\.venv\Scripts\comfycluster-controller.exe serve"
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-NoExit", "-Command", ".\.venv\Scripts\comfycluster-agent.exe run --mock-gpus 2"
Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:9320"
