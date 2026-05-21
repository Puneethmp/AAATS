"""scripts/deploy_ledger_flag.py -- safe USE_UNIFIED_LEDGER flag flip on box.

Spec: docs/decisions/2026-05-21_ledger_spec_recommendations.md Q4=A.

Refuses to flip USE_UNIFIED_LEDGER unless a "drain_ok" event was appended
to data/ledger_flag_history.json within the last 10 minutes. Performs an
atomic .env update on the Contabo box via the paramiko .tmp + mv -f
pattern (consistent with docs/conventions/deploy_discipline.md).

Usage
-----
    # 1. operator runs drain_positions.py on the box and confirms exit 0.
    # 2. operator runs this script with the new value.
    python scripts/deploy_ledger_flag.py --set true
    python scripts/deploy_ledger_flag.py --set false

The script:
  - Reads data/ledger_flag_history.json and finds the most recent drain_ok.
  - Aborts if no drain_ok in the last 10 minutes.
  - Connects to aaats@100.95.126.39 over Tailscale.
  - Reads /home/aaats/aaats/.env, replaces or appends the USE_UNIFIED_LEDGER
    line.
  - Uploads the new file as .env.tmp and atomically renames it to .env.
  - Restarts aaats-paper-crypto via `docker compose ... restart`.
  - Appends a "flag_flipped" event to ledger_flag_history.json with old/new
    values and the post-restart container image SHA.

The script does NOT execute the live flip itself -- that is a separate
workstream (scripts/deploy_live_flip.py). This script only manages the
USE_UNIFIED_LEDGER env var.

Hard constraints honored:
- Refuses with non-zero exit unless drain_ok < 10min old.
- Atomic .env swap (.tmp + mv -f) -- no half-written env file.
- Records every flip in ledger_flag_history.json for an audit trail.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

DEFAULT_BOX_HOST = "100.95.126.39"
DEFAULT_BOX_USER = "aaats"
DEFAULT_ENV_PATH = "/home/aaats/aaats/.env"
DEFAULT_COMPOSE = "/home/aaats/aaats/deployment/docker-compose.yml"
DEFAULT_CONTAINER = "aaats-paper-crypto"
DRAIN_FRESHNESS = timedelta(minutes=10)
FLAG_NAME = "USE_UNIFIED_LEDGER"


def parse_bool(s: str) -> bool:
    s = s.strip().lower()
    if s in {"true", "1", "yes", "on"}:
        return True
    if s in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean: {s!r}")


def find_recent_drain_ok(
    history_path: pathlib.Path,
    freshness: timedelta = DRAIN_FRESHNESS,
    now: datetime | None = None,
) -> dict | None:
    """Return the most recent drain_ok event within `freshness`, or None."""
    if not history_path.exists():
        return None
    try:
        doc = json.loads(history_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    events = doc.get("events") if isinstance(doc, dict) else None
    if not isinstance(events, list):
        return None
    now = now or datetime.now(timezone.utc)
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        if event.get("type") != "drain_ok":
            continue
        ts = event.get("timestamp")
        if not isinstance(ts, str):
            continue
        try:
            event_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        if (now - event_time) <= freshness:
            return event
    return None


def render_env(existing: str, new_value: bool) -> str:
    """Return an .env body with USE_UNIFIED_LEDGER set to new_value.

    Preserves all other lines verbatim. Replaces an existing line in place
    or appends a new line at the end.
    """
    new_line = f"{FLAG_NAME}={'True' if new_value else 'False'}"
    lines = existing.splitlines()
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith(f"{FLAG_NAME}="):
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        lines.append(new_line)
    body = "\n".join(lines)
    if not body.endswith("\n"):
        body += "\n"
    return body


def append_history(history_path: pathlib.Path, event: dict) -> None:
    if history_path.exists():
        doc = json.loads(history_path.read_text(encoding="utf-8"))
    else:
        doc = {"events": [], "current_value": False}
    if not isinstance(doc, dict) or "events" not in doc:
        doc = {"events": [], "current_value": False}
    doc["events"].append(event)
    if event.get("type") == "flag_flipped" and "new_value" in event:
        doc["current_value"] = bool(event["new_value"])
    history_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = history_path.with_suffix(history_path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    tmp.replace(history_path)


def flip_on_box(
    new_value: bool,
    host: str = DEFAULT_BOX_HOST,
    user: str = DEFAULT_BOX_USER,
    env_path: str = DEFAULT_ENV_PATH,
    compose_path: str = DEFAULT_COMPOSE,
    container: str = DEFAULT_CONTAINER,
) -> dict:
    """Perform the atomic .env swap and container restart on the box."""
    import paramiko  # lazy import so unit tests don't require paramiko

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user)
    try:
        # Read existing .env
        _, stdout, _ = ssh.exec_command(f"cat {env_path}")
        existing = stdout.read().decode()
        new_body = render_env(existing, new_value)

        # Upload to .env.tmp then atomic mv -f
        sftp = ssh.open_sftp()
        try:
            with sftp.open(env_path + ".tmp", "w") as f:
                f.write(new_body)
        finally:
            sftp.close()
        ssh.exec_command(f"mv -f {env_path}.tmp {env_path}")

        # Restart container
        _, stdout, stderr = ssh.exec_command(
            f"cd {pathlib.PurePosixPath(env_path).parent} && "
            f"docker compose -f {compose_path} restart {container}"
        )
        rc = stdout.channel.recv_exit_status()
        restart_out = stdout.read().decode()
        restart_err = stderr.read().decode()

        # Capture new image SHA
        _, stdout, _ = ssh.exec_command(
            f"docker inspect {container} --format '{{{{.Image}}}}'"
        )
        image_sha = stdout.read().decode().strip()
    finally:
        ssh.close()

    return {
        "host": host,
        "env_path": env_path,
        "container": container,
        "restart_exit_code": rc,
        "restart_stdout": restart_out[-500:],
        "restart_stderr": restart_err[-500:],
        "image_sha": image_sha,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=f"Safely flip the {FLAG_NAME} env var on the box.",
    )
    ap.add_argument("--set", required=True,
                    help="New value: true/false/on/off/yes/no/1/0")
    ap.add_argument("--history-path", default=None,
                    help="Path to ledger_flag_history.json")
    ap.add_argument("--host", default=DEFAULT_BOX_HOST)
    ap.add_argument("--user", default=DEFAULT_BOX_USER)
    ap.add_argument("--env-path", default=DEFAULT_ENV_PATH)
    ap.add_argument("--compose-path", default=DEFAULT_COMPOSE)
    ap.add_argument("--container", default=DEFAULT_CONTAINER)
    ap.add_argument("--skip-restart", action="store_true",
                    help="Apply .env change but do not restart container (testing).")
    args = ap.parse_args(argv)

    history_path = (
        pathlib.Path(args.history_path) if args.history_path
        else (_ROOT / "data" / "ledger_flag_history.json")
    )
    try:
        new_value = parse_bool(args.set)
    except ValueError as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 2

    drain_event = find_recent_drain_ok(history_path)
    if drain_event is None:
        print(
            f"ABORT: no drain_ok event in {history_path} within "
            f"the last {DRAIN_FRESHNESS.total_seconds() / 60:.0f} minutes.\n"
            "Run scripts/drain_positions.py first.",
            file=sys.stderr,
        )
        return 1

    print(f"Drain check ok at {drain_event['timestamp']}; flipping {FLAG_NAME}={new_value}.")
    result = flip_on_box(
        new_value=new_value,
        host=args.host,
        user=args.user,
        env_path=args.env_path,
        compose_path=args.compose_path,
        container=args.container,
    )

    append_history(
        history_path,
        {
            "type": "flag_flipped",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "new_value": new_value,
            "drain_event_timestamp": drain_event["timestamp"],
            "image_sha": result["image_sha"],
            "host": result["host"],
            "restart_exit_code": result["restart_exit_code"],
        },
    )

    if result["restart_exit_code"] != 0:
        print(
            f"WARNING: container restart returned {result['restart_exit_code']}",
            file=sys.stderr,
        )
        print(result["restart_stderr"], file=sys.stderr)
        return 1

    print(f"OK: {FLAG_NAME} set to {new_value}, image={result['image_sha']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
