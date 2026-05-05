"""
Tests for data/validator.py — OHLCV Data Quality Validator
"""
import numpy as np
import pandas as pd
import pytest
from data.validator import OHLCVValidator, DataQualityReport


def make_clean_df(n=200, freq="1h"):
    np.random.seed(0)
    close = 100.0 + np.cumsum(np.random.normal(0, 0.5, n))
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq=freq),
        "open":   close * np.random.uniform(0.999, 1.001, n),
        "high":   close * np.random.uniform(1.001, 1.010, n),
        "low":    close * np.random.uniform(0.990, 0.999, n),
        "close":  close,
        "volume": np.random.uniform(1e4, 1e5, n),
    })
    return df


@pytest.fixture
def clean_ohlcv():
    return make_clean_df()


@pytest.fixture
def validator():
    return OHLCVValidator(freq="1h", symbol="TEST/USDT")


def _issue_checks(report):
    """Return list of check names from all issues."""
    return [i.check for i in report.issues]


def test_clean_data_high_score(clean_ohlcv, validator):
    report = validator.validate(clean_ohlcv)
    assert isinstance(report, DataQualityReport)
    assert report.score >= 80.0, f"Clean data should score >= 80, got {report.score}"


def test_clean_data_no_critical_errors(clean_ohlcv, validator):
    report = validator.validate(clean_ohlcv)
    critical = [i for i in report.issues if i.severity == "CRITICAL"]
    assert len(critical) == 0, f"Clean data should have no critical issues: {critical}"


def test_negative_price_detected(clean_ohlcv, validator):
    bad = clean_ohlcv.copy()
    bad.loc[5, "close"] = -100.0
    report = validator.validate(bad)
    checks = _issue_checks(report)
    assert any("neg" in c.lower() or "price" in c.lower() for c in checks), \
        f"Should detect negative price. Got issues: {checks}"


def test_ohlc_inconsistency_detected(clean_ohlcv, validator):
    bad = clean_ohlcv.copy()
    bad.loc[10, "high"] = bad.loc[10, "low"] * 0.98  # high < low
    report = validator.validate(bad)
    checks = _issue_checks(report)
    assert any("ohlc" in c.lower() or "consisten" in c.lower() or "high" in c.lower()
               for c in checks), f"Should detect OHLC inconsistency. Got: {checks}"


def test_stale_prices_detected(clean_ohlcv, validator):
    stale = clean_ohlcv.copy()
    stale.loc[20:27, "close"] = 100.0
    report = validator.validate(stale)
    checks = _issue_checks(report)
    assert any("stale" in c.lower() or "repeat" in c.lower() or "identical" in c.lower()
               for c in checks), f"Should detect stale prices. Got: {checks}"


def test_extreme_return_detected(validator):
    n = 100
    close = np.ones(n) * 100.0
    close[50] = 180.0
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="1h"),
        "open": close * 0.999, "high": close * 1.005,
        "low": close * 0.995, "close": close,
        "volume": np.ones(n) * 1000.0,
    })
    report = validator.validate(df)
    checks = _issue_checks(report)
    assert any("return" in c.lower() or "outlier" in c.lower() or "extreme" in c.lower()
               for c in checks), f"Should detect extreme return. Got: {checks}"


def test_zero_volume_detected(clean_ohlcv, validator):
    bad = clean_ohlcv.copy()
    bad.loc[30:37, "volume"] = 0.0
    report = validator.validate(bad)
    checks = _issue_checks(report)
    assert any("volume" in c.lower() or "zero" in c.lower()
               for c in checks), f"Should detect zero volume. Got: {checks}"


def test_score_range(clean_ohlcv, validator):
    report = validator.validate(clean_ohlcv)
    assert 0.0 <= report.score <= 100.0


def test_to_dict_serializable(clean_ohlcv, validator):
    report = validator.validate(clean_ohlcv)
    d = report.to_dict()
    assert isinstance(d, dict)
    assert "score" in d


def test_clean_removes_bad_rows(validator):
    n = 100
    close = np.ones(n) * 100.0
    close[5] = -50.0
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="1h"),
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.ones(n) * 1000.0,
    })
    report = validator.validate(df)
    cleaned = report.clean(df)
    assert len(cleaned) < n
    assert (cleaned["close"] > 0).all()


def test_timestamp_ordering_detected():
    n = 50
    close = np.ones(n) * 100.0
    ts = pd.date_range("2024-01-01", periods=n, freq="1h").tolist()
    df = pd.DataFrame({
        "timestamp": ts[::-1],  # reversed
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.ones(n) * 1000.0,
    })
    v = OHLCVValidator(freq="1h")
    report = v.validate(df)
    checks = _issue_checks(report)
    assert any("timestamp" in c.lower() or "order" in c.lower() or "monoton" in c.lower()
               for c in checks), f"Should detect timestamp ordering. Got: {checks}"
