param(
    [string]$ListenHost = "0.0.0.0",
    [int]$Port = 9320,
    [string]$AgentToken,
    [string]$SslCertFile,
    [string]$SslKeyFile,
    [switch]$OpenFirewall,
    [string]$ControllerExe = ".\dist\comfycluster-controller.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ControllerExe)) {
    throw "Controller executable not found at '$ControllerExe'. Run scripts\build-controller.ps1 first."
}
if ([bool]$SslCertFile -ne [bool]$SslKeyFile) {
    throw "SslCertFile and SslKeyFile must be supplied together."
}

function ConvertTo-DotEnvValue([string]$Value) {
    if ($null -eq $Value) { return "''" }
    return "'" + ($Value -replace "'", "\\'") + "'"
}

$installDir = Join-Path $env:LOCALAPPDATA "ComfyCluster\Controller"
$targetExe = Join-Path $installDir "comfycluster-controller.exe"
$configPath = Join-Path $installDir ".env"
$databasePath = Join-Path $installDir "comfycluster.db"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Copy-Item -Force $ControllerExe $targetExe

$existingTokenLine = $null
if (Test-Path $configPath) {
    $existingTokenLine = Get-Content $configPath |
        Where-Object { $_ -match '^COMFYCLUSTER_AGENT_TOKEN=' } |
        Select-Object -First 1
}

$generatedToken = $null
if ($AgentToken) {
    $tokenLine = "COMFYCLUSTER_AGENT_TOKEN=$(ConvertTo-DotEnvValue $AgentToken)"
} elseif ($existingTokenLine) {
    $tokenLine = $existingTokenLine
} else {
    $generatedToken = (& $targetExe new-agent-token).Trim()
    $tokenLine = "COMFYCLUSTER_AGENT_TOKEN=$(ConvertTo-DotEnvValue $generatedToken)"
}

@(
    "COMFYCLUSTER_DATABASE_PATH=$(ConvertTo-DotEnvValue $databasePath)"
    $tokenLine
) | Set-Content -Encoding UTF8 $configPath

$arguments = @("serve", "--host", $ListenHost, "--port", [string]$Port)
if ($SslCertFile) {
    $arguments += @("--ssl-certfile", $SslCertFile, "--ssl-keyfile", $SslKeyFile)
}
$argumentString = ($arguments | ForEach-Object {
    if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\\"') + '"' } else { $_ }
}) -join ' '

$taskName = "ComfyCluster Controller"
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
    -Description "ComfyCluster fleet controller" `
    -Force | Out-Null

if ($OpenFirewall) {
    $ruleName = "ComfyCluster Controller TCP $Port"
    if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule `
            -DisplayName $ruleName `
            -Direction Inbound `
            -Action Allow `
            -Protocol TCP `
            -LocalPort $Port | Out-Null
    }
}

Start-ScheduledTask -TaskName $taskName
$scheme = if ($SslCertFile) { "https" } else { "http" }
$wsScheme = if ($SslCertFile) { "wss" } else { "ws" }
Write-Host "Installed and started '$taskName'."
Write-Host "Dashboard: ${scheme}://localhost:$Port"
Write-Host "Agent URL: ${wsScheme}://<controller-host>:$Port/api/v1/agents/ws"
if ($generatedToken) {
    Write-Host "Agent bootstrap token: $generatedToken"
} elseif ($AgentToken) {
    Write-Host "Agent bootstrap token: using supplied token"
} else {
    Write-Host "Agent bootstrap token: preserved from existing config"
}
Write-Host "Controller config: $configPath"
