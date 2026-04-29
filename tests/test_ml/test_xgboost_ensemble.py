"""Tests for ml/xgboost_ensemble.py."""

from __future__ import annotations

import numpy as np
import pytest

from ml.xgboost_ensemble import (
    ModelConfig,
    build_ensemble,
    position_scale_from_confidence,
    score_signal,
    train_all,
    _generate_synthetic_data,
    _CONFIDENCE_FULL,
    _CONFIDENCE_HALF,
)


class TestBuildEnsemble:
    def test_builds_three_markets(self):
        ensemble = build_ensemble()
        assert set(ensemble.keys()) == {"us", "india", "crypto"}

    def test_models_untrained_initially(self):
        ensemble = build_ensemble()
        for model in ensemble.values():
            assert not model.is_trained

    def test_custom_config(self):
        config = ModelConfig(n_estimators=50)
        ensemble = build_ensemble(config)
        assert ensemble["us"].model.n_estimators == 50


class TestTrainAll:
    def test_trains_all_markets(self):
        ensemble = build_ensemble()
        results = train_all(ensemble)
        for market in ("us", "india", "crypto"):
            assert ensemble[market].is_trained
            assert "train_acc" in results[market]
            assert "val_acc" in results[market]

    def test_accuracy_above_50pct(self):
        ensemble = build_ensemble()
        results = train_all(ensemble)
        for market, metrics in results.items():
            assert metrics["val_acc"] >= 0.4, f"{market} val_acc too low"

    def test_custom_data_used(self):
        ensemble = build_ensemble()
        custom_data = {
            "us": _generate_synthetic_data("us", n_samples=500, seed=1),
        }
        results = train_all(ensemble, data=custom_data)
        assert ensemble["us"].is_trained


class TestScoreSignal:
    def setup_method(self):
        self.ensemble = build_ensemble(ModelConfig(n_estimators=50))
        train_all(self.ensemble)

    def test_returns_float_between_0_and_1(self):
        features = {
            "return_1d": 0.01, "return_5d": 0.03, "return_20d": 0.08,
            "rsi_14": 55.0, "macd": 0.5, "ema_spread_pct": 0.05,
            "adx_14": 28.0, "atr_14": 2.0, "hist_vol_20": 0.15, "vol_ratio_20": 1.2,
        }
        score = score_signal("us", features, self.ensemble)
        assert 0.0 <= score <= 1.0

    def test_untrained_returns_neutral(self):
        fresh = build_ensemble()  # untrained
        score = score_signal("us", {}, fresh)
        assert score == 0.5

    def test_unknown_market_returns_neutral(self):
        score = score_signal("unknown_market", {}, self.ensemble)
        assert score == 0.5

    def test_missing_features_handled(self):
        score = score_signal("us", {}, self.ensemble)
        assert 0.0 <= score <= 1.0

    def test_india_model_produces_score(self):
        features = {
            "returns_1d": 0.01, "returns_5d": 0.02, "returns_20d": 0.05,
            "rsi_14": 50.0, "macd": 0.3, "ema_spread_pct": 0.04,
            "adx_14": 26.0, "atr_14": 1.5, "india_vix": 14.0,
        }
        score = score_signal("india", features, self.ensemble)
        assert 0.0 <= score <= 1.0

    def test_crypto_model_produces_score(self):
        features = {
            "return_1d": 0.02, "return_5d": 0.05,
            "rsi_14": 52.0, "macd": 0.8, "ema_spread_pct": 0.03,
            "atr_pct": 0.025, "vol_ratio": 1.3,
        }
        score = score_signal("crypto", features, self.ensemble)
        assert 0.0 <= score <= 1.0


class TestPositionScale:
    def test_high_confidence_full_size(self):
        assert position_scale_from_confidence(0.75) == 1.0
        assert position_scale_from_confidence(0.60) == 1.0

    def test_medium_confidence_half_size(self):
        assert position_scale_from_confidence(0.50) == 0.5
        assert position_scale_from_confidence(0.40) == 0.5

    def test_low_confidence_skip(self):
        assert position_scale_from_confidence(0.30) == 0.0
        assert position_scale_from_confidence(0.0) == 0.0

    def test_boundary_full(self):
        assert position_scale_from_confidence(_CONFIDENCE_FULL) == 1.0

    def test_boundary_half(self):
        assert position_scale_from_confidence(_CONFIDENCE_HALF) == 0.5


class TestGenerateSyntheticData:
    def test_shapes_correct(self):
        for market in ("us", "india", "crypto"):
            X, y = _generate_synthetic_data(market, n_samples=100)
            assert X.shape[0] == 100
            assert y.shape[0] == 100

    def test_labels_binary(self):
        X, y = _generate_synthetic_data("us", n_samples=200)
        assert set(y).issubset({0, 1})

    def test_both_classes_present(self):
        X, y = _generate_synthetic_data("us", n_samples=500)
        assert 0 in y and 1 in y
