"""Tests for markets/india/storage.py — uses real SQLite via tmp_path, no mocks."""

import pandas as pd
import pytest

from markets.india.storage import (
    fetch_bars,
    fetch_option_chain_history,
    store_bars,
    store_option_chain_snapshot,
)

_SYMBOL = "RELIANCE"
_UNDERLYING = "NIFTY"


def _make_equity_bars(dates=None) -> pd.DataFrame:
    if dates is None:
        dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    n = len(dates)
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(dates, utc=True),
            "open": [100.0] * n,
            "high": [105.0] * n,
            "low": [99.0] * n,
            "close": [103.0] * n,
            "volume": [1000.0] * n,
            "atr_14": [2.5] * n,
        }
    )


def _make_option_chain() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "strike": [21000.0, 21000.0, 21500.0, 21500.0],
            "option_type": ["CE", "PE", "CE", "PE"],
            "expiry": ["29MAY2025"] * 4,
            "ltp": [150.0, 80.0, 90.0, 120.0],
            "oi": [50000.0, 40000.0, 30000.0, 60000.0],
            "iv": [0.18, 0.17, 0.16, 0.19],
            "volume": [5000.0, 4000.0, 3000.0, 6000.0],
        }
    )


# ── Test 1: store_bars inserts correctly ─────────────────────────────────────


def test_store_bars_inserts_correctly(tmp_path):
    db = str(tmp_path / "india.db")
    count = store_bars(_make_equity_bars(), _SYMBOL, db)
    assert count == 3

    result = fetch_bars(_SYMBOL, "2024-01-01", "2024-01-03", db)
    assert len(result) == 3
    for col in ("open", "high", "low", "close", "volume"):
        assert col in result.columns


# ── Test 2: duplicate (symbol, timestamp) → upsert, not duplicate ────────────


def test_upsert_no_duplicates(tmp_path):
    db = str(tmp_path / "india.db")
    df = _make_equity_bars()
    store_bars(df, _SYMBOL, db)
    store_bars(df, _SYMBOL, db)  # identical re-store

    result = fetch_bars(_SYMBOL, "2024-01-01", "2024-01-03", db)
    assert len(result) == 3  # INSERT OR REPLACE: still 3 rows, not 6


# ── Test 3: fetch_bars returns correct date range ────────────────────────────


def test_fetch_bars_date_range(tmp_path):
    db = str(tmp_path / "india.db")
    all_dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    store_bars(_make_equity_bars(all_dates), _SYMBOL, db)

    result = fetch_bars(_SYMBOL, "2024-01-02", "2024-01-04", db)
    assert len(result) == 3


# ── Test 4: empty fetch returns empty DataFrame (not exception) ───────────────


def test_empty_fetch_returns_empty_df(tmp_path):
    db = str(tmp_path / "india.db")

    result = fetch_bars("NONEXISTENT", "2024-01-01", "2024-01-31", db)
    assert isinstance(result, pd.DataFrame)
    assert result.empty

    result_fo = fetch_option_chain_history("NONEXISTENT", "2024-01-01", "2024-01-31", db)
    assert isinstance(result_fo, pd.DataFrame)
    assert result_fo.empty


# ── Test 5: store_option_chain_snapshot inserts CE and PE rows ────────────────


def test_store_option_chain_snapshot_ce_and_pe(tmp_path):
    db = str(tmp_path / "india.db")
    count = store_option_chain_snapshot(
        _make_option_chain(), _UNDERLYING, "2024-01-02T00:00:00", db
    )
    assert count == 4

    result = fetch_option_chain_history(_UNDERLYING, "2024-01-01", "2024-01-03", db)
    assert len(result) == 4
    assert "CE" in set(result["option_type"])
    assert "PE" in set(result["option_type"])


# ── Test 6: fetch_option_chain_history returns correct range ─────────────────


def test_fetch_option_chain_history_date_range(tmp_path):
    db = str(tmp_path / "india.db")
    df = _make_option_chain()  # 4 rows per snapshot

    # 3 daily snapshots at midnight UTC (distinct timestamps → no PK collision)
    store_option_chain_snapshot(df, _UNDERLYING, "2024-01-01T00:00:00", db)
    store_option_chain_snapshot(df, _UNDERLYING, "2024-01-02T00:00:00", db)
    store_option_chain_snapshot(df, _UNDERLYING, "2024-01-03T00:00:00", db)

    in_range = fetch_option_chain_history(_UNDERLYING, "2024-01-01", "2024-01-02", db)
    assert len(in_range) == 8  # 4 rows × 2 snapshots

    all_three = fetch_option_chain_history(_UNDERLYING, "2024-01-01", "2024-01-03", db)
    assert len(all_three) == 12  # 4 rows × 3 snapshots
