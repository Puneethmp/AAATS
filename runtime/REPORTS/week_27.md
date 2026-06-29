# Weekly Report — week 27

> Window: 2026-06-27T07:53:26.458970+00:00 -> 2026-06-29T02:53:35.794646+00:00 | events: 31
> All PnL NET of fees + slippage (+ funding for perps). Gross-only is never reported.

## PnL vs no-trade baseline

| Measure | Value |
|---|---:|
| Net PnL (all strategies) | -3.2648 |
| Gross PnL (reference only) | -2.1225 |
| No-trade baseline | +0.0000 |
| **Gap vs no-trade** | **-3.2648** |
| Beats no-trade? | NO |
| Cost ratio (costs / winners' gross) | n/a |

## Per-strategy (net of costs)

| Strategy | n | gross | fees | slippage | funding | net | beats no-trade |
|---|---:|---:|---:|---:|---:|---:|:--:|
| C6_bollinger_range | 23 | -1.439 | 0.462 | 0.462 | 0.000 | -2.362 | NO |
| C3_altcoin_reversion | 8 | -0.684 | 0.109 | 0.109 | 0.000 | -0.902 | NO |

## Loss-bucket distribution

| Bucket | n | net |
|---|---:|---:|
| SIGNAL | 20 | -3.6492 |
| RISK | 2 | -1.1362 |
| WIN | 9 | +1.5204 |

## Recurring failure-pattern flags (-> monthly hypothesis cycle)

- 59% of losing exits are `hard_stop` (13/22)
- most losses concentrated in C6_bollinger_range (16)

## Verdict

Does NOT beat the no-trade baseline. Per the program rule, a flat week beats a losing week — strategies failing to clear $0 net are candidates for demotion.

## Open book (maintenance contract: should be EMPTY)
```
altcoin_reversion_state: {
  "XPL/USDT": {
    "entry_price": 0.09924,
    "entry_ts": "2026-06-28T07:38:40.507641+00:00",
    "size_usd": 5.0,
    "entry_z": -1.965465316817011,
    "max_z": -1.2426008685957706,
    "symbol_vol": 0.09513143422120213
  },
  "KITE/USDT": {
    "entry_price": 0.1209,
    "entry_ts": "2026-06-29T03:38:40.384937+00:00",
    "size_usd": 7.77,
    "entry_z": -1.6277934714425293,
    "max_z": -1.6277934714425293,
    "symbol_vol": 0.05146529890513847
  }
}
bollinger_range_state: {
  "USD1/USDT": {
    "entry_price": 1.0005,
    "entry_ts": "2026-06-29T00:38:30.960838+00:00",
    "size_usd": 9.721818825906938,
    "entry_pct_b": 0.09793854701105315,
    "entry_rsi": 31.111111111094658
  }
}
stat_arb_state: {}
```

## OI collector health (T3 — the only live research thread, usable ~2027)
```
rows_total=16560  rows_last_7d=5190  newest=2026-06-29T04:07:01+00:00
distinct collection hours last 7d: 173 (expect ~168; gaps if fewer)
db_size_bytes=2469888
disk /home: used 23G of 72G (33%)
```

## Health anomalies (last 7 days)
```
paper-crypto: health=healthy restarts=0 started=2026-06-27T05:37:30.970359387Z
heartbeat-checker alerts (non-OK lines, last 7d):
[2026-05-24T09:55:02Z] suppressed (cooldown 40s < 3600s): auto-cron heartbeat stale 121min (>1200s threshold) — cron daemon may be dead
t3-watchdog alerts (non-OK lines):
```

_Generated 2026-06-29T04:10:02Z by aaats-weekly-report.sh (cron, Mondays 06:10Z)._
