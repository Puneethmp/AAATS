"""Live-flip deploy. Operator types 'FLIP TO LIVE $25' to proceed.

Workflow:
  1. Verify the rollback baseline exists and is fresh (<= 30 min).
  2. Verify data/pre_flight_log.json has PF1/PF2/PF3 all pass.
  3. If .env.live is missing locally, render it from
     .rollback/2026-05-22_live_flip/env.pre by injecting the four
     LIVE_TRANCHE_* and PAPER_MODE / LIVE_CAPITAL_USD values.
  4. Print the summary block and require the literal string
     'FLIP TO LIVE $25' on stdin to proceed.
  5. Atomic SCP: upload .env.live -> /home/aaats/aaats/.env.tmp,
     then mv -f to .env.
  6. docker compose ... restart aaats-paper-crypto.
  7. Tail container logs for ~30s.

Hard constraints (NEXT_PROMPT.md 2026-05-21):
  - Operator must type the literal confirmation string at the gate.
  - Do NOT auto-respond if invoked under tests/automation.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
from datetime import datetime, timezone

import paramiko

BASELINE_DIR = pathlib.Path(".rollback") / "2026-05-22_live_flip"
ENV_LIVE_PATH = pathlib.Path(".env.live")
PF_LOG = pathlib.Path("data") / "pre_flight_log.json"
BOX_HOST = "100.95.126.39"
BOX_USER = "aaats"
ENV_PATH_ON_BOX = "/home/aaats/aaats/.env"
COMPOSE_PATH = "/home/aaats/aaats/deployment/docker-compose.yml"
CONTAINER = "aaats-paper-crypto"
CONFIRM_STRING = "FLIP TO LIVE $25"
BASELINE_MAX_AGE_MIN = 30


# --- env.live rendering ---------------------------------------------------

LIVE_VARS = {
    "PAPER_MODE": "False",
    "LIVE_CAPITAL_USD": "25.0",
    "LIVE_TRANCHE_START": "2026-05-22T00:00:00Z",
    "LIVE_TRANCHE_NAME": "tranche_1_25usd",
}


def render_env_live(env_pre_body: str) -> str:
    """Produce .env.live body from the box's .env.pre, applying LIVE_VARS."""
    lines = env_pre_body.splitlines()
    applied: set[str] = set()
    for i, line in enumerate(lines):
        for key, new_val in LIVE_VARS.items():
            if key in applied:
                continue
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={new_val}"
                applied.add(key)
                break
    for key, new_val in LIVE_VARS.items():
        if key not in applied:
            lines.append(f"{key}={new_val}")
    body = "\n".join(lines)
    if not body.endswith("\n"):
        body += "\n"
    return body


def ensure_env_live() -> pathlib.Path:
    """If .env.live exists, return its path; else render from env.pre."""
    if ENV_LIVE_PATH.exists():
        return ENV_LIVE_PATH
    env_pre = BASELINE_DIR / "env.pre"
    if not env_pre.exists():
        sys.exit(
            f"ABORT: .env.live missing and no baseline at {env_pre}. "
            "Run scripts/live_flip_rollback_baseline.py first."
        )
    body = render_env_live(env_pre.read_text(encoding="utf-8"))
    ENV_LIVE_PATH.write_text(body, encoding="utf-8")
    print(f"Rendered {ENV_LIVE_PATH} from {env_pre} (applied {sorted(LIVE_VARS)})")
    return ENV_LIVE_PATH


# --- pre-flight gates -----------------------------------------------------

def check_baseline_fresh() -> None:
    manifest = BASELINE_DIR / "MANIFEST.txt"
    if not manifest.exists():
        sys.exit("ABORT: no rollback baseline at " + str(BASELINE_DIR))
    age_min = (time.time() - manifest.stat().st_mtime) / 60
    if age_min > BASELINE_MAX_AGE_MIN:
        sys.exit(
            f"ABORT: baseline is {age_min:.1f}min old "
            f"(> {BASELINE_MAX_AGE_MIN} min). "
            "Re-run live_flip_rollback_baseline.py."
        )


def check_pre_flights_green() -> None:
    if not PF_LOG.exists():
        sys.exit(
            "ABORT: data/pre_flight_log.json missing — "
            "run scripts/run_pre_flights.py first."
        )
    pf = json.loads(PF_LOG.read_text(encoding="utf-8"))
    for k in ("PF1", "PF2", "PF3"):
        if k not in pf or pf[k].get("status") != "pass":
            sys.exit(f"ABORT: {k} not green in pre_flight_log.json")


def require_confirmation() -> None:
    print("=" * 60)
    print("LIVE FLIP — paper_mode False, capital $25 USD")
    print(f"Box: {BOX_USER}@{BOX_HOST}, container: {CONTAINER}")
    print("Rollback baseline at: " + str(BASELINE_DIR))
    print("PF1/PF2/PF3: all pass (per data/pre_flight_log.json)")
    print("=" * 60)
    print(f"Type '{CONFIRM_STRING}' to proceed, or anything else to abort:")
    response = input("> ").strip()
    if response != CONFIRM_STRING:
        sys.exit("ABORT: confirmation string mismatch — no changes made")


# --- box ops --------------------------------------------------------------

def upload_and_swap(ssh: paramiko.SSHClient, env_live_path: pathlib.Path) -> None:
    print("Uploading .env.live to box (atomic .tmp + mv -f)...")
    sftp = ssh.open_sftp()
    try:
        sftp.put(str(env_live_path), ENV_PATH_ON_BOX + ".tmp")
    finally:
        sftp.close()
    _, stdout, _ = ssh.exec_command(
        f"mv -f {ENV_PATH_ON_BOX}.tmp {ENV_PATH_ON_BOX}"
    )
    stdout.channel.recv_exit_status()


def restart_container(ssh: paramiko.SSHClient) -> int:
    print(f"Restarting {CONTAINER}...")
    _, stdout, stderr = ssh.exec_command(
        f"cd /home/aaats/aaats && "
        f"docker compose -f {COMPOSE_PATH} restart {CONTAINER}"
    )
    rc = stdout.channel.recv_exit_status()
    print(stdout.read().decode())
    print(stderr.read().decode())
    return rc


def tail_logs(ssh: paramiko.SSHClient) -> None:
    print("Tailing logs for 30s window (--since 1m, last 100 lines)...")
    _, stdout, _ = ssh.exec_command(
        f"docker logs {CONTAINER} --tail 100 --since 1m"
    )
    print(stdout.read().decode())


def main() -> int:
    check_baseline_fresh()
    check_pre_flights_green()
    env_live = ensure_env_live()
    require_confirmation()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(BOX_HOST, username=BOX_USER)
    try:
        upload_and_swap(ssh, env_live)
        time.sleep(2)
        rc = restart_container(ssh)
        time.sleep(5)
        tail_logs(ssh)
    finally:
        ssh.close()

    print("\nLIVE FLIP COMPLETE at " + datetime.now(timezone.utc).isoformat())
    if rc != 0:
        print(f"WARNING: container restart exit code = {rc}", file=sys.stderr)
        return 1
    print("Watch first 4 cycles via scripts/tail_paper_crypto.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
