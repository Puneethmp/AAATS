# Monthly Hypothesis Cycle

> Phase 4 of the forensic-audit mandate. Wires the weekly report's recurring
> failure-pattern flags into the existing pre-registration framework
> (`PRE_REGISTRATION_TEMPLATE.md`, `theses/`, `log_verdict.py`, `LEDGER.md`).
> The hard rules below are NOT optional — they are the entire reason the program
> is trustworthy.

## Forbidden

- Retraining or rule-tweaking in reaction to an individual losing trade. That is
  curve-fitting to noise and is treated as a **critical bug**.
- Re-running a mechanism already in `falsified.md`. A FAIL is terminal.
- Reporting any PnL gross of costs (use `analytics.ledger_repricer`).

## Cadence

1. **Per trade** — the ledger already captures entry features, exit reason,
   size, and (via `analytics.ledger_repricer`) the loss bucket and what the
   no-trade baseline did over the same window.
2. **Weekly** — `python tools/reports/weekly_report.py --week NN` →
   `REPORTS/week_NN.md`: net PnL vs no-trade baseline, loss-bucket distribution,
   cost ratio, recurring failure-pattern flags.
3. **Monthly** — this cycle:
   - Read the four weekly reports' **recurring failure-pattern flags**.
   - Form **at most 2** falsifiable hypotheses from those flags
     (e.g. "filtering entries within 2h of funding settlement improves expectancy").
   - Pre-register each: copy `PRE_REGISTRATION_TEMPLATE.md` →
     `theses/T<N>_<name>.md`, fill every field, **commit BEFORE any signal/PnL
     computation** (the commit SHA is the anti-snooping timestamp).
   - Run the harness ONCE per thesis (seed=7) on walk-forward OOS data only.
   - **Promotion gate (all required):** statistically significant improvement
     (report the test + p-value) AND survives realistic costs (the 5-part gate
     in `PRE_REGISTRATION_TEMPLATE.md` §5) AND beats no-trade.
   - PASS → promote (keep prior model hot-swappable for rollback).
     FAIL → append to `LEDGER.md` via `log_verdict.py` and add a row to
     `falsified.md`. Never silently retried.

## Model retraining

Only at month boundaries, walk-forward, previous model kept hot-swappable.

## Demotion rule

If after month 3 the no-trade baseline still beats every active strategy net of
costs, the monthly report must **explicitly recommend reducing to
data-collection-only mode**. Do not extend losing strategies hope they have not
earned. (As of the 2026-06-10 audit, the no-trade baseline already beats every
active strategy — the burden of proof is on any new thesis, not on "do nothing.")
