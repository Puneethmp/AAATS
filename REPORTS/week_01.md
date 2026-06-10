# Weekly Report — week 01

> Window: 2026-05-23T20:53:21.481916+00:00 -> 2026-06-09T14:17:16.137938+00:00 | events: 271
> All PnL NET of fees + slippage (+ funding for perps). Gross-only is never reported.

## PnL vs no-trade baseline

| Measure | Value |
|---|---:|
| Net PnL (all strategies) | -13.0066 |
| Gross PnL (reference only) | -2.2672 |
| No-trade baseline | +0.0000 |
| **Gap vs no-trade** | **-13.0066** |
| Beats no-trade? | NO |
| Cost ratio (costs / winners' gross) | 16.39 |

## Per-strategy (net of costs)

| Strategy | n | gross | fees | slippage | funding | net | beats no-trade |
|---|---:|---:|---:|---:|---:|---:|:--:|
| C3_altcoin_reversion | 94 | -2.923 | 1.794 | 1.794 | 0.000 | -6.510 | NO |
| C6_bollinger_range | 161 | +0.479 | 3.158 | 3.158 | 0.000 | -5.838 | NO |
| C1_stat_arb | 16 | +0.176 | 0.418 | 0.418 | 0.000 | -0.659 | NO |

## Loss-bucket distribution

| Bucket | n | net |
|---|---:|---:|
| SIGNAL | 121 | -20.8279 |
| RISK | 15 | -9.2299 |
| COST | 27 | -1.0622 |
| WIN | 108 | +18.1134 |

## Recurring failure-pattern flags (-> monthly hypothesis cycle)

- 57% of losing exits are `hard_stop` (78/136)
- most losses concentrated in C6_bollinger_range (85)

## Verdict

Does NOT beat the no-trade baseline. Per the program rule, a flat week beats a losing week — strategies failing to clear $0 net are candidates for demotion.
