# Weekly Report — week 24

> Window: 2026-06-04T12:32:05.705343+00:00 -> 2026-06-11T08:58:08.953424+00:00 | events: 115
> All PnL NET of fees + slippage (+ funding for perps). Gross-only is never reported.

## PnL vs no-trade baseline

| Measure | Value |
|---|---:|
| Net PnL (all strategies) | -5.2003 |
| Gross PnL (reference only) | -0.8557 |
| No-trade baseline | +0.0000 |
| **Gap vs no-trade** | **-5.2003** |
| Beats no-trade? | NO |
| Cost ratio (costs / winners' gross) | 3.55 |

## Per-strategy (net of costs)

| Strategy | n | gross | fees | slippage | funding | net | beats no-trade |
|---|---:|---:|---:|---:|---:|---:|:--:|
| C3_altcoin_reversion | 43 | -2.079 | 0.752 | 0.752 | 0.000 | -3.583 | NO |
| C6_bollinger_range | 72 | +1.223 | 1.420 | 1.420 | 0.000 | -1.617 | NO |

## Loss-bucket distribution

| Bucket | n | net |
|---|---:|---:|
| SIGNAL | 51 | -9.0252 |
| RISK | 7 | -5.1757 |
| COST | 12 | -0.4498 |
| WIN | 45 | +9.4502 |

## Recurring failure-pattern flags (-> monthly hypothesis cycle)

- 60% of losing exits are `hard_stop` (35/58)
- most losses concentrated in C6_bollinger_range (37)

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
rows_total=3810  rows_last_7d=3810  newest=2026-06-11T11:07:01+00:00
distinct collection hours last 7d: 127 (expect ~168; gaps if fewer)
db_size_bytes=565248
disk /home: used 25G of 72G (35%)
```

## Health anomalies (last 7 days)
```
paper-crypto: health=healthy restarts=0 started=2026-06-10T17:12:35.82342962Z
heartbeat-checker alerts (non-OK lines, last 7d):
[2026-05-24T09:55:02Z] suppressed (cooldown 40s < 3600s): auto-cron heartbeat stale 121min (>1200s threshold) — cron daemon may be dead
t3-watchdog alerts (non-OK lines):
```

_Generated 2026-06-11T11:55:40Z by aaats-weekly-report.sh (cron, Mondays 06:10Z)._
