"""
Unified Regime Detection Pipeline
===================================
Why this exists
---------------
AAATS had two regime detectors that never spoke to each other:
  1. indicators/regime_detector.py  — rule-based (EMA + ADX + ATR), fast but reactive
  2. intelligence/regime/hmm_regime.py — Gaussian HMM, probabilistic but needs warmup

This module is the single authoritative regime interface. It combines both into a
weighted consensus regime signal with a calibrated confidence score.

Consensus Logic
---------------
  Rule-based contributes: hard regime label with fixed weight
  HMM contributes: soft state probabilities with learned weight

  Final regime = argmax of weighted probability vector across states

  Confidence = max(weighted_probs) — measures how decisive the consensus is.
  Confidence < 0.5 → ambiguous (recommend reduced position sizing)
  Confidence > 0.75 → strong signal (allow full position sizing)

Output Labels
-------------
  'BULL_TREND'      — trending up (HMM bull + rule-based BULL_TREND)
  'BEAR_TREND'      — trending down
  'RANGE_BOUND'     — sideways/low-volatility consolidation
  'HIGH_VOLATILITY' — volatility spike, regime-agnostic (risk-off)
  'UNKNOWN'         — insufficient data

Integration Points
------------------
  strategies/regime/adaptive_switcher.py  — consumes RegimeSignal.label
  portfolio/allocation_engine.py          — scales positions by RegimeSignal.confidence
  risk/engine.py                          — HIGH_VOLATILITY → reduce all sizes

Usage
-----
  from intelligence.regime.regime_pipeline import RegimePipeline

  pipeline = RegimePipeline()
  pipeline.fit(df_train)                      # train HMM on historical data

  signal = pipeline.detect(df_recent)         # single-bar latest regime
  df_with_regime = pipeline.detect_series(df) # bar-by-bar regime DataFrame
  report = pipeline.regime_report(df)         # full regime statistics
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from indicators.regime_detector import RegimeDetector, RegimeDetectorConfig, Regime
from intelligence.regime.hmm_regime import GaussianHMM
from foundation.logger import get_logger

_log = get_logger("intelligence.regime", "regime_pipeline")

RegimeLabel = Literal["BULL_TREND", "BEAR_TREND", "RANGE_BOUND", "HIGH_VOLATILITY", "UNKNOWN"]

# Mapping from HMM labels to pipeline canonical labels
_HMM_TO_CANONICAL = {
    "bull": "BULL_TREND",
    "bear": "BEAR_TREND",
    "sideways": "RANGE_BOUND",
}

# Mapping from rule-based labels to probability vectors
_RULE_LABEL_PROBS = {
    "BULL_TREND":      {"BULL_TREND": 0.80, "RANGE_BOUND": 0.10, "BEAR_TREND": 0.05, "HIGH_VOLATILITY": 0.05},
    "BEAR_TREND":      {"BEAR_TREND": 0.80, "RANGE_BOUND": 0.10, "BULL_TREND": 0.05, "HIGH_VOLATILITY": 0.05},
    "RANGE_BOUND":     {"RANGE_BOUND": 0.75, "BULL_TREND": 0.10, "BEAR_TREND": 0.10, "HIGH_VOLATILITY": 0.05},
    "HIGH_VOLATILITY": {"HIGH_VOLATILITY": 0.90, "BEAR_TREND": 0.05, "BULL_TREND": 0.03, "RANGE_BOUND": 0.02},
    "UNKNOWN":         {"BULL_TREND": 0.25, "BEAR_TREND": 0.25, "RANGE_BOUND": 0.25, "HIGH_VOLATILITY": 0.25},
}

_ALL_LABELS: list[str] = ["BULL_TREND", "BEAR_TREND", "RANGE_BOUND", "HIGH_VOLATILITY"]


@dataclass
class RegimeSignal:
    """
    Output of RegimePipeline.detect().

    Attributes
    ----------
    label           Consensus regime label.
    confidence      0.0–1.0. How decisive the consensus is.
    probs           Dict of label → probability for all canonical regimes.
    rule_label      Raw label from the rule-based detector.
    hmm_probs       Dict of hmm_label → prob (None if HMM not fitted).
    n_bars          Number of bars used for detection.
    """
    label: str
    confidence: float
    probs: dict[str, float]
    rule_label: str
    hmm_probs: dict[str, float] | None = None
    n_bars: int = 0

    @property
    def is_ambiguous(self) -> bool:
        return self.confidence < 0.50

    @property
    def is_strong(self) -> bool:
        return self.confidence >= 0.75

    @property
    def position_size_factor(self) -> float:
        """
        Scale factor for position sizing based on regime confidence.
        Returns 0.0–1.0. Use this to multiply target position sizes.
        """
        if self.label == "HIGH_VOLATILITY":
            return max(0.0, self.confidence * 0.5)  # Half-size in high vol
        if self.label == "UNKNOWN":
            return 0.0
        return min(1.0, self.confidence)


# ---------------------------------------------------------------------------
# Regime Pipeline
# ---------------------------------------------------------------------------

class RegimePipeline:
    """
    Combines rule-based regime detector + Gaussian HMM into a consensus regime signal.

    Parameters
    ----------
    hmm_weight      Weight given to HMM probabilities in the consensus (0.0–1.0).
                    Rule-based gets (1 - hmm_weight). Default 0.4 — HMM is useful
                    but we don't trust it fully until calibrated on live data.
    n_hmm_states    2 (bear/bull) or 3 (bear/sideways/bull).
    hmm_n_iter      EM iterations for HMM training.
    rule_config     Config for the rule-based detector.
    min_hmm_bars    Minimum bars to attempt HMM fitting.
    """

    def __init__(
        self,
        hmm_weight: float = 0.4,
        n_hmm_states: int = 2,
        hmm_n_iter: int = 100,
        rule_config: RegimeDetectorConfig | None = None,
        min_hmm_bars: int = 100,
        random_state: int = 42,
    ):
        if not 0.0 <= hmm_weight <= 1.0:
            raise ValueError("hmm_weight must be in [0, 1]")
        self.hmm_weight = hmm_weight
        self.rule_weight = 1.0 - hmm_weight
        self.min_hmm_bars = min_hmm_bars

        self._rule_detector = RegimeDetector(config=rule_config or RegimeDetectorConfig())
        self._hmm = GaussianHMM(
            n_states=n_hmm_states,
            n_iter=hmm_n_iter,
            random_state=random_state,
        )
        self._hmm_fitted = False

    # ------------------------------------------------------------------
    def fit(self, df: pd.DataFrame) -> "RegimePipeline":
        """
        Train the HMM on historical OHLCV data.
        Requires at least min_hmm_bars rows. If fewer rows, HMM is skipped
        and only the rule-based detector will be used.

        Parameters
        ----------
        df    DataFrame with at minimum 'close' column (volume optional but recommended).
        """
        if len(df) < self.min_hmm_bars:
            _log.warning(
                f"Only {len(df)} bars; need {self.min_hmm_bars} to train HMM. "
                "Falling back to rule-based only."
            )
            return self

        try:
            self._hmm.fit(df)
            self._hmm_fitted = True
            _log.info(
                f"HMM fitted: {self._hmm.n_states} states, "
                f"log_likelihood={self._hmm._log_likelihood_:.1f}"
            )
        except Exception as exc:
            _log.warning(f"HMM fitting failed: {exc}. Using rule-based only.")

        return self

    # ------------------------------------------------------------------
    def detect(self, df: pd.DataFrame) -> RegimeSignal:
        """
        Detect regime at the LATEST bar of df.

        Parameters
        ----------
        df    DataFrame with OHLCV + at minimum: ema_50, ema_200, atr_14.
              (Use indicators.features.compute_features to prepare.)
        """
        if len(df) == 0:
            return RegimeSignal(
                label="UNKNOWN", confidence=0.0,
                probs={l: 0.25 for l in _ALL_LABELS},
                rule_label="UNKNOWN", n_bars=0,
            )

        # Rule-based: detect on full df, take last row
        rule_series = self._rule_detector.detect_series(df)
        rule_label = str(rule_series.iloc[-1])

        # Convert rule label to probability vector
        rule_probs = dict(_RULE_LABEL_PROBS.get(rule_label, _RULE_LABEL_PROBS["UNKNOWN"]))

        # HMM probabilities
        hmm_probs_dict: dict[str, float] | None = None
        if self._hmm_fitted:
            try:
                hmm_proba_df = self._hmm.predict_proba(df)
                hmm_row = hmm_proba_df.iloc[-1]  # last bar
                hmm_probs_dict = {
                    _HMM_TO_CANONICAL.get(col, "RANGE_BOUND"): float(val)
                    for col, val in hmm_row.items()
                }
                # Ensure all canonical labels exist
                for lbl in _ALL_LABELS:
                    hmm_probs_dict.setdefault(lbl, 0.0)
                # HIGH_VOLATILITY: HMM doesn't model this — inherit from rule
                hmm_probs_dict["HIGH_VOLATILITY"] = rule_probs["HIGH_VOLATILITY"]
                # Renormalise
                total = sum(hmm_probs_dict.values())
                if total > 0:
                    hmm_probs_dict = {k: v / total for k, v in hmm_probs_dict.items()}
            except Exception as exc:
                _log.debug(f"HMM predict_proba failed: {exc}")
                hmm_probs_dict = None

        # Consensus
        consensus = self._weighted_consensus(rule_probs, hmm_probs_dict)
        label = max(consensus, key=consensus.get)  # type: ignore[arg-type]
        confidence = round(float(consensus[label]), 4)

        return RegimeSignal(
            label=label,
            confidence=confidence,
            probs={k: round(v, 4) for k, v in consensus.items()},
            rule_label=rule_label,
            hmm_probs=hmm_probs_dict,
            n_bars=len(df),
        )

    # ------------------------------------------------------------------
    def detect_series(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute consensus regime for EVERY bar in df.

        Returns a DataFrame with columns:
          regime, confidence, rule_regime, [hmm_bull, hmm_bear, hmm_sideways]
        """
        # Rule-based is vectorised
        rule_series = self._rule_detector.detect_series(df)

        # HMM probabilities (full series)
        hmm_proba_df: pd.DataFrame | None = None
        if self._hmm_fitted:
            try:
                hmm_proba_df = self._hmm.predict_proba(df)
            except Exception as exc:
                _log.debug(f"HMM detect_series failed: {exc}")

        rows = []
        for i in range(len(df)):
            rule_lbl = str(rule_series.iloc[i])
            rule_probs = dict(_RULE_LABEL_PROBS.get(rule_lbl, _RULE_LABEL_PROBS["UNKNOWN"]))

            hmm_probs_dict: dict[str, float] | None = None
            if hmm_proba_df is not None:
                row = hmm_proba_df.iloc[i]
                hmm_probs_dict = {
                    _HMM_TO_CANONICAL.get(col, "RANGE_BOUND"): float(val)
                    for col, val in row.items()
                }
                for lbl in _ALL_LABELS:
                    hmm_probs_dict.setdefault(lbl, 0.0)
                hmm_probs_dict["HIGH_VOLATILITY"] = rule_probs["HIGH_VOLATILITY"]
                total = sum(hmm_probs_dict.values())
                if total > 0:
                    hmm_probs_dict = {k: v / total for k, v in hmm_probs_dict.items()}

            consensus = self._weighted_consensus(rule_probs, hmm_probs_dict)
            label = max(consensus, key=consensus.get)  # type: ignore[arg-type]
            confidence = round(float(consensus[label]), 4)

            row_dict: dict = {
                "regime": label,
                "confidence": confidence,
                "rule_regime": rule_lbl,
            }
            if hmm_probs_dict:
                for lbl, prob in hmm_probs_dict.items():
                    row_dict[f"hmm_{lbl.lower()}"] = round(prob, 4)
            rows.append(row_dict)

        return pd.DataFrame(rows, index=df.index)

    # ------------------------------------------------------------------
    def regime_report(self, df: pd.DataFrame) -> dict:
        """
        Full regime report: frequency, mean return, volatility per regime + transitions.
        """
        series_df = self.detect_series(df)
        close = df["close"].replace(0, np.nan).ffill()
        ret = close.pct_change().fillna(0.0)

        labels = series_df["regime"]
        report: dict = {"regime_stats": {}, "transition_matrix": {}}

        for lbl in labels.unique():
            mask = labels == lbl
            r_regime = ret[mask]
            runs, run = [], 0
            for v in mask:
                if v:
                    run += 1
                else:
                    if run > 0:
                        runs.append(run)
                    run = 0
            if run > 0:
                runs.append(run)

            report["regime_stats"][lbl] = {
                "frequency_pct": round(float(mask.mean() * 100), 2),
                "mean_return_pct": round(float(r_regime.mean() * 100), 4),
                "ann_volatility_pct": round(float(r_regime.std() * np.sqrt(252) * 100), 3),
                "mean_duration_bars": round(float(np.mean(runs)), 1) if runs else 0,
                "n_episodes": len(runs),
                "avg_confidence": round(float(series_df.loc[mask, "confidence"].mean()), 3),
            }

        # Transition matrix
        all_labels = labels.unique().tolist()
        for from_lbl in all_labels:
            report["transition_matrix"][from_lbl] = {}
            from_mask = labels == from_lbl
            next_labels = labels.shift(-1)[from_mask].dropna()
            for to_lbl in all_labels:
                count = (next_labels == to_lbl).sum()
                report["transition_matrix"][from_lbl][to_lbl] = round(
                    float(count / max(len(next_labels), 1)), 4
                )

        # HMM stats
        if self._hmm_fitted:
            report["hmm"] = self._hmm.regime_report(df)
        report["n_bars"] = len(df)
        return report

    # ------------------------------------------------------------------
    def _weighted_consensus(
        self,
        rule_probs: dict[str, float],
        hmm_probs: dict[str, float] | None,
    ) -> dict[str, float]:
        """Weighted average of rule and HMM probability vectors."""
        if hmm_probs is None:
            return {k: round(v, 6) for k, v in rule_probs.items()}

        consensus = {}
        for lbl in _ALL_LABELS:
            rp = rule_probs.get(lbl, 0.0)
            hp = hmm_probs.get(lbl, 0.0)
            consensus[lbl] = self.rule_weight * rp + self.hmm_weight * hp

        # Normalise
        total = sum(consensus.values())
        if total > 0:
            consensus = {k: v / total for k, v in consensus.items()}

        return consensus
