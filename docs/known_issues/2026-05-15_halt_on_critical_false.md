# `halt_on_critical=False` band-aid in intracycle reconciler call

**Filed**: 2026-05-15
**Status**: ACTIVE BAND-AID — keep in paper mode; HARD BLOCKER for any move to live capital.
**Call-site**: [trading/live_paper_runner.py:1696](../../trading/live_paper_runner.py#L1696)
**Reconciler signature**: [scripts/reconcile_intracycle.py:352](../../scripts/reconcile_intracycle.py#L352) (default `halt_on_critical=True`; docstring: "False is for testing only.")
**Introduced**: commit `bdb8f85` (2026-05-15, "feat(ops): intracycle reconciler call + per-cycle heartbeat write"). Has never been `True` in any committed version of the runner — the commit captured the shape the live container had already been running with since the 2026-05-15 P0/P1 deploy. The flag itself was originally chosen during the 2026-05-12 48h sprint (project memory `project_aaats_48h_sprint.md`) and survived the rebase to origin/main as-is.

## What it does

`reconcile_now(halt_on_critical=False)` runs the drift detector and returns a
`ReconciliationResult`, but suppresses the side effect at
[scripts/reconcile_intracycle.py:533](../../scripts/reconcile_intracycle.py#L533):

```python
if halt_issues and halt_on_critical:
    # ... foundation.kill_switch.halt() per affected market
```

With `False`, HALT-severity drift entries are still produced, logged, and
written to the audit trail — but the kill switch never fires. The runner's
own `if _rec.halted: break` guard never trips because `result.halted` stays
`False`.

## Why the band-aid exists

The reconciler compares two "sources of truth" for open positions:

- **Source A** = `data/paper_positions.json` (currently `{"india":{}, "crypto":{}}` — empty by design) merged with strategy-state JSONs (`altcoin_reversion_state.json`, `bollinger_range_state.json`, etc.).
- **Source B** = `SUM(BUY.shares) - SUM(SELL.shares)` from `paper_trades.db`.

Per [docs/decisions/2026-05-15_drift_diagnosis.md](../decisions/2026-05-15_drift_diagnosis.md), Source A was empty for every live position until the 2026-05-14 patch that taught the reconciler to read strategy-state files. Even today, every position the runner opens via a strategy state file is at risk of tripping `symbol_present_in_only_one_source` (severity HALT) if state files and DB diverge for any reason — and the architectural ledger fix (unified positions ledger, Q1-Q4 pending) has not landed. If `halt_on_critical=True`, a single phantom drift entry would halt the whole runner per-cycle.

Two recent mitigations reduced — but did not eliminate — the false-positive surface:

- **Deny-list filter** ([reconcile_intracycle.py:407](../../scripts/reconcile_intracycle.py#L407)) — skips symbols banned by the universe scanner (zombies/memes/wrapped) where ledger residue is impossible to drain.
- **Dust filter** ([reconcile_intracycle.py:421](../../scripts/reconcile_intracycle.py#L421)) — sub-$0.10-notional residuals classified as ledger rounding, not real drift.

These keep the WARN/HALT counts low in steady state, but the underlying canonical-source ambiguity remains.

## Conditions under which the flag MUST be flipped back to `True`

Flip when **all** of the following are true:

1. Unified positions ledger spec ([docs/specs/unified_positions_ledger.md](../specs/unified_positions_ledger.md)) is implemented and Q1-Q4 are answered.
2. `tests/test_reconcile_denylist.py` (and any new tests covering the ledger) pass against a known-clean state with `halt_on_critical=True`.
3. A 24-hour paper run completes with zero HALT-severity reconciler entries in the audit trail (`paper_trades.db` `audit_trail` table, `module='reconcile_intracycle'`, `result='FAILURE'`).
4. Before any flip to live capital — this is a HARD BLOCKER per [pre-live gates](../decisions/pre_live_gates.md).

## What it does NOT silence

The drawdown-based kill switch in [risk/engine.py](../../risk/engine.py) is unaffected. The 2026-05-14 -42.6% drawdown halt fired through that path, not through the reconciler. So the band-aid silences only the *reconciler's* halt verb, not the broader portfolio risk system.

## Cross-references

- Project memory: `project_aaats_48h_sprint.md` (original mid-flight band-aid context).
- Drift diagnosis: [docs/decisions/2026-05-15_drift_diagnosis.md](../decisions/2026-05-15_drift_diagnosis.md).
- Pre-live gate: [docs/decisions/pre_live_gates.md](../decisions/pre_live_gates.md).
- Tests: [tests/test_reconcile_denylist.py](../../tests/test_reconcile_denylist.py).
