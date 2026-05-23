# Operator-away protocol (autonomous 30-day paper soak)

**Authored:** 2026-05-23 (Cowork session)
**Effective:** 2026-05-25 (operator departure) through operator return
**Purpose:** Pre-authorize routine bot decisions so the D.5 30-day no-intervention paper soak can run while the operator is unreachable. This is the single doc the operator reads before leaving and the bot's decision tree while they're gone.

## TL;DR (read this if nothing else)

By the time the operator leaves (2026-05-25):

1. The B.1.5 backtest harness has been built and run against C3/C6 on 30-60 days historical Binance data.
2. The backtest outcome dictates GO/NO-GO on the soak (see "Backtest-gated GO/NO-GO" below).
3. If GO: paper book is reset to $200, D.5 30-day soak begins. Bot runs autonomously per pre-auth matrix below.
4. If NO-GO: bot is left HALTED. Telegram alert sent. Operator returns to a halted bot, not a bleeding one.

The bot will not flip to live during this period under ANY circumstances. C.1–C.7 gates remain in force. The 30-day soak is paper-only.

## Backtest-gated GO/NO-GO (the critical Day-3 decision)

The B.1.5 backtest harness output is the ONLY input to the GO/NO-GO call. No subjective judgment, no operator override needed mid-flight — the rule is hard-coded into the reset script.

| Backtest result on C3 (60-day historical) | Action |
|---|---|
| P&L > 0 AND Sharpe > 0.5 AND profitable in 2 of 3 regime windows AND still profitable at 0.5% synthetic slippage | **FULL GO**: reset to $200, start soak with full strategy stack (C1 + C3 + C6 active). |
| P&L > 0 but fails any of the above sub-criteria | **PARTIAL GO**: reset to $200, start soak with full stack (C1+C3+C6) BUT divergence-watcher armed for days 1-7 (cuts C3 if pnl exits [-$2,+$2]). Per Cowork D2 (2026-05-23), the prior "PARTIAL -> HALT C3 preemptively" rule is OVERRIDDEN — the backtest edge is too valuable to preemptively discard, and the watcher gives a fast trip-wire if live behavior diverges from the replay. |
| P&L < 0 OR backtest harness fails to produce a result | **NO-GO**: do NOT reset, do NOT start soak. Bot stays in current halted state. Telegram pager-level alert to operator. Operator returns to a frozen-but-not-bleeding bot. |

The reset script `scripts/reset_paper_book_200.py` reads the backtest result file `data/backtest_results/c3_60d_summary.json` and refuses to run if the result is NO-GO. If the file is absent, the reset script refuses to run (fail-safe default).

## Pre-auth decision matrix (what the bot decides without operator)

The autonomy contract reserves money/risk/doctrine/broker/mode/strategy-additions for the operator. While away, the operator pre-authorizes these specific cases:

| Event | Pre-authorized action | Why |
|---|---|---|
| B.2 evaluation eligibility hit (2026-05-29) | Run the B.2 measurement queries automatically. If P1/P2/P3 all green → proceed to B.3 setup. If any of F1/F2/F3 fire → HALT C3 + Telegram alert + leave bot running on C1/C6. | Per `docs/known_issues/2026-05-23_strategy_c3_post_b2.md` decision protocol. Operator-decision-free because the criteria are binary. |
| Single strategy hits 3 consec exceptions (D.1 auto-halt fires) | Leave strategy halted. Telegram alert. Other strategies continue. | D.1 isolation is the existing mitigation. No human decision needed; halting one strategy isn't catastrophic. |
| C3 divergence-watcher fires (days 1-7, C3 P&L outside [-$2, +$2] since day-1) | C3 auto-HALT via `strategy_halt_state.json`. Telegram pager-level alert ([PAGER] prefix, severity=critical). C1 + C6 continue trading. Watcher deactivates after day 7. | Per Cowork D3 (2026-05-23). PARTIAL backtest verdicts run the full stack with this watcher as the first-week trip-wire — a fast, automatic divergence cut-off rather than preemptively halting C3 for the whole soak. |
| Container restart by D.2 watchdog (single occurrence within 4h window) | No action. This is normal recovery. Log only. | Watchdog handles in <60s. Routine. |
| Container restart by D.2 watchdog (5+ in one calendar day) | HALT_ALL via `kill.py` CLI auto-invocation. Telegram pager-level alert. | Repeated restarts = something structural is broken. Stop trading until operator investigates. |
| Engine HALT_MARKET fires (-15% market drawdown) | No action. Engine handles via new-entry gate. Open positions continue to MTM. Daily digest reflects. | Per "Kill-switch semantics" in CLAUDE.md, this is by design. |
| Engine HALT_ALL fires (-20% portfolio drawdown) | Telegram pager-level alert. Bot continues to MTM but blocks all new entries. | Existential. Operator must investigate even if remotely. |
| Drawdown beyond -40% from peak | Auto-invoke `kill.py halt --all`. Telegram pager-level alert. **This is a tripwire — bot stops everything.** | -40% means -20% portfolio kill itself failed, OR open positions bled through it. Cannot continue without human inspection. |
| Share-equality divergence detected (any) | Standard alert chain (Telegram via Grafana). No pager escalation unless > $1.00. | Existing chain validated 2026-05-16. |
| Share-equality divergence > $1.00 | Telegram pager-level alert. Bot continues trading; this is data-side, not trading-side. | Likely reconciler / ledger drift. Need operator eyes; doesn't require stop. |
| 3+ consecutive daily digests with `Action needed != NONE` | Telegram pager-level alert. Bot continues. | Sustained problem state means autonomous recovery isn't working. |
| New strategy emerges (e.g. C2 starts firing for first time) | HALT the new strategy via `strategy_halt_state.json` write. Telegram alert. | Doctrine: strategy additions are operator-only. A newly-firing strategy = additions decision. Halt until operator review. |
| Doctrine-amendment-level decision required | Bot does NOT make. Telegram pager-level alert. Bot continues in current state. | E.g., "should we change the -20% kill to -25%?" is doctrine. Never autonomous. |

## Pager-level Telegram triggers (these wake the operator)

Pager messages route to Telegram chat `1946109268` (operator's primary chat per `CLAUDE.md`). Format: `[PAGER] <subsystem>: <one-line-summary>. Action taken: <auto-action-or-none>. Read full status at <link or path>.`

Pager triggers (the complete list — anything not on this list is NOT pager-level, just normal Telegram alert):

1. **Drawdown beyond -40% from peak.** Tripwire fires, bot fully halted.
2. **Container down > 30 min** (watchdog gave up retrying, OR aaats-metrics also down so we can't observe).
3. **HALT_ALL kill switch fired** (-20% portfolio kill).
4. **Share-equality divergence > $1.00.**
5. **3+ consecutive digests with `Action needed != NONE`.**
6. **B.2 evaluation F1/F2/F3 fired** (informational pager — bot has auto-HALTed C3 per pre-auth; operator should be aware).
7. **New strategy firing for first time** (informational; bot has auto-HALTed it per pre-auth).
8. **Doctrine-level decision required** (any condition not covered by pre-auth matrix).

If the operator has Telegram on phone, these will buzz. If the operator is fully offline, the bot will still take the pre-authorized action and the pager messages will queue in Telegram for whenever the operator opens it.

## What the operator does each day (if accessing remotely)

Optional but recommended if you have any access:

1. **Read the daily digest.** Delivered 09:00 IST to Telegram chat `1946109268`. Format defined in `docs/decisions/2026-05-21_track_d_reliability_addendum.md` Appendix A. Look for: `Action needed`, `Halted strategies`, `Drawdown`, `Alerts fired`.
2. **Action needed = NONE** for 3+ digests in a row = soak is going well. Soak counter increments.
3. **Action needed != NONE** for any single day = note it, but don't intervene unless pager fires. Most issues self-resolve within a day.
4. **No action ever required** unless a pager fires.

## What the operator does if a pager fires (remote access scenarios)

| Access level | Pager response |
|---|---|
| Telegram on phone + laptop available | SSH to box, read `data/alerts_log.json` + container logs, decide. |
| Telegram on phone only | Reply to pager Telegram with `/kill-all` to force HALT, or `/resume` to clear an over-cautious auto-halt. (Telegram CLI bot to be wired Day 2.) |
| Fully offline | Bot has already taken pre-authorized action. Whatever the pager says, the bot has done it. Operator reviews on return. |

## What the operator does NOT do (this is critical)

- **Never live-flip during the away period.** C.1–C.7 gates remain in force. Even if the soak goes spectacularly well and the operator is tempted to flip $25 live remotely, the doctrine forbids it without the full Track C evaluation, which requires operator-on-station read of B.3 + D.5 + C.7 outputs.
- **Never override the backtest-gated GO/NO-GO Day 3 decision from remote.** If the backtest says NO-GO, the bot stays halted. No remote override. The operator must be physically back to re-evaluate.
- **Never escalate the live tranche size during away period.** G1 stays $25 even after operator returns. Tranche escalation requires C.7 + operator decision.

## Departure checklist (operator runs before leaving 2026-05-25)

In order:

1. **Verify session 8 [0] shipped.** Check that the operator-halt MTM gap fix is deployed (run a `docker exec aaats-paper-crypto python -c "from trading.live_paper_runner import run_crypto; print(run_crypto.__code__.co_consts)"` or similar; confirm MTM-above-halt-check ordering).
2. **Verify backtest result file exists and reports GO or NO-GO.** Read `data/backtest_results/c3_60d_summary.json`. If GO, proceed. If NO-GO, do NOT run reset; bot stays in current halted state and operator confirms-bye via Telegram.
3. **Run the reset script.** `python scripts/reset_paper_book_200.py --confirm` (script refuses without the flag).
4. **Verify first NONE-NONE digest fires within 24h of reset.** This is the D.5 day-1 trigger. Watch Telegram.
5. **Verify Telegram pager chain works.** Send a synthetic pager via `python -c "from observability.alerts import send_alert; send_alert('[PAGER-TEST] Operator-away protocol active', level='pager')"`. Confirm received on phone.
6. **Verify PF5 stress tests passed.** Read `tests/preflight/test_pf5_*.py` output; all 8 scenarios green.
7. **Final commit + push.** Per `feedback_github_push_every_session` standing rule. Reset script and runbook live on origin/main.
8. **Acknowledge bye in Telegram chat:** "Operator AFK, expected return ~YYYY-MM-DD. Pre-auth matrix per docs/runbooks/2026-05-23_operator_away_protocol.md is active. Bot, you have the conn."

## Return checklist (operator runs on return)

In order:

1. **Read every queued Telegram pager message.** Each one explains what happened and what auto-action was taken.
2. **Read every daily digest sent during away period.** Look for `Action needed != NONE` streaks.
3. **Read `data/alerts_log.json`.** Full timeline of every alert fired during the period.
4. **Check soak counter.** If D.5 reached day-30 with all NONE-NONE digests, C.6 is satisfied. If interrupted, restart day-1 counter.
5. **If B.2 fired during away period:** read its result, validate the auto-action (auto-HALT or auto-proceed) was correct.
6. **If B.3 4-week soak started during away period:** check whether final-vs-start equity passes C.7. If yes, ready for Track C evaluation. If no, re-triage per C.7's failure-branch logic.
7. **Decide on live flip per C.1–C.7.** Operator-on-station decision; no remote authority.

## What happens if the operator never returns

Worst-case: bot continues running autonomously. Eventually one of these:

- D.5 30-day soak completes successfully → bot continues paper trading indefinitely on the validated stack, generating daily digests, never auto-flipping live. Safe steady-state.
- Drawdown tripwire fires → bot halts itself, sends pager, sits idle. Safe steady-state.
- Container fails permanently → watchdog can't recover → silence in digests. After ~48h of digest silence, the box's cron monitor (TBD addition) would page. Pre-existing aaats-base monitoring not currently configured for this; could be added Day 2 as PF5.9.

**The bot will never lose more than $40 of paper money** during the away period (-20% portfolio kill from $200 = $40 max realized loss after the portfolio-kill MTM-on-open positions floor stops further loss). Real money is not at risk in any scenario; this is paper.

## Cross-references

- `docs/decisions/2026-05-23_doctrine_amendment_200_floor.md` — the $200 amendment this runbook enables.
- `docs/decisions/2026-05-22_live_flip_rebuild_plan.md` — Track C gates (C.1–C.7) that this runbook respects.
- `docs/decisions/2026-05-22_b15_backtest_harness.md` — B.1.5 design; the harness output is the GO/NO-GO input.
- `docs/decisions/2026-05-21_autonomy_contract.md` — original autonomy contract that this runbook pre-authorizes specific cases of.
- `docs/decisions/2026-05-21_track_d_reliability_addendum.md` — D.1–D.5 reliability infrastructure that this runbook depends on.
- `docs/known_issues/2026-05-23_strategy_c3_post_b2.md` — B.2 P1/P2/P3 + F1/F2/F3 criteria that the pre-auth matrix references.
- `CLAUDE.md` "Kill-switch semantics" — three-channel halt model.

## Caveats and open items

1. **Telegram CLI bot for remote `/kill-all` / `/resume`** is not yet built. If the operator needs phone-only kill control, that's a Day 2 add. Currently the only kill path is SSH-to-box + `python -m kill --all`.
2. **PF5.9 box-silence monitor** is not in the v1 PF5 scope. If the box itself goes dark (not just a container, the whole box), the operator wouldn't be paged unless an external monitor (UptimeRobot, etc.) is configured. This is operator-decision; not blocking the soak start.
3. **The 30-day soak runs in parallel with the B.3 4-week soak.** D.5 measures reliability (zero `Action needed`); B.3 measures profitability (final equity ≥ start). They can both pass, both fail, or split. C.6 and C.7 are evaluated separately.
4. **B.1.5 backtest harness is the bottleneck.** If Day 2 fails to produce a backtest result, Day 3 reset cannot proceed (per fail-safe rule). The operator must extend timeline or abort.

## Last word

This runbook exists to prevent the operator from feeling forced to make decisions on a phone in an airport. Every decision the bot might face during the away period either:

- Has a pre-authorized action defined above, or
- Pages the operator, or
- Halts the bot and waits.

There is no fourth option. If a situation arises that isn't covered, the bot defaults to halt-and-page. This is conservative by design — the cost of an unnecessary halt is "missed paper trading days." The cost of an autonomous decision in an unanticipated situation is "the soak result is no longer trustworthy."
