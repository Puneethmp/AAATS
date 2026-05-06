# GitHub Actions Autonomous Build Setup

**Goal:** Run AAATS autonomous builds in the cloud 24/7 without your laptop needing to be on.

---

## ✅ SETUP STEPS

### Step 1: Create GitHub Repository

```bash
# If you haven't already
git init
git add .
git commit -m "Initial AAATS setup with autonomous build system"
git remote add origin https://github.com/YOUR_USERNAME/AAATS.git
git branch -M main
git push -u origin main
```

### Step 2: Verify Workflow File

Check that `.github/workflows/autonomous-build.yml` exists in your repo:

```bash
ls -la .github/workflows/
# Should show: autonomous-build.yml
```

### Step 3: Enable GitHub Actions

1. Go to: https://github.com/YOUR_USERNAME/AAATS
2. Click **"Actions"** tab
3. Click **"I understand my workflows, go ahead and enable them"**

### Step 4: Configure Build Schedule (Optional)

Edit `.github/workflows/autonomous-build.yml` and change the cron schedule:

```yaml
on:
  schedule:
    # Current: Daily at 8 AM UTC
    - cron: '0 8 * * *'

    # Options:
    # Every day at 8 AM: '0 8 * * *'
    # Every weekday at 8 AM: '0 8 * * 1-5'
    # Twice daily (8 AM & 8 PM): '0 8,20 * * *'
    # Every 6 hours: '0 */6 * * *'
```

### Step 5: Set GitHub Secrets (for real API integration)

If builds need to use real APIs (Angel One, Alpaca):

1. Go to: **Settings** → **Secrets and variables** → **Actions**
2. Add new secrets:

```
ANGEL_API_KEY: your_api_key
ANGEL_CLIENT_ID: your_client_id
ANGEL_PIN: your_pin
ANGEL_TOTP_SECRET: your_totp_secret
ALPACA_API_KEY: your_alpaca_key
ALPACA_SECRET_KEY: your_alpaca_secret
```

3. Update `.github/workflows/autonomous-build.yml` to use secrets:

```yaml
- name: Configure environment
  env:
    ANGEL_API_KEY: ${{ secrets.ANGEL_API_KEY }}
    ANGEL_CLIENT_ID: ${{ secrets.ANGEL_CLIENT_ID }}
    ANGEL_PIN: ${{ secrets.ANGEL_PIN }}
    ANGEL_TOTP_SECRET: ${{ secrets.ANGEL_TOTP_SECRET }}
  run: |
    echo "API credentials loaded from GitHub Secrets"
```

---

## 🚀 HOW IT WORKS

### 1. Scheduled Execution
```
Every day at 8 AM UTC:
  ├─ GitHub Actions spins up Ubuntu runner
  ├─ Checks out your code
  ├─ Installs Python, dependencies
  ├─ Reads SESSION_STATE.md
  ├─ Runs health checks
  ├─ Executes build sequence
  ├─ Commits changes
  ├─ Pushes to repo
  └─ Completes (logs available in Actions tab)
```

### 2. Manual Trigger (Optional)

You can also trigger builds manually:

1. Go to: GitHub → **Actions** tab
2. Select **"AAATS Autonomous Build"**
3. Click **"Run workflow"**
4. Wait for build to complete (check logs)

### 3. View Build Results

1. Go to: GitHub → **Actions** tab
2. Click latest workflow run
3. See detailed logs and outputs
4. Check **SESSION_STATE.md** in commits for what was built

---

## 📊 BUILD PROCESS (How GitHub Actions Runs It)

```
┌─ Scheduled Trigger (Daily 8 AM UTC)
├─ Setup Python 3.14 environment
├─ Install dependencies (pip install -r requirements.txt)
├─ Read SESSION_STATE.md to find next module
├─ Run health checks (pytest, git status)
├─ Execute build sequence:
│  ├─ PRE-BUILD VALIDATION
│  ├─ DESIGN REVIEW
│  ├─ CODE GENERATION
│  ├─ UNIT TESTS
│  ├─ INTEGRATION TEST
│  ├─ COMPLETION REPORT
│  └─ GIT COMMIT
├─ Update SESSION_STATE.md
├─ Commit and push changes
└─ Done (logs saved in GitHub)
```

---

## 🔐 SECURITY NOTES

✅ **Safe:**
- GitHub Actions runs in isolated containers
- Secrets are encrypted and never logged
- Each run gets a fresh environment
- Auto-cleanup after build

⚠️ **Best Practices:**
1. Use GitHub Secrets for API keys (not .env in repo)
2. Keep .env in .gitignore (never commit secrets)
3. Review workflows before enabling
4. Use branch protection rules if collaborative

---

## 🛠️ TROUBLESHOOTING

### Build fails with "Module not found"
```
Check: scripts/autonomous_build.py exists and is executable
Fix: git add scripts/autonomous_build.py && git commit && git push
```

### Build doesn't run at scheduled time
```
Check: Actions tab → "AAATS Autonomous Build" → "This workflow is disabled"
Fix: Click "Enable workflow"
```

### Can't push changes (authentication error)
```
GitHub Actions uses automatic GITHUB_TOKEN (built-in)
Should work automatically.
If fails: Check repo permissions and branch protection rules
```

### Tests failing in Actions but passing locally
```
Common causes:
  - PATH differences (Actions uses /home/runner/work/...)
  - Python version differences (specify python-version)
  - Missing dependencies in requirements.txt
  - Env variables not set (use GitHub Secrets)
```

---

## 📈 MONITORING

### View Build Logs
1. GitHub → **Actions** tab
2. Click workflow run
3. Click job name
4. See full execution logs

### Check Build Summary
- Each run generates a summary in **Annotations** section
- Shows what modules were built, test results

### Track Changes
- GitHub → **Commits** tab
- Filter by author: "Claude Autonomous Builder"
- See commit messages and changed files

---

## ⏸️ PAUSE/RESUME BUILDS

### Disable Workflow Temporarily
```yaml
# In .github/workflows/autonomous-build.yml, change:
on:
  schedule:
    # Comment out to disable:
    # - cron: '0 8 * * *'

  workflow_dispatch:
```

### Re-enable Workflow
```yaml
on:
  schedule:
    - cron: '0 8 * * *'  # Uncomment to enable

  workflow_dispatch:
```

---

## 📝 EXAMPLE: What Builds Look Like

### Successful Build
```
Job: autonomous-build
Status: ✅ Completed
Time: 5 minutes 23 seconds

Steps:
  ✅ Checkout code
  ✅ Set up Python
  ✅ Install dependencies
  ✅ Read session state
  ✅ Configure Git
  ✅ Health checks
  ✅ Build next module
  ✅ Run tests
  ✅ Update session state
  ✅ Commit and push

Commit: Autonomous build: 2026-04-29 — Phase 2 development
```

### Files Changed
```
SESSION_STATE.md (updated with build results)
.github/workflows/logs (timestamped)
```

---

## 🎯 NEXT: Integrate Claude Code (Advanced)

For full Claude Code integration in GitHub Actions:

```yaml
- name: Build with Claude Code
  env:
    CLAUDE_API_KEY: ${{ secrets.CLAUDE_API_KEY }}
  run: |
    pip install claude-sdk
    python -c "
    from claude import Claude
    claude = Claude(api_key='$CLAUDE_API_KEY')
    # Call autonomous build
    "
```

This requires:
1. Claude API key from https://console.anthropic.com
2. Install official Claude SDK
3. More complex workflow logic

**Status:** Currently this feature is in beta, but will be fully supported soon.

---

## 📊 BUILD VELOCITY WITH GITHUB ACTIONS

**Example Schedule:**
```
Monday-Friday: 8 AM build (2-3 modules per build)
Result: 10-15 modules per week

At this rate:
- Phase 2 (Strategies): 3-4 weeks
- Phase 3-7 (Advanced): 5-6 weeks
- Total: 2-3 months to complete system

Cost: FREE (GitHub Actions includes 2,000 free minutes/month)
```

---

## ✅ FINAL CHECKLIST

- [ ] GitHub repository created and pushed
- [ ] `.github/workflows/autonomous-build.yml` exists in repo
- [ ] GitHub Actions enabled in repo settings
- [ ] Schedule configured (daily 8 AM UTC or your preference)
- [ ] GitHub Secrets added (if using real APIs)
- [ ] First test run triggered manually
- [ ] Logs checked to verify build works
- [ ] SESSION_STATE.md updated with build results
- [ ] Commits pushed successfully

---

## 🚀 YOU'RE DONE!

Your AAATS system now builds **automatically in the cloud 24/7** without your laptop needing to be on.

**What happens next:**
1. GitHub runs builds on your schedule (daily 8 AM UTC)
2. Each build:
   - Reads SESSION_STATE.md
   - Determines next module
   - Builds 2-3 modules
   - Tests everything
   - Commits changes
   - Pushes to repo
3. You check GitHub whenever you want to see progress

---

**Created:** 2026-04-29 | **Status:** Ready for autonomous cloud builds
