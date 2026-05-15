# AAATS reconciler architectural drift — diagnosis 2026-05-14

> **Mirrored from operator-local memory on 2026-05-15. Canonical location is now this file; the memory copy is historical.**
>
> Original: `~/.claude/projects/c--Users-udaym-OneDrive-Desktop-Puneeth/memory/project_aaats_drift_diagnosis.md`
> The operator-local copy will be left in place for continuity but is no longer the source of truth. Future updates land here.

---

State on Contabo (`aaats-paper-crypto`): risk-halted at -42.6% drawdown as of
2026-05-14T13:48Z (was -28.9% earlier same day). Breached -15% crypto halt and
-20% portfolio halt. Halt is correct, deliberately NOT lifted. Halt is held
in-memory by `foundation.kill_switch`, not in a state file.
`data/halt_state.json` shows `{"crypto": false}` but its semantics are
ambiguous and not authoritative — trust logs instead.

## Root cause of the 17-symbol drift (was 16 earlier)

`scripts/reconcile_intracycle.py` (in container at `/app/scripts/`) compares:

- **Source A** = `data/paper_positions.json` → `{"india":{}, "crypto":{}}` (EMPTY)
- **Source B** = `SUM(BUY.shares) - SUM(SELL.shares)` from `paper_trades.db`
  (17 symbols as of 2026-05-14 13:48Z: 12 are real live positions from the
   strategy state files; 5 are pure share-rounding arithmetic drift for
   nominally-closed positions — PENGU -20.46, LUNC -6838.6, SOL -9e-5,
   ETH -2e-5, EUR -0.0146)

It does NOT read:
- `altcoin_reversion_state.json` (where 10 of those symbols actually live)
- `bollinger_range_state.json` (where TRX/USDT lives)
- Any per-strategy state

Every symbol the live runner opens via a strategy state file trips
`symbol_present_in_only_one_source` because A is empty by design — the runner
never writes back to `paper_positions.json`.

## Three possible canonical-source decisions for next session

(a) **`paper_positions.json` is canonical** — runner must write strategy
    positions there. Wide change but cleanest reconciliation.
(b) **Per-strategy state files are canonical** — reconciler unions them into
    Source A. Smaller change but reconciler becomes strategy-aware.
(c) **`paper_trades.db` SUM is canonical** — drop Source A and per-strategy
    JSONs entirely. Simplest model, but loses per-position metadata
    (entry_z, entry_pct_b, etc.) the strategies need for exit logic.

## Unexplored sources to investigate next session

- `oms.db` (40 KB, last touched 2026-05-12) — may hold yet another positions truth
- `audit_trail.db` (823 KB, actively updated) — event log, useful for replay

**Why:** the bot is halted and accumulating drift logs every cycle; we need an
honest canonical source before unhalting, otherwise the reconciler kill switch
will re-fire immediately.

**How to apply:** before any unhalt attempt, pick a canonical-source design,
write an integration test that proves reconcile_now() returns
`passed=True` against a known state, then ship. Do not attempt cleanup-script
workarounds — they band-aid one symbol per script run.

## Compose project layout (critical for any redeploy)

Two SEPARATE compose projects on the host:

- `aaats-paper-crypto` → project=`deployment`,
  config=`/home/aaats/aaats/deployment/docker-compose.yml`
- `aaats-grafana` (and prometheus, exporters) → project=`aaats-base`,
  config=`/srv/aaats/compose/docker-compose.{base,cp3,grafana}.yml`

`docker compose down` from one path will NOT touch containers from the other.

## Container has no `sqlite3` binary

Querying SQLite in the container requires `docker exec ... python -c
"import sqlite3; ..."`. The `sqlite3` CLI is not installed.

## Cleanup script note

`scripts/cleanup_orphan_positions.py` (patched 2026-05-13) writes a SELL audit
row but leaves the `id` column NULL. The TEXT PRIMARY KEY column doesn't
auto-populate. Next time it's touched, fill `id=uuid4()`. The script also
doesn't reach `paper_trades.db` BUY-SELL aggregation — so closing PENGU via the
script changed its drift `actual` from +336.92 → -20.46 (didn't make it zero;
the BUY shares from prior cycles still aggregate). The script is a workaround
for state-file orphans, not a drift fix.

## Follow-up linkage (added 2026-05-15)

The 2026-05-15 surgical fix in `.rollback/2026-05-15_record_fix/` addresses
**one of the contributing causes** of Source B drift — exit-shares mismatch in
C3 (`trading/altcoin_reversion.py`) and C6 (`trading/bollinger_range.py`)
where SELL rows recorded `size_usd/current_price` instead of the BUY row's
entry shares. This eliminates ongoing dust accumulation in `paper_trades.db`
SUM but does NOT solve the architectural drift (Source A is still empty by
design). Unified ledger spec (`docs/specs/unified_positions_ledger.md`) is
the proper fix and is frozen pending operator Q1-Q4 answers.

Related: prior 48h sprint where `halt_on_critical=False` band-aid was applied
— that band-aid is still in effect; the drift halt is firing through the risk
engine's drawdown logic, not the reconciler.
