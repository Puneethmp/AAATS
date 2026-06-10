"""
Transaction-cost model — the single source of truth for fees, slippage and
funding in AAATS honest-PnL accounting.

WHY THIS EXISTS (forensic-audit Phase 2, 2026-06-10)
----------------------------------------------------
The live PnL path (C1/C3/C6 in trading/*.py) records gross signal PnL from RAW
prices: zero fees, zero slippage, zero funding. The Phase 0 loss attribution
(AUDIT/loss_attribution.md) showed the ledger is therefore optimistic by ~$5-11
on a $110 book over 17 days, and that even the GROSS number is already negative.

This module makes cost accounting explicit and testable so that every reported
PnL number can be net of costs (the mandate forbids gross-only reporting). It is
pure (no I/O, no global state) so it can be unit-tested and reused by the
ledger repricer, the no-trade baseline and the weekly report.

Rates mirror execution/fill_model.py (Binance VIP-0) so there is ONE definition
of the cost of trading in the repo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ---- Binance VIP-0 fee schedule (bps = basis points = 0.01%) ----------------
# Mirrors execution/fill_model.py:110-113. Keep these two in sync.
SPOT_TAKER_BPS = 10.0  # 0.10%
SPOT_MAKER_BPS = 10.0  # 0.10%
PERP_TAKER_BPS = 5.0  # 0.05% USDT-M
PERP_MAKER_BPS = 2.0  # 0.02% USDT-M

# Default modeled slippage per side. Majors are tighter than this; small alts
# (the bulk of C3/C6 volume) are frequently worse. 10 bps/side is a deliberately
# conservative-but-not-extreme placeholder used ONLY when a realized slippage
# figure is not available. Always prefer measured slippage when you have it.
DEFAULT_SLIPPAGE_BPS = 10.0

Instrument = Literal["spot", "perp"]
Liquidity = Literal["taker", "maker"]

_BPS = 1e-4


def fee_bps(instrument: Instrument = "spot", liquidity: Liquidity = "taker") -> float:
    """Return the fee in bps for the given instrument / liquidity side."""
    table = {
        ("spot", "taker"): SPOT_TAKER_BPS,
        ("spot", "maker"): SPOT_MAKER_BPS,
        ("perp", "taker"): PERP_TAKER_BPS,
        ("perp", "maker"): PERP_MAKER_BPS,
    }
    return table[(instrument, liquidity)]


def fee_usd(
    notional_usd: float,
    instrument: Instrument = "spot",
    liquidity: Liquidity = "taker",
) -> float:
    """Exchange fee for a single fill of `notional_usd`. Always >= 0."""
    return abs(notional_usd) * fee_bps(instrument, liquidity) * _BPS


def slippage_usd(
    notional_usd: float, slippage_bps: float = DEFAULT_SLIPPAGE_BPS
) -> float:
    """Slippage cost for a single fill. Always >= 0 (cost is never a benefit)."""
    return abs(notional_usd) * abs(slippage_bps) * _BPS


def funding_usd(
    notional_usd: float,
    funding_rate: float,
    intervals: int = 1,
    side: Literal["long", "short"] = "long",
) -> float:
    """
    Funding paid (+) or received (-) for a perp position held across
    `intervals` funding settlements.

    Convention: when funding_rate > 0, longs PAY shorts. So a long returns a
    POSITIVE cost (drag) and a short returns a NEGATIVE cost (credit). Spot has
    no funding -> callers pass funding_rate=0.
    """
    flow = abs(notional_usd) * funding_rate * intervals
    return flow if side == "long" else -flow


@dataclass(frozen=True)
class RoundTripCost:
    fees: float
    slippage: float
    funding: float

    @property
    def total(self) -> float:
        return self.fees + self.slippage + self.funding

    def as_dict(self) -> dict[str, float]:
        return {
            "fees": round(self.fees, 6),
            "slippage": round(self.slippage, 6),
            "funding": round(self.funding, 6),
            "total": round(self.total, 6),
        }


def round_trip_cost(
    entry_notional_usd: float,
    exit_notional_usd: float | None = None,
    instrument: Instrument = "spot",
    liquidity: Liquidity = "taker",
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    funding_rate: float = 0.0,
    funding_intervals: int = 0,
    side: Literal["long", "short"] = "long",
) -> RoundTripCost:
    """
    Total cost of opening AND closing one position.

    entry/exit notional default to equal if exit is None (good enough when only
    the entry size is known). Fees and slippage apply on BOTH legs; funding
    applies once across the holding period (`funding_intervals` settlements).
    """
    if exit_notional_usd is None:
        exit_notional_usd = entry_notional_usd
    fees = fee_usd(entry_notional_usd, instrument, liquidity) + fee_usd(
        exit_notional_usd, instrument, liquidity
    )
    slip = slippage_usd(entry_notional_usd, slippage_bps) + slippage_usd(
        exit_notional_usd, slippage_bps
    )
    fund = (
        funding_usd(entry_notional_usd, funding_rate, funding_intervals, side)
        if funding_intervals > 0
        else 0.0
    )
    return RoundTripCost(fees=fees, slippage=slip, funding=fund)


def net_pnl(
    gross_pnl: float,
    entry_notional_usd: float,
    exit_notional_usd: float | None = None,
    instrument: Instrument = "spot",
    liquidity: Liquidity = "taker",
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    funding_rate: float = 0.0,
    funding_intervals: int = 0,
    side: Literal["long", "short"] = "long",
) -> float:
    """gross_pnl minus all round-trip costs. THE number to report."""
    cost = round_trip_cost(
        entry_notional_usd,
        exit_notional_usd,
        instrument,
        liquidity,
        slippage_bps,
        funding_rate,
        funding_intervals,
        side,
    )
    return gross_pnl - cost.total
