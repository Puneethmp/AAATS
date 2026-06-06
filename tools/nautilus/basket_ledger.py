"""N-leg dollar-neutral cross-sectional basket ledger (Reactivation T1/T2, 2026-06-06).

Generalizes the C7 per-PAIR funding ledger (tools/nautilus/run_c7_funding_arb_oos.py)
to an arbitrary-N dollar-neutral long/short basket with daily mark-to-market, real
8h funding accrual per leg, and turnover-based taker fees. Pure pandas/numpy — no
NautilusTrader dependency (a 30-instrument event-driven NT sim is the wrong tool for
a daily-rebalanced cross-sectional basket; the Track F walk-forward harness is
likewise a direct/vectorized sim).

Frozen accounting conventions (per pre-reg §3 "Common to T1/T2"):
  - Book = $100 fixed. Each side gets `book` dollars of notional (equal-dollar legs),
    so gross exposure = 2*book, net = 0 at construction. Per-trade return = leg
    pnl_net / leg notional.
  - Fees: taker `fee_rate` per side on every leg, charged on |Δnotional| turnover at
    every rebalance (initial entry and final liquidation included).
  - Funding: a leg's funding cashflow = -(signed units) * mark * rate, i.e. a LONG
    perp pays when rate>0 and a SHORT receives when rate>0. Applied per real 8h
    settlement print, assigned to the day that contains it.
  - Marks: daily 00:00-UTC perp close. Position entered at rebalance day r's mark;
    the move r->r+1 is attributed to the position held over it (no look-ahead).

A "trade" (round trip) = a maximal continuous holding of one symbol on one side
(long/short). T2's weekly full rebalance makes every hold exactly one week (a
"position-week"); T1's hysteresis makes holds span multiple rebalances. This single
definition serves both theses' registered min-sample framings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class BasketResult:
    trades: list = field(default_factory=list)  # per round-trip ledger rows
    daily_pnl: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    book: float = 100.0
    gross_turnover_usd: float = 0.0
    fees_total_usd: float = 0.0
    funding_total_usd: float = 0.0

    @property
    def daily_returns(self) -> pd.Series:
        return self.daily_pnl / self.book


def build_daily_close(hourly_close: pd.DataFrame) -> pd.DataFrame:
    """Daily 00:00-UTC mark panel from an hourly perp-close panel (cols=symbols).

    Uses the 00:00 bar's close as the day's mark (exact midnight stamp, no
    resample blending). Forward-fills isolated gaps so a single missing hourly
    bar does not drop a symbol from a day's universe.
    """
    midnights = hourly_close[hourly_close.index.hour == 0]
    midnights = midnights.copy()
    midnights.index = midnights.index.normalize()
    midnights = midnights[~midnights.index.duplicated(keep="last")].sort_index()
    return midnights


def _funding_daily_matrix(
    funding: dict[str, pd.Series], days: pd.DatetimeIndex, symbols: list[str]
) -> np.ndarray:
    """Sum of funding RATES settled on each calendar day per (day, symbol).
    Multiplying later by signed notional gives the funding cashflow. Vectorized
    per symbol (no per-settlement Python loop) — `days` must be sorted ascending.

    Schedule-INDEPENDENT: depends only on funding/days/symbols, so compute it ONCE
    and reuse across the real run + all null draws (see precompute_funding_matrix)."""
    n, m = len(days), len(symbols)
    out = np.zeros((n, m))
    days_i8 = days.normalize().asi8
    for j, s in enumerate(symbols):
        ser = funding.get(s)
        if ser is None or len(ser) == 0:
            continue
        fdays = ser.index.normalize().asi8
        pos = np.searchsorted(days_i8, fdays)
        valid = (pos >= 0) & (pos < n)
        pos_v = pos[valid]
        rates = ser.to_numpy()[valid]
        match = days_i8[pos_v] == fdays[valid]
        np.add.at(out[:, j], pos_v[match], rates[match])
    return out


def precompute_funding_matrix(
    daily_close: pd.DataFrame, funding: dict[str, pd.Series]
) -> np.ndarray:
    """Public wrapper: funding-rate daily matrix aligned to daily_close's (days x
    symbols). Pass the result to simulate_basket(funding_rate_mat=...) to avoid
    recomputing it on every null draw."""
    return _funding_daily_matrix(funding, daily_close.index, list(daily_close.columns))


def simulate_basket(
    daily_close: pd.DataFrame,
    funding: dict[str, pd.Series],
    schedule: list[tuple[pd.Timestamp, dict[str, float]]],
    book: float = 100.0,
    fee_rate: float = 0.0005,
    liquidate_at_end: bool = True,
    funding_rate_mat: np.ndarray | None = None,
    compute_trades: bool = True,
) -> BasketResult:
    """Simulate a dollar-neutral basket.

    Parameters
    ----------
    daily_close : days(midnight UTC) x symbols perp-close panel.
    funding     : {symbol -> Series(8h settlement ts -> funding_rate)}.
    schedule    : list of (rebalance_day, {symbol: signed_dollar_notional}); + long,
                  - short. Rebalance days must be in `daily_close.index`. The
                  portfolio is held constant (in entry-units) until the next entry.
    book        : capital base for return normalization.
    fee_rate    : taker fee fraction per side, charged on |Δnotional| turnover.
    funding_rate_mat : optional precomputed daily funding-rate matrix (from
                  precompute_funding_matrix); pass it to skip the per-call rebuild
                  in null loops. If None it is computed from `funding`.
    compute_trades : when False, skip the per-symbol round-trip ledger (nulls only
                  need daily_pnl for the pooled-OOS Sharpe) — a big speedup.
    """
    days = daily_close.index
    symbols = list(daily_close.columns)
    sidx = {s: j for j, s in enumerate(symbols)}
    n, m = len(days), len(symbols)
    price = daily_close.to_numpy(dtype=float)

    # --- target notional per day (held constant between rebalances) ---
    target = np.zeros((n, m))  # signed dollar notional in force at END of each day
    rebal_rows = []  # (day_index, weights dict) aligned to daily index
    day_pos = {d: i for i, d in enumerate(days)}
    sched_sorted = sorted(schedule, key=lambda kv: kv[0])
    for ts, weights in sched_sorted:
        di = day_pos.get(pd.Timestamp(ts).normalize())
        if di is None:
            continue
        rebal_rows.append((di, weights))
    # forward-fill target notional from each rebalance to the next
    rebal_rows.sort()
    for k, (di, weights) in enumerate(rebal_rows):
        hi = rebal_rows[k + 1][0] if k + 1 < len(rebal_rows) else n
        row = np.zeros(m)
        for s, w in weights.items():
            j = sidx.get(s)
            if j is not None:
                row[j] = w
        target[di:hi, :] = row

    # --- units in force at END of each day (signed) = notional / price-at-entry ---
    # Recompute entry price per rebalance segment; within a segment units are fixed.
    units = np.zeros((n, m))
    for k, (di, weights) in enumerate(rebal_rows):
        hi = rebal_rows[k + 1][0] if k + 1 < len(rebal_rows) else n
        p = price[di, :]
        with np.errstate(divide="ignore", invalid="ignore"):
            u = np.where((p > 0) & np.isfinite(p), target[di, :] / p, 0.0)
        units[di:hi, :] = u

    # --- daily price PnL: move (d-1 -> d) attributed to units held over it ---
    price_pnl = np.zeros((n, m))
    dp = np.diff(price, axis=0)  # (n-1, m), price[d]-price[d-1]
    dp = np.nan_to_num(dp, nan=0.0)
    price_pnl[1:, :] = units[:-1, :] * dp

    # --- funding PnL: -(signed units) * mark * rate, per settlement-day ---
    if funding_rate_mat is None:
        funding_rate_mat = _funding_daily_matrix(funding, days, symbols)
    mark = np.nan_to_num(price, nan=0.0)
    funding_pnl = -(units * mark) * funding_rate_mat

    # --- fees: fee_rate * |Δ notional| at each rebalance (+ final liquidation) ---
    fee = np.zeros((n, m))
    for di, weights in rebal_rows:
        # drifted value of the previous position at THIS rebalance's price
        p = price[di, :]
        # prev units were units[di-1] (end of prior day); value them at p
        prev_u = units[di - 1, :] if di > 0 else np.zeros(m)
        drifted_prev = np.where(np.isfinite(p), prev_u * p, 0.0)
        new_notional = target[di, :]
        turn = np.abs(new_notional - drifted_prev)
        fee[di, :] += fee_rate * turn
    if liquidate_at_end and rebal_rows:
        last_di = n - 1
        p = price[last_di, :]
        final_u = units[last_di, :]
        final_notional = np.where(np.isfinite(p), final_u * p, 0.0)
        fee[last_di, :] += fee_rate * np.abs(final_notional)

    net_per_day_sym = price_pnl + funding_pnl - fee
    daily_pnl = pd.Series(net_per_day_sym.sum(axis=1), index=days)

    # --- per round-trip ledger: segment each symbol's signed-hold into runs ---
    # (skipped for null draws, which only need daily_pnl for the pooled Sharpe)
    trades = []
    sign = np.sign(units) if compute_trades else np.zeros_like(units)
    for j, s in enumerate(symbols):
        col_sign = sign[:, j]
        d = 0
        while d < n:
            if col_sign[d] == 0:
                d += 1
                continue
            run_sign = col_sign[d]
            start = d
            while d < n and col_sign[d] == run_sign:
                d += 1
            end = d - 1  # inclusive last day of the hold
            seg = slice(start, end + 1)
            pnl = float(
                price_pnl[seg, j].sum() + funding_pnl[seg, j].sum() - fee[seg, j].sum()
            )
            notionals = np.abs(target[seg, j])
            notionals = notionals[notionals > 0]
            notional = float(notionals.mean()) if len(notionals) else 0.0
            if notional <= 0:
                continue
            trades.append(
                {
                    "symbol": s,
                    "side": "long" if run_sign > 0 else "short",
                    "pnl_net": pnl,
                    "notional": notional,
                    "funding": float(funding_pnl[seg, j].sum()),
                    "fees": float(fee[seg, j].sum()),
                    "entry_ts": int(days[start].value),
                    "ts": int(days[end].value),  # close ts -> fold bucketing
                    "hold_days": int(end - start + 1),
                }
            )

    return BasketResult(
        trades=trades,
        daily_pnl=daily_pnl,
        book=book,
        gross_turnover_usd=float(fee.sum() / fee_rate) if fee_rate else 0.0,
        fees_total_usd=float(fee.sum()),
        funding_total_usd=float(funding_pnl.sum()),
    )
