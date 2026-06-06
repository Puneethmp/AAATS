#!/usr/bin/env python3
"""AAATS T3 positioning collector — hourly OI + premium-index snapshot (2026-06-06).

Forward-collects the positioning-crowding data family registered (DATA-GATED) by
docs/decisions/2026-06-06_reactivation_thesis_portfolio_preregistration.md §3 T3.
Binance only serves ~30d of OI history, so the T3 thesis cannot be backtested until
>=9 months are collected forward (or historical data is purchased). This cron is
that forward collector. It does NOT compute any signal or PnL — pure data capture.

Runs hourly from the box crontab as the `aaats` user (NOT in a container). Stdlib
only (urllib + sqlite3) so it needs no venv/pip. Append-only: INSERT only, never
UPDATE/DELETE — the capture is the immutable record.

  - OI:      GET /fapi/v1/openInterest?symbol=  (per symbol; base-unit OI)
  - premium: GET /fapi/v1/premiumIndex          (all symbols in one call)
  - oi_notional_usd = open_interest * mark_price

L10-style disk guard: if /home usage >85%, fire one Telegram alert via
aaats-cron-alert.sh (prefix T3/DISK) and keep collecting (capture continuity beats
silence). Universe is the static top-30 in t3_u30_symbols.txt beside this script;
refresh it by re-running the U30 resolver and re-deploying that file.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FAPI = "https://fapi.binance.com"
BASE_DIR = Path("/home/aaats/t3")
DB_PATH = BASE_DIR / "t3_positioning.db"
SYMS_FILE = Path(__file__).resolve().parent / "t3_u30_symbols.txt"
ALERT_SCRIPT = "/home/aaats/bin/aaats-cron-alert.sh"
DISK_PATH = "/home"
DISK_WARN_PCT = 85.0
DISK_ALERT_COOLDOWN_S = 6 * 3600  # one disk alert per 6h
DISK_STAMP = BASE_DIR / ".t3_disk_alert_stamp"


def _get(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": "aaats-t3-collector"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (public)
        return json.loads(resp.read().decode())


def _alert(message: str) -> None:
    """Best-effort Telegram alert via the existing cron-alert helper."""
    if not os.path.exists(ALERT_SCRIPT):
        return
    try:
        subprocess.run(["bash", ALERT_SCRIPT, message], timeout=30, check=False)
    except Exception:
        pass


def _disk_guard() -> None:
    try:
        st = os.statvfs(DISK_PATH)
        used_pct = 100.0 * (1.0 - (st.f_bavail / st.f_blocks))
    except Exception:
        return
    if used_pct < DISK_WARN_PCT:
        return
    now = time.time()
    last = 0.0
    if DISK_STAMP.exists():
        try:
            last = float(DISK_STAMP.read_text().strip() or "0")
        except Exception:
            last = 0.0
    if now - last >= DISK_ALERT_COOLDOWN_S:
        _alert(
            f"L10/DISK T3 collector: {DISK_PATH} at {used_pct:.1f}% (>{DISK_WARN_PCT}%)"
        )
        try:
            DISK_STAMP.write_text(str(now))
        except Exception:
            pass


def _load_symbols() -> list[str]:
    if not SYMS_FILE.exists():
        return []
    out = []
    for line in SYMS_FILE.read_text().splitlines():
        s = line.strip().upper()
        if s and not s.startswith("#"):
            out.append(s if s.endswith("USDT") else f"{s}USDT")
    return out


def _ensure_db() -> sqlite3.Connection:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS oi_snapshots (
            ts_utc TEXT NOT NULL,
            symbol TEXT NOT NULL,
            open_interest REAL,
            oi_notional_usd REAL,
            mark_price REAL,
            index_price REAL,
            last_funding_rate REAL,
            next_funding_time INTEGER,
            interest_rate REAL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_oi_sym_ts ON oi_snapshots(symbol, ts_utc)"
    )
    conn.commit()
    return conn


def collect() -> int:
    _disk_guard()
    symbols = _load_symbols()
    if not symbols:
        _alert("T3/ERROR collector: empty symbol list (t3_u30_symbols.txt missing?)")
        return 1
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # premium index for ALL symbols in one call -> map by symbol
    premium = {}
    try:
        for row in _get(f"{FAPI}/fapi/v1/premiumIndex"):
            premium[row.get("symbol")] = row
    except Exception:
        premium = {}

    conn = _ensure_db()
    rows, n_ok = [], 0
    for sym in symbols:
        try:
            oi = _get(f"{FAPI}/fapi/v1/openInterest?symbol={sym}")
            open_interest = float(oi.get("openInterest"))
        except Exception:
            open_interest = None
        p = premium.get(sym, {})
        mark = float(p["markPrice"]) if p.get("markPrice") is not None else None
        index = float(p["indexPrice"]) if p.get("indexPrice") is not None else None
        notional = (
            open_interest * mark
            if (open_interest is not None and mark is not None)
            else None
        )
        rows.append(
            (
                ts,
                sym,
                open_interest,
                notional,
                mark,
                index,
                float(p["lastFundingRate"])
                if p.get("lastFundingRate") is not None
                else None,
                int(p["nextFundingTime"])
                if p.get("nextFundingTime") is not None
                else None,
                float(p["interestRate"]) if p.get("interestRate") is not None else None,
            )
        )
        if open_interest is not None:
            n_ok += 1
        time.sleep(0.05)

    conn.executemany("INSERT INTO oi_snapshots VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    print(
        f"[{ts}] t3: wrote {len(rows)} rows ({n_ok} with OI) for {len(symbols)} symbols"
    )
    if n_ok == 0:
        _alert("T3/ERROR collector: 0 symbols returned OI this tick")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(collect())
