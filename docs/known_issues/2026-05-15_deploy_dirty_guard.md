# TODO — Dirty-working-tree guard for deploy scripts (2026-05-15)

## Status
DEFERRED — skipped during the 2026-05-15 drift-reconciliation session per the
"deploy scripts have inconsistent shapes" STOP condition in the prompt.

## Motivation
This morning we discovered that `scripts/deploy_c5b_halt.py` SCP'd the working
tree copy of `trading/live_paper_runner.py`, which included ~80 lines of
uncommitted pre-existing changes (the P0.1/P0.2 risk-engine reseat). The
container ended up running code that wasn't in `origin/main`. We caught it
the same day and reconciled in commits `33114cc`, `243ca75`, `bdb8f85`
(final SHA `bdb8f8573bbccefcb45f2c780581aae87ddad1f6`), but the next
divergence could be a *bug* rather than a benign refactor.

A pre-SCP dirty-check would have refused the deploy until either
the changes were committed or `--allow-dirty` was passed explicitly.

## Why skipped this session
The 4 existing deploy entrypoints have materially different shapes — a single
uniform guard is awkward and the change exceeds the prompt's 30-line budget:

| Script | Shape | Dirty-check fit |
| --- | --- | --- |
| `tools/operator/deploy_to_contabo.py` | Tarball of dir trees (`INCLUDE=["trading", "foundation", ...]`) → SCP → remote extract → docker build | Needs `git status --porcelain` walked against every file under each INCLUDE path |
| `scripts/deploy_c5b_halt.py` | Single-file SFTP+atomic-mv → no-deps rebuild | Trivial — check the one `LOCAL_FILE` |
| `scripts/deploy_share_assertion.py` | Single-file SFTP+atomic-mv → no-deps rebuild | Trivial — same as above |
| `deploy_grafana_dashboard.py` | Builds dashboard JSON in-code → HTTP POST to Grafana API | **N/A** — no file shipped from disk; dashboard state lives in Python, not the working tree |

A shared helper module + per-script invocation totals ~50 lines (35 helper +
5 × 3 scripts) and has to handle two distinct manifest shapes (single file vs.
directory tree).

## Recommended implementation when picked up

### Single helper module: `scripts/_deploy_dirty_guard.py` (~35 lines)

```python
"""
Pre-deploy guard: refuse to SCP files that have uncommitted git changes.

Use:
    from scripts._deploy_dirty_guard import check_clean_or_exit
    check_clean_or_exit(["trading/live_paper_runner.py"], allow_dirty=False)
    check_clean_or_exit(["trading", "foundation", "scripts"], allow_dirty=False)

Paths can be files or directories — the latter checks every file under that
prefix. Pass `--allow-dirty` on the deploy script's CLI to override (the
helper detects this in sys.argv automatically).
"""
import subprocess, sys, pathlib

def _dirty_files() -> set[str]:
    out = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=pathlib.Path(__file__).parent.parent,
        text=True, encoding="utf-8",
    )
    # First two chars: index/working-tree status. Anything containing M/D in
    # the working-tree column counts as dirty for our purpose.
    dirty = set()
    for line in out.splitlines():
        if len(line) < 4:
            continue
        idx, wt, _, path = line[0], line[1], line[2], line[3:].strip()
        if wt in ("M", "D", "?") or idx in ("M", "D", "A", "R"):
            # strip optional rename arrow
            path = path.split(" -> ")[-1].strip().strip('"')
            dirty.add(path)
    return dirty

def check_clean_or_exit(manifest: list[str], allow_dirty: bool | None = None) -> None:
    if allow_dirty is None:
        allow_dirty = "--allow-dirty" in sys.argv
    dirty = _dirty_files()
    matched = set()
    for entry in manifest:
        entry = entry.replace("\\", "/").rstrip("/")
        for f in dirty:
            if f == entry or f.startswith(entry + "/"):
                matched.add(f)
    if not matched:
        return
    if allow_dirty:
        print("=" * 65)
        print("  --allow-dirty: SHIPPING UNCOMMITTED CHANGES")
        for f in sorted(matched):
            print(f"    {f}")
        print("  You really don't want to do this except in emergencies.")
        print("=" * 65)
        return
    print("=" * 65, file=sys.stderr)
    print("  DEPLOY REFUSED — uncommitted changes in deploy manifest:", file=sys.stderr)
    for f in sorted(matched):
        print(f"    {f}", file=sys.stderr)
    print("  Commit first, or pass --allow-dirty to override.", file=sys.stderr)
    print("=" * 65, file=sys.stderr)
    sys.exit(2)
```

### Per-script invocation (~5 lines each)

- `tools/operator/deploy_to_contabo.py` — add at top of `main()`:
  ```python
  from scripts._deploy_dirty_guard import check_clean_or_exit
  check_clean_or_exit(INCLUDE)
  ```

- `scripts/deploy_c5b_halt.py` — add at top of `main()`:
  ```python
  from scripts._deploy_dirty_guard import check_clean_or_exit
  check_clean_or_exit([LOCAL_FILE.relative_to(PROJECT_ROOT).as_posix()])
  ```

- `scripts/deploy_share_assertion.py` — same shape as deploy_c5b_halt.py.

- `deploy_grafana_dashboard.py` — **skip**, no on-disk manifest.

## Tests
- Unit test the helper:
  - empty manifest → no exit, no output
  - clean manifest → no exit, no output
  - dirty file matching manifest entry exactly → exit code 2
  - dirty file in a directory in the manifest → exit code 2
  - dirty file outside the manifest → no exit (this is the key contract:
    `runtime/` and `data/` auto-cron writes must NEVER trigger the guard)
  - `--allow-dirty` in sys.argv → no exit, prints warning

## Acceptance criteria
1. Helper module + 3 per-script integrations land in a single commit.
2. Repeatable test (or recorded manual scenario) showing the guard
   refuses a `deploy_c5b_halt.py` invocation when
   `trading/live_paper_runner.py` is dirty.
3. `--allow-dirty` documented in each script's docstring.

## Cross-references
- Today's drift incident: commits `33114cc`, `243ca75`, `bdb8f85`
  (final SHA `bdb8f8573bbccefcb45f2c780581aae87ddad1f6`).
- Underlying state-divergence pattern: project memory
  `project_aaats_drift_diagnosis.md` (canonical copy at
  `docs/decisions/2026-05-15_drift_diagnosis.md`).
- Related: unified positions ledger spec (Q1-Q4 pending) addresses the
  *data*-side divergence; this TODO addresses the *code*-side divergence.
