param(
    [Parameter(Mandatory = $true)]
    [string]$ControllerUrl,

    [string]$AgentToken,

    [string]$ComfyHome,

    [string]$ComfyCliExecutable,

    [string]$AgentExe = ".\dist\comfycluster-agent.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $AgentExe)) {
    throw "Agent executable not found at '$AgentExe'. Run scripts\build-agent.ps1 first."
}

function ConvertTo-DotEnvValue([string]$Value) {
    if ($null -eq $Value) { return "''" }
    return "'" + ($Value -replace "'", "\\'") + "'"
}

$installDir = Join-Path $env:LOCALAPPDATA "ComfyCluster"
$targetExe = Join-Path $installDir "comfycluster-agent.exe"
$configPath = Join-Path $installDir ".env"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Copy-Item -Force $AgentExe $targetExe

$config = @(
    "COMFYCLUSTER_CONTROLLER_URL=$(ConvertTo-DotEnvValue $ControllerUrl)"
)
if ($AgentToken) {
    $config += "COMFYCLUSTER_AGENT_TOKEN=$(ConvertTo-DotEnvValue $AgentToken)"
}
if ($ComfyHome) {
    $config += "COMFYCLUSTER_COMFY_HOME=$(ConvertTo-DotEnvValue $ComfyHome)"
}
if ($ComfyCliExecutable) {
    $config += "COMFYCLUSTER_COMFY_CLI_EXECUTABLE=$(ConvertTo-DotEnvValue $ComfyCliExecutable)"
}
$config | Set-Content -Encoding UTF8 $configPath

$taskName = "ComfyCluster Agent"
$action = New-ScheduledTaskAction `
    -Execute $targetExe `
    -Argument "run" `
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
Write-Host "Config: $configPath"
Write-Host "Controller: $ControllerUrl"
