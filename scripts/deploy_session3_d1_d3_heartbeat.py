"""
Session 3 one-shot deploy: D.1 + D.3 + heartbeat-reader fix.

Files shipped together (all-or-nothing):
  monitoring/heartbeat_monitor.py            (catalog row 1 — flat reader)
  monitoring/metrics_exporter.py             (D.1 strategy_exception counter)
  trading/live_paper_runner.py               (D.1 dispatch + D.3 startup smoke)
  trading/strategy_isolation.py              (D.1 new helper)
  risk/strategy_halt.py                      (D.1 new per-strategy halt)
  state/__init__.py                          (D.3 new tree)
  state/schemas.py                           (D.3 new tree)

Doctrine (CLAUDE.md):
  1. SFTP-upload each file to <path>.tmp (mkdir -p first for new dirs).
  2. After ALL uploads succeed: mv -f for each (atomic swap on box).
  3. docker compose up -d --build --no-deps aaats-paper-crypto.

Captures pre/post image SHAs into
.rollback/2026-05-22_session3_d1_d3_heartbeat_box/MANIFEST.txt.

Run: venv\\Scripts\\python scripts\\deploy_session3_d1_d3_heartbeat.py [--allow-dirty]
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

# Each entry: (local rel path, set of remote parent dirs that must exist)
FILES: list[str] = [
    "monitoring/heartbeat_monitor.py",
    "monitoring/metrics_exporter.py",
    "trading/live_paper_runner.py",
    "trading/strategy_isolation.py",
    "risk/strategy_halt.py",
    "state/__init__.py",
    "state/schemas.py",
]

MANIFEST = (
    PROJECT_ROOT / ".rollback" / "2026-05-22_session3_d1_d3_heartbeat_box" / "MANIFEST.txt"
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
    parser = argparse.ArgumentParser(description="Session 3 D.1 + D.3 + heartbeat deploy")
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
    print("  Session 3 deploy -> aaats-paper-crypto")
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

    print("\n[2/8] Capturing pre-rebuild state + pre-deploy SHAs...")
    _, pre_image = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1",
        "pre image",
    )
    _, pre_restart = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.RestartCount}}' 2>&1",
        "pre RestartCount",
    )
    pre_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(
            client,
            f"test -f {REMOTE_DIR}/{rel} && sha256sum {REMOTE_DIR}/{rel} || echo 'ABSENT {rel}'",
            f"pre SHA {rel}",
        )
        pre_shas[rel] = out.split()[0] if rc == 0 and "ABSENT" not in out else "ABSENT"

    print("\n[3/8] Ensuring new remote dirs exist (state/, etc)...")
    remote_parent_dirs = sorted({str(_pl.PurePosixPath(rel).parent) for rel in FILES if "/" in rel})
    for d in remote_parent_dirs:
        _run(
            client,
            f"mkdir -p {REMOTE_DIR}/{d}",
            f"mkdir -p {d}",
        )

    print("\n[4/8] SFTP upload all files to .tmp...")
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

    print("\n[5/8] Atomic swaps (mv -f each)...")
    swapped: list[tuple[str, str, str]] = []
    for rel, remote, tmp in uploaded:
        rc, _ = _run(client, f"mv -f {tmp} {remote} && echo OK", f"swap {rel}")
        if rc != 0:
            print(f"       FAIL on {rel} after {len(swapped)} successful swaps.")
            print("       Manual rollback may be required from pre_shas.")
            client.close()
            return 2
        swapped.append((rel, remote, tmp))

    print("\n[6/8] Rebuilding aaats-paper-crypto (no-deps)...")
    rc, _ = _run(
        client,
        (
            f"cd {REMOTE_DIR}/deployment && "
            "docker compose up -d --build --no-deps aaats-paper-crypto 2>&1 | tail -25"
        ),
        "build + recreate",
    )
    if rc != 0:
        print("       FAIL — container did not come up.")
        client.close()
        return 3

    print("\n[7/8] Capturing post-rebuild state + post-deploy SHAs...")
    _, post_image = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1",
        "post image",
    )
    _, post_status = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}}' 2>&1",
        "State.Status",
    )
    _, post_restart = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.RestartCount}}' 2>&1",
        "post RestartCount",
    )
    post_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client, f"sha256sum {REMOTE_DIR}/{rel}", f"post SHA {rel}")
        post_shas[rel] = out.split()[0] if rc == 0 else "(failed)"

    print("\n[8/8] Inside-container smoke tests...")
    _, hb_check = _run(
        client,
        "docker exec aaats-paper-crypto python -c "
        "'from monitoring.heartbeat_monitor import get_all_heartbeats, is_alive; "
        "print(\"flat-reader-resolvable\", list(get_all_heartbeats().keys()))' 2>&1",
        "heartbeat reader resolves",
    )
    _, halt_check = _run(
        client,
        "docker exec aaats-paper-crypto python -c "
        "'from risk.strategy_halt import list_halted_strategies; "
        "print(\"halted:\", list_halted_strategies())' 2>&1",
        "strategy_halt resolves",
    )
    _, schema_check = _run(
        client,
        "docker exec aaats-paper-crypto python -c "
        "'from state.schemas import validate_all_state_files; "
        "import json; print(json.dumps(validate_all_state_files(\"/app/data\"), indent=2))' 2>&1",
        "validate_all_state_files",
    )

    client.close()

    deployed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "ROLLBACK BASELINE - 2026-05-22 Session 3 D.1 + D.3 + heartbeat deploy",
        "=" * 80,
        "",
        f"DEPLOYED_AT_UTC        = {deployed_at}",
        f"PRE_REBUILD_IMAGE_SHA  = {pre_image}",
        f"POST_REBUILD_IMAGE_SHA = {post_image}",
        f"PRE_RESTART_COUNT      = {pre_restart}",
        f"POST_RESTART_COUNT     = {post_restart}",
        f"POST_STATUS            = {post_status}",
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
    lines.append("Smoke results (inside container):")
    lines.append(f"  heartbeat reader : {hb_check}")
    lines.append(f"  strategy_halt    : {halt_check}")
    lines.append(f"  schema smoke     : {schema_check}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 65)
    print(f"  pre  image:   {pre_image}")
    print(f"  post image:   {post_image}")
    print(f"  status:       {post_status}")
    print(f"  RestartCount: {pre_restart} -> {post_restart}")
    print(f"  MANIFEST written: {MANIFEST}")
    print("=" * 65)
    return 0


if __name__ == "__main__":
    sys.exit(main())
