# Weekly Report — week 28

> Window: 2026-06-29T05:53:33.092790+00:00 -> 2026-07-04T20:31:25.966902+00:00 | events: 74
> All PnL NET of fees + slippage (+ funding for perps). Gross-only is never reported.

## PnL vs no-trade baseline

| Measure | Value |
|---|---:|
| Net PnL (all strategies) | -6.4245 |
| Gross PnL (reference only) | -3.8487 |
| No-trade baseline | +0.0000 |
| **Gap vs no-trade** | **-6.4245** |
| Beats no-trade? | NO |
| Cost ratio (costs / winners' gross) | n/a |

## Per-strategy (net of costs)

| Strategy | n | gross | fees | slippage | funding | net | beats no-trade |
|---|---:|---:|---:|---:|---:|---:|:--:|
| C6_bollinger_range | 38 | -2.292 | 0.665 | 0.665 | 0.000 | -3.622 | NO |
| C3_altcoin_reversion | 36 | -1.557 | 0.623 | 0.623 | 0.000 | -2.803 | NO |

## Loss-bucket distribution

| Bucket | n | net |
|---|---:|---:|
| SIGNAL | 37 | -5.0469 |
| RISK | 9 | -4.5186 |
| COST | 4 | -0.1098 |
| WIN | 24 | +3.2506 |

## Recurring failure-pattern flags (-> monthly hypothesis cycle)

- 37% of losing exits are `hard_stop` (17/46)
- most losses concentrated in C6_bollinger_range (26)

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
rows_total=21600  rows_last_7d=5190  newest=2026-07-06T04:07:01+00:00
distinct collection hours last 7d: 173 (expect ~168; gaps if fewer)
db_size_bytes=3211264
disk /home: used 23G of 72G (33%)
```

## Health anomalies (last 7 days)
```
paper-crypto: health=healthy restarts=0 started=2026-07-04T05:45:36.056448043Z
heartbeat-checker alerts (non-OK lines, last 7d):
[2026-05-24T09:55:02Z] suppressed (cooldown 40s < 3600s): auto-cron heartbeat stale 121min (>1200s threshold) — cron daemon may be dead
t3-watchdog alerts (non-OK lines):
```

_Generated 2026-07-06T04:10:03Z by aaats-weekly-report.sh (cron, Mondays 06:10Z)._
