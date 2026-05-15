@echo off
title AAATS Contabo Status Check
cd /d "%~dp0..\.."
call venv\Scripts\activate.bat
python tools\operator\check_and_start_trader.py
echo.
echo Press any key to close...
pause > nul
