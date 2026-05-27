"""
AAATS → Contabo Deployment Script (2026-05-27 L11 legacy-drift baseline)

Closes the recurring "L11 capital invariant warn at -$8.5169 every cycle"
that has fired since the L11 instrumentation shipped on 2026-05-26.

Audit: docs/known_issues/2026-05-27_l11_legacy_drift_baseline.md

Ships:
  1. execution/paper_trader.py
       New helper `_read_legacy_drift_baseline` + extended L11 compute that
       subtracts an operator-recorded baseline from raw delta before the
       verdict. Backward-compatible: `delta_usd` field now carries the
       effective (baseline-adjusted) value; new fields raw_delta_usd,
       baseline_drift_usd, effective_delta_usd are added.
  2. monitoring/metrics_exporter.py
       Three new Prometheus gauges: aaats_capital_invariant_raw_delta_usd,
       aaats_capital_invariant_baseline_drift_usd,
       aaats_capital_invariant_effective_delta_usd. Existing
       aaats_capital_invariant_delta_usd continues to emit (with effective
       value now), so existing Grafana panels keep working.
  3. data/capital_invariant_baseline.json
       Records crypto baseline=-$8.5169 with full audit metadata.
       Bind-mount file: lands live without container rebuild.
  4. docs/known_issues/2026-05-27_l11_legacy_drift_baseline.md
       Audit trail + operator runbook for refreshing the baseline.

Run on the Windows workstation:
    venv\\Scripts\\python tools\\operator\\deploy_l11_baseline_2026_05_27.py

Safe to re-run: idempotent. A re-run overwrites the same files and
rebuilds the same container; no state is lost. Pass --dry-run to print
the plan without connecting.
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

# Canonical deploy helpers — see CLAUDE.md "Deploy machinery gotchas" for
# the 10 recurring failure modes each helper closes. Standing rule: every
# deploy script imports deploy_lib; do not reinvent.
sys.path.insert(0, str(PROJECT_ROOT))
from tools.operator.deploy_lib import (  # noqa: E402
    atomic_upload_normalized,
    clear_stale_git_locks,
    enforce_utf8_console,
    ensure_remote_dirs,
    preflight_ruff_format,
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
    "execution/paper_trader.py": f"{REMOTE_DIR}/execution/paper_trader.py",
    "monitoring/metrics_exporter.py": f"{REMOTE_DIR}/monitoring/metrics_exporter.py",
    "data/capital_invariant_baseline.json": f"{REMOTE_DIR}/data/capital_invariant_baseline.json",
    "docs/known_issues/2026-05-27_l11_legacy_drift_baseline.md": f"{REMOTE_DIR}/docs/known_issues/2026-05-27_l11_legacy_drift_baseline.md",
}

# Rebuild containers that bake source code into the image. data/ is a bind
# mount on aaats-paper-crypto, so the baseline JSON lands live without
# rebuild — but paper_trader.py is baked into the image and the L11 reader
# only sees the new code after a rebuild. metrics_exporter.py runs in
# aaats-metrics, also baked.
CONTAINERS_TO_REBUILD = ("aaats-paper-crypto", "aaats-metrics")

ROLLBACK_DIR = PROJECT_ROOT / ".rollback" / "2026-05-27_l11_baseline"


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
    for line in out.splitlines()[-20:]:
        print(f"    {line}")
    if err and rc not in ok_rc:
        for line in err.splitlines()[-15:]:
            print(f"    [stderr] {line}")
    return rc, out, err


def atomic_upload(sftp: paramiko.SFTPClient, local: pathlib.Path, remote: str) -> None:
    """Atomic .tmp + posix_rename swap with line-ending normalization for
    textual files. Wrapped via deploy_lib so this script can't reintroduce
    the CRLF leak path."""
    print(
        f"  → upload {local.name} ({local.stat().st_size}B sha={sha256_of(local)}) -> {remote}"
    )
    atomic_upload_normalized(sftp, local, remote)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-rebuild",
        action="store_true",
        help="Push files but don't rebuild containers. Use when only the "
        "baseline JSON changed (bind-mount file picked up live).",
    )
    parser.add_argument(
        "--skip-git",
        action="store_true",
        help="Skip the local rebase + commit + push step. Use when running "
        "in CI or when the changes are already committed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan, do not connect or upload.",
    )
    args = parser.parse_args()

    print(
        f"== AAATS L11 baseline deploy ({datetime.datetime.utcnow().isoformat()}Z) =="
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

    # Standing rule: clear stale git locks Cowork left behind on the mounted
    # filesystem (Cowork sandbox can't unlink across the mount). See
    # CLAUDE.md "Deploy machinery gotchas" #4.
    if not args.skip_git:
        cleared = clear_stale_git_locks(PROJECT_ROOT)
        for path in cleared:
            print(f"  cleared stale lock: {path}")

        # Standing rule: preflight ruff format BEFORE git add. The pre-commit
        # hook would otherwise auto-reformat mid-commit and race the commit
        # ref. See CLAUDE.md "Deploy machinery gotchas" #5.
        changed_py = [
            PROJECT_ROOT / src for src in CHANGED_FILES if src.endswith(".py")
        ]
        if changed_py:
            print("\n== Preflight ruff format ==")
            preflight_ruff_format(changed_py)

    # Stage rollback baseline locally before doing anything destructive.
    ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
    manifest = ROLLBACK_DIR / "MANIFEST.txt"
    with manifest.open("w", encoding="utf-8") as f:
        f.write("# AAATS L11 baseline rollback baseline\n")
        f.write(f"# Generated: {datetime.datetime.utcnow().isoformat()}Z\n")
        f.write(f"# Host: {USER}@{HOST}\n\n")
        f.write("## Files changed (workstation -> box)\n")
        for src, dst in CHANGED_FILES.items():
            local = PROJECT_ROOT / src
            f.write(f"  {src}  ->  {dst}\n")
            f.write(f"    sha256_16 = {sha256_of(local)}\n")
            f.write(f"    size      = {local.stat().st_size}B\n")
        f.write(
            "\n## Rollback steps\n"
            "  1. On box: cp <path>.bak-<ts> <path> for each backup taken below.\n"
            "  2. On box: docker compose -f deployment/docker-compose.yml up "
            "-d --build --no-deps aaats-paper-crypto aaats-metrics\n"
            "  3. On box: rm -f "
            + REMOTE_DIR
            + "/data/capital_invariant_baseline.json\n"
            "     (baseline file is harmless if missing; L11 falls back to v1 behavior.)\n"
        )

    # Connect.
    print("\n== Connecting via SSH ==")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
    sftp = client.open_sftp()
    try:
        # Backup current paper_trader.py + metrics_exporter.py on the box.
        ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        print("\n== Backing up current state ==")
        for src, dst in CHANGED_FILES.items():
            if not src.endswith(".py"):
                continue
            run(
                client,
                f"cp -p {dst} {dst}.bak-{ts} 2>/dev/null || true",
                desc=f"snapshot {dst}",
            )

        # Make sure remote dirs exist (docs/known_issues might not).
        # ensure_remote_dirs treats inputs as FILE paths and mkdirs the
        # parents — so pass the actual destination file paths, not dir paths.
        ensure_remote_dirs(client, list(CHANGED_FILES.values()))

        # Upload changed files (atomic .tmp swap via deploy_lib normalization).
        print("\n== Uploading changed files ==")
        for src, dst in CHANGED_FILES.items():
            local = PROJECT_ROOT / src
            atomic_upload(sftp, local, dst)

        if not args.skip_rebuild:
            for ctr in CONTAINERS_TO_REBUILD:
                print(f"\n== Rebuilding {ctr} container ==")
                run(
                    client,
                    f"cd {REMOTE_DIR} && docker compose -f deployment/docker-compose.yml up -d --build --no-deps {ctr}",
                    desc=f"docker compose up -d --build --no-deps {ctr}",
                    ok_rc=(0,),
                )

            print("\n== Waiting 25s for containers to settle ==")
            time.sleep(25)
            run(
                client,
                "docker ps --filter name=aaats- --format '{{.Names}}: {{.Status}}' | sort",
                desc="container status",
            )

        # Smoke test 1: confirm baseline file is readable inside container.
        print("\n== Smoke test: baseline file readable in container ==")
        run(
            client,
            'docker exec aaats-paper-crypto python -c "'
            "import json; "
            "p=json.load(open('/app/data/capital_invariant_baseline.json')); "
            "import sys; sys.stdout.write('crypto_baseline_usd=' + str(p['crypto']['baseline_usd']) + '\\n')\"",
            desc="cat capital_invariant_baseline.json from container",
        )

        # Smoke test 2: compute L11 invariant — should now show effective ≈ 0.
        print("\n== Smoke test: compute L11 invariant — effective should be ≈ 0 ==")
        run(
            client,
            'docker exec aaats-paper-crypto python -c "'
            "from execution.paper_trader import compute_capital_invariant; "
            "import json; "
            "p=json.load(open('/app/data/paper_portfolio.json')); "
            "pos=json.load(open('/app/data/paper_positions.json')); "
            "r=compute_capital_invariant(p, 'crypto', positions=pos); "
            "print('L11', 'verdict=' + str(r['verdict']), "
            "'raw=' + str(r['raw_delta_usd']), "
            "'baseline=' + str(r['baseline_drift_usd']), "
            "'effective=' + str(r['effective_delta_usd']))\"",
            desc="invoke compute_capital_invariant inside container",
        )

        # Smoke test 3: confirm new metrics are exposed.
        print("\n== Smoke test: verify new L11 metrics on /metrics endpoint ==")
        run(
            client,
            "curl -s http://localhost:9091/metrics | grep -E "
            "'^aaats_capital_invariant_(raw_delta|baseline_drift|effective_delta)' | head -10",
            desc="curl metrics | grep capital_invariant_(raw|baseline|effective)",
            ok_rc=(0, 1),
        )

        # Smoke test 4: read the live alert JSON to see what L11 wrote.
        print("\n== Smoke test: live alert JSON after deploy ==")
        run(
            client,
            f"cat {REMOTE_DIR}/data/capital_invariant_alerts.json 2>/dev/null || echo '(no alert file yet — L11 either ok or not yet run)'",
            desc="cat capital_invariant_alerts.json",
            ok_rc=(0, 1),
        )

        print("\n== DEPLOY COMPLETE ==")
        print(f"Rollback manifest: {manifest}")
        print("\nNext steps:")
        print("  1. Wait one full cycle (~15 min) — L11 will run on cycle end.")
        print(
            "  2. Read runtime/capital_invariant_alerts.json — verdict should be 'ok'"
        )
        print("     (or absent, which also means ok).")
        print("  3. Grafana panel aaats_capital_invariant_delta_usd should go to ≈ 0.")
        print("  4. Telegram L11 alerts stop firing.")
        print("  5. If new drift accumulates beyond the $2 WARN threshold on top")
        print("     of the baseline, L11 will fire again — that's a NEW leak.")
        print("\nIf a re-baseline is needed later:")
        print(
            "  ssh aaats@100.95.126.39 'rm /home/aaats/aaats/data/capital_invariant_baseline.json'"
        )
        print("  Wait one cycle. Capture the new raw delta. Update the JSON, redeploy.")
        return 0
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    sys.exit(main())
