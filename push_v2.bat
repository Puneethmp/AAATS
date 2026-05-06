@echo off
REM ═══════════════════════════════════════════════════════════════
REM  AAATS — Push v2 paper trading upgrade to GitHub
REM  Double-click to run once. Uses your cached Windows git creds.
REM ═══════════════════════════════════════════════════════════════
cd /d "C:\Users\udaym\OneDrive\Desktop\Puneeth"

echo [%DATE% %TIME%] Pushing v2 upgrades to GitHub...
git push origin main
if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] Push successful!
    echo      Commit: Upgrade paper trading to v2 - institutional grade
) else (
    echo.
    echo [ERROR] Push failed. You may need to authenticate.
    echo         Try running: git push origin main
    echo         in this folder's terminal.
)
pause
