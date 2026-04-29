# AAATS Legal Trading Setup Guide for Indian Traders

**Goal:** Complete paper trading of legal trading system across Angel One, Binance, and Alpaca (if approved)

**Timeline:** 2-7 days for setup | Paper trading: May 8 - July 8, 2026

---

## Phase 1: Pre-Setup Preparation (Before May 1)

### Step 1: Gather Documents

**Essential Documents:**
- [ ] PAN (Permanent Account Number) — 10-digit code
- [ ] Aadhar (if needed for IB)
- [ ] Passport (for international brokers)
- [ ] Bank statement (recent, < 3 months)
- [ ] Photo ID (passport or Aadhar)

**Know Your Information:**
- Bank account number (for deposits/withdrawals)
- Email address (for broker accounts)
- Phone number (for OTP verification)

### Step 2: Review Financial Capacity

**Minimum Capital to Start:**
- Angel One: ₹5,000 minimum
- Binance: ₹10,000 recommended (>₹50k for TDS testing)
- Alpaca: $1,000 USD minimum (~₹83,000) if approved

**Recommended Paper Trading Capital:**
- ₹50,000-100,000 total across all brokers
- This allows testing of multi-market strategies
- Enough to see meaningful returns during paper trading

---

## Phase 2: Broker Setup (May 1-7)

### BROKER #1: Angel One (PRIMARY - REQUIRED)

#### Step 1: Create Angel One Account

**Time Required:** 30 minutes

**Action:**
1. Visit: https://www.angelone.in/open-account
2. Fill application form:
   - Name, Email, Phone
   - PAN number
   - Date of birth
   - Bank account details
3. Submit KYC documents (photo + address)
4. Wait for approval: Typically 1-2 hours

#### Step 2: Set API Access

**Time Required:** 15 minutes

**Action:**
1. Login to Angel One web platform
2. Go to: Settings → API Access
3. Request SmartAPI access (algorithm trading)
4. Keep this information safe:
   - API Key: `REDACTED_ANGEL_KEY` (already configured)
   - Client ID: `REDACTED_ANGEL_CLIENT_ID` (already configured)
   - PIN: `9066` (already configured in .env)
   - TOTP Secret: `JZCRAQDC7SYURTQE5VR5GALAF4` (already configured)

**Verification:**
```bash
# Test Angel One connection:
pytest tests/test_india/test_angel_one_integration.py -v
# Should show: ✅ Angel One API Connected
```

#### Step 3: Deposit Funds (Optional for Paper Trading)

**For Paper Trading:** Not required (virtual money)

**For Live Trading Later:**
1. Transfer ₹5,000-100,000 to Angel One bank account
2. Wait 1-2 days for funds to appear in platform
3. System auto-allocates capital

---

### BROKER #2: Binance (SECONDARY - RECOMMENDED)

#### Step 1: Create Binance Account

**Time Required:** 20 minutes

**Action:**
1. Visit: https://www.binance.com
2. Click "Register"
3. Enter email + password
4. Verify email (check inbox)
5. Enable 2FA (security)
   - Use Google Authenticator or Authy
   - Save backup codes safely

#### Step 2: Complete KYC (Know Your Customer)

**Time Required:** 15 minutes

**Action:**
1. Login to Binance
2. Go to: Account → Verification
3. Click "Verify Identity"
4. Enter PAN, name, date of birth
5. Upload photo ID (Aadhar or Passport)
6. Take selfie (Binance asks for it)
7. Wait for approval: Usually 1-5 minutes (instant sometimes)

**Verification Step:**
Binance will ask "Resident of India?" — Answer: YES
Binance applies 30% TDS automatically.

#### Step 3: Create API Keys

**Time Required:** 10 minutes

**Action:**
1. Login to Binance
2. Go to: Account → API Management
3. Click "Create API"
4. Name it: "AAATS-Trading"
5. Binance gives you:
   - **API Key:** Copy and save (will need in .env)
   - **Secret Key:** Copy and save (will need in .env)
6. Enable these restrictions:
   - ✅ Spot trading
   - ✅ Margin trading (optional)
   - ❌ Withdraw (DISABLE - security)
   - ✅ IP Whitelist your home IP (security)

**Update .env:**
```
CRYPTO__BINANCE_API_KEY=your_api_key_here
CRYPTO__BINANCE_SECRET_KEY=your_secret_key_here
```

#### Step 4: Test Connection (Optional for Paper Trading)

**For Testing:**
```bash
# Test Binance connection:
pytest tests/test_crypto/test_binance_integration.py -v
# Should show: ✅ Binance API Connected
```

---

### BROKER #3: Alpaca (OPTIONAL - APPROVAL UNCERTAIN)

#### Step 1: Apply for Alpaca Account

**Time Required:** 15 minutes (approval: 5-7 days)

**Action:**
1. Visit: https://alpaca.markets
2. Click "Open Account"
3. Select "Individual Account"
4. Fill application:
   - Name, Email, Phone, Address
   - Nationality: India
   - PAN number
   - Bank account (for USD transfers)
5. Upload documents:
   - Photo ID (Aadhar/Passport)
   - Proof of address (utility bill/bank statement)
6. Submit and wait

**⚠️ IMPORTANT:** Alpaca may REJECT Indian residents. If rejected, use Interactive Brokers (Tier 4) as backup.

#### Step 2: If Approved - Create API Keys

**Time Required:** 10 minutes

**Action:**
1. Login to Alpaca dashboard
2. Go to: Settings → API Keys
3. Create new key: "AAATS-Trading"
4. Alpaca gives you:
   - **API Key:** Save it
   - **Secret Key:** Save it
   - **Paper Trading URL:** Use this for paper trading
5. Update .env:
```
US__ALPACA_API_KEY=your_key_here
US__ALPACA_SECRET_KEY=your_secret_here
US__ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

#### Step 3: Paper Trading Mode

**CRITICAL:** Start in PAPER MODE (not live):
1. Alpaca gives you virtual $25,000
2. Use this for testing strategies
3. All trades are simulated
4. Real commission/tax rules apply

---

### IF ALPACA REJECTED: Interactive Brokers Backup

**Time Required:** 15 minutes (approval: 5-7 days)

**Action:**
1. Visit: https://www.interactivebrokers.com
2. Click "Open Account"
3. Fill application (same as Alpaca)
4. Mention: "Algorithmic trading, API access needed"
5. Provide tax info:
   - PAN (or US ITIN if you have one)
   - Resident of India: YES
6. Submit and wait for approval

**Cost:** Usually $10/month minimum fee (waived if account > $2,000)

---

## Phase 3: System Integration (May 1-2)

### Step 1: Update .env Configuration

**File:** `C:\Users\udaym\OneDrive\Desktop\Puneeth\.env`

**Current Status:** Already updated with:
- ✅ Angel One credentials
- ✅ Alpaca placeholder
- ✅ Binance placeholder
- ✅ Interactive Brokers (commented, backup only)

**Action:** Fill in your broker credentials:

```bash
# For Binance (required):
CRYPTO__BINANCE_API_KEY=your_actual_binance_api_key
CRYPTO__BINANCE_SECRET_KEY=your_actual_binance_secret

# For Alpaca (if approved):
US__ALPACA_API_KEY=your_actual_alpaca_key
US__ALPACA_SECRET_KEY=your_actual_alpaca_secret

# For Interactive Brokers (if Alpaca rejected):
# (Uncomment and fill if needed)
US_IB__ACCOUNT_ID=your_ib_account
US_IB__API_KEY=your_ib_key
```

**⚠️ WARNING:** Never commit .env to git (already in .gitignore)

### Step 2: Verify All Connections

**Run Health Checks:**
```bash
# Test all broker connections:
pytest tests/test_health_checks.py -v

# Output should show:
# ✅ Angel One: Connected
# ✅ Binance: Connected (or ⏳ if not set up)
# ✅ Alpaca: Connected (or ⏳ if not approved)
```

### Step 3: Verify Paper Trading Mode

**For Alpaca:**
Confirm you're using: `https://paper-api.alpaca.markets` (not live)

**For Binance:**
Paper trading not available (but low commission, so safe for learning)

**For Angel One:**
Paper trading available in later phases (use with caution)

---

## Phase 4: Compliance Setup (May 1-7)

### Step 1: Create Tax Records Folder

**Location:** `C:\Users\udaym\Documents\AAATS_TAX_RECORDS\`

**Subdirectories:**
```
├── 2026
│   ├── Angel_One/
│   │   ├── Statements/
│   │   ├── Trades/
│   │   └── TDS_Certificates/
│   ├── Binance/
│   │   ├── Statements/
│   │   ├── Trades/
│   │   └── TDS_Certificates/
│   └── Alpaca/
│       ├── Statements/
│       ├── Trades/
│       └── TDS_Certificates/
```

### Step 2: Export Paper Trading Records

**Monthly Routine (Every Month):**
1. Login to web app
2. Go to: Reports → Export Trades
3. Download CSV file:
   - Date
   - Broker
   - Instrument
   - Quantity
   - Price
   - P&L
   - Tax Treatment
4. Save to: `2026/Broker_Name/Trades/` folder

### Step 3: Collect TDS Certificates

**Binance TDS (If transactions > ₹50k):**
1. Login to Binance
2. Go to: Account → Tax Documents
3. Download TDS certificate (if any TDS deducted)
4. Save to: `2026/Binance/TDS_Certificates/`
5. Binance sends PDF with:
   - Amount of transaction
   - TDS amount (30%)
   - Certificate number (for ITR)

**Alpaca Dividends (If applicable):**
1. Login to Alpaca
2. Go to: Account → Tax Documents
3. Download any TDS documents
4. Save to: `2026/Alpaca/TDS_Certificates/`

---

## Phase 5: Paper Trading Launch (May 8)

### Day 1: Verify System is Live

**Checklist:**
- [ ] Web app accessible: https://aaats-trading-dashboard.streamlit.app
- [ ] Dashboard shows positions (should be empty at start)
- [ ] Strategies display correctly
- [ ] Risk engine active
- [ ] Paper trading mode confirmed

### Day 1-7: Initial Trades

**First Week Goals:**
- [ ] Execute 5-10 test trades
- [ ] Verify order execution (placement, fill, exit)
- [ ] Check P&L calculations
- [ ] Confirm Telegram notifications work
- [ ] Review trade logs

**Daily Monitoring (5 minutes):**
1. Open web app
2. Check open positions
3. Review today's P&L
4. Check alerts (if any)
5. Record observations

### Week 2-4: Strategy Validation

**Goals:**
- [ ] Profitable in at least 2 market regimes
- [ ] Risk engine tested (no blowups)
- [ ] Kill switches verified
- [ ] All strategies working
- [ ] TDS tracking functional (if Binance trades)

**Weekly Review:**
1. Download trade report
2. Calculate P&L per strategy
3. Calculate estimated taxes
4. Review Telegram notifications

---

## Phase 6: Tax Compliance During Paper Trading

### Monthly (Every Month End)

**Action:** Reconcile P&L

1. Export all trades from web app (CSV)
2. Calculate:
   - Total profit/loss
   - TDS paid (if any)
   - Tax liability estimate
3. Save to records folder
4. Telegram alert shows: "Monthly P&L: $X, Est. Tax: $Y"

### Quarterly (Every 3 Months)

**Action:** Tax estimate update

1. Review all trades
2. Calculate cumulative TDS
3. Estimate annual tax liability
4. Check if tax payment needed (usually no, since paper trading)

### When Going Live (If Profitable)

**Before Depositing Real Money:**
1. Calculate expected annual profit
2. Calculate expected annual taxes
3. Plan for ITR filing (July 31 deadline)
4. Ensure funds available for taxes

---

## Critical Dates & Deadlines

### May 1-8: Setup & Build Phase
- [ ] Angel One account: DONE
- [ ] Binance account: DONE
- [ ] Alpaca account (if pursuing): Approved or rejected
- [ ] All APIs connected
- [ ] Health checks passing
- [ ] AAATS autonomous build completed
- [ ] Web app live

### May 8 - July 8: Paper Trading (2 Months)
- [ ] Execute 100+ trades
- [ ] Validate profitability
- [ ] Test risk engine
- [ ] Collect TDS certificates
- [ ] Track all trades for ITR

### July 8: Go/No-Go Decision
- [ ] Profitable 2+ months: READY for live trading
- [ ] Not profitable: Continue paper trading or revise strategy

### July 31: Annual Tax Filing Deadline (If Live Trading)
- [ ] Gather all trade records
- [ ] Collect TDS certificates from brokers
- [ ] Calculate final tax liability
- [ ] File ITR-2 before July 31

### August 1+: Live Trading (If Approved)
- [ ] Deposit real capital
- [ ] Switch from paper to live mode
- [ ] Monitor daily (same dashboard)
- [ ] Monthly tax tracking

---

## Troubleshooting

### Issue: Alpaca Rejected My Application
**Solution:** Use Interactive Brokers (Tier 4) instead
- Same regulatory compliance
- Slightly more complex (Form W-8BEN required)
- More expensive ($10/month minimum)

### Issue: Binance TDS Not Showing
**Solution:** Check transaction size
- TDS applies only to transactions > ₹50,000
- Small trades: No TDS (but still taxable)
- Contact Binance support for TDS certificate generation

### Issue: API Connection Failing
**Solution:** Debug steps
1. Check .env credentials (copy/paste errors?)
2. Verify API keys are still active (not regenerated)
3. Check IP whitelist (Binance has this)
4. Run health check: `pytest tests/test_health_checks.py -v`

### Issue: Paper Trading Losses Mounting
**Solution:** Normal during learning phase
- Paper trading = Risk-free learning opportunity
- Adjust strategy parameters
- Review web app "Performance Analytics" for insights
- Continue until profitable (minimum 2 months)

---

## Final Checklist Before Live Trading

**READY TO GO LIVE ONLY AFTER ALL ARE TRUE:**

- [ ] 2+ months of profitable paper trading
- [ ] Win rate: > 45% (system profitable despite losses)
- [ ] Sharpe ratio: > 1.0 (good risk-adjusted returns)
- [ ] Max drawdown: < 20% (risk engine working)
- [ ] All TDS certificates collected
- [ ] Tax liability calculated
- [ ] Real capital available and ready
- [ ] Reviewed LEGAL_COMPLIANCE.md
- [ ] Understand tax obligations (ITR filing, TDS handling)
- [ ] Emergency contact plan (if system issues)

---

## Support & Questions

**For Compliance Questions:**
- Read: LEGAL_COMPLIANCE.md (comprehensive)
- Contact: Income Tax Help Line (India)

**For Broker Setup Questions:**
- Angel One Support: support@angelone.in
- Binance Support: support@binance.com
- Alpaca Support: support@alpaca.markets

**For System Issues:**
- GitHub Issues: https://github.com/yourname/AAATS
- Telegram: Alerts show error messages

---

**Created:** 2026-04-29 | **Status:** SETUP READY | **Next Phase:** May 8 Paper Trading
