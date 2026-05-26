# Deploy Hygiene Fix — Close the Recurring Deploy-Machinery Failure Class

**Date:** 2026-05-26 (follow-on to 2026-05-26 structural fix)
**Status:** ACTIVE
**Sprint:** Cowork session "stop the bug fires" — Part 2

## Context

The 2026-05-26 structural-fix deploy (commit `ba92446`) shipped successfully but required **9 manual interventions** during execution. The operator's report flagged them all and explicitly asked: "Also identify any recurring issues and fix it for once." Inspection confirmed each one had been logged in prior sessions but no script ever absorbed the lesson — every new deploy reinvented the same broken patterns.

## Diagnosis

| # | Failure | Concrete instance (2026-05-26) | Pattern in history |
|---|---|---|---|
| 1 | CRLF in `.sh` on box | `autopush.sh` uploaded via paramiko failed `bash -n`; ran on OLD copy until `sed -i 's/\r$//'` | Bit in 2026-05-15 metrics deploy, 2026-05-23 PF5.7 work |
| 2 | Windows cp1252 console | `deploy_structural_fix.py` crashed printing `→`; required `PYTHONIOENCODING=utf-8` | Any deploy script that prints emojis |
| 3 | Auto-cron 15-min race | Forced stash → rebase → pop dance during push | Documented since 2026-05-22, kept biting |
| 4 | Cowork `.git/index.lock` stuck | Cowork sandbox cannot unlink on mount; Windows must clear before commit | First seen 2026-05-25 Track E memo |
| 5 | Pre-commit ruff auto-format race | 4 files reformatted at commit time → had to re-stage and re-commit | Standing recurrence since pre-commit hook adoption |
| 6 | Grafana dashboard mount path drift | Deploy wrote to repo path; running Grafana reads `/srv/aaats/compose/grafana/dashboards/`; required manual `cp` | First explicit instance, but mount split has existed since `aaats-base` project setup |
| 7 | `.github/workflows/` dir absent on box | `mkdir -p` triage required during deploy | Bit on 2026-05-25 GitHub Actions workflow shipping |
| 8 | `docker cp` soft-fail noise | `cp FAILED: funding_arb_state.json` logged every cycle since 2026-05-24 | Logged 100+ times in last week of autopush.log |
| 9 | paramiko binary-mode CRLF | Same as #1 but for `.py` files; less catastrophic but still imports as CRLF text | Implicit in #1, distinct mechanism |

All 9 trace to one root class: **"deploy machinery has no consistent toolkit; every script reinvents the same broken patterns."**

## Decision

Ship a unified `tools/operator/deploy_lib.py` module that every future deploy script imports. The helpers each close one of the failure modes above with a one-line call site instead of an ad-hoc workaround. Retrofit the active autopush script (`scripts/box/aaats-autopush-v3.sh`) to existence-guard cp commands. Document gotchas in CLAUDE.md so future sessions don't have to re-derive.

### Files changed

- **NEW** `tools/operator/deploy_lib.py` — 250 lines, durable helpers:
  - `normalize_bytes_for_text_file(data, filename)` — CRLF→LF + BOM strip for textual extensions
  - `normalize_local_file_in_place(path)` — same, applied in-place
  - `atomic_upload_normalized(sftp, local, remote)` — replaces `sftp.put()`
  - `enforce_utf8_console()` — Windows cp1252 → UTF-8 stdout/stderr
  - `clear_stale_git_locks(repo_root)` — removes `.git/index.lock` etc
  - `auto_rebase_or_stash(branch)` — handles auto-cron 15-min race
  - `preflight_ruff_format(paths)` — runs ruff BEFORE `git add` so commit doesn't race
  - `ensure_remote_dirs(client, paths)` — mkdir -p parents
  - `push_grafana_dashboard(sftp, client, local)` — writes to BOTH repo path AND `GRAFANA_HOST_MOUNT`
  - `container_file_exists(client, container, path)` — test before cp
  - `smart_cp_state(client, ...)` — silent skip for ephemeral state files
  - Constants: `LINE_ENDING_NORMALIZE_EXTS`, `GRAFANA_HOST_MOUNT`, `EPHEMERAL_STATE_FILES`, `HARD_REQUIRED_STATE_FILES`

- **PATCHED** `scripts/box/aaats-autopush-v3.sh` — `cp_state()` now existence-guards via `docker exec test -f` BEFORE `docker cp`. Missing soft files skip silently (no log spam). Missing HARD files still increment `SNAPSHOT_FAILURES` and trigger alert. Closes failure mode #8.

- **PATCHED** `CLAUDE.md` — new "Deploy machinery gotchas" section under the top header. Every future Claude Code session reads this before touching deploy machinery.

### Not changed (deliberately)

- `tools/operator/deploy_to_contabo.py` — still uses tarball upload mechanism. Retrofitting it to use `deploy_lib` for line-ending normalization needs the `tar.addfile()` + custom `TarInfo` route, which is a slightly larger refactor than is wise to bundle in this sprint. Tracked as follow-up; the only currently-affected file types in its tarball are `.py` files which the existing Python interpreter handles regardless of CRLF on the box (so this is a latent-only bug, not active). Will revisit if it ever bites.
- The Grafana admin password rotation (`/srv/aaats/secrets/grafana_admin_password` out of sync) — pre-existing infra issue, not caused by deploy machinery; tracked separately.

## Verification

- `python -c "from tools.operator.deploy_lib import *; print('ok')"` — module imports clean (verified)
- CRLF strip, BOM strip, binary passthrough — unit tested (verified)
- `bash -n scripts/box/aaats-autopush-v3.sh` — parses (verified)
- The next autopush tick after deploy should show ZERO `cp FAILED` lines for `funding_arb_state.json` / `share_equality_mismatches.json` / `momentum_state.json`. Previously these polluted every tick.

## Rollback

Per-file: revert `tools/operator/deploy_lib.py` (it's a new file, just delete it; nothing imports it yet from active code paths). Revert `scripts/box/aaats-autopush-v3.sh` from the rollback baseline at `/home/aaats/bin/aaats-autopush.sh.bak-<ts>` written by the previous deploy. Revert CLAUDE.md by removing the new section.

## References

- `tools/operator/deploy_lib.py` (new)
- `scripts/box/aaats-autopush-v3.sh` (cp_state existence-guard at ~line 117)
- `CLAUDE.md` (new section at lines 4-26)
- Operator's final report from 2026-05-26 deploy listing the 9 manual interventions
- `docs/decisions/2026-05-26_structural_observability_fix.md` (the deploy these issues surfaced during)
