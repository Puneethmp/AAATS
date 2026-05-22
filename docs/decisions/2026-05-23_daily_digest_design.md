# Phase D.4 — Daily digest implementation memo

**Status:** DESIGN MEMO, no code this session. Implementation lands in a future Claude Code session per the rebuild plan's Track D.
**Authored:** 2026-05-22 (session 4).
**Closes:** Sub-task [3] of session-4 prompt.
**Parent plan:** [`2026-05-21_track_d_reliability_addendum.md`](2026-05-21_track_d_reliability_addendum.md) §"Phase D.4" + Appendix A (format LOCKED).
**Cross-refs:**
- `state/schemas.py` — D.3 pydantic schemas; the digest reads these as authoritative.
- `data/strategy_exception_state.json` + `data/strategy_halt_state.json` — D.1 counters.
- `data/watchdog_heartbeat.json` — D.2 self-heartbeat (restart counter, last decision).

## Problem statement

Track D's premise is that the bot must be checkable from one daily Telegram
message. The format is locked (Appendix A of the addendum). What's missing
is the implementation surface: **which writer produces each field, which
schedule fires the send, and what does the dry-run look like.**

This memo answers those three questions and frees session 5+ to implement
without re-litigating sources.

## Data sources per field

The digest format (verbatim from Appendix A) annotated with sources. All
JSON files are read via the D.3 `state.schemas.load_validated` helper so a
schema-drift breaks the digest loud rather than silent.

```
🤖 AAATS daily digest — YYYY-MM-DD (T+N since rebuild)
```

- **YYYY-MM-DD**: `datetime.now(timezone(timedelta(hours=5, minutes=30)))`
  in **IST** (the operator's TZ). The digest fires at 09:00 IST, so the
  "today" date string reflects the operator's calendar day.
- **T+N**: days since `2026-05-12` (the rebuild anchor — first session of
  the 48h sprint that became the multi-week rebuild). Hard-coded constant;
  bump only if the rebuild scope explicitly resets.

### Section 1 — P&L (24h)

```
📊 P&L (24h)
  Realized:   $±X.XX
  Unrealized: $±X.XX
  Equity:     $XXX.XX  (peak $XXX.XX, dd −X.X%)
```

| Field | Source | Query / read |
|---|---|---|
| Realized | `data/paper_trades.db` table `paper_trades` | `SELECT ROUND(SUM(pnl),2) FROM paper_trades WHERE action='SELL' AND timestamp >= datetime('now','-24 hours')` |
| Unrealized | computed from open BUYs in `paper_trades.db` + current market price | For each open BUY (`action='BUY'` with no matching SELL by `correlation_id` or `client_order_id`), fetch current price; sum `(current - entry_price) * shares` |
| Equity | `data/state/risk_engine_state.paper.json` (post-A.1) or `risk_engine_state.json` (pre-A.1, legacy fallback) | Read `last_equity` |
| Peak | same file | Read `peak` |
| Drawdown | derived | `(last_equity - peak) / peak * 100` |

**Unrealized P&L gotcha:** until the unified-ledger sprint closes, the
`paper_positions.json` ledger and the `paper_trades.db` ledger may
disagree (the 2026-05-15 reconciler diagnosis). The digest MUST source
from the trades DB (which is the authoritative immutable record), NOT
from `paper_positions.json`. Document the chosen source in the memo so
session 5+ doesn't pick the wrong one.

**Live mode reading:** when `SYSTEM__TRADING_MODE=live`, the digest reads
`risk_engine_state.live.json` (A.1 isolation). The digest itself reads
the env var to pick the right file; alternatively, it reads both and
emits two digests labeled `[PAPER]` / `[LIVE]`. **Recommendation:** one
digest per mode-active container; do not bundle. Cleaner alert routing.

### Section 2 — Operational

```
⚙️  Operational
  Cycles run:        N (expected N, X.X% uptime)
  Exceptions:        N  (Y auto-halted)
  Container restarts: N  (auto: A, manual: M)
  Alerts fired:      N  (open: X, resolved: Y)
```

| Field | Source | Read |
|---|---|---|
| Cycles run | `paper_trades.db` (proxy) OR a new `cycle_log` table | Count distinct cycle IDs in last 24h. **Gap:** no canonical cycle counter table today; the runner writes a heartbeat per cycle but only the latest is retained. Either (a) tail container logs for "cycle N complete" lines, (b) add a `cycle_log` table written per cycle, or (c) read the runner's `risk_engine_state.last_update_ts` history (also single-row, won't work). **Recommended:** add a tiny `cycle_log` table in session 5 implementation — `(timestamp, cycle, market)` — written from `live_paper_runner.py:1908` next to the heartbeat write. Idempotent and cheap. |
| Expected | constant: `96` for a 15-min cycle interval × 24h | `int(86400 / CYCLE_INTERVAL_SEC)` |
| Uptime % | derived | `cycles_run / expected * 100` |
| Exceptions | `data/strategy_exception_state.json` (D.1) | Sum `total_exceptions` across strategies. The schema is `{strategy: {total_exceptions, consecutive_exceptions, last_exception_ts}}`. Delta from 24h ago needs a "yesterday's value" stash → see below for the persistence pattern. |
| Auto-halted | `data/strategy_halt_state.json` (D.1) | Count strategies with `halted=True` and `halted_at >= 24h ago` |
| Container restarts | `docker inspect aaats-paper-crypto --format '{{.RestartCount}}'` | Delta from yesterday's RestartCount. **Auto vs manual:** the watchdog increments its own `restart_history` in `data/watchdog_heartbeat.json::restart_count_in_window` — diff = (RestartCount delta) - (watchdog restart_count delta). Anything left is operator-initiated. |
| Alerts fired | new `data/alerts_log.json` | **Gap:** `observability.alerts.send_alert` does NOT log its sends today; it just fires and forgets. Session 5+ should add an append-only log line per send + a resolution field for the operator to mark resolved (or auto-resolve on a follow-up "RESOLVED" alert). For the first digest implementation, this row can be omitted (or shown as "N/A") until the alerts log lands. |

### Section 3 — Strategies (24h)

```
📈 Strategies (24h)
  Firing:   Cn (X trades), Cm (Y trades), Co (Z trades)
  Silent:   Cp, Cq, Cr   (reason: ...)
  Halted:   Cs (since YYYY-MM-DD, reason)
```

| Field | Source | Read |
|---|---|---|
| Firing | `paper_trades.db` | `SELECT strategy, COUNT(*) FROM paper_trades WHERE timestamp >= datetime('now','-24 hours') GROUP BY strategy ORDER BY 2 DESC LIMIT 3` |
| Silent | doctrine universe ∖ firing | Universe constant in `config/doctrine.py` or similar. Reason for silence per strategy: `(C5b: halted), (N1-N7: container is --market crypto)`. Sourced from the locked B.1 triage table in the parent plan. |
| Halted | `data/strategy_halt_state.json` | For each `halted=True` row: emit `(strategy, halted_at date, reason)` |

### Section 4 — Action needed

```
⚠️  Action needed: NONE | <one-line summary>
```

Computed AFTER all other sections. Set to a non-NONE string when ANY of:
- `dd <= -10%` (approaching kill threshold, operator should look)
- `alerts_open >= 3` (alert backlog)
- `consecutive_exceptions >= 2` for any strategy not yet halted (D.1
  halts at 3; warn at 2)
- A container restart in the last 24h that the watchdog DID NOT account
  for (i.e., a manual or daemon-policy restart that wasn't deliberate)
- `share_equality_mismatches.json` non-empty (per memo
  `docs/known_issues/2026-05-22_share_equality_alert_chain.md`)

Otherwise `NONE` → operator can ignore the message.

**The locked invariant:** 30 consecutive days of `Action needed: NONE`
is the D.5 soak's pass criterion. Tightening or loosening the trigger
list above is a D.4-implementation decision; widening it CANNOT raise
the false-positive rate or the 30-day clock will never reach 30.

## Schedule: cron vs scheduled-task vs in-container loop

Three candidates surfaced; one recommended.

| Option | Where | Setup | Failure mode |
|---|---|---|---|
| (a) `cron` inside aaats-watchdog | adds a crond layer to the slim image, daily `09:00 IST` | needs cron daemon + crontab + Tini | cron silent failure is the classic dropper; we'd lose digests without noticing |
| (b) Windows Task Scheduler on operator workstation | scheduled task fires `python scripts/run_daily_digest.py --remote` against the Tailscale SSH | operator-side, can edit | breaks if laptop is closed or VPN drops |
| (c) **dedicated Python loop in aaats-watchdog** | watchdog poll loop adds a "time-since-last-digest >= 24h" check, fires inline | one extra branch in `health/watchdog.py::main` | observable: watchdog's own self-heartbeat already proves it's alive; digest skips show up as "no digest yesterday" |

**Recommended: (c).** The watchdog already has Telegram credentials,
`data/` rw access (per session-4 D.2 deploy), and a 60-second poll loop.
Daily-digest dispatch is one if-branch:

```python
# pseudo: inside Watchdog.main loop, alongside the existing tick() call
ist_now = datetime.now(IST)
if ist_now.hour == 9 and not _digest_sent_today():
    from monitoring.daily_digest import build_and_send_digest
    build_and_send_digest()
    _mark_digest_sent(ist_now.date())
```

The "sent today" guard uses `data/digest_log.json` (one line per send,
written atomically). The 60-second poll means the first poll after
09:00:00 IST sends; subsequent polls that day no-op.

Trade-off rejected: separate `aaats-digest` container. Cleaner isolation
but adds compose surgery, image build, +50 MB of Python runtime, and an
extra Docker socket consumer the operator must trust. The watchdog
already paid that cost.

## Dry-run plan

Order of validation before going live:

1. **Module dry-run (workstation):**
   ```
   venv\Scripts\python -m monitoring.daily_digest --dry-run --as-of 2026-05-22
   ```
   Reads the workstation's `runtime/*.json` (or a `--data-dir` override),
   prints the digest to stdout. NO Telegram send.

2. **Golden-output test:** `tests/test_daily_digest.py` writes a fixed
   set of state files into `tmp_path/data/`, invokes the digest builder,
   asserts the exact output string (modulo timestamp). Locks the format.

3. **Box dry-run:**
   ```
   docker exec aaats-watchdog python -m monitoring.daily_digest --dry-run
   ```
   Reads the box's `/app/data/` state. NO Telegram send. Operator
   inspects the output.

4. **First live send:** flip `--dry-run` off in the watchdog's
   `build_and_send_digest()` call. Operator confirms receipt on Telegram.
   Watchdog logs `[digest] sent YYYY-MM-DD` to its own stdout for audit.

5. **Day-2 verification:** the next day's `digest_log.json` shows two
   sends; the second message references "T+N+1" since the rebuild anchor.

6. **D.5 soak begins** the first day the digest fires cleanly with
   `Action needed: NONE`.

## Telegram destination

Same chat as alerts: env var `ALERTS__TELEGRAM_CHAT_ID` (per
`observability/alerts.py:31-37`). No new chat needed.

Message tag: `[SYSTEM]` (the existing convention from
`observability/alerts.py:42`). The digest body itself starts with the
robot emoji per Appendix A so the operator sees the daily header even if
they swipe past the `[SYSTEM]` tag.

Rate limiting: one message per day per mode. `_digest_sent_today()`
guard prevents duplicates on watchdog restart (digest_log.json is
persistent in `data/`).

## What is NOT in this memo

- The unified-ledger sprint work that fixes the `paper_positions.json`
  vs `paper_trades.db` drift. The digest reads from `paper_trades.db`
  exclusively to side-step that drift. Once the unified ledger lands,
  the digest can be re-pointed if a better source emerges.
- A live-mode digest. A.1 isolation makes a separate live digest natural
  (one container per mode), but the implementation can ship paper-only
  first and add live in the same session that activates A.2's DRY_RUN
  broker.
- Anomaly detection (e.g., "P&L dropped 3σ overnight"). The Action-needed
  triggers are threshold-based; anomaly detection is a D.6+ topic.

## Implementation queue (session 5 candidate)

1. New module `monitoring/daily_digest.py` with `build_digest(data_dir,
   as_of) -> str` (pure function) + `build_and_send_digest()` (IO).
2. New `data/digest_log.json` writer + reader.
3. `health/watchdog.py::main` loop: time-of-day check + dispatch.
4. New table `cycle_log(timestamp, cycle, market)` in
   `data/paper_trades.db` with a writer call in
   `trading/live_paper_runner.py` next to the heartbeat write.
5. Tests at `tests/test_daily_digest.py`: golden-output, missing-state
   tolerance, `Action needed` trigger matrix.

**Estimate:** 1 Sonnet session for the digest module + tests + watchdog
loop wiring. The new `cycle_log` table is a 5-line addition; the rest is
SQL aggregations and string formatting.

## Status log

- **2026-05-22 (session 4)** — Memo authored. NO code edits. Format
  locked in Appendix A of the Track D addendum; data sources mapped;
  dispatch via the existing aaats-watchdog poll loop selected over cron
  / Task Scheduler / separate container. Implementation queued for
  session 5.
