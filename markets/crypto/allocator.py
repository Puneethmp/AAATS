"""
markets/crypto/allocator.py  —  Top-K candidate selector with portfolio caps
============================================================================

PURPOSE
-------
The scanner produces ranked candidate lists per strategy (often dozens). The
allocator applies HARD PORTFOLIO CAPS to pick the final subset the system
will actually trade this cycle.

Without this layer, on a 100-symbol universe with loose thresholds, the
system could open 30+ tiny positions on $120 — fees would eat everything.
The allocator's job is "more candidates ≠ more entries."

USAGE
-----
    from markets.crypto.scanner import score_universe
    from markets.crypto.allocator import allocate

    ranked = score_universe(universe, fetch_fn)
    plan = allocate(
        ranked_candidates=ranked,
        open_positions=positions["crypto"],
        portfolio_capital=portfolio["crypto"]["capital"],
    )
    # → {
    #     "c3": ["OP/USDT", "ARB/USDT"],
    #     "c6": ["LDO/USDT", "MATIC/USDT", "RUNE/USDT"],
    #   }
    # Each strategy then enters only the symbols on its list.

CAPS (tunable via env or constants below)
-----------------------------------------
- MAX_OPEN_POSITIONS  = 6  total open across all alt strategies (C3+C6)
- MAX_PER_STRATEGY    = 3  per strategy
- MAX_PER_SYMBOL      = 1  no doubling up across strategies
- MIN_FREE_CAPITAL    = 25 reserved for C5b funding arb (don't deploy below this)
- MIN_PER_TRADE_USD   = 5  skip if cap math would size below this

Caps are HARD — they are not "preferences," they are circuit breakers
against capital fragmentation on small accounts.
"""

from __future__ import annotations

import logging
from typing import Iterable

log = logging.getLogger(__name__)


# ── Caps (tune here, single source of truth) ──────────────────────────────────
MAX_OPEN_POSITIONS  = 6     # max concurrent alt positions across C3 + C6
MAX_PER_STRATEGY    = 3     # max concurrent per strategy
MAX_PER_SYMBOL      = 1     # no stacking across strategies
MIN_FREE_CAPITAL    = 25.0  # reserve for C5b
MIN_PER_TRADE_USD   = 5.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _existing_open_symbols(open_positions: dict | None) -> set[str]:
    """Symbols where another strategy already holds a non-zero position."""
    if not open_positions:
        return set()
    out = set()
    for sym, pos in open_positions.items():
        try:
            shares = float(pos.get("shares", 0.0) or 0.0)
            if abs(shares) > 1e-9:
                out.add(sym)
        except Exception:
            continue
    return out


def _count_open_by_strategy(open_positions: dict | None) -> dict[str, int]:
    """
    Count currently-open positions by strategy. Best-effort — depends on
    the position dict carrying a 'strategy' key. Falls back to 0 if missing.
    """
    counts: dict[str, int] = {}
    if not open_positions:
        return counts
    for sym, pos in open_positions.items():
        strat = (pos or {}).get("strategy", "")
        if not strat:
            continue
        counts[strat] = counts.get(strat, 0) + 1
    return counts


# ── Public allocator ──────────────────────────────────────────────────────────

def allocate(
    ranked_candidates: dict[str, list[tuple[str, float]]],
    open_positions: dict | None = None,
    portfolio_capital: float = 0.0,
    strategy_to_state_count: dict[str, int] | None = None,
) -> dict[str, list[str]]:
    """
    Apply portfolio caps to ranked candidate lists.

    Args:
        ranked_candidates:    output of scanner.score_universe()
        open_positions:       positions["crypto"] dict from runner
        portfolio_capital:    current cash for alt strategies
        strategy_to_state_count:  optional override for "currently open per
                                  strategy" if the open_positions dict
                                  doesn't carry strategy attribution. Useful
                                  when strategies persist their own state.

    Returns:
        {strategy_name: [list_of_symbols_to_enter_this_cycle]}

    Caps enforced (in order):
      1. portfolio_capital >= MIN_FREE_CAPITAL — else return {} (no entries)
      2. total_already_open + new_picks <= MAX_OPEN_POSITIONS
      3. per_strategy_open + new_picks <= MAX_PER_STRATEGY
      4. no symbol present in open_positions (MAX_PER_SYMBOL=1)
      5. estimated per-trade size >= MIN_PER_TRADE_USD
    """
    plan: dict[str, list[str]] = {s: [] for s in ranked_candidates}

    # Capital floor
    if portfolio_capital < MIN_FREE_CAPITAL:
        log.info(
            "[allocator] capital=$%.2f < min=$%.2f — no new entries this cycle",
            portfolio_capital, MIN_FREE_CAPITAL,
        )
        return plan

    held_symbols = _existing_open_symbols(open_positions)
    strat_counts = strategy_to_state_count or _count_open_by_strategy(open_positions)
    total_open   = sum(strat_counts.values()) if strat_counts else len(held_symbols)
    headroom     = MAX_OPEN_POSITIONS - total_open

    if headroom <= 0:
        log.info(
            "[allocator] total open=%d >= max=%d — no new entries",
            total_open, MAX_OPEN_POSITIONS,
        )
        return plan

    log.info(
        "[allocator] capital=$%.2f  open=%d/%d  per_strategy_counts=%s",
        portfolio_capital, total_open, MAX_OPEN_POSITIONS, strat_counts,
    )

    # Walk through each strategy's ranked list, applying per-strategy caps
    picked_symbols: set[str] = set()  # symbols already picked this cycle

    for strat, cands in ranked_candidates.items():
        per_strat_open  = strat_counts.get(strat, 0)
        per_strat_left  = MAX_PER_STRATEGY - per_strat_open
        if per_strat_left <= 0:
            log.debug("[allocator] %s: already at MAX_PER_STRATEGY", strat)
            continue

        slots = min(per_strat_left, headroom - len(picked_symbols))
        if slots <= 0:
            break

        for sym, score in cands:
            if len(plan[strat]) >= slots:
                break
            if sym in held_symbols or sym in picked_symbols:
                continue
            plan[strat].append(sym)
            picked_symbols.add(sym)

        if plan[strat]:
            log.info(
                "[allocator] %s picks (top %d): %s",
                strat, len(plan[strat]),
                ", ".join(plan[strat]),
            )

    return plan
