"""
Phase 1: 24-Hour Crypto Validation Runner

Runs the crypto paper trading loop, writes all metrics to:
  - logs/background_runner.log  (live tail)
  - data/phase1_metrics.json    (collected after 24h)

Usage:
    python scripts/phase1_runner.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from foundation.logger import get_logger
from foundation.kill_switch import is_halted

_log = get_logger("phase1", "runner")

_LOG_DIR = Path("logs")
_LOG_DIR.mkdir(exist_ok=True)

_PHASE1_STATE = Path("data/phase1_checkpoint.json")
_METRICS_OUT  = Path("data/phase1_metrics.json")
_POLL_SECONDS = 3600        # 1-hour cycles
_TOTAL_CYCLES = 24          # 24 cycles = 24 hours

# ─── load .env credentials into os.environ ────────────────────────────────────
def _load_env() -> None:
    env_file = Path(".env")
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.split("#")[0].strip()   # strip inline comments
        if k and v:
            os.environ.setdefault(k, v)


def _save_checkpoint(data: dict) -> None:
    _PHASE1_STATE.parent.mkdir(exist_ok=True)
    _PHASE1_STATE.write_text(json.dumps(data, indent=2))


def _load_checkpoint() -> dict:
    """Load existing checkpoint if RUNNING, so we can resume after a crash."""
    if not _PHASE1_STATE.exists():
        return {}
    try:
        cp = json.loads(_PHASE1_STATE.read_text(encoding="utf-8"))
        if cp.get("status") == "RUNNING" and cp.get("cycles_done", 0) > 0:
            return cp
    except Exception:
        pass
    return {}


def main() -> None:
    _load_env()

    # Resume from existing checkpoint if we crashed mid-run
    existing = _load_checkpoint()
    if existing:
        cycles_already_done = existing["cycles_done"]
        start_iso = existing["start_time"]
        end_iso = existing["expected_end"]
        _log.info("=" * 60)
        _log.info(f"PHASE 1: RESUMING from cycle {cycles_already_done}/{_TOTAL_CYCLES}")
        _log.info(f"Original start: {start_iso}")
        _log.info("=" * 60)
        checkpoint = existing
    else:
        start_ts = time.time()
        start_iso = datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat()
        end_ts = start_ts + _TOTAL_CYCLES * _POLL_SECONDS
        end_iso = datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()
        cycles_already_done = 0
        _log.info("=" * 60)
        _log.info("PHASE 1: 24-Hour Crypto Validation STARTED")
        _log.info(f"Start : {start_iso}")
        _log.info(f"End   : {end_iso}")
        _log.info("=" * 60)
        checkpoint = {
            "phase": 1,
            "status": "RUNNING",
            "start_time": start_iso,
            "expected_end": end_iso,
            "cycles_planned": _TOTAL_CYCLES,
            "cycles_done": 0,
            "trades_total": 0,
            "errors": 0,
            "health_checks_ok": 0,
            "health_checks_failed": 0,
        }
        _save_checkpoint(checkpoint)

    from execution.crypto_runner import run_once

    for cycle in range(cycles_already_done + 1, _TOTAL_CYCLES + 1):
        cycle_start = time.time()
        _log.info(f"[Cycle {cycle:02d}/{_TOTAL_CYCLES}] Starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        if is_halted("crypto"):
            _log.warning("Crypto market HALTED — stopping Phase 1")
            checkpoint["status"] = "HALTED"
            _save_checkpoint(checkpoint)
            break

        try:
            trades = run_once()
            checkpoint["trades_total"] += trades
            checkpoint["health_checks_ok"] += 1
            _log.info(f"[Cycle {cycle:02d}/{_TOTAL_CYCLES}] Done. Trades this cycle: {trades} | Total: {checkpoint['trades_total']}")
        except Exception as exc:
            checkpoint["errors"] += 1
            checkpoint["health_checks_failed"] += 1
            _log.error(f"[Cycle {cycle:02d}/{_TOTAL_CYCLES}] Error: {exc}")

        checkpoint["cycles_done"] = cycle
        checkpoint["status"] = "RUNNING"
        _save_checkpoint(checkpoint)

        # Sleep until next cycle (skip sleep on last cycle)
        if cycle < _TOTAL_CYCLES:
            elapsed = time.time() - cycle_start
            sleep_for = max(0, _POLL_SECONDS - elapsed)
            _log.info(f"Sleeping {sleep_for/60:.1f} min until next cycle…")
            time.sleep(sleep_for)

    # ── Completion ─────────────────────────────────────────────────────────────
    end_actual = datetime.fromtimestamp(time.time(), tz=timezone.utc).isoformat()
    checkpoint["status"] = "COMPLETED"
    checkpoint["actual_end"] = end_actual
    _save_checkpoint(checkpoint)

    # Collect final metrics
    _collect_metrics(checkpoint)

    _log.info("=" * 60)
    _log.info("PHASE 1 COMPLETE")
    _log.info(f"Cycles: {checkpoint['cycles_done']}/{_TOTAL_CYCLES}")
    _log.info(f"Trades: {checkpoint['trades_total']}")
    _log.info(f"Errors: {checkpoint['errors']}")
    _log.info("Metrics written to data/phase1_metrics.json")
    _log.info("=" * 60)


def _collect_metrics(checkpoint: dict) -> None:
    """Query DB and write phase1_metrics.json."""
    import sqlite3
    metrics: dict = {
        "phase": 1,
        "status": "COMPLETED",
        "duration_hours": checkpoint["cycles_done"],
        "cycles_done": checkpoint["cycles_done"],
        "trades": 0,
        "pnl": 0.0,
        "uptime_percent": 0.0,
        "health_checks": {
            "ok": checkpoint["health_checks_ok"],
            "failed": checkpoint["health_checks_failed"],
        },
        "avg_slippage_bps": 0.0,
        "drifts": 0,
        "kill_switch_tested": False,
        "all_checks_passed": False,
        "next_phase": 2,
        "collected_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    # Query paper trades DB
    trades_db = Path("data/paper_trades.db")
    if trades_db.exists():
        try:
            start_ts = time.time() - checkpoint["cycles_done"] * 3600
            with sqlite3.connect(trades_db) as conn:
                row = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(pnl), 0) FROM paper_trades WHERE market='crypto'",
                ).fetchone()
                metrics["trades"] = row[0] or 0
                metrics["pnl"] = round(row[1] or 0.0, 2)
        except Exception:
            pass

    # Slippage
    slippage_db = Path("data/slippage.db")
    if slippage_db.exists():
        try:
            with sqlite3.connect(slippage_db) as conn:
                row = conn.execute(
                    "SELECT AVG(ABS(slippage_bps)) FROM slippage WHERE market='crypto'"
                ).fetchone()
                metrics["avg_slippage_bps"] = round(row[0] or 0.0, 1)
        except Exception:
            pass

    # Uptime
    total = metrics["health_checks"]["ok"] + metrics["health_checks"]["failed"]
    metrics["uptime_percent"] = round(
        100 * metrics["health_checks"]["ok"] / max(total, 1), 1
    )

    # Validation checklist
    checks = {
        "uptime_ok":       metrics["uptime_percent"] >= 95,
        "trades_ok":       metrics["trades"] >= 1,
        "slippage_ok":     metrics["avg_slippage_bps"] <= 50 or metrics["avg_slippage_bps"] == 0,
        "drifts_ok":       metrics["drifts"] == 0,
        "errors_ok":       checkpoint["errors"] <= 2,
    }
    metrics["checks"] = checks
    metrics["all_checks_passed"] = all(checks.values())

    _METRICS_OUT.parent.mkdir(exist_ok=True)
    _METRICS_OUT.write_text(json.dumps(metrics, indent=2))
    _log.info(f"Metrics saved: {_METRICS_OUT}")


if __name__ == "__main__":
    main()
