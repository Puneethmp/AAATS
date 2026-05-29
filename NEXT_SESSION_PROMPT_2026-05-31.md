# AAATS — Next Claude Code Session Prompt (2026-05-31) — ESCALATED: method decision required

**Model tier:** Sonnet for implementation; Opus only if the operator picks a path needing non-obvious design. Do NOT default to Opus.

**Soak guard:** D.5 30-day paper soak is live (day-30 ETA 2026-06-22). Offline backtest/data work only. Do NOT touch `aaats-paper-crypto`, runtime state, or live config. No deploy.

---

## STOP — this session is gated on an operator strategic decision

Track F F.1 (2026-05-30) escalated per the operator's own decision rule. **Do NOT auto-queue a 3rd single-strategy perp candidate.** The first task is to confirm the operator's chosen direction (A/B/C/D below). If the operator has already answered, execute that; if not, surface the decision and wait.

## Context — why we escalated (read `docs/decisions/2026-05-30_track_f_f1_perp_tsmom_and_c7_close.md`)

EDGE-FIRST is locked: no execution infra (margin/liq engine, broker adapter) until a perp-native edge graduates G1–G7 on BOTH 6mo windows. Three distinct edge classes have now failed that gate, and they fail in a **regime-complementary** pattern:

| class | mechanism | current window | earlier window |
|---|---|---|---|
| C3 mean-reversion | price reversion | PASS (gated PF 1.49) | FAIL (PF 0.69) |
| C7 funding-carry | funding rent | FAIL (fee-bound, ~30bps RT vs ~1bps/8h) | structural FAIL |
| TSMOM momentum | trend persistence | FAIL (−$5.16, DD 28.7%) | profitable +$20.30 but OOS-Sharpe −0.92 → FAIL G2/G6 |

C3 (reversion) and TSMOM (momentum) are opposite bets that win in opposite windows; the two windows are opposite regimes. A single-factor strategy is a one-regime bet, so the dual-opposite-window gate is structurally unpassable by any single directional/reversion strategy. **The bottleneck looks like the method, not the next strategy.**

Also settled this session: C7 has NO hedge-sizing bug (balanced by construction, directional ≈ $0); it is fee-bound on any asset — closed NO-GO. Perp data is now complete (6 syms × both windows); NO spot fetcher exists (spot-only strategies still blocked on earlier-window spot).

## The decision (operator picks; lead recommendation = A)

- **A (recommended) — regime-conditional ENSEMBLE at the allocator.** Run C3 (reversion) + TSMOM (momentum) together; allocator tilts capital by detected regime; graduate the *ensemble* on both windows. Monetizes the complementarity this session surfaced. Reuses both existing harnesses (`run_c3_perp_funded_*`, `run_perp_tsmom_oos.py`) + the unchanged G1–G7 gate. Regime signal at the ALLOCATOR (per locked 2026-05-27 doctrine), not inside a strategy — Track 11 proved in-strategy regime gates over-filter. First task: build an ensemble harness that combines the two per-trade ledgers under a regime-weight scalar, score G1–G7 on both windows. NO threshold sweeping.
- **B — change the graduation frame.** Replace the two-opposite-6mo-window gate with walk-forward across regime-tagged sub-periods + a deploy-time regime detector. Needs a robustness criterion that isn't curve-fitting.
- **C — majors market-making / liquidity provision.** Less directional, but needs order-book microstructure data AAATS lacks + different infra. Larger commitment; scope a data-feasibility check first.
- **D — question the loop economically.** At $25 tranches with ~30bps round-trip fees, the fee floor may dominate any small-notional edge regardless of signal. If so, the constraint is capital/fees, not signal discovery — revisit tranche size / fee tier / whether live-flip is worth it at all.

## Hard constraints
- No infra build (no margin/liq engine, no broker adapter, no spot fetcher) until an edge — single or ensemble — graduates both windows.
- Offline only; soak untouched; no deploy. G1–G7 gate UNCHANGED, no sweeping/re-tuning.
- Do NOT silently start a 3rd single-strategy trial — that is the pattern the escalation flagged.

## Session-end discipline
- `clear_stale_git_locks` FIRST (a .git/index.lock block lost the 1757-line 2026-05-25 Track F spec — do not repeat). `git pull --rebase` before push (box auto-cron every 15 min). Atomic commits per scope; verify the push landed.
- Memory with the verdict + branch fired; link `[[aaats-2026-05-30-track-f-f1-perp-edge-trials]]`.
- Overwrite this next-session prompt.
- Evidence-first: file:line for code, harness run for every number.
