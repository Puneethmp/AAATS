# Weekly Report — week 25

> Window: 2026-06-08T11:17:12.965190+00:00 -> 2026-06-11T08:58:08.953424+00:00 | events: 41
> All PnL NET of fees + slippage (+ funding for perps). Gross-only is never reported.

## PnL vs no-trade baseline

| Measure | Value |
|---|---:|
| Net PnL (all strategies) | -1.0328 |
| Gross PnL (reference only) | +0.4250 |
| No-trade baseline | +0.0000 |
| **Gap vs no-trade** | **-1.0328** |
| Beats no-trade? | NO |
| Cost ratio (costs / winners' gross) | 1.21 |

## Per-strategy (net of costs)

| Strategy | n | gross | fees | slippage | funding | net | beats no-trade |
|---|---:|---:|---:|---:|---:|---:|:--:|
| C6_bollinger_range | 27 | -0.779 | 0.548 | 0.548 | 0.000 | -1.875 | NO |
| C3_altcoin_reversion | 14 | +1.204 | 0.181 | 0.181 | 0.000 | +0.842 | YES |

## Loss-bucket distribution

| Bucket | n | net |
|---|---:|---:|
| SIGNAL | 24 | -4.0962 |
| COST | 3 | -0.0974 |
| WIN | 14 | +3.1605 |

## Recurring failure-pattern flags (-> monthly hypothesis cycle)

- 67% of losing exits are `hard_stop` (16/24)
- most losses concentrated in C6_bollinger_range (17)

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
rows_total=6480  rows_last_7d=5190  newest=2026-06-15T04:07:01+00:00
distinct collection hours last 7d: 173 (expect ~168; gaps if fewer)
db_size_bytes=962560
disk /home: used 24G of 72G (33%)
```

## Health anomalies (last 7 days)
```
paper-crypto: health=healthy restarts=0 started=2026-06-10T17:12:35.82342962Z
heartbeat-checker alerts (non-OK lines, last 7d):
[2026-05-24T09:55:02Z] suppressed (cooldown 40s < 3600s): auto-cron heartbeat stale 121min (>1200s threshold) — cron daemon may be dead
t3-watchdog alerts (non-OK lines):
```

_Generated 2026-06-15T04:10:04Z by aaats-weekly-report.sh (cron, Mondays 06:10Z)._
