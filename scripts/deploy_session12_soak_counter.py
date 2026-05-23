"""
Session 12 deploy: D.5 soak counter + anomaly-window logic.

Ships the counter from monitoring/daily_digest.py changes (compute_soak_counter,
enforce_anomaly_window_state, render_soak_counter_row, _mark_digest_sent
action_needed capture) AND backfills the d5_day1_marker.json with the
2026-05-23T13:29-15:07 phantom-ENA anomaly window so the running soak
gets its full counter credit.

Files to roll:
  monitoring/daily_digest.py        (counter + anomaly-window functions)

Marker mutation on box (in place; no file from the workstation):
  data/d5_day1_marker.json — add anomaly_windows list with the
  phantom-ENA crash-loop window backfilled.

Rebuild aaats-paper-crypto + aaats-watchdog --no-deps (both import the
module).

Smoke gates:
  (a) docker exec aaats-paper-crypto python -c
      "from monitoring.daily_digest import compute_soak_counter; print(compute_soak_counter)"
      returns function.
  (b) docker exec aaats-paper-crypto python -c
      "import json; m=json.load(open('/app/data/d5_day1_marker.json'));
       print(m.get('anomaly_windows'))"
      returns the backfilled window list.
  (c) docker exec aaats-watchdog python -m monitoring.daily_digest --dry-run
      renders the new "Soak day N ..." line.

Rollback baseline: .rollback/2026-05-23_session12_soak_counter/MANIFEST.txt
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
    "monitoring/daily_digest.py",
]

REMOTE_MKDIRS: list[str] = ["monitoring"]

MANIFEST = (
    PROJECT_ROOT
    / ".rollback"
    / "2026-05-23_session12_soak_counter"
    / "MANIFEST.txt"
)

# Phantom-ENA anomaly window (per session 11 hotfix).
ANOMALY_WINDOW = {
    "start": "2026-05-23T13:29:44+00:00",   # phantom ENA strategy-state write
    "end":   "2026-05-23T15:07:46+00:00",   # first "Reconciliation clean" post-recovery
    "reason": "phantom_ena_crash_loop",
}


def _ascii(line: str) -> str:
    return line.encode("ascii", "replace").decode("ascii")


def _run(client: paramiko.SSHClient, cmd: str, label: str, timeout: int = 300) -> tuple[int, str]:
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
    parser = argparse.ArgumentParser(description="Session 12 D.5 soak counter deploy")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from tools.operator._dirty_tree_guard import check_clean
    check_clean(FILES, allow_dirty=args.allow_dirty)

    print("=" * 70)
    print("  Session 12 [0] -> D.5 soak counter + anomaly-window logic")
    print(f"  Target: {USER}@{HOST}:{REMOTE_DIR}/<{len(FILES)} file>")
    print("  Marker backfill: phantom_ena_crash_loop window")
    print("  Rebuild: aaats-paper-crypto + aaats-watchdog (--no-deps)")
    print("=" * 70)

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
    _, pre_marker = _run(client,
        f"cat {REMOTE_DIR}/data/d5_day1_marker.json", "pre d5_day1_marker.json")
    pre_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client,
            f"sha256sum {REMOTE_DIR}/{rel} 2>&1 || echo 'ABSENT {rel}'", f"pre SHA {rel}")
        pre_shas[rel] = out.split()[0] if rc == 0 and "ABSENT" not in out else "ABSENT"

    print("\n[3/10] mkdir -p parent dirs...")
    for d in REMOTE_MKDIRS:
        _ = _run(client, f"mkdir -p {REMOTE_DIR}/{d}", f"mkdir -p {d}")

    print("\n[4/10] SFTP upload (LF-normalized)...")
    sftp = client.open_sftp()
    uploaded: list[tuple[str, str, str]] = []
    try:
        for rel in FILES:
            local = PROJECT_ROOT / rel
            remote = f"{REMOTE_DIR}/{rel}"
            tmp = remote + ".tmp"
            content = local.read_text(encoding="utf-8").replace("\r\n", "\n")
            with sftp.open(tmp, "w") as fh:
                fh.write(content)
            uploaded.append((rel, remote, tmp))
            print(f"       wrote {tmp}")
    finally:
        sftp.close()

    print("\n[5/10] Atomic swaps...")
    for rel, remote, tmp in uploaded:
        rc, _ = _run(client, f"mv -f {tmp} {remote} && echo OK", f"swap {rel}")
        if rc != 0:
            client.close()
            return 2

    print("\n[6/10] Backfill d5_day1_marker.json with anomaly_windows...")
    # Read, mutate, atomically write back.
    try:
        marker = _json.loads(pre_marker)
    except _json.JSONDecodeError:
        print(f"       FATAL: pre-deploy marker JSON unparseable: {pre_marker[:200]}")
        client.close()
        return 3
    windows = list(marker.get("anomaly_windows", []) or [])
    already_have = any(
        isinstance(w, dict) and w.get("reason") == ANOMALY_WINDOW["reason"]
        for w in windows
    )
    if not already_have:
        windows.append(ANOMALY_WINDOW)
        marker["anomaly_windows"] = windows
        sftp = client.open_sftp()
        try:
            with sftp.open(f"{REMOTE_DIR}/data/d5_day1_marker.json.tmp", "w") as fh:
                fh.write(_json.dumps(marker, indent=2))
        finally:
            sftp.close()
        _run(client,
            f"mv -f {REMOTE_DIR}/data/d5_day1_marker.json.tmp "
            f"   {REMOTE_DIR}/data/d5_day1_marker.json",
            "atomic-swap d5_day1_marker.json")
    else:
        print("       NOOP: phantom_ena_crash_loop window already present")

    print("\n[7/10] Rebuilding paper-crypto + watchdog (--no-deps, --build)...")
    rc, _ = _run(client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose up -d --build --no-deps aaats-paper-crypto aaats-watchdog "
        "2>&1 | tail -25",
        "rebuild paper-crypto + watchdog", timeout=900)
    if rc != 0:
        client.close()
        return 4

    print("\n[8/10] Settling 40s...")
    _time.sleep(40)

    print("\n[9/10] Smoke gates...")
    _, post_paper_image = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1", "post paper image")
    _, post_watchdog_image = _run(client,
        "docker inspect aaats-watchdog --format '{{.Image}}' 2>&1", "post watchdog image")
    _, post_paper_status = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}} health={{.State.Health.Status}}' 2>&1",
        "post paper status")
    _, post_watchdog_status = _run(client,
        "docker inspect aaats-watchdog --format '{{.State.Status}}' 2>&1",
        "post watchdog status")

    rc_a, smoke_a_out = _run(client,
        "docker exec aaats-paper-crypto python -c "
        "\"from monitoring.daily_digest import compute_soak_counter, enforce_anomaly_window_state, render_soak_counter_row; "
        "print('counter symbols OK')\" 2>&1",
        "smoke (a) counter symbols importable", timeout=30)
    smoke_a_ok = rc_a == 0 and "counter symbols OK" in smoke_a_out

    rc_b, smoke_b_out = _run(client,
        "docker exec aaats-paper-crypto python -c "
        "\"import json; m=json.load(open('/app/data/d5_day1_marker.json')); "
        "print(json.dumps(m.get('anomaly_windows'), indent=2))\" 2>&1",
        "smoke (b) anomaly_windows backfilled in marker", timeout=30)
    smoke_b_ok = (rc_b == 0
                  and "phantom_ena_crash_loop" in smoke_b_out
                  and "2026-05-23T13:29:44" in smoke_b_out)

    rc_c, smoke_c_out = _run(client,
        "docker exec aaats-watchdog python -m monitoring.daily_digest --dry-run 2>&1 | tail -40",
        "smoke (c) digest renders Soak day row", timeout=120)
    smoke_c_ok = rc_c == 0 and "Soak day" in smoke_c_out

    paper_running = "running" in post_paper_status
    watchdog_running = "running" in post_watchdog_status

    post_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client, f"sha256sum {REMOTE_DIR}/{rel}", f"post SHA {rel}")
        post_shas[rel] = out.split()[0] if rc == 0 else "(failed)"

    client.close()

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    deployed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "ROLLBACK BASELINE - 2026-05-23 Session 12 [0] D.5 soak counter",
        "=" * 80,
        "",
        f"DEPLOYED_AT_UTC               = {deployed_at}",
        f"PRE_PAPER_IMAGE_SHA           = {pre_paper_image}",
        f"POST_PAPER_IMAGE_SHA          = {post_paper_image}",
        f"PRE_WATCHDOG_IMAGE_SHA        = {pre_watchdog_image}",
        f"POST_WATCHDOG_IMAGE_SHA       = {post_watchdog_image}",
        f"POST_PAPER_STATUS             = {post_paper_status}",
        f"POST_WATCHDOG_STATUS          = {post_watchdog_status}",
        f"SMOKE_A_COUNTER_SYMBOLS       = {smoke_a_ok}",
        f"SMOKE_B_MARKER_BACKFILLED     = {smoke_b_ok}",
        f"SMOKE_C_DIGEST_RENDERS_ROW    = {smoke_c_ok}",
        f"GATE_PAPER_RUNNING            = {paper_running}",
        f"GATE_WATCHDOG_RUNNING         = {watchdog_running}",
        "",
        "Pre-deploy marker:",
        f"  {_ascii(pre_marker)[:500]}",
        "",
        "Backfilled anomaly window:",
        f"  {_json.dumps(ANOMALY_WINDOW)}",
        "",
        "File SHAs (pre -> post):",
    ]
    for rel in FILES:
        lines.append(f"  {rel:40s} : {pre_shas.get(rel, '?')} -> {post_shas.get(rel, '?')}")
    lines.append("")
    lines.append("Smoke (c) digest dry-run tail:")
    for line in smoke_c_out.splitlines()[-30:]:
        lines.append(f"  {_ascii(line)}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"  paper-crypto image:    {post_paper_image}")
    print(f"  watchdog image:        {post_watchdog_image}")
    print(f"  smoke A (symbols):     {smoke_a_ok}")
    print(f"  smoke B (marker):      {smoke_b_ok}")
    print(f"  smoke C (digest row):  {smoke_c_ok}")
    print(f"  paper running:         {paper_running}")
    print(f"  watchdog running:      {watchdog_running}")
    print(f"  MANIFEST written:      {MANIFEST}")
    print("=" * 70)
    all_ok = smoke_a_ok and smoke_b_ok and smoke_c_ok and paper_running and watchdog_running
    return 0 if all_ok else 9


if __name__ == "__main__":
    sys.exit(main())
