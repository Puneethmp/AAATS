@echo off
REM ═══════════════════════════════════════════════════════════════
REM  AAATS Paper Trader — One-time Task Scheduler setup
REM  Double-click this file ONCE to register the hourly task.
REM  You can safely delete this file afterwards.
REM ═══════════════════════════════════════════════════════════════

cd /d "C:\Users\udaym\OneDrive\Desktop\Puneeth"

echo Removing any existing AAATS_PaperTrader task...
schtasks /delete /tn "AAATS_PaperTrader" /f 2>nul

echo Registering hourly paper trading task...
schtasks /create ^
  /tn "AAATS_PaperTrader" ^
  /tr "\"C:\Users\udaym\OneDrive\Desktop\Puneeth\trading\run_paper_trader.bat\"" ^
  /sc hourly ^
  /mo 1 ^
  /st 09:00 ^
  /sd 06/05/2026 ^
  /rl limited ^
  /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo  SUCCESS! Task registered.
    echo  Runs every hour starting 09:00.
    echo  Log:       trading\logs\paper_runner.log
    echo  Dashboard: data\paper_report.html
    echo.
    echo  To run NOW:   schtasks /run /tn "AAATS_PaperTrader"
    echo  To check:     schtasks /query /tn "AAATS_PaperTrader" /fo list
    echo  To remove:    schtasks /delete /tn "AAATS_PaperTrader" /f
) else (
    echo.
    echo  ERROR: Task registration failed. Try running as Administrator.
)

pause
