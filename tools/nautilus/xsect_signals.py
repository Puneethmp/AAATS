"""Frozen signals + portfolio-construction for the cross-sectional theses (T1/T2).

Parameters here are FROZEN by the 2026-06-06 pre-registration §3. The schedule
builders take a `scores` panel (date x symbol) — the real ranking signal for the
registered run, or a uniform-random panel for a null draw — plus the point-in-time
`membership` map, and return a basket schedule for basket_ledger.simulate_basket.
Driving the SAME builder with random scores is exactly the registered null
(identical dates / counts / turnover; only the selection randomized).

T1 — funding dispersion (daily rebalance, hysteresis):
  signal  = trailing mean funding over 21 settlements (7d), ranked across U30.
  book    = short top quintile (high funding), long bottom quintile (low funding).
  exit    = leave the extreme TERCILE of its side, or 21d max hold.

T2 — cross-sectional momentum (weekly rebalance, full re-rank):
  signal  = trailing 21d return skipping the most recent 24h.
  book    = long top quintile, short bottom quintile; weekly full rebalance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

QUINTILE_FRAC = 0.20
TERCILE_FRAC = 1.0 / 3.0
T1_MAX_HOLD_DAYS = 21
T1_FUNDING_WINDOW = 21  # settlements (7d at 8h cadence)
T2_LOOKBACK_DAYS = 21
T2_SKIP_DAYS = 1


# ──────────────────────────────────────────────────────────────────────────
# Signal panels (real run only; nulls use random_score_panel)
# ──────────────────────────────────────────────────────────────────────────


def trailing_funding_mean_panel(
    funding: dict, daily_dates: pd.DatetimeIndex, window: int = T1_FUNDING_WINDOW
) -> pd.DataFrame:
    """T1 score: mean of the last `window` funding settlements STRICTLY BEFORE each
    daily date (no concurrency look-ahead). NaN where <window settlements exist."""
    cols = {}
    targets = daily_dates.values
    for s, ser in funding.items():
        roll = ser.rolling(window).mean().to_numpy()
        pos = np.searchsorted(ser.index.values, targets, side="left") - 1
        col = np.full(len(daily_dates), np.nan)
        valid = pos >= 0
        col[valid] = roll[pos[valid]]
        cols[s] = col
    return pd.DataFrame(cols, index=daily_dates)


def momentum_panel(
    daily_close: pd.DataFrame,
    daily_dates: pd.DatetimeIndex,
    lookback: int = T2_LOOKBACK_DAYS,
    skip: int = T2_SKIP_DAYS,
) -> pd.DataFrame:
    """T2 score: return over [d-(lookback+skip), d-skip] using daily closes strictly
    before d (skip most recent 24h). NaN where history is short."""
    full = pd.date_range(
        daily_close.index.min(), daily_close.index.max(), freq="D", tz="UTC"
    )
    px = daily_close.reindex(full).ffill()
    score = px.shift(skip) / px.shift(skip + lookback) - 1.0
    return score.reindex(daily_dates)


# ──────────────────────────────────────────────────────────────────────────
# Portfolio construction
# ──────────────────────────────────────────────────────────────────────────


def _counts(n: int) -> tuple[int, int]:
    q = max(1, round(QUINTILE_FRAC * n))
    terc = max(q, round(TERCILE_FRAC * n))
    return q, terc


def _eligible_ranked(scores: pd.DataFrame, members: list[str], d) -> list[str]:
    """Members present in `scores` with a non-NaN value at d, ranked HIGH→LOW."""
    row = scores.loc[d] if d in scores.index else None
    if row is None:
        return []
    elig = [s for s in members if s in scores.columns and pd.notna(row.get(s))]
    return sorted(elig, key=lambda s: row[s], reverse=True)


def build_t2_schedule(
    scores: pd.DataFrame,
    membership: dict,
    rebal_dates: pd.DatetimeIndex,
    book: float = 100.0,
) -> list:
    """Weekly full rebalance: long top quintile, short bottom quintile, equal dollar.
    Each side normalized to `book` (dollar-neutral by construction)."""
    schedule = []
    for d in rebal_dates:
        ranked = _eligible_ranked(scores, membership.get(d, []), d)
        n = len(ranked)
        if n < 2:
            continue
        q, _ = _counts(n)
        if 2 * q > n:
            q = n // 2
        if q < 1:
            continue
        longs = ranked[:q]  # highest momentum
        shorts = ranked[-q:]  # lowest momentum
        weights = {}
        for s in longs:
            weights[s] = book / len(longs)
        for s in shorts:
            weights[s] = -book / len(shorts)
        schedule.append((pd.Timestamp(d), weights))
    return schedule


def build_t1_schedule(
    scores: pd.DataFrame,
    membership: dict,
    rebal_dates: pd.DatetimeIndex,
    book: float = 100.0,
    max_hold_days: int = T1_MAX_HOLD_DAYS,
) -> list:
    """Daily rebalance with hysteresis. SHORT high-funding quintile, LONG low-funding
    quintile; a held name stays until it leaves the extreme TERCILE of its side or
    hits `max_hold_days`. New entries only from the extreme quintile. Each side
    normalized to `book` (dollar-neutral)."""
    schedule = []
    held_short: dict = {}  # symbol -> entry Timestamp
    held_long: dict = {}
    for d in rebal_dates:
        d = pd.Timestamp(d)
        ranked = _eligible_ranked(scores, membership.get(d, []), d)
        n = len(ranked)
        if n < 2:
            # nothing rankable: liquidate (empty target) so positions don't drift
            if held_short or held_long:
                schedule.append((d, {}))
                held_short, held_long = {}, {}
            continue
        q, terc = _counts(n)
        if 2 * q > n:
            q = n // 2
        if q < 1:
            continue
        short_pool = set(ranked[:q])  # highest funding -> short
        short_terc = set(ranked[:terc])
        long_pool = set(ranked[-q:])  # lowest funding -> long
        long_terc = set(ranked[-terc:])

        # --- drop held names that left the tercile, aged out, or fell out of U30 ---
        def _update(held, terc_set, pool):
            for s in list(held):
                aged = (d - held[s]).days >= max_hold_days
                if s not in terc_set or aged or s not in ranked:
                    del held[s]
            for s in pool:
                if len(held) >= q:
                    break
                if s not in held:
                    held[s] = d

        _update(held_short, short_terc, [s for s in ranked if s in short_pool])
        _update(held_long, long_terc, [s for s in reversed(ranked) if s in long_pool])

        weights = {}
        if held_short:
            w = book / len(held_short)
            for s in held_short:
                weights[s] = -w
        if held_long:
            w = book / len(held_long)
            for s in held_long:
                weights[s] = weights.get(s, 0.0) + w
        schedule.append((d, weights))
    return schedule
