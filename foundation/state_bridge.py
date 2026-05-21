"""foundation/state_bridge.py -- flag-aware strategy-state load/save bridge.

When ``USE_UNIFIED_LEDGER`` is OFF, state lives in a per-strategy JSON file
(legacy behavior; this is the production default through workstream B3).
When ON, state lives in the ``positions`` table via ``foundation.positions``.

The dict shape exposed to strategy code is identical either way:

    {symbol: {entry_price, entry_ts, size_usd, **strategy_metadata}}

Strategy-private fields (e.g. entry_z, max_z, entry_pct_b, symbol_vol) ride
as opaque metadata when the flag is ON (Q3=A opaque ``metadata_json``).

Spec: docs/specs/unified_positions_ledger.md
Decisions: docs/decisions/2026-05-21_ledger_spec_recommendations.md (Q4=A
behind a single env flag read once per process).
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any

from foundation import positions

_CORE_FIELDS = {"entry_price", "entry_ts", "size_usd"}
# Fields that load_state may surface from the DB row outside metadata.
# Saved-state dicts should not redundantly carry these as metadata keys.
_RESERVED_FIELDS = _CORE_FIELDS | {
    "market", "entry_shares", "entry_correlation_id",
}


def is_unified_ledger_enabled() -> bool:
    """Re-read the env flag.

    Strategies cache this value at module import per Q4=A, so flipping the
    flag mid-process is *intentionally* a no-op for already-loaded modules.
    Tests that need to exercise the alternate branch monkeypatch the
    cached attribute on the strategy module directly.
    """
    return os.environ.get("USE_UNIFIED_LEDGER", "").lower() in {
        "true", "1", "yes", "on",
    }


def load_state(
    strategy_id: str,
    market: str,
    state_file: pathlib.Path,
    *,
    use_unified: bool | None = None,
    db_path: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Return ``{symbol: pos_dict}`` for an open-position book.

    Args:
        strategy_id: e.g. ``"C3_altcoin_reversion"``.
        market: e.g. ``"crypto"`` / ``"india"`` / ``"us"``.
        state_file: legacy JSON path, used when the flag is OFF.
        use_unified: override for the env-flag check (used by tests).
        db_path: alternative SQLite path (used by tests).
    """
    on = is_unified_ledger_enabled() if use_unified is None else use_unified
    if on:
        rows = positions.list_positions(
            strategy=strategy_id, market=market, db_path=db_path,
        )
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            pos: dict[str, Any] = {
                "entry_price": r["entry_price"],
                "entry_ts":    r["entry_ts"],
                "size_usd":    r["size_usd"],
            }
            if r["metadata"]:
                pos.update(r["metadata"])
            out[r["symbol"]] = pos
        return out

    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(
    strategy_id: str,
    market: str,
    state: dict[str, Any],
    state_file: pathlib.Path,
    *,
    use_unified: bool | None = None,
    db_path: str | None = None,
) -> None:
    """Persist the strategy's open-position dict.

    Args:
        strategy_id / market / state_file / use_unified / db_path -- see
            ``load_state``.
        state: ``{symbol: pos_dict}`` -- the in-memory book to persist.
    """
    on = is_unified_ledger_enabled() if use_unified is None else use_unified
    if on:
        existing = {
            r["symbol"]: r for r in positions.list_positions(
                strategy=strategy_id, market=market, db_path=db_path,
            )
        }
        new_syms = set(state) - set(existing)
        gone_syms = set(existing) - set(state)
        kept_syms = set(state) & set(existing)

        # 1. Close positions removed from the in-memory book.
        for sym in gone_syms:
            positions.close_position(strategy_id, sym, db_path=db_path)

        # 2. Open positions newly added to the in-memory book.
        for sym in new_syms:
            pos = state[sym]
            entry_price = float(pos["entry_price"])
            size_usd = float(pos["size_usd"])
            entry_ts = str(pos["entry_ts"])
            # Prefer the actual filled quantity from record_trade rounding,
            # fall back to notional/price (matches existing strategy code
            # which has never stored entry_shares in state files).
            entry_shares = float(
                pos.get("entry_shares")
                or (size_usd / max(entry_price, 1e-9))
            )
            metadata = {
                k: v for k, v in pos.items()
                if k not in _RESERVED_FIELDS
            }
            positions.open_position(
                strategy=strategy_id,
                symbol=sym,
                market=market,
                entry_shares=entry_shares,
                entry_price=entry_price,
                size_usd=size_usd,
                entry_ts=entry_ts,
                correlation_id=pos.get("entry_correlation_id"),
                metadata=metadata or None,
                db_path=db_path,
            )

        # 3. Update metadata for surviving positions (e.g. C3 max_z).
        for sym in kept_syms:
            pos = state[sym]
            metadata = {
                k: v for k, v in pos.items()
                if k not in _RESERVED_FIELDS
            }
            positions.update_position_metadata(
                strategy=strategy_id,
                symbol=sym,
                metadata=metadata or None,
                db_path=db_path,
            )
        return

    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(state_file.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(state_file)
