#!/usr/bin/env python3
"""
Deploy the Telegram-bot self-heal change set (L1 healthcheck + L3 on-box
watchdog) to the Contabo box. L4 (GitHub Actions) deploys itself on push to
origin/main; it is NOT shipped by this script.

This is an alert-chain / uptime fix — permitted under the maintenance contract
(CLAUDE.md "MAINTENANCE CONTRACT" exception clause). Decision record:
docs/decisions/2026-06-25_telegram_selfheal.md.

What it does (idempotent, no sibling-container disruption):
  1. Smoke-verify the Telegram path FIRST (verify_telegram_path) and fail-fast
     if the token is already broken — we don't want to deploy blind.
  2. Atomic-upload the three on-box files with line-ending normalization:
       - scripts/telegram_healthcheck.py        (in-container healthcheck)
       - deployment/docker-compose.yml          (adds the healthcheck block)
       - scripts/box/aaats-telegram-watchdog.sh -> /home/aaats/bin/ (+chmod +x)
  3. Install the watchdog cron (*/5) if absent — mirrors aaats-heartbeat-checker.
  4. Rebuild + recreate ONLY aaats-telegram-bot (--no-deps --build
     --force-recreate) so the new healthcheck file is baked into the image
     (scripts/ is COPY'd into the image, not bind-mounted) and the watchdog
     baseline is seeded.
  5. Post-verify: container reports a health status, and send a post-deploy
     Telegram note via the box's own credentials.

Run from the Windows workstation (same host that runs the other deploy
scripts). Requires AAATS_SSH_PASSWORD in env/.env.

    python tools/operator/deploy_telegram_selfheal.py [--dry-run]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

try:
    import paramiko
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
    import paramiko

# deploy_lib lives next to this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy_lib as dl  # noqa: E402

import os  # noqa: E402

HOST = os.environ.get("AAATS_SSH_HOST", "100.95.126.39")
USER = os.environ.get("AAATS_SSH_USER", "aaats")
PASSWORD = os.environ.get("AAATS_SSH_PASSWORD")

REPO_ROOT = Path(__file__).resolve().parents[2]
REMOTE_REPO = "/home/aaats/aaats"
REMOTE_BIN = "/home/aaats/bin"

# (local path relative to repo root, remote absolute path, chmod_exec)
FILES = [
    (
        "scripts/telegram_healthcheck.py",
        f"{REMOTE_REPO}/scripts/telegram_healthcheck.py",
        False,
    ),
    (
        "deployment/docker-compose.yml",
        f"{REMOTE_REPO}/deployment/docker-compose.yml",
        False,
    ),
    (
        "scripts/box/aaats-telegram-watchdog.sh",
        f"{REMOTE_BIN}/aaats-telegram-watchdog.sh",
        True,
    ),
]

CRON_LINE = (
    "*/5 * * * * /home/aaats/bin/aaats-telegram-watchdog.sh "
    ">> /home/aaats/aaats-telegram-watchdog.log 2>&1"
)


def main() -> int:
    dl.enforce_utf8_console()
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="connect + smoke-verify + print plan, upload nothing",
    )
    args = ap.parse_args()

    if not PASSWORD:
        raise SystemExit("AAATS_SSH_PASSWORD not set (see .env.example).")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {HOST} ...")
    client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    print("Connected.\n")

    def run(cmd: str, label: str = "") -> tuple[int, str]:
        if label:
            print(f"[{label}]")
        _, out, err = client.exec_command(cmd, timeout=180)
        rc = out.channel.recv_exit_status()
        o, e = out.read().decode().strip(), err.read().decode().strip()
        if o:
            print(o[-3000:])
        if e and rc != 0:
            print(f"STDERR: {e[-700:]}")
        return rc, o

    # 1) smoke-verify the alert path BEFORE doing anything destructive.
    print("[1/5] Verifying Telegram token path (getMe) ...")
    if not dl.verify_telegram_path(client):
        client.close()
        raise SystemExit(
            "Telegram getMe FAILED. Token in .env is already broken — fix .env "
            "first (rotate token), then re-run. Not deploying blind."
        )
    print("      token OK.\n")

    if args.dry_run:
        print("[dry-run] would upload:")
        for local, remote, ex in FILES:
            print(f"   {local}  ->  {remote}{'  (+x)' if ex else ''}")
        print(f"[dry-run] would ensure cron: {CRON_LINE}")
        print(
            "[dry-run] would rebuild+recreate aaats-telegram-bot (--no-deps --build --force-recreate)"
        )
        client.close()
        return 0

    # 2) atomic, line-ending-normalized uploads.
    print("[2/5] Uploading files ...")
    sftp = client.open_sftp()
    dl.ensure_remote_dirs(client, [REMOTE_BIN, f"{REMOTE_REPO}/scripts/box"])
    for local, remote, ex in FILES:
        sha = dl.atomic_upload_normalized(sftp, REPO_ROOT / local, remote)
        if ex:
            run(f"chmod +x {remote}")
        print(f"   {local}  ->  {remote}  sha16={sha}")
    sftp.close()

    # 3) install watchdog cron if missing (idempotent).
    print("\n[3/5] Ensuring watchdog cron ...")
    run(
        "( crontab -l 2>/dev/null | grep -F 'aaats-telegram-watchdog.sh' ) "
        f"|| ( crontab -l 2>/dev/null; echo '{CRON_LINE}' ) | crontab -",
        "cron install",
    )
    run(
        "crontab -l | grep -F 'aaats-telegram-watchdog.sh' || echo 'CRON MISSING'",
        "cron verify",
    )

    # 4) rebuild + recreate ONLY the bot so the healthcheck attaches; seed
    #    watchdog baseline. --build is REQUIRED: scripts/ is baked into the image
    #    via `COPY . .` (deployment/Dockerfile, WORKDIR /app) and is NOT
    #    bind-mounted, so the brand-new scripts/telegram_healthcheck.py only
    #    reaches the container if the image is rebuilt. Without --build the
    #    recreate reuses the stale image, the healthcheck file is absent, and the
    #    container goes permanently `unhealthy` (then the watchdog recreate-loops).
    print("\n[4/5] Rebuilding + recreating aaats-telegram-bot ...")
    run(
        f"cd {REMOTE_REPO} && docker compose -p deployment "
        "-f deployment/docker-compose.yml up -d --no-deps --build --force-recreate "
        "aaats-telegram-bot 2>&1",
        "rebuild+recreate",
    )
    run(
        "/home/aaats/bin/aaats-telegram-watchdog.sh 2>&1 || true",
        "watchdog first-tick (seed baseline)",
    )

    # 5) post-verify + post-deploy note.
    print("\n[5/5] Post-verify ...")
    run(
        "sleep 35; docker inspect --format "
        "'status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "
        "aaats-telegram-bot 2>&1",
        "health",
    )
    dl.send_telegram_message(
        client,
        "AAATS deploy: telegram self-heal (L1 healthcheck + L3 watchdog) installed. "
        "Token rotations now auto-apply; unhealthy bot auto-recreates.",
    )
    client.close()
    print(
        "\nDone. Watch `docker inspect aaats-telegram-bot` -> health=healthy within ~2 cycles."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
