# New-dir parity guard for paramiko deploy scripts (2026-05-15)

## Status
**IMPLEMENTED** 2026-05-15. Module
[`tools/operator/_newdir_parity_guard.py`](../../tools/operator/_newdir_parity_guard.py)
exposes `check_newdir_parity(manifest_paths, allow_dirty, warn_only)`; wired
into all three paramiko deploy entrypoints alongside the dirty-tree guard:
- `tools/operator/deploy_to_contabo.py` (full tree deploy — hard refuse)
- `scripts/deploy_c5b_halt.py` (single-file — `warn_only=True`)
- `scripts/deploy_share_assertion.py` (single-file — `warn_only=True`)

Allow-list mirrored in
[`docs/conventions/deploy_discipline.md`](../conventions/deploy_discipline.md) §"Non-runtime top-level entries".
Pytest coverage: `tests/test_operator/test_newdir_parity_guard.py` (9 cases).

Implementation commit: captured in the same session as the box-vs-repo
audit triage; see `git log -- tools/operator/_newdir_parity_guard.py`.

## Motivation

The 2026-05-15 forensic audit found 16 top-level directories tracked in
`origin/main` but absent from the box host's build context at
`/home/aaats/aaats/`. Symptoms surfaced as 278 missing files in the image
audit. Root cause: the paramiko SCP deploy ships **individual files per a
hardcoded manifest** (e.g., `INCLUDE = ["trading", "foundation", ...]` in
`tools/operator/deploy_to_contabo.py`). When a brand-new top-level
directory is added to `origin/main` and no human remembers to amend the
manifest, the deploy silently skips it. The host never receives the dir,
the image is rebuilt from the partial tree, and the running container is
missing modules that the rest of the team thinks are deployed.

The dirty-tree guard catches **uncommitted manifest files**. It does NOT
catch the case where `origin/main` has top-level entries the manifest
doesn't cover. These are different failure modes:

| Failure | What ships | What's missing | Caught by |
|---|---|---|---|
| Dirty manifest file | Uncommitted working-tree version of a manifest entry | The committed `origin/main` version | dirty-tree guard ✓ |
| New top-level dir | Nothing for that dir | The whole dir | new-dir parity guard (this recipe) |

## Recipe sketch

### Helper function: `tools/operator/_newdir_parity_guard.py`

```python
"""
Pre-deploy guard: refuse to SCP-deploy when origin/main has top-level
directories not covered by the deploy manifest.

Companion to tools/operator/_dirty_tree_guard.py — same shape, different
failure mode. The dirty guard catches "manifest file is dirty"; this guard
catches "origin/main has a top-level dir the manifest doesn't mention."
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class NewDirError(RuntimeError):
    """Raised when origin/main has top-level dirs absent from the manifest."""


# Top-level entries that intentionally never ship to the runtime container.
# Update when a new workstation-only or parallel-system dir lands in repo.
# Cross-ref: docs/conventions/deploy_discipline.md for the authoritative list.
DEPLOY_ALLOWLIST_NONRUNTIME = frozenset({
    # WORKSTATION-ONLY (operator tooling, UI, build-tooling)
    "streamlit_app",  "tools",  ".pre-commit-config.yaml",
    "autodriver.sh",  "requirements.in",
    # PARALLEL-SYSTEM (aaats-engine deploy lane — not paper-crypto)
    "v6-stack",       "engine",  "docker-compose.engine.yml",
    # Repo metadata / never-shipped
    "docs",  ".github",  ".rollback",  ".claude",  ".streamlit",
    "tests",  "diagnostics",  ".gitignore",  ".gitattributes",
    "README.md",  "CLAUDE.md",  "LICENSE",
    # Runtime artifacts written by container, not by deploy
    "data",  "logs",  "runtime",
})


def _origin_main_toplevel() -> set[str]:
    """Top-level entries (dirs and root files) in origin/main."""
    out = subprocess.check_output(
        ["git", "ls-tree", "--name-only", "origin/main"],
        cwd=_repo_root(), text=True, encoding="utf-8",
    )
    return {line.strip() for line in out.splitlines() if line.strip()}


def _repo_root() -> Path:
    out = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True, encoding="utf-8",
    )
    return Path(out.strip())


def check_newdir_parity(manifest_paths: list[str], allow_dirty: bool = False) -> None:
    """
    Verify origin/main has no top-level entries outside the manifest +
    allow-list. Raise NewDirError if so.

    manifest_paths: list of top-level dirs/files the deploy script will SCP.
        Entries may have trailing slashes (preserved by manifest authors)
        but are normalized before comparison.
    allow_dirty: if True, print a loud warning and return without raising.
        Same semantics as the dirty-tree guard's --allow-dirty.
    """
    covered = {p.rstrip("/").replace("\\", "/").split("/")[0] for p in manifest_paths}
    origin = _origin_main_toplevel()
    uncovered = sorted(origin - covered - DEPLOY_ALLOWLIST_NONRUNTIME)
    if not uncovered:
        return
    if allow_dirty:
        bar = "=" * 65
        print(bar)
        print("  --allow-dirty: SHIPPING WITH UNCOVERED TOP-LEVEL DIRS")
        for entry in uncovered:
            print(f"    {entry}")
        print("  These exist in origin/main but the deploy manifest does NOT")
        print("  cover them. Box will not receive them. Commit a manifest")
        print("  update immediately after deploy completes.")
        print(bar)
        return
    bar = "=" * 65
    msg_lines = [
        bar,
        "  DEPLOY REFUSED — origin/main has top-level entries NOT in the",
        "  deploy manifest and NOT in the workstation/parallel allow-list:",
    ]
    for entry in uncovered:
        msg_lines.append(f"    {entry}")
    msg_lines.append("")
    msg_lines.append("  Either:")
    msg_lines.append("    (a) add to the deploy manifest in this script, or")
    msg_lines.append("    (b) add to DEPLOY_ALLOWLIST_NONRUNTIME in")
    msg_lines.append("        tools/operator/_newdir_parity_guard.py +")
    msg_lines.append("        docs/conventions/deploy_discipline.md, or")
    msg_lines.append("    (c) pass --allow-dirty if you really mean it.")
    msg_lines.append(bar)
    raise NewDirError("\n".join(msg_lines))
```

### Per-script invocation

Same three entrypoints as the dirty-tree guard:

```python
# tools/operator/deploy_to_contabo.py
from tools.operator._newdir_parity_guard import check_newdir_parity
check_newdir_parity(INCLUDE, allow_dirty=args.allow_dirty)

# scripts/deploy_c5b_halt.py
# scripts/deploy_share_assertion.py
# Single-file deploys: manifest is just [LOCAL_FILE.relative_to(ROOT)]; the
# parity check is still useful (catches "origin/main has new dirs but you
# only meant to deploy this one file" — that's a deploy-discipline warning,
# not a hard fail). Behavior: log uncovered dirs as a soft warning, do NOT
# raise. Implement via a `warn_only=True` kwarg.
```

### Allow-list maintenance

`DEPLOY_ALLOWLIST_NONRUNTIME` is the single source of truth for "top-level
entries that intentionally never ship to the paper-crypto runtime
container". Mirror entries into
[docs/conventions/deploy_discipline.md](../conventions/deploy_discipline.md)
under a new "non-runtime top-level entries" section so the convention doc
and the code stay in sync.

Initial seed list — per the 2026-05-15 audit triage classification:
- **WORKSTATION-ONLY**: `streamlit_app/`, `tools/`, `.pre-commit-config.yaml`, `autodriver.sh`, `requirements.in`
- **PARALLEL-SYSTEM** (`aaats-engine` lane, not paper-crypto): `v6-stack/`, `engine/`, `docker-compose.engine.yml`
- **Repo metadata / runtime artifacts** (never shipped): `docs/`, `.github/`, `.rollback/`, `.claude/`, `.streamlit/`, `tests/`, `diagnostics/`, `.gitignore`, `.gitattributes`, `README.md`, `CLAUDE.md`, `LICENSE`, `data/`, `logs/`, `runtime/`

DEAD candidates (`compliance/`, `research/`, `validation/`) and
RUNTIME-LATENT candidates (`analytics/`, `backtesting/`, `infrastructure/`,
`intelligence/`, `learning/`, `portfolio/`, `production_readiness/`,
`safety/`, `strategies/`, `kill.py`, `config/settings.py`) are
deliberately NOT in the allow-list — they ARE expected to be on box once
the audit-driven rsync + rebuild closes G3.

## Tests

Mirror `tests/test_operator/test_dirty_tree_guard.py`:

- empty manifest → uncovered = (origin - allow-list); raises if non-empty
- manifest covers everything in origin minus allow-list → no raise
- new top-level dir in origin/main not in manifest, not in allow-list → raises NewDirError
- new top-level dir in allow-list → no raise
- `allow_dirty=True` with uncovered dirs → no raise, prints warning
- `warn_only=True` with uncovered dirs → no raise, prints warning, returns

## Acceptance criteria

1. Helper module + 3 per-script integrations land in a single commit.
2. `DEPLOY_ALLOWLIST_NONRUNTIME` mirrored to
   [docs/conventions/deploy_discipline.md](../conventions/deploy_discipline.md).
3. Repeatable test showing the guard refuses a deploy when a fresh
   top-level directory has been added to `origin/main` and the manifest
   not amended.
4. `--allow-dirty` (shared with the dirty-tree guard) is honored as a
   single CLI flag covering both guards.

## Cross-references

- Companion: [docs/decisions/2026-05-15_deploy_dirty_guard.md](../decisions/2026-05-15_deploy_dirty_guard.md) — already implemented (commit `ae24d2c`).
- Failure-mode evidence: [docs/decisions/2026-05-15_box_repo_audit.md](../decisions/2026-05-15_box_repo_audit.md) — 278-file gap with classification table.
- Gate dependency: [docs/decisions/pre_live_gates.md](../decisions/pre_live_gates.md) G3 exit criterion 3.
- Deploy convention: [docs/conventions/deploy_discipline.md](../conventions/deploy_discipline.md) — to be amended with the allow-list section when this recipe lands.
