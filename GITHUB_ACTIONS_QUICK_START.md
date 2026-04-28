# GitHub Actions Setup - Quick Start (5 Minutes)

**Goal:** Enable autonomous AAATS builds in the cloud so your laptop can be OFF.

---

## ⚡ QUICK SETUP (Copy-Paste)

### Step 1: Initialize Git Repository (if not done)

```bash
cd C:\Users\udaym\OneDrive\Desktop\Puneeth

# Initialize git
git init
git config user.name "Puneeth"
git config user.email "puneethmp106@gmail.com"

# Add all files
git add .
git commit -m "Initial commit: AAATS with autonomous build system"
```

### Step 2: Create GitHub Repository

1. Go to: https://github.com/new
2. Enter:
   - Repository name: `AAATS` (or your choice)
   - Description: `Autonomous Adaptive AI Trading System`
   - Visibility: Private (or Public)
3. Click **Create repository**

### Step 3: Push to GitHub

```bash
# Add remote (replace YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/AAATS.git
git branch -M main

# Push code
git push -u origin main
```

### Step 4: Enable GitHub Actions

1. Go to: https://github.com/YOUR_USERNAME/AAATS
2. Click **Actions** tab
3. See: "This workflow is disabled. Enable it to build your code"
4. Click **"I understand my workflows, go ahead and enable them"**

### Step 5: Verify Workflow

1. GitHub → **Actions** tab
2. Should see: **"AAATS Autonomous Build"** workflow
3. Click it → Click **"Run workflow"** button
4. Wait ~5 minutes for first build to complete

✅ **Done!** Your builds will now run automatically.

---

## 🎯 WHAT HAPPENS NOW

### Every Day at 8 AM UTC:
```
GitHub Actions automatically:
  1. Spins up a cloud server
  2. Checks out your code
  3. Reads SESSION_STATE.md
  4. Builds next module (2-3 per day)
  5. Runs all tests
  6. Commits changes
  7. Pushes to repository
  8. Completes (you get notified)
```

### Your Laptop:
```
- Can be OFF ✅
- Can be ASLEEP ✅
- Can be OFFLINE ✅
- Just needs internet for git push (which GitHub Actions handles)
```

---

## 📊 MONITORING (Anytime, Anywhere)

### Check Build Status
```
GitHub.com → Your repo → Actions tab
See: ✅ Latest build status and logs
```

### View Changes
```
GitHub.com → Your repo → Commits tab
See: What modules were built, code changes
```

### Read Progress
```
GitHub.com → Your repo → Browse SESSION_STATE.md
See: Which modules completed, what's next
```

---

## 🔐 OPTIONAL: Add API Credentials to GitHub

If you want GitHub Actions to test with REAL APIs (Angel One, Alpaca):

### 1. Create Secrets in GitHub

```
GitHub → Your repo → Settings → Secrets and variables → Actions
```

### 2. Add Each Secret

```
Name: ANGEL_API_KEY
Value: REDACTED_ANGEL_KEY

Name: ANGEL_CLIENT_ID
Value: REDACTED_ANGEL_CLIENT_ID

Name: ANGEL_PIN
Value: 9066

Name: ANGEL_TOTP_SECRET
Value: JZCRAQDC7SYURTQE5VR5GALAF4

(Repeat for Alpaca if needed)
```

### 3. Uncomment in Workflow

Edit `.github/workflows/autonomous-build.yml`:

```yaml
- name: Set API credentials
  env:
    ANGEL_API_KEY: ${{ secrets.ANGEL_API_KEY }}
    ANGEL_CLIENT_ID: ${{ secrets.ANGEL_CLIENT_ID }}
    ANGEL_PIN: ${{ secrets.ANGEL_PIN }}
    ANGEL_TOTP_SECRET: ${{ secrets.ANGEL_TOTP_SECRET }}
  run: |
    echo "ANGEL_API_KEY=$ANGEL_API_KEY" >> .env
    echo "ANGEL_CLIENT_ID=$ANGEL_CLIENT_ID" >> .env
    echo "ANGEL_PIN=$ANGEL_PIN" >> .env
    echo "ANGEL_TOTP_SECRET=$ANGEL_TOTP_SECRET" >> .env
```

✅ Then builds will test with REAL APIs automatically.

---

## ⏰ ADJUST BUILD SCHEDULE

Edit `.github/workflows/autonomous-build.yml`:

### Current (Daily 8 AM UTC):
```yaml
- cron: '0 8 * * *'
```

### Other Options:

**Every 6 hours:**
```yaml
- cron: '0 */6 * * *'
```

**Twice daily (8 AM & 8 PM):**
```yaml
- cron: '0 8,20 * * *'
```

**Weekdays only:**
```yaml
- cron: '0 8 * * 1-5'
```

**Every 4 hours:**
```yaml
- cron: '0 */4 * * *'
```

Then commit and push:
```bash
git add .github/workflows/autonomous-build.yml
git commit -m "Update build schedule"
git push
```

---

## ✅ VERIFY EVERYTHING IS WORKING

### Manual Test (Right Now)

1. GitHub → **Actions** tab
2. Select **"AAATS Autonomous Build"**
3. Click **"Run workflow"** button
4. Select branch: **main**
5. Click **"Run workflow"**
6. Wait 3-5 minutes
7. See result: ✅ Passed or ❌ Failed

### Check Logs

1. Click the completed workflow
2. Click the job
3. Expand each step to see details
4. Should see: tests passing, commits pushed

### Confirm Changes Pushed

```bash
# In your local terminal
cd C:\Users\udaym\OneDrive\Desktop\Puneeth

# Pull latest changes from GitHub
git pull

# See new commits from GitHub Actions
git log --oneline -5
# Should show: "Autonomous build: 2026-04-29..."
```

---

## 🎉 YOU'RE DONE!

Your AAATS system now builds **automatically in the cloud 24/7**.

### What You Get:
- ✅ Autonomous builds without your laptop
- ✅ Scheduled daily at 8 AM UTC
- ✅ 2-3 modules built per day
- ✅ All tests run automatically
- ✅ Changes auto-committed and pushed
- ✅ Free (GitHub Actions = 2,000 free minutes/month)
- ✅ Complete autonomy (no manual intervention)

### Timeline to Completion:
```
Phase 1: 2 more weeks (finish data pipeline)
Phase 2: 3-4 weeks (strategies)
Phase 3-7: 5-6 weeks (advanced features)
Total: ~2-3 months to production-ready system
```

---

## 🆘 QUICK TROUBLESHOOTING

### "Workflow doesn't run at scheduled time"
```
Check: GitHub → Settings → Actions → Enable
Click: "I understand my workflows, go ahead..."
```

### "Workflow fails with Python error"
```
Check: Does requirements.txt have all deps?
Fix: Add missing package, push, workflow retries
```

### "Push fails with auth error"
```
Don't worry: GitHub Actions has automatic token
Should work automatically
If still fails: Check repo permission settings
```

### "Can't see workflow in Actions tab"
```
Check: .github/workflows/autonomous-build.yml exists
Check: Committed and pushed to main branch
Check: GitHub Actions enabled (see above)
```

---

## 📞 SUPPORT

- **Status:** All files created and ready
- **Next:** Push to GitHub and enable Actions
- **Questions:** Check GITHUB_ACTIONS_SETUP.md for details

---

**Setup time:** ~5 minutes  
**Cost:** FREE  
**Result:** 24/7 autonomous cloud builds  
**Your laptop:** Can stay OFF

✅ Ready to go!
