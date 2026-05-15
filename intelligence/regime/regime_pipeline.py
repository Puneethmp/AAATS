"""
intelligence/regime/regime_pipeline.py  —  HMM Regime Pipeline

Wraps GaussianHMM for use in live_paper_runner.detect_regime().
Fits on HOURLY bars (not daily) so regime labels are never stale.

Key design decisions:
  - n_states=3 (bear / sideways / bull) — sideways regime is important:
    it's when stat-arb and mean-reversion outperform directional strategies
  - Fit on last ~200 hourly bars (~8 days) — recent enough to be adaptive,
    enough history to estimate state transitions reliably
  - `detect()` uses the last bar only — fast, stateless per-call
  - Confidence = posterior P(dominant state | last bar)
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pandas as pd

from intelligence.regime.hmm_regime import GaussianHMM


class RegimeSignal(NamedTuple):
    label: str        # "BULL_TREND" | "BEAR_TREND" | "RANGE_BOUND"
    confidence: float # 0.0 – 1.0


# Map HMM internal labels → AAATS regime vocabulary
_LABEL_MAP = {
    "bull":     "BULL_TREND",
    "sideways": "RANGE_BOUND",
    "bear":     "BEAR_TREND",
}


class RegimePipeline:
    """
    Thin wrapper around GaussianHMM for per-symbol regime detection.

    Usage:
        pipe = RegimePipeline()
        pipe.fit(hourly_df)            # fit on hourly OHLCV
        sig = pipe.detect(hourly_df)   # returns RegimeSignal for last bar
    """

    def __init__(self, n_states: int = 3, n_iter: int = 80) -> None:
        self._hmm = GaussianHMM(n_states=n_states, n_iter=n_iter, random_state=42)
        self._fitted = False

    def fit(self, df: pd.DataFrame) -> "RegimePipeline":
        """Fit HMM on the provided OHLCV dataframe (hourly recommended)."""
        if len(df) < 30:
            raise ValueError(f"Need ≥30 bars to fit HMM, got {len(df)}")
        # Use last 200 bars for speed + recency
        self._hmm.fit(df.iloc[-200:])
        self._fitted = True
        return self

    def detect(self, df: pd.DataFrame) -> RegimeSignal:
        """
        Classify the regime at the last bar using soft HMM posteriors.

        Returns RegimeSignal(label, confidence).
        Raises RuntimeError if not fitted.
        """
        if not self._fitted:
            raise RuntimeError("RegimePipeline.fit() must be called before detect()")

        proba_df = self._hmm.predict_proba(df.iloc[-20:])   # last 20 bars
        last_row  = proba_df.iloc[-1]                        # final bar posteriors
        dom_state = str(last_row.idxmax())
        confidence = float(last_row.max())
        label = _LABEL_MAP.get(dom_state, "RANGE_BOUND")
        return RegimeSignal(label=label, confidence=confidence)
