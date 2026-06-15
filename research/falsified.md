# Falsified Hypotheses — index

> The mandate requires that anything failing the monthly promotion gate is logged
> here and **never silently retried**. This file is the human-readable index; the
> machine-readable, append-only source of truth is [`LEDGER.md`](LEDGER.md)
> (one row per registered harness run, written by `log_verdict.py`).

A hypothesis lands here when it FAILS the promotion gate (see
[`MONTHLY_HYPOTHESIS_CYCLE.md`](MONTHLY_HYPOTHESIS_CYCLE.md)). A FAIL is terminal:
no re-tuning, no "v2" of the same mechanism. Re-using a falsified mechanism is a
process violation, not a new experiment.

## Falsified to date (from LEDGER.md + AUDIT findings)

| Date | Hypothesis / strategy | Verdict | Why it failed |
|---|---|---|---|
| 2026-06-10 | C3 altcoin reversion (live) | NO EDGE | gross PnL negative before costs; net -$6.51 (AUDIT/loss_attribution.md) |
| 2026-06-10 | C6 bollinger range (live) | NO EDGE | gross ~flat, net -$5.84 after costs; own docstring says "signal density, not PnL" |
| 2026-06-10 | C1 stat-arb (live) | NO EDGE | gross ~flat, net -$0.66 after costs |
| 2026-06-09 | T4a funding-timing contrarian | FAIL | OOS Sharpe -0.96, null p=0.68 |
| 2026-06-09 | T4b funding-timing continuation | FAIL | gate 4/5, worst-fold DD 39% |
| 2026-06-06 | T2 cross-sectional momentum | FAIL | OOS Sharpe 0.86 but 74% fold DD; full-portfolio fail |
| 2026-06-06 | T1 funding dispersion | ECONOMICALLY VOID | median spread 8.68bps < 10bps taker |
| (prior) | C2 momentum, C5b/C7 funding-carry, TSMOM, C3+TSMOM ensemble | NO-GO | see docs/decisions/2026-05-30_track_f_walk_forward_FINAL_*.md |

**Standing conclusion (do not re-litigate):** every directional/carry mechanism
tried on free, point-in-time-clean crypto data has failed an honest, null-controlled,
out-of-sample gate. The open frontier is the OI/positioning thesis (T3), data-gated
to ~2027. Until a NEW pre-registered thesis clears the gate, the correct posture is
**no-trade** — which beats every active strategy net of costs.
