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

- Every deploy script (`tools/operator/deploy_to_contabo.py` and the smaller
  `tools/operator/deploy_*.py`) must run `git status --porcelain` against the
  deploy manifest before SCP. If any manifest file is dirty: refuse the deploy
  with a clear message, with an `--allow-dirty` emergency escape hatch that
  prints a loud warning. See `docs/known_issues/2026-05-15_deploy_dirty_guard.md`
  for the implementation recipe.
- Don't apply blanket dirty-check to the whole repo — auto-cron writes to
  `runtime/` and `data/` continuously. Check only files in the actual deploy
  manifest.
- If a deploy MUST proceed with a dirty tree (genuine emergency, code is correct
  but unmerged), commit IMMEDIATELY after deploy as its own atomic commit
  referencing the deploy SHA. Don't sit on it for a future session to find.

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

- `docs/known_issues/2026-05-15_deploy_dirty_guard.md` — implementation recipe
  for the dirty-tree guard.
- `docs/decisions/pre_live_gates.md` — gates that must close before live capital.
- `docs/conventions/operator_local_files.md` — three-bucket file layout that
  rules 1 and 2 depend on.
