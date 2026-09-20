param(
    [string]$ListenHost = "0.0.0.0",
    [int]$Port = 9320,
    [string]$AgentToken,
    [string]$AdminToken,
    [string]$AssetRoot,
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

function Find-ExistingSetting([string[]]$Lines, [string]$Name) {
    return $Lines | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -First 1
}

$installDir = Join-Path $env:LOCALAPPDATA "ComfyCluster\Controller"
$targetExe = Join-Path $installDir "comfycluster-controller.exe"
$configPath = Join-Path $installDir ".env"
$databasePath = Join-Path $installDir "comfycluster.db"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Copy-Item -Force $ControllerExe $targetExe

$existing = @()
if (Test-Path $configPath) {
    $existing = @(Get-Content $configPath)
}

function Resolve-TokenLine([string]$Name, [string]$Supplied) {
    if ($Supplied) {
        return @("$Name=$(ConvertTo-DotEnvValue $Supplied)", $null)
    }
    $existingLine = Find-ExistingSetting $existing $Name
    if ($existingLine) {
        return @($existingLine, $null)
    }
    $generated = (& $targetExe new-agent-token).Trim()
    return @("$Name=$(ConvertTo-DotEnvValue $generated)", $generated)
}

$agentResolved = Resolve-TokenLine "COMFYCLUSTER_AGENT_TOKEN" $AgentToken
$adminResolved = Resolve-TokenLine "COMFYCLUSTER_ADMIN_TOKEN" $AdminToken
$agentTokenLine = $agentResolved[0]
$generatedAgentToken = $agentResolved[1]
$adminTokenLine = $adminResolved[0]
$generatedAdminToken = $adminResolved[1]

$assetRootLine = $null
if ($AssetRoot) {
    $assetRootLine = "COMFYCLUSTER_ASSET_ROOT=$(ConvertTo-DotEnvValue $AssetRoot)"
} else {
    $assetRootLine = Find-ExistingSetting $existing "COMFYCLUSTER_ASSET_ROOT"
    if (-not $assetRootLine) {
        $AssetRoot = Join-Path $installDir "assets"
        $assetRootLine = "COMFYCLUSTER_ASSET_ROOT=$(ConvertTo-DotEnvValue $AssetRoot)"
    }
}

@(
    "COMFYCLUSTER_DATABASE_PATH=$(ConvertTo-DotEnvValue $databasePath)"
    $assetRootLine
    $agentTokenLine
    $adminTokenLine
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
Write-Host "Private asset vault: configured in $configPath"
if ($generatedAgentToken) {
    Write-Host "Agent bootstrap token: $generatedAgentToken"
} elseif ($AgentToken) {
    Write-Host "Agent bootstrap token: using supplied token"
} else {
    Write-Host "Agent bootstrap token: preserved from existing config"
}
if ($generatedAdminToken) {
    Write-Host "Platform admin token: $generatedAdminToken"
    Write-Host "Store this separately from the agent token. It is for human/API administration."
} elseif ($AdminToken) {
    Write-Host "Platform admin token: using supplied token"
} else {
    Write-Host "Platform admin token: preserved from existing config"
}
Write-Host "Controller config: $configPath"
