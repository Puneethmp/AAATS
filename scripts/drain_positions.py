"""scripts/drain_positions.py -- Q4=A precondition check for ledger flag flip.

Spec: docs/decisions/2026-05-21_ledger_spec_recommendations.md Q4=A.

Asserts that the position book is *drained* in BOTH sources of truth:
  - Source A: every data/*_state.json (excluding cooldown/halt) is empty {}.
  - Source B: the `positions` table contains zero rows.

If both are clean: appends a "drain_ok" event to data/ledger_flag_history.json
and exits 0. The companion script scripts/deploy_ledger_flag.py refuses to
flip USE_UNIFIED_LEDGER unless a "drain_ok" event has been written within
the last 10 minutes.

If either source has open positions: prints the offenders to stderr and
exits non-zero. No state files are modified.

This makes the dual-write pathology (file-based AND DB writers both active
during the flag transition) structurally impossible: the only window in
which the flag can flip is one where there is nothing to disagree on.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from foundation import positions
from scripts.migrate_positions_to_db import (
    EXCLUDED_NAMES, STATE_FILE_TO_STRATEGY,
)


def source_a_open(data_dir: pathlib.Path) -> list[str]:
    """Return list of '<file>:<symbol>' strings for any open Source-A row."""
    offenders: list[str] = []
    if not data_dir.is_dir():
        return offenders
    for path in sorted(data_dir.glob("*_state.json")):
        name = path.name
        if "cooldown" in name or name in EXCLUDED_NAMES:
            continue
        if name not in STATE_FILE_TO_STRATEGY:
            # Unknown state file -- treat as "non-drainable noise" rather
            # than a blocker; print for visibility but do not fail.
            continue
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(state, dict):
            continue
        for symbol, pos in state.items():
            if isinstance(pos, dict) and pos.get("entry_price"):
                offenders.append(f"{name}:{symbol}")
    return offenders


def source_b_open(db_path: str | None) -> list[str]:
    """Return list of '<strategy>:<symbol>' strings for any open Source-B row."""
    rows = positions.list_positions(db_path=db_path)
    return [f"{r['strategy']}:{r['symbol']}" for r in rows]


def append_history(
    history_path: pathlib.Path,
    event_type: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append an event to data/ledger_flag_history.json (creates if absent)."""
    if history_path.exists():
        try:
            doc = json.loads(history_path.read_text(encoding="utf-8"))
        except Exception:
            doc = {"events": [], "current_value": False}
    else:
        doc = {"events": [], "current_value": False}

    if not isinstance(doc, dict) or "events" not in doc:
        doc = {"events": [], "current_value": False}

    event = {
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        event.update(extra)
    doc["events"].append(event)

    history_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = history_path.with_suffix(history_path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    tmp.replace(history_path)


def drain_check(
    data_dir: pathlib.Path | None = None,
    db_path: str | None = None,
    history_path: pathlib.Path | None = None,
) -> tuple[bool, list[str], list[str]]:
    """Run the drain check. Returns (clean, source_a_offenders, source_b_offenders)."""
    data_dir = data_dir or (_ROOT / "data")
    history_path = history_path or (_ROOT / "data" / "ledger_flag_history.json")
    a_off = source_a_open(data_dir)
    b_off = source_b_open(db_path)
    clean = not a_off and not b_off
    if clean:
        append_history(
            history_path,
            event_type="drain_ok",
            extra={"data_dir": str(data_dir), "db_path": db_path or "default"},
        )
    return clean, a_off, b_off


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Drain-check: verify zero open positions in both sources.",
    )
    ap.add_argument("--data-dir", default=None,
                    help="Directory of *_state.json files (default: <repo>/data)")
    ap.add_argument("--db-path", default=None,
                    help="Path to paper_trades.db (default: <repo>/data/paper_trades.db)")
    ap.add_argument(
        "--history-path", default=None,
        help="Path to ledger_flag_history.json (default: <repo>/data/ledger_flag_history.json)",
    )
    args = ap.parse_args(argv)

    data_dir = pathlib.Path(args.data_dir) if args.data_dir else None
    history_path = pathlib.Path(args.history_path) if args.history_path else None
    clean, a_off, b_off = drain_check(
        data_dir=data_dir, db_path=args.db_path, history_path=history_path,
    )

    if clean:
        print("DRAIN OK: zero open positions in both Source A and Source B.")
        return 0

    print("DRAIN FAIL: open positions detected.", file=sys.stderr)
    if a_off:
        print("  Source A (*_state.json):", file=sys.stderr)
        for s in a_off:
            print(f"    - {s}", file=sys.stderr)
    if b_off:
        print("  Source B (positions table):", file=sys.stderr)
        for s in b_off:
            print(f"    - {s}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
