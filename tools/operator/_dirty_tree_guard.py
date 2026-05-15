"""
Pre-deploy guard: refuse to ship files that have uncommitted git changes.

Public API:
    check_clean(manifest_paths: list[str], allow_dirty: bool = False) -> None

Raises DirtyTreeError (a RuntimeError subclass) when any manifest entry is
dirty per `git status --porcelain`. When ``allow_dirty=True``, emits a loud
stderr warning instead of raising.

Manifest entry shapes:
    - File path (no trailing slash): exact match against the dirty file list.
    - Directory path (trailing slash): prefix match against every dirty file.

Only files matching the manifest are flagged. Auto-cron writes under
``runtime/``, ``data/``, ``diagnostics/reports/``, etc. are intentionally
ignored — the manifest is the whitelist of "code that this deploy ships".
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
from typing import Iterable


class DirtyTreeError(RuntimeError):
    """Raised when a deploy manifest contains uncommitted git changes."""


def _repo_root() -> pathlib.Path:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise DirtyTreeError("not a git repo") from exc
    if not out:
        raise DirtyTreeError("not a git repo")
    return pathlib.Path(out)


def _dirty_files(root: pathlib.Path) -> set[str]:
    out = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=str(root),
        text=True,
        encoding="utf-8",
    )
    dirty: set[str] = set()
    for line in out.splitlines():
        if len(line) < 4:
            continue
        idx, wt, _sep, path = line[0], line[1], line[2], line[3:].strip()
        if wt in ("M", "D", "?") or idx in ("M", "D", "A", "R"):
            path = path.split(" -> ")[-1].strip().strip('"')
            dirty.add(path.replace("\\", "/"))
    return dirty


def _matches(entry: str, dirty_path: str) -> bool:
    entry = entry.replace("\\", "/")
    if entry.endswith("/"):
        return dirty_path.startswith(entry)
    return dirty_path == entry


def _shout(matched: Iterable[str]) -> None:
    """Loud warning to stderr when --allow-dirty bypasses the guard."""
    script = pathlib.Path(sys.argv[0]).name or "<deploy>"
    use_color = bool(getattr(sys.stderr, "isatty", lambda: False)())
    red = "\033[1;31m" if use_color else ""
    rst = "\033[0m" if use_color else ""
    bar = "=" * 65
    out_lines = [
        bar,
        f"{red}  --allow-dirty: SHIPPING UNCOMMITTED CHANGES via {script}{rst}",
    ]
    for f in matched:
        out_lines.append(f"    {f}")
    out_lines.append(
        "  this deploy will create drift between local repo and the box."
        " commit immediately after."
    )
    out_lines.append(bar)
    print("\n".join(out_lines), file=sys.stderr)


def check_clean(manifest_paths: list[str], allow_dirty: bool = False) -> None:
    """Refuse the deploy if any manifest entry has uncommitted changes.

    Raises:
        DirtyTreeError: when dirty files match the manifest and
            ``allow_dirty`` is False, or when git is unavailable / cwd is
            not a git checkout (fail-closed).
    """
    root = _repo_root()
    dirty = _dirty_files(root)
    matched: list[str] = []
    for entry in manifest_paths:
        for f in dirty:
            if _matches(entry, f) and f not in matched:
                matched.append(f)
    if not matched:
        return
    matched.sort()
    if allow_dirty:
        _shout(matched)
        return
    msg_lines = ["deploy refused — uncommitted changes in manifest:"]
    for f in matched:
        msg_lines.append(f"  {f}")
    msg_lines.append("commit first, or pass --allow-dirty to override.")
    raise DirtyTreeError("\n".join(msg_lines))
