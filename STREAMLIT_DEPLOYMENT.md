# Streamlit Cloud Deployment Guide

**For:** AAATS Trading Dashboard | **Date:** 2026-04-29 | **Status:** Ready to Deploy

---

## QUICK START (5 minutes)

### Step 1: Prepare GitHub
```bash
# In your project root:
cd C:\Users\udaym\OneDrive\Desktop\Puneeth

# Stage files
git add streamlit_app/
git add .streamlit/
git commit -m "Add Streamlit web app - Phase 2.5"
git push origin main

# Verify:
git log --oneline | head -5
# Should show your new commit
```

### Step 2: Deploy to Streamlit Cloud

**Go to:** https://streamlit.io/cloud

1. Click **"New app"**
2. **Select repository:** Your AAATS repo
3. **Select branch:** `main`
4. **Set main file path:** `streamlit_app/app.py`
5. Click **"Deploy"**

**Streamlit will:**
- Install dependencies from `requirements.txt`
- Build the app
- Deploy to: `https://aaats-trading-dashboard.streamlit.app` (auto-generated URL)

⏳ First deploy takes 2-3 minutes. You'll see a progress bar.

### Step 3: Configure Secrets

Once deployed, click ⚙️ **Settings** (top right) → **Secrets**

Add these environment variables (copy/paste):

```
# Alpaca (US broker)
ALPACA_API_KEY=pk_live_YOUR_ALPACA_KEY_HERE

# Angel One (India broker)
INDIA__ANGEL_API_KEY=YOUR_ANGEL_API_KEY_HERE
INDIA__ANGEL_CLIENT_ID=YOUR_ANGEL_CLIENT_ID_HERE

# Telegram notifications  ← REVOKE OLD TOKEN, get new one from @BotFather
ALERTS__TELEGRAM_BOT_TOKEN=YOUR_NEW_TELEGRAM_BOT_TOKEN_HERE
ALERTS__TELEGRAM_CHAT_ID=YOUR_TELEGRAM_CHAT_ID_HERE

# Web app password
STREAMLIT_PASSWORD=YourSecurePassword123
```

Click **"Save"** → App auto-reloads with secrets.

### Step 4: Test the App

Open: `https://aaats-trading-dashboard.streamlit.app`

You should see:
- Login screen
- Enter your password
- Dashboard loads with live data

✅ **You're live!**

---

## DOMAIN & SHARING

### Public URL
```
https://aaats-trading-dashboard.streamlit.app
```

### Share with Others
- Anyone with the URL can access (password-protected)
- Give the link to your advisor, accountant, etc.
- App works on desktop + mobile

### Custom Domain (Optional)
```
Cost: $0-50/year (if you want: trading.yourname.com)
Setup: Streamlit Pro ($20/month) or custom domain service
Not needed for this project (public URL works fine)
```

---

## MONITORING & UPDATES

### View App Status
**Streamlit Cloud Dashboard:**
- App running: ✅ Green
- Last deployed: Date/time
- Logs: Click "Logs" to debug issues

### Redeploy After Code Changes
```bash
git add streamlit_app/
git commit -m "Fix bug in dashboard page"
git push origin main
```

Streamlit auto-redeployments (1-2 minutes).

### Rollback to Previous Version
```
Streamlit Cloud → Select previous deployment → Click "Deploy"
```

---

## LIMITS & SCALING

### Free Tier (Community Cloud)
```
✅ Allowed:
- 1 app per account (upgrade for more)
- 1 GB RAM per app
- 1 CPU
- Unlimited public URLs
- Auto-sleep after 7 days of inactivity

❌ Not Allowed:
- Custom Python modules (only pip packages)
- Long-running loops (>15 min timeout)
- Large file uploads (>200 MB)
- GPU access
```

### Scaling
If you need more:
```
Streamlit Pro: $20/month
- 3 apps
- 2 GB RAM
- Custom domain
- Priority support

For this project: Free tier is sufficient
```

---

## TROUBLESHOOTING

### App Won't Load
```
1. Check Streamlit logs: Click "Logs" button
2. Look for error messages
3. Common issues:
   - Missing dependency (add to requirements.txt)
   - Database path wrong (check config.py)
   - Secrets not set (go to Settings → Secrets)
```

### Secrets Not Working
```
1. Verify you pasted secrets correctly
2. Check spelling (case-sensitive)
3. Click "Save" after adding secrets
4. App auto-reloads after save (wait 30 seconds)
5. Refresh browser if still not working
```

### Dashboard Too Slow
```
Database query optimization:
- Limit trades to last 500 (not 100,000)
- Add indexes to SQLite (on entry_time, symbol)
- Cache calculations with @st.cache_data
```

### Logout/Session Issues
```
Click browser back button → Clears session
Re-enter password on refresh

For security: Session timeout after 30 min idle
```

---

## BACKUP & SECURITY

### Backup Strategy
```
1. Code: Already in GitHub (safe)
2. Database: Backup daily
   - Schedule: Every 24 hours
   - Command: cp aaats.db aaats_backup_$(date +%Y%m%d).db
3. Secrets: Stored in Streamlit Cloud (encrypted at rest)
```

### Security Best Practices
```
✅ DO:
- Change STREAMLIT_PASSWORD to something strong
- Use environment variables (never hardcode secrets)
- Use read-only database connection
- Set session timeout
- Monitor who accesses the app (check logs)

❌ DON'T:
- Share secrets in GitHub (use .gitignore)
- Use weak passwords
- Expose API keys in code
- Give full database write access
- Run untrusted code
```

---

## ACCESSING THE APP OFFLINE

### Local Development
```bash
cd streamlit_app
streamlit run app.py
```

Runs locally at: `http://localhost:8501`

### From Mobile
- Same as desktop (any device with browser)
- Auto-responsive (adjusts for mobile screen size)
- Test on phone: 
  1. Get your public IP: `ipconfig` (Windows)
  2. Others access: `http://[your-ip]:8501`
  3. Or just use the Streamlit Cloud URL

---

## MONITORING THE DASHBOARD

### Set Up Monitoring Alerts
```
Streamlit → Settings → Notifications
- Email when app crashes
- Slack notification on errors
```

### Check Database Sync
In the dashboard, you'll see:
```
🟢 Database Status
├─ Last sync: 30 seconds ago
├─ Trades recorded: 342
└─ Size: 12.5 MB
```

If "Last sync" shows old time, database might be stale.

---

## MAINTENANCE SCHEDULE

### Daily
- Check app is running (visit URL)
- Glance at P&L in dashboard

### Weekly
- Review performance metrics
- Download trade report
- Check Streamlit logs for errors

### Monthly
- Backup database
- Update dependencies if needed
- Review secrets (rotate passwords)

---

## NEXT STEPS

1. ✅ Deploy app to Streamlit Cloud
2. ✅ Add secrets (Alpaca, Angel One, Telegram)
3. ✅ Test login
4. ✅ Verify database connection
5. ✅ Share URL with advisors/accountants
6. ✅ Start paper trading (May 8)
7. ✅ Monitor daily during paper trading

---

**Deployment Status:** READY ✅
**Go-live Date:** May 5, 2026
**Public URL:** https://aaats-trading-dashboard.streamlit.app
