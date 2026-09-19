$ErrorActionPreference = "Stop"
$taskName = "ComfyCluster Agent"
$installDir = Join-Path $env:LOCALAPPDATA "ComfyCluster"

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$shortcutPaths = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "ComfyCluster.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "ComfyCluster.lnk")
)
foreach ($shortcutPath in $shortcutPaths) {
    if (Test-Path $shortcutPath) {
        Remove-Item -Force $shortcutPath
    }
}

if (Test-Path $installDir) {
    Remove-Item -Recurse -Force $installDir
}

Write-Host "ComfyCluster desktop and agent startup task removed."
