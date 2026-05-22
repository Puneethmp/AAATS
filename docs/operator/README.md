# Operator memory snapshots

This directory mirrors selected Cowork-side operator memory files into the repo so Claude Code sessions on the workstation can read them. The originals live in the operator's Cowork memory directory and are not synced automatically — these files are **point-in-time snapshots** with the snapshot date in the filename.

## Why this exists

Claude Code (running on the workstation) does not have access to the operator's Cowork session memory directory. Several Claude Code prompts authored in 2026-05 referenced files like `aaats_locked_doctrine_2026_05_14.md` assuming they were readable — they were not. This directory closes that gap.

## Reading rules

1. Treat every file here as a snapshot, not live state. Filename includes snapshot date.
2. Some claims will have become stale. The 2026-05-07 strategy universe document, for example, describes 12 designed strategies; production paper-crypto as of 2026-05-21 only fires 2 of them (C3, C6). Always verify against current code and `git log` before acting on memory-derived claims.
3. When in doubt, read the most recent `docs/decisions/*.md` and `docs/known_issues/*.md` first — those are authoritative for current state. The operator memory is supplementary context.
4. If a memory file conflicts with a recent decision doc, the decision doc wins.

## Files

- `aaats_locked_doctrine_2026_05_14.md` — capital plan, phase gates, kill triggers (doctrine). Authoritative for the $25 tranche / $100 floor / 5-gate framework.
- `aaats_strategy_universe.md` (2026-05-07) — design-time inventory of 12 strategies. **Largely aspirational** — production runs 2 strategies; treat as future-target catalog, not current reality.
- `aaats_dual_equity_ledger_debt.md` — architectural context for the unified-ledger work shipped 2026-05-21 (commits 4ee97f3, 61c93e7, 464bf7e). Behind `USE_UNIFIED_LEDGER=False` in production.
- `aaats_2026_05_21_no_go.md` — current state: 2026-05-22 live flip NO-GO, four-gap finding, rebuild sprint is the prerequisite.

## Sync convention

The operator updates these on a best-effort basis. If a Claude Code session needs context that isn't in here, ask — don't fabricate.
