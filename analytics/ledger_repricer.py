"""
Honest ledger re-pricer + no-trade baseline (forensic-audit Phase 2/3).

The live engine records GROSS PnL (raw prices, no costs — see
AUDIT/loss_attribution.md). This module re-reads the paper-trade ledger and
produces the number the mandate requires: PnL NET of fees + slippage (+ funding
for perps), benchmarked against the no-trade baseline ($0 flat book).

Pure read-only over the DB; no writes. Reuses analytics.cost_model so there is
one definition of trading cost in the repo.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from analytics import cost_model as cm

# Spot instruments today; flip to "perp" when/if the perp reconfig lands.
DEFAULT_INSTRUMENT: cm.Instrument = "spot"


@dataclass
class StrategyResult:
    strategy: str
    n: int = 0
    gross: float = 0.0
    fees: float = 0.0
    slippage: float = 0.0
    funding: float = 0.0
    net: float = 0.0
    wins_net: int = 0
    losses_net: int = 0

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "n": self.n,
            "gross": round(self.gross, 4),
            "fees": round(self.fees, 4),
            "slippage": round(self.slippage, 4),
            "funding": round(self.funding, 4),
            "net": round(self.net, 4),
            "wins_net": self.wins_net,
            "losses_net": self.losses_net,
        }


@dataclass
class Repricing:
    window_start: str | None
    window_end: str | None
    n_events: int
    per_strategy: dict[str, StrategyResult] = field(default_factory=dict)
    buckets: dict[str, dict] = field(default_factory=dict)

    @property
    def total_gross(self) -> float:
        return sum(s.gross for s in self.per_strategy.values())

    @property
    def total_net(self) -> float:
        return sum(s.net for s in self.per_strategy.values())

    @property
    def cost_ratio(self) -> float | None:
        """costs / gross-profit-of-winners. None when no positive gross exists.

        Reports how much of the gross edge is donated to the market. The mandate
        wants this minimized and reported.
        """
        gross_profit = sum(
            s.fees + s.slippage + s.funding for s in self.per_strategy.values()
        )
        positive_gross = sum(max(s.gross, 0.0) for s in self.per_strategy.values())
        if positive_gross <= 0:
            return None
        return gross_profit / positive_gross

    def beats_no_trade(self) -> bool:
        """The no-trade baseline is a flat $0 book. We beat it iff net > 0."""
        return self.total_net > 0.0

    def as_dict(self) -> dict:
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "n_events": self.n_events,
            "total_gross": round(self.total_gross, 4),
            "total_net": round(self.total_net, 4),
            "cost_ratio": (
                None if self.cost_ratio is None else round(self.cost_ratio, 3)
            ),
            "beats_no_trade_baseline": self.beats_no_trade(),
            "per_strategy": {k: v.as_dict() for k, v in self.per_strategy.items()},
            "buckets": self.buckets,
        }


def _exit_reason(row: dict) -> str:
    try:
        d = json.loads(row.get("notes") or "{}")
        return (d.get("exit_reason") or row.get("note") or "").lower()
    except Exception:
        return (row.get("note") or "").lower()


def _bucket(gross: float, net: float, exit_reason: str) -> str:
    """BUG / COST / SIGNAL / RISK per the mandate. BUG is never assigned here —
    code-defect detection lives in the reconciler/guards, not in re-pricing."""
    is_stop = any(
        k in exit_reason for k in ("stop", "z_hard", "z_trailing", "time_stop")
    )
    if gross < 0:
        return "RISK" if (is_stop and gross < -0.30) else "SIGNAL"
    return "COST" if net < 0 else "WIN"


def reprice_ledger(
    db_path: str,
    instrument: cm.Instrument = DEFAULT_INSTRUMENT,
    slippage_bps: float = cm.DEFAULT_SLIPPAGE_BPS,
    liquidity: cm.Liquidity = "taker",
    since: str | None = None,
    until: str | None = None,
) -> Repricing:
    """Read closed (realized-PnL) events and re-price them net of costs.

    A realized event = any row carrying a non-zero `pnl` (the closing leg).
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        q = "SELECT * FROM paper_trades WHERE pnl IS NOT NULL AND pnl != 0.0"
        params: list = []
        if since:
            q += " AND timestamp >= ?"
            params.append(since)
        if until:
            q += " AND timestamp <= ?"
            params.append(until)
        q += " ORDER BY timestamp"
        rows = [dict(r) for r in conn.execute(q, params)]
    finally:
        conn.close()

    rep = Repricing(
        window_start=rows[0]["timestamp"] if rows else None,
        window_end=rows[-1]["timestamp"] if rows else None,
        n_events=len(rows),
    )
    buckets: dict[str, dict] = {}
    for r in rows:
        strat = r.get("strategy") or "UNKNOWN"
        gross = float(r["pnl"])
        notional = float(r.get("size_usd") or r.get("value") or 0.0)
        c = cm.round_trip_cost(notional, notional, instrument, liquidity, slippage_bps)
        net = gross - c.total

        sr = rep.per_strategy.setdefault(strat, StrategyResult(strategy=strat))
        sr.n += 1
        sr.gross += gross
        sr.fees += c.fees
        sr.slippage += c.slippage
        sr.funding += c.funding
        sr.net += net
        if net > 0:
            sr.wins_net += 1
        else:
            sr.losses_net += 1

        b = _bucket(gross, net, _exit_reason(r))
        slot = buckets.setdefault(b, {"n": 0, "net": 0.0})
        slot["n"] += 1
        slot["net"] = round(slot["net"] + net, 4)

    rep.buckets = buckets
    return rep


def no_trade_baseline() -> float:
    """The flat book. Holds nothing, trades nothing. PnL is exactly 0."""
    return 0.0


def buy_and_hold_pnl(
    entry_price: float, exit_price: float, notional_usd: float
) -> float:
    """Optional reference book: buy `notional_usd` of an asset at entry_price and
    mark it at exit_price (one fee in, one fee out, no intermediate trading)."""
    if entry_price <= 0:
        return 0.0
    units = notional_usd / entry_price
    gross = units * (exit_price - entry_price)
    cost = cm.fee_usd(notional_usd, "spot", "taker") + cm.fee_usd(
        units * exit_price, "spot", "taker"
    )
    return gross - cost


if __name__ == "__main__":  # pragma: no cover - operator convenience
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "runtime/paper_trades.db"
    rep = reprice_ledger(path)
    print(json.dumps(rep.as_dict(), indent=2))
