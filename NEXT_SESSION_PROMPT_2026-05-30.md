# AAATS — Next Claude Code Session Prompt (2026-05-30) — Track F (futures/perps) F.1

**Model tier:** Sonnet for F.1.a/c/d (spec + schema design + interface borrow — decided-design docs); escalate to Opus only for F.1.b (margin/liquidation risk modeling is genuinely non-obvious). Do NOT start the whole session on Opus.

**Soak guard:** D.5 30-day paper soak is live (started 2026-05-23, day ~7, day-30 ETA 2026-06-22). Everything below is OFFLINE harness + docs work. Do NOT touch the running `aaats-paper-crypto` container, runtime state, or live config. No deploy. No doctrine change *enacted* (drafts only).

---

## Context — what Track 11 settled (the entry-gate program is CLOSED)

Track 11 tested a drift-trend gate (`gate_version=3` = divergence AND |60d log-RS drift| ≥ 0.08). **Earlier window did NOT flip — it FAILed worse** (PF 0.41 vs v1/v2's 0.69; net −5.31; OOS Sharpe −3.56). Unlike correlation (Track 10, inert), drift is **active and independent** (drift_only=1127 earlier / 1114 current — it blocked >1100 bars divergence let through) **but anti-predictive**: alts bleed vs BTC throughout *both* windows, so |drift|≥0.08 fires on 70–88% of bars and the gate throttles C3 globally, stripping winners with losers and degrading both windows (current PASSes but PF 1.49→1.35).

**Three principled allocator entry signals — divergence (best), correlation (inert), drift (harmful) — are exhausted. None makes C3-perp both-window-robust.** C3-perp solo = NO-GO; gated = PARTIAL current-only (best gate = plain v1 divergence). Full record: `docs/decisions/2026-05-29_b17_track11_drift_gate_and_track_e_entry.md`; memory `aaats-2026-05-29-track11-drift-gate`.

**Decision: committed to Track E/F (futures/perps).** Track 11 is the last C3-class entry-gate experiment.

---

## This session — Track F (futures/perps) Phase F.1: spec + soak-safe foundation

### FIRST, read these (the entry plan already exists; this session executes it)
- `docs/decisions/2026-05-29_b17_track11_drift_gate_and_track_e_entry.md` §5 — the F.1 entry plan, the 4 prereq blockers (B1–B4), and the gating checklist.
- `docs/decisions/2026-05-27_nt_final_extraction_for_success.md` — the 8 NT capabilities + P0–P4 roadmap (items 1/2/4/6 are the futures-relevant ones).

### Naming fix (do this first)
The brief's "Track E (futures/perps)" collides with the rebuild-plan's existing **Track E = operator-away soak (E.1–E.6, DONE)**. The futures program's phases are "F.1–F.7" — so **rename it "Track F — Futures/Perps."** The spec file the prior brief told us to read (`2026-05-25_track_e_futures_spec.md`) **never existed** — F.1.a writes it.

### F.1 task breakdown (all offline, soak-safe)
1. **F.1.a — Write `docs/decisions/2026-05-30_track_f_futures_spec.md`:** formalize F.1–F.7, lock the Track F rename, list B1–B4 with exit criteria. *(Sonnet, 0.5 session.)*
2. **F.1.b — Margin/liquidation prototype (B2):** in the C3-perp harness (already futures-native: real USDT-M perp klines + funding + MakerTaker fees + NT MARGIN account at `margin_init=0`), set realistic Binance USDT-M margin tiers, track liquidation price per open long, re-run current-window C3-perp, measure whether G3 drawdown survives a maintenance-margin model. Pure NT harness, no box. *(Opus, 1 session.)*
3. **F.1.c — Futures state-schema design (B4):** draft `paper_trades` columns + `funding_ledger`/`margin_state` schema (Decimal-as-TEXT). Spec + draft migration, NOT applied. *(Sonnet, 0.5 session.)*
4. **F.1.d — Broker-adapter interface borrow (B3):** document NT's `ExecutionClient`/`DataClient`/`InstrumentProvider` + order vocabulary (reduce-only, post-only, OCO, `TRAILING_STOP_MARKET`) as the futures-order interface. Design doc only. *(Sonnet, 0.5 session.)*
5. **F.1.e — Doctrine-amendment draft (B1):** draft spot-only→futures-allowed amendment for operator review (leverage cap, liquidation-distance floor, tranche gates). Operator enacts; Claude only drafts. *(Sonnet, 0.5 session.)*

### The open strategy problem — say it plainly
Track 11 proved **there is no both-window-robust futures edge today.** F.1 builds the runway; it does NOT produce a tradeable edge. A live perp also needs a *new* perp-native edge that graduates on both windows. **Parallel research line (separate from F.1 infra):** C7 funding-harvest with a hedge-sizing fix (it failed on notional, not direction — memory `aaats-2026-05-28-c7-funding-arb-verdict`), perp-native momentum/carry at other time scales, or market-making on majors. Pick ONE to scope next, after F.1.a/c/d ship.

### Hard constraints
- No live, no deploy, no box edit, no doctrine *enacted*. D.5 soak runs undisturbed.
- Reuse the existing harness + graduation gate + regime_gate; do not rebuild.
- Evidence-first: cite file:line for code, cite the harness run for every number, distinguish observed vs hypothesized.

### Session-end discipline
- `git pull --rebase` before push (box auto-cron pushes every 15 min). Atomic commits per scope. Verify the push landed.
- Memory file with the F.1 outcome; MEMORY.md pointer; link `[[aaats-2026-05-29-track11-drift-gate]]`.
- Overwrite this next-session prompt.
