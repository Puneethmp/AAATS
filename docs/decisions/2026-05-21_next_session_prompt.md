# Next session prompt (overwritten 2026-06-06)

> **STATUS: MAINTENANCE / RESEARCH-BED MODE. No active sprint. No live-flip.**
> The reactivation T1/T2 research program ran and CLOSED on 2026-06-06 — full-portfolio
> FAIL. There is nothing to build or flip. Default posture is unattended monitoring.

## What just happened (2026-06-06 reactivation session)

The pre-registered T1/T2/T3 thesis portfolio
([2026-06-06_reactivation_thesis_portfolio_preregistration.md](2026-06-06_reactivation_thesis_portfolio_preregistration.md),
registration commit `5a2c3366`) was executed end-to-end:

- **T1** cross-sectional alt-perp funding dispersion → **ECONOMICALLY VOID** (median
  round-trip funding income 8.68bps < 10bps taker; harness correctly skipped).
- **T2** cross-sectional momentum → registered-gate **FAIL 1/5** (weak signal: pooled
  Sharpe 0.857 beats ~96% of nulls but misses Bonferroni p97.5, the ≥1.0 / ≥0.5 Sharpe
  floors, and posts a 74% fold drawdown in the 2026-01 alt crash).
- **Full-portfolio FAIL** — falsification boundary now extends to cross-sectional carry
  AND cross-sectional momentum. Verdict memo:
  [2026-06-06_reactivation_T1_T2_verdict_portfolio_FAIL.md](2026-06-06_reactivation_T1_T2_verdict_portfolio_FAIL.md).
- **T3** positioning-crowding collector DEPLOYED (hourly OI+premium cron on the box,
  append-only `/home/aaats/t3/t3_positioning.db`). Registered + DATA-GATED.

## The only dated forward action

- **~2027-03 (≥9 months of T3 capture):** verify the T3 collector accumulated cleanly,
  then — and only then — freeze the T3 signal parameters by ADDENDUM to the pre-reg doc
  (before any signal/PnL computation), and run the T3 harness ONCE through the same
  5-part gate. Check meanwhile that the hourly cron is still firing (no sqlite3 CLI on
  box → use the python one-liner pattern from `tools/operator/deploy_t3_collector_2026_06_06.py`):
  `ssh aaats@100.95.126.39 '/usr/bin/python3 -c "import sqlite3;c=sqlite3.connect(chr(39)+\"/home/aaats/t3/t3_positioning.db\"+chr(39));print(c.execute(\"select count(*),max(ts_utc) from oi_snapshots\").fetchone())"'`

## Do NOT (unchanged constraints)

- Do NOT reopen T1 or T2, re-parameterize them, or build a "v2" of either mechanism.
- Do NOT scope a new strategy / flip anything live / touch the D.5 soak or C1/C3/C6/TSMOM.
- Reactivation of ANY new thesis requires its own pre-registered mechanism + committed gate.
- CLAUDE.md program status stays as-is (no PASS occurred).

## Standing maintenance

Research-bed runbook: [docs/runbooks/research_bed_maintenance.md](../runbooks/research_bed_maintenance.md).
Monitoring stack L1–L10 + auto-cron continue unattended. The D.5 soak continues. If a
monitor pages, follow its runbook; otherwise nothing here needs a human.
