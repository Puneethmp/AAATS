"""tools/backtest/c3_replay.py - bar-by-bar replay of C3 altcoin reversion.

Reuses C3's PURE-function components directly:
  _compute_z_score, _rsi, _realized_daily_vol, _compute_trade_size

Reimplements the entry/exit DRIVER (the parts that touch wall clock, file
system, and DB) so it can step through historical bars deterministically.

Replay semantics:
  - 1H bars (matches C3 production resolution).
  - At each bar t, evaluate exits FIRST on currently-open positions, then
    evaluate entries on the universe. This matches paper-mode's per-cycle
    order: exits processed before entries.
  - Fill price = bar t's close, optionally adjusted by slippage_bps.
  - No fees in the base case (paper-mode also runs fee-free internally
    for the C3 strategy ledger; see execution/paper_trader.py).
  - Cooldown is in-memory: symbol -> bar_idx_until.

Output:
    replay_c3(...) -> dict with keys:
        trades        - list of {symbol, entry_idx, exit_idx, entry_price,
                                 exit_price, shares, size_usd, pnl_usd,
                                 entry_z, exit_z, max_z, exit_reason}
        final_capital - float, starting capital + sum(pnl_usd)
        starting_capital
        peak_capital
        max_drawdown_pct - peak-to-trough on the equity curve
        bars_evaluated
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from trading import altcoin_reversion as c3

# Pure helpers we reuse directly:
_compute_z = c3._compute_z_score
_rsi = c3._rsi
_realized_vol = c3._realized_daily_vol
_compute_trade_size = c3._compute_trade_size

# Constants we replay against (snapshot in case strategy module mutates):
Z_ENTRY = c3.Z_ENTRY
Z_HARD_STOP = c3.Z_HARD_STOP
Z_TRAILING_MIN = c3.Z_TRAILING_MIN
Z_TRAILING_DROP = c3.Z_TRAILING_DROP
Z_TARGET = c3.Z_TARGET
LOOKBACK_BARS = c3.LOOKBACK_BARS
TIME_STOP_HOURS = c3.TIME_STOP_HOURS
BTC_RSI_MIN = c3.BTC_RSI_MIN
COOLDOWN_HOURS = c3.COOLDOWN_HOURS
DENYLIST_SYMBOLS = c3.DENYLIST_SYMBOLS
BTC_SYMBOL = c3.BTC_SYMBOL
MAX_CONCURRENT = c3.MAX_CONCURRENT


def _slice_until(df: pd.DataFrame, idx: int) -> pd.DataFrame:
    """Return df rows [0, idx] inclusive. idx is the current bar."""
    return df.iloc[: idx + 1]


def replay_c3(
    bars_by_symbol: dict[str, pd.DataFrame],
    start_idx: int,
    end_idx: int,
    starting_capital: float = 100.0,
    slippage_bps: float = 0.0,
    universe: Optional[list[str]] = None,
) -> dict:
    """Replay C3 over bars [start_idx, end_idx) for each symbol in `universe`.

    All DataFrames in bars_by_symbol must share the same length and be
    aligned by bar index (i.e. bars_by_symbol[s].iloc[i] for any symbol s
    is the same wall-clock time). BTC_SYMBOL must be present.

    `slippage_bps` is applied symmetrically: entry pays +slippage, exit
    pays -slippage. Setting >0 makes the result less favourable to the
    strategy; the 50 bps run is the documented sensitivity check.
    """
    if BTC_SYMBOL not in bars_by_symbol:
        raise ValueError(f"bars_by_symbol missing required {BTC_SYMBOL}")
    if universe is None:
        universe = list(c3.SYMBOLS)

    capital = float(starting_capital)
    peak = capital
    max_dd = 0.0
    positions: dict[str, dict] = {}
    cooldown: dict[str, int] = {}
    trades: list[dict] = []

    btc_df = bars_by_symbol[BTC_SYMBOL]
    n_bars = min(len(btc_df), min(len(bars_by_symbol[s]) for s in universe if s in bars_by_symbol))
    end_idx = min(end_idx, n_bars)

    for idx in range(start_idx, end_idx):
        # --- EXIT phase ---
        to_close: list[tuple[str, dict, float, str]] = []  # (symbol, pos, fill, reason)
        for sym, pos in positions.items():
            if sym not in bars_by_symbol:
                continue
            alt_df = _slice_until(bars_by_symbol[sym], idx)
            b_df = _slice_until(btc_df, idx)
            z = _compute_z(alt_df, b_df, lookback=LOOKBACK_BARS)
            if z is None:
                continue
            # Track max_z
            if z > pos["max_z"]:
                pos["max_z"] = z

            age_h = idx - pos["entry_idx"]  # 1H bars => bars == hours
            exit_reason = None
            if z >= Z_TARGET:
                exit_reason = "z_overshoot"
            elif pos["max_z"] >= Z_TRAILING_MIN and (pos["max_z"] - z) >= Z_TRAILING_DROP:
                exit_reason = "z_trailing"
            elif z <= Z_HARD_STOP:
                exit_reason = "z_hard_stop"
            elif age_h >= TIME_STOP_HOURS:
                exit_reason = f"time_stop_{TIME_STOP_HOURS}h"

            if exit_reason:
                bar_close = float(alt_df["close"].iloc[-1])
                fill = bar_close * (1.0 - slippage_bps / 10_000.0)
                to_close.append((sym, pos, fill, exit_reason))

        for sym, pos, fill, reason in to_close:
            pnl = pos["shares"] * (fill - pos["entry_price"])
            capital += pos["size_usd"] + pnl  # reserved capital returns + pnl
            trades.append({
                "symbol": sym,
                "entry_idx": pos["entry_idx"],
                "exit_idx": idx,
                "entry_price": pos["entry_price"],
                "exit_price": fill,
                "shares": pos["shares"],
                "size_usd": pos["size_usd"],
                "pnl_usd": pnl,
                "entry_z": pos["entry_z"],
                "exit_z": pos.get("last_z"),
                "max_z": pos["max_z"],
                "exit_reason": reason,
            })
            # Loss-stop -> cooldown
            if reason in ("z_hard_stop", f"time_stop_{TIME_STOP_HOURS}h") and pnl < 0:
                cooldown[sym] = idx + COOLDOWN_HOURS
            del positions[sym]

        # Capital high-water + drawdown tracking
        # Use cash + mark-to-market unrealized for equity curve.
        unreal = 0.0
        for sym, pos in positions.items():
            if sym in bars_by_symbol:
                mark = float(bars_by_symbol[sym]["close"].iloc[idx])
                unreal += pos["shares"] * (mark - pos["entry_price"])
        equity = capital + sum(p["size_usd"] for p in positions.values()) + unreal
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd

        # --- ENTRY phase ---
        btc_slice = _slice_until(btc_df, idx)
        if len(btc_slice) < 20:  # not enough bars for RSI
            continue
        btc_rsi = _rsi(btc_slice["close"], period=14)
        if btc_rsi < BTC_RSI_MIN:
            continue  # macro guard

        for sym in universe:
            if sym in positions:
                continue
            if sym in DENYLIST_SYMBOLS:
                continue
            if sym in cooldown and cooldown[sym] > idx:
                continue
            if len(positions) >= MAX_CONCURRENT:
                break
            if sym not in bars_by_symbol:
                continue

            alt_df = _slice_until(bars_by_symbol[sym], idx)
            if len(alt_df) < LOOKBACK_BARS + 5:
                continue
            z = _compute_z(alt_df, btc_slice, lookback=LOOKBACK_BARS)
            if z is None or z >= Z_ENTRY:
                continue  # not cheap enough

            symbol_vol = _realized_vol(alt_df)
            size_usd, reason = _compute_trade_size(capital, len(positions), symbol_vol)
            if size_usd <= 0.0:
                continue

            bar_close = float(alt_df["close"].iloc[-1])
            fill = bar_close * (1.0 + slippage_bps / 10_000.0)
            shares = size_usd / fill
            positions[sym] = {
                "entry_idx": idx,
                "entry_price": fill,
                "size_usd": size_usd,
                "shares": shares,
                "entry_z": z,
                "max_z": z,
                "last_z": z,
            }
            capital -= size_usd

    # Close any remaining positions at the final bar (forced liquidation).
    final_idx = end_idx - 1
    for sym in list(positions.keys()):
        pos = positions[sym]
        if sym not in bars_by_symbol:
            continue
        bar_close = float(bars_by_symbol[sym]["close"].iloc[final_idx])
        fill = bar_close * (1.0 - slippage_bps / 10_000.0)
        pnl = pos["shares"] * (fill - pos["entry_price"])
        capital += pos["size_usd"] + pnl
        trades.append({
            "symbol": sym,
            "entry_idx": pos["entry_idx"],
            "exit_idx": final_idx,
            "entry_price": pos["entry_price"],
            "exit_price": fill,
            "shares": pos["shares"],
            "size_usd": pos["size_usd"],
            "pnl_usd": pnl,
            "entry_z": pos["entry_z"],
            "exit_z": None,
            "max_z": pos["max_z"],
            "exit_reason": "end_of_window",
        })
        del positions[sym]

    return {
        "trades": trades,
        "starting_capital": float(starting_capital),
        "final_capital": float(capital),
        "peak_capital": float(peak),
        "max_drawdown_pct": float(max_dd),
        "bars_evaluated": int(end_idx - start_idx),
    }


def summarize_trades(trades: list[dict], bars: int) -> dict:
    """Compute aggregate metrics from a trades list.

    Sharpe is annualized off per-trade returns, NOT a true time-series
    Sharpe (the replay is sparse — a few trades per week on average). We
    treat each trade as one return observation: mean(returns) / std(returns)
    * sqrt(approx-trades-per-year). With ~5 trades/month per the C3
    docstring, annualization factor = sqrt(60). Conservative but
    comparable across runs.
    """
    if not trades:
        return {
            "n_trades": 0,
            "pnl_usd": 0.0,
            "win_rate": 0.0,
            "sharpe": 0.0,
            "avg_pnl_pct": 0.0,
            "profit_factor": 0.0,
        }
    pnls = np.array([t["pnl_usd"] for t in trades], dtype=float)
    sizes = np.array([t["size_usd"] for t in trades], dtype=float)
    pcts = pnls / np.where(sizes > 0, sizes, 1.0)
    wins = (pnls > 0).sum()
    losses_sum = -pnls[pnls < 0].sum()
    gains_sum = pnls[pnls > 0].sum()
    if pcts.std(ddof=1) > 1e-9 and len(pcts) >= 2:
        sharpe = float(pcts.mean() / pcts.std(ddof=1) * np.sqrt(60.0))
    else:
        sharpe = 0.0
    return {
        "n_trades": int(len(trades)),
        "pnl_usd": float(pnls.sum()),
        "win_rate": float(wins / len(trades)),
        "sharpe": sharpe,
        "avg_pnl_pct": float(pcts.mean()),
        "profit_factor": float(gains_sum / losses_sum) if losses_sum > 0 else float("inf"),
    }
