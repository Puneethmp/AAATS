# AAATS Paper Trader — Windows Task Scheduler setup
# Run once: powershell -ExecutionPolicy Bypass -File trading\setup_task.ps1

$TaskName    = "AAATS_PaperTrader"
$ProjectDir  = "C:\Users\udaym\OneDrive\Desktop\Puneeth"
$Python      = "$ProjectDir\venv\Scripts\python.exe"
$RunnerArgs  = "trading\live_paper_runner.py"
$ReportArgs  = "trading\generate_report.py"
$BatFile     = "$ProjectDir\trading\run_paper_trader.bat"

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Action: run the batch file (activates venv + runs both scripts)
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BatFile`"" `
    -WorkingDirectory $ProjectDir

# Trigger: every hour, starting now, indefinitely
$Trigger = New-ScheduledTaskTrigger `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -Once `
    -At (Get-Date)

$Trigger.Repetition.StopAtDurationEnd = $false

# Settings: run even when on battery, wake to run, don't stop if long
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable `
    -WakeToRun `
    -RunOnlyIfNetworkAvailable

# Register as current user (no password needed)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $Action `
    -Trigger  $Trigger `
    -Settings $Settings `
    -RunLevel Highest `
    -Force

Write-Host ""
Write-Host "✅ Task '$TaskName' registered successfully." -ForegroundColor Green
Write-Host "   Runs every hour | Log: $ProjectDir\logs\paper_runner.log" -ForegroundColor Cyan
Write-Host "   Dashboard: $ProjectDir\data\paper_report.html" -ForegroundColor Cyan
Write-Host ""
Write-Host "To run NOW: Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Yellow
Write-Host "To remove:  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
