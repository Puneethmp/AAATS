"""
scripts/health_check.py — Lightweight health probe for AAATS

Exposes:
  run_health_check(verbose: bool=False) -> dict
    Returns a structured dict consumed by scripts/health_http_server.py:
      {
        "timestamp": "...",
        "overall_status": "OK" | "WARNING" | "CRITICAL",
        "checks": {<name>: {"status": "...", "message": "..."}},
      }

  CLI (kept for backward-compat with Dockerfile HEALTHCHECK):
    Prints a short text summary and exits 0 (OK/WARNING) or 1 (CRITICAL).

DESIGN
------
- Stdlib + psutil only (no foundation/monitoring imports).
- Cheap: DB file stat, heartbeat JSON parse, disk + memory check.
- Tolerant: any individual check failure becomes a WARNING, not a hard fail.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("AAATS_DATA_DIR", "/app/data"))


def _check_paper_trades_db() -> dict:
    db = DATA_DIR / "paper_trades.db"
    if not db.exists():
        return {"status": "CRITICAL", "message": "paper_trades.db missing"}
    size_mb = db.stat().st_size / (1024 * 1024)
    return {"status": "OK", "message": f"paper_trades.db present ({size_mb:.2f} MB)"}


def _check_heartbeat() -> dict:
    hb = DATA_DIR / "heartbeat.json"
    if not hb.exists():
        return {"status": "CRITICAL", "message": "heartbeat.json missing (runner never started?)"}
    try:
        data = json.loads(hb.read_text())
        last_str = data.get("last_cycle") or data.get("timestamp") or ""
        if not last_str:
            return {"status": "WARNING", "message": "heartbeat has no timestamp"}
        last_str = last_str.replace("Z", "+00:00")
        last_dt = datetime.fromisoformat(last_str)
        age_s = (datetime.now(timezone.utc) - last_dt).total_seconds()
        if age_s > 3600:
            return {"status": "CRITICAL", "message": f"heartbeat stale {int(age_s)}s (>1h)"}
        if age_s > 1500:
            return {"status": "WARNING", "message": f"heartbeat stale {int(age_s)}s"}
        return {"status": "OK", "message": f"heartbeat age {int(age_s)}s"}
    except Exception as e:
        return {"status": "WARNING", "message": f"heartbeat parse error: {e}"}


def _check_disk() -> dict:
    try:
        free_gb = shutil.disk_usage(str(DATA_DIR)).free / (1024 ** 3)
    except Exception as e:
        return {"status": "WARNING", "message": f"disk_usage error: {e}"}
    if free_gb < 1.0:
        return {"status": "CRITICAL", "message": f"only {free_gb:.2f} GB free"}
    if free_gb < 5.0:
        return {"status": "WARNING", "message": f"low disk: {free_gb:.2f} GB free"}
    return {"status": "OK", "message": f"{free_gb:.1f} GB free"}


def _check_memory() -> dict:
    try:
        import psutil
        m = psutil.virtual_memory()
        if m.percent > 95:
            return {"status": "CRITICAL", "message": f"{m.percent:.0f}% mem used"}
        if m.percent > 85:
            return {"status": "WARNING", "message": f"{m.percent:.0f}% mem used"}
        return {"status": "OK", "message": f"{m.percent:.0f}% mem used"}
    except ImportError:
        return {"status": "WARNING", "message": "psutil not installed"}
    except Exception as e:
        return {"status": "WARNING", "message": f"psutil error: {e}"}


def run_health_check(verbose: bool = False) -> dict:
    checks = {
        "paper_trades_db": _check_paper_trades_db(),
        "heartbeat":       _check_heartbeat(),
        "disk":            _check_disk(),
        "memory":          _check_memory(),
    }
    statuses = [c["status"] for c in checks.values()]
    if "CRITICAL" in statuses:
        overall = "CRITICAL"
    elif "WARNING" in statuses:
        overall = "WARNING"
    else:
        overall = "OK"
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall,
        "checks": checks,
    }


def main() -> int:
    r = run_health_check()
    status = r["overall_status"]
    print(f"AAATS health: {status}")
    for name, c in r["checks"].items():
        print(f"  {c['status']:8s} {name}: {c['message']}")
    return 0 if status != "CRITICAL" else 1


if __name__ == "__main__":
    sys.exit(main())
