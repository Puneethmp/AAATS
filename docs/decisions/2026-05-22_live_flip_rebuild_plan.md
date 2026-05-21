# Live-flip rebuild plan (2026-05-22, post-NO-GO)

**Status:** DRAFT — planning only, no code, no box edits beyond read-only SQL queries.
**Authored:** 2026-05-21
**Supersedes:** the GO body of [`2026-05-22_live_readiness.md`](2026-05-22_live_readiness.md) (header already records NO-GO).

## Premise

The 2026-05-22 GO $25 first tranche was NO-GO'd on 2026-05-21 for two
independent reasons:

1. **The live-flip mechanism is non-functional by design.** The four-gap finding
   in [`docs/known_issues/2026-05-21_live_flip_mechanism_gaps.md`](../known_issues/2026-05-21_live_flip_mechanism_gaps.md)
   shows that risk state inherits across mode boundary, `PAPER_MODE` env is
   unread, `SYSTEM__TRADING_MODE` is compose-hardcoded + validate-gated, and no
   live trade loop exists. A `deploy_live_flip.py` invocation today would
   change `.env` and not the running code path.
2. **The paper strategy stack is in -13.06% drawdown** (peak $116.53,
   last_equity $101.32 per `/app/data/state/risk_engine_state.json`,
   2026-05-21T09:24:35Z). The realized component of that loss is concentrated
   in a single strategy (C3_altcoin_reversion: -$5.63 over 9 days; see
   appendix). Flipping $25 into the current strategy stack — even if the
   mechanism worked — would be deploying real capital into a losing system.

The honest path is parallel work on three fronts with the flip gated on all
three completing. A pure infra rebuild flips $25 into a -13% strategy stack;
that mechanism would work and the trade would still lose. A pure
strategy-fix without infra rebuild has nowhere to deploy. Track C is the
contract that prevents "we built the mechanism" being treated as authorization
to flip.

---

## Three tracks

### Track A — Live infrastructure rebuild (mostly sequential, ~4–8 sessions)

#### Phase A.0 — Pre-work prerequisites

- **Scope:** make the readiness scorer trustworthy; resolve any reconciler /
  halt-state debt; confirm the dual-ledger drift in `paper_positions.json` vs
  `paper_trades.db` is bounded.
- **Files touched:** `scripts/evaluate_live_readiness.py` (or whichever module
  computes the metrics in `deployment_decision.json`); audit of `paper_positions.json`
  vs `paper_trades.db` reconciliation path.
- **Why this is needed (surfaced by Step 1 diagnostics, not on the original
  prompt's A.0 list):**
  - `deployment_decision.json` (2026-05-21T09:32:01Z) reports `allowed: false`
    with blockers `Win Rate: 25.0% (min: 45.0%)`, `Maximum Drawdown: -781.0%`,
    `Infrastructure Uptime: 0.0%`. The -781% and 0% are arithmetic garbage —
    actual drawdown is -13.06% and the container is on cycle 71 with a 10s
    heartbeat. PF1 cannot run clean until these calculations are fixed.
  - `paper_positions.json` shows `{"crypto": {}}` while `paper_trades.db` has
    4 unmatched BUYs (ADA, RLUSD, U, USD1 — three are stablecoins). Two
    ledgers disagree about the open book. Bounds the value of any live PnL
    reconciliation by that drift.
  - `share_equality_mismatches.json = {}` and `halt_state.json` shows
    `crypto: false` — the share-equality detector and the crypto-side HALT
    state are clean. No Track A.0 work needed there.
- **Tests required:** unit test on the readiness scorer with synthetic inputs
  that previously produced -781%; assertion that `paper_positions.json` and
  `paper_trades.db` BUY-minus-SELL counts agree (or that the difference is
  explained by a known asymmetric strategy like halted C5b).
- **Rollback baseline:** `.rollback/<date>_A0_readiness_scorer/`.
- **Exit criteria:** `evaluate_live_readiness` returns numerically sensible
  metrics (drawdown ∈ [-100%, 0%]; uptime > 0%); blockers list reflects real
  state; share_equality + halt_state still clean.
- **Estimate:** 1 session.
- **Dependencies:** none. Parallel-safe with B.0.

#### Phase A.1 — State isolation + heartbeat-only live_loop in shadow

- **Scope:** separate risk-state files per mode (`risk_engine_state.paper.json`
  vs `risk_engine_state.live.json`); add a heartbeat-only `trading/live_loop.py`
  that imports the same cycle scaffolding as `paper_loop.py` but stubs the
  broker call; run both loops in shadow behind `SYSTEM__TRADING_MODE=live`
  feature flag in a sibling container, NOT replacing paper-crypto.
- **Files touched:** `risk/engine.py` (STATE_FILE discriminator), new
  `trading/live_loop.py`, new `deployment/docker-compose.live-shadow.yml` (or
  service-overlay), `deployment/scripts/validate_env.py` (live mode allowed
  for the shadow path).
- **Tests required:** integration test that paper-mode peak survives a
  live-mode session and vice versa; shadow container starts, heartbeats,
  emits cycle log lines, never enters trade-execution branch.
- **Rollback baseline:** `.rollback/<date>_A1_state_isolation/`.
- **Exit criteria:** two containers running side-by-side in compose,
  paper-crypto unchanged, new live-shadow container heartbeating without
  writing trades to any DB.
- **Estimate:** 2 sessions (one for risk-state isolation + tests, one for
  shadow loop + compose surgery).
- **Dependencies:** A.0 (need trustworthy readiness scorer before bringing up
  a second container).

#### Phase A.2 — Live-broker adapter (DRY-RUN mode)

- **Scope:** implement a concrete exchange adapter (broker selection is a
  deferred decision below); wire it into `live_loop.py` behind a DRY_RUN
  flag that captures intended orders to a separate `live_dry_run_trades.db`
  rather than placing them; reconcile DRY_RUN output against paper-crypto's
  signal output for the same cycles.
- **Files touched:** new `execution/live_broker_<exchange>.py`, new
  `data/live_dry_run_trades.db` schema, `live_loop.py` to call the adapter
  with DRY_RUN gate.
- **Tests required:** adapter unit tests against fixture responses; an
  integration test that runs paper-crypto signal generation and DRY_RUN
  capture for the same cycle and asserts symbol/side/size alignment; a
  reconciliation report comparing assumed paper prices vs the broker's
  real-time quotes at signal-emission time.
- **Rollback baseline:** `.rollback/<date>_A2_live_broker/`.
- **Exit criteria:** DRY_RUN captures 20+ cycles of intended orders; signal
  symbol/side/size matches paper-crypto exactly; price slippage measured.
- **Estimate:** 2 sessions.
- **Dependencies:** A.1 (need the live loop existing first).

#### Phase A.3 — `deploy_live_flip.py` rewrite

- **Scope:** rewrite the flip script to swap the compose service (or the
  container CMD), not just `.env`; add the compose-level carveout for
  `SYSTEM__TRADING_MODE=live`; update `validate_env.py` for the carveout;
  remove or update the `AUTO_APPROVAL_RULES.md:139` guardrail (deliberate,
  audited).
- **Files touched:** `scripts/deploy_live_flip.py`,
  `deployment/docker-compose.yml`, `deployment/scripts/validate_env.py`,
  `AUTO_APPROVAL_RULES.md`.
- **Tests required:** dry-run of the new flip script against a test compose
  file confirms it swaps the service correctly and validate_env permits
  live for the carveout only (not for general paper-loop reuse).
- **Rollback baseline:** `.rollback/<date>_A3_deploy_flip/`.
- **Exit criteria:** flip script idempotent, reversible
  (`--mode paper|live`); no env-only theatre; the three 2026-05-21 display-only
  PF1 fixes land here so PF1 runs clean without `--pf1-override`.
- **Estimate:** 1 session.
- **Dependencies:** A.2 (need the live broker to flip into).

#### Phase A.4 — Pre-flights against the new path

- **Scope:** PF1 (clean readiness without override), PF2 (reconcile clean),
  PF3 (Telegram synthetic), plus a **new PF4** — live-broker DRY_RUN shadow
  trade matches paper signal within tolerance over N cycles. X (tolerance)
  and Y (cycle count) determined empirically during A.2 — the working
  hypothesis is X ≤ 0.3% mid-spread slippage and Y ≥ 20 cycles.
- **Files touched:** runbook update at `docs/runbooks/2026-05-22_live_capital_go.md`;
  new PF4 recipe.
- **Tests required:** PF1–PF4 all green from the operator side without any
  override flag.
- **Rollback baseline:** runbook is reversible; no code rollback needed.
- **Exit criteria:** PF1=green, PF2=green, PF3=Telegram delivered, PF4=DRY_RUN
  reconciliation passes.
- **Estimate:** 1 session.
- **Dependencies:** A.3.

### Track B — Strategy profitability (parallel to A, ~4–6 sessions)

#### Phase B.0 — Per-strategy diagnostic deep-dive

- **Scope:** full code + recent-trade-log read on every strategy that produced
  realized P&L in the last 30d. Per the diagnostic appendix below, that is
  C3_altcoin_reversion (44 SELLs, -$5.63) and C6_bollinger_range (5 SELLs,
  -$0.13). The other 10 strategies in the doctrine universe produced zero
  trades and warrant a separate Phase B.0.5 to determine "why silent."
- **Success metric:** a written diagnostic memo per strategy citing
  file:line and trade-row evidence, ending with one of: HALT / PARAM-TUNE /
  REPLACE / KEEP.
- **Exit criteria:** all firing strategies have a triage recommendation;
  silent strategies have a "silent because…" explanation (config gate,
  scanner cap, dependency missing, etc.) or a triage flag.
- **Estimate:** 1 session (small, given only 2 firing strategies).
- **Dependencies:** none. Parallel-safe with A.0.

#### Phase B.0.5 — Silent-strategy audit (added by today's diagnostic)

- **Scope:** for each of C1, C2, C5b, N1–N7: why did this strategy produce
  zero trades over the 9-day paper-crypto window?
- **Why this exists:** the prompt assumed a 12-strategy stack; reality is a
  2-strategy stack. Either the silent strategies are deliberately gated, or
  the gate logic is wrong. Either outcome materially changes the Track B
  triage in B.1 — if 10 strategies are dormant by gate, B.1 mostly decides
  the fate of C3+C6; if they should be firing, B.0.5 surfaces an unlogged
  scanner regression.
- **Success metric:** binary classification per strategy:
  "deliberately-dormant" (cite gate config + intent) or "regressed-silent"
  (cite the missing log line / failed import / capped scanner output).
- **Exit criteria:** classification table merged.
- **Estimate:** 1 session.
- **Dependencies:** B.0.

#### Phase B.1 — Triage decisions

- **Scope:** per-strategy HALT / PARAM-TUNE / REPLACE / KEEP decision, each
  citing B.0 / B.0.5 evidence.
- **Success metric:** decisions block in this doc; new commit appending a
  table with strategy → decision → rationale → next action.
- **Exit criteria:** operator signs off on the triage table.
- **Estimate:** 1 session.
- **Dependencies:** B.0 + B.0.5.

#### Phase B.2 — Parameter sweeps on tune candidates

- **Scope:** for each PARAM-TUNE strategy from B.1, run a sweep against the
  paper-shadow path (backtest harness if extant; paper-shadow otherwise).
- **Success metric:** a sweep report per strategy showing the post-tune
  expected win rate and P&L distribution vs the current production params.
- **Exit criteria:** params either improve to break-even/positive on the
  sweep, or the strategy gets reclassified HALT in B.1's table.
- **Estimate:** 1–2 sessions.
- **Dependencies:** B.1.

#### Phase B.3 — Reduced-stack paper validation

- **Scope:** 4 consecutive calendar weeks of positive equity curve on the
  remaining strategies (post-HALTs, post-tunes), no single-week loss > 5%.
- **Success metric:** equity-curve plot + weekly P&L table.
- **Exit criteria:** 4 green weeks. If any week red > 5%, restart the
  4-week counter after fixing.
- **Estimate:** 4 weeks calendar (not session count — this is soak time).
- **Dependencies:** B.2.

### Track C — Flip gate (the explicit hurdle that must clear)

Each criterion is binary and citable to evidence.

- **C.1** All Track A phases (A.0 through A.4) complete and merged; PF1–PF4
  pass without override. Cite: PF1 output, PF2 reconcile JSON, PF3 Telegram
  screenshot, PF4 DRY_RUN reconciliation report.
- **C.2** Paper book is in an acceptable starting state for live flip, by
  one of two paths:
  - **(a)** organic recovery: paper equity drawdown shallower than -5% from
    its post-rebuild peak;
  - **(b)** explicit reset: `state-crypto` volume reset + fresh peak baseline,
    AND Track B.3 (4-week validation) passed on the reset book.
  Operator picks (a) or (b) at the time of evaluation; the diagnostic in
  Step 1.C is what informs that choice.
- **C.3** Live-broker dry-run (Phase A.2) shows order fills within X% of
  paper-mode assumed prices over Y trades. X and Y are pinned during A.2;
  working hypothesis X ≤ 0.3% mid-spread slippage, Y ≥ 20 cycles.
- **C.4** $25 tranche only. Escalation per the locked doctrine's tranche
  gates (G1–G5 unchanged; see "Doctrine reference" below).
- **C.5** Two human gates at flip moment unchanged: Telegram receipt at PF3,
  typed `FLIP TO LIVE $25` at deploy.

---

## Dependencies and parallelism

```
Week 1: [A.0] -----------------> [A.1]
        [B.0] --> [B.0.5] -----> [B.1]

Week 2: [A.1] --> [A.2]
        [B.1] --> [B.2]

Week 3: [A.2] --> [A.3] -------> [A.4]
        [B.2] --> [B.3 (soak begins, runs 4 weeks)]

Week 4-7: [B.3 soak] --------------> Track C gate evaluation
          [A.4 stays green via PF1-PF4 weekly re-run]

Week 7+: Track C gate review --> GO/NO-GO on $25 tranche
```

**Key insight:** A.0 and B.0 are parallel-safe and should start the same
session. A.1 (shadow live loop) does NOT block B-track progress because the
shadow loop doesn't trade. B.3 is the calendar-time long pole — it cannot be
compressed by adding sessions.

**Pessimistic estimate:** 7 sessions of Claude Code work + 4 calendar weeks
of B.3 soak. Best case the work is done in 3 weeks but C.2 still requires
B.3 evidence. Total: minimum **4 weeks calendar** from today to a Track C
gate review.

---

## Deferred decisions surfaced

These are NOT decided by this plan. The plan presents options; operator
decides at the point indicated.

1. **`state-crypto` volume reset vs ride-out** — decide at C.2 gate.
   - **Ride-out:** if the C3 triage from B.1 + the 2026-05-18 blowup-day
     root cause from B.0 produce a fix that recovers the open book, the
     ~$60 in current open BUYs (ADA + 3 stablecoins) is harmless to keep.
   - **Reset:** if B.0/B.1 conclude C3 is structurally broken and gets
     HALTed, the residual book's basis is broken too — reset is cleaner.
   - **Plan recommendation:** lean toward **reset** if B.1 HALTs C3.
     Stablecoin positions are zero-edge holdings; ADA is a single coin
     in a single strategy that won't be running. Easier than tracking what
     "drawdown" means against a peak the system can no longer reproduce.
2. **Live broker selection** — decide at A.2 entry.
   - **Options surfaced** (not recommended one over another without
     operator's regulatory context): Binance International (deepest
     liquidity, sub-$25 min-orders), Bybit (similar liquidity, simpler
     compliance for some jurisdictions), Kraken (US-compliant, conservative
     min-orders), CoinDCX (India-resident operator-friendly).
   - **Operator context** (from user profile memory): India-based; that
     constrains Binance/Bybit (workarounds exist) and favors CoinDCX or
     similar India-domiciled. The plan does not pick — operator's call.
3. **2026-05-21 display-only PF1 fixes** — land between A.3 and A.4 so PF1
   runs clean without `--pf1-override`. This is now an A.3 sub-task.
4. **`USE_UNIFIED_LEDGER` flag flip in production** — recommendation:
   flip ON at end of B.1 once strategy triage decisions don't depend on the
   dual-ledger reconciliation. Earlier than that risks B.1 triage
   misclassifying a strategy because the ledger drift hides its real edge.
5. **NSE/US side (`halt_state.json` shows `us: true, india: true`)** — out
   of scope for this plan; document as a separate decision when revisiting.

---

## Doctrine reference (consistency check)

This plan is consistent with the locked doctrine (2026-05-14) as captured
in [`2026-05-22_live_readiness.md`](2026-05-22_live_readiness.md):

| Doctrine item | Value in plan | Match? |
|---------------|---------------|--------|
| First tranche | $25 | ✓ |
| Doctrine floor | $100 (reached via $25 → $50 → $100 weekly escalation) | ✓ |
| Auto-revert: drawdown threshold on $25 tranche | -5% | ✓ |
| Auto-revert: any non-test reconcile HALT | Yes | ✓ |
| Auto-revert: share-equality delta > $0.50 | Yes | ✓ |
| Kill triggers (-15% market) | Inherited from `risk/engine.py`, unchanged | ✓ |
| 5 injection gates (G1–G5) | Inherited unchanged; Track C is ADDITIONAL, not a replacement | ✓ |
| Operator-only flip step (typed confirm + Telegram) | C.5 preserves both | ✓ |

**Doctrine amendments requested by this plan: 0.**

The locked-doctrine source memory (`aaats_locked_doctrine_2026_05_14.md`)
was not present on the workstation that authored this plan; the
consistency check above is against the readiness doc's transcription. If
the source memory says something different, treat the source as canonical
and update this table.

---

## Sprint cadence and review

- **Cowork session:** weekly Friday review of Track A + Track B status;
  outcomes append to "Status log" below.
- **Claude Code sessions:** 1–2 per week, scoped to a single phase.
- **The scheduled task** `aaats-live-readiness-gate-2026-05-29` fires the
  next kickoff conversation; that conversation should open by reading the
  Status log section of this doc.

---

## Diagnostic appendix

**Sources:** all P&L claims derive from `/app/data/paper_trades.db` via
`docker exec aaats-paper-crypto python /tmp/diag_*.py` on
`aaats@100.95.126.39`, run 2026-05-21T10:39Z. The exact SQL is preserved in
each script for re-run.

### Top-line — what the numbers say

- **Only 2 of the 12 doctrine strategies are actually executing** in
  paper-crypto over the 9-day window (2026-05-12 → 2026-05-21):
  C3_altcoin_reversion (92 trades) and C6_bollinger_range (10 trades).
  C1, C2, C5b (halted by design), and N1–N7 produced zero trades. The
  "12-strategy universe" in CLAUDE.md does not reflect live paper activity.
  This collapses the Track B triage scope to one primary strategy.
- **C3 is the loss source:** -$5.63 realized vs C6 -$0.13. Halting C3 would
  have moved 9d realized P&L from -$5.76 to -$0.13 (~98% of the loss is
  C3-attributable). The unrealized component (drawdown -13.06% vs realized
  ~5.7% of $100) is from peak-vs-trough timing on open positions; the
  realized-loss arithmetic alone does not explain the -13.06% drawdown
  number — see "Caveat" below.
- **2026-05-18 was a -$2.81 single-day blowup**, 9 SELLs all losers,
  >2.5× any other day's loss. Worth a root-cause in Phase B.0 — likely a
  market event correlated across the C3 universe rather than 9 independent
  bad trades.

### Caveat on drawdown vs realized P&L arithmetic

The `risk_engine_state.json` records peak=$116.53, last_equity=$101.32,
drawdown=-13.06%. Realized P&L from `paper_trades.db` sums to -$5.76 over
9 days. The remaining ~$9.5 of drawdown is **not** all unrealized
mark-to-market — the equity-curve math in the runner appears to include a
fee/slippage assumption and possibly the unified-ledger work's
`paper_portfolio.crypto.capital = $41.74` definition vs the BUY-SELL
trade-count definition. The ledger drift (`paper_positions.json = {}` vs
4 open BUYs in `paper_trades.db`) is the most likely source of the gap.
Phase A.0 (readiness-scorer triage) should pin this down because it bears
directly on what "drawdown" PF1 reads.

### A. Per-strategy P&L (window: all=9d, 7d)

```
strategy                       | win  | trades | sells | pnl_usd | wr  | avgW   | avgL   | best   | worst
C3_altcoin_reversion           | all  |     92 |    44 |  -5.634 | 27% | +0.253 | -0.279 | +1.044 | -1.296
C6_bollinger_range             | all  |     10 |     5 |  -0.128 | 20% | +0.060 | -0.047 | +0.060 | -0.059
C3_altcoin_reversion           |  7d  |     69 |    36 |  -4.875 | 33% | +0.253 | -0.344 | +1.044 | -1.296
C6_bollinger_range             |  7d  |      7 |     4 |  -0.111 | 25% | +0.060 | -0.057 | +0.060 | -0.059
```

**Sorted worst-first by pnl_usd (all-time):** C3 (-$5.634) > C6 (-$0.128).
The doctrine's 12-strategy universe collapses to a 2-row table because
the other 10 produced zero trades over the window.

**Source:** `/tmp/diag_a.py` on the box; 102 rows from
`paper_trades` between `MIN(timestamp)=2026-05-12T04:57:50Z` and
`MAX(timestamp)=2026-05-21T09:54:48Z`.

### B. Per-symbol P&L within the worst strategies

For C3 (the loss source), 32 distinct symbols traded. Top 5 worst (all C3):

```
symbol      | trades | sells | pnl_usd | win_rate
OP/USDT     |      2 |     1 |  -1.296 |   0%
ARB/USDT    |      2 |     1 |  -1.063 |   0%
PUMP/USDT   |      2 |     1 |  -0.782 |   0%
FET/USDT    |      4 |     2 |  -0.717 |   0%
LUNC/USDT   |      6 |     3 |  -0.560 |   0%
```

These five symbols account for **-$4.42 of the -$5.63 C3 total** (78% of
the C3 loss in 5 symbols out of 32). The C3 loss is concentrated by symbol;
the 27% C3 win rate is dragged by losers that are larger in magnitude than
winners (avgL=-$0.28 vs avgW=+$0.25). Halting these 5 symbols within C3
(rather than halting C3 entirely) is a B.1 option worth pricing.

For C6, the 5 symbols traded each had ≤2 trades each; no concentration
signal — C6's loss is too small to triage by symbol with confidence.

**Source:** `/tmp/diag_bcd.py`.

### C. Drawdown timeline (realized, daily resolution)

```
date         | sells | day_pnl | cum_pnl
2026-05-12   |    2  | -0.254  |  -0.254
2026-05-13   |    7  | -0.522  |  -0.775
2026-05-14   |    2  | -0.637  |  -1.413
2026-05-15   |    9  | -1.811  |  -3.224
2026-05-16   |    3  | -0.802  |  -4.025
2026-05-18   |    9  | -2.813  |  -6.838   *BLOWUP DAY (>2% of $100)
2026-05-19   |    9  | +0.743  |  -6.095
2026-05-20   |    6  | +0.630  |  -5.465
2026-05-21   |    2  | -0.297  |  -5.762
```

Peak in `risk_engine_state.json` ($116.53) is from a marking-to-market
moment between 2026-05-12 and 2026-05-18; realized-only cum_pnl never
crossed zero. The peak therefore reflects unrealized gains on then-open
positions that subsequently mean-reverted into realized losses. This is
material context for Phase A.0's readiness-scorer fix — the gate's
"drawdown" definition needs to be specified (mark-to-market or
realized-only? from peak or from initial deposit?) before PF1 can be
trusted.

**Source:** `/tmp/diag_bcd.py`.

### D. Strategy activity vs. universe (concentration)

- **C3_altcoin_reversion:** 32 distinct symbols. NOT concentrated — that's
  a wide universe. Per-symbol concentration of LOSSES exists (top-5 = 78%
  of C3 loss; see B) but trade activity is spread.
- **C6_bollinger_range:** 5 distinct symbols (TRX, EUR, FIL, ICP,
  币安人生/USDT). Note the unicode-named symbol — likely an exchange
  universe artifact worth surfacing in B.0.5.

**Concentration verdict for live-readiness:** the diversified C3 universe
mitigates single-coin blowup risk but not strategy-blowup risk. The 2026-05-18
9-of-9 losing day points at correlated downside across the C3 universe
(market-wide event) — diversification within C3 does not protect against
this.

**Source:** `/tmp/diag_bcd.py`.

### E. Reconciler / share-equality state

- `data/share_equality_mismatches.json` = `{}` — **clean**.
- `data/halt_state.json` = `{"us": true, "india": true, "crypto": false}`
  — crypto side (the live-flip target) is NOT halted. US/India HALTs are
  out of scope for this plan but worth surfacing separately.
- `data/state/risk_engine_state.json` = peak $116.53, last_equity $101.32,
  market_peaks.crypto $116.53.
- `data/paper_portfolio.json` crypto.capital = $41.74 (free cash; rest is
  in open positions per `paper_trades.db`).
- `data/paper_positions.json` = `{"india": {}, "crypto": {}}` — **empty**,
  while `paper_trades.db` shows 4 unmatched BUYs (ADA, RLUSD, U, USD1).
  **Two ledgers disagree.** This is the dual-ledger drift that the Q1–Q4
  unified-ledger work targets; flagged here as a Track A.0 input.
- `data/deployment_decision.json` (2026-05-21T09:32:01Z) reports
  `allowed: false` with blockers including `Maximum Drawdown: -781.0%` and
  `Infrastructure Uptime: 0.0%` — both arithmetic garbage. PF1 cannot be
  trusted until this is fixed in A.0.

**Source:** direct `cat` on the box; inputs preserved for re-run.

---

## Status log (append-only)

- **2026-05-21** — NO-GO declared on 2026-05-22 first tranche. This plan
  drafted. Diagnostic appendix populated; surfaced 3 issues beyond the
  original prompt scope (deployment_decision.json arithmetic garbage,
  paper_positions.json vs paper_trades.db drift, only-2-of-12 strategies
  firing). Next execution phase: **Track B.0** — per-strategy diagnostic
  deep-dive on C3 + C6, parallel-safe with **Track A.0** readiness-scorer
  fix.

---

## What this plan does NOT cover

- **v6 engine stack** (currently HALTED at -15.5% drawdown on the sibling
  `aaats-engine` container per `docs/known_issues/2026-05-21_aaats_engine_v6_halt.md`).
  Separate problem, separate doc.
- **NSE strategies N1–N7** — out of scope unless B.0.5 finds the silent
  classification is wrong AND they're contributing to current paper
  drawdown. The 9-day window shows zero N* trades.
- **$50/$100 escalation tranches** — revisit after the $25 tranche has at
  least 14 days of clean live data per the locked doctrine.
- **AUTO_APPROVAL_RULES.md governance** for the live mode — touched in
  A.3 but the broader governance review (when is `mode=live` auto-flippable
  by Claude vs operator-only) is intentionally not redrawn here.
