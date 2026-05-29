# AAATS — Next Session Prompt (2026-06-01) — DOCTRINE FORK (perp-edge program closed)

**Model tier:** Sonnet for any execution. This is an operator strategic decision, not a build. Do NOT default to Opus.

**Soak guard:** D.5 30-day paper soak is live (day-30 ETA 2026-06-22). Offline only. Do NOT touch `aaats-paper-crypto`, runtime state, or live config. No deploy. No infra.

---

## STOP — the strategy hunt is terminated by a pre-registered verdict

The Track F walk-forward (2026-05-30) was the operator-approved FINAL ARBITER. It returned **NO-GO**: the static C3+TSMOM ensemble missed **4 of 5 frozen criteria** over a 15-fold / 36-month out-of-sample test, with the **null control decisive** — its OOS performance is statistically indistinguishable from randomly-signed trades. Per the frozen terminal semantics: **do NOT iterate, do NOT re-spec, do NOT propose a 6th strategy or another walk-forward.** Read `docs/decisions/2026-05-30_track_f_walk_forward_FINAL_perp_edge_NOGO.md` and memory `aaats-2026-05-30-track-f-walk-forward-final` first.

## What is settled (the whole perp-edge arc)

Every class tried fails an honest robustness test: C3 reversion (PASS one 6mo window / net-NEGATIVE over 36mo), C7 carry (fee-bound NO-GO), TSMOM momentum (FAIL both windows), static ensemble (FAIL both), walk-forward ensemble (NO-GO, not better than chance). The recurring mechanism is regime-conditionality; at the directional level there is no edge better than random. **No further single-strategy or static-blend perp work is warranted.**

## The doctrine fork — operator decides (this session does nothing until you pick)

- **A (lead recommendation) — PAUSE the directional-crypto live-flip.** Keep the D.5 paper soak running as a monitored research bed; commit no real capital to this thesis. The L1–L10 operational/monitoring stack is the part that demonstrably works. Lowest-risk, evidence-aligned. If chosen: this session just records the pause decision + updates the live-flip doctrine doc; nothing to build.
- **B — PIVOT thesis/asset class.** Non-directional / microstructure edges (majors market-making, cross-venue basis, liquidity provision) are less regime-fragile but need order-book data AAATS lacks + new infra. If chosen: scope a DATA-FEASIBILITY check first (can we even get/store the order-book data?), not a strategy. Major multi-session commitment.
- **C — REDIRECT effort** to where AAATS excels (operational reliability, monitoring, soak infra), and treat any future edge work as a fresh thesis with its own pre-registered gate — not a continuation of this program.

## Hard constraints
- The walk-forward verdict STANDS. No re-litigation, no parameter re-tuning, no "one more strategy."
- Offline only; soak untouched; no deploy; no infra until/unless a NEW thesis graduates its OWN pre-registered robustness test.

## Session-end discipline
- `clear_stale_git_locks` FIRST. `git pull --rebase` before push (box auto-cron every 15 min). Atomic commits; verify the push landed.
- Memory with the operator's fork decision; link `[[aaats-2026-05-30-track-f-walk-forward-final]]`.
- Overwrite this next-session prompt.
- Evidence-first: file:line for code, harness run for every number.
