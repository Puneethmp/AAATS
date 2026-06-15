"""MarketContext — the per-date market data a risk-managed constructor needs.

The dollar-neutral baseline only needs ranked symbols. A risk-managed constructor
(inverse-vol, vol-target, beta-neutral) additionally needs, as of each rebalance
date and using ONLY data strictly before it (no look-ahead):
  - per-name realized vol  (inverse-vol weights + portfolio vol-target)
  - per-name beta to an equal-weight index  (beta-neutralization)
  - the daily returns panel  (ex-ante portfolio-vol estimate)

This object carries the daily returns panel and computes those quantities on
demand with strict as-of slicing, so the same context feeds the real run and the
null (identical risk machinery — the anti-overfit invariant).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MarketContext:
    daily_returns: (
        pd.DataFrame
    )  # index=UTC midnights, cols=symbols, simple daily returns

    @classmethod
    def from_close(cls, daily_close: pd.DataFrame) -> "MarketContext":
        return cls(daily_returns=daily_close.pct_change())

    def _window(self, date, lookback_days: int) -> pd.DataFrame:
        """Rows strictly BEFORE `date`, last `lookback_days` of them."""
        prior = self.daily_returns.loc[self.daily_returns.index < date]
        return prior.tail(lookback_days)

    def realized_vol(self, date, symbols, lookback_days: int) -> pd.Series:
        """Annualized realized vol per symbol (as-of `date`)."""
        win = self._window(date, lookback_days)[list(symbols)]
        return win.std(ddof=0) * np.sqrt(365.0)

    def beta(self, date, symbols, lookback_days: int) -> pd.Series:
        """Beta of each symbol to the equal-weight index of `symbols` (as-of)."""
        win = self._window(date, lookback_days)[list(symbols)].dropna(axis=1, how="all")
        if win.shape[0] < 3 or win.shape[1] == 0:
            return pd.Series(1.0, index=list(symbols))  # neutral fallback
        idx = win.mean(axis=1)  # equal-weight index returns
        var = float(idx.var(ddof=0))
        if var <= 0:
            return pd.Series(1.0, index=list(symbols))
        betas = {s: float(win[s].cov(idx)) / var for s in win.columns}
        return pd.Series(betas).reindex(list(symbols)).fillna(1.0)

    def portfolio_realized_vol(self, date, weights: dict, lookback_days: int) -> float:
        """Annualized realized vol of holding fixed `weights` over the lookback.

        Ex-ante proxy: apply the CURRENT signed weights to past returns and take
        the annualized std of the resulting portfolio return series. Used to scale
        gross exposure to the vol target.
        """
        if not weights:
            return 0.0
        syms = [s for s in weights if s in self.daily_returns.columns]
        win = self._window(date, lookback_days)[syms]
        if win.shape[0] < 3:
            return 0.0
        w = np.array([weights[s] for s in syms], dtype=float)
        port = win.to_numpy(dtype=float) @ w  # daily portfolio returns (per $1 book)
        port = port[~np.isnan(port)]
        if port.size < 3:
            return 0.0
        return float(np.std(port, ddof=0) * np.sqrt(365.0))
