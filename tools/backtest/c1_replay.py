"""tools/backtest/c1_replay.py — bar-by-bar replay of C1 stat_arb pairs.

Reuses C1's PURE-function components directly:
  _compute_spread_zscore, _engle_granger_pvalue, _rolling_correlation

Reimplements the entry/exit DRIVER (the parts that touch wall clock, file
system, and DB) so it can step through historical bars deterministically.

Mirrors `tools/backtest/c3_replay.py`'s shape. Architectural placement note:
the prompt called this file `backtests/c1_replay.py`, but the existing
convention (c3_replay, historical_data, run_b15_c3) lives under
`tools/backtest/`. Placed here for consistency with the existing harness.

Replay semantics:
  - 1H bars (matches stat_arb production resolution).
  - At each bar t, evaluate exits FIRST on currently-open position, then
    evaluate entry on the pair. Matches paper-mode's per-cycle order.
  - Fill price = bar t's close, optionally adjusted by slippage_bps PER LEG
    (a pair entry pays slip on long-leg buy AND short-leg sell; exit pays
    slip on both legs again — 4× slip impact per round-trip).
  - No fees in the base case (paper-mode also runs fee-free internally
    for the C1 strategy ledger; see execution/paper_trader.py).
  - One concurrent position per pair (matches live).

Scaffold scope (Phase 3): smoke run only. The health gate
(Engle-Granger p < 0.05 + corr_14d >= 0.80) is computed ONCE over the
full window and logged; if it fails, the replay aborts with an empty
trades list. Per-cycle health refresh (the live cadence is weekly) is
deferred to Phase 4 along with multi-regime breakdown + GO/NO-GO logic.

Output:
    replay_c1(...) -> dict with keys:
        trades        - list of {side, entry_idx, exit_idx, entry_z, exit_z,
                                 entry_price_a, exit_price_a,
                                 entry_price_b, exit_price_b,
                                 shares_a, shares_b, alloc, pnl_usd,
                                 exit_reason}
        final_capital - float, starting capital + sum(pnl_usd)
        starting_capital
        peak_capital
        max_drawdown_pct - peak-to-trough on the equity curve
        bars_evaluated
        health_gate   - {'eg_pvalue': float, 'corr_14d': float, 'healthy': bool}
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

from trading import stat_arb as c1  # noqa: E402

# Pure helpers we reuse directly:
_compute_zs = c1._compute_spread_zscore
_engle_granger_pvalue = c1._engle_granger_pvalue
_rolling_correlation = c1._rolling_correlation

# The BTC/ETH crypto pair from c1.PAIRS[0] is the only one with cached data.
# India pair (HDFCBANK/ICICIBANK) is dormant per locked doctrine.
CRYPTO_PAIR: c1.Pair = c1.PAIRS[0]


def _slice_until(df: pd.DataFrame, idx: int) -> pd.DataFrame:
    """Return df rows [0, idx] inclusive. idx is the current bar."""
    return df.iloc[: idx + 1]


def _check_pair_health(
    prices_a: pd.Series,
    prices_b: pd.Series,
    pair: c1.Pair,
    n_corr_bars: int,
) -> dict:
    """One-shot health gate over the full window. Returns dict with
    eg_pvalue, corr_14d, healthy. Mirrors stat_arb._run_pair's gate
    logic but computed once at replay start instead of refreshed
    weekly."""
    corr = _rolling_correlation(prices_a, prices_b, n_corr_bars)
    eg_p = _engle_granger_pvalue(prices_a, prices_b)
    healthy = (
        corr is not None
        and eg_p < pair.cointegration_p_max
        and corr >= pair.min_correlation_14d
    )
    return {
        "eg_pvalue": eg_p,
        "corr_14d": corr,
        "healthy": healthy,
    }


def replay_c1(
    bars_by_symbol: dict[str, pd.DataFrame],
    start_idx: int,
    end_idx: int,
    starting_capital: float = 100.0,
    slippage_bps: float = 0.0,
    pair: Optional[c1.Pair] = None,
) -> dict:
    """Replay C1 stat_arb over bars [start_idx, end_idx) for the given pair.

    All DataFrames in bars_by_symbol must share the same length and be
    aligned by bar index (i.e. bars_by_symbol[s].iloc[i] for any symbol s
    is the same wall-clock time). pair.long_sym + pair.short_sym must
    both be present.

    `slippage_bps` is applied symmetrically per leg: long-leg entry pays
    +slip on its buy price, short-leg entry pays -slip on its sell price,
    and exits reverse the direction. A 50bps run is the documented
    sensitivity check (matches c3_replay).
    """
    if pair is None:
        pair = CRYPTO_PAIR
    if pair.long_sym not in bars_by_symbol:
        raise ValueError(f"bars_by_symbol missing required {pair.long_sym}")
    if pair.short_sym not in bars_by_symbol:
        raise ValueError(f"bars_by_symbol missing required {pair.short_sym}")

    df_a = bars_by_symbol[pair.long_sym]
    df_b = bars_by_symbol[pair.short_sym]
    n_bars = min(len(df_a), len(df_b))
    end_idx = min(end_idx, n_bars)

    # Health gate (once, over the whole window). 14*24 hours of bars for
    # crypto per the production cadence in stat_arb._run_pair.
    n_corr = 14 * 24
    gate = _check_pair_health(df_a["close"], df_b["close"], pair, n_corr)
    if not gate["healthy"]:
        return {
            "trades": [],
            "starting_capital": float(starting_capital),
            "final_capital": float(starting_capital),
            "peak_capital": float(starting_capital),
            "max_drawdown_pct": 0.0,
            "bars_evaluated": 0,
            "health_gate": gate,
            "abort_reason": (
                f"health gate failed (eg_p={gate['eg_pvalue']:.4f} >= "
                f"{pair.cointegration_p_max} or corr_14d={gate['corr_14d']} < "
                f"{pair.min_correlation_14d})"
            ),
        }

    capital = float(starting_capital)
    peak = capital
    max_dd = 0.0
    position: dict | None = None
    trades: list[dict] = []

    for idx in range(start_idx, end_idx):
        prices_a = _slice_until(df_a["close"], idx)
        prices_b = _slice_until(df_b["close"], idx)
        _spread, z = _compute_zs(prices_a, prices_b, pair.window)
        price_a = float(df_a["close"].iloc[idx])
        price_b = float(df_b["close"].iloc[idx])

        # --- EXIT phase ---
        if position is not None:
            exit_reason: str | None = None
            if abs(z) < pair.exit_z:
                exit_reason = "CONVERGE"
            elif abs(z) >= pair.hard_stop_z:
                exit_reason = "HARD_STOP"
            else:
                age_bars = idx - position["entry_idx"]  # 1H bars => bars == hours
                if age_bars >= pair.time_stop_hours:
                    exit_reason = "TIME_STOP"

            if exit_reason:
                # Apply slippage per leg: exit reverses entry direction.
                # LONG_A exit = SELL long_sym + BUY short_sym → long pays
                # -slip on its sell, short pays +slip on its buy.
                slip_factor = slippage_bps / 10_000.0
                if position["side"] == "LONG_A":
                    fill_a = price_a * (1.0 - slip_factor)
                    fill_b = price_b * (1.0 + slip_factor)
                    pnl_a = (fill_a - position["entry_price_a"]) * position["shares_a"]
                    pnl_b = (position["entry_price_b"] - fill_b) * position["shares_b"]
                else:  # SHORT_A
                    fill_a = price_a * (1.0 + slip_factor)
                    fill_b = price_b * (1.0 - slip_factor)
                    pnl_a = (position["entry_price_a"] - fill_a) * position["shares_a"]
                    pnl_b = (fill_b - position["entry_price_b"]) * position["shares_b"]

                total_pnl = pnl_a + pnl_b
                # Capital returns: both legs of reserved alloc plus net pnl.
                capital += position["alloc"] * 2 + total_pnl
                trades.append(
                    {
                        "side": position["side"],
                        "entry_idx": position["entry_idx"],
                        "exit_idx": idx,
                        "entry_z": position["entry_z"],
                        "exit_z": z,
                        "entry_price_a": position["entry_price_a"],
                        "exit_price_a": fill_a,
                        "entry_price_b": position["entry_price_b"],
                        "exit_price_b": fill_b,
                        "shares_a": position["shares_a"],
                        "shares_b": position["shares_b"],
                        "alloc": position["alloc"],
                        "pnl_usd": total_pnl,
                        "exit_reason": exit_reason,
                    }
                )
                position = None

        # Equity curve + drawdown (mark-to-market with raw prices, no slip).
        if position is not None:
            if position["side"] == "LONG_A":
                unreal = (price_a - position["entry_price_a"]) * position[
                    "shares_a"
                ] + (position["entry_price_b"] - price_b) * position["shares_b"]
            else:
                unreal = (position["entry_price_a"] - price_a) * position[
                    "shares_a"
                ] + (price_b - position["entry_price_b"]) * position["shares_b"]
            equity = capital + position["alloc"] * 2 + unreal
        else:
            equity = capital
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd

        # --- ENTRY phase ---
        if position is None and abs(z) > pair.entry_z:
            alloc = capital * pair.alloc_pct
            if alloc * 2 > capital:
                continue  # insufficient capital — skip
            slip_factor = slippage_bps / 10_000.0
            # LONG_A means buy long_sym (pay +slip) + sell short_sym (pay -slip on receive).
            # SHORT_A inverts.
            if z < 0:
                side = "LONG_A"
                fill_a = price_a * (1.0 + slip_factor)
                fill_b = price_b * (1.0 - slip_factor)
            else:
                side = "SHORT_A"
                fill_a = price_a * (1.0 - slip_factor)
                fill_b = price_b * (1.0 + slip_factor)
            shares_a = alloc / max(fill_a, 1e-9)
            shares_b = alloc / max(fill_b, 1e-9)
            position = {
                "side": side,
                "shares_a": shares_a,
                "shares_b": shares_b,
                "entry_price_a": fill_a,
                "entry_price_b": fill_b,
                "entry_z": z,
                "entry_idx": idx,
                "alloc": alloc,
            }
            capital -= alloc * 2

    # Close any remaining position at the final bar (forced liquidation).
    if position is not None:
        idx = end_idx - 1
        price_a = float(df_a["close"].iloc[idx])
        price_b = float(df_b["close"].iloc[idx])
        prices_a = _slice_until(df_a["close"], idx)
        prices_b = _slice_until(df_b["close"], idx)
        _spread, z = _compute_zs(prices_a, prices_b, pair.window)
        slip_factor = slippage_bps / 10_000.0
        if position["side"] == "LONG_A":
            fill_a = price_a * (1.0 - slip_factor)
            fill_b = price_b * (1.0 + slip_factor)
            pnl_a = (fill_a - position["entry_price_a"]) * position["shares_a"]
            pnl_b = (position["entry_price_b"] - fill_b) * position["shares_b"]
        else:
            fill_a = price_a * (1.0 + slip_factor)
            fill_b = price_b * (1.0 - slip_factor)
            pnl_a = (position["entry_price_a"] - fill_a) * position["shares_a"]
            pnl_b = (fill_b - position["entry_price_b"]) * position["shares_b"]
        total_pnl = pnl_a + pnl_b
        capital += position["alloc"] * 2 + total_pnl
        trades.append(
            {
                "side": position["side"],
                "entry_idx": position["entry_idx"],
                "exit_idx": idx,
                "entry_z": position["entry_z"],
                "exit_z": z,
                "entry_price_a": position["entry_price_a"],
                "exit_price_a": fill_a,
                "entry_price_b": position["entry_price_b"],
                "exit_price_b": fill_b,
                "shares_a": position["shares_a"],
                "shares_b": position["shares_b"],
                "alloc": position["alloc"],
                "pnl_usd": total_pnl,
                "exit_reason": "end_of_window",
            }
        )

    return {
        "trades": trades,
        "starting_capital": float(starting_capital),
        "final_capital": float(capital),
        "peak_capital": float(peak),
        "max_drawdown_pct": float(max_dd),
        "bars_evaluated": int(end_idx - start_idx),
        "health_gate": gate,
    }


def summarize_trades(trades: list[dict], bars: int) -> dict:
    """Compute aggregate metrics from a trades list.

    Sharpe is annualized off per-trade returns, NOT a true time-series
    Sharpe (the replay is sparse — a few trades per month on average).
    We treat each trade as one return observation: mean(returns) /
    std(returns) * sqrt(approx-trades-per-year). C1 typically opens
    a few pair trades per month; annualization factor sqrt(60) matches
    c3_replay's convention. Conservative but comparable across runs.
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
    allocs = np.array([t["alloc"] for t in trades], dtype=float)
    # Per-trade pct against the two-leg notional (alloc * 2).
    pcts = pnls / np.where(allocs > 0, allocs * 2.0, 1.0)
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
        "profit_factor": float(gains_sum / losses_sum)
        if losses_sum > 0
        else float("inf"),
    }


def _smoke_main() -> int:
    """Smoke entrypoint. Loads BTC+ETH cached parquets, runs replay_c1,
    prints a one-line verdict mirroring c3_replay's output format."""
    from tools.backtest.historical_data import fetch_ohlcv

    pair = CRYPTO_PAIR
    end_ts = datetime(2026, 5, 23, 11, 0, 0, tzinfo=timezone.utc)
    print(f"== C1 stat_arb replay ({pair.long_sym}/{pair.short_sym}) ==")
    print(
        f"window={pair.window}h entry_z={pair.entry_z} exit_z={pair.exit_z} "
        f"hard_stop_z={pair.hard_stop_z} time_stop={pair.time_stop_hours}h "
        f"alloc_pct={pair.alloc_pct}"
    )

    bars = {}
    for sym in (pair.long_sym, pair.short_sym):
        df = fetch_ohlcv(sym, timeframe="1h", days_back=60, end_ts=end_ts)
        if df.empty:
            print(f"FAIL: no bars for {sym}")
            return 2
        bars[sym] = df.reset_index(drop=True)
        print(
            f"  {sym}: {len(df)} bars " f"[{df['ts'].iloc[0]} -> {df['ts'].iloc[-1]}]"
        )

    # Align on common timestamps (defensive — both should be 1440 already).
    common = set(bars[pair.long_sym]["ts"]) & set(bars[pair.short_sym]["ts"])
    for sym in (pair.long_sym, pair.short_sym):
        bars[sym] = (
            bars[sym][bars[sym]["ts"].isin(common)]
            .sort_values("ts")
            .reset_index(drop=True)
        )
    n_aligned = len(bars[pair.long_sym])
    print(f"  aligned: {n_aligned} common bars")

    # Warmup = max(window, 14*24) + 5 bars
    start_idx = max(pair.window, 14 * 24) + 5

    print("\n--- Headline run (slippage=0) ---")
    headline = replay_c1(
        bars,
        start_idx=start_idx,
        end_idx=n_aligned,
        starting_capital=100.0,
        slippage_bps=0.0,
        pair=pair,
    )
    if headline["trades"]:
        m = summarize_trades(headline["trades"], headline["bars_evaluated"])
    else:
        m = {
            "n_trades": 0,
            "pnl_usd": 0.0,
            "sharpe": 0.0,
            "win_rate": 0.0,
            "avg_pnl_pct": 0.0,
            "profit_factor": 0.0,
        }
    gate = headline["health_gate"]
    print(
        f"  health: eg_p={gate['eg_pvalue']:.4f} "
        f"corr_14d={gate['corr_14d'] if gate['corr_14d'] is not None else 'n/a'} "
        f"healthy={gate['healthy']}"
    )
    if "abort_reason" in headline:
        print(f"  ABORTED: {headline['abort_reason']}")
    else:
        print(
            f"  trades={m['n_trades']} pnl=${m['pnl_usd']:+.2f} "
            f"sharpe={m['sharpe']:+.3f} win_rate={m['win_rate']:.1%} "
            f"profit_factor={m['profit_factor']:.2f} "
            f"max_dd={headline['max_drawdown_pct']:.1%} "
            f"final_capital=${headline['final_capital']:.2f}"
        )

    print("\n--- 50bps slippage sensitivity ---")
    slip = replay_c1(
        bars,
        start_idx=start_idx,
        end_idx=n_aligned,
        starting_capital=100.0,
        slippage_bps=50.0,
        pair=pair,
    )
    if slip["trades"]:
        ms = summarize_trades(slip["trades"], slip["bars_evaluated"])
        print(
            f"  trades={ms['n_trades']} pnl=${ms['pnl_usd']:+.2f} "
            f"sharpe={ms['sharpe']:+.3f} win_rate={ms['win_rate']:.1%} "
            f"profit_factor={ms['profit_factor']:.2f} "
            f"max_dd={slip['max_drawdown_pct']:.1%}"
        )
    else:
        print(f"  (no trades — abort_reason={slip.get('abort_reason', 'none')})")

    print("\n--- VERDICT (one-line) ---")
    if headline.get("abort_reason"):
        print(f"C1 60d replay: ABORT — {headline['abort_reason']}")
    else:
        slip_pnl = (
            summarize_trades(slip["trades"], slip["bars_evaluated"])["pnl_usd"]
            if slip["trades"]
            else 0.0
        )
        print(
            f"C1 60d replay: {m['n_trades']} trades, ${m['pnl_usd']:+.2f} pnl "
            f"(zero-slip) / ${slip_pnl:+.2f} pnl (50bps), sharpe {m['sharpe']:+.2f}, "
            f"win-rate {m['win_rate']:.0%}, max_dd {headline['max_drawdown_pct']:.1%}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(_smoke_main())
