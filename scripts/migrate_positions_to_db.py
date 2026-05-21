"""scripts/migrate_positions_to_db.py — one-time positions ledger migration.

Spec: docs/specs/unified_positions_ledger.md (section "Migration plan").
Decisions: docs/decisions/2026-05-21_ledger_spec_recommendations.md (Q1-Q4=A).

What it does
------------
1. Walks data/*_state.json (excludes *cooldown*.json, halt_state.json).
2. For every (symbol, pos) pair:
     - Maps state file -> strategy ID via STATE_FILE_TO_STRATEGY.
     - Looks up the matching BUY row in paper_trades.db by
       (strategy, symbol, ts ~ entry_ts +/- 5min) and copies the *real*
       shares value -- this heals the TON/FET-class exit-sizing residuals
       retroactively.
     - Fallback: if no matching BUY row is found within +/-5min, falls
       back to size_usd / entry_price + logs a warning.
3. Inserts the row into the `positions` table via foundation.positions.
4. Renames each migrated state file to <name>.migrated_2026-05-21 (does NOT
   delete -- keeps one rollback cycle).
5. Prints before/after counts and any fallback warnings.

Idempotency
-----------
Safe to re-run *only after* renames roll the source files out of glob
range. If you re-run before then, INSERT will fail on the composite-PK
collision (intentional -- prevents accidental dual-write).

Hard constraints (per NEXT_PROMPT.md 2026-05-21):
- USE_UNIFIED_LEDGER stays OFF in production after this script runs.
- C5b funding_arb stays halted at source; funding_arb_state.json is
  migrated only if present (likely empty -- the strategy doesn't open).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

# Resolve module path when invoked as a script.
_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from foundation import positions

# Map state-file basename -> strategy ID used in paper_trades.strategy column.
STATE_FILE_TO_STRATEGY: dict[str, str] = {
    "altcoin_reversion_state.json": "C3_altcoin_reversion",
    "bollinger_range_state.json":   "C6_bollinger_range",
    "stat_arb_state.json":          "C1_stat_arb",
    "momentum_state.json":          "C2_momentum",
    "funding_arb_state.json":       "C5b_funding_arb",
}

# Files in data/ that look like state files but are NOT positions ledgers.
EXCLUDED_NAMES: set[str] = {"halt_state.json"}

MATCH_WINDOW = timedelta(minutes=5)
DEFAULT_MARKET = "crypto"


def _strategy_from_filename(name: str) -> str | None:
    return STATE_FILE_TO_STRATEGY.get(name)


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _find_buy_row_shares(
    conn: sqlite3.Connection,
    strategy: str,
    symbol: str,
    entry_ts: str,
) -> float | None:
    """Look up the BUY row in paper_trades for this (strategy, symbol, ~ts).

    Returns the canonical shares value from the row, or None if no row
    within +/-5min of entry_ts.
    """
    target = _parse_iso(entry_ts)
    if target is None:
        return None
    rows = conn.execute(
        "SELECT timestamp, shares FROM paper_trades "
        "WHERE strategy=? AND symbol=? AND action='BUY' "
        "ORDER BY timestamp DESC LIMIT 50",
        (strategy, symbol),
    ).fetchall()
    best: tuple[timedelta, float] | None = None
    for ts_str, shares in rows:
        ts = _parse_iso(ts_str)
        if ts is None or shares is None:
            continue
        delta = abs(ts - target)
        if delta <= MATCH_WINDOW and (best is None or delta < best[0]):
            best = (delta, float(shares))
    return best[1] if best else None


def _iter_state_files(data_dir: pathlib.Path):
    """Yield (state_file_path, strategy_id) for migratable files."""
    if not data_dir.is_dir():
        return
    for path in sorted(data_dir.glob("*_state.json")):
        name = path.name
        if "cooldown" in name or name in EXCLUDED_NAMES:
            continue
        strategy = _strategy_from_filename(name)
        if strategy is None:
            print(f"[skip] {name}: no STATE_FILE_TO_STRATEGY mapping",
                  file=sys.stderr)
            continue
        yield path, strategy


def migrate(
    data_dir: pathlib.Path | None = None,
    db_path: str | None = None,
    rename_suffix: str = ".migrated_2026-05-21",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the migration. Returns a summary dict.

    Args:
      data_dir: Directory holding *_state.json files (defaults to <repo>/data).
      db_path: Path to paper_trades.db (defaults to <repo>/data/paper_trades.db).
      rename_suffix: Suffix appended to each migrated state file.
      dry_run: If True, do not INSERT or rename -- just print what would happen.
    """
    data_dir = data_dir or (_ROOT / "data")
    db_path_str = db_path or str(_ROOT / "data" / "paper_trades.db")

    inserted = 0
    fallbacks: list[str] = []
    skipped_invalid: list[str] = []
    files_processed: list[str] = []

    conn = sqlite3.connect(db_path_str)
    try:
        for path, strategy in _iter_state_files(data_dir):
            files_processed.append(path.name)
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"[skip] {path.name}: unreadable ({exc})", file=sys.stderr)
                continue

            if not isinstance(state, dict) or not state:
                # Empty file -- still rename it so future runs are idempotent.
                if not dry_run:
                    path.rename(path.with_suffix(path.suffix + rename_suffix))
                print(f"[ok]   {path.name}: empty -> renamed")
                continue

            for symbol, pos in state.items():
                if not isinstance(pos, dict):
                    skipped_invalid.append(f"{path.name}:{symbol}:not-a-dict")
                    continue
                entry_price = pos.get("entry_price")
                size_usd = pos.get("size_usd")
                entry_ts = pos.get("entry_ts")
                if not entry_price or entry_price <= 0 \
                        or not size_usd or size_usd <= 0 or not entry_ts:
                    skipped_invalid.append(
                        f"{path.name}:{symbol}:missing-required-field"
                    )
                    continue

                shares = _find_buy_row_shares(conn, strategy, symbol, entry_ts)
                if shares is None or shares <= 0:
                    shares = float(size_usd) / float(entry_price)
                    fallbacks.append(
                        f"{strategy}:{symbol}:no-BUY-match-within-5min"
                        f"->size/price={shares:.8f}"
                    )

                # Build metadata blob from any strategy-private keys.
                meta_keys = {
                    k: v for k, v in pos.items()
                    if k not in {"entry_price", "size_usd", "entry_ts", "market"}
                }
                if not meta_keys:
                    meta_keys = None  # type: ignore[assignment]

                market = pos.get("market", DEFAULT_MARKET)

                if dry_run:
                    print(
                        f"[dry]  INSERT {strategy} {symbol} {market} "
                        f"shares={shares:.8f} price={entry_price} "
                        f"size_usd={size_usd} ts={entry_ts}"
                    )
                else:
                    positions.open_position(
                        strategy=strategy,
                        symbol=symbol,
                        market=market,
                        entry_shares=float(shares),
                        entry_price=float(entry_price),
                        size_usd=float(size_usd),
                        entry_ts=str(entry_ts),
                        correlation_id=pos.get("entry_correlation_id"),
                        metadata=meta_keys,
                        db_path=db_path_str,
                    )
                    inserted += 1

            if not dry_run:
                new_path = path.with_suffix(path.suffix + rename_suffix)
                path.rename(new_path)
                print(f"[ok]   {path.name} -> {new_path.name}")
    finally:
        conn.close()

    after_count = len(positions.list_positions(db_path=db_path_str))
    summary = {
        "files_processed": files_processed,
        "inserted_rows": inserted,
        "positions_after": after_count,
        "fallbacks": fallbacks,
        "skipped_invalid": skipped_invalid,
        "dry_run": dry_run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return summary


def _print_summary(summary: dict[str, Any]) -> None:
    print()
    print("=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    print(f"Files processed:      {len(summary['files_processed'])}")
    for f in summary["files_processed"]:
        print(f"  - {f}")
    print(f"Rows inserted:        {summary['inserted_rows']}")
    print(f"Positions after:      {summary['positions_after']}")
    print(f"Fallback warnings:    {len(summary['fallbacks'])}")
    for w in summary["fallbacks"]:
        print(f"  ! {w}")
    print(f"Skipped invalid:      {len(summary['skipped_invalid'])}")
    for s in summary["skipped_invalid"]:
        print(f"  - {s}")
    print(f"Dry run:              {summary['dry_run']}")
    print("=" * 60)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="One-time migration: data/*_state.json -> positions table."
    )
    ap.add_argument(
        "--data-dir", default=None,
        help="Directory holding *_state.json files (default: <repo>/data)",
    )
    ap.add_argument(
        "--db-path", default=None,
        help="Path to paper_trades.db (default: <repo>/data/paper_trades.db)",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print what would happen without writing.",
    )
    ap.add_argument(
        "--rename-suffix", default=".migrated_2026-05-21",
        help="Suffix appended to each migrated state file.",
    )
    args = ap.parse_args(argv)

    data_dir = pathlib.Path(args.data_dir) if args.data_dir else None
    summary = migrate(
        data_dir=data_dir,
        db_path=args.db_path,
        rename_suffix=args.rename_suffix,
        dry_run=args.dry_run,
    )
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
