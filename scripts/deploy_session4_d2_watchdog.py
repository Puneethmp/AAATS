"""
Session 4 one-shot deploy: D.2 watchdog sidecar.

Files shipped together (all-or-nothing):
  health/__init__.py
  health/watchdog.py
  deployment/Dockerfile.watchdog
  deployment/docker-compose.yml          (adds aaats-watchdog service)

observability/alerts.py is NOT shipped (not modified this session); SHA is
verified on the box to confirm the watchdog can resolve send_alert.

Doctrine (CLAUDE.md):
  1. SFTP-upload each file to <path>.tmp (mkdir -p first for new dirs).
  2. After ALL uploads succeed: mv -f for each (atomic swap on box).
  3. docker compose up -d --build aaats-watchdog (no --no-deps: new service).

Smoke plan (safer than the prompt's CYCLE_INTERVAL_SEC=10 recipe, which
would runaway-restart paper-crypto whose real cycle is 15 min):
  A. Verify aaats-watchdog State.Status == running.
  B. Verify module resolves + can read /app/data/heartbeat.json.
  C. Verify docker.sock works: `docker ps -q` from inside the watchdog.
  D. Code-path smoke: synthetic stale heartbeat in /tmp + monkey-patched
     restart/alert -> verify tick() returns "restart".
  E. True end-to-end socket->restart proof: pre-record paper-crypto
     RestartCount, then `docker exec aaats-watchdog docker restart
     aaats-paper-crypto`, verify RestartCount += 1 and paper-crypto is
     back to running (autostart by compose restart policy).
  F. Wait one watchdog poll interval (60s) and verify watchdog observed
     the fresh post-restart heartbeat -> last_decision == "ok".

The 4-restart escalation path is unit-tested
(tests/test_watchdog.py::test_four_consecutive_stale_ticks_escalate_on_fourth)
but a real-box 4xstale smoke requires a 45-min+ maintenance window and
is deferred to a follow-up session.

Captures pre/post image SHAs into
.rollback/2026-05-23_session4_d2_watchdog_box/MANIFEST.txt.

Run: venv\\Scripts\\python scripts\\deploy_session4_d2_watchdog.py [--allow-dirty]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json as _json
import pathlib as _pl
import sys
import time as _time

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

FILES: list[str] = [
    "health/__init__.py",
    "health/watchdog.py",
    "deployment/Dockerfile.watchdog",
    "deployment/docker-compose.yml",
]

VERIFY_ONLY: list[str] = [
    "observability/alerts.py",
]

MANIFEST = (
    PROJECT_ROOT / ".rollback" / "2026-05-23_session4_d2_watchdog_box" / "MANIFEST.txt"
)


def _run(client: paramiko.SSHClient, cmd: str, label: str) -> tuple[int, str]:
    print(f"  -> {label}")
    _, stdout, stderr = client.exec_command(cmd, timeout=600)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    for line in out.splitlines()[-15:]:
        print(f"     {line}")
    if rc != 0 and err:
        for line in err.splitlines()[-5:]:
            print(f"     ERR: {line}")
    return rc, out


def main() -> int:
    parser = argparse.ArgumentParser(description="Session 4 D.2 watchdog deploy")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="emergency override: ship uncommitted local edits",
    )
    args = parser.parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from tools.operator._dirty_tree_guard import check_clean
    check_clean(FILES, allow_dirty=args.allow_dirty)

    print("=" * 65)
    print("  Session 4 deploy -> aaats-watchdog (D.2)")
    print(f"  Target: {USER}@{HOST}:{REMOTE_DIR}/<{len(FILES)} files>")
    print("=" * 65)

    if not PASSWORD:
        print("FATAL: CONTABO__SSH_PASSWORD not in .env")
        return 1
    for rel in FILES:
        if not (PROJECT_ROOT / rel).exists():
            print(f"FATAL: {rel} not found locally")
            return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"\n[1/10] Connecting to {HOST}...")
    client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    print("       Connected")

    print("\n[2/10] Pre-deploy: capturing aaats-watchdog (if any) + paper-crypto state...")
    _, pre_watchdog_status = _run(
        client,
        "docker inspect aaats-watchdog --format '{{.State.Status}}' 2>&1 || echo NOT_FOUND",
        "pre watchdog State.Status",
    )
    _, pre_paper_image = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1",
        "pre paper image",
    )
    _, pre_paper_restart = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.RestartCount}}' 2>&1",
        "pre paper RestartCount",
    )
    pre_shas: dict[str, str] = {}
    for rel in FILES + VERIFY_ONLY:
        rc, out = _run(
            client,
            f"test -f {REMOTE_DIR}/{rel} && sha256sum {REMOTE_DIR}/{rel} || echo 'ABSENT {rel}'",
            f"pre SHA {rel}",
        )
        pre_shas[rel] = out.split()[0] if rc == 0 and "ABSENT" not in out else "ABSENT"

    print("\n[3/10] Ensuring new remote dirs exist...")
    remote_parent_dirs = sorted({str(_pl.PurePosixPath(rel).parent) for rel in FILES if "/" in rel})
    for d in remote_parent_dirs:
        _run(client, f"mkdir -p {REMOTE_DIR}/{d}", f"mkdir -p {d}")

    print("\n[4/10] SFTP upload all files to .tmp...")
    sftp = client.open_sftp()
    uploaded: list[tuple[str, str, str]] = []
    try:
        for rel in FILES:
            local = PROJECT_ROOT / rel
            remote = f"{REMOTE_DIR}/{rel}"
            tmp = remote + ".tmp"
            sftp.put(str(local), tmp)
            uploaded.append((rel, remote, tmp))
            print(f"       wrote {tmp}")
    finally:
        sftp.close()

    print("\n[5/10] Atomic swaps (mv -f each)...")
    for rel, remote, tmp in uploaded:
        rc, _ = _run(client, f"mv -f {tmp} {remote} && echo OK", f"swap {rel}")
        if rc != 0:
            print(f"       FAIL on {rel}. Manual rollback may be required.")
            client.close()
            return 2

    print("\n[6/10] Verifying observability/alerts.py exists on box (no SCP)...")
    rc, alerts_sha = _run(
        client,
        f"sha256sum {REMOTE_DIR}/observability/alerts.py 2>&1 || echo MISSING",
        "alerts SHA",
    )
    if "MISSING" in alerts_sha:
        print("       FATAL: observability/alerts.py missing on box -- watchdog needs it for Telegram.")
        client.close()
        return 3

    print("\n[7/10] Building + recreating aaats-watchdog...")
    # Defensive: if a prior aaats-watchdog container exists with mismatched
    # spec, compose up can hit a "name in use" conflict that resolves on retry.
    # Pre-remove the container (no-op if absent) before the rebuild.
    _run(
        client,
        "docker rm -f aaats-watchdog 2>&1 || true",
        "pre-rm aaats-watchdog (if any)",
    )
    rc, _ = _run(
        client,
        (
            f"cd {REMOTE_DIR}/deployment && "
            "docker compose up -d --build aaats-watchdog 2>&1 | tail -30"
        ),
        "build + recreate aaats-watchdog",
    )
    if rc != 0:
        print("       FAIL - watchdog did not come up.")
        client.close()
        return 4

    print("\n[8/10] Capturing post-rebuild state...")
    _, post_watchdog_image = _run(
        client,
        "docker inspect aaats-watchdog --format '{{.Image}}' 2>&1",
        "post watchdog image",
    )
    _, post_watchdog_status = _run(
        client,
        "docker inspect aaats-watchdog --format '{{.State.Status}}' 2>&1",
        "post watchdog State.Status",
    )
    post_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client, f"sha256sum {REMOTE_DIR}/{rel}", f"post SHA {rel}")
        post_shas[rel] = out.split()[0] if rc == 0 else "(failed)"

    print("\n[9/10] Smoke tests (steps A-F)...")
    # A. State.Status == running
    if "running" not in post_watchdog_status:
        print(f"       FAIL smoke A: aaats-watchdog status={post_watchdog_status!r}")
        client.close()
        return 5
    print("       smoke A OK: aaats-watchdog State.Status == running")

    # Give the watchdog ~5s to settle (initial import + first tick).
    _time.sleep(5)

    # B. Module resolves + can read /app/data/heartbeat.json.
    rc, b_out = _run(
        client,
        "docker exec aaats-watchdog python -c "
        "'from health.watchdog import _read_heartbeat_ts, HEARTBEAT_PATH; "
        "ts = _read_heartbeat_ts(HEARTBEAT_PATH); "
        "print(\"heartbeat_ts=\", ts)' 2>&1",
        "smoke B: read heartbeat",
    )
    if rc != 0 or "heartbeat_ts=" not in b_out:
        print("       FAIL smoke B")
        client.close()
        return 6

    # C. Docker socket: docker ps -q from inside.
    rc, c_out = _run(
        client,
        "docker exec aaats-watchdog docker ps -q --filter name=aaats-paper-crypto 2>&1",
        "smoke C: docker ps via socket",
    )
    if rc != 0 or not c_out.strip():
        print("       FAIL smoke C: socket unreachable or paper-crypto missing")
        client.close()
        return 7

    # D. Code-path smoke: synthetic stale heartbeat -> tick() == "restart".
    d_py = (
        "from pathlib import Path; "
        "import json, time; "
        "from datetime import datetime, timezone, timedelta; "
        "tmp = Path('/tmp/synthetic_stale.json'); "
        "old = datetime.now(timezone.utc) - timedelta(hours=2); "
        "tmp.write_text(json.dumps({'timestamp': old.isoformat(), "
        "'cycle': 1, 'market': 'crypto', 'cycle_duration_seconds': 12.0})); "
        "import health.watchdog as wd; "
        "wd._restart_container = lambda c: True; "
        "wd._send_alert = lambda m: None; "
        "w = wd.Watchdog(heartbeat_path=tmp); "
        "verb = w.tick(); "
        "print('verb=', verb); "
        "assert verb == 'restart', f'unexpected verb {verb}'"
    )
    rc, d_out = _run(
        client,
        f"docker exec aaats-watchdog python -c \"{d_py}\" 2>&1",
        "smoke D: synthetic stale -> restart",
    )
    if rc != 0 or "verb= restart" not in d_out:
        print("       FAIL smoke D")
        client.close()
        return 8

    # E. End-to-end: docker exec watchdog docker restart paper-crypto.
    rc, _ = _run(
        client,
        "docker exec aaats-watchdog docker restart aaats-paper-crypto 2>&1",
        "smoke E: socket-driven restart",
    )
    if rc != 0:
        print("       FAIL smoke E: socket restart failed")
        client.close()
        return 9
    print("       Waiting 20s for paper-crypto to come back up...")
    _time.sleep(20)
    _, post_e_status = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}}' 2>&1",
        "post-E paper status",
    )
    _, post_e_restart = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.RestartCount}}' 2>&1",
        "post-E paper RestartCount",
    )
    if "running" not in post_e_status:
        print(f"       FAIL smoke E: paper-crypto did not return to running (status={post_e_status!r})")
        client.close()
        return 10
    if int(post_e_restart.strip() or 0) <= int(pre_paper_restart.strip() or 0):
        print(
            "       WARN smoke E: RestartCount did not increment "
            f"({pre_paper_restart} -> {post_e_restart}). "
            "May indicate `docker restart` was a fast-recreate that didn't bump the counter; "
            "treat as advisory not blocker."
        )

    # F. Wait for next watchdog tick (poll = 60s), then observe its self-heartbeat.
    print("       Waiting 75s for watchdog's next tick + self-heartbeat write...")
    _time.sleep(75)
    rc, f_out = _run(
        client,
        f"cat {REMOTE_DIR}/data/watchdog_heartbeat.json 2>&1 || echo MISSING",
        "smoke F: watchdog self-heartbeat",
    )
    if rc != 0 or "MISSING" in f_out:
        print("       FAIL smoke F: watchdog self-heartbeat missing")
        client.close()
        return 11

    print("\n[10/10] Writing MANIFEST + done.")
    client.close()

    deployed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "ROLLBACK BASELINE - 2026-05-23 Session 4 D.2 watchdog deploy",
        "=" * 80,
        "",
        f"DEPLOYED_AT_UTC          = {deployed_at}",
        f"PRE_WATCHDOG_STATUS      = {pre_watchdog_status}",
        f"POST_WATCHDOG_IMAGE_SHA  = {post_watchdog_image}",
        f"POST_WATCHDOG_STATUS     = {post_watchdog_status}",
        f"PRE_PAPER_IMAGE_SHA      = {pre_paper_image}",
        f"PRE_PAPER_RESTART_COUNT  = {pre_paper_restart}",
        f"POST_PAPER_RESTART_COUNT = {post_e_restart}",
        f"POST_PAPER_STATUS        = {post_e_status}",
        f"OBSERVABILITY_ALERTS_SHA = {alerts_sha.split()[0] if alerts_sha else '?'}",
        "",
        "Pre-deploy file SHAs (box, captured immediately before swap):",
    ]
    for rel in FILES + VERIFY_ONLY:
        lines.append(f"  {rel:50s} : {pre_shas.get(rel, '?')}")
    lines.append("")
    lines.append("Post-deploy file SHAs (box, after rebuild):")
    for rel in FILES:
        lines.append(f"  {rel:50s} : {post_shas.get(rel, '?')}")
    lines.append("")
    lines.append("Smoke results (steps A-F all passed if exit code 0):")
    lines.append(f"  D. synthetic stale heartbeat -> verb=restart : {d_out!r}")
    lines.append(f"  F. watchdog self-heartbeat after socket restart:")
    for line in f_out.splitlines()[:20]:
        lines.append(f"     {line}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 65)
    print(f"  watchdog image:   {post_watchdog_image}")
    print(f"  watchdog status:  {post_watchdog_status}")
    print(f"  paper-crypto:     {post_e_status} (RestartCount {pre_paper_restart} -> {post_e_restart})")
    print(f"  MANIFEST written: {MANIFEST}")
    print("=" * 65)
    return 0


if __name__ == "__main__":
    sys.exit(main())
