"""
markets/crypto/confidence_scorer.py  —  ML-ready confidence scoring scaffold
============================================================================

PURPOSE
-------
Returns a per-candidate CONFIDENCE score in [0.0, 1.0] used by the allocator
to size positions and by the strategies to gate entries.

This is the SCAFFOLD. Initial implementation is rule-based (weighted blend
of indicators). The interface — `score_candidate(features) -> float` — is
designed so a trained XGBoost / LightGBM model can replace `_rule_score()`
without changing any caller code.

When 100+ fills accumulate from Phase 1 paper trading, we'll:
  1. Extract features at entry time + forward 12h return as label
  2. Train XGBoost classifier (won/lost binary or magnitude regression)
  3. Replace `_rule_score()` with `_ml_score()` — same signature
  4. Compare model confidence calibration against actual hit rates

ALL FEATURES INTENTIONALLY SIMPLE — no rolling features, no embeddings,
no cross-asset features. Just symbol-local indicators + sentiment.

USAGE
-----
    from markets.crypto.confidence_scorer import (
        extract_features, score_candidate,
    )

    feats = extract_features(symbol, ohlcv_df, z_score, fg_score)
    conf  = score_candidate(feats, strategy="c3")
    if conf < 0.45:
        skip  # low conviction
    size = base_size * conf
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# ── Feature container ─────────────────────────────────────────────────────────
@dataclass
class CandidateFeatures:
    symbol: str
    # Price/structure
    pct_b: float            # Bollinger %B
    rsi: float              # 14-period RSI
    z_score: float          # log(ALT/BTC) z over 60H (None for BTC/ETH)
    distance_from_low: float   # (close - 20H_low) / 20H_low
    distance_from_high: float  # (20H_high - close) / 20H_high
    # Volatility
    realized_vol_24h: float    # std of log returns × sqrt(24)
    atr_pct: float             # ATR(14) as % of price
    # Volume
    vol_ratio: float           # last-4-bar / 20-bar volume
    # Sentiment
    fear_greed: int            # 0-100
    # Liquidity (optional, populated from universe metadata)
    spread_pct: Optional[float] = None
    quote_volume_24h: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ── Feature extraction ────────────────────────────────────────────────────────
def _rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff().dropna()
    if len(delta) < period:
        return 50.0
    gain = delta.where(delta > 0, 0.0).rolling(period).mean().iloc[-1]
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean().iloc[-1]
    if loss == 0:
        return 100.0
    rs = gain / loss
    return float(100 - 100 / (1 + rs))


def _bb_pct_b(closes: pd.Series, period: int = 20, n_std: float = 2.0) -> float:
    rolling = closes.rolling(period)
    mid = rolling.mean().iloc[-1]
    std = rolling.std(ddof=0).iloc[-1]
    if pd.isna(mid) or pd.isna(std) or std < 1e-9:
        return 0.5
    upper = mid + n_std * std
    lower = mid - n_std * std
    return float((closes.iloc[-1] - lower) / (upper - lower))


def _atr_pct(df: pd.DataFrame, period: int = 14) -> float:
    try:
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
                       axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        return float(atr / c.iloc[-1]) if c.iloc[-1] > 0 else 0.0
    except Exception:
        return 0.0


def extract_features(
    symbol: str,
    df: pd.DataFrame,
    z_score: float = 0.0,
    fg_score: Optional[int] = None,
    spread_pct: Optional[float] = None,
    quote_volume_24h: Optional[float] = None,
) -> CandidateFeatures:
    """Build a feature row from a 1H OHLCV DataFrame."""
    closes = df["close"]
    last  = float(closes.iloc[-1])
    pct_b = _bb_pct_b(closes)
    rsi   = _rsi(closes)
    atr   = _atr_pct(df)

    # Distance from recent extremes (20 bars)
    if len(df) >= 20:
        high_20 = float(df["high"].iloc[-20:].max())
        low_20  = float(df["low"].iloc[-20:].min())
        d_low   = (last - low_20) / max(low_20, 1e-9)
        d_high  = (high_20 - last) / max(high_20, 1e-9)
    else:
        d_low, d_high = 0.0, 0.0

    # Realized vol (24H std of hourly log returns × sqrt(24))
    if len(df) >= 25:
        rets = np.diff(np.log(closes.iloc[-25:].values))
        rv24 = float(np.std(rets, ddof=1) * np.sqrt(24))
    else:
        rv24 = 0.0

    # Volume ratio
    try:
        v4  = float(df["volume"].iloc[-4:].mean())
        v20 = float(df["volume"].iloc[-20:].mean())
        vol_ratio = v4 / v20 if v20 > 0 else 1.0
    except Exception:
        vol_ratio = 1.0

    return CandidateFeatures(
        symbol=symbol,
        pct_b=pct_b, rsi=rsi, z_score=float(z_score),
        distance_from_low=d_low, distance_from_high=d_high,
        realized_vol_24h=rv24, atr_pct=atr,
        vol_ratio=vol_ratio,
        fear_greed=fg_score if fg_score is not None else 50,
        spread_pct=spread_pct,
        quote_volume_24h=quote_volume_24h,
    )


# ── Scoring functions ─────────────────────────────────────────────────────────
def _rule_score_c3(f: CandidateFeatures) -> float:
    """
    Rule-based confidence for C3 (alt/BTC mean reversion).
    Output: 0.0 (no entry) to 1.0 (max conviction).

    Weights tuned by hand based on strategy edge prior:
      - z-score extremity:   strongest predictor (0.35 weight)
      - RSI oversold extent: confirming signal      (0.20 weight)
      - Volume confirmation: anti-fake-out          (0.15 weight)
      - Realized vol:        edge is fatter w/ higher vol (0.10 weight)
      - F&G fear bonus:      mean reversion edge fatter in fear (0.10 weight)
      - Liquidity (spread):  fee/slippage drag      (0.10 weight)
    """
    s = 0.0
    # z-score component (best signal at -1.6 to -2.5)
    if f.z_score < -1.6:
        z_strength = min((abs(f.z_score) - 1.6) / 1.0, 1.0)  # capped at z=-2.6
        s += 0.35 * z_strength

    # RSI confirmation
    if f.rsi < 40:
        s += 0.20 * (40 - f.rsi) / 40

    # Volume not collapsing
    if f.vol_ratio > 0.6:
        s += 0.15 * min(f.vol_ratio / 1.5, 1.0)

    # Realized vol — mean reversion needs movement to mean-revert
    if 0.02 < f.realized_vol_24h < 0.15:
        s += 0.10 * min(f.realized_vol_24h / 0.10, 1.0)

    # Sentiment — fear amplifies edge
    if f.fear_greed < 45:
        s += 0.10 * (45 - f.fear_greed) / 45

    # Liquidity penalty
    if f.spread_pct is not None and f.spread_pct > 0.001:
        penalty = min(f.spread_pct / 0.003, 1.0)
        s -= 0.10 * penalty
    else:
        s += 0.10   # default credit when spread unknown

    return max(0.0, min(1.0, s))


def _rule_score_c6(f: CandidateFeatures) -> float:
    """
    Rule-based confidence for C6 (Bollinger absolute mean reversion).

    Weights:
      - %B extremity (lower band depth):  0.35
      - RSI oversold:                     0.25
      - Volume confirmation:              0.15
      - Realized vol band fit:            0.10
      - F&G fear/neutral:                 0.10
      - Liquidity:                        0.05
    """
    s = 0.0
    # %B depth — strongest at %B near 0 or below
    if f.pct_b < 0.15:
        s += 0.35 * (0.15 - f.pct_b) / 0.15

    # RSI confirmation
    if f.rsi < 32:
        s += 0.25 * (32 - f.rsi) / 32

    # Volume not dead
    if f.vol_ratio > 0.6:
        s += 0.15 * min(f.vol_ratio / 1.5, 1.0)

    # Vol band — mean reversion in low-vol range is fragile,
    # high vol is risky. Sweet spot: 0.02–0.08
    if 0.02 < f.realized_vol_24h < 0.08:
        s += 0.10
    elif 0.08 <= f.realized_vol_24h < 0.15:
        s += 0.05

    # Sentiment: best in fear-to-neutral; avoid greed
    if f.fear_greed < 60:
        s += 0.10 * (60 - f.fear_greed) / 60

    # Liquidity small bonus
    if f.spread_pct is None or f.spread_pct < 0.001:
        s += 0.05

    return max(0.0, min(1.0, s))


# ── Public scoring interface (the swap point for future ML model) ─────────────
def score_candidate(features: CandidateFeatures, strategy: str = "c6") -> float:
    """
    Return [0.0, 1.0] confidence for a candidate.

    Strategy-specific weighting today (rule-based). Future swap: replace
    body with a single XGBoost.predict_proba() call. The interface — one
    feature row in, one confidence out — does not change.

    Confidence interpretation:
      < 0.30  : do not enter (signal too weak)
      0.30-0.50: enter at 50% of base size
      0.50-0.70: enter at 100% of base size
      0.70-0.85: enter at 110% of base size (bonus for high conviction)
      > 0.85  : enter at 120% of base size (capped)
    """
    if strategy.lower() == "c3":
        return _rule_score_c3(features)
    elif strategy.lower() == "c6":
        return _rule_score_c6(features)
    else:
        # Default: average of both
        return (_rule_score_c3(features) + _rule_score_c6(features)) / 2.0


def confidence_to_size_multiplier(confidence: float) -> float:
    """
    Translate confidence score to position-size multiplier.
    Symmetric scaffold to ML probability calibration.
    """
    if confidence < 0.30:
        return 0.0
    elif confidence < 0.50:
        return 0.50
    elif confidence < 0.70:
        return 1.00
    elif confidence < 0.85:
        return 1.10
    else:
        return 1.20
