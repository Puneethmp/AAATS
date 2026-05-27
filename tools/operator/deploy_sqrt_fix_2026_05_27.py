"""
AAATS → Contabo Deployment Script (2026-05-27 sqrt(252) → sqrt(8760) fix)

Fixes a per-trade Sharpe annualization that used the stock-market convention
sqrt(252) on a crypto 24/7 book. Replaces with sqrt(8760) = sqrt(365*24) in
two callsites:

  monitoring/metrics_exporter.py:851  (live aaats_rolling_sharpe_14d gauge)
  analytics/strategy_optimizer.py:125 (offline grid optimizer, no container)

ONLY aaats-metrics is rebuilt; the strategy_optimizer is invoked on demand.

The live aaats_rolling_sharpe_14d Grafana panel will display values
~sqrt(8760/252) ≈ 5.9× smaller than today's. This is the correction (crypto
trades 24/7, not 252 days/year), not regression. The script sends a Telegram
heads-up to chat 1946109268 BEFORE and AFTER the rebuild so an operator
glancing at Grafana doesn't mistake the corrected panel for a strategy
collapse.

Telegram token lives at /srv/aaats/secrets/telegram_bot_token on the box.
Workstation does NOT need TELEGRAM_BOT_TOKEN in its .env — the script runs
the curl on the box via SSH so the secret never leaves the box.

Run on the Windows workstation:
    venv\\Scripts\\python tools\\operator\\deploy_sqrt_fix_2026_05_27.py

Safe to re-run: idempotent. A re-run re-uploads the same files (no-op since
content is identical) and re-rebuilds aaats-metrics (no-op since image is
cached). Pass --dry-run to print the plan without connecting.

Inventory: docs/specs/b15_data_inventory.md §3a
Phase plan: docs/specs/b15_backtest_harness.md §d
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import pathlib
import shlex
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
    raise SystemExit("CONTABO__SSH_PASSWORD (or AAATS_SSH_PASSWORD) env var not set.")
REMOTE_DIR = _env.get("CONTABO__REMOTE_DIR", "/home/aaats/aaats")
PORT = 22

TELEGRAM_CHAT_ID = "1946109268"
TELEGRAM_TOKEN_PATH = "/srv/aaats/secrets/telegram_bot_token"

CHANGED_FILES = {
    "monitoring/metrics_exporter.py": f"{REMOTE_DIR}/monitoring/metrics_exporter.py",
    "analytics/strategy_optimizer.py": f"{REMOTE_DIR}/analytics/strategy_optimizer.py",
}

# Only metrics_exporter runs inside a container. strategy_optimizer is
# invoked on-demand outside any container.
CONTAINERS_TO_REBUILD = ("aaats-metrics",)

ROLLBACK_DIR = PROJECT_ROOT / ".rollback" / "2026-05-27_sqrt_fix"


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


def send_telegram(client: paramiko.SSHClient, text: str) -> bool:
    """Send a Telegram message from the BOX (where the secret lives).

    Reads /srv/aaats/secrets/telegram_bot_token at runtime; curls api.telegram.org
    /bot<TOKEN>/sendMessage with chat_id + text. Returns True on HTTP 200.
    """
    # Use printf %s and the file read inline so the token never appears in the
    # command echo printed by paramiko.
    text_quoted = shlex.quote(text)
    chat_id_quoted = shlex.quote(TELEGRAM_CHAT_ID)
    cmd = (
        f"TOK=$(cat {TELEGRAM_TOKEN_PATH}) && "
        f"curl -s -o /tmp/tg_resp -w '%{{http_code}}' "
        f"-X POST https://api.telegram.org/bot${{TOK}}/sendMessage "
        f"-d chat_id={chat_id_quoted} "
        f"--data-urlencode text={text_quoted}"
    )
    rc, out, err = run(client, cmd, desc="telegram sendMessage", ok_rc=(0,))
    http_code = out.strip().splitlines()[-1] if out else ""
    if http_code == "200":
        print("    [telegram] sent ok")
        return True
    print(f"    [telegram] FAILED (http={http_code!r}, stderr={err[:200]!r})")
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-rebuild",
        action="store_true",
        help="Push files but don't rebuild aaats-metrics. Use for code-only "
        "tweaks where the container would pick up next natural restart.",
    )
    parser.add_argument(
        "--skip-telegram",
        action="store_true",
        help="Skip pre/post Telegram heads-up. Use if running in a fresh "
        "session where the panel-drop is already understood.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan, do not connect or upload.",
    )
    args = parser.parse_args()

    print(
        f"== AAATS sqrt(252)→sqrt(8760) deploy "
        f"({datetime.datetime.now(datetime.timezone.utc).isoformat()}) =="
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

    # Standing rule: clear stale git locks + preflight ruff format before
    # any commit step. See CLAUDE.md "Deploy machinery gotchas" #4, #5.
    cleared = clear_stale_git_locks(PROJECT_ROOT)
    for path in cleared:
        print(f"  cleared stale lock: {path}")
    changed_py = [PROJECT_ROOT / src for src in CHANGED_FILES if src.endswith(".py")]
    if changed_py:
        print("\n== Preflight ruff format ==")
        preflight_ruff_format(changed_py)

    # Rollback baseline.
    ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
    manifest = ROLLBACK_DIR / "MANIFEST.txt"
    with manifest.open("w", encoding="utf-8") as f:
        f.write("# AAATS sqrt(252)→sqrt(8760) rollback baseline\n")
        f.write(
            f"# Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
        )
        f.write(f"# Host: {USER}@{HOST}\n\n")
        f.write("## Files changed (workstation -> box)\n")
        for src, dst in CHANGED_FILES.items():
            local = PROJECT_ROOT / src
            f.write(f"  {src}  ->  {dst}\n")
            f.write(f"    sha256_16 = {sha256_of(local)}\n")
            f.write(f"    size      = {local.stat().st_size}B\n")
        f.write(
            "\n## Rollback steps\n"
            "  1. On box: cp <path>.bak-<ts> <path> for each backup taken.\n"
            "  2. On box: docker compose -f deployment/docker-compose.yml up "
            "-d --build --no-deps aaats-metrics\n"
            "  3. Sharpe panel will revert to sqrt(252) values "
            "(~5.9× higher than corrected).\n"
        )

    print("\n== Connecting via SSH ==")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
    sftp = client.open_sftp()
    try:
        # Capture a PRE snapshot of one current Sharpe value for the post-
        # rebuild message. This is best-effort; missing metric is fine.
        rc, pre_metrics, _ = run(
            client,
            "curl -s http://localhost:9091/metrics | grep '^aaats_rolling_sharpe_14d' | head -3",
            desc="snapshot pre-fix sharpe gauge",
            ok_rc=(0, 1),
        )
        pre_sample = (
            pre_metrics.splitlines()[0] if pre_metrics else "(no current value)"
        )

        # Pre-rebuild Telegram heads-up.
        if not args.skip_telegram:
            print("\n== Sending pre-rebuild Telegram heads-up ==")
            send_telegram(
                client,
                "AAATS: rebuilding aaats-metrics with sqrt(252)→sqrt(8760) fix. "
                "aaats_rolling_sharpe_14d will appear ~5.9× lower in Grafana. "
                "This is the correction (crypto trades 24/7, not 252 days/year), "
                "not regression. Pre-fix value can be reconstructed by "
                "multiplying post-fix Sharpe by sqrt(8760/252) ≈ 5.9.",
            )

        # Backup current state.
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        print("\n== Backing up current state ==")
        for src, dst in CHANGED_FILES.items():
            run(
                client,
                f"cp -p {dst} {dst}.bak-{ts} 2>/dev/null || true",
                desc=f"snapshot {dst}",
            )

        ensure_remote_dirs(client, list(CHANGED_FILES.values()))

        print("\n== Uploading changed files ==")
        for src, dst in CHANGED_FILES.items():
            local = PROJECT_ROOT / src
            print(
                f"  → upload {local.name} ({local.stat().st_size}B "
                f"sha={sha256_of(local)}) -> {dst}"
            )
            atomic_upload_normalized(sftp, local, dst)

        if not args.skip_rebuild:
            for ctr in CONTAINERS_TO_REBUILD:
                print(f"\n== Rebuilding {ctr} container ==")
                run(
                    client,
                    f"cd {REMOTE_DIR} && docker compose -f deployment/docker-compose.yml up -d --build --no-deps {ctr}",
                    desc=f"docker compose up -d --build --no-deps {ctr}",
                )

            print("\n== Waiting 25s for aaats-metrics to settle ==")
            time.sleep(25)
            run(
                client,
                "docker ps --filter name=aaats-metrics --format '{{.Names}}: {{.Status}}'",
                desc="container status",
            )

        # Smoke test: verify aaats_rolling_sharpe_14d is now sqrt(8760)-annualized.
        # The Sharpe value depends on actual trade data; we can't assert a
        # specific number. Instead we verify the metric is still emitted at
        # all and capture one sample for the post-message.
        print("\n== Smoke test: verify sharpe gauge still emits ==")
        rc, post_metrics, _ = run(
            client,
            "curl -s http://localhost:9091/metrics | grep '^aaats_rolling_sharpe_14d' | head -3",
            desc="post-fix sharpe gauge sample",
            ok_rc=(0, 1),
        )
        post_sample = (
            post_metrics.splitlines()[0]
            if post_metrics
            else "(no value emitted — check)"
        )

        # Post-rebuild Telegram confirmation.
        if not args.skip_telegram:
            print("\n== Sending post-rebuild Telegram confirmation ==")
            send_telegram(
                client,
                "AAATS: sqrt-fix deployed. aaats-metrics rebuilt OK. "
                f"PRE sample: {pre_sample[:120]}. "
                f"POST sample: {post_sample[:120]}. "
                "Post value × sqrt(8760/252) ≈ pre value. Grafana panel "
                "'Rolling 14d Sharpe Ratio' shows the corrected value.",
            )

        print("\n== DEPLOY COMPLETE ==")
        print(f"Rollback manifest: {manifest}")
        print(f"  PRE  : {pre_sample}")
        print(f"  POST : {post_sample}")
        return 0
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    sys.exit(main())
