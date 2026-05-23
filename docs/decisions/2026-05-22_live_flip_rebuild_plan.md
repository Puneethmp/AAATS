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
  PF3 (Telegram synthetic), PF4 (live-broker DRY_RUN shadow trade matches
  paper signal within tolerance over N cycles; X ≤ 0.3% mid-spread slippage
  and Y ≥ 20 cycles, pinned during A.2), and **PF5** (failure-mode stress
  tests — see PF5 subsection below).
- **Files touched:** runbook update at `docs/runbooks/2026-05-22_live_capital_go.md`;
  new PF4 recipe; new PF5 recipes in `tests/preflight/test_pf5_*.py` and a
  PF5 runbook at `docs/runbooks/2026-05-24_pf5_failure_mode_stress.md`.
- **Tests required:** PF1–PF5 all green from the operator side without any
  override flag.
- **Rollback baseline:** runbook is reversible; no code rollback needed
  (PF5 uses synthetic injection, not production code changes).
- **Exit criteria:** PF1=green, PF2=green, PF3=Telegram delivered, PF4=DRY_RUN
  reconciliation passes, PF5=all 8 scenarios pass with no manual intervention.
- **Estimate:** 2 sessions (1 for PF1–PF4 as previously scoped, 1 for PF5
  scenario implementation + run).
- **Dependencies:** A.3 for PF1–PF4; PF5 has no additional code dependency
  but operationally requires the box to be running and the watchdog/metrics
  containers reachable.

##### PF5 — Failure-mode stress test scenarios (added 2026-05-24, Cowork pass)

**Purpose:** verify the resilience paths already shipped (D.1 strategy
isolation, D.2 watchdog, three-channel kill switch, idempotency, reconciler)
actually behave correctly end-to-end under synthetic-but-realistic failure
injection. PF5 is NOT net-new resilience code — it is verification that the
existing code works as advertised. Without PF5, the C.1 claim "PF1–PF4 pass
without override" certifies the happy path only.

**Scope discipline (anti-drift):** PF5 covers failure modes that have either
already hit AAATS in production (rate limits, container crashes, exchange
flakes) or are guaranteed to hit it given enough live calendar time
(latency spikes, slippage, network partitions). PF5 explicitly does NOT
cover: futures/perpetuals/funding-rate scenarios (out of doctrine; spot
only), liquidation cascades (no leverage), regime-detection logic
(premature — needs B.3 + C.7 first), Monte Carlo simulations (needs the
B.1.5 backtest harness, deferred to post-B.2). If a stress-test idea
doesn't fit one of the 8 scenarios below, it belongs in a new memo, not
a PF5 expansion.

**Each scenario specifies:** trigger recipe (synthetic), expected system
behavior, observable signal, pass criterion. All triggers run against a
dedicated `state-crypto-stress` volume to avoid contaminating
`state-crypto-paper`.

| # | Scenario | Trigger recipe | Expected behavior | Observable signal | Pass criterion |
|---|---|---|---|---|---|
| **PF5.1** | Binance API rate limit (429) | `ccxt` monkeypatch: raise `RateLimitExceeded` on next 3 `create_order` calls, then succeed | Backoff/retry succeeds; no duplicate orders placed; idempotency key honored | `data/orders.db` has 1 row per intended order (not 3); logs contain "retrying after rate limit" with attempt count | Order eventually fills; share-equality reconciler shows zero divergence; total elapsed ≤ 60s |
| **PF5.2** | Binance API transient 5xx | `ccxt` monkeypatch: raise `ExchangeNotAvailable` on next 2 calls then succeed | Exponential backoff retry; succeed on 3rd attempt | Log entry "retry attempt 3/3 succeeded"; ledger has correct single fill | Order completes within 30s; zero manual intervention; reconciler clean |
| **PF5.3** | Network partition (cannot reach exchange) | On box: `sudo iptables -A OUTPUT -d api.binance.com -j DROP` for 60s, then flush | Orders queue or fail-fast; no zombie orders placed; on reconnect, reconciler catches up via Binance order history | `alerts_log.json` has "exchange unreachable" event with start+end timestamps; recovers when iptables flushed | No double-fill on recovery; final ledger matches Binance order history; gap visible in heartbeat but watchdog does not restart container (network failure is not container failure) |
| **PF5.4** | Order placed but ack timeout (latency spike) | `ccxt` monkeypatch: `sleep(90)` before returning ack (longer than runner's `ORDER_ACK_TIMEOUT`) | Runner times out, marks order as "ack-pending"; reconciler later detects the placed-but-unacked order via Binance order history and reconciles | Order visible in Binance's history but missing in local ledger initially; reconciler logs "found unacked order, reconciling" within next cycle | Ledger eventually consistent; no duplicate placement; share-equality clean within 2 cycles |
| **PF5.5** | Slippage spike (fill far from quoted price) | Synthetic order injection with `execution_price` 5% off `quoted_mid_at_decision` | Per-trade -2% stop fires on next mark-to-market cycle | Position SELL emitted within 1 cycle; realized PNL ≈ -2% + slippage; `alerts_log.json` records the stop firing | Position closed; no runaway loss; total realized loss ≤ -2.5% of position notional |
| **PF5.6** | Consecutive strategy exceptions trigger D.1 auto-halt | Monkeypatch one strategy's `generate_signals()` to raise `RuntimeError` 3 times consecutively | D.1 isolation halts that strategy (writes to `strategy_halt_state.json` with halt_reason + timestamp) | `strategy_halt_state.json` contains the strategy key with `halted=true, reason="3 consec exceptions"`; daily digest "Halted strategies" row updates | Other strategies continue running uninterrupted; halted strategy stops emitting signals; container does NOT restart |
| **PF5.7** | Container crash + D.2 watchdog restart | On box: `docker exec aaats-paper-crypto kill -9 1` | Docker restart policy + watchdog noticed the heartbeat gap, restart container | Container restart count incremented; watchdog log entry "heartbeat stale > threshold, restart attempted"; new heartbeat write within 60s of restart | No lost orders (any in-flight orders reconcile via PF5.4 path); reconciler shows zero divergence post-restart; `aaats_metrics_exporter_up` returns to 1.0 within 60s |
| **PF5.8** | Flash crash (instantaneous mark drop ≥ -20%) | Inject synthetic mark drop in `mark_to_market` path: force market equity to 0.79 × persisted peak for one cycle | Engine portfolio-kill fires (`HALT_ALL`); all new entries blocked; MTM continues for open positions | Digest shows "portfolio-kill threshold reached"; `risk_engine_state.paper.json` reflects the synthetic equity; `halt_state.json` crypto STAYS false (operator channel untouched — verify the kill channels are not cross-contaminating) | Zero new BUYs placed for next 3 cycles; existing positions still marked-to-market; engine kill auto-clears on next cycle if synthetic mark restored (re-derives from peak) |

**Scenarios deliberately excluded (with reason, so they cannot be added by drift):**

- **Futures funding spike**: not applicable — AAATS is spot-only per locked doctrine (`aaats_locked_doctrine_2026_05_14.md`). Adding futures = Track E (new broker adapter, new liquidation engine, new state schemas). PF5 cannot certify what AAATS does not trade.
- **Leverage liquidation cascade**: same reason as above. Spot has no liquidation.
- **Correlation crash across pairs**: requires N≥100 trade sample for statistical correlation. Pre-B.3, the sample doesn't exist.
- **Multi-strategy cascading failure**: D.1 isolation is the existing mitigation; PF5.6 verifies it. A multi-strategy cascade would mean D.1 failed, which is the PF5.6 failure case.
- **Operator phishing / API key compromise**: out of scope — operational security, not platform code.

**Implementation order:** PF5.1, PF5.2, PF5.5, PF5.6, PF5.8 first (pure
in-process monkeypatch, no box network changes). PF5.7 next (single
`docker exec kill -9`, low blast radius). PF5.3 last (iptables on the
box — schedule for a window when the operator is online and can flush
the rule if anything goes sideways).

**Test artifacts:** each scenario gets a `tests/preflight/test_pf5_N_<slug>.py`
file. Scenarios that require synthetic injection in production code
(PF5.5 slippage, PF5.8 flash crash) use existing test seams in
`risk/engine.py` and `execution/paper_executor.py` — no new production
hooks. PF5.3 and PF5.7 are operator-run from a checklist in the PF5
runbook, not pytest-driven (they require root on the box).

**Cross-references:** Mitigations under test live at `risk/strategy_halt.py`
(D.1, PF5.6), `aaats-watchdog` container (D.2, PF5.7), `risk/engine.py:39`
(market kill, PF5.8), `execution/idempotency.py` (PF5.1–PF5.4), `risk/engine.py:340-368`
(per-trade -2% stop, PF5.5). The Cowork triage that produced this PF5 list
lives at the Cowork chat dated 2026-05-23 ("institutional-grade prompt"
triage) and is summarized in memory `aaats_2026_05_23_wishlist_triage.md`.

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

- **C.1** All Track A phases (A.0 through A.4) complete and merged; PF1–PF5
  pass without override. Cite: PF1 output, PF2 reconcile JSON, PF3 Telegram
  screenshot, PF4 DRY_RUN reconciliation report, PF5 stress-test summary
  (8 scenarios × pass/fail × elapsed time × observable signal).
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
- **C.6** D.5 30-day no-intervention soak passed: 30 consecutive daily digests
  delivered with `Action needed: NONE`, zero unresolved alerts, zero manual
  ops. Cite: the 30 digest payloads archived in `data/digests/`. Added by
  [`2026-05-21_track_d_reliability_addendum.md`](2026-05-21_track_d_reliability_addendum.md).
- **C.7** **PROFITABILITY GATE (added 2026-05-23, Cowork strategic review).**
  The 4-week Phase B.3 paper-soak's final equity must be **≥ the soak's
  starting equity**. Net-flat or net-positive. This is STRICTER than the
  pre-existing B.3 criterion ("no single-week loss > 5%"), which a -3%/wk
  bleed pattern could pass while still losing 12%/yr in real terms. Rationale:
  reliability ≠ edge. A bot that is reliable but bleeding does not deserve
  $25 of real capital — the locked doctrine's `-5%` auto-revert would just
  return the capital on day 1 of live mode, wasting the tranche. Cite:
  weekly equity-curve table in the B.3 status log + final-vs-start equity
  number.
  - **If C.7 fails AND the cause is identifiable** (e.g., one strategy is
    the loss source by ≥80%): treat as a Track B re-triage trigger (HALT
    or REPLACE the loss source), then re-run B.3 from week 0. Do NOT
    repeat-tune the same strategy in the same regime — that's the
    rebuild-loop antipattern the autonomy contract was written to end.
  - **If C.7 fails AND the cause is regime-wide** (all strategies bleed
    proportionally): pause the live-flip path entirely; the strategy
    universe needs replacement, not patching. Doctrine still protects via
    the 5 injection gates + auto-revert.
  - **If C.7 passes:** proceed to the C.1–C.6 evaluation. C.7 does NOT
    unblock anything else — it just prevents proceeding when the engineering
    is correct but the edge is absent.

### Track E — Operator-away autonomous-soak setup (added 2026-05-23)

**Why this track exists:** the operator is going out of station on
2026-05-25 for a multi-day-to-multi-week period. The D.5 30-day no-intervention
soak must START before departure so the calendar clock runs while the
operator is away. This requires (a) the operator-halt MTM gap from session 7
to ship, (b) the strategy stack to be backtest-validated for likely
profitability, (c) the paper book to be reset to a clean state ($200 per
doctrine amendment), (d) the pre-auth runbook to be in place, (e) PF5
stress tests to pass, (f) the Telegram pager chain to be validated.

Track E does NOT change C.1–C.7 gates. Live flip still requires Track C
evaluation post-soak. Track E ONLY enables autonomous paper soak.

#### Phase E.1 — Operator-halt MTM gap fix + open-position reconciliation

- **Scope:** session 8 [0a]/[0]/[0c] per `docs/decisions/2026-05-21_next_session_prompt.md`. Verify open positions, hoist MTM above is_halted check, second failing-then-passing test for per-trade -2% stop firing under operator halt.
- **Why ship-blocker:** without this, post-reset positions could re-freeze under any operator halt, breaking the autonomous soak.
- **Estimate:** session 8 (~90 min).
- **Dependencies:** none — already queued.
- **Exit criteria:** session 8 ships + box deploy + post-deploy verification (operator halt set → take-profit position still closes).

#### Phase E.2 — B.1.5 backtest harness build + run

- **Scope:** build minimal backtest harness per `docs/decisions/2026-05-22_b15_backtest_harness.md`. Run C3 against 60 days of historical Binance USDT OHLCV. Compute: P&L, Sharpe, win rate, profitable-in-2-of-3-regimes, slippage-sensitivity at 0.5%. Output: `data/backtest_results/c3_60d_summary.json` with a `recommendation: GO|PARTIAL|NO-GO` field.
- **Why ship-blocker:** without backtest-driven GO/NO-GO, starting a 30-day soak on -$5.63/9d-trending strategy is throwing 30 days at a likely losing system. Operator explicitly requested "stress test profitability before paper trade" 2026-05-23.
- **Estimate:** 1–2 sessions (1 to build, 1 to run + analyze; could compress if harness is simple).
- **Dependencies:** none — parallel-safe with E.1.
- **Exit criteria:** summary JSON exists; recommendation field is GO, PARTIAL, or NO-GO; downstream reset script can read it.

#### Phase E.3 — PF5 stress-test scenarios (subset for soak-readiness)

- **Scope:** ship PF5.1, PF5.2, PF5.5, PF5.6, PF5.7, PF5.8 per A.4 PF5 spec. Defer PF5.3 (iptables — requires operator online) and PF5.4 (latency — needs careful timing) to post-departure if time-constrained.
- **Why ship-blocker:** stress tests verify the resilience paths the bot will need to use autonomously. PF5.7 (container restart) and PF5.6 (D.1 strategy halt) are the highest-frequency in-soak scenarios.
- **Estimate:** 1 session.
- **Dependencies:** A.4 PF5 spec (already in plan, this doc).
- **Exit criteria:** 6 of 8 PF5 scenarios pass with no manual intervention; PF5.3/PF5.4 documented as post-departure.

#### Phase E.4 — Reset paper book to $200 + start D.5 day-1

- **Scope:** ship `scripts/reset_paper_book_200.py` that (1) reads backtest GO/NO-GO file from E.2, (2) refuses to run if NO-GO, (3) stops aaats-paper-crypto, (4) wipes `deployment_state-crypto-paper`, (5) reinitializes at $200 baseline, (6) restarts container, (7) waits for first NONE-NONE digest and writes timestamp to D.5 day-1 marker.
- **Why ship-blocker:** the actual mechanism for starting the autonomous soak.
- **Estimate:** 0.5 session.
- **Dependencies:** E.1 + E.2 must ship first.
- **Exit criteria:** script runs on Day 3, first NONE-NONE digest fires within 24h, D.5 day-1 marker file exists.

#### Phase E.5 — Operator-away runbook validation

- **Scope:** validate `docs/runbooks/2026-05-23_operator_away_protocol.md`:
  1. Send synthetic pager-level Telegram message via `send_alert(..., level='pager')`. Confirm receipt on operator phone.
  2. Send synthetic "Action needed != NONE" digest. Confirm pager fires after 3 consecutive (synthetic).
  3. Simulate B.2 P1/P2/P3 all-green response and verify auto-proceed-to-B.3 logic runs.
  4. Simulate F1 fire and verify auto-HALT-C3 logic runs.
  5. Operator reviews runbook end-to-end and signs off in Telegram chat.
- **Why ship-blocker:** the runbook IS the operator's contract for the away period. Untested = false confidence.
- **Estimate:** 0.5 session.
- **Dependencies:** E.4 (runbook references a running bot).
- **Exit criteria:** all 5 validation steps pass; operator types departure-bye in Telegram.

#### Phase E.6 — Telegram CLI bot for remote /kill-all /resume (optional)

- **Scope:** Telegram bot listening on `1946109268` for `/kill-all` (invokes `kill.py halt --all`) and `/resume` (clears strategy_halt_state.json for a specific strategy). Auth: operator's Telegram user_id only.
- **Why optional:** SSH-from-laptop covers this; only needed if operator is phone-only.
- **Estimate:** 0.5–1 session.
- **Dependencies:** E.1 (bot needs MTM gap fix to safely resume halted strategies).
- **Exit criteria:** bot receives commands; commands execute; operator confirms phone-side test.

#### Track E execution schedule (3-day ship)

| Day | Critical-path work | Parallel work | Exit gate |
|---|---|---|---|
| **Day 1: 2026-05-23** | E.1 (session 8 — running). E.2.a (build B.1.5 harness — session 9). | This Cowork doc + doctrine amendment + runbook + memory updates. | Session 8 ships clean; harness skeleton runs end-to-end on a 1-day historical sample. |
| **Day 2: 2026-05-24** | E.2.b (run backtest on 60-day historical, compute GO/NO-GO). E.3 (PF5 scenarios). | E.6 if time permits. | Backtest summary JSON exists with GO/PARTIAL/NO-GO recommendation. 6/8 PF5 scenarios pass. |
| **Day 3: 2026-05-25** | E.4 (reset script + run if GO/PARTIAL). E.5 (runbook validation). | Final commit + push. | D.5 day-1 marker file exists; operator-bye Telegram sent. |

#### Track E failure modes (what happens if E doesn't ship by 2026-05-25)

- **If E.1 (MTM gap fix) doesn't ship by Day 1:** Day 2-3 can still build B.1.5, PF5, runbook, but the reset on Day 3 will leave open positions vulnerable to any future operator halt re-freezing them. Risk: low if operator doesn't set halt during away period. Recommendation: ship E.4 anyway, document the gap, fix on operator return.
- **If E.2 (backtest) returns NO-GO:** Day 3 reset does NOT run. Bot stays in current halted state. Operator returns to halted bot. **This is the correct behavior** — better than 30 days of validated bleeding.
- **If E.3 (PF5) only ships 3-4 scenarios:** Day 3 reset runs anyway IF the most critical scenarios (PF5.6, PF5.7, PF5.8) passed. PF5.1/PF5.2/PF5.5 cover the in-trade failure modes; if some are skipped, document and finish post-departure (no operator-online dependency).
- **If E.5 (runbook validation) fails:** Day 3 reset does NOT run. The runbook IS the operator's safety harness; an untested harness is worse than no harness because it gives false confidence. Operator stays on-station an extra day or accepts a paused soak start.

---

## Dependencies and parallelism

```
Week 1: [A.0] -----------------> [A.1]
        [B.0] --> [B.0.5] -----> [B.1]

Week 2: [A.1] --> [A.2]
        [B.1] --> [B.2]

Week 3: [A.2] --> [A.3] -------> [A.4 (PF1-PF4)] --> [A.4 PF5 stress tests]
        [B.2] --> [B.3 (soak begins, runs 4 weeks)]

Week 4-7: [B.3 soak] --------------> Track C gate evaluation
          [A.4 stays green via PF1-PF5 weekly re-run]

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

- **2026-05-22 (session 4)** — Five-track ship: [0] D.2 box deploy +
  [1] A.1 IMPLEMENTATION (workstation) + [2] B.2 memo + [3] D.4 memo +
  [4] BTC/ETH ledger drift memo.

  **[0] D.2 watchdog box deploy — SHIPPED + smokes A-F green.**
  Operator approved `/var/run/docker.sock` mount at session start.
  `scripts/deploy_session4_d2_watchdog.py` atomic-swapped 4 files
  (`health/__init__.py`, `health/watchdog.py`,
  `deployment/Dockerfile.watchdog`, `deployment/docker-compose.yml`).
  Image `sha256:4a27584eb76f...` running.

  Smokes A-F deviated from the prompt's
  `WATCHDOG_CYCLE_INTERVAL_SEC=10` recipe (would have runaway-restarted
  paper-crypto whose actual cycle is 15 min). Safer protocol:
  (A) State.Status==running, (B) `_read_heartbeat_ts(/app/data/
  heartbeat.json)` returns float, (C) `docker ps` works via socket
  from inside the watchdog, (D) synthetic stale heartbeat + monkey-patched
  restart/alert → tick() returns `restart`, (E) `docker exec watchdog
  docker restart aaats-paper-crypto` returns paper-crypto to running
  within 20s, (F) 75s later `data/watchdog_heartbeat.json` shows
  `"last_decision": "ok"`. All green. 4-restart escalation path is
  unit-tested only (real-box loop deferred — needs ~45-min maintenance
  window).

  **Two bug fixes shipped to make D.2 actually work:**
    - `Dockerfile.watchdog`: Debian 13's `docker.io` package only
      ships the daemon (dockerd, docker-proxy); the CLI lives in a
      separate `docker-cli` package excluded by `--no-install-recommends`.
      Surfaced by smoke C (`exec: "docker": executable file not found
      in $PATH`). Fix: install `docker-cli` (libc6 dep only, ~30 MB).
      Commit `89d601e`.
    - `docker-compose.yml` data mount `:ro` → rw: the watchdog's
      `_emit_self_heartbeat` silently swallowed OSError on the read-only
      mount, so `data/watchdog_heartbeat.json` was never written.
      Defense-in-depth `:ro` was nominal (watchdog already has
      docker.sock write authority). aaats-paper-crypto's data mount is
      already rw. Commit `b947573`.

  Rollback baseline at
  `.rollback/2026-05-23_session4_d2_watchdog_box/MANIFEST.txt`.

  **[1] A.1 state-isolation — WORKSTATION-COMPLETE, operator-gated for
  box deploy.**
    - `risk/engine.py:44-66`: `_state_file_path()` helper with the
      memo's discriminator precedence (AAATS_RISK_STATE_FILE >
      mode+DIR > legacy). Module-level `STATE_FILE` preserved as a
      one-shot call at import time so existing
      `monkeypatch.setattr(..., "STATE_FILE", ...)` tests still work.
    - `tests/test_state_isolation.py`: 6/6 green (5 memo-listed +
      1 unknown-mode-fallback). The load-bearing
      test_paper_peak_survives_live_session validates that a write to
      live-mode does NOT clobber the paper-mode peak.
    - `deployment/docker-compose.yml`: per-mode named volumes
      (`state-crypto-paper`, `state-crypto-live`) +
      `AAATS_RISK_STATE_DIR=/app/data/state-${SYSTEM__TRADING_MODE:-paper}`.
      Legacy `state-crypto` volume RETAINED in the top-level `volumes:`
      block (no longer mounted) as rollback baseline.
    - `scripts/migrate_state_to_per_mode.sh`: idempotent one-time
      `cp -a` from `state-crypto` into `state-crypto-paper` plus
      filename rename `risk_engine_state.json` →
      `risk_engine_state.paper.json` so the per-mode discriminator
      finds the preserved peak.
    - Pytest **108/108 + 1 skipped** on touched + adjacent suites.
    - **Operator gate:** compose change requires sign-off per the
      autonomy contract (named-volume layout = "shared infrastructure"
      scope). Box deploy sequence documented in
      [`2026-05-22_state_isolation_design.md`](2026-05-22_state_isolation_design.md)
      §"Status log".

  **[2] B.2 paper-shadow validation memo — PROTOCOL LOCKED, re-eval
  2026-05-29.** Memo at
  [`docs/known_issues/2026-05-23_strategy_c3_post_b2.md`](../known_issues/2026-05-23_strategy_c3_post_b2.md).
  Only ~3 hours of post-deploy data; zero post-patch C3 trades so far
  (C3's pre-patch rate was ~5 trades/day; 3h is below noise floor).
  Baseline frozen, pass/fail criteria defined. Backtest harness is the
  fallback if 7-day shadow comes up underpowered.

  **[3] D.4 daily digest memo — SHIPPED.** Memo at
  [`docs/decisions/2026-05-23_daily_digest_design.md`](2026-05-23_daily_digest_design.md).
  Format LOCKED per Appendix A of the Track D addendum. Data sources
  mapped per field. **Dispatch decision:** inline in the aaats-watchdog
  poll loop (60s polling already, +1 time-of-day branch at 09:00 IST).
  Cleaner than cron-in-container or Windows Task Scheduler — watchdog
  already has Telegram credentials + data/ rw + a self-heartbeat for
  meta-observability. Implementation queue is ~1 Sonnet session.

  **[4] BTC/ETH ledger drift triage — SHIPPED.** Memo at
  [`docs/known_issues/2026-05-23_btc_eth_ledger_drift.md`](../known_issues/2026-05-23_btc_eth_ledger_drift.md).
  Two converging bugs:
    (a) Reconciler's Source-A loader expects flat
        `entry_price/size_usd` per symbol (C3's schema); C1_stat_arb
        writes pair-keyed `BTC/USDT_ETH/USDT → {shares_a/shares_b/
        entry_price_a/b}`. C1 positions are silently skipped.
    (b) Source-B SQL excludes `C5b_funding_arb` but NOT `C1_stat_arb`
        — both are delta-neutral arb. C1's pair legs are summed into
        Source B as if they were directional positions, exceeding the
        $0.25 dust filter (BTC $6.94, ETH $7.54).
  Three fix paths documented; **Option A** (one-line: add `C1_stat_arb`
  to Source B's exclusion SQL) is the recommended next-reconciler-touching-session
  patch. Real C1 drift detection requires Option C (unified ledger).
  Band-aid (`halt_on_critical=False`) stays until Option A lands.

  **Cross-cutting findings:**
    - C1's FIRST entry of the rebuild landed at 2026-05-22T15:41:18Z —
      the same day session 3 deployed `halt_on_critical=True`. The
      restart loop was the predictable consequence of two changes
      landing the same cycle. Going forward, any cross-strategy +
      reconciler change should be sequenced at least one cycle apart.
    - Deploy scripts that run on the Windows operator workstation MUST
      be ASCII-only — cp1252 cannot encode `✓`, `→`, `×`, `—`. Session
      4 burned two iterations on this.
    - Operator's GitHub connectivity was intermittent during the
      session; the end-of-session push is best-effort.

  **Operator pings this session:**
    - [0] docker.sock approval — ANSWERED (approved).
    - [1] A.1 compose-change review — PENDING (queued for end-of-session
      ask).

- **2026-05-23 (session 5)** — Three-track ship: [0] reconciler Option A
  + halt_on_critical=True re-enabled, [1] A.1 box deploy, [2] D.4 daily
  digest implementation + first live send.

  **[0] BTC/ETH ledger drift Option A — SHIPPED + verified clean.**
  `scripts/reconcile_intracycle.py:323` SQL exclusion extended from
  `strategy != 'C5b_funding_arb'` to `strategy NOT IN ('C5b_funding_arb',
  'C1_stat_arb')` — parity with the other delta-neutral arb. C1's
  pair-keyed `BTC/USDT_ETH/USDT` legs no longer surface as Source B net
  positions, removing the `symbol_present_in_only_one_source` HALT-per-cycle
  trigger that forced the session-3 band-aid. `trading/live_paper_runner.py:1881`
  flipped back to `halt_on_critical=True` (the doctrine-correct default).
  Test: `tests/test_reconciler_c1_exclusion.py` seeds a synthetic open
  C1 BUY-BTC/SELL-ETH pair in a tmp DB and asserts the reconciler passes
  with zero HALT issues. 3/3 + 2/2 existing `test_reconcile_denylist.py`
  green. Box verification (`c:/tmp/verify_session5_step0.py` at 05:25Z):
  `Reconciliation clean | checked=7 positions across crypto`, RestartCount=0,
  zero BTC/ETH HALT lines. Image `sha256:7a32d03ecfc9...`.
  Rollback at `.rollback/2026-05-23_session5_reconciler_c1_exclusion/MANIFEST.txt`.

  **[1] A.1 state isolation — SHIPPED, paper peak preserved.**
  Compose change + risk/engine.py + migrate script shipped via
  `scripts/deploy_session5_a1_state_isolation.py`. Per-mode volume layout
  active: `deployment_state-crypto-paper:/app/data/state-paper` (rw on
  paper-crypto), `deployment_state-crypto-live:/app/data/state-live`
  (created empty). Legacy `deployment_state-crypto` untouched as rollback
  baseline. Two field-discovered issues fixed mid-deploy:
    - Migrate script's CRLF line endings (Windows git autocrlf) broke
      `set -euo pipefail`. Re-uploaded LF-normalized; deploy scripts now
      normalize on every SFTP write.
    - Migrate script's default `SRC_VOL=state-crypto` was an empty
      bystander volume; the real legacy state lived in compose-prefixed
      `deployment_state-crypto`. Script patched to auto-detect the
      prefixed variant by probing for the `risk_engine_state.json` file.
  Verification: post-restart log line
  `Risk engine peak loaded from /app/data/state-paper/risk_engine_state.paper.json: $131.32`
  + `market peaks loaded ... crypto=$131.32`. State-crypto-paper now
  holds the real 148-byte risk_engine_state.paper.json. Rollback at
  `.rollback/2026-05-23_session5_a1_state_isolation/MANIFEST.txt`.

  **[2] D.4 daily digest — SHIPPED, first live send confirmed.**
  New module `monitoring/daily_digest.py` (pure builder + IO shell) with
  CLI dry-run (`python -m monitoring.daily_digest --dry-run`). Sections
  per the locked Appendix A format. cycle_log SQLite table added to
  `data/paper_trades.db`, written by `trading/live_paper_runner.py:1911-1934`
  next to the heartbeat write (idempotent CREATE + INSERT per cycle).
  Watchdog dispatch loop wired in `health/watchdog.py::_maybe_dispatch_digest`:
  fires once per IST calendar day at >= 09:00 IST, guarded by
  `data/digest_log.json` to prevent the 60s poll from re-firing.
  Tests at `tests/test_daily_digest.py`: 9/9 green (golden output,
  missing-state tolerance, action-needed trigger matrix, send-guard
  with archive write).
  Box deploy via `scripts/deploy_session5_d4_daily_digest.py`. Two
  field-discovered issues fixed:
    - `Dockerfile.watchdog` did not COPY `monitoring/`. Added it; rebuilt
      watchdog. Image `sha256:e948bedc5171...`.
    - The first live digest reported `Action needed: NONE` against the
      known -33% paper drawdown because the watchdog container could not
      read `/app/data/state-paper/risk_engine_state.paper.json` (the named
      volume was only mounted in paper-crypto, not in the watchdog).
      Compose patched to add `state-crypto-paper:/app/data/state-paper:ro`
      to the aaats-watchdog volumes. Today's `digest_log.json` entry
      cleared on the box and the watchdog re-tick re-fired the corrected
      digest. Operator now has both messages in Telegram; the second
      message (sent_at_utc 05:48:13Z) supersedes the first and correctly
      reports `Equity: $87.45 (peak $131.32, dd -33.4%) ... Action
      needed: drawdown -33.4% near kill threshold (-15%)`.
  Rollback at `.rollback/2026-05-23_session5_d4_daily_digest/MANIFEST.txt`.

  **[4] D.5 day-1 — infrastructure live, clock not yet started.**
  `data/digests/2026-05-23.txt` archive file written on the box (the
  corrected digest body, 577 bytes). `digest_log.json` records the
  send with `ist_date=2026-05-23, sent=true`. D.5 day-1 begins on the
  first day the digest fires with `Action needed: NONE`, which is gated
  on B.3 soak bringing the drawdown above -10%.

  **Cross-cutting findings:**
    - The C.7 profitability gate added today by Cowork (final-week B.3
      equity >= starting equity) does not change session 5 scope but
      raises the bar for live-flip authorization. See §"Track C - Flip
      gate" C.7.
    - Operator approval for the A.1 compose change came in pre-session as
      part of the session 5 prompt (Cowork ack 2026-05-23); the ask-first
      step was already retired.
    - Workstation cp1252 vs box utf-8 is a continuing tax on deploy
      scripts; every Bash output that includes box log lines now strips
      to ASCII before print.

  **Operator pings this session:** none required. The first-digest
  Action-needed=NONE issue self-resolved within ~6 minutes via the
  corrected re-send; no operator intervention solicited.

- **2026-05-23 (session 6)** — Kill-trigger investigation + alerts-log
  writer + deploy-smoke drift + D.6 lint sweep.

  **[0a] Kill-trigger investigation — CLOSED.** Verdict primarily **(d)**:
  the -15% market kill IS firing as a new-entry size gate (every cycle
  the engine fires HALT_MARKET, the runner short-circuits `execute()`
  before any order is placed). Open positions continue to bleed
  mark-to-market by design; this is the per-trade -2% stop's job, not
  the market-level kill. Secondary finding **(c) partial**: the three
  halt channels (`data/halt_state.json`, in-memory
  `RiskEngine._halted_markets`, `data/strategy_halt_state.json`) are
  intentionally NOT synchronized — `halt_state.json` is the operator/CLI
  channel only. The session-4 observation "`halt_state.json` shows
  crypto:false, therefore kill not firing" was the wrong inference.
  Full memo at
  [`docs/known_issues/2026-05-23_kill_trigger_investigation.md`](../known_issues/2026-05-23_kill_trigger_investigation.md).

  **[0b] Derivative fixes — SHIPPED to workstation.**
    - `trading/live_paper_runner.py:run_crypto` short-circuits on
      `foundation.kill_switch.is_halted("crypto")` at top of cycle (parity
      with `run_india`). This closes the operator-CLI kill asymmetry
      surfaced by the investigation.
    - `monitoring/daily_digest.py:compute_action_needed` distinguishes
      three drawdown bands: -10 to -15% "near", -15 to -20% "past
      market-kill (new entries blocked, open positions bleed)", ≤ -20%
      "past portfolio-kill (all new entries blocked, open positions
      bleed)". Replaces the misleading "near kill threshold" wording
      that fired at -33.4%.
    - `CLAUDE.md` gains a "Kill-switch semantics" subsection so future
      sessions don't re-litigate the verdict.
    - Tests: `tests/test_kill_trigger_paths.py` (5/5 green) covers
      engine HALT_MARKET at -16%, no-HALT at -14%, run_crypto
      short-circuit when halted, run_crypto proceeds when clear, and
      MARKET_DRAWDOWN_HALT constant locked at -0.15. Digest band tests
      added to `tests/test_daily_digest.py`.
    - **NOT deployed to box this session.** The change is reversible
      and operator-CLI-channel only; bundled with the next session-7
      deploy when other queued items also need a rebuild.

  **[2] Alerts-log writer + deploy-smoke drift — SHIPPED to workstation.**
    - `observability/alerts.py::send_alert` now appends one row per call
      to `data/alerts_log.json` (atomic .tmp+replace, severity inferred
      from message body when not explicit, UUID4 correlation_id
      auto-generated). KeyboardInterrupt passes through cleanly so the
      operator can still Ctrl+C the bot.
    - `monitoring/daily_digest.py` reads `alerts_log.json`, computes
      fired/open/resolved over the 24h window, flips `alerts_known=True`
      when the file is present, and adds a new Action-needed trigger:
      `alerts_open >= 3` fires the action line.
    - `tools/operator/_digest_smoke.py` is the deploy-smoke helper that
      runs `python -m monitoring.daily_digest --dry-run` inside the
      target container, parses the Equity line, and asserts it is NOT
      N/A when the on-disk state file exists. Catches the session-5
      volume-mount drift at build time. Tests:
      `tests/test_alerts_log.py` (11/11), `tests/test_operator/test_digest_smoke.py`
      (9/9), digest alerts-log tests added to `tests/test_daily_digest.py`.

  **[3] D.6 lint sweep + row 7 + row 22 — SHIPPED to workstation.**
    - `tools/lint/silent_except.py` is an AST walker that flags
      `except <T>: pass` (silent-except) and loguru `%s/%d` placeholders
      (loguru-printf). 273 baseline hits (80 silent-except + 188
      loguru-printf after annotating doctrine-correct paths in
      foundation/kill_switch.py and observability/alerts.py with
      `# noqa: silent-except`).
    - `tools/lint/silent_except_baseline.txt` locks the current counts;
      `tests/test_lint_silent_except.py` fails the suite if either rule's
      count INCREASES (cleanup downward is encouraged with a print
      reminder to update the baseline).
    - `tests/test_lint_logic.py` (10/10) covers the AST checks
      themselves against synthetic tmp_path fixtures.
    - **Row 7 (metrics-exporter target-down):** `monitoring/metrics_exporter.py`
      gains `collect_self_up()` emitting `aaats_metrics_exporter_up=1`
      from the scrape loop, complementing Prometheus's `up{job=...}`
      target gauge with in-band liveness.
    - **Row 22 (dead-code SELL-share recompute resurrection risk):**
      `tests/test_dead_code_guard.py` asserts
      `execution/crypto_runner.py` + `execution/india_runner.py` remain
      deleted, and that no new code introduces
      `round(size_usd / entry_price, 6)` on a SELL path. 2/2 green.

  **[4] D.5 day-1 — NOT TRIGGERED.** Today's digest fired with action
  needed != NONE (paper drawdown -33.4% → past market-kill band per the
  new wording). Day-1 clock remains parked until B.3 soak brings the
  drawdown above -10%.

  **Cross-cutting findings:**
    - C1_stat_arb standalone (`trading/stat_arb.py:478`) still
      bypasses `apply_kill_switch_gate` (deferred to B.2 per B.1
      triage). At -33% drawdown the bot would happily open new C1
      positions IF the strategy's entry-z fires. Currently latent
      because C1 is honestly skipping on z=-0.116.
    - Pre-existing 6-test-failure baseline (xgboost confidence
      thresholds + consensus voting + dual_ledger_drift bounds + Angel
      One credentials) is unrelated to this session's surfaces;
      confirmed by stash-and-rerun before commit. Filed for a later
      session that owns those modules.
    - Workstation-local; no box deploy. Compose + rebuild will roll up
      run_crypto kill-switch parity + digest wording + alerts-log
      writer in session 7's first deploy.

  **Operator pings this session:** none required.

- **2026-05-24 (session 7)** — Coordinated session-6 box deploy + C1
  kill-gate wire + lint chip-away (B.2 skipped, ineligible until 2026-05-29).

  **[0] Session-6 bundled deploy — SHIPPED + smoke green.**
  `scripts/deploy_session7_kill_alerts_lint.py` rolled 9 files (3 image-baked
  changes to paper-crypto + 1 to metrics + 1 to watchdog, plus 4 workstation-side
  helpers) onto the box in one paramiko atomic-swap pass. Post-rebuild image SHAs
  captured at `.rollback/2026-05-24_session7_kill_alerts_lint/MANIFEST.txt`:
  paper-crypto `4905e304…`, metrics `25f222ac…`, watchdog `d0ad9ab1…`.
  Smoke gates: digest dry-run inside aaats-watchdog renders
  `Equity: $87.45  (peak $131.32, dd -33.4%)`; new band wording fires
  `Action needed: drawdown -33.4% past portfolio-kill threshold (-20%); all new
  entries blocked, open positions continue to mark-to-market`;
  `aaats_metrics_exporter_up=1.000000` on `:9091/metrics`.

  **Surfaced finding — operator-channel halt was being silently ignored
  pre-deploy.** Box `data/halt_state.json` shows
  `{us:true, india:true, crypto:true}` set at 2026-05-22 17:41 UTC (~13 hours
  before deploy). Pre-deploy `run_crypto` ignored this entirely and kept
  trading (digest showed `C1_stat_arb (10 trades)` over 24h). Post-deploy the
  session-6 `is_halted("crypto")` gate fires correctly and the runner short-
  circuits with `Crypto market HALTED (kill switch) — skipping cycle`. **Operator
  decision:** keep crypto halted; -33.4% drawdown is past the portfolio-kill
  threshold and a halt is defensible. Reset path documented for future sessions:
  `python kill.py --reset crypto` on the box, but the engine-level -15% kill
  will continue to gate new entries until paper-crypto recovers above -15%.

  **Semantic gap surfaced (session 8 item):** the runner-wide short-circuit
  on `is_halted("crypto")` ALSO stops mark-to-market and exit logic for
  open positions, broader than the engine-level kill's documented "block new
  entries, keep MTM" semantics. The C3 standalone gate at
  `altcoin_reversion.py:598` blocks SELL emissions too, so currently
  positions are stuck open during operator halt. Worth a session-8 review:
  either (a) move the runner short-circuit BELOW exit/MTM code so open
  positions still bleed correctly, or (b) accept current semantics as
  intentional and document it in `CLAUDE.md` "Kill-switch semantics".

  **[1] B.2 — SKIPPED (eligibility 2026-05-29).** Today is 2026-05-23; the
  B.2 evaluation window begins 2026-05-29 per
  `docs/known_issues/2026-05-23_strategy_c3_post_b2.md`. Reordered per prompt
  fallback: [2], [3].

  **[2] C1 stat_arb standalone kill-gate — SHIPPED.**
  `run_stat_arb_crypto` and `_run_pair` now accept
  `full_positions` / `full_portfolio` kwargs and resolve
  `trading.live_paper_runner.apply_kill_switch_gate` once per cycle, parity
  with C3 / C6. Gate is consulted before BUY emission at the entry block
  and before SELL emission at CONVERGE / HARD_STOP / TIME_STOP exit paths.
  Call site in `trading/live_paper_runner.py` updated to pass the runner-wide
  state dicts. Tests at `tests/test_stat_arb_kill_gate.py` (4/4 green) cover:
  signature accepts new kwargs (pre-patch raised TypeError); gate-tripped
  blocks entry at -33% drawdown even when |z|>entry_z; gate-open allows
  entry (proves the fixture isn't silently failing); back-compat path
  (kwargs omitted) bypasses the gate cleanly. **The latent bug surfaced at
  end of session 6** ("C1 would happily open new positions IF the entry-z
  fires") is now closed.

  **[3] D.6 lint chip-away — SHIPPED.**
  `execution/paper_executor.py` lines 126/144/150/217/268/276/294 converted
  from `log.X("...%s...", args)` to f-string form (7 hits removed).
  `execution/idempotency.py` lines 179/191/200 silent-except handlers gain
  `log.debug(...)` bodies that record the OperationalError message
  (3 hits removed; new module-level logger added). My own session-7
  stat_arb.py edits also converted to f-strings (-3 hits I would have
  added). Net: silent-except 80 → 77, loguru-printf 188 → 181 (10 fewer).
  Baseline at `tools/lint/silent_except_baseline.txt` ratcheted downward;
  ratchet CI gate at `tests/test_lint_silent_except.py` green.

  **[4] D.5 day-1 — STILL PARKED.** Today's box digest fired with
  `Action needed: drawdown -33.4% past portfolio-kill threshold (-20%)`.
  Day-1 clock remains parked until equity recovers and a NONE digest
  fires.

  **Cross-cutting findings:**
    - Pre-existing test failure `tests/test_dual_ledger_drift.py
      ::test_dual_ledger_drift_bounded[runtime]` — confirmed via
      git-stash that it fails BEFORE session-7 edits; caused by box
      auto-cron snapshots in `runtime/`, unrelated to the C1 kill-gate
      or lint work. Triage owner: a later session that owns the
      runtime/ ledger writer.
    - Lint rule observation: many `loguru-printf` hits in stdlib-logging
      modules (e.g. `paper_executor.py` uses `logging.getLogger`, not
      loguru) are false positives — `%s` is correct stdlib usage there.
      Conversion to f-strings is doctrine-neutral (works for both) but
      eagerly formats. If future cleanup chips a hot debug path, prefer
      `# noqa: loguru-printf` over f-string conversion for stdlib code.
    - Lint baseline file lives under `tools/lint/silent_except_baseline.txt`;
      always ratchet downward after a cleanup batch and re-run
      `tests/test_lint_silent_except.py` to lock the new floor.

  **Operator pings this session:** one — clarification on the operator
  halt_state divergence surfaced in [0]. Resolved with operator's
  "best recommendation" preference; keep-halted chosen.

- **2026-05-23 (session 8)** — Operator-halt MTM gap resolution +
  alerts-log smoke confirmation + lint chip-away. B.2 still ineligible
  (< 2026-05-29). D.5 day-1 still parked (action != NONE).

  **[0a] Open-position verification — ZERO open positions.** Box query
  against `paper_trades.db` with `status='open' OR quantity != 0` returned
  0 rows. State files `risk_engine_state.paper.json`,
  `portfolio_state.paper.json`, `equity_curve.json` are MISSING from
  `/app/data/` (filed as ancillary; secondary to [0] and didn't gate it).
  `halt_state.json` mtime confirms session-7 finding: set
  2026-05-22T15:41:25Z, ~16h pre-deploy. Branch logic: -33.4% is realized
  loss, no stale MTM exposure, [0c] forced-MTM is NOT needed. Recovery
  clock starts cleanly when operator clears halt.

  **[0] Operator-halt MTM gap — SHIPPED (workstation; pending box deploy
  this session).** Adopted option (a) from the session-8 prompt: split
  the per-emission kill gate into ENTRY and EXIT variants so the
  operator halt blocks new entries without freezing open positions or
  per-trade stops. Layout:
    - New private helper `_mark_to_market_and_decide()` in
      [trading/live_paper_runner.py](trading/live_paper_runner.py) drives
      `engine.update_portfolio` + `engine.update_market` once per
      emission and returns the more severe of the two decisions
      (HALT_ALL > HALT_MARKET > ALLOW). Fixes a latent bug where
      `update_market`'s decision was returned even when
      `update_portfolio` had already set `_all_halted=True` — on a fresh
      engine the freshly-seeded market peak gave ALLOW.
    - `apply_kill_switch_gate` (ENTRY) now consults
      `foundation.kill_switch.is_halted(market)` BEFORE the engine
      decision. Blocks BUY emission on operator halt + HALT_ALL +
      HALT_MARKET.
    - New `apply_kill_switch_exit_gate` (EXIT) only blocks on
      catastrophic HALT_ALL. HALT_MARKET and operator halt allow the
      SELL through so positions can bleed via ATR / per-trade /
      converge.
    - `execute()` routes BUY through the entry gate and SELL through
      the exit gate. HOLD signals still MTM the engine so the
      existing-position branch (per-trade -2% stop check) operates
      against fresh peak/drawdown state.
    - `run_crypto` + `run_india` no longer short-circuit on
      `is_halted`. They log the halt once and proceed — `_check_trailing_stops`,
      MTM, exit signals, and standalone-strategy exits all fire.
    - C3 [`trading/altcoin_reversion.py`](trading/altcoin_reversion.py)
      and C6 [`trading/bollinger_range.py`](trading/bollinger_range.py)
      import the new exit-gate alias `_exit_gate_check` and use it on
      the SELL branch. C1 [`trading/stat_arb.py`](trading/stat_arb.py)
      `_run_pair` accepts a new `exit_gate_check` kwarg propagated by
      `run_stat_arb_crypto`.
    - Coverage: 12 new tests in
      [tests/test_operator_halt_mtm_gap.py](tests/test_operator_halt_mtm_gap.py)
      (entry-gate / exit-gate / execute() routing / runner reaches
      trailing-stops / C3-C6-C1 import wire-ups). Session-7 C1 kill-gate
      tests still 4/4 green.
    - Existing [tests/test_kill_trigger_paths.py](tests/test_kill_trigger_paths.py)
      `test_run_crypto_short_circuits_when_halted` updated to
      `test_run_crypto_reaches_binance_probe_even_when_halted` — old
      assertion captured the pre-fix bug, new assertion captures the
      desired post-fix invariant.
    - Documented in
      [docs/known_issues/2026-05-23_kill_trigger_investigation.md](docs/known_issues/2026-05-23_kill_trigger_investigation.md)
      via inline doctrings on the new helpers; CLAUDE.md "Kill-switch
      semantics" section already reflects the engine-vs-operator split
      and remains accurate.

  **[3] Alerts-log smoke — CONFIRMED FIRING.** Sent
  `send_alert('TEST session 8 smoke 2026-05-23', market='crypto')`
  inside `aaats-paper-crypto`. `/home/aaats/aaats/data/alerts_log.json`
  was newly created (188 bytes) with one row containing the timestamp,
  market, severity inference (`info`), message, and UUID4
  correlation_id. Session-7's lazy-creation contract holds: the writer
  fires on first `send_alert` call rather than at runner init. Daily
  digest's "Alerts fired" row will populate on the next watchdog tick
  that runs after a real (non-test) alert lands.

  **[2] Lint chip-away — SHIPPED.** Six silent-except hits closed; new
  baseline `silent-except: 71` (was 77, -6 net). Loguru-printf
  unchanged at 181 — `[2b]` rule refinement deferred.
    - `execution/paper_trader.py:94, 106, 111` — sqlite3.OperationalError
      handlers (column-already-exists / index-already-exists / view-rebuild)
      now `log.debug` the exception text rather than silently passing.
    - `execution/status_db.py:50` — same pattern for the
      engine_status migration loop. Added module-level logger
      (`get_logger("execution", "status_db")`); the module had been
      logger-less.
    - `foundation/mode_manager.py:128` — LIVE-activation Telegram
      alert failure now `log.warning`s rather than silently swallowing,
      with the explicit caveat that the mode switch itself still
      committed (the alert is best-effort).
    - `diagnostics/d2_ml_dist.py:116` — per-bar `score_signal`
      exception now `print`s the symbol + bar index instead of
      silently dropping the row.
    - `tools/lint/silent_except_baseline.txt` ratcheted 77 → 71;
      `tests/test_lint_silent_except.py` green at the new floor.

  **[2b] Loguru-only scoping — DEFERRED.** Triage holds: most
  `loguru-printf` hits are doctrine-neutral and chipping by hand reaches
  hot paths without needing rule narrowing. Save for a Haiku-grade
  session when the chip-away queue runs lean.

  **[4] D.5 day-1 — STILL PARKED.** Crypto remains under operator halt,
  drawdown -33.4%. Action-needed band continues to fire. Day-1 clock
  resumes only after the halt clears AND drawdown recovers above the
  -10% session-7 band wording threshold.

  **Cross-cutting findings:**
    - `_mark_to_market_and_decide` more-severe-of-two precedence is a
      net behavior change beyond the operator-halt fix. The session-7
      gate would have under-reported HALT_ALL on the first cycle after
      a restart when `update_market` had not yet been called for the
      market. Worth a watchdog look if any unexpected HALT_ALL alerts
      land in the next 7 days — they may have been silently masked
      before this session.
    - On-disk state file absences (`risk_engine_state.paper.json`,
      `portfolio_state.paper.json`, `equity_curve.json`) in
      `/app/data/` are surprising given runner had been alive for 16h
      pre-deploy. Possibly the persistence path moved to
      `data/state/risk_engine_state.json` (which DOES exist on box per
      session-7 doctrine; the paper-suffixed path
      `state/risk_engine_state.paper.json` is what the new isolated
      mode would write). Filed as follow-up for session 9 — does NOT
      gate the operator-halt fix.
    - Operator parallel-edit observed: untracked files
      `docs/decisions/2026-05-23_doctrine_amendment_200_floor.md` and
      `docs/runbooks/2026-05-23_operator_away_protocol.md` and an
      unstaged edit to this very plan adding the PF5 subsection
      appeared during my session. Treated as out-of-band operator
      work; my commit does NOT include them.

  **Operator pings this session:** none required. The MTM-gap fix was
  the documented option (a) recommendation from the prompt; no
  divergence from the design recommendation, no surprises.

- **2026-05-23 (session 9)** — Session-8 code SHIPPED to box; B.1.5
  backtest harness BUILT and RUN; result **PARTIAL**.

  **[0] Session-8 box deploy — SHIPPED.** Built
  [scripts/deploy_session8_operator_halt_gap.py](scripts/deploy_session8_operator_halt_gap.py),
  shipped 9 files (`trading/live_paper_runner.py`, `trading/altcoin_reversion.py`,
  `trading/bollinger_range.py`, `trading/stat_arb.py`, `execution/paper_trader.py`,
  `execution/status_db.py`, `foundation/mode_manager.py`,
  `diagnostics/d2_ml_dist.py`, `tools/lint/silent_except_baseline.txt`).
  Image rebuilt to `sha256:064483a2bfaa…` (was `4905e304…`).
  Smoke A (new OPERATOR HALT wording: green), B (`apply_kill_switch_exit_gate`
  import: green), C (digest dry-run Equity line non-N/A: green) all passed
  on first run.

  **[0.5] HOTFIX state_bridge.py — REQUIRED ON DETECTION.** Smoke D
  (strategy `_exit_gate_check` imports) failed and runner log showed
  `ImportError: cannot import name 'state_bridge' from 'foundation'`.
  Root cause: commit 464bf7e (2026-05-21) added
  `foundation/state_bridge.py` and `foundation/positions.py` for the
  unified positions ledger (USE_UNIFIED_LEDGER flag); both files were
  NEVER SCP'd to the box. Sessions 7 and 8 didn't touch them and the
  strategy files on the box were the OLD versions without the import.
  Session-9's deploy of the NEW strategy files (which import
  `state_bridge`) exposed the gap. Hotfix via
  [c:/tmp/hotfix_state_bridge.py](c:/tmp/hotfix_state_bridge.py) SCP'd
  both files and rebuilt `aaats-paper-crypto` to image `sha256:1d3a7ffadd38…`.
  Post-hotfix logs show C3 evaluating ADA/USDT and the new exit gate
  correctly blocking the SELL on HALT_ALL (contract behaving exactly as
  designed: HALT_ALL blocks exits, HALT_MARKET / operator halt allow
  them through). Smoke D's symbol-presence check was bogus
  (`_exit_gate_check` is a function-local binding, not a module-level
  export); the runtime evidence (clean import in cycle logs, gate
  blocking ADA) is what matters and it is green. Rollback at
  `.rollback/2026-05-24_session9_hotfix_state_bridge/MANIFEST.txt`.

  **[0b] State file investigation — read-only probe done.** All of
  `/app/data/risk_engine_state.paper.json`, `portfolio_state.paper.json`,
  `equity_curve.json`, `/app/data/state/risk_engine_state.json`, and the
  state/-prefixed paper variants are ABSENT inside `aaats-paper-crypto`.
  The `/app/data/state/` directory itself does not exist. Runner is
  re-deriving portfolio state every cycle from `paper_trades.db` — works
  but no persistence. Filed at
  [docs/known_issues/2026-05-23_state_persistence_paths_missing.md](../known_issues/2026-05-23_state_persistence_paths_missing.md).
  Session 11 reset will wipe `state-crypto-paper` volume regardless, so
  no further action this session. Post-reset re-investigation hooks
  documented in the issue.

  **[1] B.1.5 backtest harness — BUILT and RUN. Recommendation:
  PARTIAL.** New [tools/backtest/](tools/backtest/) package: `__init__.py`,
  `historical_data.py` (ccxt Binance OHLCV fetcher with parquet cache at
  `data/historical/`), `c3_replay.py` (bar-by-bar replay engine reusing
  C3's PURE helpers — `_compute_z_score`, `_rsi`, `_realized_daily_vol`,
  `_compute_trade_size` — with a reimplemented entry/exit driver that
  steps through historical bars deterministically), `run_b15_c3.py`
  (orchestrator + recommendation logic).
  - Headline 60d run (`SOL/LINK/AVAX/DOT` vs `BTC` on 1h Binance bars,
    1440 aligned bars, starting capital $100, zero slippage):
    **86 trades, +$5.43 P&L, Sharpe 1.52, 47.7% win rate.**
  - 50bps slippage sensitivity: **-$5.72** (P&L flips sign; the strategy
    edge is razor-thin and disappears under realistic transaction costs).
    THIS is the criterion that demotes from GO to PARTIAL.
  - Three regime windows (BTC realized vol low/mid/high):
    `low_vol = +$2.53` (24h, 65% WR, Sharpe 2.72),
    `mid_vol = -$0.36` (38t, 45% WR, Sharpe -0.45),
    `high_vol = +$3.33` (27t, 41% WR, Sharpe 2.27).
    **Profitable regimes: 2 of 3.**
  - LIMITATIONS encoded in the `evidence` field of the JSON output:
    replay disables BEAR regime gate (HMM not in replay) and BTC.D
    fast-rise filter — both make replay PERMISSIVE (allows entries
    production would skip). Result is therefore an upper bound.
  - Tests: [tests/test_b15_backtest_harness.py](tests/test_b15_backtest_harness.py)
    — 12/12 pass (synthetic dip-recover → fires + profitable SOL trade;
    synthetic flat → zero trades + NO-GO; recommendation threshold rules
    parametrized over 9 boundary cases + harness-failed short-circuit).
  - JSON summary at
    [data/backtest_results/c3_60d_summary.json](data/backtest_results/c3_60d_summary.json).

  **Recommendation GATE for session 11 reset: PARTIAL.** Per the
  session-9 hard-coded rule table, PARTIAL means pnl_usd > 0 (yes:
  +$5.43) but at least one secondary criterion failed (here: 50bps
  slippage flips P&L negative). The reset is NOT BLOCKED by NO-GO;
  the operator should proceed with the session-11 reset but tighten
  slippage assumptions in the post-reset C3 monitoring. Specifically:
  if live C3 P&L over the first week of soak diverges from the
  +0% line by >$2 in either direction, that's a signal the live
  slippage is bigger than the harness modeled and the strategy
  should re-halt for re-tuning.

  **[2] Operator halt status — UNCHANGED.** `data/halt_state.json` at
  `{us:true, india:true, crypto:true}` since 2026-05-22 15:41 UTC. Not
  cleared this session per the prompt's "no autonomous reset". Session
  11 reset script will handle halt clearing as part of the reset flow.

  **[3] PF5 stress-test scaffolding — DEFERRED to session 10.** Time
  budget consumed by the hotfix and the backtest run. PF5.6 (D.1 auto-
  halt monkeypatch) and PF5.5 (slippage) move to session 10's queue per
  the prompt's "if session 9 doesn't reach [3], session 10 picks it up".

  **[4]/[5]/[6] — All correctly skipped per prompt.** [4] B.2 eligibility
  opens 2026-05-29; [5] lint chip-away skipped (no slack after backtest);
  [6] D.5 day-1 still parked behind operator halt + drawdown band.

  **Cross-cutting findings:**
    - The state_bridge gap (above) is a CLASS of bug worth a doctrine
      note: when shipping a strategy file that imports a new foundation
      module, the foundation module must be in the same SCP manifest.
      The dirty-tree guard catches uncommitted-file deploys but not
      this case (the new module IS committed locally; it just wasn't
      shipped). Session 10 may want to add a "module import graph"
      guard to `tools/operator/_dirty_tree_guard.py` that walks the
      file manifest's imports and asserts every imported local module
      is either (a) in the manifest or (b) already present on the box.
    - The 50bps-slippage P&L flip on C3 is consistent with the strategy's
      own post-mortem (2026-05-21 strategy diagnostic): C3's edge is
      thin and depends on Binance's tight spreads continuing. If the
      operator-away window sees a Binance maintenance event or a stress
      day with widened spreads, C3 will underperform the backtest.

  **Operator ping this session (REQUIRED per prompt):**

    > B.1.5 backtest result: **PARTIAL**. 60d C3 replay against live
    > Binance OHLCV produced +$5.43 P&L (Sharpe 1.52, 47.7% WR,
    > 86 trades, 2/3 profitable regimes). 50bps slippage demotes to
    > -$5.72 — strategy edge is razor-thin under realistic costs and
    > that is what demotes from GO to PARTIAL. PARTIAL allows the
    > session-11 reset to proceed per the hard-coded threshold rule;
    > the operator-away soak begins on schedule. Recommend tightening
    > slippage assumptions in post-reset monitoring (re-halt C3 if
    > live P&L diverges from $0 line by >$2 in either direction over
    > the first soak week, since divergence is the slippage-bigger-
    > than-expected signal).

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
