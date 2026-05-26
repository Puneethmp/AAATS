"""tools/operator/deploy_lib.py — durable deploy helpers (sprint 2026-05-26).

Closes the recurring deploy-machinery failure class identified after the
2026-05-26 structural-fix deploy. Across the 2026-05-15 → 2026-05-26 window,
9+ distinct manual interventions were required per deploy, all from the
same set of root causes. Each one is logged here once, with the structural
fix beside it. Every future deploy script in tools/operator/ should import
from this module instead of reinventing.

Recurring failure modes addressed:

  1. CRLF line endings break .sh files on box (bit twice in 2026-05-26 alone)
     → atomic_upload_normalized() strips CRLF for textual extensions.
  2. paramiko SFTP binary mode preserves Windows CRLF
     → Same fix; covers .sh/.py/.yml/.json/.md/.txt.
  3. tarfile.add() preserves bytes as-is
     → normalize_bytes_for_text_file() can be applied to TarInfo addfile.
  4. Windows cp1252 console crashes on Unicode arrows in print()
     → enforce_utf8_console() reconfigures stdout/stderr at script entry.
  5. Box auto-cron races every 15 min during push (forced stash/rebase/pop)
     → auto_rebase_or_stash() handles the dance.
  6. Cowork sandbox leaves stale .git/index.lock Windows must clear
     → clear_stale_git_locks() removes the usual suspects.
  7. Pre-commit ruff auto-reformat racing commit
     → preflight_ruff_format() runs format+check before staging.
  8. Grafana dashboard mount path is /srv/aaats/compose/grafana/dashboards/
     (NOT deployment/grafana/dashboards/ in the repo)
     → GRAFANA_HOST_MOUNT constant + push_grafana_dashboard() that writes
     to both the repo path AND the live mount path.
  9. Soft-fail docker cp pollutes autopush log every cycle for files that
     legitimately don't exist (C5b disabled, share-eq never triggered)
     → container_file_exists() + smart_cp_state() guards.

Idempotent + safe to re-import. No side effects at import time.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable

# ──────────────────────────────────────────────────────────────────────────
# Constants — durable facts about box layout
# ──────────────────────────────────────────────────────────────────────────

LINE_ENDING_NORMALIZE_EXTS: frozenset[str] = frozenset(
    (".sh", ".py", ".yml", ".yaml", ".json", ".md", ".txt", ".env", ".cfg", ".ini")
)

# Real Grafana host mount as of 2026-05-26 (per CLAUDE.md: aaats-base project
# lives at /srv/aaats/compose/; aaats-paper-crypto's project lives at
# /home/aaats/aaats/deployment/). The Grafana container reads dashboards
# from the aaats-base project's mount, NOT the deployment/ project's.
GRAFANA_HOST_MOUNT: str = "/srv/aaats/compose/grafana/dashboards"

# Files that don't always exist on the box. Used by autopush + deploy to
# silently skip rather than log a cp failure every cycle.
EPHEMERAL_STATE_FILES: frozenset[str] = frozenset(
    (
        "funding_arb_state.json",  # C5b disabled
        "share_equality_mismatches.json",  # only written when WARN fires
        "capital_invariant_alerts.json",  # only written on non-ok verdict
        "momentum_state.json",  # C2 not yet active
        "strategy_halt_state.json",  # only written when a strategy halts
        "ledger_divergence_alerts.json",  # only written on divergence
    )
)

# Hard-required snapshot files. Missing one of these = real deploy failure.
HARD_REQUIRED_STATE_FILES: frozenset[str] = frozenset(
    ("paper_trades.db", "paper_positions.json", "paper_portfolio.json")
)


# ──────────────────────────────────────────────────────────────────────────
# Line-ending normalization
# ──────────────────────────────────────────────────────────────────────────


def normalize_bytes_for_text_file(data: bytes, filename: str) -> bytes:
    """Strip CRLF→LF + strip UTF-8 BOM for files whose extension is in
    LINE_ENDING_NORMALIZE_EXTS. Pass binary files through unchanged.

    The single line that has bitten every Windows→Linux deploy in this repo
    since 2026-05-15.
    """
    ext = Path(filename).suffix.lower()
    if ext not in LINE_ENDING_NORMALIZE_EXTS:
        return data
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def normalize_local_file_in_place(path: Path) -> bool:
    """Apply normalize_bytes_for_text_file to a local file. Returns True if
    the file was modified. Safe for both Cowork-mount and native Windows.
    """
    raw = path.read_bytes()
    fixed = normalize_bytes_for_text_file(raw, path.name)
    if fixed != raw:
        path.write_bytes(fixed)
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────
# SFTP atomic upload with normalization
# ──────────────────────────────────────────────────────────────────────────


def atomic_upload_normalized(sftp, local_path: Path, remote_path: str) -> str:
    """Upload via .tmp + posix_rename atomic swap, normalizing line endings
    for textual files. Returns sha16 of the bytes that landed on the box
    (post-normalization), which is what should be checksummed for rollback.
    """
    raw = local_path.read_bytes()
    normalized = normalize_bytes_for_text_file(raw, local_path.name)
    sha = hashlib.sha256(normalized).hexdigest()[:16]
    tmp = remote_path + ".tmp"
    with sftp.file(tmp, "wb") as f:
        f.write(normalized)
    sftp.posix_rename(tmp, remote_path)
    return sha


# ──────────────────────────────────────────────────────────────────────────
# Windows console encoding (cp1252 → utf-8)
# ──────────────────────────────────────────────────────────────────────────


def enforce_utf8_console() -> None:
    """Set Windows console to UTF-8 + reconfigure stdout/stderr. Idempotent.
    Call once at the top of any deploy script that might print() emojis or
    Unicode arrows. Without this, scripts that work on macOS/Linux crash
    on Windows the moment they print a non-ASCII char.
    """
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────────
# Git hygiene — locks + auto-rebase before push
# ──────────────────────────────────────────────────────────────────────────


def clear_stale_git_locks(repo_root: Path) -> list[str]:
    """Remove .git/index.lock and friends. Returns list of files cleared.
    Cowork sandbox leaves these behind when it can't unlink on the mount;
    Windows can clear them safely since Cowork has exited.
    """
    cleared: list[str] = []
    git_dir = Path(repo_root) / ".git"
    if not git_dir.exists():
        return cleared
    for lockname in (
        "index.lock",
        "HEAD.lock",
        "config.lock",
        "packed-refs.lock",
        "MERGE_HEAD.lock",
    ):
        p = git_dir / lockname
        if p.exists():
            try:
                p.unlink()
                cleared.append(str(p))
            except OSError:
                pass
    return cleared


def _git(*args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


def auto_rebase_or_stash(
    branch: str = "main", repo_root: Path | None = None
) -> tuple[bool, str]:
    """Pre-push hygiene: fetch, stash if dirty, pull --rebase, pop stash.
    Returns (success, message). Handles the box auto-cron 15-min race.

    Note: the box's auto-cron commits ONLY runtime/ files; the workstation
    work touches everything else. So the rebase should almost always be
    clean (no overlapping files). This handles the rare case where
    overlap occurs by failing loudly rather than silent merge.
    """
    rc, _, err = _git("fetch", "origin", branch, cwd=repo_root)
    if rc != 0:
        return False, f"git fetch failed: {err.strip()}"

    rc, out, _ = _git("status", "--porcelain", cwd=repo_root)
    dirty = bool(out.strip())
    stashed = False
    if dirty:
        rc, _, err = _git(
            "stash", "push", "-u", "-m", "deploy-auto-stash", cwd=repo_root
        )
        stashed = rc == 0
        if not stashed:
            return False, f"git stash failed: {err.strip()}"

    rc, _, err = _git("pull", "--rebase", "origin", branch, cwd=repo_root)
    if rc != 0:
        # restore stash before bailing
        if stashed:
            _git("stash", "pop", cwd=repo_root)
        return False, f"git pull --rebase failed: {err.strip()}"

    if stashed:
        rc, _, err = _git("stash", "pop", cwd=repo_root)
        if rc != 0:
            return False, f"git stash pop failed: {err.strip()}"

    return True, f"rebased onto origin/{branch}"


# ──────────────────────────────────────────────────────────────────────────
# Pre-commit ruff preflight
# ──────────────────────────────────────────────────────────────────────────


def preflight_ruff_format(
    paths: Iterable[Path], repo_root: Path | None = None
) -> tuple[bool, str]:
    """Run `ruff format` then `ruff check --fix` on the given paths BEFORE
    git add. Prevents the pre-commit hook from reformatting at commit time
    and forcing a re-stage. Idempotent. Returns (ok, message).

    Falls back to silent no-op if ruff is not installed (the operator may
    legitimately skip ruff in some workflows).
    """
    py_paths = [str(p) for p in paths if str(p).endswith(".py") and Path(p).exists()]
    if not py_paths:
        return True, "no .py paths to ruff"
    try:
        r1 = subprocess.run(
            ["ruff", "format", *py_paths], capture_output=True, text=True, cwd=repo_root
        )
        r2 = subprocess.run(
            ["ruff", "check", "--fix", *py_paths],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
    except FileNotFoundError:
        return True, "ruff not installed; skipping preflight"
    msg = (r1.stdout + r1.stderr + r2.stdout + r2.stderr).strip()
    return (
        r1.returncode == 0 and r2.returncode in (0, 1)
    ), msg or "ruff preflight done"


# ──────────────────────────────────────────────────────────────────────────
# Remote dir provisioning
# ──────────────────────────────────────────────────────────────────────────


def ensure_remote_dirs(client, paths: Iterable[str]) -> None:
    """mkdir -p on the box for each remote path's parent dir. Idempotent.

    `paths` are absolute remote paths (file paths, not dirs). The function
    extracts each parent and mkdir -p's them in a single SSH round-trip.
    """
    dirs: set[str] = set()
    for p in paths:
        parent = str(PurePosixPath(p).parent)
        if parent and parent not in ("/", "."):
            dirs.add(parent)
    if not dirs:
        return
    cmd = " && ".join(f"mkdir -p {d}" for d in sorted(dirs))
    _, stdout, _ = client.exec_command(cmd, timeout=30)
    stdout.channel.recv_exit_status()  # wait


# ──────────────────────────────────────────────────────────────────────────
# Grafana dashboard push — repo + live mount
# ──────────────────────────────────────────────────────────────────────────


def push_grafana_dashboard(
    sftp, client, local_dashboard: Path, remote_dir: str = GRAFANA_HOST_MOUNT
) -> tuple[str, str]:
    """Push a dashboard JSON to BOTH the repo's deployment/grafana/dashboards/
    (for git source-of-truth) AND the live Grafana host mount at
    /srv/aaats/compose/grafana/dashboards/ (where the running Grafana
    container actually reads from).

    Without writing to the live mount, repo dashboards are invisible to
    the running Grafana — bit in 2026-05-26 deploy.

    Returns (repo_remote_path, live_remote_path).
    """
    fname = local_dashboard.name
    repo_remote = f"/home/aaats/aaats/deployment/grafana/dashboards/{fname}"
    live_remote = f"{remote_dir}/{fname}"
    ensure_remote_dirs(client, [repo_remote, live_remote])
    atomic_upload_normalized(sftp, local_dashboard, repo_remote)
    atomic_upload_normalized(sftp, local_dashboard, live_remote)
    return repo_remote, live_remote


# ──────────────────────────────────────────────────────────────────────────
# Container existence guard for docker cp
# ──────────────────────────────────────────────────────────────────────────


def container_file_exists(client, container: str, container_path: str) -> bool:
    """Cheap existence check inside a docker container. Used by smart_cp_state
    to skip cp commands for ephemeral state files that legitimately don't
    exist yet (e.g. C5b state when C5b is disabled).
    """
    cmd = f"docker exec {container} test -f {container_path}"
    _, stdout, _ = client.exec_command(cmd, timeout=10)
    return stdout.channel.recv_exit_status() == 0


def smart_cp_state(
    client,
    container: str,
    container_path: str,
    host_path: str,
    silent_on_missing: bool = True,
) -> tuple[bool, str]:
    """docker cp guarded by file existence inside the container.

    Returns (success, status_message). When silent_on_missing is True (the
    default for ephemeral state), a missing source file is treated as
    success-with-skip rather than failure, so logs stay clean.
    """
    if silent_on_missing and not container_file_exists(
        client, container, container_path
    ):
        return True, "skip (not present in container)"
    cmd = f"timeout 15 docker cp {container}:{container_path} {host_path}"
    _, stdout, stderr = client.exec_command(cmd, timeout=30)
    rc = stdout.channel.recv_exit_status()
    if rc != 0:
        return False, f"cp failed: {stderr.read().decode().strip()}"
    return True, "cp ok"
