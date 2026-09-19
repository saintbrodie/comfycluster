param(
    [Parameter(Mandatory = $true)]
    [string]$ControllerUrl,

    [string]$ComfyHome,

    [string]$AgentExe = ".\dist\comfycluster-agent.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $AgentExe)) {
    throw "Agent executable not found at '$AgentExe'. Run scripts\build-agent.ps1 first."
}

$installDir = Join-Path $env:LOCALAPPDATA "ComfyCluster"
$targetExe = Join-Path $installDir "comfycluster-agent.exe"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Copy-Item -Force $AgentExe $targetExe

$arguments = @("run", "--controller", $ControllerUrl)
if ($ComfyHome) {
    $arguments += @("--comfy-home", $ComfyHome)
}
$argumentString = ($arguments | ForEach-Object {
    if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\\"') + '"' } else { $_ }
}) -join ' '

$taskName = "ComfyCluster Agent"
$action = New-ScheduledTaskAction `
    -Execute $targetExe `
    -Argument $argumentString `
    -WorkingDirectory $installDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$userId = if ($env:USERDOMAIN) { "$env:USERDOMAIN\$env:USERNAME" } else { $env:USERNAME }
$principal = New-ScheduledTaskPrincipal `
    -UserId $userId `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Description "ComfyCluster Windows GPU worker agent" `
    -Force | Out-Null

Start-ScheduledTask -TaskName $taskName
Write-Host "Installed and started '$taskName'."
Write-Host "Agent: $targetExe"
Write-Host "Controller: $ControllerUrl"
