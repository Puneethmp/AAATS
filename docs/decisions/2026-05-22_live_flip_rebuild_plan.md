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

- **2026-05-21 (session 1)** — A.0 + B.0 + B.0.5 + D.0 executed in parallel.

  **Track A.0 — SHIPPED (workstation; not yet deployed to box).** Root
  cause located: `production_readiness/metrics_aggregator.py:127-136`
  (drawdown — `max(peak, 1.0)` denominator + realized-only pnl-curve
  instead of canonical equity peak) and `:210-211, 226` (uptime — binary
  `1.0 if heartbeats else 0.0` ignored freshness). The NO-GO doc's
  fingered path `monitoring/metrics_aggregator.py` does not exist; bug
  lives in `production_readiness/`. Fix prefers `data/state/risk_engine_state.json`
  peak/last_equity; falls back to a clamped pnl-curve calc with $100
  starting-capital denominator floor; uses `is_alive(market, max_age_seconds=120)`
  per-market for uptime. Tests: `tests/test_live_readiness_scorer.py`
  (3 drawdown + 3 uptime cases, 6/6 pass; fails pre-fix per design) and
  `tests/test_dual_ledger_drift.py` (bounded-drift baseline over data/
  and runtime/ ledgers, 2/2 pass). Rollback baseline at
  `.rollback/2026-05-21_A0_readiness_scorer/`. **Bind-mount note:** the
  bug-bearing file is image-baked, NOT bind-mounted — fix takes effect
  on box only after `docker compose ... up -d --build --no-deps aaats-paper-crypto`.
  Scorer is operator-invoked (next PF1 run), not a daemon, so a stale
  image continues producing garbage until rebuild.

  **Track A.0 — surfaced new findings:**
    (i) `runtime/paper_positions.json` has 9 actual positions while
        `data/paper_positions.json` is empty. Drift is between `data/`
        (canonical-for-prod) and `runtime/` (debug/scratch), NOT solely
        between `paper_positions.json` and `paper_trades.db`. Worth a
        Track B item to identify the writer of `runtime/paper_positions.json`.
    (ii) `data/share_equality_mismatches.json` is **NOT** empty —
        contains `{"C3_altcoin_reversion|TON/USDT":6, "...|FET/USDT":6}`.
        Pre-existing per `docs/operator/aaats_dual_equity_ledger_debt.md`,
        but the parent plan stated `{}`. State has changed since the
        plan was authored.
    (iii) Drift baseline updated in `tests/test_dual_ledger_drift.py`
        to reflect actual state: stablecoins + ADA + U + PENGU (open
        C3 BUY) + ICICIBANK (HALTed india leg). Rebaseline procedure
        documented in the test docstring.

  **Track B.0 — SHIPPED.** Three memos written:
    - `docs/known_issues/2026-05-21_strategy_c3_altcoin_reversion_diagnostic.md`
      — verdict **PARAM-TUNE** (contingent HALT). Load-bearing finding:
      `BTC_DOM_FAST_RISE = 0.008` is declared at
      `trading/altcoin_reversion.py:77` and documented in the module's
      own docstring at :10-11 as the "alt season over" entry filter, but
      it is **never read by `_entry_allowed` at :314-330**. Wiring it
      is a 1–3 line patch (concrete code sketch in the memo §5.1).
      Symbol-level halt math: residual P&L without OP/ARB/PUMP/FET/LUNC =
      **-$1.216 over 9d** (vs the full -$5.634), residual EV ≈
      -$0.034/trade. 2026-05-18 blowup root cause = market event
      (BTC-led rally) exposed by the unwired filter.
    - `docs/known_issues/2026-05-21_strategy_c6_bollinger_range_diagnostic.md`
      — verdict **KEEP** (insufficient data). 5 SELLs / -$0.128 is
      below triage-confidence noise floor; per-trade magnitudes within
      the strategy's own documented expected range. Re-evaluate after
      4 weeks of B.3 soak with ≥30 SELLs OR a >1% weekly loss.
    - `docs/known_issues/2026-05-21_silent_strategy_audit.md` (Phase
      B.0.5) — 1 regressed-silent (C1 stat_arb, `corr14d=0.000` from
      poisoned 7-day cache despite a sitting z=+4.74 signal — fix is a
      single-file deletion of `data/stat_arb_health.json`), 2 gate-honest
      dormant (C2, C5b), 7 out-of-scope dormant (N1 due to `--market crypto`
      at compose:92; N2–N7 have no source files). C1 is the
      highest-leverage near-term fix because it's market-neutral and
      lowers the equity-curve correlation against the
      currently-90%-directional book.

  **Track B.1 triage table (output of B.0 + B.0.5):**
    | Strategy | Verdict |
    |---|---|
    | C1_stat_arb | FIX (cache invalidation, prereq for B.2) |
    | C2_momentum_breakout | KEEP (gate-honest) |
    | C3_altcoin_reversion | PARAM-TUNE |
    | C5b_funding_arb | HALT (existing) |
    | C6_bollinger_range | KEEP (insufficient data) |
    | N1–N7 | OUT OF SCOPE |

  **Pytest:** 8/8 new tests pass; broader run shows 614/619 pass with
  5 pre-existing failures in `test_ml/`, `test_decision/`, and 6 errors
  in `test_india/test_angel_one_integration.py` (live broker creds).
  None caused by A.0 work — those files were not touched this session.

- **2026-05-22 (session 2)** — Five-track ship: C1 cache invalidation +
  A.0 box deployment + B.1 confirmation + D.1 + D.3 all green.

  **[0] C1 stat_arb cache invalidation — SHIPPED + observed.** Deleted
  `/app/data/stat_arb_health.json` on box (rollback backup at
  `/tmp/stat_arb_health.json.bak_2026-05-21_session2`). Next cycle at
  `2026-05-22T03:54:39Z` recomputed the cache cleanly:
  `eg_pvalue=0.0181, corr_14d=0.971, pair_healthy=True`. **The
  silent-strategy audit's diagnosed mechanism was partially stale.**
  The pre-deletion cache was `eg_pvalue=0.39, corr_14d=0.92,
  pair_healthy=False` — failing the cointegration gate (`eg_p < 0.05`
  at `trading/stat_arb.py:344`), NOT failing the correlation gate.
  Audit's quoted `corr14d=0.000` value matched an older state. After
  invalidation, the new cache passes both gates; C1 gate is OPEN. Spread
  z at observed cycle was −0.116 (below the `entry_z=1.8` threshold),
  so C1 honestly skipped this cycle — exactly the expected, gate-honest
  behaviour. C1 reclassified from `regressed-silent` → `gate-honest`
  pending z > 1.8. No further C1 work this session.

  **[1] A.0 box deployment — SHIPPED.** `production_readiness/metrics_aggregator.py`
  SCP'd to box via atomic `.tmp` + `mv -f`; image rebuilt with
  `docker compose -f deployment/docker-compose.yml up -d --build --no-deps
  aaats-paper-crypto`. Pre-deploy box SHA `56342edbdb17…`, post-deploy
  SHA `baab72511b71…` (matches workstation). Post-deploy PF1 verified:

  ```
  Score: 69.7%
  Blockers:
    - Win Rate: 28.8% (minimum: 45.0%)
    - Maximum Drawdown: -22.8% (threshold: -15.0%)
    - Infrastructure Uptime: 0.0% (minimum: 95.0%)
  ```

  Drawdown math fixed (real −22.8% from `risk_engine_state.json`
  peak/last_equity vs the previous −781% arithmetic garbage). PF1 now
  reports real metrics; Win Rate / Trades reflect actual paper state.
  **Uptime still 0%** — surfaced a NEW bug at
  `monitoring/heartbeat_monitor.py:142` (`Heartbeat(**hb_data)` — the
  reader expects a nested-per-market dict, but the runner writes a flat
  schema directly at `trading/live_paper_runner.py:1873-1882`). This is
  catalog row 1 verbatim and is what D.3 (also shipped this session)
  catches on startup. Fix is to remove the legacy nested reader path
  (or update it to match the flat writer); deferred to next session.

  **[1.a] paper_positions writer drift — DOCUMENTED.** Memo at
  `docs/known_issues/2026-05-22_paper_positions_writer_drift.md`.
  `runtime/paper_positions.json` is a workstation-only scratch file
  (the box host has no `runtime/`); production canonical is
  `data/paper_positions.json`. No production-code writer to `runtime/`
  was found. Recommended next action: delete the workstation
  `runtime/paper_positions.json` (deferred so memo can be reviewed first).

  **[1.b] share-equality alert chain audit — CLEAN.** Memo at
  `docs/known_issues/2026-05-22_share_equality_alert_chain.md`. Box
  `data/share_equality_mismatches.json` is `{}` with mtime
  `2026-05-16 08:26` (pre-session-1). Session 1's TON/FET-counter
  finding likely cited a workstation-side copy, not box production.
  Alert-chain end-to-end was validated by the 2026-05-16 synthetic
  test (per `CLAUDE.md`) and remains intact. **No new D-track row
  added; no catalog change.**

  **[2] B.1 triage confirmation block — MERGED (this commit).** See the
  block immediately below. C3 verdict revised to "PARAM-TUNE +
  symbol-halt (combined)" per session-1 symbol-halt math; C1 verdict
  revised to `KEEP (gate-honest after [0])`; other strategies as
  drafted in the silent-strategy audit's Phase B.1 table.

  **[3] D.1 per-strategy exception isolation — SHIPPED.** New
  helper `trading/strategy_isolation.py::run_strategy_with_isolation`
  + per-strategy halt state `risk/strategy_halt.py` writing to
  `data/strategy_halt_state.json`. The five strategy-dispatch call
  sites in `trading/live_paper_runner.py` (N1, C1, C2, C3, C6) replaced
  the bare try/except with the isolation envelope. Three consecutive
  same-strategy exceptions → auto-halt via the helper + Telegram alert;
  successful run resets the streak. Counter exposed by
  `monitoring/metrics_exporter.py::collect_strategy_exceptions` as
  `aaats_strategy_exception_total{strategy=...}` plus
  `aaats_strategy_consecutive_exceptions{...}` and
  `aaats_strategy_halted{...}`. Tests at
  `tests/test_strategy_isolation.py` cover all 7 cases (success
  resets, single exception no-halt, 3-consecutive auto-halt with
  sibling-still-runs, Telegram alert on halt, success-after-failure
  resets streak, already-halted skips dispatch, reset re-enables).

  **[4] D.3 schema-drift assertions — SHIPPED.** New module
  `state/schemas.py` with pydantic v2 models for the 5 state files
  (heartbeat / halt_state / risk_engine_state / paper_positions /
  share_equality_mismatches). Validating I/O helpers `load_validated`
  / `save_validated` route writers and readers through the schema.
  Startup smoke in `trading/live_paper_runner.py::main` calls
  `validate_all_state_files(data_dir)` and refuses-to-start on any
  `INVALID` result (`SystemExit` with the offending file). Tests at
  `tests/test_state_schemas.py` cover all 5 schemas (16 cases incl.
  production-state-shaped fixtures from the 2026-05-22 box snapshot,
  legacy-shape rejection, extra-key rejection, malformed-JSON failure
  path, and the cross-cutting `validate_all_state_files` reporter).

  **Pytest:** 31/31 new + regression tests green:

  ```
  tests/test_state_schemas.py          16 passed
  tests/test_strategy_isolation.py      7 passed
  tests/test_dual_ledger_drift.py       2 passed
  tests/test_live_readiness_scorer.py   6 passed
  ```

  Rollback baseline at `.rollback/2026-05-22_d1_d3_isolation_schemas/`.

- **2026-05-22 (session 3)** — Four-track ship: [0] heartbeat reader +
  [1] box deploy of D.1/D.3/heartbeat + [2] B.2 C3 patch + [3] D.2
  watchdog + [4] A.1 design memo. PF1 score 80.6% → 100.2%; Infrastructure
  Uptime cleared from blockers.

  **[0] Legacy heartbeat reader removal — SHIPPED.**
  `monitoring/heartbeat_monitor.py` rewritten for the FLAT schema
  (catalog row 1). Dataclass mirrors `state.schemas.HeartbeatSchema`
  (`timestamp/cycle/market/cycle_duration_seconds`); `emit_heartbeat` +
  the legacy `HeartbeatMonitor.emit_heartbeat` removed (runner is sole
  writer); `get_heartbeat / get_all_heartbeats / is_alive` rewritten for
  flat shape. `"--market both"` fans out to crypto+india. Dead path
  cleanup: `trading/paper_loop.py::emit_cycle_heartbeat` removed (no
  callers). `tools/operator/test_monitoring_modules.py` updated to
  simulate the runner's flat write directly. `tests/test_heartbeat_monitor.py`
  added (11 tests: flat round-trip + legacy-shape rejection + edge cases).
  `tests/test_live_readiness_scorer.py::_seed_heartbeat` migrated to flat.
  `runtime/paper_positions.json` deleted per the 1.a memo.

  **[1] SCP-deploy D.1 + D.3 + heartbeat-reader fix — SHIPPED + verified.**
  `scripts/deploy_session3_d1_d3_heartbeat.py` (new) atomic-swapped 7
  files (D.1 new tree + D.3 new tree + heartbeat-reader fix). First
  rebuild surfaced a residual `from monitoring.heartbeat_monitor import
  emit_heartbeat` in `trading/paper_loop.py` (production entry point
  delegates to `trading/live_paper_runner.py::main()` at :350) →
  ImportError → restart loop. Follow-up swap shipped the cleaned-up
  `paper_loop.py`. Container stable, cycle 1 completed in 13.2s with
  fresh heartbeat write. PF1 post-verify:

  ```
  Score: 100.2%
  Blockers:
    - Win Rate: 28.3% (minimum: 45.0%)
    - Maximum Drawdown: -33.4% (threshold: -15.0%)
  ```

  **Infrastructure Uptime cleared** (was 0.0% / a blocker in sessions
  1+2). Remaining 2 blockers are real strategy-state values; the
  drawdown is per the canonical `risk_engine_state.json` (peak=$131.32,
  last_equity≈$87.45). Rollback baseline at
  `.rollback/2026-05-22_session3_d1_d3_heartbeat_box/MANIFEST.txt`.

  **Pre/post-deploy box SHAs (live_paper_runner.py):**
  pre=`7d48a501ad2a85f7…` → post=`72f675535632e89a…` (includes the
  post-deploy halt_on_critical band-aid swap + B.2 btc_dom_now wiring).

  **[1].a — production entry point clarified.** Sessions 1+2's repeated
  reference to `trading/live_paper_runner.py` as "the runner" was
  partially correct: `live_paper_runner.py:main()` is the loop, but the
  container's compose CMD is `python trading/paper_loop.py --market crypto`.
  `paper_loop.py:350-370` is a thin arg-parser shim that delegates to
  `live_paper_runner.main()`. D.3 startup smoke fires correctly because
  the delegation invokes the runner's main. The session-2 catalog
  references to "runner main" remain valid; the entry-point label was
  the only ambiguity.

  **[1].b — kill-trigger band-aid (operator-approved).** Session-2's
  `d1b7feb` set `halt_on_critical=True` at
  `trading/live_paper_runner.py:1881`. The box was running the
  pre-d1b7feb image until this session's deploy. Post-deploy the
  reconciler HALTed every cycle on a real ~$7 BTC/ETH drift
  (`symbol_present_in_only_one_source`) — restart-loop fingerprint
  (RestartCount 6→14 in 5min). Operator approved reverting to
  `halt_on_critical=False` (band-aid) and deferring the BTC/ETH ledger
  drift to the unified-ledger sprint. Reconciler still WARNs every
  cycle; the WARN is now the surfaced signal, not a HALT. Container
  stable post-revert (cycle 1 completed in 13.2s).

  **[2] B.2 — C3 PARAM-TUNE + symbol-halt — SHIPPED + deployed.**
  `trading/altcoin_reversion.py`:
    - (a) `BTC_DOM_FAST_RISE` wired into `_entry_allowed` (declared at
      :77 but unread since 2026-05-12). New `data/c3_btc_dom_cache.json`
      persists the previous cycle's BTC.D reading; the runner passes
      `btc_dom_now=btc_dom` and altcoin_reversion computes the
      percentage-point delta. Filter refuses entry when delta ≥ 0.8 pp.
    - (b) `DENYLIST_SYMBOLS = {OP/USDT, ARB/USDT, PUMP/USDT, FET/USDT,
      LUNC/USDT}` short-circuits the ENTRY branch. Held positions take
      the manage-open branch and exit cleanly (SELL is NOT impeded).
    - First-cycle semantics: no cache → delta=None → filter inactive
      (gate-honest first cycle after a (re)deploy).
  `trading/live_paper_runner.py`:
    - Pass `btc_dom_now=btc_dom` into the C3 dispatch site (the
      isolation envelope from session 2 already accepts kwargs).
  Tests: `tests/test_altcoin_reversion_btc_dom_filter.py` 9/9 green
  (5 filter semantics + 2 denylist + 2 cache round-trip). Deployed in
  the same SCP swap as the halt_on_critical band-aid revert.

  **[3] D.2 — Heartbeat watchdog sidecar — CODE + TESTS shipped, BOX
  DEPLOY DEFERRED to operator approval (compose-level change).**
  `health/watchdog.py`: pure-logic `WatchdogState.classify` decision
  machine (verbs: ok / restart / restart_missing / escalate),
  IO-shell `Watchdog.tick`. Detects via `now - heartbeat.timestamp >
  3 × CYCLE_INTERVAL_SEC = 2700s`. Restart rate-limited to 3 in
  30 min; 4th detection escalates Telegram-only. Self-heartbeat at
  `data/watchdog_heartbeat.json`. `deployment/Dockerfile.watchdog`:
  python:3.11-slim + docker CLI + python-telegram-bot. Compose entry
  for `aaats-watchdog` mounts `/var/run/docker.sock` (full rw — Docker
  socket doesn't support ro mounts; least-privilege deferred). Tests
  at `tests/test_watchdog.py` (11/11 green): state-machine 6 + tick
  integration 5 (incl. 4th-tick escalation + docker-restart-failure
  follow-up alert). Manual end-to-end on box deferred to a follow-up
  rebuild (the docker.sock mount is a privileged change; operator
  approval queued for next session — flagged in next_session_prompt).

  **[4] A.1 — State isolation design (memo only) — SHIPPED.**
  `docs/decisions/2026-05-22_state_isolation_design.md` (new): proposes
  env-var discriminator + per-mode named-volume layout for
  `risk_engine_state.{paper,live}.json`. Code at `risk/engine.py:44-46`
  already supports `AAATS_RISK_STATE_FILE` override; the memo adds a
  `SYSTEM__TRADING_MODE`-driven path resolution + per-mode named volumes
  (`state-crypto-paper`, `state-crypto-live`). NO code edits this
  session. Operator review gate on the compose change. Implementation
  queued for session 4.

  **Pytest:** 61/61 + 1 cleanly skipped:

  ```
  tests/test_heartbeat_monitor.py                11 passed (new)
  tests/test_altcoin_reversion_btc_dom_filter.py  9 passed (new)
  tests/test_watchdog.py                         11 passed (new)
  tests/test_state_schemas.py                    16 passed (regression)
  tests/test_strategy_isolation.py                7 passed (regression)
  tests/test_live_readiness_scorer.py             6 passed (regression)
  tests/test_dual_ledger_drift.py                 1 passed + 1 skip (runtime/ absent per 1.a memo)
  ```

  Rollback baselines at `.rollback/2026-05-22_session3_d1_d3_heartbeat_box/MANIFEST.txt`.

---

## B.1 triage table (decision merged 2026-05-22 session 2)

The Phase B.1 triage table drafted in
[`docs/known_issues/2026-05-21_silent_strategy_audit.md`](../known_issues/2026-05-21_silent_strategy_audit.md)
§"Triage table for Phase B.1" is hereby confirmed with two revisions
from this session:

| Strategy | Verdict | Rationale | Next action (file:line scope; NO code edits this session) |
|---|---|---|---|
| `C1_stat_arb` | **KEEP (gate-honest)** | After 2026-05-22 cache invalidation, gate passes (`eg_p=0.0181, corr_14d=0.971`). Strategy honestly skipped current cycle on z=−0.116 < `entry_z=1.8`. Monitor for z > 1.8 next 7d. | `trading/stat_arb.py:478` — add `apply_kill_switch_gate` call site to parity with C3/C6 (deferred to session 3 B.2). |
| `C2_momentum_breakout` | **KEEP (gate-honest)** | Gate at `trading/momentum_breakout.py:200-201` honestly refusing on `regime=BEAR_TREND` AND `F&G < 40`. No action until regime+sentiment flip. | None. Re-fires automatically. |
| `C3_altcoin_reversion` | **PARAM-TUNE + symbol-halt (combined)** | Per [`docs/known_issues/2026-05-21_strategy_c3_altcoin_reversion_diagnostic.md`](../known_issues/2026-05-21_strategy_c3_altcoin_reversion_diagnostic.md) §5. Combined-verdict math (session 1): residual P&L without top-5 = −$1.216/9d vs full −$5.63/9d. Reversible. | (a) Wire `BTC_DOM_FAST_RISE` at `trading/altcoin_reversion.py:_entry_allowed` (lines 314-330; constant declared at :77, never read); (b) extend the symbol deny-list to include `OP/USDT, ARB/USDT, PUMP/USDT, FET/USDT, LUNC/USDT` at `trading/altcoin_reversion.py:487` per-cycle universe loop. Sweep in B.2. |
| `C5b_funding_arb` | **HALT (existing)** | Already commented out at `trading/live_paper_runner.py:1666-1670` since 2026-05-15. Re-enable only after unified-ledger Q1–Q4 resolves $25/leg vs $50/round-trip asymmetry. | None. Per `docs/known_issues/2026-05-15_c5b_halt.md` re-enable checklist. |
| `C6_bollinger_range` | **KEEP (insufficient data)** | Per [`docs/known_issues/2026-05-21_strategy_c6_bollinger_range_diagnostic.md`](../known_issues/2026-05-21_strategy_c6_bollinger_range_diagnostic.md): 5 SELLs / −$0.128 is below noise floor. Re-evaluate after 4 weeks B.3 soak with ≥30 SELLs OR a >1% weekly loss. | None this session. |
| `N1_stat_arb_india` | **OUT OF SCOPE** | Container runs `--market crypto`; NSE side dormant until week 7+ per doctrine. | None. |
| `N2–N7` | **OUT OF SCOPE** | No source files exist; design-time labels only at `docs/operator/aaats_strategy_universe.md`. | None. |

The B.2 phase (parameter sweeps on the C3 PARAM-TUNE candidates) consumes
this table as input. The C3 wire+denylist patch is the only behavior
change anticipated for B.2 — it's reversible and reduces realized loss
by ~78% per the session-1 symbol-halt math.

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
