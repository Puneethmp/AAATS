# Operator-local file layout

Three buckets, three homes. Decision rule: **would a teammate cloning this
repo need this file to do their job?** If yes, it's committed. If no, it's
gitignored. Put it under the right path on first creation; do not let
operator detritus accumulate at the repo root.

## The three buckets

### 1. Per-machine launchers (`.bat`, `.ps1`, `.vbs`)

- **`tools/launchers/` (committed)** — launchers that locate themselves via
  `%~dp0` (or PowerShell equivalent) and use only relative paths to reach
  the repo root. Cross-machine because they assume nothing about absolute
  paths.
- **`tools/local/` (gitignored)** — launchers that hard-code an absolute
  path like `C:\Users\udaym\OneDrive\Desktop\Puneeth\...`. Per-machine,
  not portable, do not commit.

Test before committing: clone the repo to a fresh path and run the launcher
without editing anything. If it still works, it belongs in
`tools/launchers/`. If you have to fix a path, it belongs in `tools/local/`.

### 2. Operator scripts (Python wrappers over `paramiko` / `docker` / SSH)

- **`tools/operator/` (committed)** — shared operator infrastructure:
  paramiko-based SCP deploys, diagnostic harnesses, fix-pack verifiers.
  These are how the team interacts with the live box; they belong in the
  repo.
- **`tools/local/` (gitignored)** — single-operator scratch scripts (quick
  one-off probes, throwaway debug runners). Do not commit; if it becomes
  useful to others, promote it to `tools/operator/` with a docstring.

Production code at `trading/`, `execution/`, `risk/`, `monitoring/`,
`strategies/`, `markets/`, `scripts/` (DB init, reconciler, etc.) **must
not** import from `tools/`. The dependency goes one way: `tools/` reads
the codebase, the codebase does not reach into `tools/`.

### 3. Transient outputs

- **`data/diagnostics/` (gitignored)** — captured CSV/PNG/JSON output of
  diagnostic scripts. The `data/*` gitignore rule already covers this.
- **`diagnostics/reports/` (gitignored)** — historical landing zone for
  the d1-d6 backtest replays' artifacts. Gitignored as of 2026-05-15;
  outputs written here will not be tracked.
- **Repo-root `.txt` dumps** — never. If you need to capture stdout for a
  diagnostic run, redirect to `data/diagnostics/<date>_<purpose>.txt` or
  `diagnostics/reports/`. Anything at the repo root is presumed to be
  source.

## Why this matters

This convention exists because operator detritus piled up at the repo root
three times within a single day (2026-05-15), and each round of cleanup is
a tax. Sources of churn:

- One-off `paramiko`-SSH wrappers written to probe a live issue, then never
  promoted or deleted.
- `.bat`/`.ps1` launchers that hard-code OneDrive paths.
- Diagnostic stdout dumps left around as `*.txt` after the issue was fixed.
- Claude Code prompt drafts saved next to source files.

Putting these under `tools/` on first creation — rather than at the repo
root — means a clean `git status` after every session and a recognizable
boundary between code and operator tooling.

## Linkage to deploy-dirty guard

The SCP-deploy pipeline (`tools/operator/deploy_to_contabo.py`) does not
yet refuse to deploy when the working tree is dirty. The known-issues
filing [docs/known_issues/2026-05-15_deploy_dirty_guard.md](../known_issues/2026-05-15_deploy_dirty_guard.md)
captures the rationale and proposed fix. Once that guard lands, operator
scripts that wrap the deploy MUST honor it; a dirty working tree of
operator detritus should not pass the guard either.

## Promotion / demotion

A file's home is not permanent. Promote from `tools/local/` to
`tools/operator/` (or from a launcher in `tools/local/` to
`tools/launchers/`) when:

- A second person needs to run it.
- It survives more than one session.
- It has a docstring or `--help`.

Demote from `tools/operator/` to `tools/local/` (or delete) when:

- It hard-codes a value that only works on one machine.
- It hasn't been touched in months and the issue it probed is closed.
- The functionality moved into a production module.
