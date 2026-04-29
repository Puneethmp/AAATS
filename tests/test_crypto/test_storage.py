"""
Tests for markets/crypto/storage.py — real SQLite via tmp_path, no mocks.
"""

from __future__ import annotations

import pandas as pd
import pytest

from markets.crypto.storage import fetch_bars, fetch_latest_timestamp, store_bars

_SYMBOL = "BTC/USDT"
_TF = "1Day"


def _make_bars(dates: list[str] | None = None) -> pd.DataFrame:
    if dates is None:
        dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    n = len(dates)
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(dates, utc=True),
            "open": [40000.0 + i for i in range(n)],
            "high": [41000.0 + i for i in range(n)],
            "low": [39000.0 + i for i in range(n)],
            "close": [40500.0 + i for i in range(n)],
            "volume": [500.0 + i for i in range(n)],
        }
    )


def test_store_bars_inserts_correctly(tmp_path):
    db = str(tmp_path / "crypto.db")
    count = store_bars(_make_bars(), _SYMBOL, _TF, db)
    assert count == 3

    result = fetch_bars(_SYMBOL, _TF, "2024-01-01", "2024-01-03", db)
    assert len(result) == 3
    for col in ("open", "high", "low", "close", "volume"):
        assert col in result.columns


def test_upsert_no_duplicates(tmp_path):
    db = str(tmp_path / "crypto.db")
    df = _make_bars()
    store_bars(df, _SYMBOL, _TF, db)
    store_bars(df, _SYMBOL, _TF, db)

    result = fetch_bars(_SYMBOL, _TF, "2024-01-01", "2024-01-03", db)
    assert len(result) == 3


def test_fetch_bars_date_range(tmp_path):
    db = str(tmp_path / "crypto.db")
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    store_bars(_make_bars(dates), _SYMBOL, _TF, db)

    result = fetch_bars(_SYMBOL, _TF, "2024-01-02", "2024-01-04", db)
    assert len(result) == 3


def test_empty_fetch_returns_empty_df(tmp_path):
    db = str(tmp_path / "crypto.db")
    result = fetch_bars("ETH/USDT", "1Hour", "2024-01-01", "2024-01-31", db)
    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_missing_column_raises_value_error(tmp_path):
    db = str(tmp_path / "crypto.db")
    bad_df = pd.DataFrame({"timestamp": pd.to_datetime(["2024-01-01"], utc=True), "open": [40000.0]})
    with pytest.raises(ValueError, match="missing required columns"):
        store_bars(bad_df, _SYMBOL, _TF, db)


def test_empty_df_returns_zero(tmp_path):
    db = str(tmp_path / "crypto.db")
    count = store_bars(pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"]), _SYMBOL, _TF, db)
    assert count == 0


def test_different_symbols_isolated(tmp_path):
    db = str(tmp_path / "crypto.db")
    store_bars(_make_bars(), "BTC/USDT", "1Day", db)
    store_bars(_make_bars(), "ETH/USDT", "1Day", db)

    btc = fetch_bars("BTC/USDT", "1Day", "2024-01-01", "2024-01-03", db)
    eth = fetch_bars("ETH/USDT", "1Day", "2024-01-01", "2024-01-03", db)
    assert len(btc) == 3
    assert len(eth) == 3


def test_different_timeframes_isolated(tmp_path):
    db = str(tmp_path / "crypto.db")
    store_bars(_make_bars(), "BTC/USDT", "1Day", db)
    store_bars(_make_bars(), "BTC/USDT", "1Hour", db)

    daily = fetch_bars("BTC/USDT", "1Day", "2024-01-01", "2024-01-03", db)
    hourly = fetch_bars("BTC/USDT", "1Hour", "2024-01-01", "2024-01-03", db)
    assert len(daily) == 3
    assert len(hourly) == 3


def test_fetch_latest_timestamp_returns_max(tmp_path):
    db = str(tmp_path / "crypto.db")
    store_bars(_make_bars(), _SYMBOL, _TF, db)

    latest = fetch_latest_timestamp(_SYMBOL, _TF, db)
    assert latest is not None
    assert "2024-01-03" in latest


def test_fetch_latest_timestamp_none_when_empty(tmp_path):
    db = str(tmp_path / "crypto.db")
    latest = fetch_latest_timestamp("UNKNOWN/USDT", "1Day", db)
    assert latest is None


def test_result_ordered_ascending(tmp_path):
    db = str(tmp_path / "crypto.db")
    dates = ["2024-01-03", "2024-01-01", "2024-01-02"]
    store_bars(_make_bars(dates), _SYMBOL, _TF, db)

    result = fetch_bars(_SYMBOL, _TF, "2024-01-01", "2024-01-03", db)
    timestamps = result["timestamp"].tolist()
    assert timestamps == sorted(timestamps)
