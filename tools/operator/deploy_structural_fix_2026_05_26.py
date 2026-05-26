"""
AAATS → Contabo Deployment Script (2026-05-26 structural observability fix)

Ships the three changes from the "stop the bug fires" sprint:

  A. Expanded autopush snapshot (+ DB freshness check)
       scripts/box/aaats-autopush-v3.sh  →  /home/aaats/bin/aaats-autopush.sh
  B. Capital invariant guard (L11)
       execution/paper_trader.py         →  container code (rebuild)
       trading/live_paper_runner.py      →  container code (rebuild)
  C. Daily Telegram digest workflow
       .github/workflows/daily-digest.yml  →  picked up by GitHub Actions on push

Run on the Windows workstation:
    venv\\Scripts\\python tools\\operator\\deploy_structural_fix_2026_05_26.py

What this script does:
  1. SSH to the box and back up the current /home/aaats/bin/aaats-autopush.sh
  2. SCP the new autopush script to /home/aaats/bin/aaats-autopush.sh (atomic swap via .tmp)
  3. SCP the changed container Python files to /home/aaats/aaats/{execution,trading}/
  4. docker compose up -d --build --no-deps aaats-paper-crypto (rebuild ONE service)
  5. Verify: query the new compute_capital_invariant from inside the container
  6. Record a rollback baseline under .rollback/2026-05-26_structural_fix/

After this script, the GitHub Actions workflow (daily-digest.yml) starts running
automatically once the file lands on origin/main — push your branch and the
:05 6 UTC cron picks it up next morning.

Safe to re-run: the script is idempotent. A re-run will overwrite the same
files and rebuild the same container; no state is lost.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import pathlib
import subprocess
import sys
import time

try:
    import paramiko
except ImportError:
    print("Installing paramiko...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
    import paramiko

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

# Pull in canonical deploy helpers so a re-run can't reintroduce the CRLF leak
# path that landed v3 dashboard JSON on the box with Windows line endings
# during the 2026-05-26 deploy. See tools/operator/deploy_lib.py.
sys.path.insert(0, str(PROJECT_ROOT))
from tools.operator.deploy_lib import (  # noqa: E402
    atomic_upload_normalized,
    clear_stale_git_locks,  # noqa: F401  (kept for symmetry with other deploy scripts)
    enforce_utf8_console,
)

enforce_utf8_console()


def load_env(path: pathlib.Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().split("#")[0].strip()
    return env


_env = load_env(PROJECT_ROOT / ".env")
HOST = _env.get("CONTABO__TAILSCALE_IP", "100.95.126.39")
USER = _env.get("CONTABO__SSH_USER", "aaats")
PASSWORD = _env.get("CONTABO__SSH_PASSWORD") or os.environ.get("AAATS_SSH_PASSWORD")
if not PASSWORD:
    raise SystemExit(
        "CONTABO__SSH_PASSWORD (or AAATS_SSH_PASSWORD) env var not set. "
        "Copy .env.example to .env and fill in the rotated password."
    )
REMOTE_DIR = _env.get("CONTABO__REMOTE_DIR", "/home/aaats/aaats")
PORT = 22

# Files this sprint changes (relative to PROJECT_ROOT).
CHANGED_FILES = {
    # source path on workstation                                →   destination path on box
    "scripts/box/aaats-autopush-v3.sh": "/home/aaats/bin/aaats-autopush.sh",
    "execution/paper_trader.py": f"{REMOTE_DIR}/execution/paper_trader.py",
    "trading/live_paper_runner.py": f"{REMOTE_DIR}/trading/live_paper_runner.py",
    "monitoring/metrics_exporter.py": f"{REMOTE_DIR}/monitoring/metrics_exporter.py",
    "deployment/grafana/dashboards/aaats_command_center_v3.json": f"{REMOTE_DIR}/deployment/grafana/dashboards/aaats_command_center_v3.json",
    ".github/workflows/daily-digest.yml": f"{REMOTE_DIR}/.github/workflows/daily-digest.yml",
}

# Containers that need a rebuild (NOT just file refresh).
# aaats-metrics rebuild: pulls in the new L11 collector_capital_invariant.
# aaats-paper-crypto rebuild: pulls in L11 invariant call in run_crypto.
# aaats-grafana DOES NOT rebuild — dashboard JSON is picked up by the
# provisioning loop (updateIntervalSeconds=30) within 30s of the file landing.
CONTAINERS_TO_REBUILD = ("aaats-paper-crypto", "aaats-metrics")

ROLLBACK_DIR = PROJECT_ROOT / ".rollback" / "2026-05-26_structural_fix"


def sha256_of(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()[:16]


def run(
    client: paramiko.SSHClient, cmd: str, desc: str = "", ok_rc=(0,)
) -> tuple[int, str, str]:
    if desc:
        print(f"  → {desc}")
    _, stdout, stderr = client.exec_command(cmd, timeout=300)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    for line in out.splitlines()[-15:]:
        print(f"    {line}")
    if err and rc not in ok_rc:
        for line in err.splitlines()[-15:]:
            print(f"    [stderr] {line}")
    return rc, out, err


def atomic_upload(sftp: paramiko.SFTPClient, local: pathlib.Path, remote: str) -> None:
    """Atomic .tmp + posix_rename swap with line-ending normalization for
    textual files. Thin wrapper over deploy_lib.atomic_upload_normalized so
    this script can't reintroduce the CRLF leak path. Retrofitted 2026-05-26
    after the v3 dashboard JSON landed on the box with Windows line endings.
    """
    print(
        f"  → upload {local.name} ({local.stat().st_size}B sha={sha256_of(local)}) -> {remote}"
    )
    atomic_upload_normalized(sftp, local, remote)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-rebuild",
        action="store_true",
        help="Only push autopush script + workflow; don't touch the container "
        "(use when only autopush/workflow changed since last deploy).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan, do not connect or upload.",
    )
    args = parser.parse_args()

    print(
        f"== AAATS structural fix deploy ({datetime.datetime.utcnow().isoformat()}Z) =="
    )
    print(f"Host: {USER}@{HOST}:{PORT}  remote_dir={REMOTE_DIR}")
    print(f"Changed files: {len(CHANGED_FILES)}")
    for src in CHANGED_FILES:
        local = PROJECT_ROOT / src
        if not local.exists():
            print(f"  ! MISSING: {local}")
            return 2
        print(f"    - {src}  sha={sha256_of(local)}")

    if args.dry_run:
        print("[dry-run] stopping before SSH connection.")
        return 0

    # Stage rollback baseline locally before doing anything destructive.
    ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
    manifest = ROLLBACK_DIR / "MANIFEST.txt"
    with manifest.open("w", encoding="utf-8") as f:
        f.write("# AAATS structural fix rollback baseline\n")
        f.write(f"# Generated: {datetime.datetime.utcnow().isoformat()}Z\n")
        f.write(f"# Host: {USER}@{HOST}\n\n")
        f.write("## Files changed (workstation -> box)\n")
        for src, dst in CHANGED_FILES.items():
            local = PROJECT_ROOT / src
            f.write(f"  {src}  ->  {dst}\n")
            f.write(f"    sha256_16 = {sha256_of(local)}\n")
            f.write(f"    size      = {local.stat().st_size}B\n")

    # Connect.
    print("\n== Connecting via SSH ==")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
    sftp = client.open_sftp()
    try:
        # Backup current autopush script on the box.
        ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        print("\n== Backing up current state ==")
        run(
            client,
            f"cp -p /home/aaats/bin/aaats-autopush.sh /home/aaats/bin/aaats-autopush.sh.bak-{ts} 2>/dev/null || true",
            desc=f"snapshot autopush.sh -> aaats-autopush.sh.bak-{ts}",
        )
        run(
            client,
            f"cp -p {REMOTE_DIR}/execution/paper_trader.py {REMOTE_DIR}/execution/paper_trader.py.bak-{ts} 2>/dev/null || true",
            desc="snapshot paper_trader.py",
        )
        run(
            client,
            f"cp -p {REMOTE_DIR}/trading/live_paper_runner.py {REMOTE_DIR}/trading/live_paper_runner.py.bak-{ts} 2>/dev/null || true",
            desc="snapshot live_paper_runner.py",
        )

        # Upload changed files (atomic .tmp swap).
        print("\n== Uploading changed files ==")
        for src, dst in CHANGED_FILES.items():
            local = PROJECT_ROOT / src
            atomic_upload(sftp, local, dst)

        # Ensure autopush script is executable.
        run(
            client,
            "chmod +x /home/aaats/bin/aaats-autopush.sh",
            desc="chmod +x autopush.sh",
        )

        if not args.skip_rebuild:
            for ctr in CONTAINERS_TO_REBUILD:
                print(f"\n== Rebuilding {ctr} container ==")
                run(
                    client,
                    f"cd {REMOTE_DIR} && docker compose -f deployment/docker-compose.yml up -d --build --no-deps {ctr}",
                    desc=f"docker compose up -d --build --no-deps {ctr}",
                    ok_rc=(0,),
                )

            # Sanity wait for both containers to register healthy.
            print("\n== Waiting 25s for containers to settle ==")
            time.sleep(25)
            run(
                client,
                "docker ps --filter name=aaats- --format '{{.Names}}: {{.Status}}' | sort",
                desc="container status",
            )

        # Smoke test: import the new module + call the invariant.
        print("\n== Smoke test: L11 capital invariant function exists ==")
        run(
            client,
            'docker exec aaats-paper-crypto python -c "'
            "from execution.paper_trader import compute_capital_invariant, assert_capital_invariant; "
            "import json; "
            "p=json.load(open('/app/data/paper_portfolio.json')); "
            "print('L11_OK', compute_capital_invariant(p, 'crypto'))\"",
            desc="invoke L11 inside container",
        )

        # Smoke test: autopush script syntax-checks.
        print("\n== Smoke test: autopush script syntax-checks ==")
        run(
            client,
            "bash -n /home/aaats/bin/aaats-autopush.sh && echo 'AUTOPUSH_SYNTAX_OK'",
            desc="bash -n /home/aaats/bin/aaats-autopush.sh",
        )

        # Smoke test: trigger autopush once now to verify all 11 snapshots work.
        print("\n== Smoke test: trigger autopush manually to verify snapshot list ==")
        run(
            client,
            "sudo -n /home/aaats/bin/aaats-autopush.sh; tail -30 /home/aaats/aaats-autopush.log",
            desc="manual autopush invocation",
            ok_rc=(0, 1),
        )

        # Smoke test: confirm L11 metrics flow through aaats-metrics
        print("\n== Smoke test: verify L11 metrics on /metrics endpoint ==")
        run(
            client,
            "curl -s http://localhost:9091/metrics | grep -E '^aaats_capital_invariant' | head -10",
            desc="curl metrics | grep capital_invariant",
            ok_rc=(0, 1),
        )

        # Smoke test: confirm Grafana picked up the new dashboard
        print(
            "\n== Smoke test: confirm Grafana provisioned v3 dashboard (waits 35s) =="
        )
        time.sleep(35)
        run(
            client,
            "docker exec aaats-grafana ls /etc/grafana/dashboards/ 2>/dev/null | grep -i v3 || echo 'v3 not visible yet'",
            desc="check v3 dashboard file in grafana container",
        )

        print("\n== DEPLOY COMPLETE ==")
        print(f"Rollback manifest: {manifest}")
        print("\nNext steps:")
        print(
            "  1. git commit + push the changed files (workflow needs them on origin/main)"
        )
        print("  2. Watch the next autopush tick — should land all 11 snapshot files")
        print("  3. First daily digest fires at 06:05 UTC tomorrow morning")
        print(
            "  4. Set GitHub repo secrets TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID if missing"
        )
        print("  5. Open v3 dashboard: http://100.95.126.39:3000/d/aaats-cmd-center-v3")
        return 0
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    sys.exit(main())
