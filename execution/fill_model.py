"""
execution/fill_model.py  —  Realistic paper-fill simulation
============================================================

PURPOSE
-------
Closes Gap 1 (paper-trading fidelity). Replaces the naive
`price * (1 + 0.001)` slippage assumption in live_paper_runner with a fill
model that uses real mainnet orderbook depth + recent trades.

DESIGN PRINCIPLES
-----------------
1. Use real mainnet data (already fetched per cycle via ccxt) — no separate
   WS connection needed at AAATS's 15-min cycle cadence.
2. Maker fills only when honest: limit price strictly inside the book AND
   a recent trade printed through it. Bid-ask oscillation alone does NOT
   produce a fill (Hummingbot's known false-positive bug).
3. Taker fills walk live L20 depth with a latency penalty applied — the
   price the strategy SAW vs the price it would actually GET after RTT.
4. Apply real Binance VIP-0 fees: spot 0.10%/0.10%, USDT-M futures
   maker 0.02% / taker 0.05% (override via params for other tiers).
5. Funding accrual is deterministic from mark price — already correct in
   trading/funding_arb.py; this module doesn't touch it.

NON-GOALS
---------
- Live mainnet WebSocket streaming. AAATS cycles every 15 min; REST snapshots
  of orderbook + recent trades are sufficient. WS would add complexity for
  no measurable accuracy gain at this cadence.
- Partial fills with queue position modeling. We use a simple
  "filled-or-not" approximation — good enough for proof-of-concept.
- Cross-exchange best-execution routing. AAATS is Binance-only Phase 1.

USAGE
-----
    from execution.fill_model import FillModel, FillResult

    fm = FillModel(maker_fee_bps=2.0, taker_fee_bps=5.0)

    # Taker example (market order semantics):
    result = fm.simulate_taker(
        side="BUY",
        intended_price=43210.0,
        size=0.0012,
        orderbook=ccxt_orderbook,  # dict with "bids" and "asks"
        latency_ms=120,
        recent_volatility=0.015,
    )
    # result.fill_price, result.fees_usd, result.slippage_bps, result.filled

    # Maker example (limit order at a posted price):
    result = fm.simulate_maker(
        side="BUY",
        limit_price=43200.0,
        size=0.0012,
        orderbook=ccxt_orderbook,
        recent_trades=ccxt_recent_trades,  # list of trade dicts
        wait_window_seconds=900,
    )
    # result.filled = True only if a trade printed through limit_price during window
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Literal

Side = Literal["BUY", "SELL"]


# ─── Result type ─────────────────────────────────────────────────────────────


@dataclass
class FillResult:
    """One realistic fill simulation outcome."""

    filled: bool
    fill_price: float
    filled_size: float
    fees_usd: float
    slippage_bps: float       # vs intended_price; positive = worse for you
    side: Side
    fill_type: str            # "MAKER" | "TAKER" | "REJECTED_NO_LIQUIDITY" | "REJECTED_NO_PRINT"
    notes: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "filled": self.filled,
            "fill_price": round(self.fill_price, 8),
            "filled_size": round(self.filled_size, 8),
            "fees_usd": round(self.fees_usd, 6),
            "slippage_bps": round(self.slippage_bps, 2),
            "side": self.side,
            "fill_type": self.fill_type,
            "notes": self.notes,
        }


# ─── FillModel ───────────────────────────────────────────────────────────────


class FillModel:
    """
    Realistic fill simulator.

    Construction:
        FillModel(
            maker_fee_bps=2.0,        # 0.02% — Binance USDT-M VIP-0 maker
            taker_fee_bps=5.0,        # 0.05% — Binance USDT-M VIP-0 taker
            spot_maker_fee_bps=10.0,  # 0.10% — Binance spot VIP-0
            spot_taker_fee_bps=10.0,  # 0.10% — Binance spot VIP-0
            latency_noise_bps=2.0,    # extra Gaussian slippage from microstructure
        )
    """

    def __init__(
        self,
        maker_fee_bps: float = 2.0,
        taker_fee_bps: float = 5.0,
        spot_maker_fee_bps: float = 10.0,
        spot_taker_fee_bps: float = 10.0,
        latency_noise_bps: float = 2.0,
    ) -> None:
        self.maker_fee_bps = maker_fee_bps
        self.taker_fee_bps = taker_fee_bps
        self.spot_maker_fee_bps = spot_maker_fee_bps
        self.spot_taker_fee_bps = spot_taker_fee_bps
        self.latency_noise_bps = latency_noise_bps

    # ── Taker (market order or aggressive limit) ─────────────────────────

    def simulate_taker(
        self,
        side: Side,
        intended_price: float,
        size: float,
        orderbook: dict[str, list[list[float]]] | None,
        latency_ms: int = 100,
        recent_volatility: float = 0.01,
        is_spot: bool = True,
    ) -> FillResult:
        """
        Simulate a taker fill that walks the live orderbook.

        Args:
            side:              "BUY" → walks ASKS; "SELL" → walks BIDS.
            intended_price:    Price the strategy SAW when generating signal.
            size:              Shares/contracts requested.
            orderbook:         ccxt orderbook dict: {"bids": [[p, qty], ...],
                                                     "asks": [[p, qty], ...]}.
                               None = no book available → use intended_price ± 5 bps.
            latency_ms:        RTT delay before order reaches exchange. We model
                               this as an extra slippage push in the direction of
                               adverse selection.
            recent_volatility: 24-bar stddev of returns (e.g. 0.015 = 1.5%).
                               Higher vol → wider latency-driven adverse move.
            is_spot:           True for spot fees, False for USDT-M perp fees.

        Returns:
            FillResult.
        """
        fee_bps = self.spot_taker_fee_bps if is_spot else self.taker_fee_bps

        # If we have no book, use intended price with a small adverse push
        if not orderbook or not orderbook.get("asks") or not orderbook.get("bids"):
            adverse_bps = 5.0 + self.latency_noise_bps
            fill_price = self._apply_slippage(intended_price, side, adverse_bps)
            slip = self._slippage_bps(intended_price, fill_price, side)
            return FillResult(
                filled=True,
                fill_price=fill_price,
                filled_size=size,
                fees_usd=self._fees(fill_price, size, fee_bps),
                slippage_bps=slip,
                side=side,
                fill_type="TAKER",
                notes={"no_book": True},
            )

        # Walk the relevant side of the book
        levels = orderbook["asks"] if side == "BUY" else orderbook["bids"]

        remaining = size
        filled_notional = 0.0
        filled_qty = 0.0
        levels_consumed = 0

        for level in levels:
            if remaining <= 0:
                break
            level_price = float(level[0])
            level_qty = float(level[1])

            take_qty = min(remaining, level_qty)
            filled_notional += take_qty * level_price
            filled_qty += take_qty
            remaining -= take_qty
            levels_consumed += 1

        if filled_qty <= 0:
            return FillResult(
                filled=False,
                fill_price=0.0,
                filled_size=0.0,
                fees_usd=0.0,
                slippage_bps=0.0,
                side=side,
                fill_type="REJECTED_NO_LIQUIDITY",
                notes={"book_levels": len(levels)},
            )

        # If we couldn't fill the whole size, treat as partial. AAATS strategies
        # are small relative to book depth, so this is rare.
        vwap_fill = filled_notional / filled_qty

        # Apply latency-driven adverse move: during the RTT, price may move
        # against us. Model as proportional to (latency_ms × volatility).
        latency_adverse_bps = max(
            0.0,
            (latency_ms / 1000.0) * recent_volatility * 1e4 * 0.5,
        )
        # Plus the structural latency noise (microstructure noise)
        latency_adverse_bps += abs(random.gauss(0, self.latency_noise_bps))

        fill_price_after_latency = self._apply_slippage(
            vwap_fill, side, latency_adverse_bps,
        )

        return FillResult(
            filled=True,
            fill_price=fill_price_after_latency,
            filled_size=filled_qty,
            fees_usd=self._fees(fill_price_after_latency, filled_qty, fee_bps),
            slippage_bps=self._slippage_bps(intended_price, fill_price_after_latency, side),
            side=side,
            fill_type="TAKER",
            notes={
                "book_levels_consumed": levels_consumed,
                "book_vwap": round(vwap_fill, 6),
                "latency_adverse_bps": round(latency_adverse_bps, 2),
                "partial": filled_qty < size,
            },
        )

    # ── Maker (passive limit order) ──────────────────────────────────────

    def simulate_maker(
        self,
        side: Side,
        limit_price: float,
        size: float,
        orderbook: dict[str, list[list[float]]] | None,
        recent_trades: list[dict[str, Any]] | None,
        is_spot: bool = True,
    ) -> FillResult:
        """
        Honest maker fill: only filled if (a) limit price is strictly inside
        the book AND (b) a recent trade printed through your price.

        Why "and": Hummingbot's bug is firing fills on bid-ask oscillation
        alone, which overstates returns. We require an actual print through
        the limit price during the wait window before declaring a fill.

        Args:
            side:          "BUY" — limit < current best ask (would post on bid side)
                           "SELL" — limit > current best bid
            limit_price:   Strategy's intended maker price.
            size:          Size of the limit order.
            orderbook:     Current book snapshot.
            recent_trades: List of trades that occurred during the wait window.
                           Each: {"price": float, "amount": float, "side": str}.
            is_spot:       Fee tier selector.

        Returns:
            FillResult with filled=True if a trade printed through limit_price.
        """
        fee_bps = self.spot_maker_fee_bps if is_spot else self.maker_fee_bps

        if not orderbook or not orderbook.get("asks") or not orderbook.get("bids"):
            return FillResult(
                filled=False,
                fill_price=0.0,
                filled_size=0.0,
                fees_usd=0.0,
                slippage_bps=0.0,
                side=side,
                fill_type="REJECTED_NO_BOOK",
                notes={"reason": "orderbook_unavailable"},
            )

        best_bid = float(orderbook["bids"][0][0])
        best_ask = float(orderbook["asks"][0][0])

        # Validate maker position
        if side == "BUY" and limit_price >= best_ask:
            # This would actually be a taker. Reject and tell caller to use taker path.
            return FillResult(
                filled=False, fill_price=0.0, filled_size=0.0, fees_usd=0.0,
                slippage_bps=0.0, side=side, fill_type="REJECTED_CROSSED_BOOK",
                notes={"limit_price": limit_price, "best_ask": best_ask,
                       "reason": "limit_buy_>=_best_ask_use_taker_instead"},
            )
        if side == "SELL" and limit_price <= best_bid:
            return FillResult(
                filled=False, fill_price=0.0, filled_size=0.0, fees_usd=0.0,
                slippage_bps=0.0, side=side, fill_type="REJECTED_CROSSED_BOOK",
                notes={"limit_price": limit_price, "best_bid": best_bid,
                       "reason": "limit_sell_<=_best_bid_use_taker_instead"},
            )

        # Check if any recent trade printed through our price
        if not recent_trades:
            return FillResult(
                filled=False, fill_price=0.0, filled_size=0.0, fees_usd=0.0,
                slippage_bps=0.0, side=side, fill_type="REJECTED_NO_PRINT",
                notes={"reason": "no_recent_trades_during_window"},
            )

        if side == "BUY":
            # Filled if any sell-side trade printed at <= our limit (someone hit our bid)
            crossing_trades = [
                t for t in recent_trades
                if float(t.get("price", 0)) <= limit_price
                and t.get("side", "").lower() in ("sell", "")
            ]
        else:
            # Filled if any buy-side trade printed at >= our limit
            crossing_trades = [
                t for t in recent_trades
                if float(t.get("price", 0)) >= limit_price
                and t.get("side", "").lower() in ("buy", "")
            ]

        if not crossing_trades:
            return FillResult(
                filled=False, fill_price=0.0, filled_size=0.0, fees_usd=0.0,
                slippage_bps=0.0, side=side, fill_type="REJECTED_NO_PRINT",
                notes={
                    "reason": "no_trade_printed_through_limit",
                    "trades_seen": len(recent_trades),
                    "limit_price": limit_price,
                },
            )

        # Use the limit price as fill (maker fills AT the posted price, not
        # at the crossing trade price)
        return FillResult(
            filled=True,
            fill_price=limit_price,
            filled_size=size,
            fees_usd=self._fees(limit_price, size, fee_bps),
            slippage_bps=0.0,   # maker = no slippage by definition
            side=side,
            fill_type="MAKER",
            notes={
                "crossing_trades": len(crossing_trades),
                "best_bid": best_bid,
                "best_ask": best_ask,
            },
        )

    # ── Internals ────────────────────────────────────────────────────────

    @staticmethod
    def _apply_slippage(price: float, side: Side, bps: float) -> float:
        """Push price adversely by `bps` basis points."""
        sign = 1 if side == "BUY" else -1
        return price * (1 + sign * bps / 1e4)

    @staticmethod
    def _slippage_bps(intended: float, filled: float, side: Side) -> float:
        """Compute realized slippage in bps. Positive = worse for you."""
        if intended <= 0:
            return 0.0
        sign = 1 if side == "BUY" else -1
        return sign * (filled - intended) / intended * 1e4

    @staticmethod
    def _fees(price: float, size: float, fee_bps: float) -> float:
        """Notional × fee."""
        return abs(price * size) * fee_bps / 1e4
