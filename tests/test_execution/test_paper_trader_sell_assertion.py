"""
Tests for paper_trader._check_sell_buy_share_equality.

P1 guardrail (2026-05-15): post-INSERT detection that the SELL row written to
paper_trades has shares equal to its FIFO-matching BUY row. Detection-only —
never halts, never modifies.
"""

from __future__ import annotations

import time

import pytest

from execution import paper_trader


class _WarnCapture:
    """Stand-in loguru logger that records warning() calls."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg, *args, **kwargs):
        if args:
            self.warnings.append(msg.format(*args))
        else:
            self.warnings.append(str(msg))

    def info(self, *_a, **_k):
        pass

    def debug(self, *_a, **_k):
        pass

    def error(self, *_a, **_k):
        pass


@pytest.fixture
def capture_log(monkeypatch):
    cap = _WarnCapture()
    monkeypatch.setattr(paper_trader, "_log", cap)
    return cap


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "paper_trades.db")
    # Materialize schema before first record_trade() — dedupe_check runs before
    # _conn() and assumes the table already exists (true in production).
    paper_trader._conn(path).close()
    return path


def _buy(db_path, symbol, shares, price, strategy="C3_altcoin_reversion", nonce=0):
    return paper_trader.record_trade(
        db_path=db_path,
        market="crypto",
        symbol=symbol,
        action="BUY",
        shares=shares,
        price=price,
        strategy=strategy,
        nonce=nonce,
    )


def _sell(db_path, symbol, shares, price, strategy="C3_altcoin_reversion", nonce=0):
    return paper_trader.record_trade(
        db_path=db_path,
        market="crypto",
        symbol=symbol,
        action="SELL",
        shares=shares,
        price=price,
        strategy=strategy,
        nonce=nonce,
    )


class TestSellBuyShareEquality:
    def test_matching_pair_emits_no_warning(self, db_path, capture_log):
        _buy(db_path, "TON/USDT", shares=1.51314025, price=2.50)
        _sell(db_path, "TON/USDT", shares=1.51314025, price=2.078)
        assert capture_log.warnings == []

    def test_mismatched_pair_emits_warning_with_correct_delta(
        self, db_path, capture_log
    ):
        # Simulates the C3 exit-sizing bug: SELL shares computed from
        # size_usd / exit_price instead of stored entry shares. Losing trade,
        # so exit_price < entry_price → SELL shares > BUY shares.
        buy_shares = 1.51314025
        sell_shares = 1.58578826  # artificial residual: ~0.0726 sh
        _buy(db_path, "TON/USDT", shares=buy_shares, price=2.50)
        _sell(db_path, "TON/USDT", shares=sell_shares, price=2.078)

        assert len(capture_log.warnings) == 1
        msg = capture_log.warnings[0]
        assert "SELL/BUY share mismatch" in msg
        assert "strategy=C3_altcoin_reversion" in msg
        assert "symbol=TON/USDT" in msg
        assert f"buy_shares={buy_shares}" in msg
        assert f"sell_shares={sell_shares}" in msg
        expected_delta = abs(sell_shares - buy_shares)
        assert f"delta={expected_delta:.10f}" in msg

    def test_fifo_match_when_multiple_open_buys(self, db_path, capture_log):
        # Two BUYs for same (strategy, symbol). FIFO: first SELL pairs with
        # BUY1, second SELL pairs with BUY2. The first SELL has shares that
        # match BUY2 — should still WARN because it pairs with BUY1.
        _buy(db_path, "FET/USDT", shares=45.42, price=0.22, nonce=1)
        # Distinct timestamps guarantee FIFO order regardless of id tiebreak.
        time.sleep(0.01)
        _buy(db_path, "FET/USDT", shares=99.99, price=0.21, nonce=2)
        time.sleep(0.01)
        _sell(db_path, "FET/USDT", shares=99.99, price=0.20, nonce=3)

        assert len(capture_log.warnings) == 1
        msg = capture_log.warnings[0]
        assert "buy_shares=45.42" in msg
        assert "sell_shares=99.99" in msg

        # Second SELL pairs with BUY2 (FIFO advance) — matched, no new warning.
        _sell(db_path, "FET/USDT", shares=99.99, price=0.20, nonce=4)
        assert len(capture_log.warnings) == 1
