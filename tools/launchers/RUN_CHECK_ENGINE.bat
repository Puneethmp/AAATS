@echo off
title AAATS Engine Check
cd /d "%~dp0..\.."
call venv\Scripts\activate.bat
python tools\operator\check_engine.py
echo.
echo Press any key to close...
pause > nul
