# Box ↔ repo forensic hash audit (2026-05-15)

- **Audit valid as of**: 2026-05-15 (UTC).
- **Container image SHA**: `7051c405c75abb11f0056055a2390d0071ccc858ff3e7bfc075627291d83a160` (created `2026-05-15T11:36:18+02:00` = `09:36:18 UTC`).
- **Container started**: `2026-05-15T09:36:31 UTC` (`aaats-paper-crypto`).
- **`origin/main` HEAD at audit time**: `e118a91` (auto-cron tip; the last non-auto commit is `4842abf docs(ops): fix deploy-dirty-guard wiring SHA after rebase`).
- **Verdict**: **FAIL** — material drift identified. Pre-live gate **G3 OPEN**.

## Why this audit ran

Per the deploy-dirty-guard work (commits `0d6c83e`..`4842abf`), all known
file-level drift between the Contabo box and `origin/main` should now be
prevented by the in-script guard. This audit is a one-shot validation that
the prior cleanup was complete and that the running container can be
trusted as faithful to `origin/main`. A hard pre-live readiness gate.

## Methodology

1. **Define the audit set.** All files tracked in `origin/main` with source-
   code-like extensions (`.py`, `.yml`, `.yaml`, `.toml`, `.json`, `.ini`,
   `.cfg`, `.txt`, `.in`, `.sh`, `Dockerfile`), excluding pure-documentation
   and rollback/runtime paths (`docs/`, `.github/`, `.rollback/`, `.claude/`,
   `.streamlit/`, `runtime/`, `data/`, `logs/`, `diagnostics/reports/`) and
   the freeform `*_COMPLETE.md` / `*_SUMMARY.md` root markers.
   - Result: **413 files**.
2. **Hash the canonical (`origin/main`) side.** For each path, resolve its
   blob OID via `git ls-tree -r origin/main`, then `git cat-file blob <oid> |
   sha256sum`. (A first pass used `git show "origin/main:<path>" |
   sha256sum`; that silently produced empty-blob hashes for paths beginning
   with `.`, which would have masked drift. The cat-file path is robust.)
3. **Hash the box side.** SSH into `aaats@100.95.126.39`, exec inside the
   running `aaats-paper-crypto` container, and `find /app -type f` with the
   same extension filter and the runtime/rollback exclusions, then
   `sha256sum`.
   - Result: **142 files** found on box.
4. **Path-set arithmetic.** Compute three sets:
   - (a) paths in audit manifest, not in box;
   - (b) paths on box, not in audit manifest;
   - (c) common paths whose hashes differ.

## Findings

| Category | Count | Severity |
| --- | --- | --- |
| (a) In repo, missing from container | **278** | **HIGH** — image is built from a partial source tree |
| (b) In container, not in repo | **7** | LOW–MEDIUM — all 7 are post-build-time tombstones |
| (c) Common-path hash mismatches | **0** | **n/a — the audit's only good news** |

The (c) = 0 result is the structurally important one: every file that
exists on both sides matches `origin/main` byte-for-byte. The per-file
SCP discipline is faithful. The drift is at a coarser granularity —
whole directories — not at the file content level.

### (a) Files in repo absent from container — by top-level entry

| Entry | Missing count | Notes |
| --- | --- | --- |
| `tests/` | 65 | Not loaded at runtime by `paper_loop.py`. Low operational risk. |
| `v6-stack/` | 57 | Used by the separate `engine/` compose stack, not by `aaats-paper-crypto`. |
| `strategies/` | 46 | High potential impact if any code path imports from it. |
| `streamlit_app/` | 17 | Dashboard service runs from the same image — would fail. |
| `tools/` | 16 | Operator tooling — runs from Windows workstation, not container. Low risk. |
| `portfolio/` | 12 | Image-baked path. Unknown current import dependence. |
| `intelligence/` | 9 | Image-baked path. Unknown current import dependence. |
| `research/` | 6 | Image-baked path. Unknown current import dependence. |
| `production_readiness/` | 6 | Image-baked path. Unknown current import dependence. |
| `scripts/` | 5 | `scripts/` is bind-mounted from host — missing host-side too, see below. |
| `safety/`, `infrastructure/`, `engine/`, `analytics/` | 5 each | Image-baked. |
| `learning/`, `compliance/` | 4 each | Image-baked. |
| `backtesting/` | 3 | Image-baked. |
| `validation/`, `requirements.in`, `kill.py`, `docker-compose.engine.yml`, `deployment/grafana/.../share_equality.yaml`, `config/settings.py`, `autodriver.sh`, `.pre-commit-config.yaml` | 1 each | Mix. `config/settings.py` is imported by `foundation/health_monitor.py` (which IS on box) — a real runtime risk if health monitoring is wired up. |

**Confirmed root cause.** The HOST build context at
`/home/aaats/aaats/` itself lacks these directories — they were never
SCP'd from the Windows workstation to the box. The image is built from
that partial context (compose `build.context: ..`, `Dockerfile: COPY .
.`), so it faithfully bakes in whatever exists on the host at build
time. The SCP-based paramiko deploy ships files individually, but the
addition of an entirely new directory to `origin/main` is not
accompanied by any per-file SCP, so new directories never propagate to
the host.

### (b) Files in container absent from repo — all tombstones

All 7 phantoms predate the running image at `2026-05-15T09:36 UTC`:

| Path | Removed in | When (UTC) | Classification |
| --- | --- | --- | --- |
| `execution/crypto_runner.py` | `5b750b1` chore(cleanup): delete production-dead crypto_runner/india_runner chain | 2026-05-15 09:56 | **Tombstone** — existed at build time, removed 20 min later |
| `execution/india_runner.py` | `5b750b1` | 2026-05-15 09:56 | Tombstone |
| `execution/orchestrator.py` | `5b750b1` | 2026-05-15 09:56 | Tombstone |
| `scripts/continuous_runner.py` | `5b750b1` | 2026-05-15 09:56 | Tombstone (host disk via bind mount) |
| `scripts/phase1_local_monitor.py` | `5b750b1` | 2026-05-15 09:56 | Tombstone (host disk) |
| `scripts/phase1_runner.py` | `5b750b1` | 2026-05-15 09:56 | Tombstone (host disk) |
| `deploy_to_contabo.py` (at `/app/` root) | `edcb56c` chore(repo): relocate operator scripts to tools/operator/ | 2026-05-15 11:17 | Tombstone — relocated to `tools/operator/deploy_to_contabo.py` |

None of these are runtime imports for `paper_loop.py` (otherwise their
removal in `5b750b1` would have broken the running runner the moment
they were SCP-deleted — which they were not, since the runner is still
up). They are dead code on disk only. Will be removed automatically on
the next image rebuild + host `/home/aaats/aaats/scripts/` cleanup.

### (c) Hash mismatches on common paths — none

0 mismatches across 135 common paths. The per-file SCP swap (upload to
`.tmp`, atomic `mv -f`) is operating correctly. Per the deploy-dirty
guard, no untracked workstation-side edits leaked through.

## Recommendations (audit-only — no remediation in this session)

1. **Host build context resync.** Rsync the full
   `origin/main` snapshot to `/home/aaats/aaats/` (mirroring delete) and
   rebuild the image. This is the only reliable way to close the (a)
   gap. Capture rollback baseline in `.rollback/2026-05-15_audit_rebuild/`
   first.
2. **Add `.dockerignore` at repo root.** Compose's `build.context: ..`
   makes the repo root the build context, but the existing
   `deployment/.dockerignore` is in the wrong place to be applied. Once
   the rebuild is faithful, a root-level ignore is needed to keep
   `docs/`, `.rollback/`, `.claude/`, `.github/`, runtime artifacts out
   of the image.
3. **New-dir deploy hook.** Extend the deploy-dirty-guard (commit
   `ae24d2c`) with a "host vs `origin/main` top-level-dir parity"
   check that runs at deploy time. Refuses to deploy if the host is
   missing any top-level directory present in `origin/main`. Cheap
   structural-drift detector; prevents this exact failure mode from
   recurring after the rebuild.
4. **Re-run this audit post-rebuild.** Gate G3 stays OPEN until a
   re-run produces 0 mismatches in all three categories (with the
   bind-mount caveats explicitly enumerated).

Do not execute any of the above in this session. Capture only.

## Re-run recipe

```bash
# Workstation, from repo root, with origin synced.

# 1. Verify clean tree (only data/paper_trades.db should be auto-cron-dirty).
git fetch origin
git status --porcelain | grep -v -E '^.. (runtime/|data/|diagnostics/reports/|logs/|tools/local/|\.claude/settings\.json)'
git log --oneline origin/main..HEAD  # must be empty

# 2. Audit manifest (production-code surface in origin/main).
git ls-tree -r --name-only origin/main \
  | grep -E '\.(py|yml|yaml|toml|json|ini|cfg|txt|in|sh)$|(^|/)Dockerfile$' \
  | grep -v -E '^(docs/|\.github/|\.rollback/|\.claude/|\.streamlit/|runtime/|data/|logs/|diagnostics/reports/)' \
  | grep -v -E '^(test_results|TEST_RESULTS|.*_COMPLETE|.*_SUMMARY|.*_SPEC|.*_NOTES|.*_PLAN|FLAGGED|README|CLAUDE|ANGEL_ONE_SETUP|AUTONOMOUS|AUTO_|BUILD_READY|GITHUB_ACTIONS|K2_REPLAY|LEGAL_COMPLIANCE|MASTER_|NEXT_STEPS|PHASE_|SESSION_|STRATEGY_|STREAMLIT_DEPLOYMENT|TOKEN_|WEB_APP)' \
  | sort > /tmp/audit_manifest.txt

# 3. Local hashes via blob OIDs (robust against shell quoting of leading-dot paths).
git ls-tree -r origin/main \
  | awk -F'\t' '{split($1,a," "); print a[3]"\t"$2}' > /tmp/tree_oids.txt
join -t$'\t' -1 1 -2 1 \
  <(sort -k1,1 /tmp/audit_manifest.txt | awk '{print $0"\t"$0}') \
  <(awk -F'\t' '{print $2"\t"$1}' /tmp/tree_oids.txt | sort -k1,1) \
  | awk -F'\t' '{print $3"\t"$1}' > /tmp/audit_local_oids.txt
> /tmp/audit_local.txt
while IFS=$'\t' read -r oid path; do
  sha=$(git cat-file blob "$oid" | sha256sum | awk '{print $1}')
  printf "%s  %s\n" "$sha" "$path" >> /tmp/audit_local.txt
done < /tmp/audit_local_oids.txt
sort -k 2 /tmp/audit_local.txt -o /tmp/audit_local.txt

# 4. Box hashes via SSH + docker exec.
ssh aaats@100.95.126.39 'docker exec aaats-paper-crypto find /app -type f \
  \( -name "*.py" -o -name "*.yml" -o -name "*.yaml" -o -name "*.toml" -o -name "*.json" -o -name "*.ini" -o -name "*.cfg" -o -name "*.txt" -o -name "*.in" -o -name "*.sh" -o -name "Dockerfile" \) \
  -not -path "*/__pycache__/*" -not -path "*.pyc" \
  -not -path "/app/runtime/*" -not -path "/app/data/*" -not -path "/app/logs/*" \
  -not -path "/app/diagnostics/reports/*" \
  -not -path "/app/.rollback/*" -not -path "/app/.claude/*" -not -path "/app/.github/*" \
  -not -path "/app/.streamlit/*" -not -path "/app/docs/*" \
  -exec sha256sum {} +' \
  | sed 's|  /app/|  |' \
  | sort -k 2 > /tmp/audit_box.txt

# 5. Classify.
awk '{$1=""; sub(/^  /,""); print}' /tmp/audit_local.txt | sort -u > /tmp/paths_local.txt
awk '{$1=""; sub(/^  /,""); print}' /tmp/audit_box.txt   | sort -u > /tmp/paths_box.txt
comm -23 /tmp/paths_local.txt /tmp/paths_box.txt > /tmp/cat_a_local_only.txt  # in repo, missing on box
comm -13 /tmp/paths_local.txt /tmp/paths_box.txt > /tmp/cat_b_box_only.txt    # phantom on box
comm -12 /tmp/paths_local.txt /tmp/paths_box.txt > /tmp/paths_common.txt
> /tmp/cat_c_hash_diff.txt
while IFS= read -r p; do
  hl=$(awk -v p="$p" '$2==p {print $1}' /tmp/audit_local.txt)
  hb=$(awk -v p="$p" '$2==p {print $1}' /tmp/audit_box.txt)
  [ "$hl" != "$hb" ] && echo "$p" >> /tmp/cat_c_hash_diff.txt
done < /tmp/paths_common.txt

wc -l /tmp/cat_a_local_only.txt /tmp/cat_b_box_only.txt /tmp/cat_c_hash_diff.txt
```

Gate is closed when (a), (b), (c) all read 0 — or each remaining entry
has an explicit explanation captured here.

## Appendix: full divergence lists

### A. 278 files in `origin/main` absent from container

Saved at `tools/audits/2026-05-15_cat_a_local_only.txt` (committed
alongside this doc).

### B. 7 phantom files on container

```
deploy_to_contabo.py
execution/crypto_runner.py
execution/india_runner.py
execution/orchestrator.py
scripts/continuous_runner.py
scripts/phase1_local_monitor.py
scripts/phase1_runner.py
```

## Triage outcome (2026-05-15, same-day follow-up)

The 278-file gap was triaged against the *live runtime critical path* — i.e.,
what the running `aaats-paper-crypto` container actually executes. Container
state at triage time:

- `aaats-paper-crypto` `Up 3 hours (healthy)`, image still `7051c405c75a…`,
  `RestartCount=0`. Drawdown progressed from -3.94% to -4.24% on normal
  market action; no crash signal.
- Entrypoint: `python scripts/init_db.py && python trading/paper_loop.py --market crypto`.
- `paper_loop.py` imports only from `foundation/`, `monitoring/`, `risk/` —
  none of the 16 missing top-level dirs.
- Healthcheck `scripts/health_check.py` is stdlib + psutil only.
- Daily ML retrain cron runs `python -m ml.train_from_history`; `ml/` is on
  box. `init_db.py` is stdlib-only.

Conclusion before classification: **no live trading code path imports any of
the missing dirs**. The 278-file gap is real but no foreground subprocess is
currently failing because of it.

### P1 classification table

Bucket key: **RUNTIME-ACTIVE** = on a live import path (would crash now);
**RUNTIME-LATENT** = runtime-shaped code, no live importer yet;
**WORKSTATION-ONLY** = developer/operator tooling, never expected in
container; **PARALLEL-SYSTEM** = `aaats-engine` v6 deployment, separate
image; **DEAD** = no recent commits *and* no importers anywhere.

| Entry | Files | Latest commit | Live-runtime importer? | Other importers | Bucket |
|---|---|---|---|---|---|
| `analytics/` | 5 | 2026-05-06 | none | `scripts/{daily_reconciliation,optimize_strategies,run_stress_tests}.py` (operator-on-demand) | RUNTIME-LATENT |
| `backtesting/` | 3 | 2026-05-06 | none | tests only | RUNTIME-LATENT |
| `compliance/` | 4 | 2026-05-06 | none | none | DEAD |
| `engine/` | 6 | 2026-05-06 | none | engine internals only | PARALLEL-SYSTEM |
| `infrastructure/` | 5 | 2026-05-06 | none | infrastructure internals only | RUNTIME-LATENT |
| `intelligence/` | 9 | **2026-05-15** | none | intelligence internals only | RUNTIME-LATENT (ghost-captured by `395a6a6`) |
| `learning/` | 4 | 2026-05-06 | none | learning internals + tests | RUNTIME-LATENT |
| `portfolio/` | 12 | 2026-05-06 | none | portfolio internals only | RUNTIME-LATENT |
| `production_readiness/` | 6 | 2026-05-06 | none | self + `safety/` + `streamlit_app/views/page_production_readiness.py` | RUNTIME-LATENT |
| `research/` | 6 | 2026-05-06 | none | none | DEAD |
| `safety/` | 5 | 2026-05-06 | none | self + `scripts/safety_check.py` (operator-on-demand) | RUNTIME-LATENT |
| `strategies/` | 46 | **2026-05-15** | none | strategies internals + tests | RUNTIME-LATENT (ghost-captured by `eeb0963`) |
| `streamlit_app/` | 17 | **2026-05-15** | none | self; dashboard runs on Streamlit Cloud, not container | WORKSTATION-ONLY |
| `tools/` | 25 | **2026-05-15** | none | tests only | WORKSTATION-ONLY |
| `v6-stack/` | 87 | 2026-05-06 | none | self only | PARALLEL-SYSTEM |
| `validation/` | 1 | 2026-05-06 | none | none (`__init__.py` only) | DEAD |
| `.pre-commit-config.yaml` | — | 2026-05-06 | n/a | git pre-commit hook (workstation) | WORKSTATION-ONLY |
| `autodriver.sh` | — | 2026-05-06 | n/a | Claude Code session chainer (workstation) | WORKSTATION-ONLY |
| `docker-compose.engine.yml` | — | 2026-05-06 | n/a | v6 engine compose | PARALLEL-SYSTEM |
| `kill.py` | — | **2026-05-15** | n/a | emergency CLI; README documents `python kill.py --market <m>` from project root. Missing from host build context — operator-emergency tool, not container-baked. | RUNTIME-LATENT (host) |
| `requirements.in` | — | 2026-05-06 | n/a | pip-tools input (workstation build step) | WORKSTATION-ONLY |
| `config/settings.py` | — | 2026-05-06 | none in `--market crypto` runtime | `markets/us/fetcher.py` (US not live) | RUNTIME-LATENT |
| `deployment/grafana/provisioning/alerting/share_equality.yaml` | — | **2026-05-15** | n/a | Grafana alert rule for the share-equality WARN counter. Verified absent from `/srv/aaats/compose/`, `/home/aaats/aaats/deployment/grafana/`, and inside `aaats-grafana`. **Counter fires (runtime assertion in `execution/paper_trader.py` is live) but no Grafana alert is wired to it.** | RUNTIME-LATENT (grafana side) |

`scripts/` and `tests/` are excluded from this triage:
- `scripts/` is bind-mounted from host; the 5 phantom-tombstones (cat (b)) and the 5 missing entries (`deploy_c5b_halt.py`, `deploy_share_assertion.py`, `verify_share_assertion_deployed.py`, `verify_share_equality_counter.py`, `watch_first_sell.py`) are operator deploy/verify scripts, never expected in the runtime fold.
- `tests/` (65 files) is test surface; never expected on box.

**Headline**: zero RUNTIME-ACTIVE entries. Every missing item is in
RUNTIME-LATENT, WORKSTATION-ONLY, PARALLEL-SYSTEM, or DEAD.

### Ghost-code commit findings (P2)

A "ghost-code commit" = today's commit that captured a file into a
now-missing dir. The commit stands as an accurate "what's in git" record;
the question is whether its message overstated what's actually live on the
box. Three matches:

| SHA | Subject | Ghost-captured file(s) | Reality on box |
|---|---|---|---|
| `395a6a6` | `feat(execution,foundation,intelligence): paper-fidelity engine + decision ledger + HMM regime` | `intelligence/regime/regime_pipeline.py` | The execution + foundation halves of the commit ARE deployed (`execution/{fill_model,idempotency,oms,paper_executor}.py`, `foundation/decision_ledger.py` are on box). The **HMM regime** half is *not* — `intelligence/regime/regime_pipeline.py` never reached `/home/aaats/aaats/`, and `paper_loop.py` doesn't import `intelligence` anyway. "HMM regime live" reading of this commit's subject is false. |
| `eeb0963` | `feat(ml): paper-phase confidence bucket tuning + commit _ml_gate.yaml` | `strategies/configs/_ml_gate.yaml` | `ml/xgboost_ensemble.py` deployed; daily ML retrain works. But the YAML gate config is in the missing `strategies/` tree, so any code reading `strategies/configs/_ml_gate.yaml` (if/when wired) silently misses the tuned thresholds. |
| `2c69a54` | `feat(observability): SELL/BUY share-equality assertion + WARN counter + Grafana alert` | `deployment/grafana/provisioning/alerting/share_equality.yaml` | The runtime assertion (in `execution/paper_trader.py`) IS live and the WARN counter increments per the project memory. The **Grafana alert rule** is *not* deployed — the YAML is absent from `/srv/aaats/compose/`, the host build context, and the `aaats-grafana` container. The counter has no alert wired to it. |

No retroactive reverts. The commits remain accurate as repo snapshots. The
deploy-discipline convention should note that "captures source for what's
running on the box" *requires a same-cycle audit of the manifest the
paramiko deploy actually shipped* — otherwise the commit message is a
forward-looking statement of intent, not a verifiable claim.

### Revised verdict

Still **FAIL** — the structural gap is real and the gate stays open. But
the failure is qualified:

- **PASS** on per-file SCP fidelity (cat (c) = 0 across 135 common paths).
- **PASS** on live-runtime safety (no RUNTIME-ACTIVE entries; the running
  container does not silently depend on any missing module).
- **FAIL** on structural completeness (16 dirs + 6 files in repo, absent
  from host build context; image rebuild would not reproduce `origin/main`).
- **FAIL** on commit-message verifiability (three today-commits captured
  half-deployed features as if the whole thing were live).

### Remediation path (no execution this session)

1. **rsync only what needs to live in the image**: RUNTIME-LATENT dirs +
   `kill.py` + `config/settings.py`. Skip WORKSTATION-ONLY and
   PARALLEL-SYSTEM. Rebuild the paper-crypto image. (`v6-stack/` +
   `docker-compose.engine.yml` belong to the `aaats-engine` deploy lane
   and are out of scope here.)
2. **Deploy the Grafana alert YAML** to the actual Grafana compose path
   (`/srv/aaats/compose/grafana/provisioning/alerting/`) so commit
   `2c69a54`'s alert half catches up to the deployed assertion half.
3. **DEAD candidates** (`compliance/`, `research/`, `validation/`) — file
   for a separate cleanup decision; do not propose deletion from this
   audit.
4. **New-dir parity guard** at deploy time, recipe filed at
   [docs/known_issues/2026-05-15_deploy_newdir_parity.md](../known_issues/2026-05-15_deploy_newdir_parity.md).
5. **Re-run the audit** after the rebuild. Audit RUNTIME-LATENT dirs as a
   first-class success criterion; permit WORKSTATION-ONLY and
   PARALLEL-SYSTEM via an explicit allow-list in
   [docs/conventions/deploy_discipline.md](../conventions/deploy_discipline.md).

## Remediation 2026-05-16

Executed in a single bypassPermissions session ending 2026-05-16T05:30Z.

### Image SHAs

| Container | Pre-session | Post-session |
| --- | --- | --- |
| `aaats-metrics` | `sha256:6866e2779981782f8931d0fb3eea7ceeb9c073dfd09a7a1314dd0d17b78358a6` | `sha256:79c80b570b95039b3c8d279ed5f1ae629219dcda2ce995a2479396e9a8f887b8` |
| `aaats-paper-crypto` | `sha256:7051c405c75abb11f0056055a2390d0071ccc858ff3e7bfc075627291d83a160` | `sha256:1a06f1a3de03045eeab54fcd82e9bdbe232ad59a58fd78b28e03c2d15fb73b5c` |

Two paper-crypto rebuilds (P3 then drift-fix), one metrics rebuild.

### RUNTIME-LATENT tarball

- Source: `git archive --format=tar origin/main -- <11 entries>` (origin/main HEAD `3ffa77e` at session start).
- SHA256: `ddc0e8dff9ce20947e12255e907daf022ecef6ed90891ce74b3381c15fa734fe`
- Size: 102 KB compressed; 124 tar entries.
- Path on box: `/tmp/runtime_latent_payload.tar.gz`.
- 11 entries shipped: `analytics/`, `backtesting/`, `infrastructure/`, `intelligence/`, `learning/`, `portfolio/`, `production_readiness/`, `safety/`, `strategies/`, `config/settings.py`, `kill.py`.

### Mid-session findings (not in original audit scope)

The audit's `(c) = 0 hash mismatches` finding had a methodology artifact: it hashed `docker exec aaats-paper-crypto find /app`, i.e., the *image*, not the *host build context*. The remediation re-audit hashed the new image with LF-normalization (`tr -d '\r'` before `sha256sum`) and surfaced three pre-existing drifts the original audit had missed:

1. **`monitoring/metrics_exporter.py`** — origin/main `1400b0e9…`, host stale `99ab80c2…` (May-12). The `collect_share_equality()` function added in commit `f6e835a` had never been SCP'd to the host. Fixed by atomic paramiko swap pre-P1 rebuild.
2. **`execution/paper_trader.py`** — origin/main `0926a0fe…`, host stale `94aa9d88…` (LF-normalized). Box was missing `_bump_share_mismatch_counter()` and its call site — meaning live SELL/BUY mismatches never persisted to `data/share_equality_mismatches.json`. Production trigger of the very feature G3.partial closes was inert. Fixed by atomic paramiko swap pre-drift-fix rebuild.
3. **`deployment/Dockerfile`** — origin/main `e36bb0bc…`, host `58ec331c…`. Box CMD pointed at deleted `main.py`; origin/main fails fast with explicit SystemExit. Cosmetic-safety only (compose always overrides CMD), but real drift. Fixed in the same atomic swap.

Additionally, 6 tombstones (`execution/crypto_runner.py`, `execution/india_runner.py`, `execution/orchestrator.py`, `scripts/{continuous,phase1_local_monitor,phase1}_runner.py`) survived the P3 rebuild because the host build context still contained them. Moved to `/tmp/aaats_tombstones_2026-05-16/` on box (recoverable) before the drift-fix rebuild baked them out of the image.

### Network topology fix (runtime-only)

`aaats-metrics` (network: `aaats-network`, deployment compose) was unreachable from `aaats-prometheus` (network: `aaats`, aaats-base compose). DNS-resolved name `aaats-metrics` failed cross-network. The Prometheus target had been silently `down` since the Grafana stack overlay (2026-05-06), invisible to the original audit because the audit didn't query Prometheus targets.

Applied: `docker network connect aaats aaats-metrics`. Fully reversible; reverts on container recreate. **Persistent fix is a follow-up** — needs `deployment/docker-compose.yml` to attach `aaats-metrics` to the external `aaats` network. Tracked in `.rollback/2026-05-15_metrics_rebuild/MANIFEST.txt` under KNOWN FOLLOW-UPS.

### End-to-end chain validation

Synthetic `_TEST_/_TEST_` trigger via direct write to `data/share_equality_mismatches.json` (production code path: same JSON the `_bump_share_mismatch_counter` writes to). Bumped twice to give `increase()[1h]` a non-zero delta.

| Layer | Evidence |
| --- | --- |
| Exporter | `aaats_share_equality_mismatch_total{strategy="_TEST_",symbol="_TEST_"} 1` at `aaats-metrics:9091/metrics` |
| Prometheus | Target `aaats-metrics` health=`up`; `increase(...)[1h] = 1.09` |
| Grafana | Rule `share_equality_mismatch` fired at `2026-05-16T04:39:00Z` and `04:40:00Z` (log: `Sending alerts to local notifier count=1`) |
| Telegram | Operator confirmed delivery to chat `1946109268`; body: "SELL/BUY share-equality mismatch detected" |

Cleanup: `data/share_equality_mismatches.json` reset to `{}` post-validation. Series stales out on next scrape; alert auto-resolves.

### Re-audit diff

LF-normalized box hashes vs origin/main, production-code surface (206 → 200 files after tombstone cleanup):

- **Hash mismatches**: 0
- **Phantom files on box (only_in_box)**: 0
- **only_in_repo (acceptable absences)**: 6 — all WORKSTATION-ONLY operator scripts allow-listed in original audit (`config/.env.example`, `scripts/deploy_c5b_halt.py`, `scripts/deploy_share_assertion.py`, `scripts/verify_share_assertion_deployed.py`, `scripts/verify_share_equality_counter.py`, `scripts/watch_first_sell.py`).

### Final verdict: **PASS**

G3 closure conditions all met:
- ✅ RUNTIME-LATENT dirs present on box and baked into image
- ✅ Pre-existing RUNTIME hash drift (paper_trader.py, Dockerfile) resolved
- ✅ Tombstones cleaned from host build context
- ✅ Re-audit produces 0 RUNTIME drift
- ✅ Share-equality alert chain validated end-to-end with explicit timestamp.
