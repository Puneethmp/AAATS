@echo off
REM ═══════════════════════════════════════════════════════════════
REM  AAATS Live Paper Trader — Windows Task Scheduler launcher
REM  Runs hourly. Scheduled via Windows Task Scheduler.
REM
REM  Markets:  India NSE (Angel One SmartAPI) + Crypto (Binance)
REM  Strategy: Full AAATS consensus pipeline
REM  Output:   data\paper_trades.db  data\paper_report.html
REM ═══════════════════════════════════════════════════════════════

cd /d "C:\Users\udaym\OneDrive\Desktop\Puneeth"

REM ── Run paper trading cycle ──────────────────────────────────
call venv\Scripts\activate
echo [%DATE% %TIME%] Starting AAATS paper trading cycle...

python trading\live_paper_runner.py
if %ERRORLEVEL% NEQ 0 (
    echo [%DATE% %TIME%] ERROR: live_paper_runner.py failed with code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

REM ── Generate HTML report ─────────────────────────────────────
python trading\generate_report.py
if %ERRORLEVEL% NEQ 0 (
    echo [%DATE% %TIME%] WARNING: generate_report.py failed (non-fatal)
)

echo [%DATE% %TIME%] Done. Report: data\paper_report.html
