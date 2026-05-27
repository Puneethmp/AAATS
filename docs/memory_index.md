# Memory index — cross-surface mirror

**Why this file exists.** AAATS is worked on from two surfaces — Claude Code
(CLI on the Windows workstation) and Cowork (browser sandbox). Each keeps its
own file-based memory directory, and the two are **not shared**. A memory
anchor written from Cowork is invisible to a Claude Code session and vice
versa: the Phase 3.5 break-even anchor went missing on the workstation in
exactly this way (referenced in commits + specs, but never present in the
Claude Code memory dir).

This file is the durable, git-tracked mirror that **both** surfaces can always
see. It lists the key memory anchor titles + one-line summaries. The full
content of each anchor lives in the writing surface's memory dir; this index
just guarantees a session on either surface knows the anchor exists and can ask
for it (or read the canonical repo doc named alongside it).

**Maintenance rule:** when a session writes a memory anchor that future
cross-surface work will need, add a one-line pointer here in the same commit.
Keep this in sync with the Claude Code `MEMORY.md` index for the entries below.

---

## B.1.5 backtest-harness sprint (2026-05-27) — the live decision artifact

The strategic A/B/C/D decision from this sprint is **deferred to the operator**
at soak-end (~2026-06-22). The decision document is the canonical entry point:

- **`docs/decisions/2026-05-27_b15_doctrine_proposal.md`** — operator-facing
  decision doc. Four options (status-quo / retire C1+C6 / full rebuild /
  allocator-level regime weighting), recommendation = B + D. Read this first.
- **`docs/specs/b15_backtest_harness.md`** — full methodology, Phases 3–5 with
  per-strategy tables, regime-feature tables, gating re-test tables.
- **`docs/specs/b15_data_inventory.md`** — what's on disk (file:line inventory).

### B.1.5 phase anchors (memory)

| Anchor | One-line summary |
|---|---|
| `aaats_2026_05_27_b15_gap_analysis.md` | ANCHOR. B.1.5 partly shipped (~1,300 LOC C3 harness). First run verdict=PARTIAL — slippage-fragile (+$5.43 zero-friction → −$5.72 at 50bps). Hybrid architecture locked. |
| `aaats_c3_slippage_fragility.md` | Live C3 path applies ZERO slippage (raw prices); harness applies configurable. Soak PnL is biased optimistic. For live-flip GO/NO-GO read the harness's 50bps sensitivity, not soak realized_pnl. |
| `aaats_2026_05_27_b15_phase4_c3_walkforward.md` | Verdict WINDOW-DEPENDENT across 5×60d windows. 4/5 MARGINAL, 1/5 DEAD (W2 mid-Dec→Feb). Soak window (W5) is BEST, not a cherry-pick. Live-flip GO needs a regime gate. |
| `aaats_2026_05_27_b15_phase5_regime_gate.md` | Verdict GATE-INEFFECTIVE. W2 fingerprint clear at 60d (trend_strength z=+5.43) but trailing-60-bar gate over-filters W3 (MARGINAL→DEAD). Simple-threshold exhausted; regime-awareness belongs at the allocator. |

Per-strategy final verdicts: **C1** break-even 2.83 bps → DEAD; **C6**
unprofitable at zero cost → DEAD; **C3** break-even 22.79 bps, MARGINAL,
window-dependent, in-strategy gating ineffective.

Raw outputs live in `data/backtest_results/*.json` (now git-tracked — the
`data/*` blanket ignore was given a `!data/backtest_results/` negation).

---

## Standing feedback rules (apply to all future sessions)

| Rule | Where the full rule lives | One-line |
|---|---|---|
| **Regime filtering belongs at the allocator** | memory `feedback_regime_filtering_at_allocator.md` | Don't add regime gates inside single-strategy entry hooks; do it at the portfolio layer as a capital-weight scalar. Per-bar trailing windows are too noisy. Established by B.1.5 Phase 5. |
| **L11 capital-invariant baseline pattern** | repo `docs/known_issues/2026-05-27_l11_legacy_drift_baseline.md` (+ memory `aaats_2026_05_26_structural_fix_shipped.md`) | L11 verdict gates on `effective_delta_usd` = raw − operator-recorded baseline. Legacy drift (−$8.5169) is subtracted via `data/capital_invariant_baseline.json`, NOT treated as a live leak. Refresh the baseline only via the runbook in that doc. |

> Note: there is no standalone `invariant_baseline_pattern.md` memory anchor —
> the L11 baseline pattern is documented in the repo known-issues doc above,
> which is the canonical, always-visible source for both surfaces.

---

## Other durable references frequently needed cross-surface

| Anchor / doc | One-line |
|---|---|
| memory `feedback_grafana_datasource_uid.md` | Provisioned Grafana datasource UID is `aaats-prom`, NOT `prometheus`. Hard-coding `prometheus` → "No data" on every panel. Use `deploy_lib.grafana_datasource_ref()`. |
| memory `feedback_windows_encoding.md` | Use ASCII for terminal output; `utf-8-sig` for file reads. Windows cp1252 console crashes on Unicode. Deploy scripts call `deploy_lib.enforce_utf8_console()`. |
| memory `project_aaats_d5_soak_window.md` | Operator-away 30d soak (day-30 ETA 2026-06-22). us/india halts intentional; `paper_trades.db` reset 2026-05-23 is the intentional baseline. |
| repo `CLAUDE.md` | Deploy machinery gotchas (#1–#11), monitoring layers L1–L11, kill-switch semantics, doc layout. The canonical operator-notes file. |
