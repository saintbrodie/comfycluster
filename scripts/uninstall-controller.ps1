param(
    [switch]$RemoveData,
    [int]$Port = 9320,
    [switch]$RemoveFirewallRule
)

$ErrorActionPreference = "Stop"
$taskName = "ComfyCluster Controller"
$installDir = Join-Path $env:LOCALAPPDATA "ComfyCluster\Controller"

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

if ($RemoveFirewallRule) {
    $ruleName = "ComfyCluster Controller TCP $Port"
    Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
}

if ($RemoveData -and (Test-Path $installDir)) {
    Remove-Item -Recurse -Force $installDir
    Write-Host "Removed controller task and data from $installDir"
} else {
    Write-Host "Removed controller task. Data/config preserved at $installDir"
}
