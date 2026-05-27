"""
AAATS → Contabo Deployment Script (v3 — deploy_lib retrofit, 2026-05-27)

Reads credentials from .env file.
Run: venv\\Scripts\\python deploy_to_contabo.py [--allow-dirty]

v3 changes (retrofit to tools/operator/deploy_lib — closes the last
un-retrofit deploy script per CLAUDE.md "Deploy machinery gotchas"):
  • Raw `.tar.gz` upload replaced with per-file atomic_upload_normalized
    (.tmp + posix_rename swap, CRLF→LF normalization for textual files).
    tarfile preserved Windows CRLF and shipped \\r into box bash/yml/json —
    gotchas #1/#3/#9. Now every textual file is normalized on the way out.
  • enforce_utf8_console() at entry — gotcha #2 (Windows cp1252 console
    crashes on the Unicode arrows/emoji this script prints).
  • clear_stale_git_locks() before the dirty-tree guard — gotcha #4
    (Cowork sandbox leaves .git/index.lock the mount can't unlink).
  • preflight_ruff_format() over the deployable .py set runs BEFORE the
    dirty-tree guard — gotcha #5. If ruff reformats anything, the guard
    then refuses (unless --allow-dirty), surfacing uncommitted format drift
    rather than shipping it.
  • verify_telegram_path() smoke-tests the canonical /home/aaats/aaats/.env
    token path before the destructive rebuild — gotcha #11 (informational;
    this script sends no alerts itself, but the smoke catches a dead token
    early for any future alerting added here).

v2 changes (fixes 2026-05-13 collateral-damage incident — retained):
  • No more `docker compose down --remove-orphans` (was nuking grafana,
    metrics, telegram-bot every deploy). Now restarts ONLY the service
    whose code changed (aaats-paper-crypto).
  • Firewall step removed. Doctrine is Tailscale-only — public ports stay
    closed.
  • Status banner reflects actual exit codes; no false-success message.
  • Other observability services (grafana, prometheus, metrics, telegram-bot)
    are NEVER touched by this script. Manage them via deployment/docker-compose
    directly when needed.

Dirty-tree guard (2026-05-15):
  Refuses to deploy if any file/dir in INCLUDE has uncommitted git changes.
  Pass --allow-dirty for an emergency override (commit immediately after).
"""

import argparse
import subprocess
import sys
import os
import pathlib

try:
    import paramiko
except ImportError:
    print("Installing paramiko...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
    import paramiko

import time

# Repo root. This script lives at tools/operator/, so the repo root is three
# levels up. v3 fix: PROJECT_ROOT used to be `__file__.parent` (= tools/operator/),
# a latent bug from when the script was moved out of the repo root — it made the
# module crash on import (load_env looked for tools/operator/.env) and resolved
# every INCLUDE path (trading/, requirements.txt, .env) against the wrong dir.
# PROJECT_ROOT now equals the repo root so file resolution + .env load work.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = _REPO_ROOT
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Canonical deploy helpers — see CLAUDE.md "Deploy machinery gotchas" for the
# recurring failure modes each helper closes. Standing rule: every deploy
# script imports deploy_lib; do not reinvent.
from tools.operator.deploy_lib import (  # noqa: E402
    atomic_upload_normalized,
    clear_stale_git_locks,
    enforce_utf8_console,
    ensure_remote_dirs,
    preflight_ruff_format,
    verify_telegram_path,
)

enforce_utf8_console()


# ── Load .env ────────────────────────────────────────────────────────────────
def load_env(path):
    env = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().split("#")[0].strip()
    return env


_env = load_env(PROJECT_ROOT / ".env")

HOST = _env.get("CONTABO__TAILSCALE_IP", "100.95.126.39")
USER = _env.get("CONTABO__SSH_USER", "aaats")
PASSWORD = _env.get("CONTABO__SSH_PASSWORD") or os.environ.get("AAATS_SSH_PASSWORD")
if not PASSWORD:
    raise SystemExit(
        "CONTABO__SSH_PASSWORD (or AAATS_SSH_PASSWORD) not set. "
        "Copy .env.example to .env and fill in the rotated password."
    )
REMOTE_DIR = _env.get("CONTABO__REMOTE_DIR", "/home/aaats/aaats")
TAILSCALE = _env.get("CONTABO__TAILSCALE_IP", "100.95.126.39")
GRAFANA_PW = _env.get("CONTABO__GRAFANA_PASSWORD", "")
PORT = 22

# ── Files to deploy ──────────────────────────────────────────────────────────
INCLUDE = [
    "trading",
    "foundation",
    "monitoring",
    "risk",
    "ml",
    "markets",
    "indicators",
    "execution",
    "decision",
    "observability",
    "deployment",
    "data/ml",
    "scripts",
    ".env",
    "requirements.txt",
]
EXCLUDE = [
    "__pycache__",
    "*.pyc",
    "venv",
    ".git",
    "node_modules",
    "paper_trades.db",
    "logs",
]
# ─────────────────────────────────────────────────────────────────────────────


def run(client, cmd, desc="", ok_rc=(0,)):
    if desc:
        print(f"  → {desc}")
    _, stdout, stderr = client.exec_command(cmd, timeout=300)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    for line in out.splitlines()[-15:]:
        print(f"    {line}")
    if err and rc not in ok_rc:
        for line in err.splitlines()[-5:]:
            print(f"    ERR: {line}")
    return rc, out


def skip(s):
    for ex in EXCLUDE:
        if (ex.startswith("*") and s.endswith(ex[1:])) or (
            not ex.startswith("*") and ex in s
        ):
            return True
    return False


def collect_files():
    """Expand INCLUDE into (local_path, relposix) pairs, applying the skip()
    filter. relposix is the POSIX-style path relative to the repo root, used
    to build the remote destination. Replaces the v2 tarball build — each
    file is uploaded individually via atomic_upload_normalized so textual
    files land CRLF-normalized and swaps are atomic.
    """
    pairs = []
    for item in INCLUDE:
        src = PROJECT_ROOT / item
        if not src.exists():
            print(f"    ⚠ not found: {item}")
            continue
        if src.is_file():
            pairs.append((src, item.replace("\\", "/")))
        else:
            for f in src.rglob("*"):
                rel = str(f.relative_to(PROJECT_ROOT))
                if not skip(rel) and f.is_file():
                    pairs.append((f, rel.replace("\\", "/")))
    print(f"    {len(pairs)} files to upload")
    return pairs


def _build_manifest():
    """INCLUDE -> manifest entries: dirs get trailing slash, files stay bare."""
    file_entries = {".env", "requirements.txt"}
    return [
        item if item in file_entries else item.rstrip("/") + "/" for item in INCLUDE
    ]


def main():
    parser = argparse.ArgumentParser(description="AAATS deploy to Contabo")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="emergency override: ship uncommitted local edits. You'll need to "
        "commit them immediately after deploy or you've created drift.",
    )
    args = parser.parse_args()

    # Gotcha #4: clear stale .git locks Cowork left on the mount BEFORE any
    # git-touching step (the dirty-tree guard reads git state).
    for path in clear_stale_git_locks(_REPO_ROOT):
        print(f"  cleared stale lock: {path}")

    # Gotcha #5: preflight ruff format over the deployable .py set BEFORE the
    # dirty-tree guard. If ruff reformats anything, the guard below then
    # refuses (unless --allow-dirty), so format drift surfaces instead of
    # shipping. No-ops if ruff isn't installed.
    deployable_py = [p for p, _ in collect_files() if p.suffix == ".py"]
    if deployable_py:
        ok, msg = preflight_ruff_format(deployable_py, repo_root=_REPO_ROOT)
        print(f"  ruff preflight: {msg.splitlines()[-1] if msg else 'done'} (ok={ok})")

    from tools.operator._dirty_tree_guard import check_clean
    from tools.operator._newdir_parity_guard import check_newdir_parity

    check_clean(_build_manifest(), allow_dirty=args.allow_dirty)
    check_newdir_parity(INCLUDE, allow_dirty=args.allow_dirty)

    print("=" * 65)
    print("  AAATS → Contabo Deployment")
    print(f"  Target: {USER}@{HOST} (Tailscale):{REMOTE_DIR}")
    print("=" * 65)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    print(f"\n[1/9] Connecting to {HOST}...")
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
    print("      ✓ Connected")

    print("\n[2/9] Server checks...")
    rc, _ = run(client, "docker --version && docker compose version 2>&1")
    if rc != 0:
        print("      ✗ Docker not found on server")
        sys.exit(1)
    run(
        client,
        "systemctl is-active docker || sudo systemctl start docker 2>&1",
        ok_rc=(0, 1, 3),
    )
    print("      ✓ Docker OK")

    # v2: NO `docker compose down`. We restart only the service we updated
    # at step [6/8] below. Grafana / Prometheus / metrics / telegram-bot are
    # left running untouched.
    # v3: per-file atomic_upload_normalized replaces the raw tarball. Each
    # textual file is CRLF→LF normalized and swapped atomically (.tmp +
    # posix_rename) so a half-written file is never visible to the box.
    print("\n[3/8] Uploading codebase (per-file atomic + CRLF-normalized)...")
    pairs = collect_files()
    remote_files = [f"{REMOTE_DIR}/{rel}" for _, rel in pairs]
    run(client, f"mkdir -p {REMOTE_DIR}")
    ensure_remote_dirs(client, remote_files)  # mkdir -p every parent in one pass
    sftp = client.open_sftp()
    uploaded = 0
    try:
        for (local, rel), remote in zip(pairs, remote_files):
            atomic_upload_normalized(sftp, local, remote)
            uploaded += 1
            if uploaded % 50 == 0:
                print(f"      … {uploaded}/{len(pairs)} files")
    finally:
        sftp.close()
    run(
        client,
        f"mkdir -p {REMOTE_DIR}/logs {REMOTE_DIR}/data/state {REMOTE_DIR}/data/ml",
    )
    print(f"      ✓ Uploaded {uploaded} files (atomic, normalized)")

    # v2: firewall step REMOVED. Doctrine is Tailscale-only — public ports
    # 3000/9090/9091 must stay firewalled. Don't open them.
    print("\n[4/8] Firewall step skipped (Tailscale-only doctrine)")

    # Gotcha #11: smoke-test the canonical Telegram token path before the
    # destructive rebuild. This script sends no alerts itself, so the smoke
    # is informational — but it catches a dead token early for any future
    # alerting wired here, and confirms the box's .env path is intact.
    print("\n[4b/8] Telegram path smoke (informational)...")
    if verify_telegram_path(client):
        print("      ✓ Telegram token path OK (api.telegram.org/getMe 200)")
    else:
        print(
            "      ⚠ Telegram smoke FAILED — token path stale. Non-fatal "
            "(this script sends no alerts); rotate before relying on alerts."
        )

    print("\n[5/8] Building Docker image (2–5 min)...")
    rc, _ = run(
        client,
        f"cd {REMOTE_DIR}/deployment && docker compose build aaats-paper-crypto 2>&1 | tail -10",
        "docker build",
    )
    if rc != 0:
        print("      ✗ Build failed — see above")
        client.close()
        sys.exit(1)
    print("      ✓ Image built")

    # v2: surgical recreate. Only aaats-paper-crypto. Other services
    # (prometheus, grafana, metrics, telegram-bot) are left alone.
    print("\n[6/8] Recreating aaats-paper-crypto with new image/config...")
    rc, _ = run(
        client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose up -d --no-deps --force-recreate aaats-paper-crypto 2>&1",
    )
    if rc != 0:
        print("      ✗ Container start failed — aborting (other services untouched).")
        client.close()
        sys.exit(1)
    print("      ✓ aaats-paper-crypto recreated")

    print("\n[7/8] Waiting 15s for first cycle...")
    time.sleep(15)

    print("\n[8/8] Status check & integrity verification...")
    rc, ps = run(
        client, "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
    )
    expected_extra = [
        "aaats-grafana",
        "aaats-prometheus",
        "aaats-metrics",
        "aaats-telegram-bot",
    ]
    missing = [s for s in expected_extra if s not in ps]
    if missing:
        print(f"      ⚠ Observability services not running: {missing}")
        print("      ⚠ NOTE: this deploy script no longer manages those services.")
        print(
            f"      ⚠ Restore via: cd {REMOTE_DIR}/deployment && docker compose up -d "
            + " ".join(missing)
        )
    rc, _ = run(client, "docker logs aaats-paper-crypto --tail 40 2>&1", "First logs")

    # v2: honest banner — only declare success if paper-crypto is actually up.
    rc, status = run(
        client,
        "docker inspect -f '{{.State.Status}}/{{.State.Health.Status}}' aaats-paper-crypto 2>&1",
    )
    healthy = "running" in status and ("healthy" in status or "starting" in status)
    print("\n" + "=" * 65)
    if healthy:
        print(f"  ✅ aaats-paper-crypto: {status}")
    else:
        print(f"  ⚠ aaats-paper-crypto: {status} — check logs")
    if missing:
        print(f"  ⚠ Missing services (not started by this script): {missing}")
    print()
    print(f"  Grafana (Tailscale): http://{TAILSCALE}:3000")
    print(f"  SSH:   ssh {USER}@{HOST}")
    print("  Logs:  docker logs aaats-paper-crypto -f")
    print("=" * 65)
    client.close()


if __name__ == "__main__":
    main()
