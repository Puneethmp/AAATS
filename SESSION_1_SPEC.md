# AAATS — Session 1 Spec
## Module: `risk/us/position_sizer.py`
## Date: April 2026 | Approved by: Puneeth

---

## DEVIATION FROM BLUEPRINT — LOGGED

**Change:** Risk Engine built before Strategy Pool (blueprint Phase 5 → moved to now)
**Justification:** Backtests without position sizing produce Sharpe numbers that don't reflect real capital deployment. Position size directly affects transaction cost calculations and drawdown metrics. Building risk engine first means every backtest from Session 3 onward produces valid metrics.
**Owner sign-off:** Puneeth — April 2026
**Section 15 compliant:** Yes

---

## PRE-BUILD VALIDATION (Claude Code runs this before writing any code)

### 1. Library Check
```
pip show scipy        # for Kelly math — stdlib math is insufficient for edge cases
pip show numpy        # already installed, confirm version
pip show pandas       # already installed, confirm version
```

If scipy not present: `pip install scipy` — add to requirements.txt.
No other new libraries required. Quarter-Kelly math is implementable in pure Python + numpy but scipy's statistical functions make edge case handling cleaner.

### 2. Spec Integrity Check
Confirm these exist before building:
- `markets/us/storage.py` — position sizer reads ATR from feature store
- `markets/us/feature_engineer.py` — ATR(14) must be a computed feature
- `core/config.py` (or equivalent) — portfolio allocation constants must be accessible

If any are missing or ATR(14) is not in the feature set, STOP and write to FLAGGED_ISSUES.md.

### 3. Reliability Check
- Quarter-Kelly formula: verified mathematical approach, survivable losing streaks
- ATR(14): standard, well-tested volatility measure for stop placement
- No external API calls in this module — pure computation, no network dependency

---

## MODULE SPECIFICATION

### File: `risk/us/position_sizer.py`

### Purpose
Computes the number of shares to buy/sell for a US equity trade given:
- Current portfolio value (US allocation only)
- Signal entry price
- ATR(14) for the symbol at signal time
- Win rate estimate (from strategy metadata, defaults to 0.52 if unknown)
- Edge estimate (average win / average loss ratio, defaults to 1.5 if unknown)

Returns: shares to trade, stop-loss price, risk amount in USD, rejection reason if any rule is violated.

### Class Interface

```python
@dataclass
class SizingInput:
    symbol: str
    entry_price: float          # signal entry price (USD)
    atr_14: float               # ATR(14) at signal time — from feature store
    portfolio_value: float      # total US portfolio allocation (USD)
    win_rate: float = 0.52      # strategy win rate estimate (0.0–1.0)
    edge_ratio: float = 1.5     # avg_win / avg_loss ratio
    atr_multiplier: float = 2.0 # stop distance = atr_multiplier × ATR

@dataclass  
class SizingOutput:
    symbol: str
    shares: int                 # always integer — no fractional shares
    entry_price: float
    stop_price: float           # entry_price - (atr_multiplier × atr_14) for long
    risk_per_share: float       # entry_price - stop_price
    total_risk_usd: float       # shares × risk_per_share
    position_value_usd: float   # shares × entry_price
    risk_pct_of_portfolio: float # total_risk_usd / portfolio_value
    position_pct_of_portfolio: float # position_value_usd / portfolio_value
    approved: bool
    rejection_reason: str | None  # None if approved
```

### Core Logic — Quarter-Kelly + ATR

```
Step 1: Kelly fraction
  kelly_f = win_rate - (1 - win_rate) / edge_ratio

Step 2: Quarter-Kelly (safety scaling)
  quarter_kelly_f = kelly_f / 4

Step 3: Risk amount in USD (capped at 1.5% of portfolio)
  kelly_risk_usd = quarter_kelly_f × portfolio_value
  max_risk_usd = 0.015 × portfolio_value
  risk_usd = min(kelly_risk_usd, max_risk_usd)

Step 4: Stop distance (ATR-based)
  stop_distance = atr_multiplier × atr_14
  stop_price = entry_price - stop_distance  (long position)

Step 5: Shares
  risk_per_share = stop_distance
  raw_shares = risk_usd / risk_per_share
  shares = floor(raw_shares)  # always round DOWN, never up

Step 6: Position value
  position_value = shares × entry_price

Step 7: Concentration check
  position_pct = position_value / portfolio_value
  if position_pct > 0.10: reject — concentration limit
```

### Validation Rules (all must pass or return approved=False)

| Rule | Check | Rejection Reason |
|---|---|---|
| Minimum shares | shares >= 1 | "Position too small: 0 shares computed" |
| Max risk per trade | risk_pct_of_portfolio <= 1.5% | "Risk {x}% exceeds 1.5% max" |
| Max position size | position_pct_of_portfolio <= 10% | "Position {x}% exceeds 10% concentration limit" |
| Valid ATR | atr_14 > 0 | "Invalid ATR: must be > 0" |
| Valid entry price | entry_price > 0 | "Invalid entry price" |
| Valid portfolio value | portfolio_value > 0 | "Invalid portfolio value" |
| Win rate range | 0 < win_rate < 1 | "Win rate must be between 0 and 1" |
| Negative Kelly guard | kelly_f > 0 | "Negative Kelly: strategy has no edge at these parameters" |
| Stop price positive | stop_price > 0 | "Stop price is negative — ATR too large relative to entry price" |

### Negative Kelly Handling
If kelly_f <= 0 (win_rate too low for the edge_ratio), the system has no mathematical edge.
Do NOT default to some arbitrary size. Return approved=False with reason "Negative Kelly: strategy has no edge at these parameters". This is a hard stop — not a soft warning.

---

## TEST SPECIFICATION

### File: `tests/test_risk/test_us_position_sizer.py`

Minimum 8 tests. All must pass before session ends.

| Test | Scenario | Expected |
|---|---|---|
| test_normal_sizing | Standard input, win_rate=0.55, edge=1.5, ATR=2.0, price=100, portfolio=100000 | approved=True, shares>0, risk_pct<=1.5%, position_pct<=10% |
| test_max_risk_cap | Kelly output exceeds 1.5% — verify it is capped, not rejected | approved=True, risk_pct exactly 1.5% |
| test_concentration_limit | High price + large portfolio → position would exceed 10% | approved=False, rejection_reason contains "concentration" |
| test_zero_shares | Very high price, very small portfolio, very tight ATR → 0 shares | approved=False, rejection_reason contains "too small" |
| test_negative_kelly | win_rate=0.30, edge_ratio=1.0 → kelly_f < 0 | approved=False, rejection_reason contains "Negative Kelly" |
| test_invalid_atr | atr_14=0 | approved=False, rejection_reason contains "Invalid ATR" |
| test_stop_price_calculation | Verify stop_price = entry_price - (atr_multiplier × atr_14) exactly | stop_price correct to 4 decimal places |
| test_shares_floor | raw_shares = 10.9 → shares = 10, never 11 | shares == 10 |

---

## POST-BUILD SELF-REVIEW (Claude Code runs this after writing code)

1. **Intent check:** Does the sizer always return fewer shares when ATR is high? (Higher volatility = smaller position — this is the core safety property. Verify with two test calls.)

2. **Edge cases:** What happens when entry_price = stop_price? (Division by zero in risk_per_share.) Ensure this is caught before the division.

3. **Interface contract:** SizingOutput.approved is always explicitly set — never left as default. Confirm.

4. **30-day survivability:** This module has zero network calls, zero database calls, zero file I/O. It is pure computation. It will not break due to external failures. Confirm this is true of the final code.

5. **Blueprint compliance check:** Confirm 1.5% max risk and 10% concentration limit are hardcoded constants, not magic numbers — they must be named constants at the top of the file (e.g., `MAX_RISK_PCT = 0.015`).

---

## SESSION OUTPUT REQUIREMENTS

Claude Code must produce before ending the session:

1. `risk/__init__.py` — empty, marks package
2. `risk/us/__init__.py` — empty, marks package
3. `risk/us/position_sizer.py` — full implementation
4. `tests/test_risk/__init__.py` — empty
5. `tests/test_risk/test_us_position_sizer.py` — all 8 tests passing
6. Updated `SESSION_STATE.md` — next session = drawdown_guardian
7. Appended `BLUEPRINT.md` Change Log entry for this session
8. Updated `README.md` build status table

---

## SESSION_STATE.md — Write This After Session Ends

```
CURRENT_SESSION=COMPLETE
NEXT_MODULE=risk/us/drawdown_guardian.py
NEXT_SESSION=2
PHASE=RISK_ENGINE
BLOCKED=FALSE
LAST_BUILD=risk/us/position_sizer.py
TESTS_PASSING=82+  # update with actual count
```

---

## FLAGGED_ISSUES.md — Pre-Existing Flag to Carry Forward

```
[OPEN] [2026-04-27] [markets/us/storage.py] [NEEDS_REVIEW]
SQLite correct for Phase 1–3. DuckDB analytics layer required in Phase 2 for 
cross-symbol backtesting queries. Add DuckDB as read-only analytics layer 
alongside SQLite when backtesting engine is built in Session 3.
Status: OPEN — action deferred to Session 3
```

```
[OPEN] [2026-04-27] [BLUEPRINT.md Section 4] [STALE_DOC]
Intelligence Stack table lists `pandas-ta` as locked. Actual library in use is 
`pandas-ta-classic` (import: pandas_ta_classic). Blueprint must be corrected.
Status: OPEN — correction pending owner approval to edit blueprint
```
