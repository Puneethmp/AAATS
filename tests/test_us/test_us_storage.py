"""Tests for markets/us/storage.py — uses real SQLite via tmp_path, no mocks."""

import pandas as pd
import pytest
from sqlalchemy import inspect

from markets.us.storage import (
    create_tables,
    get_engine,
    query_features,
    query_ohlcv,
    store_features,
    store_ohlcv,
)

_SYMBOL = "AAPL"
_START = pd.Timestamp("2024-01-01", tz="UTC")
_END = pd.Timestamp("2024-01-03", tz="UTC")

_FEATURE_COLS = [
    "return_1d",
    "return_5d",
    "return_20d",
    "return_60d",
    "rsi_14",
    "macd",
    "signal",
    "hist",
    "ema_20",
    "ema_50",
    "ema_200",
    "bb_upper",
    "bb_mid",
    "bb_lower",
    "adx_14",
    "atr_14",
    "hist_vol_20",
    "obv",
    "vol_ratio_20",
]


def _make_ohlcv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2024-01-01", "2024-01-02", "2024-01-03"], utc=True
            ),
            "open": [100.0, 101.0, 102.0],
            "high": [105.0, 106.0, 107.0],
            "low": [99.0, 100.0, 101.0],
            "close": [103.0, 104.0, 105.0],
            "volume": [1000.0, 2000.0, 3000.0],
        }
    )


def _make_features() -> pd.DataFrame:
    """Feature DataFrame matching calculate_features() output schema."""
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2024-01-01", "2024-01-02", "2024-01-03"], utc=True
            ),
            "open": [100.0, 101.0, 102.0],
            "high": [105.0, 106.0, 107.0],
            "low": [99.0, 100.0, 101.0],
            "close": [103.0, 104.0, 105.0],
            "volume": [1000.0, 2000.0, 3000.0],
        }
    )
    for col in _FEATURE_COLS:
        df[col] = 1.0
    return df


@pytest.fixture
def engine(tmp_path):
    eng = get_engine(tmp_path / "test_us.db")
    create_tables(eng)
    return eng


# ── Test 1: both tables created ───────────────────────────────────────────────


def test_both_tables_created(engine):
    tables = inspect(engine).get_table_names()
    assert "us_ohlcv" in tables
    assert "us_features" in tables


# ── Test 2: store and query ohlcv ─────────────────────────────────────────────


def test_store_and_query_ohlcv(engine):
    count = store_ohlcv(engine, _SYMBOL, _make_ohlcv())
    assert count == 3

    result = query_ohlcv(engine, _SYMBOL, _START, _END)
    assert len(result) == 3
    for col in ["open", "high", "low", "close", "volume"]:
        assert col in result.columns


# ── Test 3: upsert — no duplicates on re-store ────────────────────────────────


def test_upsert_no_duplicates(engine):
    df = _make_ohlcv()
    store_ohlcv(engine, _SYMBOL, df)
    store_ohlcv(engine, _SYMBOL, df)  # identical re-store

    result = query_ohlcv(engine, _SYMBOL, _START, _END)
    assert len(result) == 3  # INSERT OR REPLACE: still 3 rows, not 6


# ── Test 4: empty query returns empty df ─────────────────────────────────────


def test_empty_query_returns_empty_df(engine):
    result = query_ohlcv(engine, "NONEXISTENT", _START, _END)
    assert result.empty

    result_feat = query_features(engine, "NONEXISTENT", _START, _END)
    assert result_feat.empty


# ── Test 5: store and query features ─────────────────────────────────────────


def test_store_and_query_features(engine):
    count = store_features(engine, _SYMBOL, _make_features())
    assert count == 3

    result = query_features(engine, _SYMBOL, _START, _END)
    assert len(result) == 3
    assert "rsi_14" in result.columns
    assert "ema_200" in result.columns
    assert "vol_ratio_20" in result.columns


# ── Test 6: market column = "us" ─────────────────────────────────────────────


def test_market_column_is_us(engine):
    store_ohlcv(engine, _SYMBOL, _make_ohlcv())
    ohlcv_result = query_ohlcv(engine, _SYMBOL, _START, _END)
    assert "market" in ohlcv_result.columns
    assert (ohlcv_result["market"] == "us").all()

    store_features(engine, _SYMBOL, _make_features())
    feat_result = query_features(engine, _SYMBOL, _START, _END)
    assert "market" in feat_result.columns
    assert (feat_result["market"] == "us").all()
