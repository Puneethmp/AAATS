@echo off
title AAATS Fix Missing Modules
cd /d "%~dp0..\.."
call venv\Scripts\activate.bat
python tools\operator\fix_missing_modules.py
echo.
echo Press any key to close...
pause > nul
