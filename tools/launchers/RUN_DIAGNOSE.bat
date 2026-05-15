@echo off
title AAATS Grafana + Cloudflare Diagnose
cd /d "%~dp0..\.."
call venv\Scripts\activate.bat
python tools\operator\diagnose_grafana_cf.py
echo.
echo Press any key to close...
pause > nul
