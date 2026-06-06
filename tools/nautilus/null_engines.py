"""Null engines for the cross-sectional reactivation theses (T1/T2, 2026-06-06).

Generalizes the Track F sign-shuffle null (run_walk_forward.py) to the registered
SELECTION nulls of the pre-reg doc §3:

  - T1 "random-quintile selection — same dates, same counts per side, same
    hysteresis mechanics, names drawn uniformly from U30; 1000 draws."
  - T2 "random-rank quintiles — same dates, same counts, same weekly turnover;
    1000 draws."

Both are realized identically: replace the real ranking SIGNAL with a uniform
random score per (date, eligible symbol) and run the SAME schedule builder. This
guarantees same dates / counts / turnover mechanics by construction (the builder,
not the null, owns hysteresis and rebalance cadence), so the null carries the
identical fee load — the property the pre-reg requires of a valid null.

seed=7, 1000 draws (frozen). The gated null statistic is criterion 5's pooled-OOS
daily Sharpe; this module returns its 1000-draw distribution.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tools.nautilus.xsect_walkforward import pooled_oos_daily_sharpe


def random_score_panel(
    dates: pd.DatetimeIndex, symbols: list[str], rng: np.random.Generator
) -> pd.DataFrame:
    """Uniform-random score per (date, symbol). The schedule builder ranks these
    within each date's eligible universe exactly as it ranks the real signal, so
    a random panel yields a uniformly-random selection with identical mechanics."""
    return pd.DataFrame(
        rng.random((len(dates), len(symbols))), index=dates, columns=symbols
    )


def null_distribution(
    schedule_builder,
    simulate,
    score_index: pd.DatetimeIndex,
    score_columns: list[str],
    folds,
    book: float,
    n: int = 1000,
    seed: int = 7,
) -> np.ndarray:
    """Run `n` random-selection draws and return their pooled-OOS daily Sharpes.

    schedule_builder(scores_df) -> schedule (list of (day, weights)).
    simulate(schedule) -> BasketResult.
    """
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    for i in range(n):
        scores = random_score_panel(score_index, score_columns, rng)
        schedule = schedule_builder(scores)
        res = simulate(schedule)
        out[i] = pooled_oos_daily_sharpe(res.daily_pnl, folds, book)
    return out
