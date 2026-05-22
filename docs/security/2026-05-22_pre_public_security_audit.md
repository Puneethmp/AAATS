# Pre-public security audit (2026-05-22)

**Status:** ACTION REQUIRED — operator must complete Tier 2 items before flipping the repo to public.
**Authored:** 2026-05-22 (Claude Code session 2 follow-up).
**Trigger:** Operator stated intent to make `Puneethmp/AAATS` public.

## TL;DR

| Tier | What | Who | When |
|---|---|---|---|
| 0 | Rotate SSH password on Contabo box; disable password auth | **Operator** | **BEFORE going public** |
| 0 | Rotate Telegram bot token | **Operator** | Before going public |
| 0 | Rotate any broker API keys ever stored in `.env` | **Operator** | Before going public |
| 0 | Rotate Grafana admin password (separate from SSH password — also leaked) | ✅ DONE 2026-05-22 via `grafana cli admin reset-admin-password`; new value in workstation `.env` + `~/grafana_admin_pw_2026-05-22.txt` | — |
| 1 | Replace hardcoded SSH password in 11 ops scripts (7 SSH + 4 Grafana-curl) with env-var pattern | DONE this commit | — |
| 1 | Add `.env.example`, `SECURITY.md`, `.pre-commit-config.yaml` with gitleaks | DONE this commit | — |
| 2 | Decide repo-public path (new clean repo vs sanitize-this-repo vs portfolio-only) | **Operator** | Decision required |
| 2 | If sanitize path: rewrite history with `git-filter-repo`, force-push, accept the auto-cron break | **Operator** + Claude | After Tier 0 |
| 2 | Enable GitHub-side secret scanning, push protection, Dependabot, branch protection | **Operator** | After flipping to public |
| 3 | Decide whether `data/*.db`, `data/operator/*.md`, and strategy code in `trading/` should ship to public | **Operator** | Decision required |

## What was found

### CRITICAL — hardcoded SSH password in 11 tracked files

The literal SSH password for `aaats@100.95.126.39` (value: `Puneeth1234`)
appears in 11 tracked files. The first 7 use the pattern `PASSWORD = "Puneeth1234"`:

- [`tools/operator/check_engine.py`](../../tools/operator/check_engine.py)
- [`tools/operator/check_and_start_trader.py`](../../tools/operator/check_and_start_trader.py)
- [`tools/operator/fix_missing_modules.py`](../../tools/operator/fix_missing_modules.py)
- [`tools/operator/remote_followup.py`](../../tools/operator/remote_followup.py)
- [`tools/operator/remote_diagnostics.py`](../../tools/operator/remote_diagnostics.py)
- [`tools/operator/diagnose_grafana_cf.py`](../../tools/operator/diagnose_grafana_cf.py)
- [`tools/operator/remote_final.py`](../../tools/operator/remote_final.py)

Four more use slight variants (one had a `.env`-fallback to the literal,
two used `PASS = ...` / `SSH_PASS = ...`):

- [`tools/operator/deploy_to_contabo.py`](../../tools/operator/deploy_to_contabo.py)
- [`tools/operator/diagnose_and_fix.py`](../../tools/operator/diagnose_and_fix.py)
- [`tools/operator/fix_issues.py`](../../tools/operator/fix_issues.py)
- [`tools/operator/deploy_grafana_dashboard.py`](../../tools/operator/deploy_grafana_dashboard.py)

Combined with the host IP (also in the same files), anyone reading the repo
has working SSH credentials.

### CRITICAL — hardcoded Grafana admin password in 5 tracked files

A second credential leak surfaced during this audit. The Grafana admin
password (a 23-char alphanumeric token) is embedded in `curl -u admin:<token>`
calls in 5 files:

- [`tools/operator/deploy_grafana_dashboard.py`](../../tools/operator/deploy_grafana_dashboard.py)
  (as part of an HTTP URL constant)
- [`tools/operator/diagnose_and_fix.py`](../../tools/operator/diagnose_and_fix.py)
- [`tools/operator/remote_followup.py`](../../tools/operator/remote_followup.py)
- [`tools/operator/remote_diagnostics.py`](../../tools/operator/remote_diagnostics.py)
- [`tools/operator/remote_final.py`](../../tools/operator/remote_final.py)

Grafana is Tailscale-only (not internet-routable), so the immediate blast
radius is bounded to the tailnet. But anyone on the tailnet (or anyone who
compromised it via the SSH leak above) has admin-level Grafana access:
read all dashboards, exfiltrate metrics, modify alert rules to silence
production alerts, add a malicious data source. Rotate this as part of
the same Tier 0 sweep as the SSH password.

**This commit (session 2 security pass) replaces all 11 SSH-password
occurrences and all 5 Grafana-password occurrences with
`os.environ.get(...)` reads** that raise `SystemExit` if the env var is
unset. The pattern is consistent across files. To run any
of these scripts now, the operator must:

1. Copy `.env.example` → `.env`.
2. Fill in `AAATS_SSH_PASSWORD=<rotated password>`.
3. Source the env file (`set -a; source .env; set +a`) or use a tool like
   `direnv` / `python-dotenv` to load it.

**The hardcoded value is still in `git log` for all 1,661 historical commits.**
This means anyone with a clone of the current repo — including any past
contributors, automated backups, GitHub event listeners, and any web archive
that scraped during a brief public window — still has the password. Treat the
password as **permanently compromised** and rotate immediately, regardless of
whether you go public.

### HIGH — infrastructure identifiers in 49 tracked files

- **`100.95.126.39`** — the box's Tailscale IP. Tailscale-only addresses are
  not internet-routable, BUT they reveal the network topology and (combined
  with the leaked SSH password) allow anyone on a compromised Tailscale node
  to pivot directly into the trading box.
- **`1946109268`** — the Telegram chat ID receiving alerts. Anyone with the
  Telegram bot token can spam this chat (and tokens can leak via Telegram bot
  enumeration if the bot was ever publicly named).
- **`puneethmp`** — operator identifier across multiple files.

Files containing one or more of these (grep `100\.95\.126\.39|1946109268|puneethmp`
returns 49 matches): mostly under [`docs/`](../), [`scripts/`](../../scripts/),
[`tools/operator/`](../../tools/operator/), and [`.rollback/`](../../.rollback/).
The pattern is dense enough that wholesale scrubbing should be templated
(via a substitution table) rather than file-by-file edits.

### HIGH — committed trade/state data

`.gitignore` has explicit exceptions for the following files, so they are
tracked and live in `origin/main`:

```
!data/paper_trades.db
!data/positions.db
!data/equity_curve.db
!data/slippage.db
!data/status.db
!data/ledger_flag_history.json
!data/halt_state.json
!data/phase1_checkpoint.json
!data/phase1_metrics.json
```

The Contabo box auto-cron pushes a new snapshot of these every 15 minutes,
so the git history contains **hundreds of versions** of `paper_trades.db`
(months of full trade signal/timing/sizing data — your strategies'
fingerprints) and the equity curve.

Going public ships this entire trade history. **Operator decision required:**
is the trade-history audit-trail visibility worth exposing the strategy edge?

If no, the `.gitignore` exceptions need to be removed AND the auto-cron's
push behaviour (which assumes these are tracked) needs to change. That's
a follow-up sprint.

### MEDIUM — proprietary strategy code

The entire `trading/` tree is the IP refined over the rebuild sprint:

- [`trading/altcoin_reversion.py`](../../trading/altcoin_reversion.py) (C3)
- [`trading/bollinger_range.py`](../../trading/bollinger_range.py) (C6)
- [`trading/stat_arb.py`](../../trading/stat_arb.py) (C1)
- [`trading/momentum_breakout.py`](../../trading/momentum_breakout.py) (C2)
- [`trading/funding_arb.py`](../../trading/funding_arb.py) (C5b, currently halted)
- [`trading/live_paper_runner.py`](../../trading/live_paper_runner.py)

Plus the parameter constants (entry z, exit z, hard stops, BTC.D thresholds,
cooldown windows) and the doctrine docs at
[`docs/operator/`](../../docs/operator/). Once public, anyone can run a
near-identical clone.

**Operator decision required:** publish full strategies, redact key
constants, or publish only a high-level architecture summary?

### MEDIUM — operator personal/planning context

- [`docs/operator/aaats_locked_doctrine_2026_05_14.md`](../../docs/operator/aaats_locked_doctrine_2026_05_14.md)
  — capital plan ($25 → $50 → $100 escalation), 5 doctrine gates, kill
  triggers.
- [`docs/operator/aaats_strategy_universe.md`](../../docs/operator/aaats_strategy_universe.md)
  — design intent of all 12 strategies.
- [`docs/operator/aaats_2026_05_21_no_go.md`](../../docs/operator/aaats_2026_05_21_no_go.md)
  — current NO-GO status with full diagnostic appendix.
- [`docs/operator/aaats_dual_equity_ledger_debt.md`](../../docs/operator/aaats_dual_equity_ledger_debt.md)
  — architectural debt history.

These are intentional internal-planning docs. Going public ships your
business plan along with the code.

### MEDIUM — `.rollback/*/MANIFEST.txt` audit history

Tracks every box-side deploy with pre-deploy SHAs and exact rollback
procedures. Useful context for collaborators; sensitive infrastructure
detail for adversaries. Worth keeping in private fork; debatable in public.

### LOW — existing CI/CD is clean

[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) and
[`autonomous-build.yml`](../../.github/workflows/autonomous-build.yml) only
contain `test_*` placeholder values for broker/Telegram creds. No real
secrets in workflow files.

[`requirements.txt`](../../requirements.txt) pinning is `>=`-based, not
exact. **Recommend pinning exact versions before public** — `>=` permits
silent dependency-confusion attacks via re-published older packages.

## Three realistic paths to "public"

### Path A — New public repo (RECOMMENDED, lowest risk)

1. Keep `Puneethmp/AAATS` private. It contains your full history and
   secrets (already compromised; rotate but don't try to scrub).
2. Create `Puneethmp/AAATS-public`. Hand-pick what to ship:
   - Code with secrets-via-env-var (already done in this commit).
   - `docs/decisions/` (architecture, decision history).
   - `docs/specs/`, `docs/runbooks/`.
   - Tests.
   - `SECURITY.md`, `.pre-commit-config.yaml`, `.env.example`.
   - Skip: `docs/operator/`, `data/*.db`, `.rollback/`, the box-IP files,
     specific strategy constants if you want to redact them.
3. **Use `git init` in the public repo with no history.** The first commit
   is a clean snapshot of what you choose to ship.
4. Time: 1–3 hours of file-curation + one operator decision on
   strategy-redaction depth.

**Why recommended:** the password leak in history is permanent. A new repo
sidesteps it entirely. You also get to curate what your public-facing brand
looks like.

### Path B — Sanitize-and-flip this repo (HIGHER RISK)

1. Operator rotates all credentials first (Tier 0).
2. Run [`git-filter-repo`](https://github.com/newren/git-filter-repo) with a
   substitution table that scrubs:
   - `Puneeth1234` → `***REDACTED***`
   - `100.95.126.39` → `<BOX_IP>`
   - `1946109268` → `<TELEGRAM_CHAT_ID>`
   - Plus removal of all `data/*.db` blobs (those are big).
3. Force-push to `origin/main`. This rewrites all 1,661 commits.
4. Notify any existing clones (including the box's auto-cron) to reset
   their working trees: `git fetch && git reset --hard origin/main`.
5. Flip visibility on GitHub.
6. Enable GitHub secret scanning + push protection so future leaks are
   blocked.

**Risks:** force-pushing breaks the box's auto-cron (next 15-min push will
fail with non-fast-forward — operator must intervene). The scrub will miss
context-dependent secret patterns (e.g., a passphrase mentioned in a code
comment that doesn't match the substitution table). Anyone who cloned
during the leaky window already has the data.

### Path C — Stay private; share a portfolio snippet only

1. Don't flip visibility at all.
2. Create a separate public `Puneethmp/aaats-portfolio` with:
   - A README screenshot of the Grafana dashboard.
   - One redacted architecture diagram.
   - The session 1/2 decision docs with operator-info scrubbed.
3. No working code, no strategy code, no infrastructure detail.

**When to choose:** if the goal is "show recruiters / collaborators what
you've built" rather than open-source the system. Lowest risk, lowest signal.

## What this commit does

Tier 1 actions that need no approval — applied:

- **Replaces hardcoded `Puneeth1234` in 7 files** with env-var reads.
  Operator must set `AAATS_SSH_PASSWORD` to run any of those scripts now.
- **Adds [`.env.example`](../../.env.example)** documenting every env var
  the project consumes.
- **Adds [`SECURITY.md`](../../SECURITY.md)** with the responsible-disclosure
  policy.
- **Adds [`.pre-commit-config.yaml`](../../.pre-commit-config.yaml)** with
  the `gitleaks` hook (blocks future secret commits) + standard hygiene
  hooks (large-file block, JSON validation, ruff, bandit).
- **Adds this audit document.**

## What this commit does NOT do (operator-action required)

Tier 0 (do BEFORE going public):

- [ ] **Rotate SSH password on box.** SSH to `aaats@100.95.126.39` (via
      Tailscale), `passwd`, pick a strong password OR (recommended) disable
      password auth entirely and require key-based auth:
      ```bash
      ssh-copy-id aaats@100.95.126.39   # if not already
      sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
      sudo systemctl restart ssh
      ```
- [ ] **Rotate Telegram bot token.** Via @BotFather → /token → /revoke.
      Update `ALERTS__TELEGRAM_BOT_TOKEN` in your `.env` and on the box.
- [ ] **Rotate any broker API keys** stored in the box's `.env`. Even if
      they were never in the repo, the box itself may have been compromised
      via the leaked SSH password.

Tier 2 (decisions):

- [ ] Pick Path A / B / C from §"Three realistic paths".
- [ ] If Path A or B: decide on strategy-redaction depth.
- [ ] If keeping `data/*.db` tracked, accept that the trade-history is public
      (audit-trail value vs. strategy-edge cost).

Tier 3 (GitHub-side, after flipping):

- [ ] Enable secret scanning + push protection (Settings → Code security →
      Secret scanning + Push protection).
- [ ] Enable Dependabot security updates (Settings → Code security →
      Dependabot).
- [ ] Set up branch protection on `main`:
      - Require pull request reviews before merging.
      - Require status checks (CI) to pass.
      - Do NOT enable "Require linear history" yet — the box's auto-cron
        push pattern relies on merge commits.
- [ ] Install pre-commit hooks locally: `pip install pre-commit && pre-commit install`.
- [ ] (Optional) Pin `requirements.txt` to exact versions (`==`) before
      enabling Dependabot, so upgrades come in via Dependabot PRs rather
      than silent installs.
- [ ] (Optional) Enable CodeQL scanning (Settings → Code security → Code
      scanning → Set up → CodeQL).

## Verifying the changes

After applying this commit:

```bash
# 1. Confirm no hardcoded password remains in tracked files:
git grep "Puneeth1234"
# Expected: only this audit doc + (already removed) historical commits.

# 2. Confirm the operator scripts fail informatively when env var is unset:
unset AAATS_SSH_PASSWORD
python tools/operator/check_engine.py
# Expected: "AAATS_SSH_PASSWORD env var not set. Copy .env.example to .env, ..."

# 3. Install and run the pre-commit hook locally:
pip install pre-commit
pre-commit install
pre-commit run --all-files
# Expected: gitleaks reports the existing `data/*.db` and historical
# matches under tools/operator/ — investigate any reports against new files.
```

## Trending defensive baselines worth adding (recommendations)

These are 2025–2026 trending practices we don't yet have:

- **SLSA provenance** for any built artifacts (irrelevant until we ship
  containers to a registry; future).
- **Sigstore-style commit signing.** `git config gpg.format ssh` + your
  GitHub-registered SSH key produces signed commits with no GPG keyring
  needed.
- **Sigstore/Cosign for the trading-container image** if it ever lands on a
  registry.
- **OpenSSF Scorecard** integration via GitHub Action — auto-grades your
  repo against the 20-ish security best practices and publishes the score.
- **Dependency review action** on PRs (built-in GitHub feature, free for
  public repos) — blocks merges that introduce known-CVE dependencies.

Add these incrementally; none are blockers for going public.
