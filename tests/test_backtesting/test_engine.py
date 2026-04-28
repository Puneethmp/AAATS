"""
Tests for backtesting/engine.py.

Covers: basic round-trip trade, transaction cost deduction, timestamp ordering
enforcement, overfitting gate (Sharpe > 3.0), position sizer integration,
and empty-DataFrame guard.

All tests use synthetic DataFrames — no external API calls, no DB access.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from backtesting.engine import (
    US_COMMISSION_PER_SHARE,
    US_SLIPPAGE_PCT,
    US_SPREAD_PCT,
    BacktestResult,
    run_backtest,
)
from risk.us.position_sizer import SizingOutput


# ── Shared helpers ────────────────────────────────────────────────────────────


def _make_features(
    prices: list[float],
    atrs: list[float] | None = None,
    symbol: str = "AAPL",
) -> pd.DataFrame:
    """Minimal features DataFrame with required columns."""
    n = len(prices)
    if atrs is None:
        atrs = [10.0] * n  # ATR=10 keeps position_pct well under 10% for price≈100
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="D"),
            "close": prices,
            "atr_14": atrs,
            "symbol": [symbol] * n,
        }
    )


def _sequence_strategy(actions: list[str | None], win_rate: float = 0.55, edge_ratio: float = 1.5):
    """Strategy that plays a fixed action sequence by bar index."""
    call_count = [0]

    def strategy(row):
        idx = call_count[0]
        call_count[0] += 1
        if idx >= len(actions) or actions[idx] is None:
            return None
        return {"action": actions[idx], "win_rate": win_rate, "edge_ratio": edge_ratio}

    return strategy


def _approved_sizing_mock(shares: int = 50, entry_price: float = 100.0) -> SizingOutput:
    """Returns a pre-built approved SizingOutput for mock patching."""
    return SizingOutput(
        symbol="AAPL",
        shares=shares,
        entry_price=entry_price,
        stop_price=entry_price - 20.0,
        risk_per_share=20.0,
        total_risk_usd=shares * 20.0,
        position_value_usd=shares * entry_price,
        risk_pct_of_portfolio=shares * 20.0 / 100_000,
        position_pct_of_portfolio=shares * entry_price / 100_000,
        approved=True,
        rejection_reason=None,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_basic_backtest():
    """Buy → hold → sell with known prices produces the correct trade count
    and a positive net return.

    Setup: price[0]=90 (ignored), price[1]=100 (BUY), price[2]=100 (HOLD),
           price[3]=110 (SELL), price[4]=110 (ignored).
    ATR=10 → stop_distance=20 → shares≈75 at portfolio=100,000 → position_pct≈7.5%<10%.
    """
    prices = [90.0, 100.0, 100.0, 110.0, 110.0]
    df = _make_features(prices, atrs=[10.0] * 5)

    actions = [None, "BUY", "HOLD", "SELL", None]
    result = run_backtest(df, _sequence_strategy(actions), portfolio_value=100_000.0)

    assert result.total_trades == 1, "Expected exactly one completed round-trip"
    assert result.winning_trades == 1
    assert result.losing_trades == 0
    assert result.total_return_pct > 0, "Net return must be positive for a 10% price gain"
    assert len(result.trade_log) == 1
    # Note: approved may be False if the 5-bar Sharpe spikes >3.0 (expected with
    # one high-return bar surrounded by flat bars). Approval logic is tested
    # separately in test_overfitting_gate.


def test_transaction_costs_applied():
    """Net P&L must equal gross P&L minus exactly 2 × shares × commission.

    Slippage/spread are embedded in adjusted entry/exit prices — the difference
    between gross and net isolates the per-share commission only.
    """
    # Buy at 100, sell at 110 (bars 1 and 2)
    prices = [100.0, 100.0, 110.0, 110.0]
    df = _make_features(prices)

    actions = [None, "BUY", "SELL", None]
    result = run_backtest(df, _sequence_strategy(actions), portfolio_value=100_000.0)

    assert result.total_trades == 1
    trade = result.trade_log[0]

    # Entry price must reflect slippage + spread (upward for long)
    expected_entry = 100.0 * (1.0 + US_SLIPPAGE_PCT + US_SPREAD_PCT)
    assert abs(trade["entry_price"] - expected_entry) < 1e-9, (
        f"Entry price {trade['entry_price']:.8f} != expected {expected_entry:.8f}"
    )

    # Exit price must reflect slippage + spread (downward for long)
    expected_exit = 110.0 * (1.0 - US_SLIPPAGE_PCT - US_SPREAD_PCT)
    assert abs(trade["exit_price"] - expected_exit) < 1e-9, (
        f"Exit price {trade['exit_price']:.8f} != expected {expected_exit:.8f}"
    )

    # gross_pnl - net_pnl must equal total commission exactly
    shares = trade["shares"]
    expected_total_commission = 2 * shares * US_COMMISSION_PER_SHARE
    commission_deducted = trade["gross_pnl"] - trade["net_pnl"]
    assert abs(commission_deducted - expected_total_commission) < 1e-9, (
        f"Commission gap {commission_deducted:.8f} != expected {expected_total_commission:.8f}"
    )

    # Net P&L must be less than gross (costs always positive)
    assert trade["net_pnl"] < trade["gross_pnl"]


def test_timestamp_enforcement():
    """Rows must reach strategy_fn in strict chronological order.

    This is the timestamp gate: features_df is sorted ascending before the bar
    loop runs, ensuring no future bar is presented to the strategy before its time.
    """
    # Deliberately pass bars out of order to verify the engine re-sorts them
    prices = [105.0, 101.0, 103.0, 102.0, 104.0]
    df = _make_features(prices)
    # Shuffle the DataFrame to simulate unsorted input
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)

    received_timestamps: list[pd.Timestamp] = []

    def recording_strategy(row):
        received_timestamps.append(row["timestamp"])
        return None  # HOLD — no trades

    run_backtest(df, recording_strategy, portfolio_value=100_000.0)

    assert len(received_timestamps) == 5, "All 5 bars must reach strategy_fn"
    for i in range(1, len(received_timestamps)):
        assert received_timestamps[i] > received_timestamps[i - 1], (
            f"Timestamp order violation at position {i}: "
            f"{received_timestamps[i - 1]} → {received_timestamps[i]}"
        )


def test_overfitting_gate():
    """When Sharpe ratio > 3.0, result must have approved=False and the
    rejection_reason must identify the overfitting gate.

    We patch _compute_sharpe so the test is deterministic and not sensitive
    to the exact sequence of returns produced by a specific data set.
    """
    prices = [100.0, 100.0, 110.0, 110.0]
    df = _make_features(prices)
    actions = [None, "BUY", "SELL", None]

    with patch("backtesting.engine._compute_sharpe", return_value=3.5):
        result = run_backtest(df, _sequence_strategy(actions), portfolio_value=100_000.0)

    assert result.approved is False, "Sharpe=3.5 must trigger overfitting gate"
    assert result.rejection_reason is not None
    assert "Sharpe > 3.0" in result.rejection_reason
    assert "overfitted" in result.rejection_reason.lower()
    assert result.sharpe_ratio == 3.5  # Value is preserved in result for inspection


def test_position_sizer_integration():
    """size_position must be called exactly once for every approved BUY signal.

    Verifies that the engine never bypasses the risk module to compute arbitrary
    sizing — every trade must go through position_sizer.size_position().
    """
    prices = [100.0, 100.0, 110.0, 110.0]
    df = _make_features(prices)
    actions = [None, "BUY", "SELL", None]

    with patch("backtesting.engine.size_position") as mock_sizer:
        mock_sizer.return_value = _approved_sizing_mock(shares=50, entry_price=100.0)
        result = run_backtest(df, _sequence_strategy(actions), portfolio_value=100_000.0)

    mock_sizer.assert_called_once()  # Exactly one BUY signal → exactly one call
    assert result.total_trades == 1, "One SELL should close the mocked position"


def test_position_sizer_rejection_skips_trade():
    """When size_position returns approved=False, no position is opened and
    the trade count remains zero."""
    prices = [100.0, 100.0, 110.0, 110.0]
    df = _make_features(prices)
    actions = [None, "BUY", "SELL", None]

    rejected = SizingOutput(
        symbol="AAPL",
        shares=0,
        entry_price=100.0,
        stop_price=0.0,
        risk_per_share=0.0,
        total_risk_usd=0.0,
        position_value_usd=0.0,
        risk_pct_of_portfolio=0.0,
        position_pct_of_portfolio=0.0,
        approved=False,
        rejection_reason="Position too small: 0 shares computed",
    )

    with patch("backtesting.engine.size_position", return_value=rejected):
        result = run_backtest(df, _sequence_strategy(actions), portfolio_value=100_000.0)

    assert result.total_trades == 0
    assert result.trade_log == []


def test_empty_features():
    """Empty DataFrame must produce a zero-trade rejected result immediately.

    No trades, no metrics, approved=False, and equity_curve contains only
    the initial portfolio value.
    """
    empty_df = pd.DataFrame(columns=["timestamp", "close", "atr_14"])

    result = run_backtest(empty_df, lambda row: None, portfolio_value=100_000.0)

    assert result.total_trades == 0
    assert result.winning_trades == 0
    assert result.losing_trades == 0
    assert result.approved is False
    assert result.rejection_reason is not None
    assert "Empty" in result.rejection_reason
    assert result.equity_curve == [100_000.0]
    assert result.trade_log == []
    assert result.total_return_pct == 0.0
    assert result.sharpe_ratio == 0.0
