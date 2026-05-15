@echo off
title AAATS Contabo Deployment
echo ============================================================
echo   AAATS Deploying to Contabo VPS via Tailscale
echo   Target: aaats@100.95.126.39
echo ============================================================
echo.
cd /d "%~dp0..\.."
call venv\Scripts\activate.bat
python tools\operator\deploy_to_contabo.py
echo.
echo Press any key to close...
pause > nul
