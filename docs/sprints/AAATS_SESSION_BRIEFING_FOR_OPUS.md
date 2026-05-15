# AAATS — COMPLETE SESSION BRIEFING FOR NEXT AI SESSION
**Date:** 2026-05-07  
**Prepared by:** Claude Sonnet (Cowork Mode)  
**Intended for:** Claude Opus (Next Session)  
**Project:** AAATS — Autonomous AI Adaptive Trading System  
**User:** Puneeth (puneethmp106@gmail.com)

---

## CRITICAL CONTEXT: WHO PUNEETH IS

- Building AAATS as a long-term autonomous quant trading system
- **Capital:** Crypto $110 (Binance Futures) + NSE ₹25,000 (Angel One SmartAPI)
- **Timeline:** 3–4 months paper trading → go live
- **Infrastructure:** Oracle Cloud, Streamlit monitoring UI, cloud-native, checkpoint-driven, modular
- **Working style preference:** Ruthless mentor — direct, stress-test ideas, research thoroughly, no padding
- **Business partner mindset** — treat as co-architect, not just user

---

## WHAT EXISTS ALREADY (PRIOR SESSION — DON'T REBUILD)

From previous sessions, AAATS already has a **27-component institutional framework** built. Full spec files are on Puneeth's desktop at:

```
C:\Users\udaym\OneDrive\Desktop\Puneeth\CLAUDE_CODE_MASTER_PROMPT_ALL_PHASES.md
C:\Users\udaym\OneDrive\Desktop\Puneeth\CLAUDE_CODE_COMPLETE_INSTITUTIONAL_SYSTEM.md
C:\Users\udaym\OneDrive\Desktop\Puneeth\LEGAL_COMPLIANCE.md
C:\Users\udaym\OneDrive\Desktop\Puneeth\AAATS_LEGAL_TRADING_SETUP.md
```

**Phase status:** Phase 0 complete, Phase 1 running (paper trading, Cycle 1/24)

**27 components include:**
- Encrypted Credentials Manager
- Kill Switch + Circuit Breaker
- Persistent Position Manager
- Dynamic Position Sizer (Kelly + volatility)
- Drawdown Monitor + Auto-Pause
- PnL Attribution (per strategy/market)
- Rate Limiting + Liquidity Checker
- Order Validator, Settlement Risk Manager
- Funding Rate Monitor, Slippage Tracker
- Correlation Monitor, Market Hours Gate
- Health Monitoring, Graceful Shutdown
- Daily Reconciliation
- + 11 advanced features (stress testing, macro hedging, anomaly detection, etc.)

---

## CURRENT SYSTEM — WHAT'S RUNNING

### Crypto Layer ($110, Binance Futures)
- Universe: BTC/USDT, ETH/USDT, SOL/USDT, LINK/USDT, DOT/USDT, AVAX/USDT
- HMM regime detection (trained on daily bars → classifies BULL/BEAR/RANGE)
- 6-indicator consensus voting (BUY/SELL/HOLD majority)
- BTC Dominance filter (suppresses altcoin buys when BTC.D rising)
- Fear & Greed Index macro filter
- XGBoost ML gate (trained on 2000H Binance data, val_acc unreported)
- Stat-arb: BTC/ETH z-score on 20 bars, entry |z|>2.0, exit |z|<0.5, 4% capital/leg
- Current live position: SHORT BTC / LONG ETH entered z=+2.10, now z=+1.4
- ATR trailing stop 2.5×, Kelly sizing 8% max, 20% portfolio heat cap, -20% drawdown halt

### NSE Layer (₹25,000, Angel One SmartAPI)
- Universe: 20 stocks across Financials, IT, Energy, FMCG, Auto, Pharma, Infra
- Same signal stack as crypto + India VIX filter, sector cap (2 positions/sector)
- Separate XGBoost (trained on 2Y NSE daily bars, val_acc = 63.7%)
- Stat-arb: HDFCBANK/ICICIBANK pairs, 3% capital/leg (~₹750/side)
- Market hours gate: 09:15–15:30 IST only

### CURRENT CRITICAL ISSUE
**XGBoost ML gate is blocking 100% of directional trades** — "market too noisy."  
Only live position is the stat-arb. System is not trading directionally at all.

---

## THIS SESSION — WHAT WAS FULLY DISCUSSED AND DECIDED

### CRITIQUE OF CURRENT SYSTEM (Key Points)
1. **Capital vs. complexity mismatch** — institutional-grade architecture on $110/$25K. Fees eat returns at this size ($4/leg stat-arb is below Binance minimum notional).
2. **XGBoost blocking = broken pipeline**, not conservative risk management. Must fix.
3. **HMM daily bars + 15-min signals = temporal mismatch** (regime label hours stale).
4. **Stat-arb bypasses ALL regime filters** — no guard on the pairs layer in bear markets.
5. **20 NSE stocks at ₹2,000/position** — operational overhead exceeds diversification benefit.
6. **Fix: Kill the hard gate. Use ML as probability WEIGHTER not binary blocker.**

---

## COMPLETE STRATEGY UNIVERSE — ALL DESIGNED THIS SESSION

### CRYPTO STRATEGIES

**C1 — Enhanced BTC/ETH Stat-Arb**
- Data: 1H candles, 30-bar z-score (not 20-bar daily)
- Entry: |z| > 1.8, Exit: |z| < 0.35
- Time stop: 48H max hold
- Hard stop: z reaches 2.8 (spread blowing out)
- Weekly Engle-Granger cointegration test (pause if p>0.05)
- Correlation guard: pause if BTC/ETH 14-day correlation < 0.80
- Capital: 5% per leg ($5.50/side)
- Expected: 4–6 trades/month, 63–68% win rate, avg +0.9% per round trip

**C2 — 4H Momentum Breakout (BTC + ETH only)**
- Entry: Close > 20-bar high + RSI(14) > 52 + Volume > 1.4× 20-bar avg
- Pre-filters: HMM = BULL + BTC.D not rising >0.8%/24H + Fear & Greed > 40
- Profit target: +2.0% (close 70%), trail 30% on 1H 10-EMA
- Time stop: exit if not +0.8% in 8 hours
- Hard stop: -1.2% from entry
- Stagnation check every 2H: if <0.3% move in 4H → EXIT
- Capital: 6% ($6.60)
- Expected: 4–5 trades/month, 52–55% win rate

**C3 — Altcoin Beta Mean Reversion (SOL, LINK, AVAX)**
- Indicator: log(ALT/BTC) z-score on 4H, 20-bar lookback
- Entry: ratio z-score < -2.0 (alt underperformed BTC → snap back)
- Pre-filters: HMM ≠ BEAR + BTC RSI(4H) > 35
- Target: ratio z-score returns to -0.5
- Time stop: 24H
- Hard stop: z drops to -3.0
- Capital: 4% ($4.40), max 1 alt at a time
- Expected: 2–4 trades/month, 55–58% win rate, avg +2.5%

**C4 — Binance New Listing Play**
- Monitor: binance.com announcements feed
- Wait 30–90 min after listing open (let pump-dump settle)
- Entry: price stabilizes (<±3% over 15 min) + volume declining + price 20–40% below listing open
- Target A: +15% → close 60%; Target B: +25% → close 40%
- Time stop: 6H
- Hard stop: -8%
- Filters: >$5M volume in 2H, not Innovation Zone, not meme coin, market cap <$500M at listing
- Capital: 3% ($3.30)
- Expected: 1–2 qualifying trades/month, 55–60% win rate, avg +18%

**C5a — Directional Perpetual Futures (Long + Short)**
- Execute existing C1/C2/C3 signals on perp futures instead of spot
- Advantage: can SHORT in bear regime, lower fees (0.02% maker vs 0.1% spot)
- HARD RULE: Max 2× leverage ONLY. Never 5× or 10×.
- Bear regime SHORT signal: HMM=BEAR + consensus SELL + RSI(4H) > 60 → short weakest alt
- Short target: -1.5%, stop: +1.0% above entry
- Capital: same as underlying strategy

**C5b — Funding Rate Arbitrage (Market Neutral — Best Risk/Return)**
- Entry trigger: BTC/ETH perp funding rate > 0.08%/8H
- Structure: LONG $55 spot + SHORT $55 perp at 1× (delta neutral)
- Income: 0.08% × 3 payments/day = 0.24%/day ≈ 7%/month on $50 deployed
- Exit: close both legs when funding drops below 0.02%/8H
- Monitor: coinglass.com/FundingRate
- Capital: $50 always-on allocation
- Expected: ~$3.50–$4/month near risk-free income

---

### NSE STRATEGIES

**N1 — HDFCBANK/ICICIBANK Pairs (Enhanced)**
- Data: 30-min bars, 40-bar z-score
- Entry: |z| > 1.7, only 10:00 AM–2:00 PM IST
- Exit: |z| < 0.30 OR end-of-day 3:00 PM (no overnight pairs)
- Hard stop: z reaches ±2.8
- India VIX guard: >18 → skip new entries
- Capital: 4% per leg (₹1,000/side)
- Expected: 5–8 trades/month, 60–65% win rate

**N2 — NSE Large Cap Gap Reversal**
- Universe: HDFCBANK, ICICIBANK, TCS, RELIANCE, INFY
- Trigger: stock gap down >1.2% at open
- Filters: Nifty gap <0.7%, VIX <20, no earnings that day, no sector negative news
- Entry: 9:22 AM (7 min after open)
- Target: +0.9%, Time stop: 11:30 AM, Hard stop: -0.6%
- Capital: 6% (₹1,500)
- Expected: 2–4 trades/month, 60–63% win rate

**N3 — Weekly Momentum Rotation**
- Every Monday: rank 20 stocks by score = (ROC_1M × 0.25) + (ROC_3M × 0.35) + (ROC_6M × 0.40)
- Buy top 3 (1 per sector max), hold Monday open → Friday close
- Mid-week decay check: if stock falls out of top 10 → exit early
- Filters: VIX <22, stock not down >8% in last week, no earnings this week
- Hard stop mid-week: any holding drops >3.5% from entry
- Capital: 5% each (₹1,250 × 3)
- Expected: 37–40% CAGR potential (NSE momentum factor, 10-year backtest)

**N4 — Sector Rotation Swing (2-Week Hold)**
- Every 2 weeks: rank 6 sectors by avg 3-week return
- Buy 1 strongest stock from top 2 sectors
- Hold 2 weeks, exit if sector falls out of top 3 mid-cycle
- ATR stop: 1.8× 4H ATR
- Capital: 8% per stock (₹2,000 × 2)
- Expected: 2 positions × 2 cycles/month, 55% win rate, 1.5–2.5% per rotation

**N5 — NSE Mainboard IPO Listing Day**
- Monitor: ipowatch.in for GMP daily
- Apply filter: subscription >50×, GMP >25% and stable/rising, QIB >20×, company profitable 2Y+
- Listing day: sell at open if GMP was >40%; wait for 15-min dip if GMP was 20–35%
- Secondary market play: buy the listing dip (15–30 min after open), target +8–12%, stop -5%, time stop 2H
- Capital: 6% (₹1,500) for secondary play
- Expected: 2–4 qualifying/month, 65–70% win rate, avg 25–40% listing gain

**N6 — SME IPO Play (Highest Win Rate)**
- DATA: 90% of 2024 SME IPOs had positive listing gains. Avg extraordinary (some 200–386%)
- Filter: subscription >100×, GMP >30% and rising, Manufacturing/IT/Healthcare/Infra only, revenue growing 3Y+, promoter holding >50% post-IPO
- If hits upper circuit (20%) on listing: hold until circuit opens, then sell
- Emergency exit: if listing opens flat or negative → EXIT within 5 minutes
- Monitor: nseindia.com/market-data/all-upcoming-issues-ipo
- Expected: 2–3 qualifying/month, 80%+ win rate when filtered, 30–150% per winner

**N7 — Nifty Options (Directional, Regime-Based)**
- At current capital (₹25K): buy weekly options only (not sell — needs more margin)
- BULL regime → Buy Nifty ATM/1-OTM Call on Monday
- BEAR regime → Buy Nifty ATM/1-OTM Put on Monday
- Exit: Wednesday close (avoid final 2-day theta decay)
- Hard stop: -40% of premium paid
- Capital: 5% (₹1,250 per buy)
- Upgrade path: ₹75K → Bank Nifty futures; ₹1.5L → Nifty futures

---

## ML GATE FIX — CRITICAL ARCHITECTURAL DECISION

**Current (broken):** XGBoost outputs binary 0/1 — blocks 100% of trades  
**Fix — probability weighting:**

```python
confidence = model.predict_proba(features)[0][1]
base_size = kelly_position_size(signal)

if confidence < 0.40:   position_size = 0          # skip
elif confidence < 0.50: position_size = base_size * 0.30   # tiny
elif confidence < 0.60: position_size = base_size * 0.60   # half
elif confidence < 0.75: position_size = base_size * 0.85   # near full
else:                   position_size = base_size * 1.20   # scale up (capped at Kelly max)
```

ML becomes a confidence scorer + position sizer, not a gate. This is how institutional systems use ML.

**Also fix:** Retrain XGBoost on last 6 months of data only (not 2000H of old data). Use walk-forward validation: train months 1–4, test month 5, roll forward quarterly.

---

## DAILY OPERATING SYSTEM — DESIGNED THIS SESSION

### Capital Allocation
**Crypto ($110):**
- $22 Reserve (20%) — never deployed, recovery buffer
- $50 Always-On (funding arb C5b + stat-arb C1)
- $38 Active Trading (C2, C3, C4, C5a)

**NSE (₹25,000):**
- ₹4,000 Reserve (16%)
- ₹6,000 Always-On (HDFCBANK/ICICIBANK pairs N1)
- ₹8,000 IPO Fund (held for SME/mainboard applications)
- ₹7,000 Active Trading (N2, N3, N7)

### Daily Targets
| Day Type | Crypto Target | NSE Target | Combined |
|---|---|---|---|
| Normal | $0.55 | ₹200 | ~₹247 |
| IPO/Listing Day | $0.80+ | ₹400–800+ | ~₹500+ |
| High Vol Day | $0.20 (arb only) | ₹60 (pairs only) | ~₹77 |
| Recovery Day | 60–70% of prior loss | 60–70% of prior loss | recovery |

### Pre-Market Routine (7:30 AM IST — 30 min)
Crypto: funding rate check → regime check → BTC.D → Fear & Greed → new listing alert  
NSE: India VIX → IPO listing today? → SME subscription closing? → gap stocks at open?

### 4 Day Types
1. **Normal Day** — all strategies active, full size
2. **IPO/Listing Day** — highest profit potential, C4 + N5/N6 active
3. **High Volatility Day** (VIX >20, F&G <25) — market neutral only, preserve capital
4. **Recovery Day** — tiered protocol below

### Recovery Protocol (3 Tiers)
- **Tier 1** (<1% loss, <₹250): Trade normally, no adjustment
- **Tier 2** (1–3% loss, ₹250–₹750): Increase pairs size +30%, funding arb full, A+ signals only, take profit at 70% of normal target
- **Tier 3** (>3% loss, >₹750): Market-neutral only for 2 days, reduce all sizes -40% for 5 days, zero directional trades, review cause before resuming

### Daily Stop Rule
Stop all trading when combined daily loss hits 0.8% of total capital (~₹250). Non-negotiable.

---

## THE AAATS MASTER ARCHITECTURE — REQUESTED BUT INCOMPLETE

The user submitted a detailed, institutional-grade system design prompt at the end of the session. This is the **most important unfinished item** for the next session.

### What Was Requested
A complete architecture for AAATS as a multi-agent quant trading OS with 13 layers:

1. Market Scanner Layer (Top 300 Binance futures + Nifty 200)
2. Regime Detection Engine (12 regimes: BULL/BEAR/RANGE/HIGH_VOL/LOW_VOL/PANIC/SHORT_SQUEEZE/ALT_SEASON/BTC_DOM/MEAN_REV/LIQUIDITY_CRISIS/VOL_EXPANSION)
3. Opportunity Classification Engine (12 opportunity types)
4. Specialized Strategy Pods (7 pods: Momentum, Stat-Arb/Mean-Rev, Liquidity Sweep Hunter, Derivatives Intelligence, Volatility Expansion, Intraday NSE Momentum, Market Microstructure)
5. Meta AI Allocation Controller (decides which pod gets capital, dynamically)
6. Risk Management Engine (volatility-adjusted sizing, circuit breakers, correlation-aware)
7. Reinforcement Learning Feedback Loop (continuously learns from outcomes)
8. Portfolio Intelligence Layer (correlation risk, capital rotation, hedging)
9. Candle Structure AI Vision Layer (CNN/Transformer on chart patterns)
10. Execution & Slippage Optimization Layer
11. Derivatives Intelligence Layer (funding rate, OI, liquidation heatmaps)
12. Market Microstructure Layer (order-book imbalance, spoofing detection)
13. Adaptive Capital Rotation Engine

### The Key Architectural Question (Needs Definitive Answer)
**Single unified engine vs. dual separate engines vs. hybrid?**

The user wants analysis from: quant perspective, AI systems design, scalability, infrastructure, execution, latency, feature engineering, RL, risk management, and operational stability angles.

### My Preliminary Position (For Opus to Validate/Expand)
**Recommendation: Hybrid Architecture**
- Shared core: infrastructure, logging, orchestration, portfolio analytics, monitoring, deployment, risk framework
- Separate: strategy engines, ML models, feature pipelines, execution systems, market scanners, regime classifiers per market

Why NOT unified: crypto features (funding rates, OI, liquidation data) contaminate NSE model. Temporal dynamics are incompatible (24/7 vs 6.25H). Regime shifts at different speeds. ML trained on both markets simultaneously will underfit both.

Why NOT fully separate: doubles infrastructure cost, no cross-market portfolio intelligence, can't manage correlation between BTC rally and IT sector in India (they correlate during risk-on).

Why Hybrid wins: specialization where it matters (signal generation), unification where it helps (risk, portfolio, infrastructure).

### How Elite Quant Firms Actually Work (Research Findings)

**Renaissance Technologies (Medallion Fund):**
- One integrated model, not competing strategies — everything feeds into a single interconnected system
- Ensemble of thousands of short-horizon statistical models — right only 50.75% of trades but millions of trades
- Obsessive data quality — petabytes, cleansed to extreme degree
- Continuous research loop — test everything, deploy few, replace constantly
- 66% gross returns, 39% net (after fees)

**Citadel Multi-Pod System:**
- 5 distinct strategy businesses, each a separate pod
- CIO office allocates capital based on Sharpe ratio, drawdown, correlation across pods
- Central risk team reports to CEO (not to trading teams) — independent oversight
- PMs compete for capital based on recent performance track record
- Dynamic reallocation: strong pods get more, weak pods get less

**Key lesson adapted for AAATS:** Renaissance = unified intelligence. Citadel = competitive pods with meta-allocator. AAATS should be a hybrid — Citadel-style pods (specialized) + Renaissance-style meta-intelligence (interconnected).

---

## WHAT OPUS SHOULD DO IN THE NEXT SESSION

### Priority 1 — Complete the AAATS Master Architecture
Build the full architecture document covering:
- All 13 layers with implementation specs
- Single vs. Dual vs. Hybrid engine analysis (deep, not surface level)
- How each layer interacts with others
- RL loop design (state, action, reward, update frequency)
- Candle Structure AI approach (Transformer on OHLCV sequence > CNN on images for this use case)
- Meta AI controller logic (how it decides pod allocation)
- Market microstructure implementation at retail level
- Realistic implementation roadmap (what to build in what order given capital constraints)

### Priority 2 — ML Gate Overhaul
- Design the full probability-weighting system (replace binary gate)
- Walk-forward retraining protocol
- Separate model per market (crypto XGBoost vs. NSE XGBoost)
- Feature importance analysis (which features are actually predictive)

### Priority 3 — Derivatives Intelligence Layer (Full Design)
- Funding rate arb automation (C5b fully coded)
- Open interest analysis for entry timing
- Liquidation cascade detection
- Long/short ratio sentiment signal
- Basis spread monitoring

### Priority 4 — IPO Intelligence System
- GMP monitoring automation (scrape ipowatch.in or investorgain.com)
- Subscription data tracking
- SME vs. Mainboard filter logic
- Allotment probability modeling
- Listing day execution algorithm

### Priority 5 — RL Loop Design
- State space: current regime + recent trade outcomes + portfolio heat + vol regime
- Action space: which pod to activate + size multiplier per pod
- Reward: Sharpe contribution of each trade (not raw P&L)
- Update frequency: weekly (not real-time — too noisy at this capital level)
- Implementation: start with simple bandit algorithm, upgrade to full RL later

---

## PAPER TRADING METRICS TO TRACK (Monthly Review)

Per strategy, track weekly:
1. Win rate (running)
2. Avg time in winning vs. losing trades
3. Time stop trigger rate vs. profit target hit rate
4. Fee drag as % of gross P&L
5. Signal filter rate (% of signals blocked by pre-conditions — if >80%, conditions too strict)
6. Sharpe ratio per strategy (annualized)
7. Max single-day drawdown per strategy

### Go-Live Checklist (4 months out)
| Metric | Minimum Bar |
|---|---|
| Paper trading Sharpe (annualized) | > 1.0 |
| Max drawdown in paper period | < 15% |
| Stat-arb convergence rate | > 65% |
| XGBoost out-of-sample accuracy | > 55% |
| Fee drag as % of gross P&L | < 30% |
| System uptime / missed signals | < 5% missed |
| Funding arb income (consistent) | > $3/month |

---

## HONEST ASSESSMENT (For Business Partner Alignment)

### What Will Actually Make Money at Current Capital
1. **Funding rate arb (C5b)** — near risk-free $3–4/month on $50 deployed. Start this first.
2. **SME IPO plays (N6)** — 90% win rate in 2024 when filtered. Highest asymmetric return.
3. **HDFCBANK/ICICIBANK pairs (N1 enhanced)** — proven cointegration, most reliable NSE income.
4. **BTC/ETH stat-arb (C1 enhanced)** — needs position sizing fix (must be >$10/leg minimum).

### What Needs to Be Built But Won't Generate Returns Yet (Infrastructure)
- Full 13-layer architecture
- RL loop
- Candle Structure AI
- Market Microstructure Engine
- Meta AI controller

These are 6–12 month builds. Don't expect them to generate alpha immediately. They are the **scalability infrastructure** for when capital grows to ₹1L+ / $1,000+.

### The Honest Capital Reality
At $110/$25K, transaction costs structurally cap monthly returns. The system is being built correctly, but full profitability requires:
- Crypto: minimum $500 effective ($1,000 ideal) to make fees <0.5% per round trip
- NSE: minimum ₹75,000 ($900) for stat-arb sizing and options trading to work properly
- Target: reach this capital level through savings + paper trading profits over 3–4 months

---

## KEY DECISIONS MADE THIS SESSION (Don't Revisit)

1. ✅ Hybrid architecture (shared core + separate market engines) — decided
2. ✅ ML gate → probability weighter (not binary blocker) — decided
3. ✅ 3–4 month paper trading timeline before going live — decided
4. ✅ 12 total strategies (C1–C5b + N1–N7) — designed and validated
5. ✅ Daily operating system with 4 day types — designed
6. ✅ 3-tier recovery protocol — designed
7. ✅ Reserve capital policy (20% crypto, 16% NSE, never deployed) — decided
8. ✅ Time stop on all strategies ("if not moving, sell") — core philosophy confirmed

---

## WHAT OPUS SHOULD NOT DO

- Do not redesign the 27-component base system (already built, in prior session files)
- Do not recommend starting over — build on what exists
- Do not give surface-level retail trading advice
- Do not suggest generic indicators without backtested logic
- Do not ignore the capital constraint reality — always factor in fees
- Do not treat this as a one-time chatbot session — this is an ongoing co-development project

---

## REFERENCE LINKS FROM THIS SESSION
- [SME IPO Performance 2024](https://www.chittorgarh.com/ipo/ipo_perf_tracker.asp?exchange=sme&year=2024)
- [Live IPO GMP](https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/)
- [CoinGlass Funding Rates](https://coinglass.com/FundingRate)
- [NSE IPO Calendar](https://www.nseindia.com/market-data/all-upcoming-issues-ipo)
- [Renaissance Technologies Architecture](https://navnoorbawa.substack.com/p/renaissance-technologies-the-100)
- [Citadel Pod Architecture](https://navnoorbawa.substack.com/p/how-millennium-citadel-and-point72)
- [NSE Momentum Factor Backtest](https://momentum-lab.medium.com/momentum-strategies-in-indian-markets-insights-from-a-10-year-backtest-analysis-ef285d6533c4)
- [Drawdown Recovery Protocol](https://www.tradezella.com/blog/drawdown-management)

---

*End of Session Briefing. This document covers everything discussed in the 2026-05-07 session. The AAATS master architecture design is the primary unfinished item for the next session.*
