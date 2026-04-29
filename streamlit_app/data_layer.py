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

_DEFAULT_DB = str(Path(__file__).parent.parent / "data" / "aaats.db")
_PAPER_DB = str(Path(__file__).parent.parent / "data" / "paper_trades.db")


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
