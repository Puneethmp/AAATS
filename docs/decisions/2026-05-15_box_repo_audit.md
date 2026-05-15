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
