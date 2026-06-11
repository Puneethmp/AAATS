# Security Closeout — public-repo leak incident (2026-06-11)

> Phase B of the post-deploy closeout mandate. Incident class: secrets and
> container-log tails exposed in the PUBLIC GitHub repo `Puneethmp/AAATS`.
> Raw scan reports live OUTSIDE the repo (`C:\tmp\sectools\`) so secret
> values can never be committed; this document contains fingerprints only
> (first 4 chars + length + type).

## 1. Full-history secret scan

**Tools:** gitleaks v8.30.x (`detect --source . --log-opts="--all"` — all
branches incl. `archive/pre-prune-2026-06-10`, all tags, 3,723 commits,
104.5 MB) and trufflehog v3.95.5 (`git file://. --only-verified`, 71,247
chunks / 597 MB).

**Headline:** gitleaks 16 findings → **4 unique secret values**; trufflehog
**0 verified-live secrets** (none of the leaked values could be confirmed
active by external verification — but absence of verification is NOT
absence of risk; the TOTP seed and basic-auth pair are not in trufflehog's
verifiable-detector set).

| fp | type | where (history) | still at HEAD pre-scrub? | severity |
|---|---|---|---|---|
| `JZCR…` len 26 | base32 TOTP seed (Angel One `INDIA__ANGEL_TOTP_SECRET`) | README.md, ANGEL_ONE_SETUP.md, AAATS_LEGAL_TRADING_SETUP.md, GITHUB_ACTIONS_QUICK_START.md, config/.env.example — since 2026-04-28 | YES (5 files) | HIGH — permanent 2FA seed, public ~6 weeks |
| `admi…` len 30 | Grafana `admin:<password>` basic-auth pair | docs/security/OPERATOR_ROTATION_RUNBOOK.md — since 2026-05-22 | YES (1 file) | MEDIUM — Grafana is Tailscale-only :3000, not internet-reachable, but the pw was public |
| `admi…` len 11 | Grafana `admin:<short pw>` (older pw) | 4 one-off operator scripts — since 2026-05-15 | YES (4 files) | MEDIUM (same mitigation) |
| `eyJh…` len 184 | Cloudflare tunnel token (JWT) | tools/operator/remote_final.py — since 2026-05-15 | YES (1 file) | HIGH — grants tunnel attach to the CF account |

Log-tail vector (the original FIX 4 finding): `runtime/{engine,paper_crypto}.log`
pushed every 15 min until 2026-06-10. Current-snapshot scan of those logs
found no secret patterns; the vector is closed (0 log pushes across 73
post-deploy cron cycles — see AUDIT/deploy_verification.md A6).

## 2. Remediation executed 2026-06-11 (this session)

- **HEAD scrub:** all 4 values replaced with placeholders across 10 tracked
  files (commit referenced below). Post-scrub verification: gitleaks worktree
  scan → **0 real findings in tracked files** (1 false positive: an empty
  `.env.example` template line where the regex captured the next line's
  variable name; values there are all empty).
- Raw reports + credential survey retained at `C:\tmp\sectools\`
  (workstation-local, not in the repo).

## 3. Rotation table

Credential inventory from the box survey (`/home/aaats/aaats/.env` variable
names, `/srv/aaats/secrets/` listing) + workstation `.env`. **Rotated?** is
the operator's column to fill; smoke tests marked ✅ were run this session.

| Credential | Lives at (box) | Leaked? | Rotated? (operator) | Post-rotation smoke test |
|---|---|---|---|---|
| `INDIA__ANGEL_TOTP_SECRET` | `/home/aaats/aaats/.env` | **YES (public 6 wks)** | ☐ — re-generate the TOTP seed in Angel One SmartAPI portal (rotating the API key alone does NOT fix this) | `python -m pytest tests/test_india/test_angel_one_integration.py -k totp` (currently credential-gated/skipping) |
| `INDIA__ANGEL_API_KEY` / `CLIENT_ID` / `PIN` | `/home/aaats/aaats/.env` | not found in repo | ☐ recommended alongside TOTP re-key | same test file, auth case |
| `CLOUDFLARE__TUNNEL_TOKEN` | `/home/aaats/aaats/.env` + `/srv/aaats/secrets/cloudflared.env` | **YES** | ☐ — delete + recreate tunnel (or rotate token) in CF Zero-Trust dashboard, update both files, restart `aaats-cloudflared*` | `docker logs aaats-cloudflared --tail 5` shows registered tunnel; bot webhook reachable |
| Grafana admin password | `/home/aaats/aaats/.env` (`CONTABO__GRAFANA_PASSWORD`) + `/srv/aaats/secrets/grafana_admin_password` (mounted via `GF_SECURITY_ADMIN_PASSWORD__FILE`) | **YES (two historical values)** | ☐ — was already flagged out-of-sync (CLAUDE.md gotcha); rotate via grafana-cli or secrets file + container restart | `curl -s -u admin:<new> http://100.95.126.39:3000/api/health` over Tailscale → `"database": "ok"` |
| `ALERTS__TELEGRAM_BOT_TOKEN` | `/home/aaats/aaats/.env` (canonical) | not in repo; log-tail exposure possible pre-2026-06-10 | operator reported rotation in progress 2026-06-10 | ✅ PASSED — `verify_telegram_path()` smoke ok at deploy (2026-06-10T17:12Z) and alerts delivered pre+post rebuild |
| `/srv/aaats/secrets/telegram_bot_token` | box secrets dir | stale (404s `getMe` since ≥2026-05-27) | ☐ delete or sync — dead path, known gotcha #11 | `curl api.telegram.org/bot$(cat …)/getMe` → expect 200 after sync, or file removed |
| `CRYPTO__BINANCE_API_KEY` / `SECRET` | `/home/aaats/aaats/.env` | not in repo | operator reported rotation in progress 2026-06-10 | Public-data path ✅ (74 cycles fetching OHLCV). Authenticated smoke (operator, optional): `docker exec aaats-paper-crypto python -c "import ccxt,os; ex=ccxt.binance({'apiKey':os.getenv('CRYPTO__BINANCE_API_KEY'),'secret':os.getenv('CRYPTO__BINANCE_SECRET_KEY')}); print(ex.fetch_balance()['info']['canTrade'])"` |
| `CONTABO__SSH_PASSWORD` | workstation `.env` + box `.env` | not in repo | ☐ optional — recommend moving to key-only SSH (an `aaats_deploy` keypair already exists on the box) | `ssh aaats@100.95.126.39 true` |
| `US__ALPACA_API_KEY` / `SECRET` | `/home/aaats/aaats/.env` | not in repo | ☐ optional (paper-only, US market inactive) | n/a |
| `KILLALL_TOTP_SECRET` | `/home/aaats/aaats/.env` | not in repo | ☐ optional | kill.py TOTP path |
| postgres / redis / grafana_api_key / webhook tokens | `/srv/aaats/secrets/*` | not in repo (box-local only) | not required | internal-only services |
| GitHub push access | box `~/.ssh/aaats_deploy` deploy key (remote is `git@github.com:…`) | not in repo | ☐ optional | `ssh -i ~/.ssh/aaats_deploy -T git@github.com` |

## 4. Repo visibility — ⚠️ CRITICAL, OPERATOR ACTION REQUIRED

Checked 2026-06-11T11:43Z: `GET https://api.github.com/repos/Puneethmp/AAATS`
unauthenticated returns **HTTP 200 — the repo is still PUBLIC.** Date made
private: ____________ (operator fills in).

Why this is not flipped automatically by this session: visibility affects
integrations (the Streamlit Cloud dashboard reads this repo; GitHub Actions
minutes become metered — see cost note in `.github/workflows/gitleaks.yml`).
**Recommendation: make it private today.** All four leaked values remain in
the still-public git HISTORY even after the HEAD scrub.

**History purge (recommended, NOT executed — needs sign-off):** on a fresh
mirror clone, `git-filter-repo --replace-text` with the four values, force
push, then re-clone the box runtime repo and re-protect branches. Note
plainly: **rotation matters more than purging** — the history has already
been public for ~6 weeks, so the values must be treated as burned regardless
of whether they are scrubbed from history. Purge is hygiene, not remediation.

## 5. Prevent recurrence

- ✅ **CI gitleaks gate:** `.github/workflows/gitleaks.yml` — scans every
  push (incl. the box's 96/day auto-cron runtime pushes, exactly the vector
  that leaked logs). Runs on GitHub infra, so a compromised/buggy box-side
  script can't skip it.
- ✅ **Workstation pre-commit gitleaks** was already in
  `.pre-commit-config.yaml` (the 4 leaks predate its installation; the CI
  gate now backstops anything committed with `--no-verify`).
- ✅ **.gitignore coverage verified:** `.env`/`*.env`/`.env.live*` (line 2-5),
  `logs/` (29), `runtime/*.log` (107), `runtime/*.db-wal|shm`,
  `runtime/.fuse_hidden*`, `runtime/t3_offbox_backups/` — covers every
  artifact class the box writes. Auto-cron payload is now exactly
  `STATUS.md, auto_cron_heartbeat.json, ledger_divergence_alerts.json,
  paper_trades.db` (verified in A6 evidence).

## Status

| Item | State |
|---|---|
| Full-history scan (gitleaks + trufflehog, all refs) | ✅ done — 4 unique leaks, 0 verified-live |
| HEAD scrub | ✅ done, worktree clean |
| Rotation | ⏳ operator: Telegram+Binance reported in progress (Telegram smoke ✅); **Angel TOTP re-key, CF tunnel token, Grafana admin pw still open** |
| Repo private | ❌ **STILL PUBLIC — top remaining action** |
| History purge | recommended, awaiting sign-off (rotation > purge) |
| Recurrence prevention | ✅ CI gate + pre-commit + .gitignore verified |
