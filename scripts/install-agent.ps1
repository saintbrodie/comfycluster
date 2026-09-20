param(
    [Parameter(Mandatory = $true)]
    [string]$ControllerUrl,

    [string]$AgentToken,

    [string]$UserToken,

    [string]$ComfyHome,

    [string]$ComfyCliExecutable,

    [switch]$DisableOutputArchive,

    [switch]$DeleteLocalOutputsAfterArchive,

    [string]$AgentExe = ".\comfycluster-agent.exe",

    [string]$DesktopExe = ".\ComfyCluster.exe",

    [bool]$LaunchDesktop = $true
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $AgentExe) -and (Test-Path ".\dist\comfycluster-agent.exe")) {
    $AgentExe = ".\dist\comfycluster-agent.exe"
}
if (-not (Test-Path $DesktopExe) -and (Test-Path ".\dist\ComfyCluster.exe")) {
    $DesktopExe = ".\dist\ComfyCluster.exe"
}
if (-not (Test-Path $AgentExe)) {
    throw "Agent executable not found at '$AgentExe'."
}

function ConvertTo-DotEnvValue([string]$Value) {
    if ($null -eq $Value) { return "''" }
    return "'" + ($Value -replace "'", "\\'") + "'"
}

function Find-ExistingSetting([string[]]$Lines, [string]$Name) {
    return $Lines | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -First 1
}

$installDir = Join-Path $env:LOCALAPPDATA "ComfyCluster"
$targetExe = Join-Path $installDir "comfycluster-agent.exe"
$targetDesktop = Join-Path $installDir "ComfyCluster.exe"
$configPath = Join-Path $installDir ".env"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Copy-Item -Force $AgentExe $targetExe
if (Test-Path $DesktopExe) {
    Copy-Item -Force $DesktopExe $targetDesktop
}

$existing = @()
if (Test-Path $configPath) {
    $existing = @(Get-Content $configPath)
}

$config = @(
    "COMFYCLUSTER_CONTROLLER_URL=$(ConvertTo-DotEnvValue $ControllerUrl)"
)

if ($AgentToken) {
    $config += "COMFYCLUSTER_AGENT_TOKEN=$(ConvertTo-DotEnvValue $AgentToken)"
} else {
    $line = Find-ExistingSetting $existing "COMFYCLUSTER_AGENT_TOKEN"
    if ($line) { $config += $line }
}

if ($UserToken) {
    $config += "COMFYCLUSTER_USER_TOKEN=$(ConvertTo-DotEnvValue $UserToken)"
} else {
    $line = Find-ExistingSetting $existing "COMFYCLUSTER_USER_TOKEN"
    if ($line) { $config += $line }
}

if ($ComfyHome) {
    $config += "COMFYCLUSTER_COMFY_HOME=$(ConvertTo-DotEnvValue $ComfyHome)"
} else {
    $line = Find-ExistingSetting $existing "COMFYCLUSTER_COMFY_HOME"
    if ($line) { $config += $line }
}

if ($ComfyCliExecutable) {
    $config += "COMFYCLUSTER_COMFY_CLI_EXECUTABLE=$(ConvertTo-DotEnvValue $ComfyCliExecutable)"
} else {
    $line = Find-ExistingSetting $existing "COMFYCLUSTER_COMFY_CLI_EXECUTABLE"
    if ($line) { $config += $line }
}

if ($DisableOutputArchive) {
    $config += "COMFYCLUSTER_ARCHIVE_OUTPUTS='false'"
} else {
    $line = Find-ExistingSetting $existing "COMFYCLUSTER_ARCHIVE_OUTPUTS"
    if ($line) { $config += $line }
}

if ($DeleteLocalOutputsAfterArchive) {
    $config += "COMFYCLUSTER_DELETE_LOCAL_OUTPUTS_AFTER_ARCHIVE='true'"
} else {
    $line = Find-ExistingSetting $existing "COMFYCLUSTER_DELETE_LOCAL_OUTPUTS_AFTER_ARCHIVE"
    if ($line) { $config += $line }
}

foreach ($settingName in @("COMFYCLUSTER_LOCAL_API_HOST", "COMFYCLUSTER_LOCAL_API_PORT", "COMFYCLUSTER_DESKTOP_REFRESH_SECONDS")) {
    $line = Find-ExistingSetting $existing $settingName
    if ($line) { $config += $line }
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

if (Test-Path $targetDesktop) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcutPaths = @(
        (Join-Path ([Environment]::GetFolderPath("Desktop")) "ComfyCluster.lnk"),
        (Join-Path ([Environment]::GetFolderPath("Programs")) "ComfyCluster.lnk")
    )
    foreach ($shortcutPath in $shortcutPaths) {
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $targetDesktop
        $shortcut.WorkingDirectory = $installDir
        $shortcut.IconLocation = $targetDesktop
        $shortcut.Save()
    }
}

Start-ScheduledTask -TaskName $taskName
Write-Host "Installed and started '$taskName'."
Write-Host "Agent: $targetExe"
Write-Host "Config: $configPath"
Write-Host "Controller: $ControllerUrl"
Write-Host "Central output archive: $(-not $DisableOutputArchive)"
Write-Host "Delete local output after verified archive: $($DeleteLocalOutputsAfterArchive.IsPresent)"
if ($UserToken) {
    Write-Host "Desktop user identity: configured"
}
if (Test-Path $targetDesktop) {
    Write-Host "Desktop: $targetDesktop"
    if ($LaunchDesktop) {
        Start-Process -FilePath $targetDesktop -WorkingDirectory $installDir
    }
}
