# AAATS — Next Claude Code Session Prompt (2026-05-31) — Branch 2: operator approves Option B, or pivots

**Model tier:** Sonnet (data fetch + walk-forward backtest on a decided design). Opus only if the operator picks a path needing non-obvious design. Do NOT default to Opus.

**Soak guard:** D.5 30-day paper soak is live (day-30 ETA 2026-06-22). Offline backtest/data work only. Do NOT touch `aaats-paper-crypto`, runtime state, or live config. No deploy. No infra (no margin/liq engine, no broker adapter).

---

## STOP — gated on operator approval of the pre-registered criterion

Track F (2026-05-30) landed on **Branch 2**: the static C3+TSMOM ensemble fails the dual-window gate, but the edge clears fees, so the binding constraint is regime-robustness, and the gate's 2-month-OOS-over-2-hand-picked-windows is small-sample. The honest next test is a **walk-forward** — but only with a robustness criterion committed BEFORE seeing results (else it's curve-fitting, the failure mode that killed the C3 entry-gate program). **Do not run the walk-forward until the operator approves (or amends) the pre-registered criterion below.**

## Context — what 2026-05-30 settled (read `docs/decisions/2026-05-30_track_f_static_ensemble_and_economics.md`)

- Static ensemble (equal-weight AND inverse-vol) FAILS both windows on G2/G5/G6. Net positive full-period (G1 ok) but OOS mean return negative in both windows. Option A (regime-conditional ensemble) REJECTED — a portfolio mean is linear in its legs, so any positive-weighted blend of two negative-OOS legs has negative OOS Sharpe regardless of correlation; it could only "pass" by overfitting a timing overlay.
- Economics: NOT fee-dominated. Edge clears the ~10bps taker floor in both windows (break-even 18–70bps RT). Fees are 14% of gross where edge is strong, 55% where weak. Net sign is tranche-invariant — raising the $25 tranche cannot rescue a losing strategy; only the fee tier can, and headroom already exists.
- Standing scoreboard: C3 reversion (PASS current/FAIL earlier), C7 carry (fee-bound NO-GO), TSMOM momentum (FAIL both), static ensemble (FAIL both). No single or static-blend perp edge graduates the dual-window gate.

## The decision (operator picks)

- **B (scoped, ready to run on approval) — walk-forward robustness test.** Prerequisite: fetch CONTIGUOUS ≥18–24mo 6-symbol perp klines+funding (the two cached windows are disjoint with a ~6mo gap) — extend `fetch_perp_data.py` with a contiguous window (soak-safe fetch). Then: 4mo-train/2mo-test folds rolled by 2mo (≥7 OOS folds) over the static equal-weight C3+TSMOM ensemble; tag folds by regime for diagnosis only.
  **PRE-REGISTERED robustness criterion (frozen; approve/amend BEFORE running, do NOT tune to output):** robust iff ALL of — (1) ensemble OOS net>0 in ≥60% of folds; (2) median per-fold OOS Sharpe ≥0.5; (3) pooled all-OOS-folds per-trade Sharpe (sqrt(60)) ≥1.0; (4) worst single-fold drawdown ≤20%. Met → real edge → Track F infra sequencing (B1 doctrine→B4 schema→B2 margin/liq→B3 adapter→F.5 paper soak). Not met → edge is genuinely regime-specific/absent → STOP the strategy hunt, escalate the doctrine fork.
  Honest prior: skeptical — OOS is negative in both current windows, also consistent with genuine overfitting. The walk-forward disambiguates; it is not a presumed rescue.
- **Pivot / pause alternatives** (operator's call, per the original escalation): majors market-making (needs order-book data + infra; scope a data-feasibility check first), or pause the live-flip hunt and reconsider whether a $25-tranche directional-crypto edge is worth pursuing at all given the regime-instability across every class tried.

## Hard constraints
- No infra until an edge graduates a robustness test. Offline only; soak untouched; no deploy. G1–G7 gate UNCHANGED, no sweeping. No new single-strategy trial.
- If running Option B: the 4 thresholds are frozen at approval — do not tune them to the walk-forward results.

## Session-end discipline
- `clear_stale_git_locks` FIRST (a .git/index.lock block lost the 1757-line 2026-05-25 Track F spec). `git pull --rebase` before push (box auto-cron every 15 min). Atomic commits; verify the push landed.
- Memory with the verdict + branch fired; link `[[aaats-2026-05-30-static-ensemble-and-economics]]`.
- Overwrite this next-session prompt.
- Evidence-first: file:line for code, harness run for every number.
