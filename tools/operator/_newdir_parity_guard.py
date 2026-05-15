"""
Pre-deploy guard: refuse to SCP-deploy when origin/main has top-level
directories not covered by the deploy manifest.

Companion to tools/operator/_dirty_tree_guard.py — same shape, different
failure mode. The dirty guard catches "manifest file is dirty"; this guard
catches "origin/main has a top-level dir the manifest doesn't mention,"
which is how the 2026-05-15 audit found 278 files silently missing from
the box build context.

Public API:
    check_newdir_parity(
        manifest_paths: list[str],
        allow_dirty: bool = False,
        warn_only: bool = False,
    ) -> None

Raises NewDirError (RuntimeError subclass) when origin/main has top-level
entries that are neither covered by the manifest nor in
DEPLOY_ALLOWLIST_NONRUNTIME. The allow-list is mirrored in
docs/conventions/deploy_discipline.md.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
from typing import Iterable


class NewDirError(RuntimeError):
    """Raised when origin/main has top-level dirs absent from the manifest."""


# Top-level entries that intentionally never ship to the paper-crypto
# runtime container. Mirror authoritative copy:
# docs/conventions/deploy_discipline.md — "Non-runtime top-level entries".
DEPLOY_ALLOWLIST_NONRUNTIME = frozenset({
    # WORKSTATION-ONLY (operator tooling, UI, build-tooling)
    "streamlit_app", "tools",
    ".pre-commit-config.yaml", "autodriver.sh", "requirements.in",
    # PARALLEL-SYSTEM (aaats-engine deploy lane — not paper-crypto)
    "v6-stack", "engine", "docker-compose.engine.yml",
    # DEAD (cleanup pending — never on box, will be removed from repo)
    "compliance", "research", "validation",
    # Repo metadata / never-shipped
    "docs", ".github", ".rollback", ".claude", ".streamlit",
    "tests", "diagnostics",
    ".gitignore", ".gitattributes",
    "README.md", "CLAUDE.md", "LICENSE",
    # Runtime artifacts written by container, not by deploy
    "data", "logs", "runtime",
})


def _repo_root() -> pathlib.Path:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise NewDirError("not a git repo") from exc
    if not out:
        raise NewDirError("not a git repo")
    return pathlib.Path(out)


def _origin_main_toplevel(root: pathlib.Path) -> set[str]:
    """Top-level entries (dirs and root files) in origin/main."""
    out = subprocess.check_output(
        ["git", "ls-tree", "--name-only", "origin/main"],
        cwd=str(root),
        text=True,
        encoding="utf-8",
    )
    return {line.strip() for line in out.splitlines() if line.strip()}


def _normalize(entry: str) -> str:
    """Manifest entry -> top-level token. Handles tools/operator/, ./x, x/y."""
    e = entry.replace("\\", "/").lstrip("./").rstrip("/")
    return e.split("/", 1)[0] if "/" in e else e


def _shout_allow_dirty(uncovered: Iterable[str]) -> None:
    script = pathlib.Path(sys.argv[0]).name or "<deploy>"
    use_color = bool(getattr(sys.stderr, "isatty", lambda: False)())
    red = "\033[1;31m" if use_color else ""
    rst = "\033[0m" if use_color else ""
    bar = "=" * 65
    lines = [
        bar,
        f"{red}  --allow-dirty: SHIPPING WITH UNCOVERED TOP-LEVEL DIRS via {script}{rst}",
    ]
    for entry in uncovered:
        lines.append(f"    {entry}")
    lines.append("  These exist in origin/main but the deploy manifest does NOT")
    lines.append("  cover them. Box will not receive them. Commit a manifest")
    lines.append("  update immediately after deploy completes.")
    lines.append(bar)
    print("\n".join(lines), file=sys.stderr)


def _shout_warn_only(uncovered: Iterable[str]) -> None:
    script = pathlib.Path(sys.argv[0]).name or "<deploy>"
    bar = "-" * 65
    lines = [
        bar,
        f"  new-dir parity WARN ({script}): origin/main has top-level entries",
        "  not covered by this manifest and not in the non-runtime allow-list:",
    ]
    for entry in uncovered:
        lines.append(f"    {entry}")
    lines.append("  This single-file deploy proceeds, but the full-tree deploy")
    lines.append("  (tools/operator/deploy_to_contabo.py) would refuse them.")
    lines.append("  Patch INCLUDE / DEPLOY_ALLOWLIST_NONRUNTIME before that runs.")
    lines.append(bar)
    print("\n".join(lines), file=sys.stderr)


def check_newdir_parity(
    manifest_paths: list[str],
    allow_dirty: bool = False,
    warn_only: bool = False,
) -> None:
    """Refuse the deploy if origin/main has top-level entries the manifest misses.

    Args:
        manifest_paths: top-level dirs/files the deploy script will SCP. May
            include trailing slashes and nested paths; only the first path
            component matters for parity.
        allow_dirty: if True, print a loud stderr warning and return without
            raising. Shares semantics with the dirty-tree guard's flag.
        warn_only: if True (single-file deploys), print a soft warning and
            return without raising even on uncovered entries. Used by the
            scripts/deploy_*.py one-shot deploys where the manifest is
            intentionally narrow.

    Raises:
        NewDirError: when uncovered entries exist, allow_dirty is False,
            and warn_only is False. Also when git is unavailable.
    """
    root = _repo_root()
    origin = _origin_main_toplevel(root)
    covered = {_normalize(p) for p in manifest_paths if p}
    uncovered = sorted(origin - covered - DEPLOY_ALLOWLIST_NONRUNTIME)
    if not uncovered:
        return
    if warn_only:
        _shout_warn_only(uncovered)
        return
    if allow_dirty:
        _shout_allow_dirty(uncovered)
        return
    bar = "=" * 65
    msg_lines = [
        bar,
        "  DEPLOY REFUSED — origin/main has top-level entries NOT in the",
        "  deploy manifest and NOT in the non-runtime allow-list:",
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
