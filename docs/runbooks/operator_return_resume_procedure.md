# Operator return — D.5 soak resumption procedure

**Authored:** 2026-05-24 (content-correctness sprint, operator-departure prep)
**Effective:** First operator session after 30-day D.5 soak (~2026-06-24)
**Companion to:** [`2026-05-23_operator_away_protocol.md`](2026-05-23_operator_away_protocol.md)

This is the PHASE 0 checklist for the first claude-code session when the
operator is back on the workstation. It extends `next_session_prompt.md`
with explicit verification of the L5-L10 content-correctness layers
shipped 2026-05-24.

The protocol is intentionally CONSERVATIVE. The default is "audit first,
reset later." Do not skip steps even if the dashboard looks clean.

---

## Step 0 — Reachability (5 min)

```bash
ssh aaats@100.95.126.39 'hostname; date -u; uptime'
```

Tailscale must respond. If it doesn't, follow [`box_unreachable_via_tailscale.md`](box_unreachable_via_tailscale.md)
BEFORE anything else.

## Step 1 — Triage from the Telegram channel (10 min)

Open the AAATS Telegram chat (chat ID `1946109268`). Scan ALL messages
from the soak window in REVERSE-CHRONOLOGICAL order looking for:

| Alert prefix | Layer | Meaning | Action |
|---|---|---|---|
| `AAATS CRON:` (cron-alert.sh) | L2/L3 | autopush failed or heartbeat stale | check git log on origin/main first |
| `AAATS LIVENESS ALERT:` | L1 | no auto-cron commit for >30min | confirm with `git log origin/main` |
| `AAATS ACTIVITY FLOOR:` | L7 | crypto silent >48h | check ML gate, regime detector |
| `Market drawdown WARN (-10%)` | L8 | crypto crossed -10% sometime | informational, may already have recovered |
| `Market drawdown CRITICAL (-15%)` | L8 | crypto crossed -15% sometime | check whether -2% per-trade stops unwound positions |
| `Market drawdown PAGE (-20%)` | L8 | L9 fired auto-halt | **do NOT remote-reset; full audit below** |
| `L9 AUTO-HALT FIRED` | L9 | log-side mirror of the page alert | same |
| `L10/DISK:` | L10 | /home >85% full | check `df`, consider log rotation |
| `L10/REPO:` | L10 | .git grew >500MB/24h | likely auto-cron committed large blob; investigate before git gc |
| `L10/COMMIT_RATE:` | L10 | <80 auto-cron commits/24h | autopush ticking but producing empty commits (probably benign) |

A clean soak shows only the daily digest. Any L8-CRITICAL or L8-PAGE or
L9 message means **the audit path below is REQUIRED** before resuming.

## Step 2 — Box-side diagnose snapshot (5 min)

```bash
ssh aaats@100.95.126.39 'bash /home/aaats/bin/aaats-diagnose.sh --quick'
```

Capture the output verbatim. The script reports container health,
heartbeat freshness, recent trade activity, halt states, and the L1-L10
layer status.

## Step 3 — L5 ledger divergence sanity (5 min)

```bash
ssh aaats@100.95.126.39 'docker exec aaats-paper-crypto python -c "
from execution.paper_trader import compute_ledger_divergence
d = compute_ledger_divergence()
print(\"divergence:\", d)
"'
```

Expected: `{}` (empty). Any entry means a strategy's state-file open
notional disagrees with the trade-DB-derived open notional by > $0.50.
The strategy will have been halted via `risk.strategy_halt`. Inspect
`data/ledger_divergence_alerts.json` for the timing and delta.

## Step 4 — L9 doctrine-halt audit (15 min — ONLY if L9 fired)

If Telegram showed any "L9 AUTO-HALT FIRED" message during the soak:

1. **Do NOT reset the halt remotely.** The Telegram message intentionally
   does not include the reset command.

2. Pull the full audit trail:

   ```bash
   ssh aaats@100.95.126.39 'cat /home/aaats/aaats/data/halt_state.json'
   ssh aaats@100.95.126.39 'docker exec aaats-paper-crypto python -c "
   import sqlite3, json
   c = sqlite3.connect(\"/app/data/paper_trades.db\")
   for r in c.execute(\"SELECT timestamp, market, symbol, action, shares, price, pnl, strategy FROM paper_trades ORDER BY timestamp DESC LIMIT 50\").fetchall():
       print(r)
   "'
   ```

3. Manually compute the equity trajectory: starting equity $200 minus
   sum of realized PnL plus mark-to-market of open positions. Confirm
   the L9 halt fired at the threshold (-20%) and not earlier or later.

4. Inspect `data/state-paper/risk_engine_state.paper.json` for the peak
   the L9 check used. Verify it matches expected.

5. Only after the audit shows clean accounting:

   ```bash
   python kill.py reset crypto  # from operator workstation
   ```

   The reset goes through the operator halt channel (data/halt_state.json),
   which is the same channel L9 writes to. The runner will pick up the
   reset on its next cycle top.

## Step 5 — L7 activity floor backfill check (5 min)

If Telegram showed any "AAATS ACTIVITY FLOOR" message:

1. Cross-check with paper_trades.db: was there a trade burst right after
   the alert, or did silence continue?

2. Inspect ML gate accuracy via Grafana panel "ML val acc 7d". If
   accuracy degraded into <50% range, retrain may have shipped a bad
   model. Inspect `data/ml/meta.json` for the retrain timestamp and
   the new val_acc; compare against the alert timing.

## Step 6 — L8 drawdown reconciliation (5 min)

```bash
curl -s http://aaats-metrics:9091/metrics | grep aaats_market_dd_pct
```

(Or use Grafana directly.) Confirm the live DD readings agree with the
Telegram alerts that fired. If the DD shows 0% but L8-CRITICAL fired,
that means the position recovered between then and now — verify with
the trade log.

## Step 7 — Resume decision

Default: resume the soak unmodified for another window, or shift to D.6
live-paper if the soak hit its 30-day mark cleanly.

Resume requires:
- L9 not fired (or fired but audit-clean, halt reset manually)
- L7 silent OR cause identified and fixed
- L5 divergence empty
- L8 all DDs above -15%
- L10 disk OK, repo size OK

If ANY of the above failed, file a `docs/decisions/<date>_soak_outcome.md`
documenting the failure mode before any further runner changes.

## Step 8 — Update auto-memory

Save the soak outcome to memory so future sessions don't have to re-read
30 days of Telegram. One entry summarizing:
- Soak start/end timestamps
- Final equity vs $200 seed
- Number of L8 alerts fired (warn/crit/page)
- L9 fired? If yes, root cause from the audit
- Any L5/L7/L10 alerts fired

Format follows the `project_aaats_*` memory pattern.
