"""
Continuous paper trading runner for cloud/autonomous deployment.
Runs indefinitely — supervisord auto-restarts on crash.
Checkpoint survives restarts; cycle count is cumulative.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from foundation.logger import get_logger
from foundation.kill_switch import is_halted

_log = get_logger("phase1", "runner")

_DATA_DIR   = Path(os.environ.get("AAATS_DATA", "data"))
_CHECKPOINT = _DATA_DIR / "phase1_checkpoint.json"
_POLL_SEC   = 3600   # 1-hour cycles
_HB_INTV    = 30     # heartbeat check interval during sleep

_shutdown = False


def _handle_sig(signum, frame) -> None:
    global _shutdown
    _shutdown = True
    _log.warning("Signal received — finishing current cycle then stopping")


signal.signal(signal.SIGINT, _handle_sig)
try:
    signal.signal(signal.SIGTERM, _handle_sig)
except AttributeError:
    pass


def _interruptible_sleep(seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if _shutdown or is_halted("crypto"):
            return True
        time.sleep(min(_HB_INTV, max(0, end - time.time())))
    return False


def _load_checkpoint() -> dict:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _CHECKPOINT.exists():
        try:
            return json.loads(_CHECKPOINT.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_checkpoint(cp: dict) -> None:
    _CHECKPOINT.write_text(json.dumps(cp, indent=2))


def main() -> None:
    # Load env from .env if present (local dev)
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.split("#")[0].strip())

    from execution.crypto_runner import run_once
    from execution.status_db import upsert_status

    cp = _load_checkpoint()
    cycle        = cp.get("cycles_done", 0)
    total_trades = cp.get("trades_total", 0)
    errors       = cp.get("errors", 0)
    start_iso    = cp.get("start_time") or datetime.now(timezone.utc).isoformat()

    if cycle > 0:
        _log.info("=" * 50)
        _log.info(f"Continuous runner RESUMING — prior cycles: {cycle}, trades: {total_trades}")
        _log.info("=" * 50)
    else:
        start_iso = datetime.now(timezone.utc).isoformat()
        _log.info("=" * 50)
        _log.info(f"Continuous runner STARTED at {start_iso}")
        _log.info("=" * 50)

    while not _shutdown:
        if is_halted("crypto"):
            _log.info("Crypto halted — sleeping 5 min")
            upsert_status("crypto", status="HALTED")
            time.sleep(300)
            continue

        cycle += 1
        cycle_start = time.time()
        _log.info(f"[Cycle {cycle}] Starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            trades = run_once()
            total_trades += trades
            _log.info(f"[Cycle {cycle}] Done. Trades: {trades} | Total: {total_trades}")
        except Exception as exc:
            errors += 1
            _log.error(f"[Cycle {cycle}] Error: {exc}")
            upsert_status("crypto", status="ERROR", error=str(exc))

        cp.update({
            "phase": 1,
            "status": "RUNNING",
            "start_time": start_iso,
            "cycles_planned": 0,   # unlimited
            "cycles_done": cycle,
            "trades_total": total_trades,
            "errors": errors,
            "health_checks_ok": cycle - errors,
            "health_checks_failed": errors,
            "last_cycle": datetime.now(timezone.utc).isoformat(),
        })
        _save_checkpoint(cp)

        elapsed   = time.time() - cycle_start
        sleep_for = max(0, _POLL_SEC - elapsed)
        _log.info(f"Sleeping {sleep_for / 60:.1f} min until next cycle")
        if _interruptible_sleep(sleep_for):
            _log.warning("Interrupted — stopping after this cycle")
            break

    cp["status"] = "HALTED"
    _save_checkpoint(cp)
    _log.info("Continuous runner stopped gracefully")


if __name__ == "__main__":
    main()
