"""
foundation/decision_ledger.py  —  Thin helper over foundation.audit_trail
=========================================================================

PURPOSE
-------
foundation/audit_trail.py is already excellent (SHA-256, immutable, query API).
This helper makes it ergonomic to instrument the live_paper_runner WITHOUT
adding 10 lines at every call site.

Closes Gap 5 (structured event log adoption) — every signal, decision,
intent, and order placement flows through a single function with a stable
`correlation_id` thread.

USAGE
-----
    from foundation.decision_ledger import DecisionLedger

    ledger = DecisionLedger()
    corr_id = ledger.start("BTC/USDT", "C2_momentum", "crypto")

    ledger.signal(corr_id, signal="BUY", regime="BULL_TREND",
                  confidence=0.72, vote_breakdown={"ema": "BUY", "rsi": "HOLD"})

    ledger.risk(corr_id, decision="ALLOW", reasons=["margin_ok", "size_ok"],
                size_adj=0.85)

    ledger.intent(corr_id, side="BUY", price=43210.5, shares=0.0012,
                  client_order_id="abc123...")

    ledger.fill(corr_id, fill_price=43215.0, fill_shares=0.0012,
                fees=0.043, slippage_bps=11.6)

    # OR for skip/error:
    ledger.skip(corr_id, reason="ML gate failed", details={"ml_conf": 0.38})
    ledger.error(corr_id, error_type="api_timeout", details={"exc": str(e)})

CORRELATION
-----------
Every entry written with the same `correlation_id` can be replayed in order
to reconstruct the full lifecycle of one trade intent — useful for daily
postmortem narratives.

PERFORMANCE
-----------
- audit_trail.append() is sync SQLite write ~1-3ms.
- For 6 strategies × 6 symbols × 4-5 entries per cycle = ~150 writes per
  15-min cycle = trivial cost.
"""

from __future__ import annotations

from typing import Any

from foundation.audit_trail import AuditTrail
from execution.idempotency import make_correlation_id


class DecisionLedger:
    """Convenience wrapper around AuditTrail with correlation_id threading."""

    def __init__(self, db_path: str = "data/audit_trail.db") -> None:
        self._trail = AuditTrail(db_path=db_path)

    # ── Lifecycle helpers ────────────────────────────────────────────────

    def start(self, symbol: str, strategy: str, market: str) -> str:
        """
        Begin a new decision thread. Returns a fresh correlation_id.

        Call this at the top of generate_signal() / execute() for each symbol
        in the cycle. Keep the returned id and pass it to all subsequent
        ledger calls for this intent.
        """
        corr_id = make_correlation_id()
        self._trail.append(
            market=market,
            module="decision_ledger",
            event_type="SIGNAL",
            details={
                "phase": "cycle_start",
                "correlation_id": corr_id,
                "symbol": symbol,
                "strategy": strategy,
            },
            result="GO",
            reason=f"cycle_start:{symbol}:{strategy}",
        )
        return corr_id

    def signal(
        self,
        correlation_id: str,
        symbol: str,
        market: str,
        signal: str,
        regime: str,
        confidence: float,
        vote_breakdown: dict[str, str] | None = None,
    ) -> None:
        """Record the strategy signal output."""
        self._trail.append(
            market=market,
            module="decision_ledger",
            event_type="SIGNAL",
            details={
                "phase": "signal",
                "correlation_id": correlation_id,
                "symbol": symbol,
                "signal": signal,
                "regime": regime,
                "confidence": round(confidence, 4),
                "vote_breakdown": vote_breakdown or {},
            },
            result="GO" if signal != "HOLD" else "NO_GO",
            reason=f"signal:{signal}:{regime}",
        )

    def risk(
        self,
        correlation_id: str,
        symbol: str,
        market: str,
        decision: str,
        reasons: list[str],
        size_adj: float = 1.0,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record the risk-engine decision."""
        result = "GO" if decision == "ALLOW" else ("NO_GO" if decision == "REDUCE" else "REJECTED")
        self._trail.append(
            market=market,
            module="decision_ledger",
            event_type="RISK_CHECK",
            details={
                "phase": "risk",
                "correlation_id": correlation_id,
                "symbol": symbol,
                "decision": decision,
                "reasons": reasons,
                "size_adj": round(size_adj, 4),
                **(details or {}),
            },
            result=result,
            reason=f"risk:{decision}:{','.join(reasons[:3])}",
        )

    def intent(
        self,
        correlation_id: str,
        symbol: str,
        market: str,
        side: str,
        price: float,
        shares: float,
        client_order_id: str,
        strategy: str,
    ) -> None:
        """Record the order intent (before broker submit / paper write)."""
        self._trail.append(
            market=market,
            module="decision_ledger",
            event_type="ORDER",
            details={
                "phase": "intent",
                "correlation_id": correlation_id,
                "symbol": symbol,
                "side": side,
                "price": round(price, 6),
                "shares": round(shares, 8),
                "notional": round(price * shares, 4),
                "client_order_id": client_order_id,
                "strategy": strategy,
            },
            result="GO",
            reason=f"intent:{side}:{symbol}",
        )

    def fill(
        self,
        correlation_id: str,
        symbol: str,
        market: str,
        side: str,
        fill_price: float,
        fill_shares: float,
        intended_price: float | None = None,
        fees: float = 0.0,
        slippage_bps: float | None = None,
        client_order_id: str | None = None,
    ) -> None:
        """Record the fill (after paper-trader records the trade)."""
        details = {
            "phase": "fill",
            "correlation_id": correlation_id,
            "symbol": symbol,
            "side": side,
            "fill_price": round(fill_price, 6),
            "fill_shares": round(fill_shares, 8),
            "fees": round(fees, 6),
        }
        if intended_price is not None:
            details["intended_price"] = round(intended_price, 6)
            details["price_diff_bps"] = round(
                (fill_price - intended_price) / max(intended_price, 1e-9) * 1e4, 2
            )
        if slippage_bps is not None:
            details["slippage_bps"] = round(slippage_bps, 2)
        if client_order_id:
            details["client_order_id"] = client_order_id

        self._trail.append(
            market=market,
            module="decision_ledger",
            event_type="ORDER",
            details=details,
            result="SUCCESS",
            reason=f"fill:{side}:{symbol}",
        )

    def skip(
        self,
        correlation_id: str,
        symbol: str,
        market: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a deliberate skip (sentiment gate, ML gate, sector cap, etc.)."""
        self._trail.append(
            market=market,
            module="decision_ledger",
            event_type="REJECTION",
            details={
                "phase": "skip",
                "correlation_id": correlation_id,
                "symbol": symbol,
                **(details or {}),
            },
            result="REJECTED",
            reason=f"skip:{reason}",
        )

    def error(
        self,
        correlation_id: str,
        symbol: str,
        market: str,
        error_type: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record an unexpected error during decision/execution path."""
        self._trail.append(
            market=market,
            module="decision_ledger",
            event_type="REJECTION",
            details={
                "phase": "error",
                "correlation_id": correlation_id,
                "symbol": symbol,
                "error_type": error_type,
                **(details or {}),
            },
            result="FAILURE",
            reason=f"error:{error_type}",
        )

    # ── Querying for postmortem / Grafana ────────────────────────────────

    def trace(self, correlation_id: str) -> list[dict[str, Any]]:
        """
        Return all entries for one correlation_id in chronological order.
        Used by daily postmortem and ad-hoc operator queries.
        """
        # AuditTrail.query() supports market/event_type filters but not
        # arbitrary detail fields. Filter in Python (correlation_id rare enough).
        all_entries = self._trail.query()
        return [
            e for e in all_entries
            if e["details"].get("correlation_id") == correlation_id
        ]
