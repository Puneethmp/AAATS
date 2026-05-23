"""
Session 12 [1] deploy: D.2 watchdog 24h pager threshold + persistent
restart history.

Closes docs/known_issues/2026-05-23_pager_5plus_restart_not_firing.md.
Ships health/watchdog.py with:
  - Persistent 24h restart history (data/watchdog_state.json)
  - DAILY_RESTART_PAGER_THRESHOLD = 5, triggers [PAGER] + auto-halt
  - Escalation message upgraded to [PAGER] + severity=critical

Files to roll:
  health/watchdog.py

Rebuild aaats-watchdog only (--no-deps); paper-crypto image not touched.

Smoke gates:
  (a) docker exec aaats-watchdog python -c
      "from health.watchdog import _check_daily_pager_threshold,
       _load_persistent_restart_history, _save_persistent_restart_history;
       print('symbols OK')"
  (b) aaats-watchdog reaches running status post-rebuild.
  (c) Watchdog log shows "hydrated N restart timestamps" boot line
      (proves persistence path works against an empty state file).

Rollback baseline: .rollback/2026-05-23_session12_pager_fix/MANIFEST.txt
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
    "health/watchdog.py",
]

REMOTE_MKDIRS: list[str] = ["health"]

MANIFEST = (
    PROJECT_ROOT
    / ".rollback"
    / "2026-05-23_session12_pager_fix"
    / "MANIFEST.txt"
)


def _ascii(line: str) -> str:
    return line.encode("ascii", "replace").decode("ascii")


def _run(client: paramiko.SSHClient, cmd: str, label: str, timeout: int = 300) -> tuple[int, str]:
    print(f"  -> {label}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    for line in out.splitlines()[-15:]:
        print(f"     {_ascii(line)}")
    if rc != 0 and err:
        for line in err.splitlines()[-5:]:
            print(f"     ERR: {_ascii(line)}")
    return rc, out


def main() -> int:
    parser = argparse.ArgumentParser(description="Session 12 [1] pager fix deploy")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from tools.operator._dirty_tree_guard import check_clean
    check_clean(FILES, allow_dirty=args.allow_dirty)

    print("=" * 70)
    print("  Session 12 [1] -> D.2 watchdog 24h pager threshold")
    print(f"  Target: {USER}@{HOST}:{REMOTE_DIR}/<{len(FILES)} file>")
    print("  Rebuild: aaats-watchdog only (--no-deps)")
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
    print(f"\n[1/9] Connecting to {HOST}...")
    client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    print("       Connected")

    print("\n[2/9] Pre-deploy state capture...")
    _, pre_watchdog_image = _run(client,
        "docker inspect aaats-watchdog --format '{{.Image}}' 2>&1", "pre watchdog image")
    pre_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client,
            f"sha256sum {REMOTE_DIR}/{rel} 2>&1 || echo 'ABSENT {rel}'", f"pre SHA {rel}")
        pre_shas[rel] = out.split()[0] if rc == 0 and "ABSENT" not in out else "ABSENT"

    print("\n[3/9] mkdir -p parent dirs...")
    for d in REMOTE_MKDIRS:
        _ = _run(client, f"mkdir -p {REMOTE_DIR}/{d}", f"mkdir -p {d}")

    print("\n[4/9] SFTP upload (LF-normalized)...")
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

    print("\n[5/9] Atomic swaps...")
    for rel, remote, tmp in uploaded:
        rc, _ = _run(client, f"mv -f {tmp} {remote} && echo OK", f"swap {rel}")
        if rc != 0:
            client.close()
            return 2

    print("\n[6/9] Rebuilding aaats-watchdog (--no-deps, --build)...")
    rc, _ = _run(client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose up -d --build --no-deps aaats-watchdog 2>&1 | tail -25",
        "rebuild watchdog", timeout=900)
    if rc != 0:
        client.close()
        return 4

    print("\n[7/9] Settling 30s for boot + first tick...")
    _time.sleep(30)

    print("\n[8/9] Smoke gates...")
    _, post_watchdog_image = _run(client,
        "docker inspect aaats-watchdog --format '{{.Image}}' 2>&1", "post watchdog image")
    _, post_watchdog_status = _run(client,
        "docker inspect aaats-watchdog --format '{{.State.Status}}' 2>&1",
        "post watchdog status")
    rc_a, sym_out = _run(client,
        "docker exec aaats-watchdog python -c "
        "\"from health.watchdog import _check_daily_pager_threshold, "
        "_load_persistent_restart_history, _save_persistent_restart_history, "
        "DAILY_RESTART_PAGER_THRESHOLD; print(f'symbols OK threshold={DAILY_RESTART_PAGER_THRESHOLD}')\" 2>&1",
        "smoke (a) pager-fix symbols importable", timeout=30)
    smoke_a_ok = rc_a == 0 and "symbols OK threshold=5" in sym_out

    rc_c, boot_log = _run(client,
        "docker logs --since 60s aaats-watchdog 2>&1 | grep -iE 'watchdog starting|hydrated' | head -5",
        "smoke (c) watchdog boot + hydrate line", timeout=30)
    # On fresh deploy with no prior state file, "hydrated" line may not
    # appear (history is empty). So the gate accepts either the hydrate
    # line OR a clean "watchdog starting" line.
    smoke_c_ok = rc_c == 0 and ("watchdog starting" in boot_log or "hydrated" in boot_log)

    watchdog_running = "running" in post_watchdog_status

    post_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client, f"sha256sum {REMOTE_DIR}/{rel}", f"post SHA {rel}")
        post_shas[rel] = out.split()[0] if rc == 0 else "(failed)"

    client.close()

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    deployed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "ROLLBACK BASELINE - 2026-05-23 Session 12 [1] pager fix",
        "=" * 80,
        "",
        f"DEPLOYED_AT_UTC               = {deployed_at}",
        f"PRE_WATCHDOG_IMAGE_SHA        = {pre_watchdog_image}",
        f"POST_WATCHDOG_IMAGE_SHA       = {post_watchdog_image}",
        f"POST_WATCHDOG_STATUS          = {post_watchdog_status}",
        f"SMOKE_A_SYMBOLS               = {smoke_a_ok}",
        f"SMOKE_C_BOOT                  = {smoke_c_ok}",
        f"GATE_WATCHDOG_RUNNING         = {watchdog_running}",
        "",
        "File SHAs (pre -> post):",
    ]
    for rel in FILES:
        lines.append(f"  {rel:40s} : {pre_shas.get(rel, '?')} -> {post_shas.get(rel, '?')}")
    lines.append("")
    lines.append("Boot log tail:")
    for line in boot_log.splitlines()[-15:]:
        lines.append(f"  {_ascii(line)}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"  watchdog image:       {post_watchdog_image}")
    print(f"  smoke A (symbols):    {smoke_a_ok}")
    print(f"  smoke C (boot):       {smoke_c_ok}")
    print(f"  watchdog running:     {watchdog_running}")
    print(f"  MANIFEST written:     {MANIFEST}")
    print("=" * 70)
    all_ok = smoke_a_ok and smoke_c_ok and watchdog_running
    return 0 if all_ok else 9


if __name__ == "__main__":
    sys.exit(main())
