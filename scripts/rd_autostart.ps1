# Register monitor to start at RD logon (runs visible — needed for Chrome/Akamai)
# Run as the RD user:  .\scripts\rd_autostart.ps1

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Exe = Join-Path $Root "dist\QueudAIO\QueudAIO.exe"
$Py = Join-Path $Root "rd_monitor.py"

if (Test-Path $Exe) {
    $Action = New-ScheduledTaskAction -Execute $Exe -WorkingDirectory (Split-Path $Exe)
    $Label = "QueudAIO.exe"
} elseif (Test-Path $Py) {
    $Action = New-ScheduledTaskAction -Execute "python" -Argument "`"$Py`"" -WorkingDirectory $Root
    $Label = "python rd_monitor.py"
} else {
    throw "Run build_rd_exe.ps1 or ensure rd_monitor.py exists"
}

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "RugbySA-Monitor" -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null

Write-Host "Scheduled task 'RugbySA-Monitor' registered at logon."
Write-Host "Runs: $Label"
Write-Host "Logs: $Root\data\monitor.log"
Write-Host "Remove: Unregister-ScheduledTask -TaskName RugbySA-Monitor -Confirm:`$false"