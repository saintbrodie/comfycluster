$ErrorActionPreference = "Stop"
$taskName = "ComfyCluster Agent"
$installDir = Join-Path $env:LOCALAPPDATA "ComfyCluster"

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

if (Test-Path $installDir) {
    Remove-Item -Recurse -Force $installDir
}

Write-Host "ComfyCluster agent startup task removed."
