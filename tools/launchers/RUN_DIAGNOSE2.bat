@echo off
cd /d "%~dp0..\.."
if not exist "data\diagnostics" mkdir "data\diagnostics"
echo Running AAATS Diagnostic... > data\diagnostics\diagnose_output.txt 2>&1
echo. >> data\diagnostics\diagnose_output.txt
py -3 tools\operator\diagnose_and_fix.py >> data\diagnostics\diagnose_output.txt 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Python error code: %ERRORLEVEL% >> data\diagnostics\diagnose_output.txt
    python tools\operator\diagnose_and_fix.py >> data\diagnostics\diagnose_output.txt 2>&1
)
echo Done. >> data\diagnostics\diagnose_output.txt
