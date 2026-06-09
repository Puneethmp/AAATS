#!/usr/bin/env python
"""Append one line from a graduation verdict JSON to research/LEDGER.md.

The ONLY Phase-2 code. Not a framework — a 1-row appender over the existing
verdict JSONs the harness already writes. No DB, no orchestration.

    python research/log_verdict.py data/graduation/T2_xsect_momentum_2026-06-06.json

params-hash = sha256 of the registered-config subset of the verdict JSON
(thesis, window, seed, fee_rate_per_side, null_model, n_folds, book_usd), first
12 hex chars — so a spec change between runs is visible in the ledger.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

LEDGER = Path(__file__).resolve().parent / "LEDGER.md"
_CFG_KEYS = (
    "thesis",
    "window",
    "seed",
    "fee_rate_per_side",
    "null_model",
    "n_folds",
    "book_usd",
    "round_trip_taker_cost_bps",
)


def params_hash(v: dict) -> str:
    cfg = {k: v[k] for k in _CFG_KEYS if k in v}
    blob = json.dumps(cfg, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def row(json_path: Path) -> str:
    v = json.loads(json_path.read_text(encoding="utf-8"))
    crit = v.get("criteria", {})
    sharpe = crit.get("3_pooled_oos_daily_sharpe", {}).get("value", "n/a")
    null_p = crit.get("5_null_control", {}).get("null_empirical_p", "n/a")
    dd = crit.get("4_worst_fold_maxdd", {}).get("value", "n/a")
    date = (v.get("timestamp", "") or "")[:10] or "?"
    return (
        f"| {date} | {v.get('thesis', '?')} | {v.get('verdict', '?')} "
        f"| {sharpe} | {null_p} | {dd} | {params_hash(v)} | {json_path.as_posix()} |"
    )


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    line = row(Path(argv[0]))
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
