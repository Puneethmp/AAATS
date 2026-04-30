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

import pandas as pd

_ROOT        = Path(__file__).parent.parent
_DEFAULT_DB  = str(_ROOT / "data" / "aaats.db")
_PAPER_DB    = str(_ROOT / "data" / "paper_trades.db")
_STATUS_DB   = str(_ROOT / "data" / "status.db")
_EQUITY_DB   = str(_ROOT / "data" / "equity_curve.db")
_SLIPPAGE_DB = str(_ROOT / "data" / "slippage.db")
_POSITIONS_DB = str(_ROOT / "data" / "positions.db")
_AUDIT_DB    = str(_ROOT / "data" / "compliance_audit.db")
_ANOMALY_DB  = str(_ROOT / "data" / "anomalies.db")


def _connect(db_path: str) -> sqlite3.Connection | None:
    if not Path(db_path).exists():
        return None
    try:
        return sqlite3.connect(db_path, check_same_thread=False)
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


def get_open_positions(db_path: str = _PAPER_DB) -> pd.DataFrame:
    """Return currently open positions (BUY with no matching SELL after)."""
    trades = get_all_trades(db_path)
    if trades.empty:
        return pd.DataFrame()

    buys = trades[trades["action"] == "BUY"].copy()
    sells = trades[trades["action"] == "SELL"]["symbol"].tolist()
    # Simple heuristic: open if symbol has more buys than sells
    open_pos = []
    for symbol in buys["symbol"].unique():
        sym_buys = buys[buys["symbol"] == symbol]
        sym_sell_count = sells.count(symbol)
        remaining = len(sym_buys) - sym_sell_count
        if remaining > 0:
            last_buy = sym_buys.iloc[0]
            open_pos.append({
                "symbol": symbol,
                "market": last_buy.get("market", ""),
                "shares": last_buy.get("shares", 0),
                "entry_price": last_buy.get("price", 0),
                "entry_time": last_buy.get("timestamp", ""),
                "signal": last_buy.get("signal", ""),
                "regime": last_buy.get("regime", ""),
            })
    return pd.DataFrame(open_pos) if open_pos else pd.DataFrame()


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
        cp = Path(_ROOT / "data" / "phase1_checkpoint.json")
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
        halt_path = Path(_ROOT / "data" / "halt_state.json")
        if halt_path.exists():
            result["halt_state"] = json.loads(halt_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass

    return result


def get_recent_alerts(limit: int = 20) -> list[dict[str, str]]:
    """Return simulated/logged alerts. Real alerts come from Telegram + kill switch."""
    return [
        {"time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
         "level": "INFO", "msg": "System healthy — paper trading active"},
        {"time": (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%H:%M:%S"),
         "level": "INFO", "msg": "Regime check: US=BULL_TREND, India=RANGE_BOUND, Crypto=RANGE_BOUND"},
    ]


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
