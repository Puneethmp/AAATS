# Deploy Discipline — Standing Rules

Two standing rules govern how code reaches the Contabo box and `origin/main`.

## Rule 1 — Never SCP-deploy from a dirty working tree

The AAATS deploy mechanism uses paramiko SCP from the local Windows workstation
to the Contabo box. The box is NOT a git repo, so SCP ships whatever is in the
local working tree — committed or not. Uncommitted local edits run on production
paper trading without ever appearing in `origin/main`.

**Why this is dangerous.** "What's running on day N?" becomes unanswerable from
git history alone. Two sessions later, the drift gets harder to identify (was it
intentional? a debug print someone forgot? a real fix?). The drift can mask the
next bug because the current state of the code in git is not what is actually
executing.

**Concrete instance (2026-05-15).** The P0.1 `LOCKED_STARTING_EQUITY` seed and
P0.2 `_compute_current_equity` / `_strategy_state_book_value` helper were
SCP-deployed to the box during the morning P0/P1 deploy session, but
`trading/live_paper_runner.py` was never committed. The drift sat for ~10 hours
until the C5b halt session surfaced it. A subsequent audit found 11 separate
feature scopes carrying similar drift.

**How to apply.**

- Enforcement is live as of `ae24d2c`; the guard
  (`tools/operator/_dirty_tree_guard.py`, function `check_clean`) refuses
  dirty-manifest deploys unless `--allow-dirty` is passed. The three paramiko
  deploy scripts — `tools/operator/deploy_to_contabo.py`,
  `scripts/deploy_c5b_halt.py`, `scripts/deploy_share_assertion.py` — invoke
  the guard before any SCP/SSH side-effect. Grafana dashboard deploy is N/A
  (POSTs to API, no on-disk manifest).
- Don't apply blanket dirty-check to the whole repo — auto-cron writes to
  `runtime/` and `data/` continuously. The guard takes an explicit manifest
  argument so only files in the actual deploy payload trigger refusal.
- If a deploy MUST proceed with a dirty tree (genuine emergency, code is correct
  but unmerged), pass `--allow-dirty` — the guard prints a loud stderr warning
  but lets you through. Commit IMMEDIATELY after deploy as its own atomic commit
  referencing the deploy SHA. Don't sit on it for a future session to find.

## Rule 1b — Never SCP-deploy with origin/main top-level dirs uncovered by the manifest

The paramiko deploy in `tools/operator/deploy_to_contabo.py` ships per a
hardcoded `INCLUDE` list. When a brand-new top-level directory is added to
`origin/main` and nobody amends `INCLUDE`, the deploy silently skips it — the
box never receives the dir and the image is rebuilt from a partial tree. The
2026-05-15 box-vs-repo audit found 16 such directories and 278 missing files
this way (see `docs/decisions/2026-05-15_box_repo_audit.md`).

**How to apply.**

- Enforcement is live; `tools/operator/_newdir_parity_guard.py` (`check_newdir_parity`)
  is invoked alongside the dirty-tree guard in all three paramiko deploy entrypoints:
  `tools/operator/deploy_to_contabo.py`, `scripts/deploy_c5b_halt.py`,
  `scripts/deploy_share_assertion.py`. The single-file deploys use `warn_only=True`
  (soft warning); the full-tree deploy refuses by default.
- The guard compares `git ls-tree --name-only origin/main` against the manifest
  + an allow-list of entries that intentionally never ship to the paper-crypto
  runtime. The allow-list is the single source of truth for "non-runtime
  top-level entries"; it must stay in sync between `_newdir_parity_guard.py`
  and the **Non-runtime top-level entries** section below.
- When the guard refuses a deploy, triage each uncovered entry: (a) add it to
  `INCLUDE` if it's runtime code that genuinely belongs on the box, (b) add it
  to `DEPLOY_ALLOWLIST_NONRUNTIME` + this doc if it's workstation-only or a
  parallel-system asset, or (c) delete it from `origin/main` if it's clutter.
  Reach for `--allow-dirty` only as a last resort and commit the manifest
  update immediately after — same discipline as the dirty-tree guard.

### Non-runtime top-level entries (authoritative allow-list)

These entries are in `origin/main` but intentionally NOT on the paper-crypto
box. The mirror in `tools/operator/_newdir_parity_guard.py:DEPLOY_ALLOWLIST_NONRUNTIME`
must be updated when this list changes (or vice versa).

| Category | Entries |
|---|---|
| **WORKSTATION-ONLY** (operator tooling, UI) | `tools/`, `streamlit_app/`, `.pre-commit-config.yaml`, `autodriver.sh`, `requirements.in` |
| **PARALLEL-SYSTEM** (`aaats-engine` lane — not paper-crypto) | `engine/`, `v6-stack/`, `docker-compose.engine.yml` |
| **DEAD** (cleanup pending — will be deleted from repo) | `compliance/`, `research/`, `validation/` |
| **Repo metadata / never-shipped** | `docs/`, `.github/`, `.rollback/`, `.claude/`, `.streamlit/`, `tests/`, `diagnostics/`, `.gitignore`, `.gitattributes`, `README.md`, `CLAUDE.md`, `LICENSE` |
| **Runtime artifacts** (written by container, not deploy) | `data/`, `logs/`, `runtime/` |

Everything ELSE in `origin/main` MUST appear in the deploy manifest — the
guard treats absence as a refusal. See
`docs/known_issues/2026-05-15_deploy_newdir_parity.md` for the implementation
record.

## Rule 2 — Push to `origin/main` at end of every session

Every Claude Code session that modifies code or docs must end with a push to
`origin/main`. The local repo is canonical history; the box gets runtime via
paramiko SCP separately — but GitHub must reflect what has been approved.

**Why.** The box is not a git repo. If the local workstation dies or the box
image is lost, GitHub is the only canonical source of truth. An approved change
that sits unpushed on the workstation is one disk failure away from being lost.
GitHub-side history makes "what was running on day N?" answerable in a way the
box's filesystem alone cannot.

**How to apply.**

- One atomic commit per scope, never a mega-commit. Conventional style:
  `fix(scope): ...`, `feat(scope): ...`, `docs(scope): ...`, `chore(scope): ...`.
- Rebase over the auto-commit cron's data commits (the cron writes ~30/day to
  `origin/main`). Use `git fetch origin && git rebase origin/main && git push origin main`.
  If the rebase conflicts on a NON-data file, STOP — real conflict, not
  auto-resolve territory.
- Verify push landed: `git log --oneline origin/main..HEAD` must be empty after push.
- Capture the final pushed SHA in the session report.
- If a session aborts mid-scope, push the completed work and note skipped scope
  explicitly. Don't sit on partial commits hoping to bundle them later.

## Commit message convention

```
<type>(<scope>): <one-line summary>

<paragraph: what this change does and why it's needed>

<paragraph: validation evidence — tests passed, box state confirmed, related
deploys, etc. For drift captures, explicitly state "running on the box since X;
this commit captures the source.">

<paragraph: any gate closure or follow-up linkage, e.g. "Closes pre-live gate G2
(docs/decisions/pre_live_gates.md)" or "Follow-up: docs/known_issues/...">
```

## See also

- `docs/decisions/2026-05-15_deploy_dirty_guard.md` — implementation history
  for the dirty-tree guard (status: IMPLEMENTED).
- `docs/decisions/pre_live_gates.md` — gates that must close before live capital.
- `docs/conventions/operator_local_files.md` — three-bucket file layout that
  rules 1 and 2 depend on.
