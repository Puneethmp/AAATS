"""
Paper Trading Loop for AAATS.

Simulates 24/7 autonomous trading using live market data feeds with
paper (simulated) order execution. All trades are logged to SQLite.

Architecture:
  - Market data tick → Feature engineer → Regime detector → Strategy signal
  - Signal → Risk Engine check → Paper order execution → SQLite log
  - Every cycle: update portfolio metrics, check kill switches

The loop is market-agnostic: the same loop drives US, India, and Crypto
sessions with different data sources and strategies per market.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from foundation.logger import get_logger
from monitoring.heartbeat_monitor import emit_heartbeat
from monitoring.realtime_state_manager import MarketState, PositionSnapshot, publish_state
from risk.engine import RiskDecision, RiskEngine

_log = get_logger("trading", "paper_loop")

_CREATE_TRADES_SQL = """
CREATE TABLE IF NOT EXISTS paper_trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    market      TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    action      TEXT NOT NULL,
    shares      INTEGER NOT NULL,
    price       REAL NOT NULL,
    value       REAL NOT NULL,
    signal      TEXT NOT NULL,
    regime      TEXT,
    risk_action TEXT NOT NULL,
    pnl         REAL,
    note        TEXT
)
"""

_INSERT_TRADE_SQL = """
INSERT INTO paper_trades
    (timestamp, market, symbol, action, shares, price, value,
     signal, regime, risk_action, pnl, note)
VALUES
    (:timestamp, :market, :symbol, :action, :shares, :price, :value,
     :signal, :regime, :risk_action, :pnl, :note)
"""


@dataclass
class Position:
    symbol: str
    market: str
    shares: int
    entry_price: float
    entry_time: str

    @property
    def current_pnl(self) -> float:
        return 0.0  # Updated by the loop with current price


@dataclass
class PaperTradingState:
    """Mutable state for the paper trading session."""
    capital: dict[str, float] = field(default_factory=lambda: {
        "us": 0.0, "india": 0.0, "crypto": 0.0
    })
    positions: dict[str, list[Position]] = field(default_factory=lambda: {
        "us": [], "india": [], "crypto": []
    })
    trade_count: int = 0
    session_start: str = field(default_factory=lambda: _now_iso())
    cycle_count: int = 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute(_CREATE_TRADES_SQL)
    conn.commit()
    return conn


def _log_trade(
    conn: sqlite3.Connection,
    *,
    market: str,
    symbol: str,
    action: str,
    shares: int,
    price: float,
    signal: str,
    regime: str | None,
    risk_action: str,
    pnl: float | None = None,
    note: str | None = None,
) -> None:
    row = {
        "timestamp": _now_iso(),
        "market": market,
        "symbol": symbol,
        "action": action,
        "shares": shares,
        "price": price,
        "value": price * shares,
        "signal": signal,
        "regime": regime,
        "risk_action": risk_action,
        "pnl": pnl,
        "note": note,
    }
    conn.execute(_INSERT_TRADE_SQL, row)
    conn.commit()


def process_signal(
    market: str,
    symbol: str,
    signal: str,
    price: float,
    shares: int,
    regime: str | None,
    risk_engine: RiskEngine,
    state: PaperTradingState,
    conn: sqlite3.Connection,
    capital: float,
) -> RiskDecision:
    """
    Process a single strategy signal through the risk engine and log to DB.

    Args:
        market:      Market name ("us", "india", "crypto").
        symbol:      Symbol being traded.
        signal:      "BUY", "SELL", or "HOLD".
        price:       Current price.
        shares:      Proposed share count.
        regime:      Current market regime string (or None).
        risk_engine: Active RiskEngine instance.
        state:       Mutable paper trading state.
        conn:        Open SQLite connection.
        capital:     Current capital for this market.

    Returns:
        RiskDecision from the risk engine.
    """
    if signal == "HOLD":
        return RiskDecision(action="ALLOW", reason="HOLD signal — no action", market=market)

    if signal == "BUY":
        decision = risk_engine.check_new_order(market, price, shares, capital)
        actual_shares = shares if decision.action == "ALLOW" else int(shares * decision.allowed_fraction)

        _log_trade(
            conn,
            market=market,
            symbol=symbol,
            action="BUY",
            shares=actual_shares,
            price=price,
            signal=signal,
            regime=regime,
            risk_action=decision.action,
            note=decision.reason,
        )

        if decision.action in ("ALLOW", "REDUCE") and actual_shares > 0:
            state.positions[market].append(
                Position(
                    symbol=symbol,
                    market=market,
                    shares=actual_shares,
                    entry_price=price,
                    entry_time=_now_iso(),
                )
            )
            state.trade_count += 1
            _log.info(f"PAPER BUY: {actual_shares}x {symbol} @ {price:.2f} [{market}]")

        return decision

    if signal == "SELL":
        # Close all positions for this symbol
        closed_positions = [p for p in state.positions[market] if p.symbol == symbol]
        state.positions[market] = [p for p in state.positions[market] if p.symbol != symbol]

        for pos in closed_positions:
            pnl = (price - pos.entry_price) * pos.shares
            _log_trade(
                conn,
                market=market,
                symbol=symbol,
                action="SELL",
                shares=pos.shares,
                price=price,
                signal=signal,
                regime=regime,
                risk_action="ALLOW",
                pnl=pnl,
                note=f"Closed from entry {pos.entry_price:.2f}",
            )
            state.trade_count += 1
            _log.info(
                f"PAPER SELL: {pos.shares}x {symbol} @ {price:.2f}, "
                f"PnL={pnl:+.2f} [{market}]"
            )

        return RiskDecision(action="ALLOW", reason="SELL processed", market=market)

    return RiskDecision(action="ALLOW", reason=f"Unknown signal: {signal}", market=market)


def fetch_paper_trades(db_path: str, market: str | None = None) -> pd.DataFrame:
    """
    Load paper trading history from SQLite.

    Args:
        db_path: Path to the trades SQLite file.
        market:  Optional market filter ("us", "india", "crypto").

    Returns:
        DataFrame of all matching trades, ordered by timestamp descending.
        Empty DataFrame if no trades exist yet.
    """
    if not Path(db_path).exists():
        return pd.DataFrame()

    conn = sqlite3.connect(db_path)
    try:
        query = "SELECT * FROM paper_trades"
        params: tuple = ()
        if market:
            query += " WHERE market = ?"
            params = (market,)
        query += " ORDER BY timestamp DESC"

        df = pd.read_sql_query(query, conn, params=params)
        return df
    except Exception:
        _log.exception("fetch_paper_trades failed")
        return pd.DataFrame()
    finally:
        conn.close()


def get_paper_summary(db_path: str) -> dict[str, Any]:
    """
    Return summary statistics for the paper trading session.

    Returns:
        Dict with total_trades, total_pnl, win_rate, markets breakdown.
    """
    df = fetch_paper_trades(db_path)
    if df.empty:
        return {"total_trades": 0, "total_pnl": 0.0, "win_rate": 0.0}

    sells = df[df["action"] == "SELL"]
    total_pnl = sells["pnl"].sum() if not sells.empty else 0.0
    win_rate = (sells["pnl"] > 0).mean() if not sells.empty else 0.0

    return {
        "total_trades": len(df),
        "total_pnl": float(total_pnl),
        "win_rate": float(win_rate),
        "markets": df["market"].value_counts().to_dict(),
    }


def emit_cycle_heartbeat(
    market: str,
    cycle_count: int,
    status: str = "RUNNING",
    error: str = "",
) -> None:
    """
    Emit a heartbeat for the current trading cycle.
    
    Should be called at the start/end of each trading cycle to signal
    that the backend is alive and processing.
    
    Args:
        market: Market identifier (us, india, crypto)
        cycle_count: Current cycle number
        status: Status string (RUNNING, IDLE, HALTED, ERROR, MARKET_CLOSED)
        error: Error message if status is ERROR
    """
    emit_heartbeat(market, status, cycle_count, error, min_interval_seconds=15.0)


def publish_cycle_state(
    market: str,
    regime: str,
    positions: list[Position],
    capital: float,
    cycle_count: int,
    total_pnl: float = 0.0,
    daily_pnl: float = 0.0,
    active_signals: list[str] | None = None,
) -> None:
    """
    Publish real-time state for the current trading cycle.
    
    Should be called after each cycle to update the dashboard with
    current portfolio state.
    
    Args:
        market: Market identifier
        regime: Current market regime
        positions: List of open positions
        capital: Current cash balance
        cycle_count: Current cycle number
        total_pnl: Total realized PnL
        daily_pnl: Today's PnL
        active_signals: List of active strategy signals
    """
    # Convert positions to snapshots
    position_snapshots = [
        PositionSnapshot(
            symbol=pos.symbol,
            shares=float(pos.shares),
            entry_price=pos.entry_price,
            current_price=pos.entry_price,  # Updated by caller with real price
            unrealized_pnl=0.0,  # Updated by caller
            entry_time=pos.entry_time,
        )
        for pos in positions
    ]
    
    # Calculate portfolio value
    portfolio_value = capital + sum(
        pos.shares * pos.entry_price for pos in positions
    )
    
    # Create market state
    state = MarketState(
        market=market,
        timestamp=_now_iso(),
        regime=regime,
        portfolio_value=portfolio_value,
        cash=capital,
        positions=position_snapshots,
        active_signals=active_signals or [],
        cycle_count=cycle_count,
        total_pnl=total_pnl,
        daily_pnl=daily_pnl,
        open_position_count=len(positions),
    )
    
    # Publish state (rate-limited to every 5 seconds)
    publish_state(state, min_interval_seconds=5.0)


# ── Docker / CLI entry point ───────────────────────────────────────────────────
# docker-compose calls: python trading/paper_loop.py --market crypto
# This delegates directly to live_paper_runner.main() which owns the loop logic.

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="AAATS paper trading entry point (delegates to live_paper_runner)"
    )
    ap.add_argument(
        "--market",
        default="crypto",
        choices=["crypto", "india", "both"],
        help="Market(s) to run  [default: crypto]",
    )
    args = ap.parse_args()

    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    from trading.live_paper_runner import main as _runner_main
    _runner_main(market=args.market)
