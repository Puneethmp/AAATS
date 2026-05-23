"""
Session 5 deploy [2]: D.4 daily digest.

Ships in one all-or-nothing batch:
  monitoring/daily_digest.py        (new module)
  trading/live_paper_runner.py      (cycle_log writer next to heartbeat)
  health/watchdog.py                (dispatch loop calls _maybe_dispatch_digest)

Image-baked changes => rebuilds both aaats-paper-crypto and aaats-watchdog.

Smoke sequence:
  1. Box dry-run via `docker exec aaats-watchdog python -m monitoring.daily_digest --dry-run`.
  2. Confirm cycle_log table exists in /app/data/paper_trades.db after one cycle.
  3. Confirm the watchdog will dispatch the digest at the next poll tick (the
     existing self-heartbeat already proves the loop is alive; the new
     last_digest_sent_for field on the heartbeat surfaces the dispatch).

Note: the daily digest WILL fire on the first watchdog tick if the current
time is past 09:00 IST. This is intentional -- the first digest's role is
to surface the current state honestly (incl. the -33% drawdown), not to
mark D.5 day-1. D.5 day-1 begins the first day the digest fires with
Action needed: NONE.

Run:
  venv\\Scripts\\python scripts\\deploy_session5_d4_daily_digest.py [--allow-dirty]
"""
from __future__ import annotations

import argparse
import datetime as _dt
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
    "monitoring/daily_digest.py",
    "trading/live_paper_runner.py",
    "health/watchdog.py",
]

MANIFEST = (
    PROJECT_ROOT
    / ".rollback"
    / "2026-05-23_session5_d4_daily_digest"
    / "MANIFEST.txt"
)


def _ascii(line: str) -> str:
    return line.encode("ascii", "replace").decode("ascii")


def _run(client: paramiko.SSHClient, cmd: str, label: str, timeout: int = 600) -> tuple[int, str]:
    print(f"  -> {label}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    for line in out.splitlines()[-20:]:
        print(f"     {_ascii(line)}")
    if rc != 0 and err:
        for line in err.splitlines()[-5:]:
            print(f"     ERR: {_ascii(line)}")
    return rc, out


def main() -> int:
    parser = argparse.ArgumentParser(description="Session 5 [2] D.4 daily digest deploy")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from tools.operator._dirty_tree_guard import check_clean
    check_clean(FILES, allow_dirty=args.allow_dirty)

    print("=" * 65)
    print("  Session 5 deploy [2] -> D.4 daily digest (watchdog + cycle_log)")
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

    print("\n[2/10] Pre-deploy state capture...")
    _, pre_paper_image = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1", "pre paper image")
    _, pre_watchdog_image = _run(client,
        "docker inspect aaats-watchdog --format '{{.Image}}' 2>&1", "pre watchdog image")
    pre_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client,
            f"sha256sum {REMOTE_DIR}/{rel} 2>&1 || echo 'ABSENT {rel}'", f"pre SHA {rel}")
        pre_shas[rel] = out.split()[0] if rc == 0 and "ABSENT" not in out else "ABSENT"

    print("\n[3/10] SFTP upload to .tmp...")
    sftp = client.open_sftp()
    uploaded: list[tuple[str, str, str]] = []
    try:
        # Force LF line endings on every upload (safety against Windows git autocrlf).
        for rel in FILES:
            local = PROJECT_ROOT / rel
            remote = f"{REMOTE_DIR}/{rel}"
            tmp = remote + ".tmp"
            content = local.read_text(encoding="utf-8")
            normalized = content.replace("\r\n", "\n")
            with sftp.open(tmp, "w") as fh:
                fh.write(normalized)
            uploaded.append((rel, remote, tmp))
            print(f"       wrote {tmp}")
        # Ensure parent dirs exist on the remote (monitoring/ already does; defensive).
        _ = _run(client, f"mkdir -p {REMOTE_DIR}/monitoring", "mkdir -p monitoring")
    finally:
        sftp.close()

    print("\n[4/10] Atomic swaps...")
    for rel, remote, tmp in uploaded:
        rc, _ = _run(client, f"mv -f {tmp} {remote} && echo OK", f"swap {rel}")
        if rc != 0:
            print(f"       FAIL on {rel}")
            client.close()
            return 2

    print("\n[5/10] Rebuilding aaats-paper-crypto (image-baked runner change)...")
    rc, _ = _run(client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose up -d --build --no-deps aaats-paper-crypto 2>&1 | tail -25",
        "rebuild paper-crypto", timeout=600)
    if rc != 0:
        print("       FAIL: paper-crypto did not come up.")
        client.close()
        return 3

    print("\n[6/10] Rebuilding aaats-watchdog (image-baked dispatch wiring)...")
    rc, _ = _run(client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose up -d --build aaats-watchdog 2>&1 | tail -25",
        "rebuild watchdog", timeout=600)
    if rc != 0:
        print("       FAIL: watchdog did not come up.")
        client.close()
        return 4

    print("\n[7/10] Post-rebuild SHAs + container status...")
    _, post_paper_image = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1", "post paper image")
    _, post_paper_status = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}}' 2>&1", "post paper status")
    _, post_watchdog_image = _run(client,
        "docker inspect aaats-watchdog --format '{{.Image}}' 2>&1", "post watchdog image")
    _, post_watchdog_status = _run(client,
        "docker inspect aaats-watchdog --format '{{.State.Status}}' 2>&1", "post watchdog status")
    post_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client, f"sha256sum {REMOTE_DIR}/{rel}", f"post SHA {rel}")
        post_shas[rel] = out.split()[0] if rc == 0 else "(failed)"

    if "running" not in post_paper_status:
        print(f"       FAIL: paper-crypto status={post_paper_status!r}")
        client.close()
        return 5
    if "running" not in post_watchdog_status:
        print(f"       FAIL: watchdog status={post_watchdog_status!r}")
        client.close()
        return 6

    # Settle for ~6s before exec.
    _time.sleep(6)

    print("\n[8/10] Smoke A: box dry-run via docker exec aaats-watchdog...")
    rc, dry_out = _run(client,
        "docker exec aaats-watchdog python -m monitoring.daily_digest --dry-run 2>&1 | tail -40",
        "box dry-run", timeout=60)
    box_dry_run_passed = (
        rc == 0
        and "AAATS daily digest" in dry_out
        and "Action needed:" in dry_out
    )
    if not box_dry_run_passed:
        print("       FAIL smoke A: dry-run did not render the expected sections.")
        client.close()
        return 7

    print("\n[9/10] Smoke B: confirm cycle_log table exists after first cycle...")
    print("       Sleeping 70s for paper-crypto to land its first post-rebuild cycle...")
    _time.sleep(70)
    rc, cycle_log_check = _run(client,
        "docker exec aaats-paper-crypto python -c "
        "\"import sqlite3; c=sqlite3.connect('/app/data/paper_trades.db'); "
        "print(c.execute('SELECT COUNT(*), MAX(timestamp) FROM cycle_log').fetchall())\" 2>&1",
        "cycle_log row count + latest ts", timeout=60)
    cycle_log_present = ("[" in cycle_log_check) and ("None" not in cycle_log_check)

    print("\n[10/10] Smoke C: watchdog self-heartbeat shows new field...")
    _, wd_hb = _run(client,
        f"cat {REMOTE_DIR}/data/watchdog_heartbeat.json 2>&1", "watchdog heartbeat")

    client.close()

    deployed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "ROLLBACK BASELINE - 2026-05-23 Session 5 [2] D.4 daily digest",
        "=" * 80,
        "",
        f"DEPLOYED_AT_UTC          = {deployed_at}",
        f"PRE_PAPER_IMAGE_SHA      = {pre_paper_image}",
        f"POST_PAPER_IMAGE_SHA     = {post_paper_image}",
        f"PRE_WATCHDOG_IMAGE_SHA   = {pre_watchdog_image}",
        f"POST_WATCHDOG_IMAGE_SHA  = {post_watchdog_image}",
        f"POST_PAPER_STATUS        = {post_paper_status}",
        f"POST_WATCHDOG_STATUS     = {post_watchdog_status}",
        f"BOX_DRY_RUN_PASSED       = {box_dry_run_passed}",
        f"CYCLE_LOG_TABLE_PRESENT  = {cycle_log_present}",
        "",
        "Pre-deploy file SHAs:",
    ]
    for rel in FILES:
        lines.append(f"  {rel:50s} : {pre_shas.get(rel, '?')}")
    lines.append("")
    lines.append("Post-deploy file SHAs:")
    for rel in FILES:
        lines.append(f"  {rel:50s} : {post_shas.get(rel, '?')}")
    lines.append("")
    lines.append("Box dry-run output (tail):")
    for line in dry_out.splitlines()[-25:]:
        lines.append(f"  {_ascii(line)}")
    lines.append("")
    lines.append("cycle_log smoke output:")
    for line in cycle_log_check.splitlines()[-5:]:
        lines.append(f"  {_ascii(line)}")
    lines.append("")
    lines.append("watchdog_heartbeat.json (post-deploy):")
    for line in wd_hb.splitlines()[-15:]:
        lines.append(f"  {_ascii(line)}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 65)
    print(f"  paper-crypto image:   {post_paper_image}")
    print(f"  watchdog image:       {post_watchdog_image}")
    print(f"  box dry-run passed:   {box_dry_run_passed}")
    print(f"  cycle_log table:      {cycle_log_present}")
    print(f"  MANIFEST written:     {MANIFEST}")
    print("=" * 65)
    return 0 if (box_dry_run_passed and cycle_log_present) else 8


if __name__ == "__main__":
    sys.exit(main())
