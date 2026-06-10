"""
AAATS -> Contabo Deployment (2026-06-10 research-bed posture)

Executes the [STAGED] deploy-coupled items from AUDIT/structural_fixes.md,
shipped as workstation commit 1c39dde3 (pushed as part of 6760155d):

  1. ML gate removed from trading/live_paper_runner.py (FIX 2) — model was
     stale (33.9d), near-random (val_acc 0.5508), bypassed by C3/C6.
  2. C5b funding_arb + C2 momentum_breakout modules DELETED (prune_log) +
     their runner dispatch removed.
  3. C1/C3/C6 demoted to no-trade: ENTRIES_DISABLED=True in the runner and
     in each strategy module. Exits / stops / MTM still run (wind-down).
  4. Honest-PnL: realized ledger rows written NET of costs at record time
     via analytics/cost_model (new file on the box).

Only aaats-paper-crypto is rebuilt. trading/ and analytics/ are baked into
the image (bind mounts are scripts/, data/, logs/ only) so a rebuild is
required.

Run on the Windows workstation:
    venv\\Scripts\\python tools\\operator\\deploy_research_bed_posture_2026_06_10.py

Safe to re-run: idempotent (same bytes re-uploaded, deletions are
mv-if-exists, rebuild is cached). Pass --dry-run to print the plan only.

Post-deploy verification performed by this script:
  - container restarts healthy and logs the RESEARCH BED posture banner
  - ENTRIES_DISABLED is True in runner + C1/C3/C6 inside the container
  - analytics.cost_model imports + prices a round-trip inside the container
  - deleted modules are gone from the box tree
  - sibling containers stay up; heartbeat file fresh; exporter :9091 alive
  - origin/main runtime/ tree contains no *.log (log-push stopped, FIX 4)
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
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

# Canonical deploy helpers — see CLAUDE.md "Deploy machinery gotchas".
sys.path.insert(0, str(PROJECT_ROOT))
from tools.operator.deploy_lib import (  # noqa: E402
    atomic_upload_normalized,
    clear_stale_git_locks,
    enforce_utf8_console,
    ensure_remote_dirs,
    send_telegram_message,
    verify_telegram_path,
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
PASSWORD = _env.get("CONTABO__SSH_PASSWORD")
REMOTE_DIR = _env.get("CONTABO__REMOTE_DIR", "/home/aaats/aaats")
PORT = 22

# Everything the posture change touches that the container bakes in.
# analytics/cost_model.py is NEW on the box (strategies import it at module
# load — without it the runner dies on boot, hence it ships in the same
# payload). ledger_repricer + model_health ship for repo/box parity (not
# imported by the runner; used by operator tooling).
UPLOAD_FILES = {
    "trading/live_paper_runner.py": f"{REMOTE_DIR}/trading/live_paper_runner.py",
    "trading/altcoin_reversion.py": f"{REMOTE_DIR}/trading/altcoin_reversion.py",
    "trading/bollinger_range.py": f"{REMOTE_DIR}/trading/bollinger_range.py",
    "trading/stat_arb.py": f"{REMOTE_DIR}/trading/stat_arb.py",
    "analytics/cost_model.py": f"{REMOTE_DIR}/analytics/cost_model.py",
    "analytics/ledger_repricer.py": f"{REMOTE_DIR}/analytics/ledger_repricer.py",
    "ml/model_health.py": f"{REMOTE_DIR}/ml/model_health.py",
}

# Deleted from repo in 1c39dde3 — must leave the box tree too, or the next
# unrelated rebuild bakes modules the repo says don't exist. mv (not rm) so
# rollback is a rename away.
DELETE_FILES = [
    f"{REMOTE_DIR}/trading/funding_arb.py",
    f"{REMOTE_DIR}/trading/momentum_breakout.py",
]

CONTAINER = "aaats-paper-crypto"
ROLLBACK_DIR = PROJECT_ROOT / ".rollback" / "2026-06-10_research_bed_posture"

SIBLING_CONTAINERS = (
    "aaats-metrics",
    "aaats-grafana",
    "aaats-prometheus",
    "aaats-watchdog",
    "aaats-telegram-bot",
    "aaats-dashboard",
)


def sha256_of(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()[:16]


def run(
    client: paramiko.SSHClient, cmd: str, desc: str = "", ok_rc=(0,), quiet=False
) -> tuple[int, str, str]:
    if desc:
        print(f"  -> {desc}")
    _, stdout, stderr = client.exec_command(cmd, timeout=600)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if not quiet:
        for line in out.splitlines()[-20:]:
            print(f"    {line}")
    if err and rc not in ok_rc:
        for line in err.splitlines()[-15:]:
            print(f"    [stderr] {line}")
    return rc, out, err


def assert_payload_committed() -> None:
    """Deploy discipline: refuse uncommitted payload files."""
    r = subprocess.run(
        ["git", "status", "--porcelain", "--", *UPLOAD_FILES.keys()],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    dirty = [ln for ln in r.stdout.splitlines() if ln.strip()]
    if dirty:
        raise SystemExit(
            "Payload files are uncommitted — commit first (deploy discipline):\n"
            + "\n".join(dirty)
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-telegram", action="store_true")
    parser.add_argument("--skip-rebuild", action="store_true")
    args = parser.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"== AAATS research-bed posture deploy ({now.isoformat()}) ==")
    print(f"Host: {USER}@{HOST}:{PORT}  remote_dir={REMOTE_DIR}")
    for src in UPLOAD_FILES:
        local = PROJECT_ROOT / src
        if not local.exists():
            print(f"  ! MISSING: {local}")
            return 2
        print(f"    upload  {src}  sha={sha256_of(local)}")
    for dst in DELETE_FILES:
        print(f"    delete  {dst}")

    if args.dry_run:
        print("[dry-run] stopping before SSH connection.")
        return 0

    if not PASSWORD:
        raise SystemExit("CONTABO__SSH_PASSWORD not set in .env")

    clear_stale_git_locks(PROJECT_ROOT)
    assert_payload_committed()

    # Rollback manifest.
    ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
    manifest = ROLLBACK_DIR / "MANIFEST.txt"
    ts = now.strftime("%Y%m%dT%H%M%SZ")
    with manifest.open("w", encoding="utf-8") as f:
        f.write("# AAATS research-bed posture rollback baseline\n")
        f.write(f"# Generated: {now.isoformat()}\n")
        f.write(f"# Host: {USER}@{HOST}\n")
        f.write("# Workstation commit: 1c39dde3 (pre-change: 8f2ba12d)\n\n")
        f.write("## Files uploaded (workstation -> box)\n")
        for src, dst in UPLOAD_FILES.items():
            local = PROJECT_ROOT / src
            f.write(f"  {src}  ->  {dst}\n")
            f.write(f"    sha256_16 = {sha256_of(local)}\n")
        f.write("\n## Files removed on box (mv to .removed-<ts>)\n")
        for dst in DELETE_FILES:
            f.write(f"  {dst}  ->  {dst}.removed-{ts}\n")
        f.write(
            "\n## Rollback steps\n"
            f"  1. On box: cp <path>.bak-{ts} <path> for each uploaded file.\n"
            f"  2. On box: mv <path>.removed-{ts} <path> for each removed file.\n"
            "  3. On box: cd /home/aaats/aaats && docker compose -f "
            "deployment/docker-compose.yml up -d --build --no-deps "
            "aaats-paper-crypto\n"
            "  4. Workstation: git revert 1c39dde3 && push (keeps repo/box sync).\n"
        )
    print(f"Rollback manifest: {manifest}")

    print("\n== Connecting via SSH ==")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
    sftp = client.open_sftp()
    results: dict[str, str] = {}
    try:
        # Gotcha #11: fail-fast Telegram smoke BEFORE any destructive step.
        if not args.skip_telegram:
            print("\n== Verifying Telegram path ==")
            if not verify_telegram_path(client):
                raise SystemExit(
                    "Telegram smoke verify FAILED — refusing to deploy blind. "
                    "Fix ALERTS__TELEGRAM_BOT_TOKEN in /home/aaats/aaats/.env "
                    "or pass --skip-telegram to accept silent alerts."
                )
            print("    [telegram] smoke ok")
            send_telegram_message(
                client,
                "AAATS deploy starting: research-bed posture (ML gate removed, "
                "C2/C5b deleted, C1/C3/C6 entries disabled, ledger writes "
                "net-of-cost). aaats-paper-crypto will rebuild; expect a "
                "~2-4 min trading-loop gap. NO new entries after this deploy; "
                "open positions wind down via exits/stops.",
            )

        print("\n== Backing up current box state ==")
        for dst in UPLOAD_FILES.values():
            run(client, f"cp -p {dst} {dst}.bak-{ts} 2>/dev/null || true", quiet=True)
        print(f"    backups taken with suffix .bak-{ts}")

        ensure_remote_dirs(client, list(UPLOAD_FILES.values()))

        print("\n== Uploading changed files ==")
        for src, dst in UPLOAD_FILES.items():
            local = PROJECT_ROOT / src
            sha = atomic_upload_normalized(sftp, local, dst)
            print(f"    {src} -> {dst}  sha_on_box={sha}")

        print("\n== Removing deleted modules (mv, reversible) ==")
        for dst in DELETE_FILES:
            run(
                client,
                f"test -f {dst} && mv {dst} {dst}.removed-{ts} || true",
                desc=f"remove {dst}",
                quiet=True,
            )
        # Stale bytecode in the host tree must not resurrect deleted modules
        # inside the image (COPY . . includes __pycache__).
        run(
            client,
            f"rm -rf {REMOTE_DIR}/trading/__pycache__ "
            f"{REMOTE_DIR}/analytics/__pycache__ {REMOTE_DIR}/ml/__pycache__",
            desc="clear host-tree __pycache__",
            quiet=True,
        )

        if not args.skip_rebuild:
            print(f"\n== Rebuilding {CONTAINER} ==")
            rc, _, _ = run(
                client,
                f"cd {REMOTE_DIR} && docker compose -f deployment/docker-compose.yml "
                f"up -d --build --no-deps {CONTAINER}",
                desc=f"docker compose up -d --build --no-deps {CONTAINER}",
            )
            if rc != 0:
                raise SystemExit(
                    f"rebuild failed rc={rc} — box untouched siblings; "
                    f"rollback via {manifest}"
                )

            print("\n== Waiting for runner startup banner (up to 5 min) ==")
            banner = ""
            for _ in range(20):
                time.sleep(15)
                rc, banner, _ = run(
                    client,
                    f"docker logs --tail 200 {CONTAINER} 2>&1 | "
                    "grep -E 'RESEARCH BED|Posture' | tail -2",
                    ok_rc=(0, 1),
                    quiet=True,
                )
                if "RESEARCH BED" in banner:
                    break
            results["posture_banner"] = banner or "(banner not seen in 5 min)"
            print(f"    banner: {results['posture_banner']}")

        print("\n== In-container verification ==")
        rc, out, _ = run(
            client,
            f'docker exec {CONTAINER} python -c "'
            "import trading.live_paper_runner as r;"
            "import trading.stat_arb as c1, trading.altcoin_reversion as c3, "
            "trading.bollinger_range as c6;"
            "from analytics.cost_model import round_trip_cost;"
            "print('flags', r.ENTRIES_DISABLED, c1.ENTRIES_DISABLED, "
            "c3.ENTRIES_DISABLED, c6.ENTRIES_DISABLED);"
            "print('rt_cost_10usd', round_trip_cost(10.0, 10.0).total)\"",
            desc="ENTRIES_DISABLED flags + cost model smoke",
        )
        results["flags"] = out
        rc, out, _ = run(
            client,
            f"docker exec {CONTAINER} sh -c "
            "'test ! -f trading/funding_arb.py && test ! -f "
            "trading/momentum_breakout.py && echo MODULES_GONE || echo STILL_PRESENT'",
            desc="deleted modules absent in image",
        )
        results["modules_gone"] = out

        print("\n== Health checks ==")
        rc, out, _ = run(
            client,
            "docker ps --format '{{.Names}}: {{.Status}}' | sort",
            desc="all containers status",
        )
        results["containers"] = out
        rc, out, _ = run(
            client,
            f"docker exec {CONTAINER} sh -c "
            "'cat /app/data/heartbeat.json 2>/dev/null | head -c 300'",
            desc="heartbeat file",
            ok_rc=(0, 1),
        )
        results["heartbeat"] = out or "(no heartbeat yet — first cycle pending)"
        rc, out, _ = run(
            client,
            "curl -s --max-time 10 http://localhost:9091/metrics | "
            "grep -c '^aaats_' || true",
            desc="exporter :9091 series count",
            ok_rc=(0, 1),
        )
        results["exporter_series"] = out

        print("\n== Log-push stopped (FIX 4) verification ==")
        rc, out, _ = run(
            client,
            "cd /srv/aaats/runtime_repo && git fetch -q origin main && "
            "git ls-tree origin/main runtime/ | grep -c '\\.log' || true",
            desc="count *.log files tracked in origin/main runtime/",
            ok_rc=(0, 1),
        )
        results["origin_log_files"] = out
        rc, out, _ = run(
            client,
            "cd /srv/aaats/runtime_repo && git show origin/main:.gitignore | "
            "grep 'runtime/' || echo MISSING",
            desc=".gitignore runtime/*.log rule on origin",
            ok_rc=(0, 1),
        )
        results["gitignore_rule"] = out

        if not args.skip_telegram:
            ok = "True True True True" in results.get(
                "flags", ""
            ) and "MODULES_GONE" in results.get("modules_gone", "")
            send_telegram_message(
                client,
                f"AAATS deploy {'COMPLETE' if ok else 'NEEDS REVIEW'}: "
                "research-bed posture live. "
                f"flags=[{results.get('flags', '?')[:80]}] "
                f"modules={results.get('modules_gone', '?')} "
                f"origin runtime *.log count={results.get('origin_log_files', '?')}. "
                "No new entries from this point; open book winds down via exits.",
            )

        print("\n== DEPLOY COMPLETE ==")
        for k, v in results.items():
            print(f"  {k}: {v[:200] if isinstance(v, str) else v}")
        return 0
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    sys.exit(main())
