# AAATS — Autonomous Adaptive AI Trading System

> A production-grade, self-learning AI trading platform for US Equities, Indian Equities (NSE/BSE), NSE F&O, and Crypto. Capital preservation first. Consistent compounding second.

---

## ⚠️ Important Disclaimer

This system is built for **paper trading and systematic research**. It does not guarantee profits. No trading system does. Past backtest performance does not predict future results. Real capital is deployed only after a minimum of 3 months of successful paper trading **per market independently**. NSE F&O involves leverage — positions can lose more than capital deployed. Read the [Master Blueprint](AAATS_MASTER_BLUEPRINT.md) before touching any code.

---

## What This System Does

AAATS is a systematic trading engine that:

- Trades three markets in parallel: US Equities (NYSE/NASDAQ), Indian Equities (NSE/BSE), and NSE Futures & Options — all from a single unified engine
- Detects the current market regime independently for each market (bull/bear/sideways/high-volatility)
- Applies the correct strategy for each regime from a validated, market-specific strategy pool
- Uses an XGBoost + LSTM hybrid ML ensemble — trained separately per market — to score signal quality
- Enforces strict risk rules that cannot be overridden, including F&O-specific Greeks and lot-size constraints
- Papers trades first, learns continuously, and graduates to live trading only when performance benchmarks are met independently per market
- Logs every decision with full explainability via SHAP — you always know why it did what it did
- Sends real-time alerts to your phone via Telegram, market-tagged

---

## What This System Does NOT Do

- It does not print money
- It does not have a 100% win rate
- It does not override its own risk rules
- It does not deploy real capital until 3+ months of paper trading evidence exists, per market
- It does not run naked short options or any undefined-risk F&O strategy

---

## Markets Covered

| Market | Exchange | Broker/Data | Status |
|---|---|---|---|
| US Equities | NYSE / NASDAQ | Alpaca Markets | Active from Phase 1 |
| Indian Equities | NSE / BSE | Angel One SmartAPI | ✅ **Ready for API integration** (as of April 28, 2026) |
| NSE Futures & Options | NSE | Angel One SmartAPI | ✅ **Ready for API integration** (as of April 28, 2026) |
| Crypto | Multi-exchange | CoinGecko + CCXT | Phase 8 only |

---

## Project Status

| Phase | Name | Status |
|---|---|---|
| 0 | Foundation | 🔴 Not Started |
| 1 | Dual Data Pipeline (US + India parallel) | 🔴 Not Started |
| 2 | Strategy Pool + Backtesting Engine | 🔴 Not Started |
| 3 | Regime Detection (US + India separate) | 🔴 Not Started |
| 4 | ML Ensemble (per-market models) | 🔴 Not Started |
| 5 | Risk Engine (equity + F&O rules) | 🔴 Not Started |
| 6 | Paper Trading Engine | 🔴 Not Started |
| 7 | Learning Loop | 🔴 Not Started |
| 8 | Crypto Layer | 🔴 Not Started |
| 9 | Live Trading | 🔴 Not Started |

---

## System Architecture (Overview)

```
[Alpaca: US OHLCV]          [Kite: India OHLCV + F&O Chain]
        ↓                               ↓
[US Validator]              [India Validator + Circuit Check]
        ↓                               ↓
[US Feature Engineer]       [India Feature Eng. + F&O Greeks]
        ↓                               ↓
[US Feature Store]          [India Feature Store]
        ↓                               ↓
[US Regime Detector]        [India Regime Detector]
        ↓                               ↓
[US Strategy Pool + ML]     [India Equity Pool + F&O Pool + ML]
        ↓                               ↓
        └──────────[Validation Gates]───┘
                          ↓
               [Decision Engine (market-tagged)]
                          ↓
        [Risk Manager ← VETO POWER — no override exists]
                          ↓
         [Alpaca Engine]      [Kite Engine (Equity + F&O)]
                          ↓
              [Unified Performance Tracker]
                          ↓
         [Drift Detector → Per-Market Retrainer]
                          ↓
        [Streamlit Dashboard + Telegram Alerts]
```

Full architecture: [AAATS_MASTER_BLUEPRINT.md](AAATS_MASTER_BLUEPRINT.md)

---

## Prerequisites

### Accounts Required

- **Alpaca Markets** account — free, paper trading included (US equities)
- **Zerodha** account with **Kite Connect API** subscription — ₹200/month (Indian equities + F&O)
- **Telegram** account + bot token (for alerts)
- **CoinGecko** free API key (Phase 8 only)

### System Requirements

- Python 3.11 (not 3.12 — ML library compatibility)
- Git
- VS Code (recommended)
- Linux/macOS recommended; Windows supported but WSL2 preferred

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/AAATS.git
cd AAATS

# 2. Create virtual environment
python3.11 -m venv venv

# 3. Activate it
# Mac/Linux:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# 4. Install pip-tools and compile dependencies
pip install pip-tools
pip-compile requirements.in
pip install -r requirements.txt

# 5. Set up environment variables
cp .env.example .env
# Edit .env and fill in all API keys
```

---

## Configuration

### Quick Start: Copy the Template

```bash
cp config/.env.example .env
# Edit .env and fill in your API keys (see below)
```

### US Market (Alpaca)

Alpaca setup is straightforward — get your API keys from [alpaca.markets](https://alpaca.markets).

```env
US__ALPACA_API_KEY=your_key_here
US__ALPACA_SECRET_KEY=your_secret_key_here
US__ALPACA_BASE_URL=https://paper-api.alpaca.markets  # paper mode
US__MAX_RISK_PER_TRADE=0.015       # 1.5% — do not increase
US__MAX_PORTFOLIO_EXPOSURE=0.06    # 6% max open at once
US__DRAWDOWN_HALT=-0.15            # -15% triggers kill switch
```

### India Market (Angel One SmartAPI) — **Now Enabled ✅**

Angel One is **free with a demat account** (no monthly API subscription fee). 

**Setup:** Follow the [Angel One Setup Guide](ANGEL_ONE_SETUP.md) for step-by-step instructions.

**Quick reference:**

```env
INDIA__ANGEL_API_KEY=your_angel_api_key                # From smartapi.angelbroking.com
INDIA__ANGEL_CLIENT_ID=REDACTED_ANGEL_CLIENT_ID                      # Your Angel One login ID
INDIA__ANGEL_PIN=9066                                  # Your 4-digit PIN
INDIA__ANGEL_TOTP_SECRET=JZCRAQDC7SYURTQE5VR5GALAF4  # 2FA backup secret
INDIA__MAX_RISK_PER_TRADE=0.015      # 1.5% equity — do not increase
INDIA__FO_MAX_RISK_PER_TRADE=0.010   # 1.0% F&O — stricter, do not increase
INDIA__DRAWDOWN_HALT=-0.15            # -15% halts India trading
```

**To verify your setup works:**

```bash
# Health check (quick)
pytest tests/test_india/test_angel_one_integration.py::TestAngelOneHealthCheck -v

# Full authentication test (connects to real API)
pytest tests/test_india/test_angel_one_integration.py::TestAngelOneIntegration::test_can_authenticate_and_get_tokens -v -s
```

See [Angel One Setup Guide](ANGEL_ONE_SETUP.md) for full details.

### System & Cross-Market Settings

```env
SYSTEM__TRADING_MODE=paper          # paper | live — never change to live manually
SYSTEM__LOG_LEVEL=INFO
SYSTEM__LOG_RETENTION_DAYS=90
SYSTEM__HEALTH_CHECK_INTERVAL_SECONDS=300

RISK__TOTAL_DRAWDOWN_HALT=-0.20     # -20% total portfolio = full system halt
RISK__MAX_TOTAL_DEPLOYMENT=0.40     # 40% max deployed across all markets
```

### Alerts (Telegram)

```env
ALERTS__TELEGRAM_BOT_TOKEN=your_bot_token
ALERTS__TELEGRAM_CHAT_ID=your_chat_id
```

### Phase 8 Only (Crypto) — Uncomment when ready

```env
# COINGECKO_API_KEY=your_key_here
# CCXT_EXCHANGE=binance
# CCXT_API_KEY=your_key_here
# CCXT_SECRET_KEY=your_key_here
```

**⚠️ Security:** Never commit `.env` to version control. It's in `.gitignore` by default.

---

## Project Structure

```
AAATS/
├── config/
│   ├── settings.py              # Pydantic v2 config models (per-market sections)
│   └── .env.example
│
├── foundation/
│   ├── logger.py                # Loguru structured logging (market-tagged)
│   ├── audit_trail.py           # Immutable, hashed decision log
│   ├── health_monitor.py        # 5-minute health checks across all markets
│   └── kill_switch.py           # Per-market + global halt
│
├── markets/
│   ├── us/
│   │   ├── fetcher.py           # Alpaca REST + WebSocket fetcher
│   │   ├── validator.py         # US data quality checks
│   │   ├── feature_engineer.py  # TA indicators + VIX + FRED macro
│   │   └── storage.py           # US feature store
│   │
│   ├── india/
│   │   ├── kite_token_manager.py  # TOTP auto-renewal (pyotp)
│   │   ├── fetcher.py             # Kite equity OHLCV fetcher
│   │   ├── fo_fetcher.py          # Kite F&O option chain fetcher
│   │   ├── validator.py           # India data validator + circuit check
│   │   ├── fo_validator.py        # F&O lot size, IV, OI, liquidity checks
│   │   ├── feature_engineer.py    # TA + India VIX + FII/DII flows
│   │   ├── fo_feature_engineer.py # Greeks (mibian), PCR, IV rank, OI
│   │   └── storage.py             # India feature store
│   │
│   └── crypto/                    # Phase 8 only
│       ├── coingecko_fetcher.py
│       ├── ccxt_connector.py
│       ├── validator.py
│       └── storage.py
│
├── intelligence/
│   ├── regime/
│   │   ├── us_regime.py           # US regime classifier (VIX + SPX)
│   │   └── india_regime.py        # India regime classifier (India VIX + Nifty + FII)
│   │
│   ├── strategies/
│   │   ├── us/
│   │   │   ├── momentum.py
│   │   │   ├── mean_reversion.py
│   │   │   ├── trend_following.py
│   │   │   ├── breakout.py
│   │   │   └── sector_rotation.py
│   │   ├── india_equity/
│   │   │   ├── momentum.py
│   │   │   ├── mean_reversion.py
│   │   │   ├── trend_following.py
│   │   │   ├── breakout.py
│   │   │   └── index_rotation.py
│   │   └── india_fo/
│   │       ├── short_strangle.py  # Hedged only
│   │       ├── bull_call_spread.py
│   │       └── bear_put_spread.py
│   │
│   └── ml/
│       ├── xgboost_model.py       # XGBoost (trained per market)
│       ├── lstm_model.py          # LSTM PyTorch (trained per market)
│       ├── ensemble.py            # Weighted ensemble + uncertainty
│       └── explainability.py      # SHAP values for audit trail
│
├── validation/
│   ├── lookahead_checker.py       # Timestamp enforcement
│   ├── overfit_detector.py        # Sharpe/PF threshold guards
│   ├── cost_simulator.py          # Market-specific cost deduction
│   ├── walk_forward.py            # Walk-forward validation engine
│   ├── liquidity_gate.py          # Position size vs ADV check
│   └── fo_greeks_validator.py     # Delta/Gamma/Theta limits for F&O
│
├── backtesting/
│   ├── engine.py                  # Full custom backtesting engine
│   ├── metrics.py                 # Sharpe, drawdown, win rate, PF
│   └── vectorbt_sweeper.py        # Parameter sweeps (vectorbt)
│
├── decision/
│   ├── meta_strategy.py           # Regime → strategy mapping per market
│   └── decision_engine.py         # Final go/no-go with market tag + reason
│
├── risk/
│   ├── us_position_sizer.py       # Quarter-Kelly + ATR (US)
│   ├── india_position_sizer.py    # Quarter-Kelly + ATR (India equity)
│   ├── fo_position_sizer.py       # Lot-aware, margin-aware, Greeks-aware
│   ├── portfolio_allocator.py     # Cross-market exposure cap
│   ├── drawdown_guardian.py       # Per-market + total circuit breaker
│   └── risk_reporter.py           # Live P&L + exposure across all markets
│
├── execution/
│   ├── alpaca_engine.py           # US paper + live execution
│   ├── kite_engine.py             # India equity + F&O execution
│   ├── crypto_engine.py           # CCXT execution (Phase 8)
│   ├── exec_simulator.py          # Latency + fill modeling
│   └── order_manager.py           # Unified order tracking, all markets
│
├── learning/
│   ├── performance_tracker.py     # Per-trade, per-strategy, per-market
│   ├── drift_detector.py          # Per-market model staleness
│   └── retrainer.py               # Scheduled + event-triggered, per market
│
├── observability/
│   ├── dashboard.py               # Streamlit (unified + per-market tabs)
│   ├── alerts.py                  # Telegram bot (market-tagged)
│   └── diagnostics.py             # System self-audit
│
├── tests/
│   ├── test_us/
│   ├── test_india_equity/
│   ├── test_india_fo/
│   ├── test_risk/
│   ├── test_validation/
│   └── test_execution/
│
├── kill.py                        # Emergency kill switch CLI
├── main.py                        # System entry point
├── requirements.in                # Top-level dependencies (pip-tools source)
├── requirements.txt               # Locked transitive deps (pip-compile output)
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml        # ruff + black pre-commit hooks
├── AAATS_MASTER_BLUEPRINT.md
└── README.md
```

---

## Running the System

```bash
# Start full trading engine (paper mode, all markets)
python main.py --mode paper

# Start specific market only
python main.py --mode paper --market us
python main.py --mode paper --market india
python main.py --mode paper --market india_fo

# Run the dashboard
streamlit run observability/dashboard.py

# Emergency halt — specific market
python kill.py --market us
python kill.py --market india

# Emergency halt — everything
python kill.py --market all --confirm

# Run all tests
pytest tests/ -v --cov=.

# Run backtesting
python backtesting/engine.py --market us --strategy momentum --start 2022-01-01 --end 2024-01-01
python backtesting/engine.py --market india --strategy momentum --start 2022-01-01 --end 2024-01-01
python backtesting/engine.py --market india_fo --strategy short_strangle --start 2022-01-01 --end 2024-01-01
```

---

## Getting Help from Claude

This project is built to be AI-assisted. The MASTER_AUTODRIVER.md and this README contain explicit prompting guidance for Claude to build and maintain AAATS.

### When to Ask Claude for Help

Claude can help with:
- **Building modules** — Give Claude the full MASTER_AUTODRIVER.md prompt + the module's spec
- **Debugging tests** — "Run `pytest tests/test_<module>.py -v`. Here's the output: [paste]. What's wrong?"
- **Refactoring existing code** — "I want to add <feature> to <module>. Current implementation: [paste]. Should I <option A> or <option B>?"
- **Backtest analysis** — "I ran a backtest on <strategy>. Results: [paste]. Is this overfitted?"

Claude should NOT be asked to:
- Override risk rules or circuit breakers
- Deploy real capital without Puneeth's explicit approval
- Ignore the BUILD ORDER (build modules out of sequence without permission)
- Skip tests or mocking layers

### How to Prompt Claude Effectively

**Use the MASTER_AUTODRIVER.md prompt.** When starting a new session to build modules, paste the entire MASTER_AUTODRIVER.md into Claude. It contains all context, build order, specs, and behavioral rules. Claude will:
1. Scan the build state
2. Ask you to confirm which module to build
3. Run pre-build validation
4. Build the module
5. Report completion (don't auto-continue)

**For debugging or refactoring tasks,** follow these principles:

1. **Be specific about the goal** — not "fix this", but "fix the backoff logic in <file> to retry 6 times instead of 3"
2. **Provide exact context** — paste the relevant code section, not "there's a bug somewhere"
3. **Clarify constraints** — "do this without changing the interface" or "keep it under 100 lines"
4. **Ask for step-by-step reasoning** — "think through the test case where the DataFrame is empty. What should happen?"
5. **Request a specific format** — "show me a diff of what changes" vs "rewrite the whole file"

### Example: Good Prompt vs Bad Prompt

**❌ Bad Prompt:**
```
Help me improve markets/us/feature_engineer.py. It's slow.
```

**✅ Good Prompt:**
```
markets/us/feature_engineer.py processes 1M+ bars per symbol but takes >10s per symbol.
Current implementation uses a loop (pasted below). Should I vectorize with numpy 
or use apply()? What's the trade-off? Show me a working example for the RSI_14 
computation that I can adapt to other indicators.

[paste current code]
```

The good prompt:
- States the problem (speed)
- Gives context (1M+ bars, 10s latency)
- Shows what you've tried (loop)
- Asks for options + reasoning
- Requests a concrete example

### Anti-Patterns (Don't Do This)

| Anti-Pattern | Why It Fails | What to Do Instead |
|---|---|---|
| "Can you build my strategy?" (no spec) | Claude will invent a strategy; risk rules are unclear | Spec the strategy in detail first. Paste the spec. Then ask Claude to build. |
| "Fix this backtest." (no context) | Claude will guess at the problem | Run the backtest. Paste the error + output. Say what you expected. |
| "Make it better." | "Better" is vague | Specify: "Reduce latency to <X>", "Fix this failure case", "Add this feature" |
| "Build the next module" (without approval) | Violates the BUILD ORDER | Always ask Puneeth first. Then ask Claude to build. |
| Loading entire AAATS repo context for a small question | Wastes tokens; slows down response | Ask the focused question with minimal context. Claude will ask for more if needed. |

### Token Efficiency

Claude prefers minimal context for simple questions. **For this project specifically:**
- **Building modules?** Paste MASTER_AUTODRIVER.md. Claude will handle the full context.
- **Debugging one test?** Paste the test, the error, and the relevant code section. Not the whole repo.
- **Quick question?** "Should risk/us/position_sizer.py use scipy or numpy for this?" — just ask. Claude will clarify if needed.

See the [Prompting Guidelines](AAATS_MASTER_BLUEPRINT.md#16-prompting-guidelines) section in AAATS_MASTER_BLUEPRINT.md for deeper guidance.

---

## Risk Rules (Summary)

These are hardcoded. They cannot be overridden from config or command line.

### US Equities

| Rule | Value |
|---|---|
| Max risk per trade | 1.5% of US portfolio allocation |
| Max total open exposure | 6% |
| Drawdown halt | -15% triggers US kill switch |

### India Equities

| Rule | Value |
|---|---|
| Max risk per trade | 1.5% of India portfolio allocation |
| Max total open exposure | 6% |
| Circuit breaker check | Mandatory before every entry |
| Drawdown halt | -15% triggers India kill switch |

### NSE F&O

| Rule | Value |
|---|---|
| Max risk per trade | 1.0% of total portfolio |
| No naked short options | Permanent rule — no exceptions |
| Max net portfolio Delta | ±0.30 |
| Expiry week position reduction | 50% of F&O positions by expiry week |
| Max simultaneous F&O positions | 3 |
| Drawdown halt | -15% F&O OR -20% total |

### Cross-Market

| Rule | Value |
|---|---|
| Max total deployment | 40% across all markets combined |
| Total portfolio halt | -20% total triggers full system halt |

Full risk documentation: [AAATS_MASTER_BLUEPRINT.md — Section 7](AAATS_MASTER_BLUEPRINT.md)

---

## Technology Stack

| Layer | Tool |
|---|---|
| Language | Python 3.11 |
| Environment | venv + pip-tools |
| Config | Pydantic v2 + python-dotenv |
| Logging | Loguru |
| CI | GitHub Actions |
| Testing | pytest + pytest-cov |
| Code Quality | ruff + black |
| Data — US Equities | Alpaca Markets API |
| Data — India Equities + F&O | Zerodha Kite API (`kiteconnect`) |
| Kite Session Renewal | `pyotp` (TOTP automation) |
| India Macro | RBI DBIE + NSE FII/DII data |
| US Macro | FRED API (`fredapi`) |
| Data — Crypto (Phase 8) | CoinGecko API |
| Execution — Crypto (Phase 8) | CCXT library |
| Feature Engineering | `pandas-ta` |
| ML Model 1 | XGBoost (per-market) |
| ML Model 2 | LSTM — PyTorch (per-market) |
| Explainability | SHAP |
| Strategy Iteration | `vectorbt` |
| Backtesting | Custom-built engine |
| F&O Greeks | `mibian` (Black-Scholes) |
| Risk Math | Quarter-Kelly + ATR |
| Feature Store (Phase 1–3) | SQLite + SQLAlchemy |
| Feature Store (Phase 4+) | PostgreSQL + TimescaleDB |
| Dashboard | Streamlit |
| Alerts | Telegram Bot API |
| Version Control | Git + GitHub |

---

## Realistic Performance Expectations

| Metric | US Equities | India Equities | NSE F&O |
|---|---|---|---|
| Annual return | 15–35% | 12–30% | 20–50% |
| Win rate | 52–60% | 52–60% | 45–55% |
| Max drawdown | -10% to -20% | -10% to -20% | -15% to -25% |
| Sharpe ratio | 1.0–1.8 | 1.0–1.8 | 0.8–1.5 |

Any backtest showing Sharpe > 3.0 or win rate > 80% is flagged as a bug, not a feature.

---

## License

Private. All rights reserved.

---

## Contact

Built and maintained by Puneeth.
Architecture decisions: [AAATS_MASTER_BLUEPRINT.md](AAATS_MASTER_BLUEPRINT.md)

---

*README version: 3.0 | Last updated: April 2026 | Status: Pre-development | Markets: US Equity + India Equity (NSE/BSE) + NSE F&O + Crypto (Phase 8)*

---

## Build Status

| Module | Status | Tests | Notes |
|--------|--------|-------|-------|
| config/settings.py | ✅ DONE | — | Phase 0 |
| foundation/logger.py | ✅ DONE | — | Phase 0 |
| foundation/audit_trail.py | ✅ DONE | — | Phase 0 |
| foundation/kill_switch.py | ✅ DONE | — | Phase 0 |
| foundation/health_monitor.py | ✅ DONE | — | Phase 0 |
| observability/alerts.py | ✅ DONE | — | Phase 0 |
| markets/us/fetcher.py | ✅ DONE | 6 passed | alpaca-py SDK (hotfix verified) |
| markets/us/validator.py | ✅ DONE | 7 passed | — |
| markets/us/feature_engineer.py | ✅ DONE | 6 passed | pandas-ta-classic 0.4.47 |
| markets/us/storage.py | ✅ DONE | 6 passed | SQLite + SQLAlchemy 2.0 |
| risk/us/position_sizer.py | ✅ DONE | 8 passed | Quarter-Kelly + ATR; scipy for NaN/inf guards |
| risk/us/drawdown_guardian.py | ✅ DONE | 6 passed | Rolling peak + kill_switch integration; in-memory state |
| backtesting/engine.py | ✅ DONE | 7 passed | Timestamp gate, overfitting gate (Sharpe>3.0), cost gate, position sizer integration |
| backtesting/validators.py | ✅ DONE | 14 passed | Lookahead bias check, overfitting check (Sharpe/PF/WR), walk-forward split validation |
| markets/india/token_manager.py | ✅ DONE | 10 passed | FULL_MOCK — SmartConnect injected; pyotp TOTP; halt+alert on failure |
| markets/india/fetcher.py | ✅ DONE | 7 passed | FULL_MOCK — getCandleData + SmartWebSocketV2 injected; IST→UTC; 30s timeout; 6x backoff+halt |
| markets/india/fo_fetcher.py | ✅ DONE | 8 passed | FULL_MOCK — getMarketData + getCandleData injected; IV≤0 rows rejected+audited; 6x backoff+halt |
| markets/india/validator.py | ✅ DONE | 10 passed | NO_MOCK_NEEDED — pandas/numpy only; NSE circuit breaker with FP epsilon fix |
| markets/india/fo_validator.py | ✅ DONE | 13 passed | NO_MOCK_NEEDED — pandas/numpy only; IV, OI, bid/ask, lot-size, valid-strike, far-OTM checks |
| markets/india/feature_engineer.py | ✅ DONE | 7 passed | NO_MOCK_NEEDED — pandas-ta-classic 0.4.47; FII/DII/india_vix broadcast; warmup rows retained |
| markets/india/fo_feature_engineer.py | ✅ DONE | 23 passed | NO_MOCK_NEEDED — scipy.stats.norm BS Greeks (mibian stale since 2016); PCR, IV Rank, Max Pain |

## Last Session
Date: 2026-04-28
Built: markets/india/fo_feature_engineer.py
Tests: 23 passed, 0 failed
Mock status: NO_MOCK_NEEDED (pure math/pandas; scipy.stats.norm for Black-Scholes)
Library deviation: mibian (last release 2016) replaced with scipy.stats.norm — identical math, actively maintained

## Next Session
Planned: markets/india/storage.py

## Known Issues
- [2026-04-28] markets/india/fo_feature_engineer.py: mibian (spec library for Greeks) last released 2016 — replaced with scipy.stats.norm (identical Black-Scholes formulas, maintained). No behaviour change. — Status: RESOLVED
- [2026-04-27] markets/us/storage.py: SQLite correct for write/point-lookup; DuckDB analytics layer needed in Phase 2 for backtesting cross-symbol queries — Status: NEEDS_REVIEW
- [2026-04-27] risk/us/position_sizer.py: Spec test_normal_sizing used ATR=2.0 which produces position_pct=37.5% (rejected); corrected to ATR=10.0 in test — Status: RESOLVED
- [2026-04-27] risk/us/drawdown_guardian.py: In-memory peak state does not survive process restarts; Phase 2 trading loop must seed guardian with persisted peak value on startup — Status: NEEDS_REVIEW
- [2026-04-27] backtesting/engine.py: iterrows() performance acceptable for daily bars; becomes bottleneck at tick/sweep scale — Status: NEEDS_REVIEW
- [2026-04-27] backtesting/engine.py: profit_factor=inf when no losing trades; downstream validators must guard against inf — Status: NEEDS_REVIEW (handled in validators.py)
- [2026-04-27] backtesting/engine.py: Bar-level Sharpe spikes on short sparse-trade datasets; overfitting gate catches it but callers must check result.approved before using sharpe_ratio — Status: NEEDS_REVIEW
