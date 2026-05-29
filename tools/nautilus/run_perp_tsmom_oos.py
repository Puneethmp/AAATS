"""Perp-native time-series momentum (TSMOM) — graduation trial (B.1.7 Track F).

Track 11 closed the C3-class entry-gate program; C7 funding-arb is fee-bound on
any asset (closed analytically 2026-05-30). This is the perp-only directional
candidate the operator chose (EDGE-FIRST, Option B): a long/short time-series
momentum strategy on USDT-M perps — NO spot leg, so it sidesteps C7's structural
20bps spot-taker killer. Being long/short on perps is genuinely perp-native (you
can hold the downtrend short, which a spot-only book cannot).

Signal (ONE a-priori parameterization, NOT swept):
  - lookback L = 336h (14d). Picked from the data's trend-persistence structure
    by tools/backtest/measure_perp_trend_persistence.py, measured on the CURRENT
    window's IN-SAMPLE portion ONLY (no peeking at either test partition). At
    daily cadence the perp universe is mean-reverting at most horizons; 14d is
    the one horizon with positive momentum persistence (pred_coef +0.0021, 55.5%
    hit). If momentum fails the gate, that weak-and-isolated persistence is the
    mechanistic explanation.
  - position = sign( close[t]/close[t-L] - 1 ), re-evaluated every 24h (daily
    rebalance). Pure sign => no tunable threshold (vol-normalising the signal
    wouldn't change a sign rule). +1 long / -1 short / 0 flat (only if trail==0).
  - $NOTIONAL per symbol, fixed. Up to 6 concurrent => <=0.9x gross on $100.

Economics matched to the C3-perp/C7 NT harness family so the graduation numbers
are apples-to-apples: Binance perp VIP-0 fees (taker 5bps / maker 2bps), fills at
bar close with zero slippage (identical to those harnesses' FillModel), real
Binance funding applied every 8h settlement a position is open across. Funding on
a perp position: long PAYS when rate>0, short RECEIVES when rate>0, i.e.
funding_pnl = -sign * notional * rate per settlement.

This is a DIRECT, fully-auditable backtest (not the NT BacktestEngine) because
TSMOM is a market-order daily-rebalance rule whose fills are unambiguous at bar
close — there is no limit-fill probability to model, so the NT engine would add
machinery without changing the economics. G7 (maker robustness) is approximated
by re-running with the 2bps maker fee; for a trend-chaser maker fills are if
anything LESS attainable than taker, so this is a generous lower-fee bound, not a
hidden optimism. Difference from the NT harnesses is documented, not silent.

Per-trade ledger: one round-trip (a sign flip closes the old position and opens
the new) == one trade. PnL_net = price PnL +/- fees(entry+exit) + funding accrued
while held. Positions still open at window end are EXCLUDED (consistent with the
C3-perp/C7 harnesses). Verdicts -> data/graduation/Perp_TSMOM_{window}_<today>.json.

    python tools/nautilus/run_perp_tsmom_oos.py
"""

# ruff: noqa: E402  — sys.path bootstrap (below) must precede repo-local imports
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.graduation.gate import evaluate_gate, emit_report

HIST = ROOT / "data" / "historical"
UNIVERSE = ["BTC", "ETH", "SOL", "LINK", "AVAX", "DOT"]
START_CAPITAL = 100.0

# --- a-priori parameters (frozen; see measure_perp_trend_persistence.py) ---
LOOKBACK_H = 336  # 14d — strongest positive trend-persistence horizon (in-sample)
REBAL_H = 24  # daily rebalance
NOTIONAL = 15.0  # $ per symbol per position (<=0.9x gross on $100 across 6 syms)
FEE_TAKER = 0.0005  # Binance perp VIP-0 taker
FEE_MAKER = 0.0002  # Binance perp VIP-0 maker (G7 lower-fee bound)

# 6mo window split: first ~4mo in-sample, last ~2mo OOS — same cutoffs as the
# C3-perp harness so the comparison is apples-to-apples.
WINDOWS = {
    "current": {"suffix": "", "oos_cutoff": pd.Timestamp("2026-03-28", tz="UTC")},
    "earlier": {
        "suffix": "_earlier",
        "oos_cutoff": pd.Timestamp("2025-03-28", tz="UTC"),
    },
}


def _load_closes(sym: str, suffix: str) -> pd.Series:
    df = pd.read_parquet(HIST / f"{sym}_USDT_1h_perp{suffix}.parquet")
    df.columns = [c.lower() for c in df.columns]
    df.index = pd.to_datetime(df["ts"], utc=True)
    return df["close"].astype(float).sort_index()


def _load_funding_on_grid(sym: str, suffix: str, grid: pd.DatetimeIndex) -> np.ndarray:
    """Funding rate aligned to the hourly bar grid (0 where no 8h settlement)."""
    f = HIST / f"{sym}_USDT_funding{suffix}.parquet"
    if not f.exists():
        return np.zeros(len(grid))
    df = pd.read_parquet(f)
    s = (
        df.set_index(pd.to_datetime(df["ts_funding"], utc=True))["funding_rate"]
        .astype(float)
        .sort_index()
    )
    return s.reindex(grid).fillna(0.0).to_numpy()


def _sharpe(rets: np.ndarray) -> float:
    if len(rets) < 2 or rets.std(ddof=1) <= 1e-12:
        return 0.0
    # sqrt(60) per-trade annualisation — identical convention to the C3/C7 family.
    return float(rets.mean() / rets.std(ddof=1) * np.sqrt(60.0))


def _backtest(window: str, fee: float):
    """Direct TSMOM backtest for one window at a given per-trade fee rate.

    Returns (trades, decomposition) where each trade is one closed round-trip.
    """
    suffix = WINDOWS[window]["suffix"]
    closes = {s: _load_closes(s, suffix) for s in UNIVERSE}
    # common hourly grid across all symbols
    grid = closes[UNIVERSE[0]].index
    for s in UNIVERSE[1:]:
        grid = grid.intersection(closes[s].index)
    grid = grid.sort_values()
    px = {s: closes[s].reindex(grid).to_numpy() for s in UNIVERSE}
    fund = {s: _load_funding_on_grid(s, suffix, grid) for s in UNIVERSE}
    n = len(grid)

    pos = {s: None for s in UNIVERSE}  # open position meta or None
    trades = []
    tot_price_gross = tot_funding = tot_fees = 0.0
    n_funding_events = 0

    for t in range(n):
        ts = grid[t]
        # ---- funding accrual to any open position (per 8h settlement at this bar)
        for s in UNIVERSE:
            p = pos[s]
            if p is None:
                continue
            rate = fund[s][t]
            if rate != 0.0:
                # long pays when rate>0, short receives when rate>0
                contrib = -p["sign"] * p["qty"] * p["entry_px"] * float(rate)
                p["funding"] += contrib
                n_funding_events += 1
        # ---- daily rebalance
        if t >= LOOKBACK_H and t % REBAL_H == 0:
            for s in UNIVERSE:
                trail = px[s][t] / px[s][t - LOOKBACK_H] - 1.0
                target = int(np.sign(trail))  # +1 / -1 / 0
                p = pos[s]
                cur_sign = p["sign"] if p is not None else 0
                if target == cur_sign:
                    continue  # hold — no trade, no fee
                # close current position (if any)
                if p is not None:
                    exit_px = px[s][t]
                    price_pnl = p["sign"] * (exit_px - p["entry_px"]) * p["qty"]
                    exit_fee = fee * p["qty"] * exit_px
                    pnl_net = price_pnl + p["funding"] - p["entry_fee"] - exit_fee
                    trades.append(
                        {
                            "sym": s,
                            "pnl_net": pnl_net,
                            "funding": p["funding"],
                            "fees": p["entry_fee"] + exit_fee,
                            "price_gross": price_pnl,
                            "notional": NOTIONAL,
                            "ts": int(ts.value),
                            "hold_h": t - p["entry_idx"],
                            "sign": p["sign"],
                        }
                    )
                    tot_price_gross += price_pnl
                    tot_funding += p["funding"]
                    tot_fees += p["entry_fee"] + exit_fee
                    pos[s] = None
                # open new position (if not flat)
                if target != 0:
                    entry_px = px[s][t]
                    qty = NOTIONAL / entry_px
                    entry_fee = fee * qty * entry_px
                    pos[s] = {
                        "sign": target,
                        "entry_px": entry_px,
                        "qty": qty,
                        "entry_fee": entry_fee,
                        "funding": 0.0,
                        "entry_idx": t,
                    }
    decomp = {
        "price_gross_usd": round(tot_price_gross, 4),
        "funding_total_usd": round(tot_funding, 4),
        "fees_total_usd": round(tot_fees, 4),
        "n_funding_events": n_funding_events,
        "n_open_at_end": sum(1 for p in pos.values() if p is not None),
    }
    return trades, decomp


def _metrics(trades, oos_cutoff):
    rows = sorted(trades, key=lambda r: r["ts"])
    if not rows:
        return None
    pnls = np.array([r["pnl_net"] for r in rows])
    rets = np.array([r["pnl_net"] / r["notional"] for r in rows])
    gains = pnls[pnls > 0].sum()
    losses = -pnls[pnls < 0].sum()
    equity = START_CAPITAL + np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    max_dd = float(np.max((peak - equity) / peak)) if len(equity) else 0.0
    cut = int(oos_cutoff.value)
    is_rows = [r for r in rows if r["ts"] < cut]
    oos_rows = [r for r in rows if r["ts"] >= cut]

    def _sh_pnl(sub):
        if not sub:
            return 0.0, 0.0
        r = np.array([x["pnl_net"] / x["notional"] for x in sub])
        return round(_sharpe(r), 4), round(float(sum(x["pnl_net"] for x in sub)), 4)

    is_sharpe, is_pnl = _sh_pnl(is_rows)
    oos_sharpe, oos_pnl = _sh_pnl(oos_rows)
    return {
        "net_pnl_usd": round(float(pnls.sum()), 4),
        "n_trades": int(len(rows)),
        "win_rate": round(float((pnls > 0).mean()), 4),
        "profit_factor": round(float(gains / losses), 4)
        if losses > 0
        else float("inf"),
        "full_sharpe": round(_sharpe(rets), 4),
        "in_sample_sharpe": is_sharpe,
        "oos_sharpe": oos_sharpe,
        "max_drawdown_pct": round(max_dd, 4),
        "is_pnl": is_pnl,
        "oos_pnl": oos_pnl,
        "n_long": int(sum(1 for r in rows if r["sign"] > 0)),
        "n_short": int(sum(1 for r in rows if r["sign"] < 0)),
        "avg_hold_h": round(float(np.mean([r["hold_h"] for r in rows])), 1),
    }


def evaluate(window: str, emit: bool = True):
    """Run TSMOM (taker + maker) for one window and score the graduation gate."""
    taker_trades, decomp = _backtest(window, FEE_TAKER)
    maker_trades, _ = _backtest(window, FEE_MAKER)
    oos_cutoff = WINDOWS[window]["oos_cutoff"]
    mt = _metrics(taker_trades, oos_cutoff)
    mm = _metrics(maker_trades, oos_cutoff)
    if mt is None:
        mt = {"net_pnl_usd": 0.0, "n_trades": 0}
    metrics = {
        "net_pnl_usd": mt["net_pnl_usd"],
        "sharpe": mt.get("oos_sharpe", 0.0),  # gate G2 reads OOS Sharpe
        "max_drawdown_pct": mt.get("max_drawdown_pct", 0.0),
        "n_trades": mt["n_trades"],
        "profit_factor": mt.get("profit_factor", 0.0),
        "in_sample_sharpe": mt.get("in_sample_sharpe", 0.0),
        "oos_sharpe": mt.get("oos_sharpe", 0.0),
        "pnl_at_maker_0_5": mm["net_pnl_usd"] if mm else 0.0,
        # --- decomposition / context (not gate inputs) ---
        "price_gross_usd": decomp["price_gross_usd"],
        "funding_total_usd": decomp["funding_total_usd"],
        "fees_total_usd": decomp["fees_total_usd"],
        "funding_events_count": decomp["n_funding_events"],
        "n_open_at_end": decomp["n_open_at_end"],
        "_full_sharpe": mt.get("full_sharpe", 0.0),
        "_win_rate": mt.get("win_rate", 0.0),
        "_is_pnl_usd": mt.get("is_pnl", 0.0),
        "_oos_pnl_usd": mt.get("oos_pnl", 0.0),
        "_n_long": mt.get("n_long", 0),
        "_n_short": mt.get("n_short", 0),
        "_avg_hold_h": mt.get("avg_hold_h", 0.0),
        "_params": (
            f"LOOKBACK_H={LOOKBACK_H} REBAL_H={REBAL_H} NOTIONAL={NOTIONAL} "
            f"taker={FEE_TAKER} maker={FEE_MAKER} (sign-only, no threshold, not swept)"
        ),
        "_data": "REAL Binance USDT-M perp 1h klines + funding (fetch_perp_data.py)",
        "_method": "direct market-order daily-rebalance backtest, fills at bar close, "
        "0 slippage; G7 = maker-fee rerun (generous lower-fee bound for a trend-chaser)",
        "_window": (
            "current 2025-11-28..2026-05-27 (OOS>=2026-03-28); "
            "earlier 2024-11-28..2025-05-27 (OOS>=2025-03-28)"
        ),
    }
    result = evaluate_gate(metrics)
    path = (
        emit_report(
            f"Perp_TSMOM_{window}",
            metrics,
            result,
            out_dir=str(ROOT / "data" / "graduation"),
        )
        if emit
        else None
    )
    return metrics, result, path


def main():
    rows = []
    reports = {}
    results = {}
    for window in ("current", "earlier"):
        m, r, path = evaluate(window, emit=True)
        results[window] = (m, r)
        reports[window] = path
        rows.append((window, m, r))

    print("\n===== PERP TSMOM (14d sign, daily rebal, long/short) — DUAL WINDOW =====")
    print(
        f"{'window':<9}|{'n_tr':>5}|{'L/S':>9}|{'net':>9}|{'oosShrp':>8}|"
        f"{'PF':>6}|{'maxDD':>7}|{'mkr_pnl':>9}| verdict"
    )
    print("-" * 78)
    for window, m, r in rows:
        print(
            f"{window:<9}|{m['n_trades']:>5}|{m['_n_long']:>4}/{m['_n_short']:<4}|"
            f"{m['net_pnl_usd']:>+9.2f}|{m['oos_sharpe']:>8.2f}|"
            f"{m['profit_factor']:>6.2f}|{m['max_drawdown_pct']:>7.3f}|"
            f"{m['pnl_at_maker_0_5']:>+9.2f}| {'PASS' if r.passed else 'FAIL'}"
        )

    print("\n--- PnL DECOMPOSITION (taker) ---")
    for window, m, r in rows:
        print(
            f"{window}: price_gross {m['price_gross_usd']:+.3f} + funding "
            f"{m['funding_total_usd']:+.3f} - fees {m['fees_total_usd']:.3f} "
            f"-> net {m['net_pnl_usd']:+.3f} | WR {m['_win_rate']:.1%} "
            f"avg_hold {m['_avg_hold_h']}h funding_events {m['funding_events_count']}"
        )

    print("\n--- PER-CRITERION G1..G7 ---")
    for window, m, r in rows:
        print(f"[{window}] {'PASS' if r.passed else 'FAIL'}")
        for g in sorted(r.criteria):
            c = r.criteria[g]
            print(f"   [{'ok' if c['passed'] else 'XX'}] {g}: {c['detail']}")

    cur_pass = results["current"][1].passed
    earl_pass = results["earlier"][1].passed
    print("\nreports:")
    for w in ("current", "earlier"):
        print(f"  {reports[w]}")
    print(
        f"\nBOTH-WINDOW GRADUATION? {'YES' if (cur_pass and earl_pass) else 'NO'}  "
        f"(current {'PASS' if cur_pass else 'FAIL'}, "
        f"earlier {'PASS' if earl_pass else 'FAIL'})"
    )


if __name__ == "__main__":
    main()
