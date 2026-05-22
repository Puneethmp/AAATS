# `paper_positions.json` writer drift — `runtime/` vs `data/`

**Status:** OPEN (identification only — fix deferred to Track A.0 follow-up)
**Authored:** 2026-05-22
**Closes:** Sub-task 1.a from session 2 prompt; surfaced from session 1 status log entry (i).

## Summary

There are **two** `paper_positions.json` files on the workstation. They have
different schemas and disagree about open positions:

| Path                          | Contents                | Schema             | Tracked? |
|-------------------------------|-------------------------|--------------------|----------|
| `data/paper_positions.json`   | `{"india":{}, "crypto":{}}` | per-market empty   | YES (canonical) |
| `runtime/paper_positions.json` | 5 India + 4 crypto entries (DRREDDY/LT/SBIN/AXISBANK/HINDUNILVR + ETH/BTC/LINK/SOL with `shares`, `entry_price`, `entry_time`, `regime`, `sector`, `atr_entry`, `risk_pct`) | per-market → per-symbol position records | NO — `runtime/` is an intentionally git-ignored scratch dir (see `tools/operator/_dirty_tree_guard.py:16`) |

Pre-existing `dual_equity_ledger_debt` (`docs/operator/aaats_dual_equity_ledger_debt.md`)
is the `data/paper_positions.json` vs `paper_trades.db` drift. The `runtime/`
file is a **third** source surfaced in session 1.

## Production read path

The box never sees `runtime/`. On the box host the file does not exist:

```
$ ssh aaats@100.95.126.39 'find /home/aaats/aaats -name paper_positions.json'
/home/aaats/aaats/data/paper_positions.json
```

So `runtime/paper_positions.json` is a **workstation-only artifact**. It
cannot affect production behaviour today.

## Writer / reader call graph (workstation tree)

`rg --no-heading -n "paper_positions" --type py` returns 5 production hits:

| File                                          | Line | Role     | Path written/read           |
|-----------------------------------------------|------|----------|-----------------------------|
| `trading/live_paper_runner.py`                | 60   | Writer (via `save_positions`) + reader (via `load_positions`) | `data/paper_positions.json` |
| `trading/live_paper_runner.py`                | 23   | Docstring reference                          | `data/paper_positions.json` |
| `trading/live_paper_runner.py`                | 768  | Comment (standalone strategies bypass)       | `data/paper_positions.json` |
| `scripts/reconcile_intracycle.py`             | 113  | Reader (drift detection)                     | `data/paper_positions.json` (POSITIONS_FILE = `_ROOT / "data" / ...`) |
| `scripts/reconcile_intracycle.py`             | 183  | DEPRECATED comment — "paper_positions.json is no longer canonical" | n/a |
| `scripts/reconcile_intracycle.py`             | 368  | Backward-compat merge for legacy positions   | `data/paper_positions.json` |
| `engine/v6_engine.py`                         | 165  | Reader (v6 exporter side, sibling container) | `_DATA_DIR / "paper_positions.json"` (config-driven, `data/` in practice) |
| `tests/test_dual_ledger_drift.py`             | 23, 115 | Test harness — explicitly asserts `runtime/` vs `data/` drift bound | both |
| `tests/test_reconcile_denylist.py`            | 57   | Test (monkeypatches the path)                | `tmp_path / "paper_positions.json"` |
| `tests/scripts/test_drain_positions.py`       | n/a  | Test                                          | `tmp_path` |
| `tests/scripts/test_migrate_positions_to_db.py` | n/a | Test                                          | `tmp_path` |

**No production code writes to `runtime/paper_positions.json`.** The file
was created either by an operator-side script that bypassed the
`AAATS_DATA` env override (no current code path matches), by an earlier
debug session that has since been deleted, or by a tooling experiment.
The richer per-symbol schema (`shares`, `entry_price`, `entry_time`,
`regime`, `sector`, `atr_entry`, `risk_pct`) hints at an older snapshot —
the current canonical `paper_positions.json` writer in
`trading/live_paper_runner.py` writes via `save_positions` which uses
the same per-symbol shape, but the production state on box has been
empty for some time (per the reconciler's "no longer canonical"
comment at `scripts/reconcile_intracycle.py:183`).

## Canonical-path recommendation

**`data/paper_positions.json` is and remains canonical.** Rationale:

1. The reconciler explicitly documents the deprecation
   (`scripts/reconcile_intracycle.py:183`), routing trust to per-strategy
   state files (e.g. `data/altcoin_reversion_state.json`).
2. The Q1–Q4 unified-ledger design (see
   `docs/decisions/2026-05-21_ledger_spec_recommendations.md`) plans to
   replace `paper_positions.json` entirely with a SQL-backed unified
   ledger behind `USE_UNIFIED_LEDGER=False` — i.e., the canonical
   answer post-unification is "neither file", with `paper_positions.json`
   maintained as a write-through shim during transition.
3. The `runtime/` directory is declared a scratch space at
   `tools/operator/_dirty_tree_guard.py:16` (explicit allow-list for
   uncommitted writes by auto-cron, debug runs, etc.). Promoting any
   `runtime/` file to canonical would invalidate that contract.

## Recommended next action (NOT executed this session)

1. **Delete `runtime/paper_positions.json`** on the workstation — it is
   noise, not data. The `runtime/` dir survives; only this one file is
   removed. Per the dirty-tree guard, this is a workstation-local
   change with no box impact.
2. **Add a one-line gitignore-or-noisy-watch entry** to
   `tools/operator/_dirty_tree_guard.py` so future stray writes to
   `runtime/paper_positions.json` are flagged at audit time rather than
   accumulating silently.

Both actions are reversible (file deletion is recoverable from this
working tree's git history if needed; the dirty-tree-guard change is a
single allow-list edit). Defer execution to next session so this memo
can be reviewed first.

## Why this is NOT urgent

- Production (the box) does not have `runtime/`. Removing the
  workstation file has zero production impact.
- The D.3 schema validation introduced this session
  (`state/schemas.py::PaperPositionsSchema`) accepts the canonical
  `{"india": {...}, "crypto": {...}}` shape at either path, so a future
  re-creation of `runtime/paper_positions.json` would still load
  cleanly through the canonical reader — the schema is permissive on
  per-symbol contents.
- D.3's `validate_all_state_files()` startup smoke only inspects
  `data/`, not `runtime/`, so any future drift in the scratch dir
  cannot fail-the-runner-at-boot.

## Open follow-up

The schema-drift catalog row 6 (dual-ledger
`paper_positions.json` vs `paper_trades.db`) **stays open** post-D.3 —
that drift is now caught only by `tests/test_dual_ledger_drift.py`'s
bounded-drift baseline. The unified-ledger sprint closes it; until then,
the bounded-drift test enforces the constraint.
