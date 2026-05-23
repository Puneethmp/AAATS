"""PF5.5 — Slippage stress test.

Pre-soak gating check that the paper-fill path tolerates a 100bps
inside-spread orderbook (a stressed but not pathological book):

  * FillModel.simulate_taker walks the book and returns a fill at the
    expected adverse-side price (BUY fills near ask, SELL near bid).
  * paper_trader.record_trade persists that fill_price into the
    paper_trades.db row, preserving the realized slippage.

A 100bps wide spread is well outside Binance VIP-0 typical conditions
but inside the regime the soak might briefly touch during high
volatility windows; the soak must not deadlock or write malformed
rows in that case.

LIMITATION DOCUMENTED (not fixed in this test): execution/paper_trader.py
does NOT enforce a minimum-notional check after the fill price is
adjusted for slippage. A position sized at the intended-price min-lot
boundary could fall below Binance's MIN_NOTIONAL after slippage and
still be recorded; that is a known gap. See test_documents_no_min_notional_guard.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from execution import paper_trader
from execution.fill_model import FillModel
from execution.paper_trader import record_trade


def _build_100bps_spread_book(
    mid: float = 100.0,
    spread_bps: float = 100.0,
    depth_per_level: float = 5.0,
    n_levels: int = 5,
) -> dict[str, list[list[float]]]:
    """Construct a synthetic orderbook with a 100bps spread inside.

    mid=100, spread=100bps => best_bid=99.50, best_ask=100.50.
    Levels step out 10bps either side with `depth_per_level` size each.
    """
    half_spread = mid * (spread_bps / 2.0) / 1e4
    best_bid = mid - half_spread
    best_ask = mid + half_spread
    step = mid * (10.0 / 1e4)  # 10bps between levels

    bids = [[round(best_bid - i * step, 6), depth_per_level] for i in range(n_levels)]
    asks = [[round(best_ask + i * step, 6), depth_per_level] for i in range(n_levels)]
    return {"bids": bids, "asks": asks}


@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    path = str(tmp_path / "paper_trades.db")
    # Materialize schema before first record_trade() — dedupe_check runs before
    # _conn() and assumes the table already exists (true in production).
    paper_trader._conn(path).close()
    return path


def test_taker_buy_then_sell_through_100bps_book_records_realistic_fills(
    tmp_db: str,
) -> None:
    """End-to-end: simulate a BUY then SELL of 1.0 share through a 100bps
    book; record both via paper_trader; assert the ledger reflects the
    slippage (BUY fills > intended, SELL fills < intended)."""
    fm = FillModel(latency_noise_bps=0.0)  # deterministic — strip Gaussian noise
    book = _build_100bps_spread_book(mid=100.0, spread_bps=100.0)
    intended = 100.0

    buy = fm.simulate_taker(
        side="BUY",
        intended_price=intended,
        size=1.0,
        orderbook=book,
        latency_ms=0,
        recent_volatility=0.0,
        is_spot=True,
    )
    assert buy.filled, f"BUY did not fill on a 100bps book: {buy}"
    # Best ask is mid + 50bps = 100.50; BUY fill must be >= best ask.
    assert buy.fill_price >= 100.5 - 1e-6, (
        f"BUY fill {buy.fill_price} should be at-or-above best ask 100.50"
    )
    # Slippage must reflect spread crossing (>= 50bps).
    assert buy.slippage_bps >= 45.0, (
        f"BUY slippage_bps={buy.slippage_bps} too low for 100bps spread"
    )

    sell = fm.simulate_taker(
        side="SELL",
        intended_price=intended,
        size=1.0,
        orderbook=book,
        latency_ms=0,
        recent_volatility=0.0,
        is_spot=True,
    )
    assert sell.filled, f"SELL did not fill on a 100bps book: {sell}"
    assert sell.fill_price <= 99.5 + 1e-6, (
        f"SELL fill {sell.fill_price} should be at-or-below best bid 99.50"
    )
    assert sell.slippage_bps >= 45.0, (
        f"SELL slippage_bps={sell.slippage_bps} too low for 100bps spread"
    )

    # Now persist both via record_trade and verify the row prices match
    # the fill_model output (not the intended price).
    buy_id = record_trade(
        db_path=tmp_db,
        market="crypto",
        symbol="SOL/USDT",
        action="BUY",
        shares=1.0,
        price=buy.fill_price,
        strategy="C3_altcoin_reversion",
        signal="pf5.5-buy",
    )
    sell_id = record_trade(
        db_path=tmp_db,
        market="crypto",
        symbol="SOL/USDT",
        action="SELL",
        shares=1.0,
        price=sell.fill_price,
        strategy="C3_altcoin_reversion",
        signal="pf5.5-sell",
    )

    assert buy_id and sell_id and buy_id != sell_id

    conn = sqlite3.connect(tmp_db)
    rows = conn.execute(
        "SELECT action, price, value FROM paper_trades "
        "WHERE strategy='C3_altcoin_reversion' ORDER BY timestamp"
    ).fetchall()
    conn.close()

    assert len(rows) == 2
    actions = [r[0] for r in rows]
    assert actions == ["BUY", "SELL"]
    # Recorded prices must match fill_model output (within float tolerance).
    assert abs(rows[0][1] - buy.fill_price) < 1e-6, (
        f"BUY row price {rows[0][1]} != fill_price {buy.fill_price}"
    )
    assert abs(rows[1][1] - sell.fill_price) < 1e-6, (
        f"SELL row price {rows[1][1]} != fill_price {sell.fill_price}"
    )
    # Round-trip P&L is negative (cost = spread + 2x taker fees).
    realized = (sell.fill_price - buy.fill_price) * 1.0
    assert realized < 0.0, (
        f"100bps round-trip should realize a loss before fees; got ${realized:.4f}"
    )


def test_documents_no_min_notional_guard(tmp_db: str) -> None:
    """DOCUMENTATION TEST: record_trade does not refuse a row whose
    post-slippage notional falls below a hypothetical $1.00 min-notional.
    This is a known gap. If a future change adds a guard, this test
    should be updated (and probably converted into an assertion that
    the guard rejects).

    We assert the CURRENT (pre-guard) behavior: the row is accepted.
    """
    fm = FillModel(latency_noise_bps=0.0)
    book = _build_100bps_spread_book(mid=10.0, spread_bps=100.0)

    # Intended size = 0.10 share at intended price 10.0 -> $1.00 notional.
    # After 100bps slippage, the realized notional is ~ $1.005 — still
    # over a $1.00 floor, but if the user picked a stricter floor like
    # $1.20, the post-slippage row would fall below it.
    result = fm.simulate_taker(
        side="BUY",
        intended_price=10.0,
        size=0.10,
        orderbook=book,
        latency_ms=0,
        recent_volatility=0.0,
        is_spot=True,
    )
    assert result.filled

    trade_id = record_trade(
        db_path=tmp_db,
        market="crypto",
        symbol="LINK/USDT",
        action="BUY",
        shares=0.10,
        price=result.fill_price,
        strategy="C3_altcoin_reversion",
        signal="pf5.5-min-notional-doc",
    )
    assert trade_id, "row insert should succeed (no guard in place today)"

    conn = sqlite3.connect(tmp_db)
    n = conn.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE id = ?", (trade_id,)
    ).fetchone()[0]
    conn.close()
    assert n == 1, (
        "Row exists. CURRENT behavior is permissive; absence of a "
        "min-notional-after-slippage guard is a documented gap."
    )
