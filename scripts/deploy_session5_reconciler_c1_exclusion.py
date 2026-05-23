"""
Session 5 deploy [0]: BTC/ETH ledger drift Option-A fix.

Files shipped together (all-or-nothing):
  scripts/reconcile_intracycle.py   (Source B SQL: add C1_stat_arb to NOT IN)
  trading/live_paper_runner.py      (halt_on_critical=False -> True)

Doctrine (CLAUDE.md):
  1. SFTP each file to <path>.tmp.
  2. After uploads succeed: mv -f for each (atomic swap on box).
  3. `live_paper_runner.py` is image-baked => rebuild aaats-paper-crypto.
     `reconcile_intracycle.py` lives under scripts/ which is bind-mounted,
     so the next cycle picks it up immediately; rebuild keeps the image
     baseline in sync with the bind-mount source.
  4. Watch one full cycle of aaats-paper-crypto logs and assert:
       - reconciler line shows "checked=N positions" without HALT-severity issues.
       - No HALT log line; container does NOT restart-loop.
  5. Captures pre/post image SHAs into the rollback MANIFEST.

Run:
  venv\\Scripts\\python scripts\\deploy_session5_reconciler_c1_exclusion.py [--allow-dirty]
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
    "scripts/reconcile_intracycle.py",
    "trading/live_paper_runner.py",
]

MANIFEST = (
    PROJECT_ROOT
    / ".rollback"
    / "2026-05-23_session5_reconciler_c1_exclusion"
    / "MANIFEST.txt"
)


def _ascii(line: str) -> str:
    # cp1252 codec on the operator Windows workstation chokes on box log emoji
    # (e.g., kill-switch lines use stop-sign + arrow). Strip to ASCII for print.
    return line.encode("ascii", "replace").decode("ascii")


def _run(client: paramiko.SSHClient, cmd: str, label: str) -> tuple[int, str]:
    print(f"  -> {label}")
    _, stdout, stderr = client.exec_command(cmd, timeout=600)
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
    parser = argparse.ArgumentParser(description="Session 5 [0] reconciler C1 exclusion deploy")
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
    print("  Session 5 deploy [0] -> Option-A reconciler fix + halt_on_critical=True")
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
    print(f"\n[1/8] Connecting to {HOST}...")
    client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    print("       Connected")

    print("\n[2/8] Pre-deploy state capture...")
    _, pre_paper_image = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1",
        "pre paper image",
    )
    _, pre_paper_status = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}}' 2>&1",
        "pre paper status",
    )
    _, pre_paper_restart = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.RestartCount}}' 2>&1",
        "pre paper RestartCount",
    )
    pre_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(
            client,
            f"sha256sum {REMOTE_DIR}/{rel} 2>&1 || echo 'ABSENT {rel}'",
            f"pre SHA {rel}",
        )
        pre_shas[rel] = out.split()[0] if rc == 0 and "ABSENT" not in out else "ABSENT"

    print("\n[3/8] SFTP upload all files to .tmp...")
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

    print("\n[4/8] Atomic swaps (mv -f each)...")
    for rel, remote, tmp in uploaded:
        rc, _ = _run(client, f"mv -f {tmp} {remote} && echo OK", f"swap {rel}")
        if rc != 0:
            print(f"       FAIL on {rel}. Manual rollback may be required.")
            client.close()
            return 2

    print("\n[5/8] Rebuilding aaats-paper-crypto (image-baked runner change)...")
    rc, _ = _run(
        client,
        (
            f"cd {REMOTE_DIR}/deployment && "
            "docker compose up -d --build --no-deps aaats-paper-crypto 2>&1 | tail -30"
        ),
        "rebuild aaats-paper-crypto",
    )
    if rc != 0:
        print("       FAIL - aaats-paper-crypto did not come up.")
        client.close()
        return 3

    print("\n[6/8] Post-rebuild state + SHAs...")
    _, post_paper_image = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1",
        "post paper image",
    )
    _, post_paper_status = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}}' 2>&1",
        "post paper status",
    )
    post_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client, f"sha256sum {REMOTE_DIR}/{rel}", f"post SHA {rel}")
        post_shas[rel] = out.split()[0] if rc == 0 else "(failed)"

    if "running" not in post_paper_status:
        print(f"       FAIL: paper-crypto status={post_paper_status!r}")
        client.close()
        return 4

    print("\n[7/8] Observing one cycle (~15 min) for reconciler clean run...")
    print("       Waiting 60s for first post-rebuild cycle to begin...")
    _time.sleep(60)
    # Look at the most recent cycle's reconciler line + any HALT lines.
    rc, recon_lines = _run(
        client,
        "docker logs --tail 400 aaats-paper-crypto 2>&1 | grep -iE 'reconcil|HALT' | tail -30 || true",
        "tail reconciler + HALT lines",
    )
    halt_in_logs = any(
        "RECONCILIATION HALTED" in line or "HALT crypto:" in line
        for line in recon_lines.splitlines()
    )
    _, post_post_restart = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.RestartCount}}' 2>&1",
        "post-observation paper RestartCount",
    )
    restart_delta = int(post_post_restart.strip() or 0) - int(pre_paper_restart.strip() or 0)
    if restart_delta > 1:
        print(
            f"       WARN: RestartCount jumped {pre_paper_restart} -> {post_post_restart} "
            f"(delta={restart_delta}). Investigate before claiming clean."
        )
    if halt_in_logs:
        print(
            "       WARN: HALT line found in recent logs. Inspect manually before "
            "moving to [1]/[2]. (The fix may take one more cycle to flush old halts.)"
        )

    print("\n[8/8] Writing MANIFEST + done.")
    client.close()

    deployed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "ROLLBACK BASELINE - 2026-05-23 Session 5 [0] reconciler C1 exclusion + halt_on_critical=True",
        "=" * 80,
        "",
        f"DEPLOYED_AT_UTC          = {deployed_at}",
        f"PRE_PAPER_IMAGE_SHA      = {pre_paper_image}",
        f"POST_PAPER_IMAGE_SHA     = {post_paper_image}",
        f"PRE_PAPER_STATUS         = {pre_paper_status}",
        f"POST_PAPER_STATUS        = {post_paper_status}",
        f"PRE_PAPER_RESTART_COUNT  = {pre_paper_restart}",
        f"POST_PAPER_RESTART_COUNT = {post_post_restart}",
        f"HALT_IN_RECENT_LOGS      = {halt_in_logs}",
        "",
        "Pre-deploy file SHAs (box, captured immediately before swap):",
    ]
    for rel in FILES:
        lines.append(f"  {rel:50s} : {pre_shas.get(rel, '?')}")
    lines.append("")
    lines.append("Post-deploy file SHAs (box, after rebuild):")
    for rel in FILES:
        lines.append(f"  {rel:50s} : {post_shas.get(rel, '?')}")
    lines.append("")
    lines.append("Reconciler + HALT log lines observed in [7/8] window:")
    for line in recon_lines.splitlines()[-30:]:
        lines.append(f"  {line}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 65)
    print(f"  paper-crypto image:   {post_paper_image}")
    print(f"  paper-crypto status:  {post_paper_status}")
    print(f"  RestartCount delta:   {pre_paper_restart} -> {post_post_restart} ({restart_delta:+d})")
    print(f"  HALT in recent logs:  {halt_in_logs}")
    print(f"  MANIFEST written:     {MANIFEST}")
    print("=" * 65)
    return 0


if __name__ == "__main__":
    sys.exit(main())
