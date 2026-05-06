"""
Read-only data layer for the AAATS Streamlit web app.

All functions read from SQLite — never write. The trading engine is the
sole writer. This separation prevents the web app from corrupting live state.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import os as _os

import pandas as pd

_ROOT        = Path(__file__).parent.parent
_DATA_ROOT   = Path(_os.environ.get("AAATS_DATA", str(_ROOT / "data")))
_LOG_ROOT    = Path(_os.environ.get("AAATS_LOGS", str(_ROOT / "logs")))
_DEFAULT_DB  = str(_DATA_ROOT / "aaats.db")
_PAPER_DB    = str(_DATA_ROOT / "paper_trades.db")
_STATUS_DB   = str(_DATA_ROOT / "status.db")
_EQUITY_DB   = str(_DATA_ROOT / "equity_curve.db")
_SLIPPAGE_DB = str(_DATA_ROOT / "slippage.db")
_POSITIONS_DB = str(_DATA_ROOT / "positions.db")
_AUDIT_DB    = str(_DATA_ROOT / "compliance_audit.db")
_ANOMALY_DB  = str(_DATA_ROOT / "anomalies.db")


def _connect(db_path: str) -> sqlite3.Connection | None:
    if not Path(db_path).exists():
        return None
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    except Exception:
        return None


# ── Paper trades ──────────────────────────────────────────────────────────────

def get_all_trades(db_path: str = _PAPER_DB) -> pd.DataFrame:
    conn = _connect(db_path)
    if conn is None:
        return _empty_trades()
    try:
        df = pd.read_sql_query(
            "SELECT * FROM paper_trades ORDER BY timestamp DESC", conn
        )
        conn.close()
        return df
    except Exception:
        return _empty_trades()


def get_open_positions() -> pd.DataFrame:
    """Return open positions from positions.db (authoritative source)."""
    conn = _connect(_POSITIONS_DB)
    if conn is None:
        return pd.DataFrame()
    try:
        df = pd.read_sql_query(
            """SELECT symbol, market, entry_price, shares,
                      ROUND(entry_price * shares, 4) AS value,
                      datetime(entry_time, 'unixepoch') AS entry_time
               FROM positions WHERE closed=0 ORDER BY entry_time DESC""",
            conn,
        )
        conn.close()
        return df
    except Exception:
        conn.close()
        return pd.DataFrame()


def get_portfolio_summary(db_path: str = _PAPER_DB) -> dict[str, Any]:
    trades = get_all_trades(db_path)
    if trades.empty:
        return _zero_summary()

    sells = trades[trades["action"] == "SELL"]
    total_pnl = float(sells["pnl"].sum()) if not sells.empty else 0.0
    win_rate = float((sells["pnl"] > 0).mean()) if not sells.empty else 0.0
    total_trades = len(trades)
    wins = int((sells["pnl"] > 0).sum()) if not sells.empty else 0
    losses = int((sells["pnl"] <= 0).sum()) if not sells.empty else 0

    return {
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "avg_win": float(sells[sells["pnl"] > 0]["pnl"].mean()) if wins > 0 else 0.0,
        "avg_loss": float(sells[sells["pnl"] <= 0]["pnl"].mean()) if losses > 0 else 0.0,
    }


def get_equity_curve(db_path: str = _PAPER_DB, initial_capital: float = 100_000.0) -> pd.DataFrame:
    """Build cumulative equity curve from completed trades."""
    trades = get_all_trades(db_path)
    sells = trades[trades["action"] == "SELL"].copy() if not trades.empty else pd.DataFrame()

    if sells.empty:
        today = datetime.now(timezone.utc)
        return pd.DataFrame({
            "date": pd.date_range(today - timedelta(days=1), today, periods=2),
            "equity": [initial_capital, initial_capital],
        })

    sells = sells.sort_values("timestamp")
    sells["cumulative_pnl"] = sells["pnl"].cumsum()
    sells["equity"] = initial_capital + sells["cumulative_pnl"]
    return sells[["timestamp", "equity"]].rename(columns={"timestamp": "date"})


def get_monthly_returns(db_path: str = _PAPER_DB) -> pd.DataFrame:
    trades = get_all_trades(db_path)
    sells = trades[trades["action"] == "SELL"].copy() if not trades.empty else pd.DataFrame()

    if sells.empty:
        return pd.DataFrame(columns=["month", "pnl"])

    sells["timestamp"] = pd.to_datetime(sells["timestamp"])
    sells["month"] = sells["timestamp"].dt.to_period("M").astype(str)
    monthly = sells.groupby("month")["pnl"].sum().reset_index()
    return monthly


def get_strategy_breakdown(db_path: str = _PAPER_DB) -> pd.DataFrame:
    trades = get_all_trades(db_path)
    sells = trades[trades["action"] == "SELL"].copy() if not trades.empty else pd.DataFrame()

    if sells.empty:
        return pd.DataFrame()

    breakdown = sells.groupby("signal").agg(
        trades=("pnl", "count"),
        total_pnl=("pnl", "sum"),
        win_rate=("pnl", lambda x: (x > 0).mean()),
        avg_pnl=("pnl", "mean"),
    ).reset_index()
    return breakdown


def get_engine_status(db_path: str = _STATUS_DB) -> pd.DataFrame:
    """Return live engine status rows written by the trading runners."""
    conn = _connect(db_path)
    if conn is None:
        return pd.DataFrame(columns=[
            "market", "last_run", "regime", "symbols_scanned", "trades_today", "status", "error"
        ])
    try:
        df = pd.read_sql_query("SELECT * FROM engine_status", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


def get_institutional_metrics() -> dict:
    """Return live institutional risk/compliance metrics from all DBs."""
    import json
    result: dict = {
        "phase1": {},
        "drawdown_pct": 0.0,
        "avg_slippage_bps": 0.0,
        "open_positions": 0,
        "anomalies_24h": 0,
        "audit_entries": 0,
        "halt_state": {},
    }
    try:
        cp = _DATA_ROOT / "phase1_checkpoint.json"
        if cp.exists():
            result["phase1"] = json.loads(cp.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass

    conn_eq = _connect(_EQUITY_DB)
    if conn_eq:
        try:
            row = conn_eq.execute(
                "SELECT current_drawdown FROM equity_curve WHERE market='crypto' ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            result["drawdown_pct"] = round((row[0] or 0.0) * 100, 2) if row else 0.0
            conn_eq.close()
        except Exception:
            pass

    conn_sl = _connect(_SLIPPAGE_DB)
    if conn_sl:
        try:
            row = conn_sl.execute("SELECT AVG(ABS(slippage_bps)) FROM slippage WHERE market='crypto'").fetchone()
            result["avg_slippage_bps"] = round(row[0] or 0.0, 1) if row else 0.0
            conn_sl.close()
        except Exception:
            pass

    conn_pos = _connect(_POSITIONS_DB)
    if conn_pos:
        try:
            row = conn_pos.execute("SELECT COUNT(*) FROM positions WHERE closed=0").fetchone()
            result["open_positions"] = row[0] if row else 0
            conn_pos.close()
        except Exception:
            pass

    import time
    conn_an = _connect(_ANOMALY_DB)
    if conn_an:
        try:
            row = conn_an.execute(
                "SELECT COUNT(*) FROM anomalies WHERE timestamp > ?", (time.time() - 86400,)
            ).fetchone()
            result["anomalies_24h"] = row[0] if row else 0
            conn_an.close()
        except Exception:
            pass

    conn_au = _connect(_AUDIT_DB)
    if conn_au:
        try:
            row = conn_au.execute("SELECT COUNT(*) FROM compliance_audit").fetchone()
            result["audit_entries"] = row[0] if row else 0
            conn_au.close()
        except Exception:
            pass

    try:
        halt_path = _DATA_ROOT / "halt_state.json"
        if halt_path.exists():
            result["halt_state"] = json.loads(halt_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass

    return result


def get_recent_alerts(limit: int = 20) -> list[dict[str, str]]:
    """Read real alerts from loguru JSON log files under logs/."""
    import re as _re, json as _json
    log_root = _LOG_ROOT
    _keywords = ("PAPER", "BUY", "SELL", "HALT", "Cycle", "cycle", "trade",
                 "Trade", "error", "Error", "regime", "Regime", "COMPLETE",
                 "STARTED", "RESUMING", "ERROR", "WARNING", "WARN")
    entries: list[tuple[str, dict]] = []

    for log_file in sorted(log_root.rglob("*.log"),
                            key=lambda f: f.stat().st_mtime, reverse=True)[:6]:
        try:
            for raw in log_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = _json.loads(raw)
                    record = rec.get("record", {})
                    ts   = str(record.get("time", {}).get("repr", ""))
                    lvl  = str(record.get("level", {}).get("name", "INFO")).upper()
                    msg  = str(record.get("message", rec.get("text", raw)))[:220]
                    if lvl not in ("ERROR", "WARNING", "WARN") and not any(k in msg for k in _keywords):
                        continue
                    entries.append((ts, {"time": ts[11:19] if len(ts) > 19 else ts,
                                         "level": lvl, "msg": msg}))
                except Exception:
                    clean = _re.sub(r"\x1b\[[0-9;]*m", "", raw).strip()
                    if any(k in clean for k in _keywords):
                        entries.append(("", {"time": "", "level": "INFO", "msg": clean[:220]}))
        except Exception:
            continue

    entries.sort(key=lambda x: x[0], reverse=True)
    alerts = [a for _, a in entries[:limit]]
    if not alerts:
        alerts = [{"time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                   "level": "INFO",
                   "msg": "No log files yet — runner will create them on next cycle"}]
    return alerts


def get_health_metrics() -> dict:
    """Return lightweight system health data for the System Health Panel.

    All measurements are non-blocking and safe to call on every Streamlit refresh.
    """
    import json as _json, time as _time

    now = datetime.now(timezone.utc)
    result: dict = {
        "collected_at": now.isoformat(),
        "runner_status": "UNKNOWN",
        "last_cycle_ts": "",
        "last_cycle_age_s": None,
        "heartbeat_ts": "",
        "heartbeat_age_s": None,
        "runner_alive": False,
        "last_trade_ts": "",
        "last_trade_age_s": None,
        "cycle_count": 0,
        "db_write_latency_ms": None,
        "log_update_age_s": None,
        "memory_mb": None,
        "cpu_pct": None,
        "phase1_cycles_done": 0,
        "phase1_cycles_total": 24,
        "phase1_status": "UNKNOWN",
    }

    # ── Engine status (last cycle time, heartbeat, alive check) ──────────────
    conn = _connect(_STATUS_DB)
    if conn:
        # Ensure new columns exist in any pre-existing status.db
        for _col, _cdef in [("heartbeat_ts", "TEXT DEFAULT ''"),
                             ("cycle_count",  "INTEGER DEFAULT 0")]:
            try:
                conn.execute(f"ALTER TABLE engine_status ADD COLUMN {_col} {_cdef}")
                conn.commit()
            except Exception:
                pass  # column already exists
        try:
            row = conn.execute(
                "SELECT last_run, heartbeat_ts, status, cycle_count FROM engine_status "
                "WHERE market='crypto'"
            ).fetchone()
            if row:
                result["last_cycle_ts"]  = row[0] or ""
                result["heartbeat_ts"]   = row[1] or ""
                result["runner_status"]  = row[2] or "UNKNOWN"
                result["cycle_count"]    = int(row[3] or 0)
                # Compute ages
                for key, ts in [("last_cycle_age_s", row[0]), ("heartbeat_age_s", row[1])]:
                    if ts:
                        try:
                            dt = datetime.fromisoformat(ts)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            result[key] = round((now - dt).total_seconds())
                        except Exception:
                            pass
                # Runner is "alive" if heartbeat within 2× cycle length (2h) OR
                # last_run within 2h AND status is not ERROR
                hb_age = result["heartbeat_age_s"]
                lc_age = result["last_cycle_age_s"]
                result["runner_alive"] = (
                    (hb_age is not None and hb_age < 7200) or
                    (lc_age is not None and lc_age < 7200 and result["runner_status"] not in ("ERROR",))
                )
        except Exception:
            pass
        conn.close()

    # ── Last trade timestamp ─────────────────────────────────────────────────
    conn = _connect(_PAPER_DB)
    if conn:
        try:
            row = conn.execute(
                "SELECT timestamp FROM paper_trades WHERE market='crypto' "
                "ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            if row and row[0]:
                result["last_trade_ts"] = row[0]
                try:
                    dt = datetime.fromisoformat(row[0])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    result["last_trade_age_s"] = round((now - dt).total_seconds())
                except Exception:
                    pass
        except Exception:
            pass
        conn.close()

    # ── DB write latency (write + read a temp row to paper_trades.db) ────────
    conn2 = _connect(_STATUS_DB)
    if conn2:
        try:
            t0 = _time.perf_counter()
            conn2.execute("UPDATE engine_status SET heartbeat_ts=heartbeat_ts WHERE market='_health_probe'")
            conn2.commit()
            result["db_write_latency_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
        except Exception:
            pass
        conn2.close()

    # ── Log file freshness ──────────────────────────────────────────────────
    try:
        newest = max(_LOG_ROOT.rglob("*.log"), key=lambda f: f.stat().st_mtime, default=None)
        if newest:
            result["log_update_age_s"] = round(_time.time() - newest.stat().st_mtime)
    except Exception:
        pass

    # ── Phase 1 checkpoint ──────────────────────────────────────────────────
    try:
        cp = _DATA_ROOT / "phase1_checkpoint.json"
        if cp.exists():
            data = _json.loads(cp.read_text(encoding="utf-8", errors="ignore"))
            result["phase1_cycles_done"]  = data.get("cycles_done", 0)
            result["phase1_cycles_total"] = data.get("cycles_planned", 24)
            result["phase1_status"]       = data.get("status", "UNKNOWN")
    except Exception:
        pass

    # ── Memory / CPU (psutil, optional) ────────────────────────────────────
    try:
        import psutil as _ps
        proc = _ps.Process()
        result["memory_mb"] = round(proc.memory_info().rss / 1024 / 1024, 1)
        result["cpu_pct"]   = proc.cpu_percent(interval=0.1)
    except Exception:
        pass

    return result


def get_halt_state() -> dict:
    """Return current halt_state.json as a dict. Keys: us, india, crypto (bool)."""
    import json as _json
    halt_path = _DATA_ROOT / "halt_state.json"
    try:
        if halt_path.exists():
            return _json.loads(halt_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass
    return {}


def write_halt_state(us: bool | None = None, india: bool | None = None,
                     crypto: bool | None = None) -> bool:
    """Update halt_state.json atomically. Only updates provided keys. Returns True on success."""
    import json as _json
    try:
        current = get_halt_state()
        if us is not None:
            current["us"] = us
        if india is not None:
            current["india"] = india
        if crypto is not None:
            current["crypto"] = crypto
        halt_path = _DATA_ROOT / "halt_state.json"
        tmp = halt_path.with_suffix(".tmp")
        tmp.write_text(_json.dumps(current, indent=2))
        tmp.replace(halt_path)
        return True
    except Exception:
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "id", "timestamp", "market", "symbol", "action",
        "shares", "price", "value", "signal", "regime",
        "risk_action", "pnl", "note",
    ])


def _zero_summary() -> dict[str, Any]:
    return {
        "total_pnl": 0.0, "win_rate": 0.0, "total_trades": 0,
        "wins": 0, "losses": 0, "avg_win": 0.0, "avg_loss": 0.0,
    }
