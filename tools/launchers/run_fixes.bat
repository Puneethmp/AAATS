@echo off
echo ============================================
echo  AAATS Fix Runner — paper_trades.db + metrics
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found on PATH. Install Python 3 first.
    pause
    exit /b 1
)

REM Install paramiko if missing
echo Checking paramiko...
python -c "import paramiko" >nul 2>&1
if errorlevel 1 (
    echo Installing paramiko...
    pip install paramiko --quiet
)

echo.
echo Running fix_issues.py...
echo.

cd /d "%~dp0..\.."
python tools\operator\fix_issues.py

echo.
echo ============================================
echo  Done. Review output above for any errors.
echo ============================================
pause
