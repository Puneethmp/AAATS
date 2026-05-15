"""
execution/paper_executor.py  —  PaperExecutor: realistic fills + audit trail
=============================================================================

PURPOSE
-------
The bridge layer between AAATS strategies and the FillModel. Replaces the
naive `price * (1 + 0.001)` slippage assumption in live_paper_runner with a
realistic simulator that:

  1. Fetches a fresh orderbook snapshot via ccxt before each fill
  2. Asks FillModel to simulate the fill (taker by default)
  3. Records the trade via paper_trader.record_trade() with full audit details
  4. Writes a fill entry to the DecisionLedger linked by correlation_id

CYCLE COST
----------
- One ccxt.fetch_order_book() per BUY/SELL signal (~50-150ms each)
- AAATS cycles every 15 min with 6 symbols × ~1 BUY-or-SELL per cycle = ~6 calls/cycle
- Binance public rate limit: 6000 weight/min on /api/v3/depth → unlimited at this rate
- Total cycle overhead added: <1 second

WHEN TO USE
-----------
- Phase 1 paper trading: ALL fills should go through PaperExecutor instead of
  live_paper_runner's inline _fill_price() helper.
- Live trading: NEVER. Replace with a real broker adapter that places real orders.

INTEGRATION POINT
-----------------
In trading/live_paper_runner.execute(), replace:

    fill = _fill_price(last_price, "BUY", market, features)
    value = shares * fill
    record_trade(...)

With:

    from execution.paper_executor import PaperExecutor
    pe = PaperExecutor.singleton()
    result = pe.simulate_and_record(
        market="crypto",
        symbol=symbol,
        side="BUY",
        intended_price=last_price,
        size=shares,
        strategy="C2_momentum",
        signal=signal,
        regime=regime,
        confidence=conf,
        ml_scale=ml_size_scale,
        features=features,
    )
    if result is None or not result.filled:
        return  # paper "rejection"
    # downstream uses result.fill_price / result.fees_usd

SAFETY
------
- Singleton pattern means one shared ccxt binance instance — respects
  Binance rate limits naturally via ccxt's built-in throttler.
- Falls back gracefully if orderbook fetch fails (uses old slippage model).
- Never raises — always returns a FillResult or None.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from execution.fill_model import FillModel, FillResult
from execution.idempotency import make_client_order_id, make_correlation_id
from execution.paper_trader import record_trade

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
_DB_PATH = str(_ROOT / "data" / "paper_trades.db")


class PaperExecutor:
    """
    Stateful paper-trading executor.

    Holds a shared ccxt binance client (rate-limited automatically) and a
    FillModel configured for Binance VIP-0 fees.
    """

    _instance: "PaperExecutor | None" = None

    @classmethod
    def singleton(cls) -> "PaperExecutor":
        """Return the process-wide singleton (lazy)."""
        if cls._instance is None:
            cls._instance = PaperExecutor()
        return cls._instance

    def __init__(self) -> None:
        self.fill_model = FillModel(
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            spot_maker_fee_bps=10.0,
            spot_taker_fee_bps=10.0,
            latency_noise_bps=2.0,
        )
        self._binance: Any = None  # lazy init

    def _get_binance(self) -> Any:
        if self._binance is not None:
            return self._binance
        try:
            import ccxt
            # No API keys needed for orderbook + recent trades (public).
            # Reuse keys if present in env for consistency.
            import os
            self._binance = ccxt.binance({
                "apiKey": os.environ.get("CRYPTO__BINANCE_API_KEY", ""),
                "secret": os.environ.get("CRYPTO__BINANCE_SECRET_KEY", ""),
                "enableRateLimit": True,
            })
        except Exception as exc:
            log.error("PaperExecutor: ccxt binance init failed: %s", exc)
            self._binance = None
        return self._binance

    def _fetch_book_and_trades(
        self,
        symbol: str,
    ) -> tuple[dict | None, list[dict] | None]:
        """Pull live orderbook and recent trades. Returns (None, None) on failure."""
        ex = self._get_binance()
        if ex is None:
            return None, None

        book = None
        trades = None
        try:
            book = ex.fetch_order_book(symbol, limit=20)
        except Exception as exc:
            log.warning("PaperExecutor: orderbook fetch failed for %s: %s",
                        symbol, exc)

        try:
            trades = ex.fetch_trades(symbol, limit=50)
        except Exception as exc:
            log.debug("PaperExecutor: trades fetch failed for %s: %s",
                      symbol, exc)

        return book, trades

    @staticmethod
    def _compute_recent_volatility(features: pd.DataFrame | None) -> float:
        """24-bar stddev of 1h returns, default 1% if unavailable."""
        if features is None or len(features) < 25 or "close" not in features.columns:
            return 0.01
        try:
            return float(features["close"].pct_change().dropna().tail(24).std())
        except Exception:
            return 0.01

    def simulate_and_record(
        self,
        market: str,
        symbol: str,
        side: str,
        intended_price: float,
        size: float,
        strategy: str,
        signal: str = "",
        regime: str = "",
        confidence: float = 0.0,
        ml_scale: float = 1.0,
        features: pd.DataFrame | None = None,
        fill_type: str = "TAKER",  # "TAKER" | "MAKER"
        is_spot: bool = True,
        notes_extra: dict[str, Any] | None = None,
    ) -> FillResult | None:
        """
        End-to-end: fetch book → simulate fill → record to paper_trades.db.

        Returns:
            FillResult on success (filled=True), None on failure or rejection.

        The FillResult is also persisted to paper_trades + an audit-trail
        decision_ledger entry (when caller links correlation_id manually).
        """
        # Skip non-crypto markets — orderbook fetch is only wired for crypto.
        # India NSE markets use a separate adapter; this PaperExecutor is
        # crypto-first for Phase 1.
        if market != "crypto":
            return None

        book, trades = self._fetch_book_and_trades(symbol)

        vol = self._compute_recent_volatility(features)

        if fill_type == "MAKER":
            # Maker path expects limit_price strictly inside book; if our
            # intended_price is a market-cross level, caller should pass
            # fill_type="TAKER" instead.
            result = self.fill_model.simulate_maker(
                side=side, limit_price=intended_price, size=size,
                orderbook=book, recent_trades=trades, is_spot=is_spot,
            )
        else:
            result = self.fill_model.simulate_taker(
                side=side, intended_price=intended_price, size=size,
                orderbook=book, latency_ms=120,
                recent_volatility=vol, is_spot=is_spot,
            )

        if not result.filled:
            log.info(
                "PAPER fill rejected | %s %s @ %.6f x%.8f | type=%s | reason=%s",
                side, symbol, intended_price, size, result.fill_type,
                result.notes.get("reason", "unknown"),
            )
            return None

        # Compose notes for the trade row
        notes = {
            "confidence": round(confidence, 4),
            "ml_scale": round(ml_scale, 4),
            "fill_type": result.fill_type,
            "fees_usd": round(result.fees_usd, 6),
            "slippage_bps": round(result.slippage_bps, 2),
            "intended_price": round(intended_price, 8),
            "filled_size": round(result.filled_size, 8),
            "recent_vol": round(vol, 6),
            "fill_model_notes": result.notes,
        }
        if notes_extra:
            notes.update(notes_extra)

        # Derive ids for this trade (idempotent across retries)
        cli_id = make_client_order_id(
            strategy=strategy or f"{market}_directional",
            market=market,
            symbol=symbol,
            side=side,
            bar_ts=None,
            nonce=0,
        )
        corr_id = make_correlation_id()

        # Persist
        try:
            trade_id = record_trade(
                db_path=_DB_PATH,
                market=market, symbol=symbol,
                action=side,
                shares=result.filled_size,
                price=result.fill_price,
                signal=signal,
                regime=regime,
                risk_action="ALLOW",
                strategy=strategy,
                entry_time=datetime.now(timezone.utc).isoformat() if side == "BUY" else None,
                size_usd=round(result.fill_price * result.filled_size, 4),
                notes=notes,
                client_order_id=cli_id,
                correlation_id=corr_id,
            )
            log.info(
                "PAPER %s %s @ %.6f x%.8f | type=%s fees=$%.4f slip=%.1fbps "
                "| strat=%s | trade=%s",
                side, symbol, result.fill_price, result.filled_size,
                result.fill_type, result.fees_usd, result.slippage_bps,
                strategy, trade_id[:8],
            )
        except Exception as exc:
            log.error("PaperExecutor record_trade failed: %s", exc, exc_info=True)

        # Decision ledger fill event (best-effort)
        try:
            from foundation.decision_ledger import DecisionLedger
            DecisionLedger().fill(
                correlation_id=corr_id,
                symbol=symbol,
                market=market,
                side=side,
                fill_price=result.fill_price,
                fill_shares=result.filled_size,
                intended_price=intended_price,
                fees=result.fees_usd,
                slippage_bps=result.slippage_bps,
                client_order_id=cli_id,
            )
        except Exception as exc:
            log.debug("PaperExecutor ledger.fill skipped (non-fatal): %s", exc)

        return result
