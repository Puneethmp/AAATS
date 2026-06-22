# Weekly Report — week 26

> Window: None -> None | events: 0
> All PnL NET of fees + slippage (+ funding for perps). Gross-only is never reported.

## PnL vs no-trade baseline

| Measure | Value |
|---|---:|
| Net PnL (all strategies) | +0.0000 |
| Gross PnL (reference only) | +0.0000 |
| No-trade baseline | +0.0000 |
| **Gap vs no-trade** | **+0.0000** |
| Beats no-trade? | NO |
| Cost ratio (costs / winners' gross) | n/a |

## Per-strategy (net of costs)

| Strategy | n | gross | fees | slippage | funding | net | beats no-trade |
|---|---:|---:|---:|---:|---:|---:|:--:|

## Loss-bucket distribution

| Bucket | n | net |
|---|---:|---:|

## Recurring failure-pattern flags (-> monthly hypothesis cycle)

- (none crossed the 25% threshold this window)

## Verdict

Does NOT beat the no-trade baseline. Per the program rule, a flat week beats a losing week — strategies failing to clear $0 net are candidates for demotion.

## Open book (maintenance contract: should be EMPTY)
```
altcoin_reversion_state: {}
bollinger_range_state: {}
stat_arb_state: {}
```

## OI collector health (T3 — the only live research thread, usable ~2027)
```
rows_total=11520  rows_last_7d=5190  newest=2026-06-22T04:07:01+00:00
distinct collection hours last 7d: 173 (expect ~168; gaps if fewer)
db_size_bytes=1736704
disk /home: used 24G of 72G (33%)
```

## Health anomalies (last 7 days)
```
paper-crypto: health=healthy restarts=0 started=2026-06-10T17:12:35.82342962Z
heartbeat-checker alerts (non-OK lines, last 7d):
[2026-05-24T09:55:02Z] suppressed (cooldown 40s < 3600s): auto-cron heartbeat stale 121min (>1200s threshold) — cron daemon may be dead
t3-watchdog alerts (non-OK lines):
```

_Generated 2026-06-22T04:10:02Z by aaats-weekly-report.sh (cron, Mondays 06:10Z)._
