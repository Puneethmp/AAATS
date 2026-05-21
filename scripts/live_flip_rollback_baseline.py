"""Pre-live-flip rollback baseline capture.

Captures the box's .env, container image SHA, and a copy of paper_trades.db
into .rollback/2026-05-22_live_flip/ so the operator can revert cleanly if
the first cycles after the live flip show problems.

Companion to scripts/deploy_live_flip.py.
"""

from __future__ import annotations

import datetime
import json
import pathlib

import paramiko

BOX_HOST = "100.95.126.39"
BOX_USER = "aaats"
BASELINE_DIR = pathlib.Path(".rollback") / "2026-05-22_live_flip"


def main() -> None:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(BOX_HOST, username=BOX_USER)
    try:
        _, stdout, _ = ssh.exec_command("cat /home/aaats/aaats/.env")
        (BASELINE_DIR / "env.pre").write_bytes(stdout.read())

        _, stdout, _ = ssh.exec_command(
            "docker inspect aaats-paper-crypto --format '{{.Image}}'"
        )
        (BASELINE_DIR / "image_sha.pre").write_bytes(stdout.read())

        # Snapshot the box DB to /tmp on the box (cheap copy, recoverable
        # while the box is up). A full SCP back to the workstation is
        # avoided because the file may be large and the rollback path only
        # needs the box-local copy.
        ssh.exec_command(
            "cp /home/aaats/aaats/data/paper_trades.db "
            "/tmp/paper_trades_pre_live.db"
        )

        # Capture RestartCount + uptime for the audit trail.
        _, stdout, _ = ssh.exec_command(
            "docker inspect aaats-paper-crypto "
            "--format '{{.RestartCount}}|{{.State.StartedAt}}'"
        )
        rc_started = stdout.read().decode().strip()
    finally:
        ssh.close()

    manifest = {
        "purpose": "pre-live-flip baseline (first tranche $25)",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "files": [
            "env.pre",
            "image_sha.pre",
            "/tmp/paper_trades_pre_live.db (on box)",
        ],
        "box_container_restart_count_pipe_started_at": rc_started,
    }
    (BASELINE_DIR / "MANIFEST.txt").write_text(
        json.dumps(manifest, indent=2),
    )
    print(f"Rollback baseline written to {BASELINE_DIR}")


if __name__ == "__main__":
    main()
