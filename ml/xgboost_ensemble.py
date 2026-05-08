"""
XGBoost Ensemble for AAATS Signal Confidence Scoring.

Walk-forward TimeSeriesSplit CV + Platt calibration + drift monitoring.
Position size mapped via 5-bucket smooth scaling (YAML-configurable).
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import TimeSeriesSplit, train_test_split
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from foundation.logger import get_logger

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

_log = get_logger("ml", "xgboost_ensemble")

_MODEL_DIR = Path(__file__).parent / "models"

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
    calibrator: Any = None
    feature_stats: dict[str, dict[str, float]] = field(default_factory=dict)
    cv_metrics: dict[str, float] = field(default_factory=dict)

    def fit(self, X: np.ndarray, y: np.ndarray, n_splits: int = 5) -> dict[str, float]:
        if len(y) < n_splits * 2:
            raise ValueError(
                f"{self.market}: only {len(y)} samples; need >= {n_splits * 2}"
            )
        tscv = TimeSeriesSplit(n_splits=n_splits)
        fold_val_accs = []
        last_val_idx = None
        for fold_idx, (train_idx, val_idx) in enumerate(tscv.split(X)):
            X_tr, X_vl = X[train_idx], X[val_idx]
            y_tr, y_vl = y[train_idx], y[val_idx]
            sf = StandardScaler()
            X_tr_s = sf.fit_transform(X_tr)
            X_vl_s = sf.transform(X_vl)
            clf_fold = XGBClassifier(**self.model.get_params())
            clf_fold.fit(X_tr_s, y_tr)
            acc = float(clf_fold.score(X_vl_s, y_vl))
            fold_val_accs.append(acc)
            _log.info(f"  [{self.market}] fold {fold_idx + 1}/{n_splits}: val_acc={acc:.3f}")
            last_val_idx = val_idx

        mean_val_acc = float(np.mean(fold_val_accs))
        std_val_acc = float(np.std(fold_val_accs))

        X_all_s = self.scaler.fit_transform(X)
        self.model.fit(X_all_s, y)
        train_acc = float(self.model.score(X_all_s, y))

        try:
            X_cal = self.scaler.transform(X[last_val_idx])
            y_cal = y[last_val_idx]
            # sklearn 1.6+ deprecated cv="prefit" string. Use FrozenEstimator
            # if available; fall back to legacy "prefit" on older sklearn.
            try:
                from sklearn.frozen import FrozenEstimator
                self.calibrator = CalibratedClassifierCV(
                    FrozenEstimator(self.model), method="sigmoid"
                )
            except ImportError:
                self.calibrator = CalibratedClassifierCV(
                    self.model, cv="prefit", method="sigmoid"
                )
            self.calibrator.fit(X_cal, y_cal)
            _log.info(f"  [{self.market}] Platt calibrator fit on {len(y_cal)} samples")
        except Exception as exc:
            _log.warning(f"  [{self.market}] calibration failed: {exc}")
            self.calibrator = None

        for i, feat_name in enumerate(self.features):
            self.feature_stats[feat_name] = {
                "mean": float(X[:, i].mean()),
                "std": float(X[:, i].std() + 1e-9),
            }

        self.is_trained = True
        self.cv_metrics = {
            "train_acc": train_acc,
            "val_acc": mean_val_acc,
            "val_acc_std": std_val_acc,
            "n_samples": int(len(y)),
            "n_folds": n_splits,
        }
        _log.info(
            f"{self.market.upper()} trained walk-forward val_acc={mean_val_acc:.3f} "
            f"+/- {std_val_acc:.3f} train_acc={train_acc:.3f} n={len(y)}"
        )
        return self.cv_metrics

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.is_trained or self.model is None:
            raise RuntimeError(f"{self.market} model not trained")
        X_s = self.scaler.transform(X)
        if self.calibrator is not None:
            return self.calibrator.predict_proba(X_s)[:, 1]
        return self.model.predict_proba(X_s)[:, 1]

    def check_drift(self, X: np.ndarray, threshold_z: float = 3.0) -> dict[str, float]:
        if not self.feature_stats or X.size == 0:
            return {}
        drift = {}
        for i, feat_name in enumerate(self.features):
            s = self.feature_stats.get(feat_name)
            if s is None:
                continue
            value = float(X[0, i]) if X.ndim == 2 else float(X[i])
            z = abs(value - s["mean"]) / s["std"]
            drift[feat_name] = float(z)
        return drift

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({
                "model": self.model,
                "scaler": self.scaler,
                "is_trained": self.is_trained,
                "calibrator": self.calibrator,
                "feature_stats": self.feature_stats,
                "cv_metrics": self.cv_metrics,
            }, f)
        _log.info(f"Saved {self.market} model -> {path}")

    def load(self, path: Path) -> None:
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.model = data["model"]
        self.scaler = data["scaler"]
        self.is_trained = data["is_trained"]
        self.calibrator = data.get("calibrator")
        self.feature_stats = data.get("feature_stats", {})
        self.cv_metrics = data.get("cv_metrics", {})
        _log.info(f"Loaded {self.market} model <- {path}")


def _generate_synthetic_data(market, n_samples=2000, seed=42):
    rng = np.random.default_rng(seed)
    features = _FEATURE_MAP[market]
    X = rng.standard_normal((n_samples, len(features)))
    return_5d_idx = 1 if "return_5d" in features else 0
    rsi_idx = 3 if "rsi_14" in features else 0
    ema_idx = 5 if "ema_spread_pct" in features else 0
    score = (
        0.4 * X[:, return_5d_idx]
        + 0.3 * (X[:, ema_idx] > 0)
        + 0.2 * (X[:, rsi_idx] < 0.5)
        + 0.1 * rng.standard_normal(n_samples)
    )
    y = (score > 0).astype(int)
    return X, y


def build_ensemble(config=None):
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


def train_all(ensemble, data=None):
    results = {}
    for market, model in ensemble.items():
        if data and market in data:
            X, y = data[market]
        else:
            X, y = _generate_synthetic_data(market)
        results[market] = model.fit(X, y)
    return results


def score_signal(market, features_row, ensemble):
    model = ensemble.get(market)
    if model is None or not model.is_trained:
        _log.warning(f"No trained model for {market} — returning 0.5")
        return 0.5
    feature_values = [features_row.get(f, 0.0) for f in model.features]
    X = np.array([feature_values])
    try:
        proba = model.predict_proba(X)[0]
        drift = model.check_drift(X)
        extreme = {f: z for f, z in drift.items() if z > 3.0}
        if extreme:
            _log.warning(f"[{market}] feature drift |z|>3: {extreme}")
        return float(proba)
    except Exception as exc:
        _log.error(f"score_signal failed for {market}: {exc}")
        return 0.5


_GATE_CONFIG_PATH = Path(__file__).parent.parent / "strategies" / "configs" / "_ml_gate.yaml"

_DEFAULT_BUCKETS = [
    (0.40, 0.00),
    (0.50, 0.30),
    (0.60, 0.60),
    (0.75, 0.85),
    (1.01, 1.20),
]

_BUCKETS_CACHE = {}


def _load_buckets(market=None):
    cache_key = market or "default"
    if cache_key in _BUCKETS_CACHE:
        return _BUCKETS_CACHE[cache_key]
    buckets = _DEFAULT_BUCKETS
    if _YAML_AVAILABLE and _GATE_CONFIG_PATH.exists():
        try:
            with open(_GATE_CONFIG_PATH, "r") as f:
                cfg = yaml.safe_load(f) or {}
            override = None
            if market and market in cfg and cfg[market] and cfg[market].get("buckets"):
                override = cfg[market]["buckets"]
            elif "default" in cfg and cfg["default"] and cfg["default"].get("buckets"):
                override = cfg["default"]["buckets"]
            if override:
                buckets = [(float(b["confidence_max"]), float(b["scale"])) for b in override]
                _log.info(f"Loaded ML gate buckets from YAML for market={cache_key}: {buckets}")
        except Exception as exc:
            _log.warning(f"Failed to load {_GATE_CONFIG_PATH}: {exc} — using defaults")
    _BUCKETS_CACHE[cache_key] = buckets
    return buckets


def position_scale_from_confidence(confidence: float, market: str | None = None) -> float:
    """5-bucket smooth scaling. <0.40 skip / 0.40-0.50 30% / 0.50-0.60 60% /
    0.60-0.75 85% / >=0.75 120% (capped at Kelly upstream)."""
    buckets = _load_buckets(market)
    for conf_max, scale in buckets:
        if confidence < conf_max:
            return float(scale)
    return float(buckets[-1][1])
