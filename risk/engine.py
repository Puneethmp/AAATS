"""
Central Risk Engine for AAATS.

Aggregates portfolio-level, market-level, and per-trade risk checks
into a single decision gate. Every order must pass through this engine.

Kill switch thresholds (non-negotiable):
  Portfolio:  -20% total drawdown → halt ALL markets
  Per market: -15% drawdown in any market → halt that market
  Per trade:  -2% max loss from entry → close position immediately

The engine does NOT execute orders — it returns RiskDecision objects
that the execution layer acts on. This keeps risk logic pure and testable.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from foundation.logger import get_logger

try:
    from config.doctrine import LOCKED_STARTING_EQUITY
except Exception:
    # Fallback if config.doctrine import fails (e.g. test scaffolding before
    # the module is on sys.path). The doctrinal value must stay in lockstep
    # with config/doctrine.py.
    LOCKED_STARTING_EQUITY = 110.0

_log = get_logger("risk", "engine")

# ── Hard-coded kill switch thresholds ─────────────────────────────────────────
PORTFOLIO_DRAWDOWN_HALT = -0.20   # -20% total portfolio
MARKET_DRAWDOWN_HALT = -0.15      # -15% per market
PER_TRADE_MAX_LOSS = -0.02        # -2% per trade from entry

# Persisted drawdown-peak state. Restarts must NOT lose the high-water mark,
# otherwise a halt-triggering drawdown silently resets to 0% on every reboot.
#
# Per-mode isolation (A.1, 2026-05-23): the state file path is chosen by the
# discriminator below so paper-mode and live-mode peaks/drawdowns do NOT
# inherit across a mode flip. See docs/decisions/2026-05-22_state_isolation_design.md.
def _state_file_path() -> Path:
    """Return the per-mode risk-engine state file path.

    Discriminator precedence (highest first):
      1. ``AAATS_RISK_STATE_FILE`` -- fully-qualified path override (wins).
      2. ``SYSTEM__TRADING_MODE`` + ``AAATS_RISK_STATE_DIR`` -- composed
         per-mode path (``risk_engine_state.<mode>.json``).
      3. Legacy default ``/app/data/state/risk_engine_state.json`` -- no
         mode suffix, preserved for callers (tests, local scripts) that
         do not set ``SYSTEM__TRADING_MODE``.
    """
    explicit = os.environ.get("AAATS_RISK_STATE_FILE")
    if explicit:
        return Path(explicit)
    mode = os.environ.get("SYSTEM__TRADING_MODE")
    state_dir = Path(os.environ.get("AAATS_RISK_STATE_DIR", "/app/data/state"))
    if mode in ("paper", "live"):
        return state_dir / f"risk_engine_state.{mode}.json"
    return state_dir / "risk_engine_state.json"


STATE_FILE = _state_file_path()

Action = Literal["ALLOW", "REDUCE", "HALT_MARKET", "HALT_ALL", "CLOSE_POSITION"]


@dataclass
class RiskDecision:
    action: Action
    reason: str
    market: str = ""
    allowed_fraction: float = 1.0   # 0.0–1.0; 1.0 = full size allowed


@dataclass
class MarketState:
    peak_value: float
    current_value: float

    @property
    def drawdown(self) -> float:
        if self.peak_value <= 0:
            return 0.0
        return (self.current_value - self.peak_value) / self.peak_value

    def update(self, current_value: float) -> None:
        self.current_value = current_value
        if current_value > self.peak_value:
            self.peak_value = current_value


@dataclass
class RiskEngine:
    """
    Stateful risk engine tracking portfolio and per-market values.

    Usage:
        engine = RiskEngine(initial_portfolio=100_000)
        engine.update_market("us", 50_000)
        decision = engine.check_new_order("us", entry_price=100, shares=10, capital=50_000)
        if decision.action == "ALLOW":
            place_order(...)
    """

    initial_portfolio: float
    _portfolio_peak: float = field(init=False)
    _portfolio_current: float = field(init=False)
    _markets: dict[str, MarketState] = field(default_factory=dict, init=False)
    _halted_markets: set[str] = field(default_factory=set, init=False)
    _all_halted: bool = field(default=False, init=False)
    _loaded_market_peaks: dict[str, float] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        persisted = self._load_persisted_state()
        loaded_peak = persisted.get("peak")
        if loaded_peak is not None:
            self._portfolio_peak = loaded_peak
            _log.info(
                f"Risk engine peak loaded from {STATE_FILE}: ${loaded_peak:.2f}"
            )
        else:
            self._portfolio_peak = max(self.initial_portfolio, LOCKED_STARTING_EQUITY)
            _log.info(
                f"Risk engine peak seeded from doctrine: ${self._portfolio_peak:.2f} "
                f"(initial={self.initial_portfolio:.2f}, locked={LOCKED_STARTING_EQUITY:.2f})"
            )
        self._portfolio_current = self.initial_portfolio
        self._loaded_market_peaks = persisted.get("market_peaks", {})
        if self._loaded_market_peaks:
            peaks_str = ", ".join(
                f"{m}=${v:.2f}" for m, v in self._loaded_market_peaks.items()
            )
            _log.info(f"Risk engine market peaks loaded from {STATE_FILE}: {peaks_str}")

    @staticmethod
    def _load_persisted_state() -> dict:
        """Read persisted risk-engine state from STATE_FILE.

        Returns:
            dict with optional keys ``peak`` (portfolio high-water mark) and
            ``market_peaks`` (dict[str, float] of per-market high-water marks).
            Empty dict on miss or unreadable file. Backward-compatible with
            the pre-2026-05-18 schema that lacks ``market_peaks``.
        """
        try:
            if not STATE_FILE.exists():
                return {}
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            out: dict = {}
            peak = float(data.get("peak", 0.0))
            if peak > 0:
                out["peak"] = peak
            raw_peaks = data.get("market_peaks", {})
            if isinstance(raw_peaks, dict):
                valid = {
                    str(m): float(v)
                    for m, v in raw_peaks.items()
                    if isinstance(v, (int, float)) and float(v) > 0
                }
                if valid:
                    out["market_peaks"] = valid
            return out
        except Exception as exc:
            _log.warning(
                f"Risk engine state file unreadable ({exc}); falling back to doctrine"
            )
            return {}

    def _persist_state(self) -> None:
        """Atomically persist portfolio + per-market peaks to STATE_FILE.

        Called after every update_portfolio / update_market so a process
        restart cannot reset any high-water mark — without this, per-market
        peaks were in-memory only and silently reset on container recreate.
        """
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "peak": float(self._portfolio_peak),
                "last_update_ts": time.time(),
                "last_equity": float(self._portfolio_current),
                "market_peaks": {
                    m: float(s.peak_value) for m, s in self._markets.items()
                },
            }
            tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, STATE_FILE)
        except Exception as exc:
            _log.warning(f"Failed to persist risk engine state to {STATE_FILE}: {exc}")

    # ── State updates ─────────────────────────────────────────────────────────

    def update_portfolio(self, current_value: float) -> RiskDecision:
        """
        Update total portfolio value and check portfolio-level kill switch.

        Returns:
            RiskDecision with HALT_ALL if drawdown > 20%, else ALLOW.
        """
        if current_value > self._portfolio_peak:
            self._portfolio_peak = current_value
        self._portfolio_current = current_value

        # Persist after every update so a restart cannot reset the peak.
        self._persist_state()

        if self._portfolio_peak <= 0:
            dd = 0.0
        else:
            dd = (self._portfolio_current - self._portfolio_peak) / self._portfolio_peak
        if dd <= PORTFOLIO_DRAWDOWN_HALT:
            self._all_halted = True
            reason = (
                f"Portfolio drawdown {dd:.1%} breached {PORTFOLIO_DRAWDOWN_HALT:.0%} halt threshold"
            )
            _log.error(f"HALT ALL MARKETS — {reason}")
            return RiskDecision(action="HALT_ALL", reason=reason, allowed_fraction=0.0)

        _log.debug(f"Portfolio drawdown {dd:.1%} — within limits")
        return RiskDecision(action="ALLOW", reason="Portfolio within limits")

    def update_market(self, market: str, current_value: float) -> RiskDecision:
        """
        Update a market's value and check market-level kill switch.

        Args:
            market:        "us", "india", or "crypto".
            current_value: Current market portfolio value.

        Returns:
            RiskDecision with HALT_MARKET if drawdown > 15%, else ALLOW.
        """
        if market not in self._markets:
            # Seed peak from persisted high-water mark when available; else
            # from the current value. ``max`` guards against a stale persisted
            # peak being lower than what we observe right now — we'd never
            # want to discard newly-observed information.
            seed_peak = max(
                self._loaded_market_peaks.get(market, 0.0),
                current_value,
            )
            self._markets[market] = MarketState(
                peak_value=seed_peak, current_value=current_value
            )
        state = self._markets[market]
        state.update(current_value)

        # Persist after every update — per-market peaks must survive restarts
        # or the kill switch silently resets on every container recreate.
        self._persist_state()

        dd = state.drawdown
        if dd <= MARKET_DRAWDOWN_HALT:
            self._halted_markets.add(market)
            reason = (
                f"{market.upper()} drawdown {dd:.1%} breached "
                f"{MARKET_DRAWDOWN_HALT:.0%} halt threshold"
            )
            _log.error(f"HALT {market.upper()} — {reason}")
            return RiskDecision(
                action="HALT_MARKET", reason=reason, market=market, allowed_fraction=0.0
            )

        return RiskDecision(
            action="ALLOW",
            reason=f"{market.upper()} drawdown {dd:.1%} within limits",
            market=market,
        )

    # ── Order gate ────────────────────────────────────────────────────────────

    def check_new_order(
        self,
        market: str,
        entry_price: float,
        shares: int,
        capital: float,
    ) -> RiskDecision:
        """
        Gate a proposed new order through all risk checks.

        Args:
            market:      Market name ("us", "india", "crypto").
            entry_price: Proposed entry price per share/unit.
            shares:      Number of shares/units to buy.
            capital:     Total capital allocated to this market.

        Returns:
            RiskDecision. Action is "ALLOW" only if all checks pass.
        """
        if self._all_halted:
            return RiskDecision(
                action="HALT_ALL",
                reason="All markets halted (portfolio drawdown)",
                market=market,
                allowed_fraction=0.0,
            )

        if market in self._halted_markets:
            return RiskDecision(
                action="HALT_MARKET",
                reason=f"{market.upper()} is halted (market drawdown)",
                market=market,
                allowed_fraction=0.0,
            )

        # Per-trade size check: order value <= 2% of capital
        order_value = entry_price * shares
        if capital > 0:
            order_pct = order_value / capital
            max_order_pct = abs(PER_TRADE_MAX_LOSS)  # 2%
            if order_pct > max_order_pct:
                reduced_shares = max(int(capital * max_order_pct / entry_price), 1)
                _log.warning(
                    f"Order size {order_pct:.1%} exceeds {max_order_pct:.0%} limit — "
                    f"reducing from {shares} to {reduced_shares} shares"
                )
                return RiskDecision(
                    action="REDUCE",
                    reason=f"Order value {order_pct:.1%} of capital exceeds 2% limit",
                    market=market,
                    allowed_fraction=max_order_pct / order_pct,
                )

        return RiskDecision(
            action="ALLOW",
            reason="All risk checks passed",
            market=market,
            allowed_fraction=1.0,
        )

    def check_open_position(
        self,
        market: str,
        entry_price: float,
        current_price: float,
    ) -> RiskDecision:
        """
        Check whether an open position should be closed via per-trade stop.

        Args:
            market:        Market name.
            entry_price:   Original entry price.
            current_price: Current price.

        Returns:
            CLOSE_POSITION if loss >= 2%, else ALLOW.
        """
        if entry_price <= 0:
            return RiskDecision(action="ALLOW", reason="Invalid entry price", market=market)

        pnl_pct = (current_price - entry_price) / entry_price
        if pnl_pct <= PER_TRADE_MAX_LOSS:
            reason = f"Per-trade stop triggered: {pnl_pct:.1%} loss on {market.upper()}"
            _log.warning(reason)
            return RiskDecision(
                action="CLOSE_POSITION", reason=reason, market=market, allowed_fraction=0.0
            )

        return RiskDecision(action="ALLOW", reason=f"Position PnL {pnl_pct:.1%}", market=market)

    # ── Status ────────────────────────────────────────────────────────────────

    def is_market_halted(self, market: str) -> bool:
        return market in self._halted_markets or self._all_halted

    def is_all_halted(self) -> bool:
        return self._all_halted

    def portfolio_drawdown(self) -> float:
        if self._portfolio_peak <= 0:
            return 0.0
        return (self._portfolio_current - self._portfolio_peak) / self._portfolio_peak

    def market_drawdown(self, market: str) -> float:
        state = self._markets.get(market)
        return state.drawdown if state else 0.0

    def reset_market(self, market: str) -> None:
        """Re-enable a halted market after human review."""
        self._halted_markets.discard(market)
        _log.warning(f"Market {market.upper()} halt cleared by human operator")

    def reset_all(self) -> None:
        """Re-enable all markets after human review."""
        self._all_halted = False
        self._halted_markets.clear()
        _log.warning("All market halts cleared by human operator")
