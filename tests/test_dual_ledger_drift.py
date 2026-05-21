"""
Bounded-drift assertion for the dual-ledger (paper_positions.json vs paper_trades.db).

Track A.0 deliberately does NOT alter the writer paths in execution/ / trading/
this session — that's deferred to the unified-ledger sprint per
docs/decisions/2026-05-21_ledger_spec_recommendations.md.

Instead, this test pins the *baseline* of drift the system tolerates today.
Any new unmatched BUY symbol outside the baseline is a regression and fails
loudly. This makes the existing ledger debt observable as code, not folklore.

## Current baseline (2026-05-21, A.0 session)

`data/paper_trades.db` open BUYs without matching `data/paper_positions.json`:

  - **Stablecoins** (USDT, USDC, USD1, RLUSD, DAI, BUSD, TUSD, FDUSD) —
    benign zero-edge holdings; legs of stablecoin pairs.
  - **ADA** — held over from C5b funding_arb $25/leg asymmetry bug
    (docs/known_issues/2026-05-15_c5b_halt.md); C5b HALTed at source.
  - **U** — pre-existing unmatched BUY per
    docs/decisions/2026-05-22_live_flip_rebuild_plan.md §E.
  - **PENGU** — open C3 BUY pending SELL; matches a live position in
    `runtime/paper_positions.json` but not `data/paper_positions.json`.
    Surfaces the data/ vs runtime/ writer drift first noted in A.0 report.

`runtime/paper_trades.db` open BUYs (HALTed india leg):

  - **ICICIBANK** — N1 stat_arb_india pair leg; india HALTed at the
    container level (`--market crypto` in deployment/docker-compose.yml).
    No SELL can fire under current configuration.

## Rebaseline procedure

When the unified-ledger flag (`USE_UNIFIED_LEDGER=True`) flips on, the
bound shrinks to "no drift at all" — `_BASELINE_DRIFT_SYMBOLS` empties
and any unmatched BUY fails. Until then, edits to this list require:

  1. A new `docs/known_issues/` entry naming the symbol + reason.
  2. Operator sign-off per autonomy contract (money / risk / doctrine
     scope adjacent — adding to the exempt list is a doctrine-adjacent
     decision because it broadens "acceptable drift").
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


_STABLECOINS = {
    "USDT", "USDC", "USD1", "RLUSD", "DAI", "BUSD", "TUSD", "FDUSD",
}
# Documented baseline drift as of 2026-05-21. See module docstring for
# the rebaseline procedure. Do NOT add symbols here without a paired
# docs/known_issues/ entry + operator sign-off.
_BASELINE_DRIFT_SYMBOLS = _STABLECOINS | {
    "ADA",        # C5b residual
    "U",          # pre-existing unmatched BUY
    "PENGU",      # open C3 BUY, matches runtime/ ledger only
    "ICICIBANK",  # N1 india leg, container HALTed at crypto-only
}
_EXEMPT_SYMBOLS = _BASELINE_DRIFT_SYMBOLS


def _extract_base(symbol: str) -> str:
    """Strip a quote suffix from a trading pair, e.g. 'ADA/USDT' → 'ADA'."""
    return symbol.split("/")[0] if "/" in symbol else symbol


def _open_buy_symbols(db_path: Path) -> list[tuple[str, int, int]]:
    """Return [(symbol, buy_count, sell_count)] where buy_count > sell_count."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            """
            SELECT symbol,
                   SUM(CASE WHEN action='BUY'  THEN 1 ELSE 0 END) AS buys,
                   SUM(CASE WHEN action='SELL' THEN 1 ELSE 0 END) AS sells
              FROM paper_trades
             GROUP BY symbol
            """
        ).fetchall()
    finally:
        conn.close()
    return [(sym, int(b or 0), int(s or 0)) for sym, b, s in rows if (b or 0) > (s or 0)]


def _load_positions(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


@pytest.mark.parametrize(
    "data_root",
    [Path("data"), Path("runtime")],
    ids=["data", "runtime"],
)
def test_dual_ledger_drift_bounded(data_root: Path):
    """
    Open BUYs in paper_trades.db without a matching paper_positions.json
    entry are tolerated ONLY for symbols on the exemption list.

    Skips cleanly if the data dir doesn't exist (e.g. fresh checkout).
    """
    db_path = data_root / "paper_trades.db"
    positions_path = data_root / "paper_positions.json"

    if not db_path.exists():
        pytest.skip(f"{db_path} not present — bound has nothing to check")

    open_buys = _open_buy_symbols(db_path)
    if not open_buys:
        return  # no open BUYs → no drift possible

    positions = _load_positions(positions_path)
    crypto_positions = positions.get("crypto", {}) or {}
    india_positions = positions.get("india", {}) or {}
    known_position_symbols = (
        set(crypto_positions.keys()) | set(india_positions.keys())
    )

    unexplained = []
    for symbol, buys, sells in open_buys:
        base = _extract_base(symbol)
        if symbol in known_position_symbols or base in known_position_symbols:
            continue  # ledger agrees → no drift
        if base in _EXEMPT_SYMBOLS:
            continue  # documented exception
        unexplained.append((symbol, buys, sells))

    assert not unexplained, (
        f"Dual-ledger drift exceeded documented bound in {data_root}/. "
        f"Unmatched BUYs without exemption: {unexplained}. "
        f"Either (a) the writer path regressed and a new symbol class is leaking, "
        f"or (b) the exemption list in this test needs updating with operator sign-off."
    )
