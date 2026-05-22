---
name: AAATS Complete Strategy Universe (Session 2026-05-07)
description: All 12 strategies designed across crypto and NSE with exact entry/exit rules, daily operating system, recovery protocol
type: project
originSessionId: dc3b601e-bd65-4805-b294-9be75664f48c
snapshot_from_cowork_memory: 2026-05-21
caveat_2026_05_21: This 12-strategy framework is largely aspirational. Production paper-crypto as of 2026-05-21 only fires 2 strategies (C3_altcoin_reversion, C6_bollinger_range). C1, C2, C5b are wired but starved by gating/regime/universe filters in the current window. NSE strategies N1-N7 are paper-only design, not deployed. Treat this doc as future-target catalog, not current production reality.
---
# AAATS Complete Strategy Universe

**Designed:** 2026-05-07
**Status:** Ready for paper trading implementation
**Caveat (2026-05-21):** Per the diagnostic in `docs/decisions/2026-05-22_live_flip_rebuild_plan.md`, only C3 and C6 fire in production. The full 12-strategy framework below is design-time, not production-time. The Track B Phase 0 work explicitly investigates why the other 10 don't trade.

## CRYPTO STRATEGIES ($110 capital, Binance Futures)

### C1 — BTC/ETH Stat-Arb (Enhanced)
- 1H candles, 30-bar z-score, entry |z|>1.8, exit |z|<0.35
- Time stop: 48H, hard stop: z reaches 2.8
- Weekly Engle-Granger test, correlation guard <0.80
- 5% capital per leg, expected 4–6 trades/month, 63–68% WR

### C2 — 4H Momentum Breakout (BTC+ETH only)
- Entry: Close >20-bar high + RSI(14)>52 + Vol>1.4× avg
- Filters: HMM=BULL + BTC.D not rising>0.8% + F&G>40
- Target +2.0%, time stop 8H if not +0.8%, hard stop -1.2%
- Stagnation exit: <0.3% move in 4H → exit
- 6% capital, 52–55% WR

### C3 — Altcoin Beta Mean Reversion (SOL, LINK, AVAX)
- log(ALT/BTC) z-score <-2.0 → LONG alt
- Filters: HMM≠BEAR + BTC RSI>35
- Target: z returns to -0.5, time stop 24H, hard stop z=-3.0
- 4% capital, 55–58% WR, avg +2.5%
- **As of 2026-05-21: this strategy is the primary loss source (-$5.63 of -$5.76 9d realized P&L). 78% of loss concentrated in 5 names: OP, ARB, PUMP, FET, LUNC. Track B.0 investigation target.**

### C4 — Binance New Listing Play
- Wait 30–90 min post-listing, buy stabilization dip
- Filters: >$5M vol in 2H, not Innovation Zone, market cap<$500M
- Target +15%/+25%, time stop 6H, hard stop -8%
- 3% capital, 55–60% WR

### C5a — Directional Perpetual Futures
- Execute C1/C2/C3 signals on perps, max 2× leverage
- Short signals now available in BEAR regime
- 0.02% maker fee vs 0.1% spot — more efficient

### C5b — Funding Rate Arbitrage (Always-On)
- Entry: funding >0.08%/8H → LONG $50 spot + SHORT $50 perp (1×, delta neutral)
- Exit: funding drops below 0.02%/8H
- ~7%/month on $50 deployed, near risk-free
- Monitor: coinglass.com/FundingRate
- **As of 2026-05-21: HALTED — buy-side audit found per-leg vs round-trip notional asymmetry. See docs/known_issues/2026-05-15_buy_side_audit.md.**

## NSE STRATEGIES (₹25,000, Angel One SmartAPI)

[Not deployed as of 2026-05-21. Design-only.]

### N1 — HDFCBANK/ICICIBANK Pairs (Enhanced)
- 30-min bars, 40-bar z-score, entry |z|>1.7, 10AM–2PM only
- Exit: |z|<0.30 or 3PM EOD force-close
- VIX guard >18 skips entries
- 4% capital/leg (₹1,000/side), 5–8 trades/month, 60–65% WR

### N2-N7
See original memory for full N2-N7 definitions; not material to current Track B work since NSE side is out of scope until crypto profitability is established.

## CAPITAL ALLOCATION (design-time)
**Crypto:** $22 reserve | $50 always-on (C5b+C1) | $38 active
**NSE:** ₹4K reserve | ₹6K always-on (N1) | ₹8K IPO fund | ₹7K active

## ML GATE FIX (Critical, design-time)
Replace binary XGBoost gate with probability weighting:
- <0.40 confidence → size=0 (skip)
- 0.40–0.50 → size×0.30
- 0.50–0.60 → size×0.60
- 0.60–0.75 → size×0.85
- >0.75 → size×1.20 (capped at Kelly max)

## DAILY STOP RULE
Stop all trading at 0.8% combined daily loss. Non-negotiable.
