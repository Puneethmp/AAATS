# AAATS Streamlit Web Application Specification

**Version:** 1.0 | **Date:** 2026-04-29 | **Status:** APPROVED FOR BUILD | **Tokens:** ~58k

---

## OVERVIEW

A real-time trading dashboard built with Streamlit that provides complete visibility into the AAATS autonomous trading system. Used for paper trading (May 8 - July 8) and live trading (August+).

**Key Features:**
- Real-time position tracking (updates every 30 seconds)
- Performance analytics (win rate, Sharpe ratio, monthly returns)
- Investment guide (calculator + procedures)
- Strategy details (entry/exit rules, backtest results)
- Risk monitoring (drawdown %, kill switch status)
- Account settings (paper/live toggle, credentials, parameters)
- Trade export (CSV, PDF reports)

---

## ARCHITECTURE

```
Streamlit Web App (Frontend)
      ↓
SQLite Database (Read-only proxy)
      ↓
Trading Engine (Writers)
      ↓
Broker APIs (Alpaca, Angel One)
```

**Data flow:**
1. Trading engine executes trades → writes to SQLite
2. Web app reads SQLite every 30 seconds (read-only)
3. User sees live P&L, positions, alerts

---

## PAGE 1: DASHBOARD (Real-Time Portfolio)

### Purpose
Show current account status, positions, and equity curve at a glance.

### Components

**A. Sidebar (Fixed, always visible)**
```
AAATS Trading Dashboard
━━━━━━━━━━━━━━━━━━━━━━
📊 Dashboard
📈 Performance Analytics  
💡 Investment Guide
🎯 Strategy Details
⚠️ Risk & Alerts
⚙️ Settings & Account
📄 Reports & Export

🔴 System Status: HEALTHY
├─ Alpaca: ✅
├─ Angel One: ✅ (TOTP: expires in 12h)
└─ Database: ✅

🔴 HALT ALL MARKETS [Red button - prominent]
```

**B. Main Content**

*Hero Metrics (Top row, large numbers)*
```
┌──────────────────────────────────────────────────────┐
│ Total P&L        Account Balance      Drawdown        │
│ +$1,245 (+6.2%)  $98,755 / $100k     8.5% / 20%      │
│ USD: +$847       Capital Deployed    ▓▓▓░░░░░░░░     │
│ INR: +₹10,234    $40,000 (40%)                        │
└──────────────────────────────────────────────────────┘
```

*Equity Curve (Interactive Plotly chart)*
```
Plot: Cumulative portfolio value over time
- X-axis: Date/time
- Y-axis: Dollar value
- Line: Smooth curve from start date to today
- Hover: Show date + value
- Zoom/pan: Interactive
```

*Active Positions Table*
```
Symbol | Market | Strategy      | Entry    | Current  | ATR Stop | Unrealized P&L | % Return
AAPL   | US     | US Momentum   | $150.23  | $152.45  | $148.50  | +$222          | +1.5%
RELIANCE | India | India Mom.   | ₹2543    | ₹2612    | ₹2500    | +₹6,900        | +2.7%
BTC    | Crypto | Crypto Grid   | $42100   | $43200   | $41000   | +$1100         | +2.6%
```

*Today's Trades Log (Last 10 trades)*
```
Entry Time | Symbol | Type    | Entry    | Exit     | P&L    | Duration | Status
14:32:15   | MSFT   | Long    | $380.50  | $382.10  | +$160  | 18 min   | ✅ Closed
14:15:22   | INFY   | Short   | ₹1843    | ₹1840    | +₹300  | 12 min   | ✅ Closed
14:01:45   | ETH    | Long    | $2250    | $2245    | -$500  | 22 min   | ✅ Closed (Loss)
```

*Market Regime Tags (Prominent)*
```
🟢 US: BULL_TREND (Confidence: 87%)
🟡 India: HIGH_VOLATILITY (VIX: 16.3)
🔵 Crypto: RANGE_BOUND (PCR: 0.95)
```

---

## PAGE 2: PERFORMANCE ANALYTICS

### Purpose
Detailed trading statistics to evaluate strategy effectiveness and readiness for live trading.

### Components

**Win Rate & Metrics (Summary cards)**
```
┌──────────────────────────────────────────────────┐
│ Win Rate       Avg Win        Avg Loss           │
│ 64%            +$145          -$80               │
│ (23W/13L)      Profit Factor: 1.81               │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ Sharpe Ratio   Sortino Ratio  Max Drawdown       │
│ 1.45           1.92           -12.5%             │
│ (Risk-adjusted returns excellent)                 │
└──────────────────────────────────────────────────┘
```

**Monthly Returns Chart (Bar chart)**
```
Bar chart: Every month showing total profit/loss
- Green bars: Profitable months
- Red bars: Loss months
- Hover: Show exact amount
- Include month name + year
```

**Best/Worst Trades**
```
Largest Win: +$892 (TSLA, May 1)
Largest Loss: -$456 (AMD, May 3)
Longest Trade: 2.5 hours (GOOGL)
Shortest Trade: 4 minutes (MSFT)
```

**Strategy Performance Breakdown**
```
Strategy              Trades | Win%  | Avg P&L | Sharpe
US Momentum           34     | 65%   | +$42    | 1.2
India Momentum        28     | 61%   | +$38    | 0.9
Crypto Grid           12     | 72%   | +$145   | 1.8
───────────────────────────────────────────────────
TOTAL                 74     | 64%   | +$55    | 1.45
```

**Drawdown Over Time (Area chart)**
```
Chart: Cumulative peak-to-trough decline
- X-axis: Date
- Y-axis: Drawdown %
- Area: Red shaded area showing water mark
- Max drawdown line: Horizontal red line at -12.5%
```

---

## PAGE 3: INVESTMENT GUIDE

### Purpose
Educate user on how to invest, expected returns, risk breakdown, and step-by-step procedures.

### Components

**A. Investment Calculator (Interactive - POST-TAX FOCUS)**
```
Question 1: "How much capital can you invest?"
Input: ₹50,000
↓
Question 2: "Choose your brokers:"
☑ Angel One (India) ☑ Binance (Crypto) ☑ Alpaca (US)
↓
Question 3: "Target monthly return % (BEFORE taxes)?"
Input: 10%
↓
System calculates and shows (PRIMARY OUTPUT):

GROSS RETURNS (Before taxes):
├─ Capital: ₹50,000
├─ Target monthly return: 10% = ₹5,000/month
├─ Expected annual: +₹60,000 = 120% return

TAX LIABILITY (This is what matters):
├─ Angel One (40% allocation):
│  ├─ Capital gains tax (30% short-term): -₹600/month
│  └─ After-tax profit: ₹1,400/month
├─ Binance (35% allocation):
│  ├─ TDS (30% on transactions > ₹50k): -₹525/month
│  └─ After-tax profit: ₹1,225/month
├─ Alpaca (15% allocation):
│  ├─ Withholding tax (20-30%): -₹225/month
│  └─ After-tax profit: ₹525/month
├─ Reserve (10% allocation):
│  └─ No trading: ₹0 tax

NET PROFIT (After-tax, REALISTIC):
├─ Expected monthly NET: ₹3,150 (63% of gross)
├─ Expected annual NET: ₹37,800
├─ Effective tax rate: 37%
└─ ✅ Recommendation: Safe and legal

Position sizing (auto-calculated):
├─ Max loss per trade: 2% = ₹1,000
├─ Max portfolio risk: 20% = ₹10,000 (kill switch triggers at this)
└─ Position size per trade: ₹500-2,000 (auto-adjusted for volatility)

Tax calendar:
├─ Monthly: Reconcile trades + TDS paid
├─ Quarterly: Review estimated annual liability
├─ July 31: File ITR-2 with all broker statements
└─ Remember: Keep records for 7 years!

[Adjust capital] [Adjust return target] [View tax breakdown]
```

**Key Difference:** Previous calculator showed GROSS. This shows NET (after-tax). Most important because you see what actually hits your bank account.

**B. Paper Trading Checklist**
```
✅ Week 1: Basic trades execute consistently
   └─ Current: 34 trades executed, 0 errors
✅ Week 2-4: Profitable in multiple market types
   └─ Current: BULL +12%, RANGE +8%, VOLATILE +5%
✅ Tax compliance understanding complete
   └─ Review: LEGAL_COMPLIANCE.md ✓
   └─ Understand: ITR-2 filing, TDS tracking
   └─ Verified: Post-tax profit calculations in Investment Guide
⏳ Month 2: Risk engine tested, zero false positives
   └─ Current: Day 23/30 - On track
⏳ Risk validation: 3+ months before live trading

Progress: 75% of paper trading checklist complete
Estimated ready for live trading: June 15, 2026

⚠️ CRITICAL: Before going live, ensure you understand:
   - Tax liability for your expected annual profit
   - TDS certificates from each broker
   - ITR-2 filing deadlines (July 31)
   - Record retention (7 years)
```

**C. Investment Procedure (Step-by-step)**

*Step 1: Open Broker Accounts*
```
Requirement: Real brokerage accounts for actual trading

Alpaca (US Market):
- Go to: https://app.alpaca.markets
- Sign up (takes 5 minutes)
- Minimum deposit: $0 for paper, $1 for margin
- Link in AAATS settings → [Connect Alpaca Account]

Angel One (India Market):
- Go to: https://www.angelone.in
- Sign up (takes 10 minutes, requires Aadhaar)
- Minimum deposit: ₹0 for paper, ₹500 for live
- Link in AAATS settings → [Connect Angel One Account]
```

*Step 2: Fund Your Account (When Ready for Live Trading)*
```
When: After 2+ months profitable paper trading
Amount: $500-1000 (start small)

Alpaca Funding:
1. Log into Alpaca → Account → Transfers
2. Link bank account (ACH, 1-3 days)
3. Deposit amount
4. Wait 1-3 days for settlement

Angel One Funding:
1. Log into Angel One → Funds → Deposit
2. Choose method: NEFT, UPI, or Netbanking
3. Follow instructions
4. Funds credited instantly to 1 minute
```

*Step 3: Risk Settings & Position Sizing*
```
In AAATS Settings, configure:

Max loss per trade: 2% of capital
- Example: $500 capital → max loss $10/trade
- System auto-calculates position size

Max portfolio deployment: 40% of capital
- Keep 60% cash for drawdown buffer

Max monthly loss: 20% of capital
- Example: $500 capital → system pauses at -$100

Drawdown kill switch: MANDATORY
- Auto-pause all trading at -20% drawdown
- Manual resume only after investigation
```

*Step 4: Monitor via Dashboard*
```
Daily:
- Check P&L (5 minutes)
- Review open positions
- Glance at alerts

Weekly:
- Review performance metrics
- Check win rate, Sharpe ratio
- Read Telegram summary

Monthly:
- Download trade report
- Analyze monthly P&L
- Adjust position sizing if needed

You don't need to do anything else. System trades autonomously.
```

**D. Expected Returns Breakdown**
```
┌─ CONSERVATIVE (Goal: Steady growth)
│  Expected: 5-10% monthly returns
│  Realistic: 6-8% on average
│  Worst month: -5% drawdown
│  Best month: +12% returns
│  Year 1 estimate: +72-96% annual

├─ REALISTIC (Goal: Balanced risk/reward)
│  Expected: 8-15% monthly returns
│  Realistic: 10-12% on average
│  Worst month: -12% drawdown
│  Best month: +18% returns
│  Year 1 estimate: +120-144% annual

└─ AGGRESSIVE (Goal: Maximum growth, higher risk)
   Expected: 15-20% monthly returns
   Realistic: 12-16% on average
   Worst month: -18% drawdown
   Best month: +25% returns
   Year 1 estimate: +144-192% annual
   ⚠️ Not recommended until 6+ months proven
```

**E. Risk Breakdown (Worst-Case Scenarios)**
```
Starting capital: $1,000
Paper trading duration: 2 months (zero risk)

After 2 months, switch to live trading:
Starting capital: $1,000

Scenario 1: Market crashes 20% in one day
- System drawdown kill switch: -20%
- Your loss: -$200 maximum (protected)
- Action: System pauses, you investigate

Scenario 2: Your strategy underperforms for 1 month
- Monthly loss: -$150 (15% of capital)
- You can pause, adjust, or continue
- You never lose more than you can afford

Scenario 3: Strategy is broken (tech error)
- System detects zero profitability
- Checkpoint trigger: Stop building, investigate
- No automated loss accumulation
```

**F. FAQ (Common Questions)**

```
Q: How much should I start with?
A: $500-1000. Less = fees eat profits. More = too risky as a beginner.

Q: Can I lose my entire $1000?
A: No. Kill switches prevent catastrophic losses. Worst case: -20% = -$200.

Q: What if the market crashes 50%?
A: Our risk engine auto-pauses at -20% drawdown. You control when to resume.

Q: How often do I need to check?
A: Daily (5 min to glance). Or never - system trades 24/7 without you.

Q: What if I want to add more capital mid-month?
A: System auto-adjusts position sizes. You can add/withdraw anytime.

Q: When will I see profits?
A: Paper trading: Week 1-2. Real money: Month 2-3 (after validation).

Q: What if the system loses money?
A: Stay in paper mode. Never force live trading. Investigate first.

Q: Can I use this for retirement savings?
A: Not recommended. This is speculative. Use only money you can afford to lose.

Q: What about taxes?
A: Your responsibility. But we make it easy:
   - We track TDS automatically (30% on Binance, Angel One)
   - We export trade history for ITR filing (CSV format)
   - Investment Calculator shows AFTER-TAX profit
   - You file ITR-2 by July 31 each year
   - Keep records for 7 years

Q: What taxes will I actually pay?
A: Depends on broker + holding period:
   - Angel One (India equity): 30% short-term, 20% long-term capital gains
   - Binance (Crypto): 30% TDS on transactions >₹50k (final tax)
   - Alpaca (US stocks): 20% TDS on dividends + capital gains tax
   - You see NET profit in Investment Calculator, not gross

Q: Do I need to file ITR if trading in paper mode?
A: No. ITR filing required only for LIVE trading with real money.

Q: Is this legal in India?
A: ✅ Yes. All brokers are RBI/SEBI compliant:
   - Angel One: SEBI registered
   - Binance: Legal with 30% TDS
   - Alpaca: SEC regulated, legal for Indians
   - We explicitly prohibit Exness (RBI restriction on offshore forex)

Q: What if I make ₹10 lakh profit in a year?
A: Tax liability: ~₹3 lakh (30% effective rate after short/long term mix)
   - You need to file ITR-2
   - Keep all broker statements as proof
   - We export CSV for your accountant
   - File by July 31

Q: Is this guaranteed profit?
A: No. Past performance ≠ future results. But strategy is systematically tested.
```

---

## PAGE 4: STRATEGY DETAILS

### Purpose
Explain how each strategy works, when it trades, and its historical performance.

### Components

**A. Strategy List (Expandable cards)**

*Strategy 1: US Momentum*
```
┌─ US Momentum Strategy [Expand/Collapse]
│
├─ How it works:
│  Entry: SMA50 > SMA200 (golden cross) + Momentum > threshold
│  Exit: SMA50 < SMA200 (death cross) OR ATR-based stop loss hit
│  Position size: Auto-calculated based on volatility (ATR)
│  Timeframe: 1-hour charts (holds trades 1-6 hours)
│
├─ Backtest Results:
│  Total trades: 456
│  Win rate: 65%
│  Average profit per win: $142
│  Average loss per loss: -$78
│  Profit factor: 1.82
│  Sharpe ratio: 1.4
│  Annual return: +18.5% (historical)
│
├─ Best for:
│  ✅ Bull markets (trending up)
│  ✅ Morning breakouts
│  ✅ Large-cap stocks (AAPL, MSFT, NVDA)
│  ❌ Avoid in choppy/sideways markets
│
└─ Risk rules:
   Max loss per trade: 2% of capital
   Avg holding time: 2.5 hours
   Max concurrent positions: 5
```

*Strategy 2: India Momentum*
```
Same format as above, but:
- Entry: Nifty50 > SMA, India VIX < 20
- Best for: Large-cap Indian stocks (Reliance, Infy, TCS)
- Volatility: Higher than US
```

*Strategy 3: Crypto Grid Trading*
```
- Entry: Grid levels at 2% intervals
- Exit: Take profit at +1.5% per level
- Best for: Range-bound crypto (BTC, ETH)
- Volatility: Highest
```

**B. Risk Rules (Detailed)**
```
Max loss per trade: 2%
- Example: $1,000 account → $20 max loss
- System auto-sizes positions to enforce this

Max portfolio exposure: 40%
- Example: $1,000 account → $400 max deployed
- Keeps $600 as buffer for drawdown

Position sizing formula:
Shares = (Capital × Risk %) / (Entry Price - Stop Price)

Stop loss: ATR-based (dynamic)
- High volatility → wider stop
- Low volatility → tighter stop

Maximum correlation check:
- No more than 3 correlated positions (e.g., 3 tech stocks)
- Spreads risk across sectors
```

---

## PAGE 5: RISK & ALERTS

### Purpose
Monitor real-time risk metrics and system health.

### Components

**A. Current Risk Metrics**
```
┌─ Portfolio Drawdown
│  Current: 8.5%
│  Limit: 20% (kill switch level)
│  Progress bar: ▓▓░░░░░░░░░░░ (58% to limit)
│  Action: ✅ Safe to continue
│
├─ Individual Market Drawdowns
│  US: 5.2% (within limit)
│  India: 12.1% (approaching 15% warning)
│  Crypto: 3.1% (safe)
│
└─ Total Exposure
   Deployed: $40,000 / $100,000 (40%)
   Available: $60,000 (buffer)
   Risk: ✅ Conservative positioning
```

**B. Kill Switch Status**
```
Status: 🟢 ARMED (Active, ready to pause)

History (Last 7 days):
- May 3, 14:32: Triggered (India drawdown +15%) → Position size reduced 50%
- May 2, 09:15: Triggered (Crypto glitch) → Crypto suspended 1 hour
- May 1, 16:22: Test trigger ✅ Response time: 1.2 seconds

Next safety test: May 10 (weekly)
```

**C. Alerts Log (Real-time)**
```
Timestamp      | Severity | Alert                                    | Status
2026-05-08     | 🟡 WARN  | India drawdown 15% - Position reduced    | ✅ Resolved
14:32:15       |          |                                          |
───────────────────────────────────────────────────────────────────
2026-05-08     | 🟢 INFO  | US Momentum: 2 trades closed, +$284 P&L | ✅ Normal
14:15:22       |          |                                          |
───────────────────────────────────────────────────────────────────
2026-05-08     | 🟡 WARN  | Alpaca API latency 850ms (threshold 500) | ⚠️ Monitor
13:50:01       |          |                                          |
───────────────────────────────────────────────────────────────────
2026-05-08     | 🟢 INFO  | Daily P&L: +$312 (1.2% of capital)       | ✅ Normal
08:00:00       |          |                                          |
```

**D. API Status**
```
Alpaca API:
├─ Status: ✅ CONNECTED
├─ Last sync: 2 seconds ago
├─ Latency: 142ms (good)
└─ Session: Active, expires in 6 hours

Angel One SmartAPI:
├─ Status: ✅ CONNECTED
├─ TOTP Token: Valid for 11h 47m (auto-renews)
├─ Latency: 287ms (acceptable)
└─ Session: Active

Database:
├─ Status: ✅ HEALTHY
├─ Trades recorded: 342
├─ Size: 12.5 MB
└─ Last backup: 2 hours ago
```

**E. Risk Engine Activity (Last 10 events)**
```
Time       | Event                                      | Result
05/08 14:32| Market volatility spike detected (VIX +8) | Monitored, no action
05/08 13:15| Possible correlation detected (3 tech)    | Spread check passed
05/08 12:44| Stop loss on MSFT trade                   | Exited, loss -$18
05/08 12:10| Strategy signal rejected (risk too high)  | Signal blocked, capital preserved
05/08 10:55| Kill switch test executed                 | ✅ Response: 1.1 seconds
...
```

---

## PAGE 6: SETTINGS & ACCOUNT

### Purpose
Configure account, credentials, risk parameters, and mode (paper/live).

### Components

**A. Mode Toggle (CRITICAL - 2-Step Confirmation)**
```
┌─────────────────────────────────────────────────────┐
│ Trading Mode                                        │
│ ┌──────────────┐        ┌──────────────┐           │
│ │ 🔵 PAPER     │   ↔    │ 🔴 LIVE      │           │
│ │ [ACTIVE]     │        │ [LOCKED]     │           │
│ └──────────────┘        └──────────────┘           │
│                                                     │
│ ℹ️  Paper mode: No real money at risk              │
│ ℹ️  Locked until 2+ months profitable paper trading│
│                                                     │
│ [To switch to LIVE mode:                           │
│  1. Click "REQUEST LIVE MODE"                      │
│  2. Enter PIN (security)                           │
│  3. Confirm: "I understand this risks real money" │
│  4. System verifies paper trading checklist       │
│ ]                                                  │
└─────────────────────────────────────────────────────┘
```

**B. Broker Credentials (Encrypted Storage)**
```
Alpaca API Key:
├─ Current: ••••••••••••••••••••••••
├─ Status: ✅ Connected
├─ Last used: 2 minutes ago
├─ [Test Connection] [Update Key] [Revoke]
└─ Format: pk_live_****... (masked for security)

Angel One Credentials:
├─ API Key: ••••••••••••••••••••••••
├─ Client ID: REDACTED_ANGEL_CLIENT_ID
├─ PIN: ••••••
├─ TOTP Secret: [Encrypted, not shown]
├─ Status: ✅ Connected (TOTP valid 12h)
├─ [Test Connection] [Refresh TOTP] [Update]
└─ Auto-refresh TOTP: ✅ Enabled (1x daily)

All credentials encrypted at rest. Never logged or exposed.
```

**C. Risk Parameters (User-Adjustable)**
```
Max loss per trade: [2 %] ← Slider, 0.5% - 5%
Description: Stop loss percentage from entry price

Max portfolio deployment: [40 %] ← Slider, 20% - 80%
Description: Maximum capital allocated to active trades

Max monthly drawdown: [20 %] ← Slider, 10% - 30%
Description: Portfolio stops trading if exceeded

Position correlation limit: [3] ← Number, 2-5 positions
Description: Max correlated positions (e.g., all tech stocks)

Kill switch mode: [AUTO] ← Dropdown, AUTO / MANUAL / DISABLED
⚠️ WARNING: Disabling kill switch is dangerous
Description: AUTO = auto-pause at limits. MANUAL = alerts only.

[SAVE CHANGES] [REVERT] [RESTORE DEFAULTS]
```

**D. Capital Allocation (Market Split)**
```
US Market:     [████████░░] 60% ($60,000)
India Market:  [██████░░░░] 40% ($40,000)
───────────────────────────────
Total Capital: $100,000

[Adjust sliders]
Info: Deployment auto-adjusts position sizing per market
```

**E. Notification Preferences**
```
Telegram Alerts:      ✅ Every trade
Email Alerts:         ☐ Daily summary [ADD]
SMS Alerts:           ☐ Critical events only [ADD]
In-app Notifications: ☐ Enable [ADD]

Telegram Bot Token: [••••••••••••••••••••••••••••] [Update]
Telegram Chat ID:   [REDACTED_TELEGRAM_CHAT_ID] [Verify] [Get new ID]
Email Address:      [puneethmp106@gmail.com] [Update]
Phone (for SMS):    [+91-XXXXXXXXXX] [Update]

Test Notification: [Send Test Alert]
```

---

## PAGE 7: REPORTS & EXPORT

### Purpose
Download historical trade data, performance reports, and tax documents.

### Components

**A. Trade History (Searchable, Filterable)**
```
Filter by:
├─ Date range: [Start] [End] [Last 7 days] [Last 30 days]
├─ Symbol: [All] [AAPL] [MSFT] [Reliance] [BTC] [ETH]
├─ Strategy: [All] [US Momentum] [India Momentum] [Crypto Grid]
├─ Market: [All] [US] [India] [Crypto]
└─ Status: [All] [Profitable] [Loss] [Open]

Results: 342 trades found
[Export as CSV] [Export as PDF] [Download Excel]

Table:
Entry Time     | Symbol | Strategy      | Entry    | Exit     | Status | P&L   | % Return
2026-05-08 ... | AAPL   | US Momentum   | $150.23  | $152.45  | Closed | +$222 | +1.5%
2026-05-08 ... | INFY   | India Mom.    | ₹2543    | ₹2612    | Closed | +₹900 | +2.7%
...            | ...    | ...           | ...      | ...      | ...    | ...   | ...
```

**B. Monthly Performance Reports (Auto-generated)**
```
Report Month: [May 2026]

P&L Statement:
├─ Gross P&L: +$1,245
├─ Fees: -$45
├─ Net P&L: +$1,200
└─ ROI: +6.0%

Performance Metrics:
├─ Total trades: 74
├─ Winning trades: 47 (65%)
├─ Losing trades: 27 (35%)
├─ Avg win: $148
├─ Avg loss: -$82
├─ Profit factor: 1.8
├─ Sharpe ratio: 1.45
├─ Max drawdown: -12.5%
└─ Biggest win: +$892 (TSLA, May 1)

Market breakdown:
├─ US: +$742 (68% of profits)
├─ India: +$385 (32% of profits)
└─ Crypto: +$118 (hedging)

Strategy breakdown:
├─ US Momentum: +$465
├─ India Momentum: +$503
└─ Crypto Grid: +$277

[Download as PDF] [Email to advisor] [Share]
```

**C. Tax Reports (For Real Trading)**
```
⚠️ Important: Only relevant after switching to live trading

Realized Gains/Losses:
├─ Short-term gains: +$8,450 (held < 1 year)
├─ Long-term gains: +$2,100 (held > 1 year)
├─ Total tax liability: ~$2,110 (28% in India)
└─ Estimated tax due: Date TBD (January filing)

Wash Sale Flagging:
├─ Wash sales detected: 0
├─ Status: ✅ Clean (no tax complications)

Export for Accountant:
├─ [Download IRS Form 8949] (for US)
├─ [Download ITR Annex] (for India)
└─ Format: PDF + Excel (includes all trades, P&L, dates)
```

---

## TECHNICAL REQUIREMENTS

### Stack
- **Frontend:** Streamlit (Python)
- **Database:** SQLite (read-only connection)
- **Charts:** Plotly (interactive)
- **Auth:** Simple login (API key + password)
- **Hosting:** Streamlit Community Cloud (free)
- **Real-time:** Auto-refresh every 30 seconds

### Dependencies
```
streamlit>=1.28.0
plotly>=5.17.0
pandas>=2.0.0
numpy>=1.24.0
sqlalchemy>=2.0.0
```

### Security
- Encrypted credential storage (passwords hashed, API keys salted)
- 2-step confirmation for mode toggle
- Read-only database access (prevents accidental data loss)
- Session timeout (30 min idle logout)
- Audit log (all changes logged)

### Performance
- Dashboard loads in < 2 seconds
- Real-time updates every 30 seconds
- Support for 500+ trades in history
- Mobile responsive (works on phone)

---

## BUILD SEQUENCE (Claude Code Pro)

**Phase 2.5 (May 4-5, ~58k tokens)**

1. **Pages 1-2:** Dashboard + Analytics (12k tokens)
   - Real-time position tracking
   - Performance metrics calculation
   
2. **Pages 3-4:** Investment Guide + Strategy Details (10k tokens)
   - Interactive calculator
   - FAQ content
   
3. **Pages 5-6:** Risk & Settings (8k tokens)
   - Real-time risk metrics
   - Credential management
   
4. **Page 7 + Auth:** Reports + Security (10k tokens)
   - Trade export
   - Login system
   
5. **Deployment:** Streamlit Cloud (10k tokens)
   - Deploy to public URL
   - Test all features
   - Generate public link

**Output:** Live at `https://aaats-trading-dashboard.streamlit.app`

---

**Status:** READY FOR BUILD ✅
**Next:** Claude Code Pro executes on May 4
