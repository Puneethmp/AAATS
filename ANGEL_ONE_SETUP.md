# Angel One SmartAPI Setup Guide

This guide walks you through enabling Angel One SmartAPI integration in AAATS.

**Status:** Angel One trading modules are built and ready. This guide gets you from zero to live API connection.

---

## Prerequisites

- ✅ Angel One demat account (create at [angelbroking.com](https://www.angelbroking.com))
- ✅ Active trading account (not demo)
- ✅ AAATS repository cloned and setup (`python -m venv venv` + `pip install -r requirements.txt`)

---

## Step 1: Get Your Angel One API Credentials

### 1.1 API Key & Secret

1. Log in to [smartapi.angelbroking.com](https://smartapi.angelbroking.com)
2. Go to **My Account** → **Settings** → **API**
3. You should see:
   - **API Key** (copy this)
   - **API Secret** (copy this)
4. If you don't see an API section, create a new application:
   - Click **Create App**
   - Fill in app name (e.g., "AAATS Trading")
   - Accept terms
   - You'll be issued an API Key

### 1.2 Client ID

Your **Client ID** is your Angel One login ID. Example: `REDACTED_ANGEL_CLIENT_ID`

- It's shown in your Angel One dashboard (top-right corner)
- It's also in your Angel One account statement

### 1.3 PIN & TOTP Secret

1. Open your Angel One mobile app or web platform
2. Go to **Settings** → **Security**
3. You'll find:
   - **PIN:** Your 4-digit login PIN (you set this when creating your account)
   - **2FA / TOTP:** Your backup TOTP secret (usually a long alphanumeric code like `JZCRAQDC7SYURTQE5VR5GALAF4`)

**⚠️ Important:** Save the TOTP secret in a secure place. If you lose it:
- You won't be able to auto-renew sessions
- AAATS will halt India trading and alert you
- You'll need to manually renew the secret in Angel One settings

---

## Step 2: Add Credentials to `.env`

1. Open `config/.env.example` to see the template
2. Create a copy: `cp config/.env.example .env`
3. Edit `.env` and fill in your Angel One credentials:

```env
INDIA__ANGEL_API_KEY=REDACTED_ANGEL_KEY                        # Your API Key from step 1.1
INDIA__ANGEL_CLIENT_ID=REDACTED_ANGEL_CLIENT_ID                    # Your Client ID from step 1.2
INDIA__ANGEL_PIN=9066                                 # Your 4-digit PIN from step 1.3
INDIA__ANGEL_TOTP_SECRET=JZCRAQDC7SYURTQE5VR5GALAF4 # Your TOTP secret from step 1.3

# Other Angel One settings (defaults are safe — do not change)
INDIA__MAX_RISK_PER_TRADE=0.015      # 1.5% per trade
INDIA__FO_MAX_RISK_PER_TRADE=0.010   # 1.0% for F&O
INDIA__DRAWDOWN_HALT=-0.15            # -15% halt trigger
```

**Security:** Never commit `.env` to version control. It's in `.gitignore` by default.

---

## Step 3: Verify Configuration

Run the health check to ensure your credentials are valid:

```bash
pytest tests/test_india/test_angel_one_integration.py::TestAngelOneHealthCheck -v
```

Expected output:
```
test_config_is_valid PASSED
test_totp_secret_is_valid_base32 PASSED
```

If either test fails, your `.env` file has incorrect values. Fix them and re-run.

---

## Step 4: Test Real API Connection

Once health checks pass, test actual authentication:

```bash
pytest tests/test_india/test_angel_one_integration.py::TestAngelOneIntegration::test_can_authenticate_and_get_tokens -v -s
```

This test will:
1. Read your credentials from `.env`
2. Connect to Angel One SmartAPI
3. Authenticate using your PIN + TOTP
4. Request session tokens

Expected output:
```
test_can_authenticate_and_get_tokens PASSED
✅ Authentication successful
```

**If this fails:**
- ❌ `401 Unauthorized` → PIN or API Key is wrong. Double-check `.env`.
- ❌ `Network timeout` → Angel One API is unreachable. Check internet connection.
- ❌ `Invalid TOTP` → TOTP secret is wrong or expired. Regenerate in Angel One settings.

---

## Step 5: Test Full Token Renewal Flow

Once authentication works, test the complete daily renewal cycle:

```bash
pytest tests/test_india/test_angel_one_integration.py::TestAngelOneIntegration::test_totp_renewal_works -v -s
```

This verifies:
- TOTP is generated correctly
- Tokens can be renewed multiple times
- Session tokens are cached and reused

---

## Step 6: Enable India Market in the System

Now that your credentials are verified, update the AAATS system configuration:

```python
# In your trading script (e.g., main.py)
from config.settings import AppConfig
from markets.india.token_manager import TokenManager
from smartapi import SmartConnect

# Load config (reads from .env automatically)
config = AppConfig()

# Create real SmartConnect client
smart_client = SmartConnect(api_key=config.india.angel_api_key)

# Initialize token manager
token_manager = TokenManager(
    smart_connect_client=smart_client,
    config=config,
    alert_fn=lambda msg: print(f"Alert: {msg}")
)

# Renew session before trading
tokens = token_manager.renew_session()
print(f"Auth token: {tokens['auth_token'][:20]}...")  # First 20 chars only
```

---

## Step 7: Understand Daily Token Renewal

**How it works:**
- Angel One session tokens expire at midnight IST every day
- AAATS automatically generates a new TOTP code at market open (8:00 AM IST)
- The token manager calls `generateSession()` with your PIN + fresh TOTP
- New tokens are cached and used for the rest of the trading day

**If renewal fails:**
1. India trading halts automatically (kill switch activates)
2. You receive a Telegram alert (if configured)
3. The failure is logged to audit trail
4. You must fix the issue and manually restart AAATS

**Common failure modes:**
- ❌ TOTP secret is wrong → Regenerate it in Angel One settings
- ❌ PIN changed → Update `.env` with new PIN
- ❌ Angel One API down → Wait for them to restore service
- ❌ Network connectivity issue → Check internet connection

---

## Step 8: Monitor Token Health

Check token status anytime:

```bash
# View audit trail for token renewals
sqlite3 data/audit_trail.db "SELECT * FROM audit_trail WHERE module='token_manager' ORDER BY timestamp DESC LIMIT 10;"

# Check if token is currently valid
python -c "from markets.india.token_manager import TokenManager; print(token_manager.is_token_valid())"
```

---

## Troubleshooting

### Problem: "Invalid TOTP secret" error

**Cause:** TOTP secret in `.env` is not base32-encoded or is corrupted

**Fix:**
1. Go to Angel One settings
2. Regenerate TOTP secret
3. Save the new secret to `.env`
4. Re-run health check

### Problem: "401 Unauthorized"

**Cause:** PIN or API Key is incorrect

**Fix:**
1. Verify your PIN hasn't changed
2. Verify your API Key from smartapi.angelbroking.com
3. Update `.env` with correct values
4. Re-run authentication test

### Problem: "Network timeout"

**Cause:** Angel One API is unreachable

**Fix:**
1. Check your internet connection
2. Try accessing smartapi.angelbroking.com directly
3. If Angel One is down, wait and retry later
4. Contact Angel One support if the issue persists

### Problem: Token renewal fails at market open

**Cause:** Multiple possible reasons — check logs

**Fix:**
```bash
# View system logs for India module
tail -f logs/india_token_manager.log

# Check audit trail for error details
sqlite3 data/audit_trail.db "SELECT * FROM audit_trail WHERE event_type='TOKEN_RENEWAL' AND result='FAILURE' ORDER BY timestamp DESC;"
```

---

## Security Best Practices

1. ✅ **Keep `.env` private** — Never commit to git, never share
2. ✅ **Regenerate TOTP secret periodically** — At least annually
3. ✅ **Rotate API Keys** — If you suspect a compromise
4. ✅ **Use strong PINs** — Your PIN protects your account
5. ✅ **Monitor logs** — Check audit trail for unusual activity
6. ✅ **Enable alerts** — Configure Telegram alerts for failures

---

## Next Steps

Once Angel One integration is verified:

1. **Run full system test:**
   ```bash
   pytest tests/test_india/ -v
   ```

2. **Start India data pipeline:**
   ```bash
   python main.py --mode paper --market india
   ```

3. **Monitor dashboard:**
   ```bash
   streamlit run observability/dashboard.py
   ```

4. **Begin paper trading** — Run for minimum 3 months before live trading

---

## Reference

- Angel One API Docs: https://smartapi.angelbroking.com/docs
- SmartAPI Python SDK: https://github.com/angelbroking-github/smartapi
- AAATS Blueprint: [AAATS_MASTER_BLUEPRINT.md](AAATS_MASTER_BLUEPRINT.md)

---

**Questions?** Check the [README.md](README.md) "Getting Help" section or the [MASTER_AUTODRIVER.md](MASTER_AUTODRIVER.md) architecture guide.
