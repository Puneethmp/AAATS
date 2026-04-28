# AAATS — Self-Driving Build Prompt
# Version: 2.1 | Updated: April 2026 | Research-backed, production-ready, Claude-prompting-aligned
# Paste this ONCE into Claude. It auto-builds itself from here.

---

## HOW TO USE THIS DOCUMENT

This prompt is designed to be given to Claude in full. Claude will:
1. Read the entire build plan once
2. Ask clarifying questions if ambiguous
3. Build one module per session
4. Report completion before moving on

**Golden rule:** Every interaction with Claude must be specific, include context, and ask for step-by-step reasoning. See [Prompting Guidelines](AAATS_MASTER_BLUEPRINT.md#16-prompting-guidelines) for detailed rules.

---

## RESEARCH NOTES — LIBRARY DECISIONS LOCKED HERE

All library decisions below were validated against April 2026 ecosystem state.
Claude must re-validate any library flagged VERIFY_ON_BUILD before using it.

### Key decisions made during v2.0 authoring:

| Decision | Old | New | Reason |
|---|---|---|---|
| Hyperparameter tuning | GridSearch | Optuna | Bayesian TPE sampler, 10-100x fewer trials needed, XGBoost integration with pruning |
| Drift detection | Custom | `river` (ADWIN) | Merger of creme + scikit-multiflow, actively maintained 2025, ADWIN proven for financial streams |
| Parameter sweep backtesting | vectorbt | vectorbt (open source, pip installable) | PRO is paid; open source `pip install vectorbt` is free, Apache 2.0 with Commons Clause, fully sufficient |
| ML signal classification | Regression head | 3-class softmax (0=hold, 1=long, 2=short) | Correct framing for trading — direction, not price |
| India pipeline build approach | BLOCKED entirely | Build with full mock layer | All India modules built with pytest-mock layer. Zero real API calls in tests. Swap credentials when API approved. System is 100% code-complete before API arrives. |

---

## YOUR BEHAVIOR RULES (read before doing anything)

These rules are non-negotiable and frame every decision. Think of them as guardrails, not suggestions.

### Scope & Session Management

1. **Before every session:** Scan existing files (use `find` or `glob`) to know what's already built. Ask me to confirm the current session's target module before writing code.
2. **Build ONE module per session.** When done, stop and report completion. Do not automatically start the next module — wait for Puneeth to acknowledge and confirm next steps.
3. **Never rewrite a file that already exists and has passing tests.** If tests are failing, fix them. If code is stale, ask me first. Unnecessary rewrites waste tokens and risk regressions.
4. **Never build ahead.** If current module's tests are not green, fix them before moving on. Leave incomplete work in a state Puneeth can resume.

### Token Discipline

5. **Token discipline is non-negotiable.** Before rewriting existing files, loading large files, or building unrequested modules, STOP and tell Puneeth exactly what you're about to do and why. Wait for explicit approval. This includes:
   - Files > 200 lines you've already read this session
   - Refactoring working code
   - Loading entire projects when only one file matters
6. **After each module is complete,** print the completion summary (see format below) and STOP. Do not start the next module. This forces a checkpoint where Puneeth can review and approve next steps.

### Architecture Rules

7. **India pipeline rule:** Build all India modules with a full mock layer. The `SmartConnect` client is injected via dependency injection. Tests use `unittest.mock.patch`. When Puneeth receives API approval, he drops real credentials into `.env` — the code changes zero lines. This is not optional.
8. **BLOCKED phase rule:** Phase 4 (India Pipeline) is no longer a blocker. Build it with mocks. Only skip if the SPEC itself is missing — not because of missing credentials.
9. **Library self-check rule:** Before installing any library, run `pip index versions <lib>` and check the last release date. If last release > 18 months ago, flag it in FLAGGED_ISSUES.md and await approval before proceeding. No exceptions.
10. **Optuna rule:** Every ML module that trains a model uses Optuna for hyperparameter search, not GridSearchCV or manual tuning. This is locked.

---

## HOW TO START EVERY SESSION

Run this check first, every single time. This is the startup ritual that prevents wasted work.

1. **Inventory the current state.** Run `find . -name "*.py" | grep -v __pycache__ | sort` to list existing files. Don't load them yet — just know they exist.
2. **Compare against BUILD ORDER.** Look at the BUILD ORDER section below. Which phases are marked ✅ COMPLETE? Which modules are still pending?
3. **Report status clearly.** Print exactly:
   ```
   BUILD STATUS:
   ✅ Complete: [list modules from BUILD ORDER marked done]
   ⏳ In Progress: [if any]
   ⏸️ Next: [next module from BUILD ORDER that's not started]
   ```
4. **Ask for explicit confirmation.** Quote the target module back to me and ask: "Should I build [MODULE NAME]? Yes/no/skip to [OTHER MODULE]?" Do not assume. Wait for my response.
5. **Only after confirmation:** Read the spec for that module from the SPECS section. Then proceed with PRE-BUILD VALIDATION.

---

## PRE-BUILD VALIDATION (run before writing a single line of code)

Before building anything, validate the spec for this session. This is not optional. Think of this as a stress-test — your job is to find gaps before coding, not after.

### Step 1 — Library Check (Non-negotiable)

For every library named in the spec, run:
```bash
pip index versions <library_name>
```

Check each result against:
- **Maintenance status:** Last release within 18 months? If not, flag in FLAGGED_ISSUES.md and await Puneeth's approval.
- **Compatibility:** Does it work with Python 3.11? Does it conflict with other installed libs?
- **Alternatives:** Is there a better option in April 2026 that's more maintained or more fit for purpose?

**If you find an issue,** STOP. Do NOT proceed. Append to FLAGGED_ISSUES.md in this format:
```
[DATE] PRE-BUILD | MODULE: <module> | LIBRARY ISSUE: <spec_library>
Problem: <specific reason why it's wrong — stale, incompatible, or superseded>
Recommendation: <which library to use instead, with reason>
Research: <any documentation links>
Status: AWAITING_APPROVAL
```

Then report to Puneeth with the exact FLAGGED_ISSUES entry and ask: approve this change or revert the spec?

### Step 2 — Spec Integrity Check (Find Logical Gaps)

Read the spec for your target module. Ask yourself:

- **Conflicts:** Does this spec contradict any already-built module? (Example: If markets/us/fetcher.py already exists and uses Alpaca, a new spec shouldn't invent a different data source.)
- **Logical gaps:** Is the data contract clear? (Example: Does the spec say what columns the returned DataFrame should have? If not, clarify before coding.)
- **Production readiness:** Would this code survive 30 days in production? Are there edge cases (empty input, network timeout, malformed data)?
- **Interface misalignment:** Does the output format match what the next module expects? Check the downstream spec.

**If you find gaps,** ask Puneeth: "The spec for [MODULE] is unclear on [ISSUE]. Should I [OPTION A] or [OPTION B]?" Be specific about the gap.

### Step 3 — Reliability Check (Find Bugs Before Coding)

Flag any patterns that scream "this will fail in production":
- **Network calls without timeout:** If spec calls external APIs, is there a timeout? (Standard: 30s.) If not, flag it.
- **Missing error handling:** Does the spec handle network failures, malformed responses, or empty data? If not, you'll add it — but tell Puneeth first.
- **Ambiguous data contracts:** Example: "returns a DataFrame" — which columns? what dtype? what if data is empty? Be specific before coding.
- **No performance requirements:** If the spec touches >10k rows of data or involves ML, is there a performance target? If latency matters, say so upfront.

---

## BUILD ORDER (follow exactly, no skipping)

### PHASE 0 — Foundation ✅ COMPLETE — DO NOT REBUILD
- [x] config/settings.py
- [x] config/.env.example
- [x] foundation/logger.py
- [x] foundation/audit_trail.py
- [x] foundation/kill_switch.py
- [x] foundation/health_monitor.py
- [x] observability/alerts.py

### PHASE 1 — US Pipeline ✅ COMPLETE — DO NOT REBUILD
- [x] markets/us/fetcher.py + tests/test_us/test_us_fetcher.py
- [x] markets/us/validator.py + tests/test_us/test_us_validator.py
- [x] markets/us/feature_engineer.py + tests/test_us/test_us_features.py
- [x] markets/us/storage.py + tests/test_us/test_us_storage.py

### PHASE 2 — US Risk Engine ✅ COMPLETE — DO NOT REBUILD
- [x] risk/us/position_sizer.py + tests/test_risk/test_us_position_sizer.py
- [x] risk/us/drawdown_guardian.py + tests/test_risk/test_us_drawdown_guardian.py

### PHASE 3 — Backtesting Engine ✅ COMPLETE — DO NOT REBUILD
- [x] backtesting/engine.py + tests/test_backtesting/test_engine.py
- [x] backtesting/validators.py + tests/test_backtesting/test_validators.py

### PHASE 4 — India Pipeline (BUILD WITH MOCKS — credentials injected later)
⚠️ MOCK BUILD: All SmartConnect calls are behind an injected client interface.
Tests use unittest.mock.patch. Zero real API calls. Code is production-ready for when credentials arrive.
Do NOT skip this phase. Build it now.

- [ ] markets/india/token_manager.py + tests/test_india/test_token_manager.py
- [ ] markets/india/fetcher.py + tests/test_india/test_fetcher.py
- [ ] markets/india/fo_fetcher.py + tests/test_india/test_fo_fetcher.py
- [ ] markets/india/validator.py + tests/test_india/test_validator.py
- [ ] markets/india/fo_validator.py + tests/test_india/test_fo_validator.py
- [ ] markets/india/feature_engineer.py + tests/test_india/test_features.py
- [ ] markets/india/fo_feature_engineer.py + tests/test_india/test_fo_features.py
- [ ] markets/india/storage.py + tests/test_india/test_storage.py

### PHASE 5 — US Strategy Pool (Rule-Based — no ML yet)
- [ ] strategies/us/momentum.py + tests/test_strategies/test_us_momentum.py
- [ ] strategies/us/mean_reversion.py + tests/test_strategies/test_us_mean_reversion.py
- [ ] strategies/us/trend_following.py + tests/test_strategies/test_us_trend_following.py
- [ ] strategies/us/breakout.py + tests/test_strategies/test_us_breakout.py
- [ ] strategies/us/sector_rotation.py + tests/test_strategies/test_us_sector_rotation.py

### PHASE 6 — India Strategy Pool (Rule-Based — no ML yet, built with mocks)
- [ ] strategies/india/momentum.py + tests/test_strategies/test_india_momentum.py
- [ ] strategies/india/mean_reversion.py + tests/test_strategies/test_india_mean_reversion.py
- [ ] strategies/india/trend_following.py + tests/test_strategies/test_india_trend_following.py
- [ ] strategies/india/breakout.py + tests/test_strategies/test_india_breakout.py
- [ ] strategies/india/index_rotation.py + tests/test_strategies/test_india_index_rotation.py

### PHASE 7 — F&O Strategy Pool (Rule-Based, defined-risk only, built with mocks)
- [ ] strategies/fo/short_strangle.py + tests/test_strategies/test_fo_short_strangle.py
- [ ] strategies/fo/bull_call_spread.py + tests/test_strategies/test_fo_bull_call_spread.py
- [ ] strategies/fo/bear_put_spread.py + tests/test_strategies/test_fo_bear_put_spread.py

### PHASE 8 — Regime Detection
- [ ] intelligence/us_regime.py + tests/test_intelligence/test_us_regime.py
- [ ] intelligence/india_regime.py + tests/test_intelligence/test_india_regime.py

### PHASE 9 — India + F&O Risk Engine (built with mocks)
- [ ] risk/india/position_sizer.py + tests/test_risk/test_india_position_sizer.py
- [ ] risk/fo/position_sizer.py + tests/test_risk/test_fo_position_sizer.py
- [ ] risk/cross_market_allocator.py + tests/test_risk/test_cross_market_allocator.py
- [ ] risk/realtime_reporter.py + tests/test_risk/test_realtime_reporter.py

### PHASE 10 — ML Intelligence Layer
- [ ] intelligence/us_ml_model.py + tests/test_intelligence/test_us_ml_model.py
- [ ] intelligence/india_ml_model.py + tests/test_intelligence/test_india_ml_model.py
- [ ] intelligence/fo_ml_model.py + tests/test_intelligence/test_fo_ml_model.py
- [ ] intelligence/uncertainty_engine.py + tests/test_intelligence/test_uncertainty_engine.py
- [ ] intelligence/signal_ranker.py + tests/test_intelligence/test_signal_ranker.py

### PHASE 11 — Decision Engine
- [ ] decision/meta_strategy.py + tests/test_decision/test_meta_strategy.py
- [ ] decision/engine.py + tests/test_decision/test_engine.py
- [ ] decision/explainability.py + tests/test_decision/test_explainability.py

### PHASE 12 — Execution Layer
- [ ] execution/alpaca_engine.py + tests/test_execution/test_alpaca_engine.py
- [ ] execution/india_simulator.py + tests/test_execution/test_india_simulator.py
- [ ] execution/order_manager.py + tests/test_execution/test_order_manager.py

### PHASE 13 — Learning Loop
- [ ] learning/performance_tracker.py + tests/test_learning/test_performance_tracker.py
- [ ] learning/drift_detector.py + tests/test_learning/test_drift_detector.py
- [ ] learning/retrainer.py + tests/test_learning/test_retrainer.py
- [ ] learning/strategy_graveyard.py + tests/test_learning/test_strategy_graveyard.py

### PHASE 14 — Observability Dashboard
- [ ] observability/dashboard.py (Streamlit — no unit tests, manual QA only)

---

## SPECS — one block per module (read only the one you are building)

---

### SPEC: markets/india/token_manager.py

**Purpose:** Daily Angel One SmartAPI session renewal via TOTP. Runs before India market open (8:00 AM IST). If renewal fails: halt India module + Telegram alert.

**Mock strategy:** `SmartConnect` is passed as a constructor argument (dependency injection). Tests inject a `MagicMock()`. Production passes the real `SmartConnect(api_key)`.

**Libraries:**
- `smartapi-python` (pip install smartapi-python) — verify last release on build
- `pyotp` — TOTP generation
- `pytz` — IST timezone handling

**Class: `TokenManager`**
```python
class TokenManager:
    def __init__(self, smart_connect_client, config, alert_fn=None):
        # smart_connect_client: injected (real or mock)
        # config: settings object with ANGEL_CLIENT_ID, ANGEL_PIN, ANGEL_TOTP_SECRET
        # alert_fn: callable(message: str) — defaults to logger.warning if None

    def renew_session(self) -> dict:
        # Generates TOTP via pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
        # Calls client.generateSession(client_id, pin, totp)
        # Returns: {"auth_token": str, "refresh_token": str, "feed_token": str}
        # On failure: calls kill_switch.halt(market="india", ...), calls alert_fn, raises

    def get_auth_token(self) -> str:
        # Returns cached token. Raises if not yet renewed.

    def is_token_valid(self) -> bool:
        # Returns True if token was renewed today and has not expired
        # Angel One tokens expire daily — valid = renewed today in IST
```

**Tests (all mocked — no real API calls):**
1. `renew_session` returns correct dict when mock generateSession succeeds
2. TOTP is generated from correct secret
3. `renew_session` calls `kill_switch.halt(market="india")` on auth failure
4. `renew_session` calls `alert_fn` on auth failure
5. `get_auth_token` raises if `renew_session` not yet called
6. `is_token_valid` returns False if renewed yesterday (mock datetime)
7. `is_token_valid` returns True if renewed today

---

### SPEC: markets/india/fetcher.py

**Purpose:** Fetch NSE/BSE OHLCV historical + live data via Angel One SmartAPI.

**Mock strategy:** Same as token_manager — `SmartConnect` injected.

**Libraries:**
- `smartapi-python`
- `pandas`
- `pytz`

**Functions:**
```python
def fetch_historical(
    symbol: str,
    token: str,           # Angel One instrument token (e.g. "3045" for SBIN)
    exchange: str,        # "NSE" or "BSE"
    interval: str,        # "ONE_DAY", "ONE_HOUR", "FIFTEEN_MINUTE", etc.
    from_date: str,       # "YYYY-MM-DD HH:MM"
    to_date: str,
    smart_client,
    config
) -> pd.DataFrame:
    # Returns: [timestamp(IST→UTC stored), open, high, low, close, volume]
    # Exponential backoff: 1s→2s→4s→8s→16s on failure
    # 6th failure: kill_switch.halt(market="india", reason="Angel One fetch failed 6x")
    # Every failure: audit_trail entry event_type="REJECTION"
    # Timeout: 30s per call

def stream_live(
    token_list: list[dict],  # [{"exchange": "NSE", "token": "3045"}]
    callback,
    smart_client,
    config
) -> None:
    # Angel One WebSocket V2 (SmartWebSocketV2)
    # Calls callback(symbol, bar) on each tick
    # Same backoff on disconnect
```

**Tests (all mocked):**
1. `fetch_historical` returns correct columns
2. Backoff retries 3x then succeeds
3. `kill_switch.halt` called on 6th failure
4. `audit_trail` REJECTION entry on failure
5. Timestamps stored as UTC
6. `stream_live` callback called with correct data shape

---

### SPEC: markets/india/fo_fetcher.py

**Purpose:** Fetch NSE F&O option chain data (OI, IV, strike data) via Angel One SmartAPI.

**Mock strategy:** Injected client, full mocks in tests.

**Libraries:**
- `smartapi-python`
- `pandas`
- `pytz`

**Functions:**
```python
def fetch_option_chain(
    underlying: str,     # e.g. "NIFTY"
    expiry: str,         # "DDMMMYYYY" e.g. "29MAY2025"
    smart_client,
    config
) -> pd.DataFrame:
    # Returns: [strike, option_type (CE/PE), ltp, oi, change_in_oi, iv, bid, ask, volume]
    # Timeout: 30s
    # On failure: audit_trail REJECTION + backoff

def fetch_fo_ohlcv(
    symbol: str,         # e.g. "NIFTY25MAY24000CE"
    token: str,
    interval: str,
    from_date: str,
    to_date: str,
    smart_client,
    config
) -> pd.DataFrame:
    # Returns standard OHLCV for futures/options instrument
    # Same backoff and kill_switch rules as equity fetcher
```

**Tests (all mocked):**
1. `fetch_option_chain` returns correct columns
2. CE and PE rows both present
3. IV > 0 for all returned rows (or row is rejected)
4. `fetch_fo_ohlcv` returns OHLCV columns
5. Kill switch triggered on 6th failure
6. Audit trail entry on failure

---

### SPEC: markets/india/validator.py

**Purpose:** Validate NSE/BSE equity bar data. India-specific: circuit breaker checks.

**Libraries:** `pandas`, `numpy`

**Function:**
```python
def validate_bars(df: pd.DataFrame, symbol: str, config) -> tuple[pd.DataFrame, list[dict]]:
    # Reject if:
    # - null fields in any OHLCV column
    # - volume = 0
    # - high < low
    # - price spike > 20% vs previous close
    # - out-of-order timestamps
    # - stock at NSE upper or lower circuit limit (circuit_pct in [5, 10, 20] configured per symbol)
    # Every rejection: audit_trail entry event_type="REJECTION" with reason
    # Returns: (clean_df, list of rejection dicts with symbol, timestamp, reason)
```

**Tests:**
1. Valid bars pass through unchanged
2. Null field rejected
3. Zero volume rejected
4. high < low rejected
5. >20% spike rejected, <20% passes
6. Out-of-order timestamp rejected
7. Stock at upper circuit limit rejected (mock circuit check)
8. Stock at lower circuit limit rejected
9. Rejection logged to audit trail
10. Clean bars count correct when mix of valid/invalid

---

### SPEC: markets/india/fo_validator.py

**Purpose:** Validate NSE F&O option chain data. Stricter than equity — options-specific checks.

**Libraries:** `pandas`, `numpy`

**Function:**
```python
def validate_option_chain(
    df: pd.DataFrame,
    underlying: str,
    config
) -> tuple[pd.DataFrame, list[dict]]:
    # Reject if:
    # - IV = 0 or negative (option pricing impossible)
    # - OI = 0 (illiquid strike — cannot enter/exit)
    # - bid = 0 AND ask = 0 (no market)
    # - lot_size not integer multiple (lot size from config)
    # - strike not in valid strike list for underlying
    # - far OTM: |strike - spot| > 30% of spot (configurable)
```

**Tests:**
1. Valid chain passes through
2. IV=0 row rejected
3. OI=0 row rejected
4. Zero bid+ask rejected
5. Far OTM strike rejected when enabled
6. Valid OTM accepted when within threshold
7. Rejection logged to audit trail

---

### SPEC: markets/india/feature_engineer.py

**Purpose:** Compute TA features for India equity bars. Identical feature set to US engineer but with India-specific macro inputs (FII/DII, India VIX).

**Libraries:**
- `pandas-ta-classic` (import as `pandas_ta_classic`) — same as US
- `numpy`
- `requests` — for fetching FII/DII from NSE public endpoint

**Function:**
```python
def engineer_features(
    df: pd.DataFrame,    # OHLCV bars from India fetcher
    symbol: str,
    india_vix: float,    # current India VIX value
    fii_net: float,      # FII net buy/sell in crores (positive=buy, negative=sell)
    dii_net: float,      # DII net buy/sell in crores
    config
) -> pd.DataFrame:
    # Adds columns:
    # Price: returns_1d, returns_5d, returns_20d, log_return
    # Momentum: rsi_14, macd, macd_signal, macd_hist, roc_10
    # Trend: ema_20, ema_50, ema_200, adx_14, bb_upper, bb_lower, bb_pct
    # Volume: obv, volume_sma_ratio, delivery_pct (if available, else NaN)
    # Volatility: atr_14, hist_vol_20, india_vix (passed in)
    # Institutional: fii_net, dii_net (passed in — append as columns)
    # Regime placeholder: india_regime (NaN until Phase 8 fills it)
```

**Tests:**
1. All expected columns present
2. RSI bounded [0, 100]
3. ATR > 0 for all rows
4. EMA_200 NaN for first 199 rows (insufficient data handled gracefully)
5. FII/DII values appended correctly
6. Function handles empty DataFrame (returns empty with same columns)
7. No lookahead — features use only past data (check with shifted test)

---

### SPEC: markets/india/fo_feature_engineer.py

**Purpose:** Compute F&O specific features: PCR, IV Rank, Max Pain, Greeks.

**Libraries:**
- `pandas`
- `numpy`
- `mibian` — Black-Scholes Greeks. Verify last release on build.

**Functions:**
```python
def compute_pcr(option_chain_df: pd.DataFrame) -> float:
    # PCR = sum(Put OI) / sum(Call OI)
    # Returns float. If sum(Call OI) = 0: return NaN (not infinity)

def compute_iv_rank(current_iv: float, iv_history_52w: list[float]) -> float:
    # IV Rank = (current_iv - min_52w) / (max_52w - min_52w) * 100
    # Returns [0, 100]. If max == min: return 50.0 (neutral)

def compute_max_pain(option_chain_df: pd.DataFrame) -> float:
    # Max Pain = strike where total OI writers (call writers + put writers) lose least
    # Algorithm: for each strike, compute total loss to writers if underlying expires there
    # Return strike with minimum total writer loss

def compute_greeks(
    option_type: str,      # "CE" or "PE"
    underlying_price: float,
    strike: float,
    time_to_expiry_days: float,
    risk_free_rate: float,
    implied_volatility: float
) -> dict:
    # Uses mibian Black-Scholes
    # Returns: {"delta": float, "gamma": float, "theta": float, "vega": float}
    # Theta returned as daily decay (divide mibian output by 365)
```

**Tests:**
1. `compute_pcr` returns correct ratio
2. `compute_pcr` returns NaN when zero calls (not ZeroDivisionError)
3. `compute_iv_rank` returns 50 when max==min
4. `compute_iv_rank` returns correct value for known inputs
5. `compute_max_pain` returns a strike that exists in the chain
6. `compute_greeks` CE delta in [0, 1]
7. `compute_greeks` PE delta in [-1, 0]
8. `compute_greeks` theta is negative (time decay)

---

### SPEC: markets/india/storage.py

**Purpose:** Store India equity bars in SQLite. Identical architecture to US storage.

**Libraries:** `SQLAlchemy`, `sqlite3` (stdlib)

**Schema:** Table `india_equity_bars`: symbol, timestamp (UTC ISO-8601), open, high, low, close, volume, atr_14
**Table** `india_fo_bars`: symbol, expiry, strike, option_type, timestamp, open, high, low, close, volume, oi, iv

**Functions:**
```python
def store_bars(df: pd.DataFrame, symbol: str, db_path: str) -> int:
    # Upsert by (symbol, timestamp) — no duplicates
    # Returns count of rows inserted

def fetch_bars(symbol: str, start: str, end: str, db_path: str) -> pd.DataFrame:
    # Returns bars in [start, end] range inclusive

def store_option_chain_snapshot(df: pd.DataFrame, underlying: str, timestamp: str, db_path: str) -> int:
    # Stores option chain snapshot

def fetch_option_chain_history(underlying: str, start: str, end: str, db_path: str) -> pd.DataFrame:
    # Returns chain snapshots in range
```

**Tests:**
1. `store_bars` inserts correctly
2. Duplicate (symbol, timestamp) → upsert, not duplicate row
3. `fetch_bars` returns correct date range
4. Empty fetch returns empty DataFrame (not exception)
5. `store_option_chain_snapshot` inserts CE and PE rows
6. `fetch_option_chain_history` returns correct range

---

### SPEC: strategies/us/momentum.py

**Purpose:** US equity momentum strategy. EMA crossover + volume confirmation. Pure rule-based — no ML.

**Libraries:** `pandas`, `numpy`

**Interface (all strategies share this interface):**
```python
from dataclasses import dataclass

@dataclass
class Signal:
    symbol: str
    direction: str          # "long", "short", "flat"
    confidence: float       # [0.0, 1.0] — rule-based confidence (not ML)
    entry_price: float
    stop_price: float       # ATR-based stop, set at signal time
    timestamp: pd.Timestamp
    strategy: str           # "us_momentum"
    regime_required: str    # "bull_trend" — strategy only fires in this regime
    reason: str             # human-readable why

def generate_signal(
    df: pd.DataFrame,    # OHLCV + feature columns from feature_engineer
    symbol: str,
    config
) -> Signal | None:
    # Returns Signal or None (no trade)
```

**Logic:**
```
Entry (Long):
  EMA_20 crosses above EMA_50 (crossover in last bar)
  AND volume > 1.5x volume SMA (volume confirmation)
  AND ADX > 20 (trending, not sideways)
  AND regime == "bull_trend" (checked against df["us_regime"] last row)

Entry (Short): opposite crossover, volume confirm, ADX > 20, regime == "bear_trend"

Stop: ATR_14 * 2.0 below entry (long) or above entry (short)

Confidence:
  Base: 0.5
  +0.15 if ADX > 30 (strong trend)
  +0.10 if RSI_14 in [45, 65] for long (momentum healthy, not overbought)
  +0.10 if volume > 2x SMA (very strong volume)
  Max: 1.0, Min: 0.0
```

**Tests:**
1. Signal generated on valid EMA crossover with volume
2. No signal when volume below threshold
3. No signal when ADX < 20
4. No signal in wrong regime
5. Stop placed correctly at ATR * 2.0 below entry
6. Confidence increases with ADX > 30
7. No signal on flat data (no crossover)
8. Returns None (not raises) when insufficient data for EMA_200

---

### SPEC: strategies/us/mean_reversion.py

**Purpose:** US equity mean reversion. Bollinger Band extremes + RSI divergence.

**Interface:** Same `Signal` dataclass and `generate_signal()` signature as momentum.

**Logic:**
```
Entry (Long):
  Close < BB_lower (price below lower band — oversold)
  AND RSI_14 < 35 (momentum confirms oversold)
  AND regime in ["sideways", "bear_trend"] (mean reversion works in ranging/oversold markets)

Entry (Short):
  Close > BB_upper
  AND RSI_14 > 65
  AND regime in ["sideways", "bull_trend"]

Stop: ATR_14 * 1.5 (tighter stop than momentum — reversion should be quick)

Confidence:
  Base: 0.5
  +0.15 if RSI < 25 (very oversold) or RSI > 75 (very overbought)
  +0.10 if BB %B < 0.05 (deep outside band)
  +0.10 if volume spike (>1.5x SMA) — panic selling often marks bottoms
```

**Tests:**
1. Long signal on close < BB_lower + RSI < 35
2. Short signal on close > BB_upper + RSI > 65
3. No signal when RSI contradicts BB position (RSI 50 but below BB)
4. Wrong regime suppresses signal
5. Confidence scoring correct
6. Stop at ATR * 1.5

---

### SPEC: strategies/us/trend_following.py

**Purpose:** US equity trend following. ADX + MACD alignment.

**Interface:** Same Signal/generate_signal.

**Logic:**
```
Entry (Long):
  ADX > 25 (strong trend)
  AND MACD_line > MACD_signal (bullish MACD alignment)
  AND MACD_hist > 0 and increasing (momentum building)
  AND EMA_50 > EMA_200 (long-term trend up)
  AND regime == "bull_trend"

Entry (Short): opposite

Stop: ATR_14 * 2.5 (wider stop — trends need room)

Confidence:
  Base: 0.5
  +0.20 if ADX > 35
  +0.10 if EMA_20 > EMA_50 > EMA_200 (full alignment)
  +0.10 if MACD_hist accelerating (increasing positive slope)
```

**Tests:**
1. Long signal on ADX + MACD alignment
2. Short signal correctly
3. No signal: ADX < 25
4. No signal: MACD misaligned
5. No signal: wrong regime
6. Confidence scores
7. Wide stop placed correctly

---

### SPEC: strategies/us/breakout.py

**Purpose:** 52-week high/low breakout + volume confirmation.

**Interface:** Same Signal/generate_signal.

**Logic:**
```
Entry (Long):
  Close > rolling_max(close, 252) of previous day (new 52-week high)
  AND volume > 2x volume SMA (breakout must be backed by volume)
  AND ATR_14 expansion (current ATR > ATR 20 bars ago — volatility expanding)
  AND regime in ["bull_trend", "high_volatility"]

Entry (Short):
  Close < rolling_min(close, 252) of previous day (52-week low)
  AND volume > 2x volume SMA
  AND regime in ["bear_trend", "high_volatility"]

Stop: Previous 52-week high/low (long: stop at prior week's high that was broken; short: opposite)

Confidence:
  Base: 0.6 (breakouts are high-conviction)
  +0.20 if volume > 3x SMA
  +0.10 if ATR expansion > 50%
```

**Tests:**
1. Long signal on new 52-week high with volume
2. No signal: new high without volume
3. No signal: volume but no new high
4. Short signal correct
5. Stop at correct level (prior week high)
6. Requires minimum 252 bars — returns None if insufficient

---

### SPEC: strategies/us/sector_rotation.py

**Purpose:** Relative strength rotation across S&P sectors. Buys strongest sector ETF, shorts weakest.

**Interface:** Same Signal, but `generate_signal` takes a dict of DataFrames (one per sector ETF).

```python
def generate_signal(
    sector_dfs: dict[str, pd.DataFrame],   # {"XLK": df, "XLF": df, ...}
    config
) -> list[Signal]:
    # Returns list of Signals (one long, one short, or empty list)
```

**Logic:**
```
Sector ETFs tracked: XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU, XLRE, XLB, XLC

Relative strength score per sector:
  RS = (returns_1m * 0.4) + (returns_3m * 0.35) + (returns_6m * 0.25)
  Normalize to z-score across sectors

Signal:
  Long: top RS sector if z-score > 1.0
  Short: bottom RS sector if z-score < -1.0
  Neutral if spread < 2.0 z-score (no clear rotation)

Stop: ATR_14 * 2.0 of the selected sector ETF

Rebalance: only change positions if RS rank changes (not every bar)
```

**Tests:**
1. Returns long on highest RS sector
2. Returns short on lowest RS sector
3. Returns empty when spread < threshold
4. Handles missing sector data gracefully (logs, excludes, continues)
5. No signal change when RS rank stable

---

### SPEC: strategies/india/momentum.py

**Purpose:** India equity momentum. EMA crossover + volume + FII confirmation.

**Interface:** Same Signal/generate_signal as US strategies. strategy="india_momentum".

**Logic:**
```
Entry (Long):
  EMA_20 crosses above EMA_50
  AND volume > 1.5x volume SMA
  AND ADX > 20
  AND fii_net > 0 (FII net buyers — India-specific confirmation)
  AND regime == "bull_trend"

Stop: ATR_14 * 2.0

Confidence:
  Base: 0.5
  +0.15 if ADX > 30
  +0.15 if fii_net > 1000 crore (strong institutional conviction)
  +0.10 if volume > 2x SMA
```

**Tests (FII data mocked — no real API):**
1. Long signal with EMA crossover + FII positive
2. No signal when FII negative (even if technical setup is valid)
3. No signal when volume weak
4. No signal in wrong regime
5. Confidence scores

---

### SPEC: strategies/india/mean_reversion.py

**Same as US mean_reversion.py logic. strategy="india_mean_reversion". No FII filter (mean reversion is contrarian — FII flows can be lagging indicator).**

**Tests:** Same 6 tests as US version.

---

### SPEC: strategies/india/trend_following.py

**Same as US trend_following.py logic. strategy="india_trend_following". Add: FII net buy confirmation for long entries (same filter as India momentum).**

**Tests:** Same as US + FII filter test.

---

### SPEC: strategies/india/breakout.py

**Same as US breakout.py logic. strategy="india_breakout". Add: delivery_pct > 40% for long breakouts (delivery volume confirms genuine institutional buying, not intraday speculation).**

**Tests:** Same as US + delivery_pct filter test.

---

### SPEC: strategies/india/index_rotation.py

**Purpose:** Nifty large cap vs mid cap relative strength rotation.

**Logic:**
```
Indices tracked: NIFTY50 (large cap proxy), NIFTYMIDCAP150 (mid cap proxy)

Relative strength:
  RS = (nifty50_3m_return / niftymid_3m_return)
  If RS > 1.05 (large caps outperforming): rotate to large cap stocks
  If RS < 0.95 (mid caps outperforming): rotate to mid cap stocks
  Neutral band [0.95, 1.05]: hold current allocation

Signal: returns allocation weight signals, not individual stock signals
  {"large_cap_weight": 0.7, "mid_cap_weight": 0.3} — strategy layer interprets this
```

**Tests:**
1. Large cap weight > mid cap when RS > 1.05
2. Mid cap weight > large cap when RS < 0.95
3. Neutral allocation in neutral band
4. Handles insufficient data (< 63 bars for 3m return)

---

### SPEC: strategies/fo/short_strangle.py

**Purpose:** Sell OTM call + OTM put when IV Rank > 70%. Hedged — always defined risk.

**Libraries:** `pandas`, `numpy`, `mibian`

```python
@dataclass
class FOSignal:
    underlying: str
    strategy: str           # "short_strangle"
    legs: list[dict]        # [{"type": "sell_call", "strike": float, "expiry": str}, ...]
    max_loss: float         # defined loss cap (from hedge legs)
    premium_collected: float
    delta_net: float        # must be within ±0.10 at entry
    theta_daily: float      # daily premium decay
    confidence: float
    timestamp: pd.Timestamp
    reason: str

def generate_fo_signal(
    option_chain_df: pd.DataFrame,
    underlying: str,
    spot_price: float,
    iv_rank: float,
    pcr: float,
    config
) -> FOSignal | None:
```

**Logic:**
```
Entry:
  iv_rank > 70 (expensive options — sell premium)
  AND pcr in [0.8, 1.3] (not extreme directional)
  AND days_to_expiry between 20 and 45 (optimal theta decay zone)
  AND net delta of strangle < ±0.10 (near-neutral)

Strike selection:
  Call: first strike above spot where delta < 0.25
  Put: first strike below spot where |delta| < 0.25

This is a SHORT strangle (undefined risk). To comply with blueprint rule (no naked shorts):
  Add OTM hedge legs:
  - Buy call 2 strikes above sold call (caps upside loss)
  - Buy put 2 strikes below sold put (caps downside loss)
  → This converts it to an Iron Condor (defined risk)

Max loss = (width of spread * lot_size) - premium_collected
```

**Tests:**
1. Signal generated when IV Rank > 70
2. No signal when IV Rank < 70
3. No signal when PCR at extreme (< 0.8 or > 1.3)
4. No signal when DTE < 20 or > 45
5. Strike selection selects correct OTM strikes
6. Net delta < 0.10 verified at entry
7. Max loss is finite (not unlimited — hedge legs present)
8. Returns None on insufficient OI (illiquid strikes)

---

### SPEC: strategies/fo/bull_call_spread.py

**Purpose:** Buy ATM call, sell OTM call. Defined-risk directional in bull regime.

```python
def generate_fo_signal(
    option_chain_df, underlying, spot_price, iv_rank, regime, config
) -> FOSignal | None:

Logic:
  Entry:
    regime == "bull_trend"
    AND iv_rank < 50 (buy options when IV is cheap)
    AND days_to_expiry between 15 and 30

  Leg 1 (buy): ATM call (delta ~0.50)
  Leg 2 (sell): OTM call, 1 strike above (delta ~0.30)

  Max loss = premium paid (defined)
  Max gain = spread width - premium paid
```

**Tests:**
1. Signal in bull regime, low IV
2. No signal in bear regime
3. No signal when IV > 50
4. Correct leg selection (buy ATM, sell OTM)
5. Max loss = premium paid (confirmed finite)

---

### SPEC: strategies/fo/bear_put_spread.py

**Exact mirror of bull_call_spread but with puts. Regime = "bear_trend".**

**Tests:** Mirror of bull_call_spread tests.

---

### SPEC: intelligence/us_regime.py

**Purpose:** Classify US market into 4 regimes: bull_trend, bear_trend, sideways, high_volatility.

**Libraries:** `pandas`, `numpy`, `pandas-ta-classic`

```python
def classify_regime(
    spx_df: pd.DataFrame,     # SPX OHLCV with features (EMA_200, ADX, ATR)
    vix_level: float,
    config
) -> str:
    # Returns one of: "bull_trend", "bear_trend", "sideways", "high_volatility"
    # Logic (evaluated in priority order — first match wins):
    #
    # 1. high_volatility: VIX > 30 AND ATR expansion (current ATR > 1.3x 20-bar ATR avg)
    #
    # 2. bull_trend: SPX close > EMA_200 AND ADX > 25 AND VIX < 20
    #
    # 3. bear_trend: SPX close < EMA_200 AND ADX > 25 AND VIX > 25
    #
    # 4. sideways: ADX < 20 (catch-all — no strong directional trend)
    #
    # Default: "sideways" if no condition matches cleanly
    #
    # Output is appended to df["us_regime"] for downstream feature use

def get_regime_history(spx_df: pd.DataFrame, vix_series: pd.Series, config) -> pd.Series:
    # Applies classify_regime row-by-row
    # Returns pd.Series indexed same as spx_df with regime labels
    # Used for backtesting (regime at each historical bar)
```

**Tests:**
1. VIX > 30 + ATR expansion → "high_volatility"
2. SPX > EMA_200, ADX > 25, VIX < 20 → "bull_trend"
3. SPX < EMA_200, ADX > 25, VIX > 25 → "bear_trend"
4. ADX < 20 → "sideways"
5. VIX > 30 wins over bull_trend conditions (priority order)
6. `get_regime_history` returns Series of correct length
7. Handles insufficient data for EMA_200 (returns "sideways" for early bars)

---

### SPEC: intelligence/india_regime.py

**Purpose:** Classify India market into 4 regimes using India VIX + Nifty + FII data.

**Same interface as us_regime.py but India-specific thresholds.**

```python
def classify_regime(
    nifty_df: pd.DataFrame,
    india_vix: float,
    fii_net: float,        # FII net buy/sell
    config
) -> str:
    # 1. high_volatility: India VIX > 22 AND ATR expansion AND PCR at extremes
    # 2. bull_trend: Nifty > EMA_200 AND ADX > 25 AND India VIX < 15 AND fii_net > 0
    # 3. bear_trend: Nifty < EMA_200 AND ADX > 25 AND India VIX > 20 AND fii_net < 0
    # 4. sideways: ADX < 20
```

**Tests:**
1. Each of the 4 regimes triggered correctly
2. FII sign matters — bear_trend requires fii_net < 0
3. Priority order: high_volatility beats bull/bear
4. Insufficient data handling

---

### SPEC: risk/india/position_sizer.py

**Purpose:** Quarter-Kelly + ATR position sizing for India equity. Same math as US, different config keys.

**Libraries:** `numpy`, `scipy`

**Same interface as risk/us/position_sizer.py. Key differences:**
- Config keys: `INDIA_MAX_RISK_PCT` (1.5%), `INDIA_MAX_POSITION_PCT` (10%)
- Currency: INR (no conversion needed — portfolio in INR)
- Circuit breaker check: if stock is near circuit limit, reduce size by 50% (partial exit may be impossible)

**Function:**
```python
def calculate_position_size(
    signal: Signal,
    portfolio_value_inr: float,
    atr: float,
    price: float,
    config
) -> dict:
    # Returns: {"shares": int, "position_value": float, "risk_amount": float, "approved": bool}
    # Approved=False if: Kelly fraction < 0, ATR=0, shares=0, position > MAX_POSITION_PCT
    # Circuit breaker proximity: if price within 2% of circuit limit, halve the position
```

**Tests:**
1. Normal sizing returns correct shares
2. ATR=0 returns approved=False
3. Position capped at MAX_POSITION_PCT
4. Circuit proximity halves position
5. Negative Kelly → approved=False
6. Portfolio=0 → approved=False, no ZeroDivisionError

---

### SPEC: risk/fo/position_sizer.py

**Purpose:** F&O position sizing. Lot-size aware. Greeks-aware. Stricter than equity (1.0% max risk).

**Libraries:** `numpy`

```python
def calculate_fo_position_size(
    strategy_signal: FOSignal,
    portfolio_value_inr: float,
    lot_size: int,              # e.g. Nifty lot = 25 units
    config
) -> dict:
    # Returns: {"lots": int, "notional_value": float, "max_loss": float, "approved": bool}
    #
    # Sizing rule:
    # max_loss_per_trade = portfolio_value * FOMAX_RISK_PCT (1.0%)
    # lots = floor(max_loss_per_trade / signal.max_loss)
    # Cap: MAX_FO_POSITIONS = 3 simultaneously
    # If lots = 0: approved=False
    # If net portfolio delta after this trade > ±0.30: approved=False (delta limit)
    # If theta_daily > 0.5% of portfolio: alert (not block)
```

**Tests:**
1. Correct lot calculation
2. Lots capped by max_loss constraint
3. Delta limit blocks oversized position
4. approved=False when lots=0
5. Theta alert triggered when threshold exceeded (but not blocked)
6. ZeroDivisionError impossible (lot_size=0 handled)

---

### SPEC: risk/cross_market_allocator.py

**Purpose:** Enforce cross-market portfolio exposure caps. Total portfolio view.

**Libraries:** `pandas`, `numpy`

```python
def check_allocation(
    us_exposure_pct: float,
    india_equity_exposure_pct: float,
    india_fo_exposure_pct: float,
    proposed_market: str,
    proposed_additional_pct: float,
    config
) -> dict:
    # Rules (from blueprint):
    # Total portfolio exposure: max 80% deployed at any time (20% cash buffer)
    # US equity: max 60% of total portfolio
    # India equity: max 50% of total portfolio
    # India F&O: max 20% of total portfolio
    # If proposed trade violates any cap: approved=False with reason
    # Returns: {"approved": bool, "reason": str, "new_exposure": dict}
```

**Tests:**
1. Trade approved when under all caps
2. Trade rejected when US would exceed 60%
3. Trade rejected when India F&O would exceed 20%
4. Trade rejected when total would exceed 80%
5. Zero exposure → any trade approved up to cap
6. Returns correct projected exposure dict

---

### SPEC: risk/realtime_reporter.py

**Purpose:** Compute live P&L and exposure snapshot across all markets.

**Libraries:** `pandas`, `datetime`

```python
@dataclass
class RiskSnapshot:
    timestamp: datetime
    us_pnl: float
    india_equity_pnl: float
    india_fo_pnl: float
    total_pnl: float
    us_drawdown_pct: float
    india_drawdown_pct: float
    total_drawdown_pct: float
    us_exposure_pct: float
    india_equity_exposure_pct: float
    india_fo_exposure_pct: float
    open_positions: int
    alerts: list[str]

def generate_snapshot(
    positions: list[dict],      # open positions with entry_price, current_price, market, size
    portfolio_peaks: dict,      # {"us": float, "india": float, "total": float}
    config
) -> RiskSnapshot:
```

**Tests:**
1. Correct total P&L computed
2. Drawdown calculated correctly vs peak
3. Alert added when drawdown > threshold
4. Zero positions returns clean snapshot
5. Mixed positive/negative P&L sums correctly

---

### SPEC: intelligence/us_ml_model.py

**Purpose:** XGBoost + LSTM ensemble for US equity signal generation. Trained per market, separate weights.

**Libraries:**
- `xgboost` — gradient boosting
- `torch` (PyTorch) — LSTM
- `optuna` — hyperparameter tuning (NOT GridSearchCV)
- `shap` — explainability
- `scikit-learn` — train/val/test split, metrics
- `numpy`, `pandas`

**Architecture:**
```
Input: feature DataFrame from us feature_engineer (≤20 features per blueprint)
Target: 3-class (0=hold, 1=long, 2=short) — computed from forward returns
  long if next_5d_return > +1.5 * ATR_14
  short if next_5d_return < -1.5 * ATR_14
  hold otherwise

XGBoost component:
  Classifier: XGBClassifier(objective="multi:softmax", n_classes=3)
  Tuning: Optuna TPE sampler, 50 trials, walk-forward CV
  Hyperparams tuned: max_depth [3,8], learning_rate [0.01,0.3], n_estimators [100,500],
                     subsample [0.6,1.0], colsample_bytree [0.6,1.0], min_child_weight [1,10]
  Explainability: SHAP TreeExplainer — top 5 feature contributions per prediction

LSTM component:
  Input: last 20 bars as sequence (20 timesteps × n_features)
  Architecture: 2-layer LSTM (hidden=64), dropout=0.2, linear output (3 classes)
  Training: Adam optimizer, CrossEntropyLoss, early stopping (patience=10)
  Tuning: Optuna — hidden_size [32,128], dropout [0.1,0.4], lr [1e-4, 1e-2]

Ensemble:
  Weighted average of softmax probabilities
  Initial weight: XGBoost 0.6, LSTM 0.4 (XGBoost more reliable on daily bars)
  Weights updated monthly by rolling Sharpe of each model's signals independently
  Final prediction: argmax(ensemble_probs)
  Confidence: max(ensemble_probs) — used as Signal.confidence
```

**Functions:**
```python
class USMLModel:
    def train(self, df: pd.DataFrame, config) -> dict:
        # Trains both XGB and LSTM with walk-forward CV
        # Returns: {"xgb_val_accuracy": float, "lstm_val_accuracy": float, "ensemble_val_accuracy": float}
        # Saves models to config.MODEL_DIR / "us_xgb.json" and "us_lstm.pt"

    def predict(self, df: pd.DataFrame) -> dict:
        # Returns: {"direction": int, "confidence": float, "shap_values": dict}
        # direction: 0=hold, 1=long, 2=short
        # Raises if models not trained/loaded

    def load(self, config) -> None:
        # Loads saved models from config.MODEL_DIR

    def save(self, config) -> None:
        # Saves current models
```

**Tests (use synthetic data — no real market data in tests):**
1. `train` runs without error on synthetic DataFrame of 500 rows
2. `predict` returns dict with correct keys
3. direction in {0, 1, 2}
4. confidence in [0.0, 1.0]
5. SHAP values dict has same keys as feature columns
6. `predict` raises if model not trained
7. `save` + `load` roundtrip — predictions identical before and after
8. Optuna runs minimum 5 trials in test (mock reduced to avoid slow CI)

---

### SPEC: intelligence/india_ml_model.py

**Identical architecture to us_ml_model.py. Key differences:**
- Feature columns from India feature_engineer (includes fii_net, dii_net, india_vix)
- Saved as "india_xgb.json" and "india_lstm.pt"
- Model weights NEVER shared with US model — separate class instance, separate files
- class: `IndiaMLModel`

**Tests:** Same 8 tests as US model on India feature columns.

---

### SPEC: intelligence/fo_ml_model.py

**Purpose:** ML model for F&O regime-based signal enhancement. Inputs include Greeks and IV features unique to F&O.

**Architecture:** XGBoost only (no LSTM) — F&O option chains are cross-sectional, not well-suited for sequential modeling.

**Feature input:** All India equity features for underlying + PCR, IV Rank, Max Pain, OI, Greeks.

**Target:** 3-class: 0=no_trade, 1=bullish_setup (buy spread), 2=bearish_setup (sell spread)

**class: `FOMLModel`**

**Tests:**
1. Train on synthetic F&O feature DataFrame
2. Predict returns direction + confidence
3. No LSTM (architecture check — assert no lstm attribute)
4. Save/load roundtrip

---

### SPEC: intelligence/uncertainty_engine.py

**Purpose:** Score confidence per signal per market. Combines ML confidence with regime alignment and market conditions.

**Libraries:** `numpy`

```python
def score_signal(
    ml_confidence: float,       # from MLModel.predict
    regime_match: bool,         # strategy.regime_required == current_regime
    vix_level: float,           # current VIX (US) or India VIX
    market: str,                # "us", "india", "fo"
    config
) -> float:
    # Final confidence = ml_confidence * regime_weight * vol_weight
    # regime_weight: 1.0 if match, 0.5 if mismatch
    # vol_weight: 1.0 if VIX normal, 0.7 if VIX elevated (>25 US / >20 India), 0.4 if extreme (>35 US / >30 India)
    # Output: [0.0, 1.0]
    # Signals with final confidence < config.MIN_CONFIDENCE_THRESHOLD are suppressed (return 0.0)
```

**Tests:**
1. Full confidence with matching regime, normal VIX
2. Halved by regime mismatch
3. Reduced by elevated VIX
4. Suppressed below threshold
5. Never returns negative or >1.0

---

### SPEC: intelligence/signal_ranker.py

**Purpose:** Takes all signals across all markets and ranks by quality. Returns prioritized list.

**Libraries:** `pandas`

```python
def rank_signals(
    signals: list[Signal | FOSignal],
    config
) -> list[Signal | FOSignal]:
    # Ranking criteria (weighted):
    # 1. confidence * 0.50
    # 2. regime_match * 0.30 (1.0 if matched, 0.0 if not)
    # 3. risk/reward * 0.20 — (target / stop distance, capped at 3.0, normalized)
    # Sort descending by composite score
    # Filter: remove signals with confidence < MIN_CONFIDENCE_THRESHOLD
    # Max signals returned: config.MAX_CONCURRENT_SIGNALS (default 10 total, 5 US + 3 India + 2 FO)
    # Returns ranked list, best signal first
```

**Tests:**
1. High confidence signal ranked above low confidence
2. Regime match boosts rank
3. Signals below threshold filtered out
4. Max signal cap enforced
5. Empty input returns empty list (not exception)
6. Mixed market signals ranked correctly

---

### SPEC: decision/meta_strategy.py

**Purpose:** Maps current regime to appropriate strategies per market.

**Libraries:** stdlib only

```python
REGIME_STRATEGY_MAP = {
    "us": {
        "bull_trend":      ["us_momentum", "us_trend_following", "us_breakout"],
        "bear_trend":      ["us_mean_reversion", "us_trend_following"],
        "sideways":        ["us_mean_reversion", "us_sector_rotation"],
        "high_volatility": ["us_mean_reversion"],  # defensive
    },
    "india": {
        "bull_trend":      ["india_momentum", "india_trend_following", "india_breakout"],
        "bear_trend":      ["india_mean_reversion", "india_trend_following"],
        "sideways":        ["india_mean_reversion", "india_index_rotation"],
        "high_volatility": ["india_mean_reversion"],
    },
    "fo": {
        "bull_trend":      ["bull_call_spread"],
        "bear_trend":      ["bear_put_spread"],
        "sideways":        ["short_strangle"],
        "high_volatility": [],  # No F&O trades in extreme volatility
    },
}

def get_active_strategies(market: str, regime: str) -> list[str]:
    # Returns list of strategy names to run for this market/regime combo

def should_trade_fo(india_regime: str, india_vix: float) -> bool:
    # No F&O in high_volatility regime OR India VIX > 22
    # Returns bool
```

**Tests:**
1. Correct strategies returned for each market/regime combo
2. Empty list for fo in high_volatility
3. `should_trade_fo` False when India VIX > 22
4. Unknown regime returns empty list (not exception)

---

### SPEC: decision/engine.py

**Purpose:** Final go/no-go decision integrating all layers. Produces a tradeable order or rejection.

**Libraries:** `dataclasses`, `datetime`, stdlib

```python
@dataclass
class TradeDecision:
    approved: bool
    signal: Signal | FOSignal | None
    reason: str            # human-readable full explanation
    risk_check_passed: bool
    regime_check_passed: bool
    confidence_threshold_passed: bool
    timestamp: datetime
    market: str

def evaluate(
    signal: Signal | FOSignal,
    regime: str,
    risk_snapshot: RiskSnapshot,
    config
) -> TradeDecision:
    # Gate 1: Active strategies check (meta_strategy says this strategy is active in this regime)
    # Gate 2: Confidence threshold (signal.confidence >= MIN_CONFIDENCE_THRESHOLD)
    # Gate 3: Cross-market allocator (risk/cross_market_allocator.py)
    # Gate 4: Drawdown guardian not halted for this market
    # Gate 5: Kill switch not active for this market
    # All gates must pass for approved=True
    # First gate failure → approved=False with reason, stops checking remaining gates
```

**Tests:**
1. All gates pass → approved=True
2. Low confidence → approved=False, reason mentions confidence
3. Drawdown guardian halted → approved=False
4. Kill switch active → approved=False
5. Allocation cap breached → approved=False
6. Wrong regime for strategy → approved=False
7. Gate failure reason is human-readable string

---

### SPEC: decision/explainability.py

**Purpose:** Generate human-readable explanation for every trade decision (approved or rejected).

**Libraries:** stdlib, `shap` (for ML prediction logs)

```python
def generate_explanation(
    decision: TradeDecision,
    shap_values: dict | None,
    config
) -> str:
    # Returns multi-line string explanation, e.g.:
    # "APPROVED: india_momentum signal on RELIANCE
    #  Regime: bull_trend ✓
    #  Confidence: 0.82 (threshold: 0.60) ✓
    #  Top ML drivers: RSI_14 (+0.12), EMA_crossover (+0.09), FII_net (+0.07)
    #  Risk: 1.3% of portfolio | Stop: ₹2,450 | Entry: ₹2,510
    #  Portfolio exposure after trade: US 40%, India 28%, F&O 8%, Total 76%"

def log_decision(decision: TradeDecision, explanation: str, config) -> None:
    # Appends to audit_trail with event_type = "TRADE_APPROVED" or "TRADE_REJECTED"
    # Also writes to daily explainability log file: logs/decisions/YYYY-MM-DD.log
```

**Tests:**
1. Approved decision generates explanation with "APPROVED"
2. Rejected decision generates explanation with "REJECTED" and reason
3. SHAP values appear in explanation when provided
4. `log_decision` writes to audit trail
5. Explanation is non-empty for all cases

---

### SPEC: execution/alpaca_engine.py

**Purpose:** Execute trades on Alpaca (US market). Paper mode by default. Live mode toggled via config.

**Libraries:** `alpaca-py` (alpaca.trading.client, alpaca.trading.requests)

**Mock strategy:** `TradingClient` injected. Tests use MagicMock.

```python
class AlpacaEngine:
    def __init__(self, trading_client, config):
        # trading_client: injected (TradingClient or mock)
        # config.ALPACA_PAPER_MODE: bool

    def submit_order(self, decision: TradeDecision) -> dict:
        # Converts TradeDecision to Alpaca MarketOrderRequest
        # Sets stop-loss via bracket order (stop_price from signal.stop_price)
        # Returns: {"order_id": str, "status": str, "filled_price": float | None}
        # On failure: logs + raises (caller handles kill switch)

    def cancel_all_orders(self, market: str = "us") -> int:
        # Cancels all open orders. Returns count cancelled.

    def get_positions(self) -> list[dict]:
        # Returns current open positions from Alpaca

    def close_position(self, symbol: str) -> dict:
        # Closes position for symbol
```

**Tests (mocked):**
1. `submit_order` calls Alpaca client with correct params
2. Stop-loss included in order
3. `cancel_all_orders` calls cancel on all open orders
4. Failure in `submit_order` is logged + re-raised
5. Paper mode uses same code path as live (only credentials differ)

---

### SPEC: execution/india_simulator.py

**Purpose:** Paper trading simulator for India market. Uses live Angel One data for prices, simulates fills internally. No real orders placed.

**Libraries:** `pandas`, `numpy`, `datetime`

```python
class IndiaSimulator:
    def __init__(self, config):
        self.open_positions: dict = {}
        self.trade_log: list[dict] = []

    def simulate_fill(
        self,
        decision: TradeDecision,
        current_price: float,
        bid: float,
        ask: float
    ) -> dict:
        # Fill price = mid-point ± 100–300ms latency simulation
        # Slippage: 0.05% of fill price added to cost
        # Returns: {"fill_price": float, "slippage_cost": float, "timestamp": datetime}

    def close_position(self, symbol: str, current_price: float) -> dict:
        # Simulates exit fill, calculates P&L, removes from open_positions

    def get_portfolio_pnl(self, current_prices: dict[str, float]) -> float:
        # MTM P&L on all open positions
```

**Tests:**
1. `simulate_fill` adds slippage correctly
2. Fill price within bid-ask spread
3. `close_position` calculates correct P&L
4. `get_portfolio_pnl` sums across positions
5. Closing non-existent position raises (not silent)

---

### SPEC: execution/order_manager.py

**Purpose:** Unified order tracking across all markets. Single source of truth for all open positions.

**Libraries:** `SQLAlchemy`, `datetime`

```python
class OrderManager:
    # SQLite-backed: table "orders" with: order_id, market, symbol, strategy, direction,
    #                entry_price, stop_price, size, status, open_time, close_time, pnl,
    #                regime_at_entry, confidence_at_entry

    def record_order(self, decision: TradeDecision, fill: dict) -> str:
        # Returns order_id

    def close_order(self, order_id: str, exit_price: float, reason: str) -> dict:
        # Updates status, computes P&L, returns summary

    def get_open_orders(self, market: str | None = None) -> list[dict]:
        # Returns all OPEN orders, optionally filtered by market

    def get_performance_summary(self, market: str | None = None) -> dict:
        # Returns: {"total_trades": int, "win_rate": float, "avg_pnl": float,
        #           "sharpe": float, "max_drawdown": float}
```

**Tests:**
1. `record_order` persists to SQLite
2. `close_order` updates status and P&L
3. `get_open_orders` filters by market correctly
4. `get_performance_summary` computes correct win_rate
5. Sharpe computed correctly on known trade history
6. Empty order book → summary returns zeros (not exception)

---

### SPEC: learning/performance_tracker.py

**Purpose:** Track per-trade, per-strategy, per-market performance over time.

**Libraries:** `pandas`, `SQLAlchemy`

```python
def record_trade_outcome(
    order_summary: dict,    # from order_manager.close_order
    db_path: str
) -> None:
    # Appends to "trade_outcomes" table
    # Columns: order_id, market, strategy, regime_at_entry, direction,
    #           entry_price, exit_price, pnl, pnl_pct, hold_days, timestamp

def get_strategy_performance(
    strategy: str,
    market: str,
    lookback_days: int,
    db_path: str
) -> dict:
    # Returns: {"sharpe": float, "win_rate": float, "avg_pnl": float,
    #           "trade_count": int, "max_drawdown": float}
    # Uses only trades within lookback_days window

def get_regime_performance(market: str, db_path: str) -> pd.DataFrame:
    # Returns DataFrame: regime × strategy → avg Sharpe
    # Used to update REGIME_STRATEGY_MAP weights
```

**Tests:**
1. `record_trade_outcome` persists correctly
2. `get_strategy_performance` returns correct Sharpe on known trade history
3. Empty result returns zeros (not exception)
4. Lookback window filters correctly (trades outside window excluded)
5. `get_regime_performance` produces correct regime × strategy matrix

---

### SPEC: learning/drift_detector.py

**Purpose:** Detect model staleness using ADWIN algorithm from `river` library.

**Libraries:**
- `river` — ADWIN drift detection (pip install river). VERIFY on build: last release within 18 months.
- `numpy`

```python
class DriftDetector:
    def __init__(self, market: str, config):
        # Creates river.drift.ADWIN() instance per market
        # ADWIN parameters: delta=0.002 (standard for financial data)

    def update(self, model_error: float) -> bool:
        # Feed latest prediction error to ADWIN
        # model_error = |predicted_direction - actual_direction| (0 or 1)
        # Returns True if drift detected (retraining needed)

    def reset(self) -> None:
        # Reset ADWIN detector after retraining completes

    def get_drift_status(self) -> dict:
        # Returns: {"in_drift": bool, "in_warning": bool, "n_updates": int}
```

**Tests:**
1. No drift on stable error sequence
2. Drift detected after injected error spike
3. `reset` clears drift state
4. `get_drift_status` returns correct dict structure
5. Each market gets independent detector (US drift doesn't affect India)

---

### SPEC: learning/retrainer.py

**Purpose:** Trigger and execute model retraining when drift detected or monthly schedule hit.

**Libraries:** `schedule` (pip install schedule), `datetime`, stdlib

```python
class Retrainer:
    def __init__(self, market: str, ml_model, drift_detector: DriftDetector, config):
        # ml_model: USMLModel, IndiaMLModel, or FOMLModel (injected)

    def check_and_retrain(self, latest_data: pd.DataFrame) -> bool:
        # Returns True if retrain happened
        # Triggers if: drift_detector.update() returns True
        #           OR monthly schedule hit (first Monday of month)
        # Before retraining: backs up current model to config.MODEL_DIR/backup/
        # After retraining: validates new model Sharpe > old model Sharpe - 0.1
        # If validation fails: restore backup, log WARNING, alert

    def force_retrain(self, data: pd.DataFrame) -> None:
        # Immediate retrain (for manual trigger or hotfix)
```

**Tests (ml_model mocked):**
1. Retrain triggered on drift signal
2. Retrain triggered on monthly schedule (mock datetime)
3. Backup created before retrain
4. Validation failure restores backup
5. `force_retrain` bypasses schedule check
6. Different markets retrain independently

---

### SPEC: learning/strategy_graveyard.py

**Purpose:** Retire underperforming strategies. Archive, don't delete. Prevent reactivation without review.

**Libraries:** `pandas`, `json`, stdlib

```python
class StrategyGraveyard:
    # JSON-backed: config.GRAVEYARD_PATH / "graveyard.json"

    def evaluate_strategy(
        self,
        strategy_name: str,
        performance: dict,    # from performance_tracker.get_strategy_performance
        config
    ) -> str:
        # Returns: "active", "warning", "retired"
        # warning: 30-day Sharpe < 0.3 (alert, don't retire yet)
        # retired: 60-day Sharpe < 0.0 (consistently losing) OR 30-day Sharpe < 0.0 (immediate)

    def retire(self, strategy_name: str, reason: str) -> None:
        # Moves strategy to graveyard.json with timestamp and reason
        # Logs to audit_trail event_type="STRATEGY_RETIRED"
        # Sends Telegram alert

    def is_active(self, strategy_name: str) -> bool:
        # Returns False if strategy is in graveyard
        # Called by meta_strategy before activating a strategy

    def get_graveyard(self) -> list[dict]:
        # Returns all retired strategies with reasons
```

**Tests:**
1. `evaluate_strategy` returns "active" for good Sharpe
2. Returns "warning" for Sharpe in warning zone
3. Returns "retired" for negative Sharpe
4. `retire` writes to JSON file
5. `is_active` returns False for retired strategy
6. `retire` calls audit_trail + alert

---

## POST-BUILD SELF-REVIEW (mandatory after every module)

After tests pass:

1. **Intent check** — Does the implementation do what the spec intends, not just what it literally says?
2. **Edge case check** — Empty input, None values, network timeout, malformed data?
3. **Interface check** — Does output exactly match what next module expects?
4. **Reliability check** — Would this survive 30 days continuous without intervention?

Flag real problems in `FLAGGED_ISSUES.md`. Fix before stopping if no spec change needed.

---

## COMPLETION REPORT FORMAT

After every module is complete and all tests pass, do THREE things in order:

### 1. Print to Terminal (Structured Checkpoint)

This is the moment Puneeth reviews your work before you move on. Be precise:

```
✅ SESSION COMPLETE — <module_name>

Built: <full_path_to_file>
Tests: <X> passed, 0 failed
Code Quality: ruff PASS | black PASS
Lines of code: ~<N> (informational)
Dependencies added: <list or "none">

Self-Review:
  Intent check: ✅ PASS / 🔴 FLAG [reason]
  Edge cases: ✅ PASS / 🔴 FLAG [reason]
  Interface alignment: ✅ PASS / 🔴 FLAG [reason]
  Reliability: ✅ PASS / 🔴 FLAG [reason]

Overall status: CLEAN / FLAGGED

Mock status: FULL_MOCK / PARTIAL_MOCK / NO_MOCK_NEEDED
Deviations from spec: [none] or [list exactly what changed and why]
Flags raised: [none] or [summary of issues, all tracked in FLAGGED_ISSUES.md]

Next session: <next_module_from_BUILD_ORDER>
```

Why this format?
- **Tests:** Proves the module works
- **Code quality:** Ensures it's readable and maintainable
- **Self-review:** Shows you caught bugs before Puneeth did
- **Deviations:** Transparency — if you deviated from spec (libraries, design), say so
- **Flags:** Everything flagged goes to FLAGGED_ISSUES.md — nothing is lost

### 2. Update SESSION_STATE.md (One-Line State Machine)

Overwrite the entire file with exactly one line. This is the system's memory of where you are:

**Normal completion:**
```
BUILT: <module_path> | STATUS: DONE | NEXT: <next_module_path>
```

**All phases complete:**
```
BUILT: <last_module> | STATUS: DONE | NEXT: ALL_DONE
```

**Hotfix mode (if Puneeth triggered it):**
```
HOTFIX: <module_path> | REASON: <why> | CHANGE: <what_changed> | NEXT: <resume_from>
```

### 3. Update README.md Build Status Table (One Row)

Find the matching row in README.md's "Build Status" table. Update it with:
- Status: ✅ DONE
- Tests: `<X> passed`
- Notes: Library info, deviations, or flag summary (one line max)

Example:
```
| markets/india/token_manager.py | ✅ DONE | 10 passed | FULL_MOCK — pyotp TOTP; smartapi-python 1.5.5 |
```

---

### Why Three Checkpoints?

1. **Terminal report** is for Puneeth to verify the work
2. **SESSION_STATE.md** is for the system to know where to resume
3. **README.md table** is for you (and Puneeth) to see project progress at a glance

All three must be updated before you stop. No exceptions.

---

## AFTER EVERY SESSION — UPDATE README.md

Update four sections only:
1. Build Status table row
2. Last Session block
3. Next Session block
4. Known Issues (sync from FLAGGED_ISSUES.md)

---

## AFTER EVERY SESSION — APPEND TO AAATS_MASTER_BLUEPRINT.md CHANGE LOG

Append one entry to `## Change Log` section. Format:
```
### [DATE] — Session: <module_built>
- Built: <module_path>
- Tests: <X passed, 0 failed>
- Mock status: <FULL_MOCK / NO_MOCK_NEEDED>
- Deviations from spec: <none or describe>
- Flags raised: <none or summary>
- Libraries used: <list>
- Approved by: Puneeth
```

---

## HOTFIX MODE

If SESSION_STATE.md starts with `HOTFIX:`:
1. Read the HOTFIX line
2. Read only that module
3. Make surgical change only
4. Re-run tests — all must pass
5. Write: `BUILT: <module> | STATUS: HOTFIX_DONE | NEXT: <resume_from>`

---

## TOKEN WASTE RULES

STOP and tell me before:
- Loading a file >200 lines you already read this session
- Rewriting a file that exists and has passing tests
- Building anything not in current session's spec
- Refactoring working code

---

## STANDARDIZATION RULES (non-negotiable, every module)

**Logging:** market-tagged, JSON, Loguru. Never print().
**Error handling:** try/except with specific exception types. Always log full traceback.
**Data contracts:** Validate required DataFrame columns at top of every function.
**Security:** No secrets in code. All from config/.env only.
**Performance:** All network calls have timeout=30s. DataFrames tested with 10k rows.
**Mocking:** All external API calls (Angel One, Alpaca, FRED) behind injected clients. Tests never make real network calls.
