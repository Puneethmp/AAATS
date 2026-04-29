"""
XGBoost Ensemble for AAATS Signal Confidence Scoring.

Three separate models (US, India, Crypto) produce a confidence score [0, 1]
for each strategy signal. Confidence > 0.6 = proceed with full size;
0.4-0.6 = proceed with half size; < 0.4 = skip.

Features used (from feature engineers):
  - Returns: return_1d, return_5d, return_20d (US) / returns_1d, returns_5d (India)
  - Momentum: rsi_14, macd, roc_10
  - Trend: ema_50, ema_200 (spread), adx_14
  - Volatility: atr_14, hist_vol_20, bb_width proxy
  - Volume: vol_ratio_20, obv

Models are trained on synthetic data by default (no historical dataset needed
at build time). Replace _generate_synthetic_data() with real historical data
once paper trading has produced enough labeled examples.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from foundation.logger import get_logger

_log = get_logger("ml", "xgboost_ensemble")

_MODEL_DIR = Path(__file__).parent / "models"

# ── Feature sets per market ────────────────────────────────────────────────────
_US_FEATURES = [
    "return_1d", "return_5d", "return_20d",
    "rsi_14", "macd", "ema_spread_pct", "adx_14",
    "atr_14", "hist_vol_20", "vol_ratio_20",
]
_INDIA_FEATURES = [
    "returns_1d", "returns_5d", "returns_20d",
    "rsi_14", "macd", "ema_spread_pct", "adx_14",
    "atr_14", "india_vix",
]
_CRYPTO_FEATURES = [
    "return_1d", "return_5d",
    "rsi_14", "macd", "ema_spread_pct",
    "atr_pct", "vol_ratio",
]

_FEATURE_MAP = {"us": _US_FEATURES, "india": _INDIA_FEATURES, "crypto": _CRYPTO_FEATURES}

_CONFIDENCE_FULL = 0.60
_CONFIDENCE_HALF = 0.40


@dataclass
class ModelConfig:
    n_estimators: int = 200
    max_depth: int = 4
    learning_rate: float = 0.05
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    random_state: int = 42
    eval_metric: str = "logloss"


@dataclass
class MarketModel:
    market: str
    features: list[str]
    model: XGBClassifier | None = None
    scaler: StandardScaler = field(default_factory=StandardScaler)
    is_trained: bool = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> dict[str, float]:
        """Train model. Returns train/val accuracy."""
        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        X_train_s = self.scaler.fit_transform(X_train)
        X_val_s = self.scaler.transform(X_val)

        self.model.fit(X_train_s, y_train)
        train_acc = float(self.model.score(X_train_s, y_train))
        val_acc = float(self.model.score(X_val_s, y_val))
        self.is_trained = True

        _log.info(
            f"{self.market.upper()} model trained — "
            f"train_acc={train_acc:.3f}, val_acc={val_acc:.3f}"
        )
        return {"train_acc": train_acc, "val_acc": val_acc}

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.is_trained or self.model is None:
            raise RuntimeError(f"{self.market} model is not trained yet")
        X_s = self.scaler.transform(X)
        return self.model.predict_proba(X_s)[:, 1]  # probability of class 1 (signal)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"model": self.model, "scaler": self.scaler, "is_trained": self.is_trained}, f)
        _log.info(f"Saved {self.market} model → {path}")

    def load(self, path: Path) -> None:
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.model = data["model"]
        self.scaler = data["scaler"]
        self.is_trained = data["is_trained"]
        _log.info(f"Loaded {self.market} model ← {path}")


def _generate_synthetic_data(
    market: str,
    n_samples: int = 2000,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Generate synthetic training data for bootstrapping the model.

    Real data should replace this once 60+ days of paper trading is available.
    The synthetic data creates plausible feature distributions and a noisy
    target based on momentum/trend heuristics.
    """
    rng = np.random.default_rng(seed)
    features = _FEATURE_MAP[market]
    n_features = len(features)

    X = rng.standard_normal((n_samples, n_features))

    # Label: 1 if returns are positive, RSI not overbought, trend up
    # Heuristic — real labels come from trade outcomes
    return_5d_idx = 1 if "return_5d" in features else 0
    rsi_idx = 3 if "rsi_14" in features else 0
    ema_idx = 5 if "ema_spread_pct" in features else 0

    score = (
        0.4 * X[:, return_5d_idx]          # positive 5d return
        + 0.3 * (X[:, ema_idx] > 0)        # ema uptrend
        + 0.2 * (X[:, rsi_idx] < 0.5)      # not overbought (normalised)
        + 0.1 * rng.standard_normal(n_samples)  # noise
    )
    y = (score > 0).astype(int)
    return X, y


def build_ensemble(config: ModelConfig | None = None) -> dict[str, MarketModel]:
    """
    Build (but not train) XGBoost models for all three markets.

    Returns:
        Dict with keys "us", "india", "crypto", each a MarketModel.
    """
    if config is None:
        config = ModelConfig()

    ensemble = {}
    for market, features in _FEATURE_MAP.items():
        clf = XGBClassifier(
            n_estimators=config.n_estimators,
            max_depth=config.max_depth,
            learning_rate=config.learning_rate,
            subsample=config.subsample,
            colsample_bytree=config.colsample_bytree,
            random_state=config.random_state,
            eval_metric=config.eval_metric,
            verbosity=0,
        )
        ensemble[market] = MarketModel(market=market, features=features, model=clf)

    return ensemble


def train_all(
    ensemble: dict[str, MarketModel],
    data: dict[str, tuple[np.ndarray, np.ndarray]] | None = None,
) -> dict[str, dict[str, float]]:
    """
    Train all market models.

    Args:
        ensemble: Dict from build_ensemble().
        data:     Optional dict of {market: (X, y)}. Uses synthetic data if None.

    Returns:
        Dict of {market: {"train_acc": ..., "val_acc": ...}}.
    """
    results = {}
    for market, model in ensemble.items():
        if data and market in data:
            X, y = data[market]
        else:
            X, y = _generate_synthetic_data(market)

        results[market] = model.fit(X, y)

    return results


def score_signal(
    market: str,
    features_row: dict[str, float],
    ensemble: dict[str, MarketModel],
) -> float:
    """
    Score a single strategy signal for confidence.

    Args:
        market:       "us", "india", or "crypto".
        features_row: Dict of feature_name → value for one bar.
        ensemble:     Trained ensemble from build_ensemble() + train_all().

    Returns:
        Confidence score [0, 1]. Use CONFIDENCE_FULL/HALF thresholds.
    """
    model = ensemble.get(market)
    if model is None or not model.is_trained:
        _log.warning(f"No trained model for {market} — returning 0.5 (neutral)")
        return 0.5

    feature_values = [features_row.get(f, 0.0) for f in model.features]
    X = np.array([feature_values])

    try:
        proba = model.predict_proba(X)[0]
        return float(proba)
    except Exception as exc:
        _log.error(f"score_signal failed for {market}: {exc}")
        return 0.5


def position_scale_from_confidence(confidence: float) -> float:
    """
    Map confidence score to position size multiplier.

    Returns:
        1.0 if confidence >= 0.6 (full size)
        0.5 if 0.4 <= confidence < 0.6 (half size)
        0.0 if confidence < 0.4 (skip trade)
    """
    if confidence >= _CONFIDENCE_FULL:
        return 1.0
    if confidence >= _CONFIDENCE_HALF:
        return 0.5
    return 0.0
