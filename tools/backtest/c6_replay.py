"""tools/backtest/c6_replay.py — bar-by-bar replay of C6 bollinger_range.

Reuses C6's PURE-function components directly:
  _rsi, _bollinger_pct_b, _volume_healthy

Reimplements the entry/exit DRIVER (the parts that touch wall clock,
file system, and DB) so it can step through historical bars deterministically.

Mirrors `tools/backtest/c3_replay.py` + `c1_replay.py` shape. Built in
Phase 3 (2026-05-27) for the C6 Sharpe-corroboration sanity check —
14d live rolling Sharpe of ~8.4 (post-sqrt-fix) needed 60d confirmation
before being treated as a real signal.

Replay semantics:
  - 1H bars (matches C6 production resolution).
  - At each bar t, evaluate exits FIRST on currently-open positions,
    then evaluate entries on the universe.
  - Fill price = bar t's close, optionally adjusted by slippage_bps.
  - No fees in the base case (paper-mode also runs fee-free internally
    for the C6 strategy ledger).
  - MAX_CONCURRENT = 2 positions across the universe (matches live).

Scaffold scope (Phase 3): smoke for Sharpe corroboration only. Two live
behaviors are simplified:
  - Regime gate (entry requires RANGE_BOUND): SKIPPED — replay treats
    every bar as RANGE_BOUND-eligible. Makes the replay PERMISSIVE
    relative to live; results are an upper bound. Same simplification
    as c3_replay's HMM-disable; documented at b15_backtest_harness.md
    "Known model gap" section.
  - Regime-flip exit (BULL/BEAR after age > 1h): SKIPPED for the same
    reason — no historical HMM state in the replay.

Output:
    replay_c6(...) -> dict with keys:
        trades        - list of {symbol, entry_idx, exit_idx, entry_price,
                                 exit_price, shares, size_usd, pnl_usd,
                                 entry_pct_b, entry_rsi, exit_pct_b,
                                 exit_reason}
        final_capital - float, starting capital + sum(pnl_usd)
        starting_capital
        peak_capital
        max_drawdown_pct
        bars_evaluated
"""

from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from trading import bollinger_range as c6  # noqa: E402

# Pure helpers we reuse directly:
_rsi = c6._rsi
_pct_b = c6._bollinger_pct_b
_volume_healthy = c6._volume_healthy

# Constants snapshot (in case strategy module mutates).
SYMBOLS = list(c6.SYMBOLS)
CAPITAL_PCT = c6.CAPITAL_PCT
MIN_TRADE_USD = c6.MIN_TRADE_USD
MAX_CONCURRENT = c6.MAX_CONCURRENT
BB_PERIOD = c6.BB_PERIOD
PCT_B_ENTRY = c6.PCT_B_ENTRY
PCT_B_TARGET = c6.PCT_B_TARGET
RSI_ENTRY = c6.RSI_ENTRY
RSI_PERIOD = c6.RSI_PERIOD
TAKE_PROFIT_PCT = c6.TAKE_PROFIT_PCT
HARD_STOP_PCT = c6.HARD_STOP_PCT
TIME_STOP_HOURS = c6.TIME_STOP_HOURS

# Warmup = max(BB_PERIOD, RSI_PERIOD + 1) + safety margin.
WARMUP_BARS = max(BB_PERIOD, RSI_PERIOD + 1) + 5


def _slice_until(df: pd.DataFrame, idx: int) -> pd.DataFrame:
    """Return df rows [0, idx] inclusive."""
    return df.iloc[: idx + 1]


def regime_proxy_range_bound(
    btc_closes: pd.Series,
    idx: int,
    bb_period: int = 20,
    bb_std: float = 2.0,
    history_window: int = 200,
    percentile_threshold: float = 0.5,
) -> bool:
    """Range-bound proxy: True if BTC's BBand width at bar ``idx`` is below
    the given percentile of the trailing ``history_window`` bars.

    Rationale: Bollinger band width compresses when prices oscillate in a
    tight range and expands when a directional move kicks in. Narrow
    bands = mean-reversion regime; wide bands = trend regime. This is a
    transparent stand-in for the live HMM regime classifier (which has no
    historical state we could replay against).

    Default percentile=0.5 keeps the bottom half of width observations as
    "range-bound" — roughly the share of time the HMM would label
    RANGE_BOUND in a balanced market.
    """
    closes = btc_closes.iloc[: idx + 1]
    if len(closes) < bb_period + 10:
        return True  # not enough data yet — be permissive
    rolling = closes.rolling(bb_period)
    mid = rolling.mean()
    std = rolling.std(ddof=0)
    # Width = (upper - lower) / mid, normalized by price.
    width = (2 * bb_std * std) / mid.clip(lower=1e-9)
    lookback = width.iloc[max(0, idx - history_window) : idx + 1].dropna()
    if len(lookback) < 20:
        return True
    threshold = lookback.quantile(percentile_threshold)
    width_now = float(width.iloc[idx])
    if pd.isna(width_now):
        return True
    return width_now < threshold


def replay_c6(
    bars_by_symbol: dict[str, pd.DataFrame],
    start_idx: int,
    end_idx: int,
    starting_capital: float = 100.0,
    slippage_bps: float = 0.0,
    symbols: Optional[list[str]] = None,
    regime_check: Optional[callable] = None,
) -> dict:
    """Replay C6 bollinger_range over bars [start_idx, end_idx) for the
    given symbols (default: SYMBOLS = BTC/USDT, ETH/USDT, SOL/USDT).

    All DataFrames must share the same length and be aligned by bar index
    (i.e. bars_by_symbol[s].iloc[i] for any symbol s is the same wall-clock
    time).
    """
    if symbols is None:
        symbols = list(SYMBOLS)
    missing = [s for s in symbols if s not in bars_by_symbol]
    if missing:
        raise ValueError(f"bars_by_symbol missing required symbols: {missing}")

    n_bars = min(len(bars_by_symbol[s]) for s in symbols)
    end_idx = min(end_idx, n_bars)

    capital = float(starting_capital)
    peak = capital
    max_dd = 0.0
    positions: dict[str, dict] = {}
    trades: list[dict] = []

    for idx in range(start_idx, end_idx):
        # --- EXIT phase ---
        to_close: list[tuple[str, dict, float, float, str]] = []
        for sym, pos in positions.items():
            df = bars_by_symbol[sym]
            closes = _slice_until(df["close"], idx)
            pct_b_now, _mid, _std = _pct_b(closes, BB_PERIOD, c6.BB_STD)
            price = float(df["close"].iloc[idx])

            # Mark-to-market pnl_pct (raw price, no slip yet — slip applied on fill).
            pnl_pct = (price - pos["entry_price"]) / pos["entry_price"]
            age_bars = idx - pos["entry_idx"]  # 1H bars => bars == hours

            exit_reason: str | None = None
            if pct_b_now >= PCT_B_TARGET:
                exit_reason = "pct_b_target"
            elif pnl_pct >= TAKE_PROFIT_PCT:
                exit_reason = "take_profit"
            elif pnl_pct <= HARD_STOP_PCT:
                exit_reason = "hard_stop"
            elif age_bars >= TIME_STOP_HOURS:
                exit_reason = f"time_stop_{TIME_STOP_HOURS}h"

            if exit_reason:
                slip_factor = slippage_bps / 10_000.0
                fill = price * (1.0 - slip_factor)  # SELL pays -slip
                to_close.append((sym, pos, fill, pct_b_now, exit_reason))

        for sym, pos, fill, exit_pct_b, reason in to_close:
            pnl = pos["shares"] * (fill - pos["entry_price"])
            capital += pos["size_usd"] + pnl
            trades.append(
                {
                    "symbol": sym,
                    "entry_idx": pos["entry_idx"],
                    "exit_idx": idx,
                    "entry_price": pos["entry_price"],
                    "exit_price": fill,
                    "shares": pos["shares"],
                    "size_usd": pos["size_usd"],
                    "pnl_usd": pnl,
                    "entry_pct_b": pos["entry_pct_b"],
                    "entry_rsi": pos["entry_rsi"],
                    "exit_pct_b": exit_pct_b,
                    "exit_reason": reason,
                }
            )
            del positions[sym]

        # Equity curve + drawdown (mark-to-market on raw prices).
        unreal = 0.0
        for sym, pos in positions.items():
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
        if len(positions) >= MAX_CONCURRENT:
            continue
        # Regime gate (optional). Live runner only enters when the HMM
        # classifies the global regime as RANGE_BOUND; replay can pass a
        # callable like regime_proxy_range_bound to approximate this.
        if regime_check is not None and not regime_check(idx):
            continue
        for sym in symbols:
            if sym in positions:
                continue
            if len(positions) >= MAX_CONCURRENT:
                break
            df = bars_by_symbol[sym]
            if idx < BB_PERIOD:
                continue
            closes = _slice_until(df["close"], idx)
            df_until = _slice_until(df, idx)

            pct_b_now, _mid, _std = _pct_b(closes, BB_PERIOD, c6.BB_STD)
            rsi_now = _rsi(closes, RSI_PERIOD)
            if pct_b_now >= PCT_B_ENTRY:
                continue  # not oversold
            if rsi_now >= RSI_ENTRY:
                continue
            if not _volume_healthy(df_until):
                continue

            size_usd = capital * CAPITAL_PCT
            if size_usd < MIN_TRADE_USD:
                continue
            if size_usd > capital:
                continue

            price = float(df["close"].iloc[idx])
            slip_factor = slippage_bps / 10_000.0
            fill = price * (1.0 + slip_factor)  # BUY pays +slip
            shares = size_usd / fill
            positions[sym] = {
                "entry_idx": idx,
                "entry_price": fill,
                "size_usd": size_usd,
                "shares": shares,
                "entry_pct_b": pct_b_now,
                "entry_rsi": rsi_now,
            }
            capital -= size_usd

    # Forced liquidation at final bar.
    final_idx = end_idx - 1
    for sym in list(positions.keys()):
        pos = positions[sym]
        price = float(bars_by_symbol[sym]["close"].iloc[final_idx])
        slip_factor = slippage_bps / 10_000.0
        fill = price * (1.0 - slip_factor)
        pnl = pos["shares"] * (fill - pos["entry_price"])
        capital += pos["size_usd"] + pnl
        closes = _slice_until(bars_by_symbol[sym]["close"], final_idx)
        pct_b_now, _, _ = _pct_b(closes, BB_PERIOD, c6.BB_STD)
        trades.append(
            {
                "symbol": sym,
                "entry_idx": pos["entry_idx"],
                "exit_idx": final_idx,
                "entry_price": pos["entry_price"],
                "exit_price": fill,
                "shares": pos["shares"],
                "size_usd": pos["size_usd"],
                "pnl_usd": pnl,
                "entry_pct_b": pos["entry_pct_b"],
                "entry_rsi": pos["entry_rsi"],
                "exit_pct_b": pct_b_now,
                "exit_reason": "end_of_window",
            }
        )
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
    """Per-trade Sharpe with sqrt(60) annualization, matching c3_replay
    + c1_replay convention. Conservative but comparable across strategies.
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
        "profit_factor": (
            float(gains_sum / losses_sum) if losses_sum > 0 else float("inf")
        ),
    }


def _smoke_main() -> int:
    """Smoke entrypoint. Loads BTC+ETH+SOL parquets, runs replay_c6,
    prints one-line verdict for the C6 Sharpe sanity check."""
    from tools.backtest.historical_data import fetch_ohlcv

    end_ts = datetime(2026, 5, 23, 11, 0, 0, tzinfo=timezone.utc)
    print("== C6 bollinger_range replay (BTC/USDT, ETH/USDT, SOL/USDT) ==")
    print(
        f"BB({BB_PERIOD},{c6.BB_STD}) RSI({RSI_PERIOD}) "
        f"pct_b_entry<{PCT_B_ENTRY} rsi_entry<{RSI_ENTRY} "
        f"target={PCT_B_TARGET} tp={TAKE_PROFIT_PCT:+.1%} "
        f"stop={HARD_STOP_PCT:+.1%} time_stop={TIME_STOP_HOURS}h "
        f"alloc_pct={CAPITAL_PCT} max_concurrent={MAX_CONCURRENT}"
    )

    bars = {}
    for sym in SYMBOLS:
        df = fetch_ohlcv(sym, timeframe="1h", days_back=60, end_ts=end_ts)
        if df.empty:
            print(f"FAIL: no bars for {sym}")
            return 2
        bars[sym] = df.reset_index(drop=True)
        print(f"  {sym}: {len(df)} bars")

    # Align on common timestamps.
    common = set.intersection(*(set(bars[s]["ts"]) for s in SYMBOLS))
    for sym in SYMBOLS:
        bars[sym] = (
            bars[sym][bars[sym]["ts"].isin(common)]
            .sort_values("ts")
            .reset_index(drop=True)
        )
    n_aligned = len(bars[SYMBOLS[0]])
    print(f"  aligned: {n_aligned} common bars")

    start_idx = WARMUP_BARS
    print(f"  start_idx={start_idx}  bars_evaluated={n_aligned - start_idx}")

    print("\n--- Headline run (slippage=0, NO regime gate, permissive) ---")
    headline = replay_c6(bars, start_idx, n_aligned, 100.0, 0.0)
    m = summarize_trades(headline["trades"], headline["bars_evaluated"])
    print(
        f"  trades={m['n_trades']} pnl=${m['pnl_usd']:+.2f} "
        f"sharpe={m['sharpe']:+.3f} win_rate={m['win_rate']:.1%} "
        f"profit_factor={m['profit_factor']:.2f} "
        f"max_dd={headline['max_drawdown_pct']:.1%} "
        f"final_capital=${headline['final_capital']:.2f}"
    )

    print("\n--- 50bps slippage sensitivity (NO regime gate) ---")
    slip = replay_c6(bars, start_idx, n_aligned, 100.0, 50.0)
    ms = summarize_trades(slip["trades"], slip["bars_evaluated"])
    print(
        f"  trades={ms['n_trades']} pnl=${ms['pnl_usd']:+.2f} "
        f"sharpe={ms['sharpe']:+.3f} win_rate={ms['win_rate']:.1%} "
        f"profit_factor={ms['profit_factor']:.2f} "
        f"max_dd={slip['max_drawdown_pct']:.1%}"
    )

    # Regime-gated runs using BTC BBand-width proxy (HMM-RANGE_BOUND stand-in).
    btc_closes = bars["BTC/USDT"]["close"]

    def _regime_gate(idx: int) -> bool:
        return regime_proxy_range_bound(btc_closes, idx)

    print("\n--- Regime-gated run (slippage=0, BTC BBand-width <50th pct) ---")
    gated = replay_c6(bars, start_idx, n_aligned, 100.0, 0.0, regime_check=_regime_gate)
    mg = summarize_trades(gated["trades"], gated["bars_evaluated"])
    print(
        f"  trades={mg['n_trades']} pnl=${mg['pnl_usd']:+.2f} "
        f"sharpe={mg['sharpe']:+.3f} win_rate={mg['win_rate']:.1%} "
        f"profit_factor={mg['profit_factor']:.2f} "
        f"max_dd={gated['max_drawdown_pct']:.1%} "
        f"final_capital=${gated['final_capital']:.2f}"
    )

    print("\n--- Regime-gated 50bps slippage ---")
    gated_slip = replay_c6(
        bars, start_idx, n_aligned, 100.0, 50.0, regime_check=_regime_gate
    )
    mgs = summarize_trades(gated_slip["trades"], gated_slip["bars_evaluated"])
    print(
        f"  trades={mgs['n_trades']} pnl=${mgs['pnl_usd']:+.2f} "
        f"sharpe={mgs['sharpe']:+.3f} win_rate={mgs['win_rate']:.1%} "
        f"profit_factor={mgs['profit_factor']:.2f} "
        f"max_dd={gated_slip['max_drawdown_pct']:.1%}"
    )

    print("\n--- VERDICT (one-line, regime-gated = closest to live) ---")
    print(
        f"C6 60d replay: PERMISSIVE {m['n_trades']} trades sharpe {m['sharpe']:+.2f}; "
        f"REGIME-GATED {mg['n_trades']} trades pnl ${mg['pnl_usd']:+.2f}, "
        f"sharpe {mg['sharpe']:+.2f}, win-rate {mg['win_rate']:.0%}; "
        f"50bps regime-gated pnl ${mgs['pnl_usd']:+.2f}, sharpe {mgs['sharpe']:+.2f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(_smoke_main())
