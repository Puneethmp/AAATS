# AAATS — Autonomous Adaptive AI Trading System
## Master Blueprint v3.1 | Owner-Approved | Last Updated: April 2026

---

> **Owner's Note:** This document is the single source of truth for AAATS. Every architectural decision, every risk rule, every phase boundary was stress-tested before being accepted. Nothing here is aspirational. Everything here is buildable. If a future decision contradicts this document, this document wins unless a written justification with research backing overrides it.
>
> **v3.0 Change:** System expanded to four market modules — US Equities (Alpaca), Indian Equities — NSE/BSE (Zerodha Kite), NSE F&O (Zerodha Kite), and Crypto (CoinGecko + CCXT, Phase 8 only). All markets share the same core engine. Market-specific logic is fully isolated in dedicated modules. Mixed logic between markets is permanently rejected.
>
> **v3.1 Change:** India broker switched from Zerodha Kite (`kiteconnect`, ₹200/month API subscription) to Angel One SmartAPI (`smartapi-python`, free with demat account). Justification: identical feature set (historical OHLCV, option chain, OI, WebSocket, TOTP auth), zero monthly subscription cost. Architecture unchanged — only broker-specific modules in `markets/india/` are affected.

---

## Table of Contents

1. [Project Identity](#1-project-identity)
2. [Honest Expectations](#2-honest-expectations)
3. [Full System Architecture](#3-full-system-architecture)
4. [Technology Stack — Final Decisions](#4-technology-stack--final-decisions)
5. [Data Sources — Final Decisions](#5-data-sources--final-decisions)
6. [ML Model Strategy](#6-ml-model-strategy)
7. [Risk Management Rules — Non-Negotiable](#7-risk-management-rules--non-negotiable)
8. [Backtesting Integrity Rules](#8-backtesting-integrity-rules)
9. [Build Phases — Full Lifetime Roadmap](#9-build-phases--full-lifetime-roadmap)
10. [Layer-by-Layer Module Reference](#10-layer-by-layer-module-reference)
11. [The 3 Rules That Cannot Be Broken](#11-the-3-rules-that-cannot-be-broken)
12. [Deferred Decisions Log](#12-deferred-decisions-log)
13. [Rejected Ideas Log](#13-rejected-ideas-log)
14. [Performance Targets](#14-performance-targets)
15. [Decision Change Protocol](#15-decision-change-protocol)

---

## 1. Project Identity

| Field | Value |
|---|---|
| **Project Name** | Autonomous Adaptive AI Trading System (AAATS) |
| **Type** | Systematic, ML-assisted trading research and execution platform |
| **Market 1** | US Equities — NYSE / NASDAQ via Alpaca Markets |
| **Market 2** | Indian Equities — NSE / BSE via Angel One SmartAPI |
| **Market 3** | NSE Futures & Options — via Angel One SmartAPI |
| **Market 4** | Crypto — BTC/ETH/majors via CoinGecko + CCXT — Phase 8 only |
| **Execution Mode** | Paper trading → Live (minimum 3 months paper per market before real capital) |
| **Owner** | Puneeth |
| **Project Lifespan** | Lifetime (not a side project) |
| **Phase 0 Start Condition** | All environments set up and confirmed |
| **Architecture Rule** | Market modules are isolated. US logic never touches India logic. Shared engine only. |

---

## 2. Honest Expectations

### What AAATS Is

- A disciplined, rule-based and ML-assisted trading platform across multiple markets
- A system that executes strategies faster and more consistently than any human
- A capital preservation engine first, a profit engine second
- A system that gets better every month through systematic learning
- A tool that makes decisions with full traceability and explainability

### What AAATS Is Not

- A money printer
- A system with zero losing trades
- A replacement for a trading edge — AI amplifies your edge; it cannot create one from nothing
- A get-rich-quick machine
- A system that beats institutional hedge funds or HFT desks

### Critical Warning — F&O Specifically

NSE F&O is a leveraged derivatives market operating on margin. A bad position can lose more than capital deployed. F&O risk rules are stricter than equities. F&O strategies are never deployed without a separately validated backtest on derivative-specific data including historical option chains. Options pricing requires Greeks (Delta, Gamma, Theta, Vega) — this is completely different math from equity position sizing.

### Realistic Performance Targets

| Metric | US Equities | India Equities | NSE F&O | Red Flag (All) |
|---|---|---|---|---|
| Annual return | 15–35% | 12–30% | 20–50% | >100% |
| Win rate | 52–60% | 52–60% | 45–55% | >85% |
| Max drawdown | -10% to -20% | -10% to -20% | -15% to -25% | <-5% (suspiciously low) |
| Sharpe ratio | 1.0–1.8 | 1.0–1.8 | 0.8–1.5 | >3.0 |
| Profit factor | 1.3–2.0 | 1.3–2.0 | 1.2–1.8 | >3.0 |

> F&O targets are deliberately more conservative on Sharpe because derivatives carry tail risk that backtests systematically underestimate.

---

## 3. Full System Architecture

```
╔══════════════════════════════════════════════════════════════════════════╗
║              AAATS v3.0 — PRODUCTION ARCHITECTURE                        ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  LAYER 0: FOUNDATION (shared across all markets)                         ║
║  ├── Config Manager         (per-market env vars, secrets, constants)    ║
║  ├── Structured Logger      (Loguru, market-tagged, every event)         ║
║  ├── Immutable Audit Trail  (append-only, market-tagged decisions)       ║
║  ├── Kill Switch System     (global halt OR per-market halt)             ║
║  └── Health Monitor         (checks all market APIs every 5 minutes)    ║
║                                                                          ║
║  LAYER 1: DATA PIPELINE (four isolated market modules)                   ║
║                                                                          ║
║  ┌─ US MODULE ──────────────────────────────────────────────────────┐   ║
║  │  ├── Alpaca Fetcher      (REST + WebSocket, real-time + hist.)    │   ║
║  │  ├── US Data Validator   (gaps, spikes, bad timestamps)           │   ║
║  │  ├── US Feature Eng.     (TA indicators + VIX + FRED macro)       │   ║
║  │  └── US Feature Store    (SQLite Phase 1–3 → TimescaleDB Phase 4) │   ║
║  └──────────────────────────────────────────────────────────────────┘   ║
║                                                                          ║
║  ┌─ INDIA EQUITY MODULE ────────────────────────────────────────────┐   ║
║  │  ├── Kite Fetcher        (NSE/BSE OHLCV via kiteconnect SDK)      │   ║
║  │  ├── Kite Token Manager  (daily TOTP auto-renewal via pyotp)      │   ║
║  │  ├── India Data Valid.   (circuit limits, delivery vol, NSE rules) │   ║
║  │  ├── India Feature Eng.  (TA + India VIX + FII/DII flows + PCR)  │   ║
║  │  └── India Feature Store (SQLite Phase 1–3 → TimescaleDB Phase 4) │   ║
║  └──────────────────────────────────────────────────────────────────┘   ║
║                                                                          ║
║  ┌─ NSE F&O MODULE ─────────────────────────────────────────────────┐   ║
║  │  ├── Kite F&O Fetcher    (option chain, OI, IV via Kite API)      │   ║
║  │  ├── F&O Data Validator  (lot size, liquidity, IV > 0, OI floor)  │   ║
║  │  ├── F&O Feature Eng.    (Greeks, PCR, IV rank, term structure)   │   ║
║  │  └── F&O Feature Store   (SQLite Phase 1–3 → TimescaleDB Phase 4) │   ║
║  └──────────────────────────────────────────────────────────────────┘   ║
║                                                                          ║
║  ┌─ CRYPTO MODULE (Phase 8 only) ───────────────────────────────────┐   ║
║  │  ├── CoinGecko Fetcher   (OHLCV, market cap, volume)             │   ║
║  │  ├── CCXT Connector      (execution, 100+ exchanges)              │   ║
║  │  ├── Crypto Validator    (wash trading filter, liquidity check)   │   ║
║  │  └── Crypto Feature Store                                          │   ║
║  └──────────────────────────────────────────────────────────────────┘   ║
║                                                                          ║
║  LAYER 2: INTELLIGENCE (per-market models, shared interface)             ║
║  ├── US Regime Detector     (bull/bear/sideways/high-vol via VIX+SPX)   ║
║  ├── India Regime Detector  (bull/bear/sideways/high-vol via India VIX) ║
║  ├── US Strategy Pool       (5 rule-based equity strategies)             ║
║  ├── India Equity Pool      (5 rule-based NSE/BSE strategies)            ║
║  ├── F&O Strategy Pool      (defined-risk only: spreads, strangles)      ║
║  ├── ML Ensemble            (XGBoost+LSTM, separately trained per mkt)   ║
║  ├── Uncertainty Engine     (confidence scoring per signal per market)   ║
║  └── Signal Ranker          (quality-ranked list, market-tagged)         ║
║                                                                          ║
║  LAYER 3: VALIDATION GATES (mandatory, market-aware, cannot be skipped)  ║
║  ├── Lookahead Bias Checker (timestamp enforcement, hard block)          ║
║  ├── Overfitting Detector   (Sharpe/PF thresholds per market type)       ║
║  ├── Walk-Forward Validator (no in-sample deployment ever)               ║
║  ├── Cost Simulator         (market-specific: STT, brokerage, slippage)  ║
║  ├── Liquidity Gate         (position size vs ADV < 1%)                  ║
║  └── F&O Greeks Validator   (Delta/Gamma/Theta within limits)            ║
║                                                                          ║
║  LAYER 4: DECISION                                                        ║
║  ├── Meta-Strategy Layer    (regime → strategy mapping per market)       ║
║  ├── Decision Engine        (final go/no-go + reason + market tag)       ║
║  └── Explainability Log     (human-readable why, per trade, per market)  ║
║                                                                          ║
║  LAYER 5: RISK (veto power — market-specific rules, shared enforcer)     ║
║  ├── US Position Sizer      (Quarter-Kelly + ATR, 1.5% max)             ║
║  ├── India Equity Sizer     (Quarter-Kelly + ATR, 1.5% max)             ║
║  ├── F&O Position Sizer     (lot-size aware, Greeks-aware, 1.0% max)    ║
║  ├── Cross-Market Allocator (total portfolio exposure cap enforced)      ║
║  ├── Drawdown Guardian      (-15% per market OR -20% total = halt)       ║
║  └── Real-Time Risk Reporter(live P&L + exposure, all markets)          ║
║                                                                          ║
║  LAYER 6: EXECUTION                                                       ║
║  ├── Alpaca Engine          (US paper + live)                            ║
║  ├── Kite Engine            (India equity + F&O paper simulation + live) ║
║  ├── CCXT Engine            (Crypto, Phase 8)                            ║
║  ├── Execution Simulator    (market-specific latency + fill modeling)    ║
║  └── Order Manager          (unified tracking, all markets)              ║
║                                                                          ║
║  LAYER 7: LEARNING LOOP                                                   ║
║  ├── Performance Tracker    (per-trade, per-strategy, per-market)        ║
║  ├── Drift Detector         (model staleness, per market independently)  ║
║  ├── Retrainer              (scheduled + event-triggered, per market)    ║
║  └── Strategy Graveyard     (retire underperformers, archive, not delete)║
║                                                                          ║
║  LAYER 8: OBSERVABILITY                                                   ║
║  ├── Streamlit Dashboard    (unified + per-market drill-down tabs)       ║
║  ├── Telegram Alert Bot     (market-tagged alerts to phone)              ║
║  └── Self-Diagnostics       (automated audit across all markets)         ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
```

### Isolation Rule

Markets share ONLY: core engine interfaces (abstract base classes), risk enforcer, audit trail, dashboard.

Markets do NOT share: data fetchers, feature engineering logic, strategy pools, ML model weights, execution engines.

Mixing market logic is permanently rejected.

---

## 4. Technology Stack — Final Decisions

### Core Infrastructure

| Component | Tool | Status | Reason |
|---|---|---|---|
| Language | Python 3.11 | **LOCKED** | Best ML ecosystem, stable. NOT 3.12 — XGBoost/PyTorch compatibility. |
| Environment | venv + pip-tools | **LOCKED** | pip-tools pins exact transitive deps. `pip-compile` generates reproducible installs. |
| Containerization | Docker | **DEFERRED — Phase 6** | Required for cloud execution. Unnecessary overhead locally in early phases. |
| Config | Pydantic v2 + python-dotenv | **LOCKED** | Type-safe, validated at startup, fails loudly on missing keys. Per-market config sections. |
| Logging | Loguru | **LOCKED** | Structured JSON, rotation built-in. Every log entry market-tagged. |
| Version Control | Git + GitHub | **LOCKED** | Non-negotiable. |
| CI | GitHub Actions | **LOCKED from Phase 0** | Auto-run pytest on every push. Catches regressions before they compound. |
| Testing | pytest + pytest-cov | **LOCKED** | Coverage enforced. Every module gets tests before it ships. |
| Code Quality | ruff + black | **LOCKED** | ruff replaces flake8/isort/pylint in one tool. black enforces formatting. Pre-commit hooks. |

### US Market Stack

| Component | Tool | Status | Reason |
|---|---|---|---|
| Broker + Data | Alpaca Markets (`alpaca-py`) | **LOCKED** | Free. Paper trading included. Real-time + historical OHLCV. REST + WebSocket. (`alpaca-trade-api` deprecated 2022 — replaced with official `alpaca-py` SDK.) |
| Macro Data | FRED API (`fredapi`) | **LOCKED — Phase 3+** | Free Federal Reserve indicators. GDP, CPI, Fed Funds Rate for feature engineering. |
| Volatility | VIX via Alpaca (^VIX) | **LOCKED** | Required for US regime detection. |

### India Market Stack

| Component | Tool | Status | Reason |
|---|---|---|---|
| Broker + Data | Angel One SmartAPI (`smartapi-python`) | **LOCKED** | Free with Angel One demat account. NSE/BSE equities + F&O. Historical OHLCV (5 years daily), real-time WebSocket, order placement. No monthly subscription fee. |
| Session Management | `pyotp` | **LOCKED** | TOTP-based daily session token auto-renewal. If renewal fails → halt India trading + alert. |
| Data Backup | NSEpy | **LOCKED as fallback** | Pulls historical OHLCV directly from NSE if Angel One historical data is insufficient. |
| India Macro | RBI DBIE + NSE FII/DII portal | **LOCKED — Phase 3+** | FII/DII net flow data is a regime indicator unique to Indian markets. Fetched daily. |
| India Volatility | India VIX via Angel One (INDIA VIX) | **LOCKED** | NSE's implied volatility index. Behaves differently from US VIX. Required for India regime. |
| F&O Chain Data | Angel One Option Chain API | **LOCKED** | Real-time OI, IV, strike data via SmartAPI. Required for all F&O strategies. |
| F&O Greeks | `mibian` library | **LOCKED** | Black-Scholes Greeks. Delta, Gamma, Theta, Vega per option position. Pure Python, no C deps. |
| PCR Calculation | Derived from Angel One OI data | **LOCKED** | Put-Call Ratio calculated internally from option chain OI. Key Indian F&O sentiment indicator. |

### Intelligence Stack (Shared Interface, Per-Market Models)

| Component | Tool | Status | Reason |
|---|---|---|---|
| Feature Engineering | `pandas-ta` | **LOCKED** | Pure Python TA library. 130+ indicators. Chosen over `ta-lib` — ta-lib requires C compilation that breaks CI. |
| ML Model 1 | XGBoost (`xgboost`) | **LOCKED** | Tabular classification. Fast, interpretable. Separate model trained per market. |
| ML Model 2 | LSTM (`PyTorch`) | **LOCKED** | Sequential temporal pattern recognition. Separate model per market. |
| Explainability | SHAP (`shap`) | **LOCKED** | SHAP values for XGBoost. Every prediction explainable. Required for audit trail. |
| Strategy Iteration | `vectorbt` | **LOCKED — Phase 2** | 100x faster than loop-based backtesting for parameter sweeps. Output still validated by custom engine. |
| Backtesting | Custom-built engine | **LOCKED** | Full control over bias guards. No third-party library enforces all the integrity rules this system requires. |
| Risk Math | Quarter-Kelly + ATR | **LOCKED** | Quarter-Kelly for position sizing. ATR for stop placement. Proven. Not gambling. |

### Data Storage

| Phase | Tool | Reason |
|---|---|---|
| Phase 1–3 | SQLite + SQLAlchemy ORM | Zero infrastructure. Handles daily bars for 1,000+ symbols across both markets. |
| Phase 4+ | PostgreSQL + TimescaleDB | Required for minute-bar data and real-time queries at scale. |

### Observability Stack

| Component | Tool | Status | Reason |
|---|---|---|---|
| Dashboard | Streamlit | **LOCKED — Phase 8** | Fast to build, sufficient through live trading. Per-market tabs. |
| Frontend | React | **DEFERRED — Phase 9+** | Not needed before live trading is proven. |
| Backend API | FastAPI + asyncio | **DEFERRED — Phase 6** | Required for real-time data at scale. Overhead not justified before Phase 6. |
| Alerts | Telegram Bot API (`python-telegram-bot`) | **LOCKED** | Free, instant, mobile. Market-tagged messages. |

### Crypto Stack (Phase 8 Only)

| Component | Tool | Status | Reason |
|---|---|---|---|
| Market Data | CoinGecko API | **LOCKED — Phase 8** | Free OHLCV. 30 calls/min free — sufficient for daily/hourly bars. Not for real-time ticks. |
| Execution | CCXT library | **LOCKED — Phase 8** | Unified interface to 100+ exchanges. CoinGecko is data-only; CCXT handles orders. |

---

## 5. Data Sources — Final Decisions

### US Equities — Alpaca Markets

- Free brokerage API with paper + live trading
- Real-time + historical OHLCV, minute and daily bars via REST and WebSocket
- Rate limits handled by exponential backoff layer
- $0 commission live; free paper trading
- **Verdict: Primary US source. Locked.**

### Indian Equities + F&O — Angel One SmartAPI

- Free with Angel One demat account — no monthly API subscription fee
- Real-time quotes, historical OHLCV (up to 5 years daily, 1 year minute bars), full option chain with OI + IV
- Angel One has NO native paper trading environment — AAATS simulates paper mode internally using live market data
- Rate limit: enforced internally via token bucket queue
- Session tokens expire daily — auto-renewed via `pyotp` TOTP login. If renewal fails: halt India trading + Telegram alert
- Brokerage: ₹20 flat per order equity; ₹20 per F&O order
- SmartAPI credentials required: API Key (from developer portal) + Client ID + Password + TOTP Secret
- **Verdict: Primary India source. Locked.**

### India Macro — RBI + SEBI/NSE Data

- RBI DBIE portal: repo rate, CPI, WPI, forex reserves
- NSE: FII/DII daily net buy/sell data (publicly available, fetched daily)
- **Verdict: Phase 3+ feature engineering supplement. Locked.**

### US Macro — FRED (Federal Reserve Economic Data)

- Free API for GDP, inflation, interest rates, unemployment
- **Verdict: Phase 3+ US feature supplement. Locked.**

### Crypto — CoinGecko + CCXT (Phase 8 Only)

- CoinGecko: OHLCV market data, free tier, 30 calls/min
- CCXT: Execution layer, connects to exchange of choice
- **Verdict: Phase 8 only. Equity engine must be proven first.**

### What We Do NOT Use

| Tool | Reason Rejected |
|---|---|
| yfinance | Web scraping, unreliable, not production-grade |
| IEX Cloud | Shut down August 2024. Dead provider. |
| Zerodha Kite (`kiteconnect`) | Paid API — ₹200/month subscription for API access. Replaced by Angel One SmartAPI (free). Architecture unchanged. |
| Fyers / Upstox | Not evaluated — Angel One chosen as free broker. Revisit only if Angel One has reliability issues post-Phase 9. |
| NSE unofficial scrapers | Fragile, ToS violation risk |
| Paid Bloomberg / Refinitiv | Out of scope |

---

## 6. ML Model Strategy

### Why Hybrid (XGBoost + LSTM)

- **XGBoost:** Tabular features — TA indicators, volume, macro, FII flows, F&O PCR. Fast. Interpretable via SHAP. Every prediction explainable.
- **LSTM:** Sequential temporal patterns — last N candles as a pattern, not isolated values.
- **Ensemble:** Weighted combination calibrated by uncertainty score. Weights updated by rolling performance.
- **Key rule:** Separate model weights per market. US model is never used for India signals.

### Model Training Rules

| Rule | Value |
|---|---|
| Minimum training data | 2 years of daily bars per market |
| Train/validation/test split | 60% / 20% / 20% |
| Validation method | Walk-forward only — no exceptions |
| Retraining trigger | Drift detected OR monthly scheduled |
| Maximum Sharpe in backtest | 3.0 — above this is overfitted, auto-rejected |
| Feature count | Start ≤ 20 per market; expand cautiously |
| Model sharing | Prohibited — separate weights per market, always |

### Feature Categories — US Equities

1. Price: OHLCV, 1d/5d/20d/60d returns, log returns
2. Momentum: RSI(14), MACD(12/26/9), Rate of Change
3. Trend: EMA crossovers (20/50/200), ADX, Bollinger Band position
4. Volume: OBV, Volume/SMA ratio, VWAP deviation
5. Volatility: ATR(14), historical vol (20d), VIX level
6. Regime: US regime label
7. Macro (Phase 3+): Fed Funds Rate, CPI, GDP growth

### Feature Categories — India Equities

1. Price: OHLCV, 1d/5d/20d/60d returns, log returns
2. Momentum: RSI(14), MACD(12/26/9), Rate of Change
3. Trend: EMA crossovers (20/50/200), ADX, Bollinger Band position
4. Volume: OBV, Volume/SMA ratio, delivery volume %
5. Volatility: ATR(14), India VIX, historical vol (20d)
6. Institutional: FII net buy/sell (daily), DII net buy/sell (daily)
7. Regime: India regime label
8. Macro (Phase 3+): RBI repo rate, CPI, IIP

### Feature Categories — NSE F&O

1. All India equity features for the underlying
2. PCR — overall and strike-specific
3. Open Interest — calls vs puts, OI change
4. IV Rank (current IV vs 52-week range)
5. IV Percentile
6. Term structure (near-month vs far-month IV spread)
7. Greeks: Delta, Gamma, Theta, Vega of position
8. Max Pain strike
9. Days to expiry

---

## 7. Risk Management Rules — Non-Negotiable

These rules have veto power over every other system component. ML, strategies, and regime detectors do not override them. Nothing does.

### US Equities — Position-Level

| Rule | Value | Reason |
|---|---|---|
| Max risk per trade | 1.5% of US portfolio allocation | Quarter-Kelly, survivable losing streak |
| Sizing method | ATR-adjusted fractional Kelly | Adapts to volatility |
| Stop-loss | ATR-based, set before entry | No exceptions |
| Max single position | 10% of US allocation | Concentration limit |

### India Equities — Position-Level

| Rule | Value | Reason |
|---|---|---|
| Max risk per trade | 1.5% of India portfolio allocation | Same Kelly logic |
| Sizing method | ATR-adjusted fractional Kelly | |
| Stop-loss | ATR-based, set before entry | No exceptions |
| Max single position | 10% of India allocation | Concentration limit |
| Circuit breaker check | System checks NSE upper/lower circuit limits before entry | Stocks at circuit limits cannot be exited normally — this is a liquidity trap |

### NSE F&O — Position-Level (Stricter Than Equities)

| Rule | Value | Reason |
|---|---|---|
| Max risk per F&O trade | 1.0% of total portfolio | Leverage amplifies losses — tighter cap required |
| Sizing | Lot-size aware, margin-adjusted | F&O trades in lots (e.g., Nifty lot = 25 units). Size must respect lot constraints. |
| Max net portfolio Delta | ±0.30 | Prevents excessive directional exposure from accumulated options |
| Theta monitoring | Alert if Theta decay > 0.5% portfolio/day | Time decay is a silent killer in long options positions |
| No naked short options | Permanently | Unlimited loss potential. Non-negotiable. |
| Expiry week rule | Reduce all F&O positions by 50% in expiry week unless actively managed | Gamma risk spikes dramatically near expiry |
| Max simultaneous F&O positions | 3 | F&O requires active monitoring — more than 3 is unmanageable |

### Cross-Market Portfolio Rules

| Rule | Value | Reason |
|---|---|---|
| Total deployment cap | Max 40% of total portfolio at any time | 60% always liquid across all markets combined |
| Per-market allocation | US Equity: 40% / India Equity: 40% / India F&O: 20% / Crypto (Phase 8): 20% | No single market dominates |
| Max correlated positions per market | 4 simultaneously | Prevents cluster risk within a market |
| Correlation threshold | > 0.7 treated as same bet | Sector clustering guard |
| Cash reserve per market | Minimum 20% of that market's allocation | Liquidity buffer |
| Currency | India INR, US USD — reported separately, not mixed in P&L | Cross-currency hedging deferred |

### Circuit Breakers

| Trigger | Action | Reset |
|---|---|---|
| Drawdown > -15% in any single market | Halt that market only | Manual review |
| Total portfolio drawdown > -20% | Full system halt, all markets | Manual review required |
| Data feed failure > 5 min (any market) | Stop new orders for that market | Feed restored + validated |
| 3 consecutive anomalous signals | Pause strategy + alert | Engineer reviews logs |
| API auth failure (any broker) | Halt that market + alert | Credentials verified |
| Kite session token expired + renewal failed | Halt India trading + alert | Token renewed and confirmed |
| Rolling 30-day Sharpe < 0.5 (any market) | Alert + strategy review | Strategy passes review |
| NSE circuit breaker on open position | Emergency alert, manual decision | Human decides |

### Kill Switch

```
python kill.py --market us          # halt US only
python kill.py --market india       # halt India equity + F&O
python kill.py --market crypto      # halt crypto only
python kill.py --market all --confirm  # halt everything
```

Tested every week during paper trading phase.

---

## 8. Backtesting Integrity Rules

### Rule 1 — No Lookahead Bias

Every data point used in a backtest must have a timestamp strictly older than the decision moment. Enforced in code, not by convention. Timestamp validation runs on every signal before it is acted on.

### Rule 2 — No Survivorship Bias

- US: Universe includes delisted NYSE/NASDAQ tickers from the test period
- India: Universe includes companies removed from Nifty 50/500 during the test period and delisted NSE/BSE stocks
- Never test on today's index composition going back in time

### Rule 3 — Transaction Costs Always Included

**US per trade:** Commission $0.005/share + slippage 0.05% + spread 0.02%

**India Equity per trade:**
- Brokerage: ₹20 flat
- STT: 0.1% on buy+sell (delivery), 0.025% sell side (intraday)
- NSE exchange charges: 0.00345%
- GST: 18% on brokerage + exchange charges
- SEBI charges: ₹10 per crore
- Slippage: 0.05% (higher for mid/small cap)

**NSE F&O per trade:**
- Brokerage: ₹20 flat
- STT: 0.0625% on sell side (options premium)
- NSE F&O exchange charges: 0.053%
- GST: 18% on brokerage + exchange charges
- Slippage: 0.05% on premium

Gross profit is never reported. Only net after ALL costs.

### Rule 4 — Walk-Forward Validation Only

No strategy validated on data it was trained on. Rolling windows only — train on past, validate on unseen future. This is the only acceptable validation method.

### Rule 5 — Overfitting Detection

| Metric | Threshold | Action |
|---|---|---|
| Sharpe ratio | > 3.0 | Auto-reject |
| Profit factor | > 3.0 | Flag for manual review |
| Win rate | > 80% | Flag as suspicious |
| In-sample vs out-of-sample Sharpe gap | > 1.0 | Auto-reject |

### Rule 6 — F&O Backtesting Specific

- Must use historical option chain data (IV, OI, Greeks) — not synthetic Black-Scholes pricing applied to spot prices
- Must simulate realistic assignment and expiry
- Must account for liquidity — far OTM options cannot be assumed to fill at mid-price
- Must model the bid-ask spread on options premium (typically 2–5% of premium for liquid strikes)

---

## 9. Build Phases — Full Lifetime Roadmap

### Phase 0 — Foundation (Week 1–2)

**What:** Project structure, environments for all markets, per-market config, logging, audit trail, kill switch (per-market), health monitor
**Exit Criteria:** System boots, logs, reads per-market config, kill switch works independently per market.

### Phase 1 — Parallel Data Pipelines (Week 3–6)

**What:** Alpaca fetcher (US) + Kite fetcher (India equity + F&O) running in parallel. Data validators for all markets. Basic feature engineering. SQLite feature store.
**Critical:** Kite TOTP auto-renewal must be working and tested before Phase 1 exits. The India pipeline is unusable without it. NSE F&O chain fetching must be tested with real Kite credentials.
**Market hours note:** India market runs 9:15–15:30 IST. US runs 20:00–02:30 IST (next day). They do NOT overlap. The system handles both independently on the same machine without conflict — each market's scheduler runs on its own clock.
**Exit Criteria:** 2 years of clean daily bars for S&P 500 AND Nifty 500 stored and queryable. F&O chain data fetching confirmed working with live Kite connection.

### Phase 2 — Strategy Pool + Backtesting Engine (Week 7–11)

**What:** 5 US equity strategies + 5 India equity strategies + 3 F&O strategies (defined-risk only). Full backtesting engine with all integrity rules and market-specific transaction costs. vectorbt for parameter sweeps.
**Exit Criteria:**
- US: 2 strategies, Sharpe 1.0–2.0, walk-forward validated
- India Equity: 2 strategies, Sharpe 1.0–2.0, walk-forward validated
- F&O: 1 strategy, Sharpe 0.8–1.5, walk-forward validated with real option chain data

### Phase 3 — Regime Detection (Week 12–14)

**What:** US regime classifier (VIX + SPX). India regime classifier (India VIX + Nifty + FII flow). Two separate models.
**Exit Criteria:** Both classifiers > 70% accuracy on out-of-sample historical data for their respective markets.

### Phase 4 — ML Ensemble (Week 15–22)

**What:** XGBoost + LSTM trained separately per market (US Equity model, India Equity model, F&O model). SHAP explainability. Uncertainty scorer.
**Note:** Minimum 3 months of clean data per market required as training input. Cannot be rushed.
**Exit Criteria:** Hybrid ensemble improves Sharpe by > 10% over rule-based baseline on out-of-sample data, for each market independently.

### Phase 5 — Risk Engine (Week 23–25)

**What:** US position sizer. India equity sizer. F&O position sizer (lot-aware, Greeks-aware). Cross-market portfolio allocator. Drawdown guardian (per-market + total). Real-time risk reporter.
**Exit Criteria:** Risk engine blocks all over-sized positions in 100% of test cases across all three market types including F&O lot-size constraints.

### Phase 6 — Paper Trading Engine (Week 26–30)

**What:** Live Alpaca paper (US). AAATS internal paper simulation for India (live Kite data, simulated fills). Kite live paper for F&O via internal simulator. Order manager unified across all markets. FastAPI backend for real-time data serving.
**Exit Criteria:** System runs continuously 30 days without crashing. Both US and India trading simultaneously. All logs clean. Kite token auto-renewal tested for 30 consecutive days.

### Phase 7 — Learning Loop (Month 8–9)

**What:** Performance tracker per market. Drift detector per market. Retrainer per market independently. Strategy graveyard.
**Exit Criteria:** System detects simulated drift and triggers per-market retraining independently without affecting other markets.

### Phase 8 — Crypto Layer (Month 10+)

**What:** CoinGecko pipeline. CCXT execution. Crypto strategies. Separate risk parameters (1.0% max per trade, not 1.5%).
**Prerequisite:** Paper trading equity curves stable 3+ months in BOTH US and India markets. Core engine proven.

### Phase 9 — Production Live Trading (Month 12–15)

**What:** Real capital. Small initial allocation. Daily human monitoring.
**Prerequisite:** Paper trading Sharpe > 1.0 sustained 6 months, per market independently.
**Sequencing:** Go live one market at a time. Recommended order: US equity first (Alpaca paper mode is most reliable), then India equity, then F&O last. F&O live trading requires demonstrated India equity profitability first.

---

## 10. Layer-by-Layer Module Reference

### Layer 0: Foundation

**Config Manager**
Reads from `.env`. Pydantic v2 validates types at startup. Fails loudly on missing keys.
Sections: `[system]`, `[us]`, `[india_equity]`, `[india_fo]`, `[crypto]`

**Structured Logger**
Loguru. JSON output. Every entry: timestamp, market, module, function, message, context dict.
Separate log files per market per module. Daily rotation, 90-day retention.

**Immutable Audit Trail**
Append-only SQLite table. Fields: timestamp, market, signal, regime, risk_check, order_placed, order_rejected, reason, sha256_hash.
No UPDATE or DELETE ever. Hashed for tamper detection.

**Kill Switch**
Per-market and global halt. Cancels open orders, logs halt with reason. Auto-triggers on drawdown thresholds or feed failure. Manual reset required.

**Health Monitor**
Every 5 minutes: Alpaca API status, Kite API status + token validity, data freshness per market, model inference latency, disk space, memory usage. Telegram alert on any failure.

### Layer 1: Data Pipeline

**Angel Token Manager**
Runs daily before market open (8:00 AM IST). Uses `pyotp` to generate TOTP and complete Angel One SmartAPI login programmatically. Validates new session token. If renewal fails: halt India module + Telegram alert + log to audit trail. This module is tested daily during paper phase.

**India Data Validator — Special Checks**
- Validates against NSE circuit limits (5%/10%/20% circuit breakers)
- Flags stocks at upper/lower circuit — these cannot be entered or exited normally
- F&O validator: checks lot size integrity, IV > 0, OI > minimum liquidity threshold (rejects illiquid strikes)

**F&O Feature Engineering**
- PCR: sum(Put OI across all strikes) / sum(Call OI across all strikes)
- IV Rank: (current IV - 52w low IV) / (52w high IV - 52w low IV) × 100
- Max Pain: strike where total option sellers (call writers + put writers) lose minimum
- Greeks: calculated via `mibian` Black-Scholes for each open position

### Layer 2: Intelligence

**Regime Detectors**

US Regime (4 states):
1. Bull Trend: SPX above 200d MA, ADX > 25, VIX < 20
2. Bear Trend: SPX below 200d MA, ADX > 25, VIX > 25
3. Sideways: ADX < 20, price range-bound around 200d MA
4. High Volatility: VIX > 30, ATR expansion, unclear direction

India Regime (4 states):
1. Bull Trend: Nifty above 200d MA, ADX > 25, India VIX < 15, FII net buyers
2. Bear Trend: Nifty below 200d MA, ADX > 25, India VIX > 20, FII net sellers
3. Sideways: ADX < 20, range-bound
4. High Volatility: India VIX > 22, ATR expansion, PCR at extremes

**Strategy Pools**

US Equity (Phase 2):
1. Momentum — EMA crossover + volume confirmation
2. Mean Reversion — Bollinger Band extremes + RSI divergence
3. Trend Following — ADX + MACD alignment
4. Breakout — 52-week high/low + volume
5. Sector Rotation — relative strength between S&P sectors

India Equity (Phase 2):
1. Momentum — EMA crossover + volume + FII net buy confirmation
2. Mean Reversion — Bollinger Band extremes + RSI
3. Trend Following — ADX + MACD
4. Breakout — 52-week high/low + delivery volume confirmation
5. Index Rotation — Nifty large cap vs mid cap relative strength

NSE F&O (Phase 2 — defined-risk strategies only):
1. Short Strangle — sell OTM call + put when IV Rank > 70%, hedged
2. Bull Call Spread — defined-risk directional play in bull regime
3. Bear Put Spread — defined-risk directional play in bear regime

No naked shorts. No undefined-risk strategies. Ever.

### Layer 3: Validation Gates

All signals from all markets pass through all applicable gates. One failed gate = signal rejected.

| Gate | Check | Action |
|---|---|---|
| Timestamp Gate | Signal uses only past-timestamped data | Hard reject + audit log |
| Overfitting Gate | Strategy Sharpe ≤ 3.0 | Hard reject |
| Cost Gate | Net profit after market-specific costs > 0 | Reject |
| Walk-Forward Gate | Validated on unseen data only | Reject |
| Liquidity Gate | Position size vs ADV < 1% | Reject illiquid signals |
| F&O Greeks Gate | Net Delta within limits, Theta acceptable | Reject F&O signal |
| Circuit Limit Gate | Stock not at NSE circuit limit | Reject India signal |

### Layer 6: Execution

**Kite Engine — India**
Paper mode: AAATS internal simulator using live Kite market data. Simulates fills at best bid/ask. Models 100–300ms execution latency.
Live mode: `kite.place_order()` for equity. `kite.place_order(variety='bo')` for bracket orders. F&O: instrument token + lot quantity specified explicitly.
Partial fills: lot-size aware — if 2.5 lots filled, rounds down to 2.

**Order Manager (Unified)**
All orders tagged: market, strategy, regime at time of signal, signal confidence.
Max simultaneous open orders: 10 US equity + 5 India equity + 3 F&O.

### Layer 8: Observability

**Streamlit Dashboard Pages:**
1. System Health — all API statuses, Angel One token expiry countdown, data freshness per market
2. Portfolio Overview — combined equity curve, total P&L in USD and INR
3. US Market — equity curve, positions, signals, regime, sector breakdown
4. India Equity — equity curve, positions, signals, regime, FII/DII flow
5. India F&O — open positions, Greeks exposure, PCR dashboard, IV rank
6. Risk — cross-market exposure, drawdowns, position sizes
7. Performance — strategy breakdown per market, Sharpe history

**Telegram Bot — Market-Tagged:**
`[US]` / `[INDIA-EQ]` / `[INDIA-FO]` / `[CRYPTO]` prefix on every alert.
Events: trade opened/closed, kill switch triggered, drawdown threshold hit, Angel One token renewal failure, NSE circuit breaker on open position, retraining triggered, strategy retired.

---

## 11. The 3 Rules That Cannot Be Broken

**Rule 1: No strategy deploys without 2+ years of walk-forward validated backtest data.**
One good month is noise. Two years across different regimes is signal. Applies to every strategy in every market.

**Rule 2: Risk engine has veto power over everything.**
ML says buy. Risk engine says no. We don't buy. No exception. No override path in code. Applies equally to US equity, India equity, and F&O.

**Rule 3: Paper trade minimum 3 months before real capital, per market independently.**
US and India paper trading clocks are separate. Going live in US does not authorize going live in India. F&O live trading requires India equity live trading to be profitable first. Each market earns its live trading rights on its own evidence.

---

## 12. Deferred Decisions Log

| Item | Deferred To | Reason |
|---|---|---|
| FastAPI + asyncio backend | Phase 6 | Not needed until live real-time data at scale |
| React frontend | Phase 9+ | Streamlit sufficient through live trading |
| PostgreSQL + TimescaleDB | Phase 4 | SQLite handles Phase 1–3 volume |
| Crypto trading | Phase 8 | Equity engine must be proven in both markets first |
| Real capital | Phase 9 | 3 months paper per market, per the rules |
| Currency hedging INR/USD | Post-Phase 9 | Complexity not justified at current scale |
| Multi-exchange routing (crypto) | Post-Phase 8 | Single exchange sufficient to start |
| BSE-specific strategies | Phase 9+ | NSE is the primary liquid market; BSE adds complexity with marginal liquidity benefit |
| Advanced options strategies (condors, calendars) | Post-Phase 9 | Defined-risk basics must be profitable first |
| Live F&O automation | Phase 9, after India equity live | F&O paper must prove Sharpe > 0.8 and India equity must be live-profitable first |

---

## 13. Rejected Ideas Log

| Item | Status | Reason |
|---|---|---|
| "Maximum profit, minimal loss" as design target | Permanently rejected | Mathematically impossible |
| Shared ML model weights across markets | Permanently rejected | US and India have fundamentally different data distributions, volatility profiles, and institutional behaviour. One model for both is worse than two separate models. |
| Naked short options in F&O | Permanently rejected | Unlimited loss potential. A systematic system cannot hold undefined-risk positions. |
| Zerodha Kite as India broker | Rejected (v3.1) | ₹200/month API subscription fee. Replaced by Angel One SmartAPI which is free and feature-equivalent. Owner decision April 2026. |
| Fyers / Upstox as India broker | Rejected | Angel One chosen. Revisit only if Angel One has persistent reliability issues post-Phase 9. |
| Full Kelly position sizing | Permanently rejected | -61.5% drawdown at 5% risk destroys accounts psychologically and financially |
| yfinance | Permanently rejected | Web scraping, unreliable, not production-grade |
| IEX Cloud | Permanently rejected | Shut down August 2024 |
| Autonomous self-learning without human oversight | Permanently rejected | Model can learn bad behaviors; human review gates required |
| React dashboard before Phase 9 | Rejected | Building UI before working engine is procrastination |
| BSE as primary market | Rejected | NSE has superior liquidity for most instruments. BSE used only where NSE is unavailable. |
| Trading Indian crypto (WazirX/CoinDCX) | Rejected | Indian crypto regulation is unstable. Global crypto via CCXT in Phase 8 is cleaner. |

---

## 14. Performance Targets

### Paper Trading Exit Criteria (Per Market, Before Real Capital)

| Metric | US Equity | India Equity | NSE F&O |
|---|---|---|---|
| Minimum duration | 3 months | 3 months | 3 months |
| Sharpe ratio | > 1.0 sustained | > 1.0 sustained | > 0.8 sustained |
| Max drawdown | < -20% | < -20% | < -25% |
| Win rate | > 50% | > 50% | > 45% |
| Backtest vs live Sharpe gap | < 30% | < 30% | < 30% |
| System uptime | > 95% | > 95% | > 95% |
| Critical errors | Zero | Zero | Zero |
| Angel One token renewals | N/A | 100% success | 100% success |

### Live Trading Success Criteria (6-month evaluation)

| Metric | US Equity | India Equity | NSE F&O |
|---|---|---|---|
| Annual return (annualized) | > 15% | > 12% | > 20% |
| Sharpe ratio | > 1.0 | > 1.0 | > 0.8 |
| Max drawdown | < -20% | < -20% | < -25% |
| Profit factor | > 1.3 | > 1.3 | > 1.2 |
| Win rate | > 52% | > 52% | > 45% |

---

## 15. Decision Change Protocol

Any change to architecture, risk rules, or technology decisions requires:

1. Written justification — why the current design is wrong
2. Research backing — at least one external source
3. Impact assessment — what does this change break or improve
4. Owner sign-off — Puneeth reviews and approves

Changes made without this protocol are invalid and revert to this document.

### Change Log

| Version | Date | Decision Changed | Justification | Research | Impact | Owner Sign-off |
|---|---|---|---|---|---|---|
| v3.1 | April 2026 | India broker: Zerodha Kite → Angel One SmartAPI | Zerodha Kite charges ₹200/month for API access. Angel One SmartAPI is free with a demat account. | Angel One SmartAPI official docs: smartapi.angelbroking.com. Equivalent features: historical OHLCV (5yr daily), option chain, OI, WebSocket, TOTP auth. | Only `markets/india/` modules change. Architecture, risk rules, feature engineering, and all other layers are unaffected. `kiteconnect` replaced with `smartapi-python` in requirements. | Puneeth — April 2026 |

---

## 16. Prompting Guidelines

This document can be given to Claude (via MASTER_AUTODRIVER.md) to auto-build AAATS. These guidelines ensure Claude understands the context, constraints, and expectations.

### Core Prompting Rules for AAATS Work

**Rule 1: Specificity is non-negotiable.**

When asking Claude to build or fix something, include:
- **What:** The exact module/file (e.g., "markets/india/token_manager.py")
- **Why:** The architectural intent (e.g., "Daily Angel One session renewal via TOTP. Must not fail silently.")
- **Constraints:** Risk rules, library choices, interface requirements (e.g., "SmartConnect injected via constructor. All tests mocked.")
- **Success criteria:** How Claude knows it's done (e.g., "10 tests pass, all edge cases covered, no real API calls")

**Bad example:**
> "Build the India token manager thing."

**Good example:**
> "Build markets/india/token_manager.py per MASTER_AUTODRIVER.md spec. This module auto-renews Angel One SmartAPI session tokens daily via TOTP (pyotp). Must have these methods: renew_session(), get_auth_token(), is_token_valid(). SmartConnect is injected — tests never call real API. If renewal fails, halt India trading + log to audit trail + alert. Write 7 tests covering success, TOTP generation, failure paths, and token caching."

**Rule 2: Provide examples, especially for edge cases.**

Claude learns from patterns. Show it:
- Input/output pairs (e.g., DataFrame in, processed features out)
- Edge cases (empty data, network timeout, malformed response)
- What success looks like in your domain (e.g., "Sharpe ratio between 1.0 and 1.8 is good; >3.0 is a red flag for overfitting")

**Rule 3: Ask for step-by-step reasoning when the task is complex.**

For ML, backtesting, risk math, or multi-stage processes, ask Claude to think through:
- What's the failure mode? (e.g., "How could the backoff logic fail? What if all 6 retries hit network timeouts?")
- What's the interface contract? (e.g., "This function receives a DataFrame with columns X, Y, Z. It must return a DataFrame with exactly these columns: A, B, C. What happens if input is empty?")
- What assumptions are you making? (e.g., "Position sizing assumes ATR > 0. What if ATR is exactly 0?")

**Rule 4: Respect the BUILD ORDER. Don't skip phases.**

If Claude is asked to build Phase 5 (Risk Engine) before Phase 1 (Data Pipeline) is complete, Claude should ask:
> "Phase 1 (US/India fetchers) is not marked complete in MASTER_AUTODRIVER.md. Should I skip to Phase 5 anyway, or build Phase 1 first?"

**Rule 5: Minimize context for simple questions; maximize for complex tasks.**

- **Simple question** ("Should I use scipy or numpy for this?"): Just ask. Claude will ask for context if needed.
- **Build a module**: Give the full MASTER_AUTODRIVER.md. Claude needs all context.
- **Debug a test**: Paste the test, the error, the relevant code. Not the entire codebase.

### Prompting Patterns for AAATS Tasks

#### Pattern 1: Building a Module

```
I'm asking you to build <module_name> per MASTER_AUTODRIVER.md.

Context:
- Current build status: [paste the BUILD STATUS from PRE-BUILD section]
- This module's purpose: [one sentence]
- Key constraints: [list 2–3 non-negotiable rules]

Here's the spec:
[paste the spec from MASTER_AUTODRIVER.md]

Before writing code:
1. Validate the spec against the rules — is anything missing or contradictory?
2. Check: are any libraries stale (>18 months old)? List them.
3. Ask me to confirm before proceeding.

Then build the module, write tests, and report completion per COMPLETION REPORT FORMAT.
```

#### Pattern 2: Debugging a Failing Test

```
I ran pytest and got this failure:

File: <path>
Error: <exact error message>
[paste stderr output]

Code context:
[paste the relevant function, ~20 lines]

Expected behavior: <what should happen>
Actual behavior: <what did happen>

Possible causes I've ruled out: [if any]

What's wrong? Suggest a fix and explain the root cause.
```

#### Pattern 3: Refactoring for Performance

```
Module: <path>
Current performance: <metric — e.g., "10s per symbol, 1M bars">
Target performance: <metric — e.g., "< 1s per symbol">

Current approach: [brief description or code]

Constraints:
- Must not change the function signature
- Tests must still pass
- No new dependencies

What's the best approach? Vectorize? Use apply()? Something else?
Show me a working example for [one specific indicator]. I'll adapt it to the others.
```

#### Pattern 4: Validating a Backtest

```
I backtested <strategy> on <market> from <date> to <date>.

Results:
- Sharpe: <X>
- Max drawdown: <Y>%
- Win rate: <Z>%
- Profit factor: <PF>

Is this realistic or overfitted?

Here's what concerns me: [specific observation]

Full backtest output: [paste or link]
```

### Anti-Patterns: What NOT to Do

| Anti-Pattern | Why It Fails | What to Do |
|---|---|---|
| "Build everything" (no spec) | Claude invents requirements; risk rules unclear | Give the spec first. One module per session. |
| "Optimize this code." (vague) | "Better" means nothing | Say: "Reduce latency to <X>" or "Fix this bug" |
| "Make the ML model better." | No target → Claude guesses | Specify: "Improve Sharpe from 1.0 to 1.5" |
| Load entire AAATS repo for one question | Wastes tokens; slow response | Ask focused question with minimal context |
| Override BUILD ORDER without asking | Breaks dependencies; untested | Always ask Puneeth. Then ask Claude to build. |
| "Can you just try X?" in backtesting | No validation criteria | Specify: "Test on 2 years walk-forward. Sharpe must be [target]" |

### How Claude Should Respond

When Claude builds a module, it should:

1. **Ask clarifying questions.** If the spec is ambiguous, say so explicitly.
2. **Validate before coding.** Run PRE-BUILD VALIDATION. Flag stale libraries, missing error handling, interface misalignment.
3. **Build with confidence.** Once validated, code cleanly, test thoroughly.
4. **Report honestly.** If deviations from spec were necessary, explain why. Flag issues in FLAGGED_ISSUES.md.
5. **Stop at completion.** Report the completion summary and STOP. Don't auto-continue to the next module.

### Example: From Prompt to Completion

**Prompt (from Puneeth to Claude):**
```
Build markets/india/token_manager.py per MASTER_AUTODRIVER.md.

Current status: Phase 0 foundation is done. Phase 1 begins here.
Module purpose: Daily Angel One SmartAPI session renewal via TOTP.

Before you write code:
1. Validate the spec — anything missing?
2. Check if smartapi-python 1.5.5 is still the best choice (it's what the spec names).
3. List any assumptions you're making about the Config object and AuditTrail API.
4. Confirm you're ready to build.
```

**Claude's Response (before coding):**
```
Pre-Build Validation:

1. Spec review: [spec looks complete. Interface is clear.]
2. Library check: smartapi-python 1.5.5 last released [date]. Status: actively maintained.
3. Assumptions:
   - Config object has config.india.ANGEL_CLIENT_ID, config.india.ANGEL_PIN, config.india.ANGEL_TOTP_SECRET
   - AuditTrail has .log(event_type, market, ...) method
   - kill_switch.halt(market="india") exists and stops trading
4. Ready to build. Proceeding...

[builds module + tests]

[reports completion per COMPLETION REPORT FORMAT]
```

---

*Document version: 3.1 | Status: Owner-Approved | Markets: US Equity + India Equity (NSE/BSE) + NSE F&O + Crypto (Phase 8) | Next review: After Phase 1 completion*

### [2026-04-26] — [HOTFIX] Session: markets/us/fetcher.py
- Built: markets/us/fetcher.py (hotfix verification)
- Tests: 6 passed, 0 failed
- Deviations from original spec: none — code was already correct, using alpaca-py SDK as specified
- Flags raised: BLUEPRINT.md still referenced alpaca-trade-api (stale doc); corrected in same session — RESOLVED
- Libraries used: alpaca-py (StockHistoricalDataClient, StockDataStream, StockBarsRequest, TimeFrame)
- Approved by: Puneeth

### [2026-04-26] — Session: markets/us/feature_engineer.py
- Built: markets/us/feature_engineer.py + tests/test_us/test_us_features.py
- Tests: 6 passed, 0 failed
- Deviations from original spec: none — spec says "identical API" for pandas-ta-classic; confirmed import is `pandas_ta_classic` (not `pandas_ta`), function-based API identical in practice
- Flags raised: none
- Libraries used: pandas-ta-classic 0.4.47, numpy
- Approved by: Puneeth

### [2026-04-27] — Session: markets/us/storage.py
- Built: markets/us/storage.py + tests/test_us/test_us_storage.py
- Tests: 6 passed, 0 failed
- Deviations from original spec: none — timestamps stored as UTC ISO-8601 strings for portable lexicographic ordering in SQLite
- Flags raised: [NEEDS_REVIEW] SQLite correct for write/point-lookup; DuckDB analytics layer needed in Phase 2 for backtesting cross-symbol queries — tracked in FLAGGED_ISSUES.md
- Libraries used: SQLAlchemy 2.0.49, SQLite (stdlib)
- Approved by: Puneeth

### [2026-04-27] — Session: risk/us/position_sizer.py
- Built: risk/us/position_sizer.py + tests/test_risk/test_us_position_sizer.py
- Tests: 8 passed, 0 failed
- Deviations from original spec: test_normal_sizing spec says ATR=2.0, price=100, portfolio=100000 → approved=True. Those parameters produce position_pct=37.5% which exceeds MAX_POSITION_PCT (10%) and would be rejected. Corrected to ATR=10.0 (position_pct=7.5%) to match the spec's stated intention (approved=True). Original spec values documented in test docstring. Flagged in FLAGGED_ISSUES.md as RESOLVED.
- Flags raised: [RESOLVED] Spec test_normal_sizing ATR parameter produced internally inconsistent outcome — corrected in test.
- Libraries used: numpy 2.x (scipy dependency, used for np.isfinite() guards on Kelly intermediate values); scipy 1.17.1 listed in requirements.in
- Approved by: Puneeth

### [2026-04-27] — Session: risk/us/drawdown_guardian.py
- Built: risk/us/drawdown_guardian.py + tests/test_risk/test_us_drawdown_guardian.py
- Tests: 6 passed, 0 failed
- Deviations from original spec: none — both MARKET_DRAWDOWN_HALT_PCT (-15%) and TOTAL_DRAWDOWN_HALT_PCT (-20%) defined as constants; threshold is selected at init based on market parameter ("all" → TOTAL, otherwise → MARKET). Spec only mentions MARKET_DRAWDOWN_HALT_PCT in the logic block; use of both constants is the correct interpretation of the Blueprint circuit-breaker intent.
- Flags raised: [NEEDS_REVIEW] In-memory peak state lost on process restart; Phase 2 trading loop wiring must seed DrawdownGuardian with persisted peak value — tracked in FLAGGED_ISSUES.md.
- Libraries used: stdlib only (dataclasses); foundation.kill_switch, foundation.logger
- Approved by: Puneeth


### [2026-04-27] — Session: backtesting/engine.py
- Built: backtesting/engine.py + tests/test_backtesting/test_engine.py
- Tests: 7 passed, 0 failed
- Deviations from original spec: none — all 4 Blueprint Section 8 integrity rules enforced: timestamp gate (sort + single-row pass to strategy_fn), overfitting gate (Sharpe>3.0 → approved=False), cost gate (slippage+spread+commission applied to every trade), walk-forward gate (non-empty check; caller owns train/test split). Single-leg long model (one position at a time) — spec does not specify multi-leg so simplest correct model used.
- Flags raised: [NEEDS_REVIEW] iterrows() performance acceptable for daily bars, bottleneck at tick/sweep scale. [NEEDS_REVIEW] profit_factor=inf when no losing trades; downstream must guard. [NEEDS_REVIEW] Bar-level Sharpe spikes on small sparse-trade datasets; overfitting gate catches it, callers must check result.approved.
- Libraries used: pandas 3.0.2, numpy 2.4.4, stdlib (math, dataclasses, typing); risk.us.position_sizer, foundation.logger
- Approved by: Puneeth


### [2026-04-27] — Session: backtesting/validators.py
- Built: backtesting/validators.py + tests/test_backtesting/test_validators.py
- Tests: 14 passed, 0 failed
- Deviations from original spec: none — all 3 functions implemented as specified. check_lookahead_bias uses a window-level check (no features at or before signal time → violation), which is the strongest static check possible without an execution trace. check_overfitting explicitly guards against float('inf') profit_factor per the engine.py FLAGGED_ISSUES.md note. validate_walk_forward_split uses strict > (not >=) so equal timestamps are correctly rejected.
- Flags raised: none — engine.py profit_factor=inf issue addressed here (FLAGGED_ISSUES.md status updated to "handled in validators.py"). Phase 4 India pipeline BLOCKED — Angel One API approval pending.
- Libraries used: pandas 3.0.2, stdlib (math, dataclasses); backtesting.engine.BacktestResult, foundation.logger
- Approved by: Puneeth

### [2026-04-27] — Session: markets/india/token_manager.py
- Built: markets/india/token_manager.py + tests/test_india/test_token_manager.py
- Tests: 10 passed, 0 failed
- Mock status: FULL_MOCK — SmartConnect injected via constructor; AuditTrail and halt patched in all tests; zero real API calls
- Deviations from spec: Added extra test (test_kill_switch_and_alert_called_on_exception) beyond the 7 required to cover the exception-path explicitly — strengthens coverage without deviating from spec intent. Config attribute paths use config.india.* (Pydantic nested model) as-built, not the flat ANGEL_CLIENT_ID style used in spec pseudocode.
- Flags raised: none
- Libraries used: smartapi-python 1.5.5, pyotp 2.9.0, pytz 2025.2, foundation.kill_switch, foundation.audit_trail, foundation.logger
- Approved by: Puneeth

### [2026-04-27] — Session: markets/india/fetcher.py
- Built: markets/india/fetcher.py + tests/test_india/test_fetcher.py
- Tests: 7 passed, 0 failed
- Mock status: FULL_MOCK — getCandleData called on injected smart_client; SmartWebSocketV2 patched at module level; AuditTrail and halt patched; zero real API calls
- Deviations from spec: Added test_empty_data_returns_empty_dataframe (7th test, spec listed 6) for empty API response edge case. SmartWebSocketV2 callbacks are set as instance attributes (sws.on_data = fn) rather than passed to connect() — matches the actual smartapi-python 1.5.5 API (connect() takes no args). Import path is SmartApi.smartWebSocketV2 (lowercase module name) not SmartApi.SmartWebSocketV2. Installed logzero and websocket-client as transitive dependencies of smartapi-python.
- Flags raised: none
- Libraries used: smartapi-python 1.5.5 (SmartWebSocketV2), pandas 2.3.3, pytz 2025.2, concurrent.futures (stdlib timeout), foundation.kill_switch, foundation.audit_trail, foundation.logger
- Approved by: Puneeth

### [2026-04-28] — Session: markets/india/fo_fetcher.py
- Built: markets/india/fo_fetcher.py + tests/test_india/test_fo_fetcher.py
- Tests: 8 passed, 0 failed
- Mock status: FULL_MOCK — getMarketData and getCandleData called on injected smart_client; AuditTrail and halt patched; zero real API calls
- Deviations from spec: Added test_empty_fetched_list_returns_empty_dataframe (5th option-chain test, spec listed 6 for the module total) for empty API response edge case. IV<=0 rows are both filtered from output AND individually audit-logged with event_type=REJECTION — spec says "IV > 0 for all returned rows (or row is rejected)"; both conditions are enforced simultaneously. Strike parsed from tradingSymbol via regex as fallback when strikePrice field absent.
- Flags raised: none
- Libraries used: smartapi-python 1.5.5, pandas 2.3.3, pytz 2025.2, re (stdlib), concurrent.futures (stdlib timeout), foundation.kill_switch, foundation.audit_trail, foundation.logger
- Approved by: Puneeth

### [2026-04-28] — Session: markets/india/validator.py
- Built: markets/india/validator.py + tests/test_india/test_validator.py
- Tests: 10 passed, 0 failed
- Mock status: NO_MOCK_NEEDED (only AuditTrail mocked; no external API calls in this module)
- Deviations from spec: Added _CIRCUIT_EPSILON=1e-9 tolerance on circuit boundary comparisons to handle IEEE 754 floating-point rounding (e.g. 100.0 * 1.10 = 110.00000000000001 in Python, causing a strict >= comparison to fail at the exact boundary). The epsilon is too small to affect any real-world price comparison — this is a correctness fix, not a spec deviation. Config circuit_pct per-symbol read from config.india.circuit_limits dict with fallback to 20% (NSE default band) when attribute absent or misconfigured.
- Flags raised: none
- Libraries used: pandas 2.3.3, numpy (imported transitively via pandas; not used directly), foundation.audit_trail, foundation.logger
- Approved by: Puneeth

### [2026-04-28] — Session: markets/india/fo_validator.py
- Built: markets/india/fo_validator.py + tests/test_india/test_fo_validator.py
- Tests: 13 passed, 0 failed
- Mock status: NO_MOCK_NEEDED (only AuditTrail mocked; no external API calls in this module)
- Deviations from spec: Lot-size check explicitly skips rows where OI==0 (already caught by oi_mask) to prevent duplicate "oi_not_lot_multiple" + "oi_zero" reasons on the same row. All six rejection checks are implemented (IV, OI, bid/ask, lot-size, valid-strikes, far-OTM). Each check is independently togglable via config — lot-size check skipped when lot_size=1; valid-strike check skipped when not configured; far-OTM check skipped when spot_price not available. Added 6 extra tests beyond the 7 required by spec (iv_negative, multiple_rejections, empty_df, no_spot_price, lot_size_violation, strike_not_in_list) for full coverage.
- Flags raised: none
- Libraries used: pandas 2.3.3, foundation.audit_trail, foundation.logger
- Approved by: Puneeth

### [2026-04-28] — Session: markets/india/feature_engineer.py
- Built: markets/india/feature_engineer.py + tests/test_india/test_features.py
- Tests: 7 passed, 0 failed
- Mock status: NO_MOCK_NEEDED — pure pandas/numpy TA; no external API calls
- Deviations from spec: Warmup rows are explicitly retained (not dropped) — spec test 4 requires EMA_200 to be NaN for first 199 bars, confirming this is the correct behaviour for the India engineer (contrast: US engineer drops warmup rows). delivery_pct passthrough: if already a column in the input df it is preserved; otherwise NaN is injected — this is the spec's intent for "if available, else NaN". india_regime column initialised as float NaN; dtype will change to object when Phase 8 fills it with strings — standard pandas behaviour.
- Flags raised: none
- Libraries used: pandas-ta-classic 0.4.47, numpy, foundation.logger
- Approved by: Puneeth

### [2026-04-28] — Session: markets/india/fo_feature_engineer.py
- Built: markets/india/fo_feature_engineer.py + tests/test_india/test_fo_features.py
- Tests: 23 passed, 0 failed
- Mock status: NO_MOCK_NEEDED — pure math + pandas; no external API calls
- Deviations from spec: mibian (spec library for Black-Scholes Greeks) last released 2016-03-12 (10+ years, well beyond 18-month threshold). Also checked py-vollib (2017-04-10) — also stale. Alternative: Black-Scholes formulas implemented directly using scipy.stats.norm (scipy 1.17.1, continuously maintained). Mathematics are identical; no behaviour change. Flagged in FLAGGED_ISSUES.md [2026-04-28] — RESOLVED. compute_greeks also raises ValueError on invalid inputs (option_type not CE/PE, DTE≤0, IV≤0, negative prices) — defensive input validation added beyond spec minimum. 23 tests written vs 8 required by spec (added: empty history, clamp tests, gamma/vega put-call parity, deep ITM/OTM delta boundary tests, invalid input guards).
- Flags raised: mibian stale library — RESOLVED with scipy.stats.norm replacement
- Libraries used: scipy 1.17.1 (scipy.stats.norm), math (stdlib), pandas 2.3.3, foundation.logger
- Approved by: Puneeth
