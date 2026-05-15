@echo off
echo ============================================================
echo  AAATS Fix Script — DB Schema + Metrics + C3 Diagnostics
echo ============================================================
echo.

cd /d "%~dp0..\.."

if not exist "data\diagnostics" mkdir "data\diagnostics"

pip install paramiko -q --break-system-packages 2>nul || pip install paramiko -q

echo Running fixes...
echo.
python tools\operator\fix_issues.py 2>&1 | tee data\diagnostics\fix_issues_output.txt

echo.
echo ============================================================
echo  Output saved to data\diagnostics\fix_issues_output.txt
echo ============================================================
pause
