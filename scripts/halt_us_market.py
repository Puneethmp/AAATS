"""
One-shot helper: halt the US market on the box via the proper kill_switch
code path (audit trail + Telegram alert + persisted to box's
/home/aaats/aaats/data/halt_state.json).

Why this helper exists:
  - The local `data/halt_state.json` in this repo is for record-keeping
    only — the aaats-paper-crypto container reads the BOX's copy at
    /home/aaats/aaats/data/halt_state.json, which is NOT auto-synced
    from origin/main (autopush writes to a separate /srv/aaats/
    runtime_repo, not /home/aaats/aaats).
  - Directly SCP'ing the JSON would skip the audit-trail write and the
    Telegram alert. Running kill.py on the box hits both.

Usage (from project root, requires .env with CONTABO__SSH_PASSWORD):
  python scripts/halt_us_market.py
  python scripts/halt_us_market.py --reset --authorized-by Puneeth

Why halt US at all (2026-05-25):
  Operator-away soak posture. India already halted; US gets symmetric
  treatment for defense-in-depth even though no run_us code path exists
  today. Cheap insurance against any future code path that consults
  halt_state["us"].
"""

from __future__ import annotations

import argparse
import datetime as _dt
import pathlib as _pl
import sys

import paramiko

PROJECT_ROOT = _pl.Path(__file__).resolve().parent.parent


def _load_env(path: _pl.Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().split("#")[0].strip()
    return env


_env = _load_env(PROJECT_ROOT / ".env")
HOST = _env.get("CONTABO__TAILSCALE_IP", "100.95.126.39")
USER = _env.get("CONTABO__SSH_USER", "aaats")
PASSWORD = _env.get("CONTABO__SSH_PASSWORD", "")
REMOTE_DIR = _env.get("CONTABO__REMOTE_DIR", "/home/aaats/aaats")


def main() -> int:
    p = argparse.ArgumentParser(description="Halt or resume the US market on box")
    p.add_argument("--reset", action="store_true", help="Resume instead of halt")
    p.add_argument(
        "--authorized-by",
        default="",
        help="Required when --reset is set",
    )
    p.add_argument(
        "--reason",
        default=f"operator-away soak posture {_dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%d')}, US halted for symmetry with India",
    )
    args = p.parse_args()

    if not PASSWORD:
        print("FATAL: CONTABO__SSH_PASSWORD not in .env")
        return 1

    if args.reset and not args.authorized_by:
        print("ERROR: --authorized-by is required when --reset is set")
        print(
            "Example: python scripts/halt_us_market.py --reset --authorized-by Puneeth"
        )
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {USER}@{HOST}...")
    client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    print("Connected.\n")

    # Read pre state
    _, out, _ = client.exec_command(f"cat {REMOTE_DIR}/data/halt_state.json")
    pre_state = out.read().decode("utf-8", "replace").strip()
    print(f"PRE state:\n{pre_state}\n")

    # Run kill.py INSIDE the container (host Python lacks the trading deps;
    # the container ships kill.py at /app/kill.py and has sqlalchemy etc.
    # baked in). Both the audit trail and Telegram alert fire from there.
    if args.reset:
        cmd = (
            f"docker exec aaats-paper-crypto python /app/kill.py "
            f"--reset --market us "
            f"--authorized-by '{args.authorized_by}' --reason '{args.reason}'"
        )
    else:
        cmd = (
            f"docker exec aaats-paper-crypto python /app/kill.py "
            f"--market us --reason '{args.reason}'"
        )
    print(f"Running on box: {cmd}\n")
    _, out, err = client.exec_command(cmd, timeout=30)
    rc = out.channel.recv_exit_status()
    print(out.read().decode("utf-8", "replace"))
    err_text = err.read().decode("utf-8", "replace").strip()
    if err_text:
        print(f"STDERR:\n{err_text}\n")

    # Read post state
    _, out, _ = client.exec_command(f"cat {REMOTE_DIR}/data/halt_state.json")
    post_state = out.read().decode("utf-8", "replace").strip()
    print(f"POST state:\n{post_state}\n")

    # Verification — read the in-process is_halted() to confirm the
    # container will see the new state on next cycle.
    verify_cmd = (
        "docker exec aaats-paper-crypto python -c "
        '"from foundation.kill_switch import is_halted; '
        'print(f\'us={is_halted(\\"us\\")} india={is_halted(\\"india\\")} '
        'crypto={is_halted(\\"crypto\\")}\')"'
    )
    _, out, _ = client.exec_command(verify_cmd, timeout=15)
    verify = out.read().decode("utf-8", "replace").strip()
    print(f"Container view: {verify}")

    client.close()

    if rc != 0:
        print(f"\nFAILED — kill.py exited with rc={rc}")
        return rc
    print("\nOK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
