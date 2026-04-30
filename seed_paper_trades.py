"""
Seed data/paper_trades.db with realistic historical paper trades.
Run once to populate the Streamlit dashboard for demo/testing.

Usage:  python seed_paper_trades.py
"""

from execution.paper_trader import record_trade
import sqlite3
from pathlib import Path

DB = "data/paper_trades.db"

# Simulate past BTC trades (BULL_TREND period)
trades = [
    # symbol,   action, shares,    entry,    signal,        regime,       pnl
    ("BTC/USDT","BUY",  0.00132,  75100.0,  "BUY",         "BULL_TREND", 0.0),
    ("ETH/USDT","BUY",  0.445,    2180.0,   "BUY",         "BULL_TREND", 0.0),
    ("BTC/USDT","SELL", 0.00132,  76400.0,  "SELL",        "BEAR_TREND", round((76400-75100)*0.00132, 4)),
    ("ETH/USDT","SELL", 0.445,    2260.0,   "SELL",        "RANGE_BOUND",round((2260-2180)*0.445, 4)),
    ("BTC/USDT","BUY",  0.00130,  76800.0,  "BUY",         "BULL_TREND", 0.0),
    ("BTC/USDT","SELL", 0.00130,  75900.0,  "SELL",        "BEAR_TREND", round((75900-76800)*0.00130, 4)),
    ("ETH/USDT","BUY",  0.440,    2195.0,   "BUY",         "BULL_TREND", 0.0),
    ("ETH/USDT","SELL", 0.440,    2310.0,   "SELL",        "HIGH_VOLATILITY", round((2310-2195)*0.440, 4)),
]

for symbol, action, shares, price, signal, regime, pnl in trades:
    record_trade(
        db_path=DB, market="crypto", symbol=symbol,
        action=action, shares=shares, price=price,
        signal=signal, regime=regime, pnl=pnl,
    )

print(f"Seeded {len(trades)} paper trades into {DB}")
print("Open the Streamlit dashboard to see results.")
