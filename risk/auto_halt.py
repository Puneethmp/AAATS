"""
Layer L9 — persistent auto-halt at portfolio-DD doctrine threshold.

Content-correctness sprint 2026-05-24, operator-departure D.5 paper soak.

Why this exists:
  The risk engine's in-memory `_halted_markets` set is rebuilt on every
  cycle from the persisted peak. If the container restarts AND the equity
  rebounds slightly above the halt threshold before the next cycle, the
  in-memory halt vanishes. Under operator-away, "bot rides position to
  -30% because container restarted and lost in-memory halt" is the worst
  plausible outcome of the soak.

Behavior:
  - One-way trigger: when any active market's drawdown crosses the
    doctrine threshold (-20% by default), the OPERATOR halt channel is
    set (data/halt_state.json) via foundation.kill_switch.halt(). This
    is the same channel kill.py CLI writes to and survives container
    restart by design.
  - NEVER auto-resets. Operator must manually reset via kill.py on return.
    The Telegram alert message makes this explicit.
  - Idempotent: a market that is already operator-halted is not re-alerted.

Wired into:
  trading/live_paper_runner.py:run_crypto (top of cycle, after the L5
  ledger-divergence check).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from foundation.logger import get_logger
from foundation.kill_switch import halt, is_halted

_log = get_logger("risk", "auto_halt")

# Doctrine threshold: at or below this drawdown, halt fires. Negative number.
DOCTRINE_HALT_DD = -0.20

# Which markets to evaluate. Markets that are already operator-halted (e.g.
# india + us during the D.5 soak) are visited but skipped because their
# equity is static — no DD ever accumulates against a flat book. The order
# is deterministic so the same offending market fires first on every cycle.
DEFAULT_ACTIVE_MARKETS: tuple[str, ...] = ("crypto",)


def _data_dir() -> Path:
    return Path(os.environ.get("AAATS_DATA", "/app/data"))


def _read_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_state_notional_for_market(market: str) -> float:
    """Sum of open position notionals for the named market.

    All current strategies are crypto-side; india/us have no state files
    today and return 0.0. Imports lazily so a missing execution.paper_trader
    (during testing) doesn't take out L9.
    """
    if market != "crypto":
        return 0.0
    try:
        from execution.paper_trader import _read_state_notional  # type: ignore

        return float(sum(_read_state_notional().values()))
    except Exception:
        return 0.0


def _compute_market_dd(
    market: str, data_dir: Path | None = None
) -> tuple[float, float, float]:
    """Returns (drawdown_frac, current_equity, market_peak) for the named market.

    drawdown_frac is signed: -0.20 == -20%. Returns (0.0, 0.0, 0.0) if the
    peak is unknown (cannot evaluate). Designed to be testable: callers
    can pass a fake data_dir for adversarial tests.
    """
    if data_dir is None:
        data_dir = _data_dir()
    eng = _read_json(data_dir / "state-paper" / "risk_engine_state.paper.json")
    port = _read_json(data_dir / "paper_portfolio.json")
    peak = float((eng.get("market_peaks") or {}).get(market) or 0.0)
    mkt_block = (port.get(market) or {}) if isinstance(port, dict) else {}
    capital = float(mkt_block.get("capital") or 0.0)
    deployed = (
        _read_state_notional_for_market(market) if data_dir == _data_dir() else 0.0
    )
    equity = capital + deployed
    if peak <= 0:
        return 0.0, equity, 0.0
    dd = (equity - peak) / peak
    return dd, equity, peak


def check_and_persist_doctrine_halt(
    markets: Iterable[str] | None = None,
    data_dir: Path | None = None,
    threshold: float = DOCTRINE_HALT_DD,
) -> list[str]:
    """Once per cycle. For each active market whose drawdown ≤ threshold:
       1. Set the operator halt channel via foundation.kill_switch.halt
          (persists to data/halt_state.json — survives restart).
       2. Fire a Telegram alert via observability.alerts (called by halt()).
       3. Log loudly so the runner cycle summary surfaces it.

    Returns the list of markets that were halted by this call. Markets
    that were already operator-halted are skipped (no duplicate alert).

    This is a ONE-WAY trigger by design. Operator must reset manually via
    kill.py on return — the Telegram message makes that explicit so a
    panic-reset by another sleeping operator-tool doesn't happen automatically.
    """
    if markets is None:
        markets = DEFAULT_ACTIVE_MARKETS
    halted_now: list[str] = []
    for market in markets:
        try:
            if is_halted(market):
                # Already in operator-halt — possibly by us on a prior cycle,
                # possibly by manual kill.py. Either way, don't re-alert.
                continue
            dd, equity, peak = _compute_market_dd(market, data_dir=data_dir)
            if peak <= 0:
                # Unknown peak — cannot evaluate. The engine will write a peak
                # on its first cycle; until then we cannot decide.
                continue
            if dd <= threshold:
                reason = (
                    f"L9 auto-doctrine halt: {market} drawdown {dd*100:.2f}% "
                    f"(equity ${equity:.2f} vs peak ${peak:.2f}, "
                    f"threshold {threshold*100:.0f}%). "
                    f"OPERATOR MUST RESET MANUALLY via kill.py on return — "
                    f"do NOT remote-reset; full audit required first per "
                    f"docs/runbooks/operator_return_resume_procedure.md."
                )
                halt(market=market, reason=reason, triggered_by="L9_auto_halt")
                halted_now.append(market)
                _log.error(
                    "L9 AUTO-HALT FIRED market={} dd={:.4f} equity={:.2f} peak={:.2f}",
                    market,
                    dd,
                    equity,
                    peak,
                )
        except Exception as exc:
            _log.warning(
                "L9 check failed for market={}: {} — continuing",
                market,
                exc,
            )
    return halted_now
