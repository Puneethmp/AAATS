"""
2026-05-25 Cowork-session deploy: heartbeat write-order fix + portfolio
stats self-reconciler.

Closes three recurring drift complaints flagged in the 2026-05-25 status
report:

  1. runtime/auto_cron_heartbeat.json frozen at 2026-05-24T09:53:53Z
     status=started, even though pushes were landing every 15min. Root
     cause: scripts/box/aaats-autopush-v3.sh wrote `write_heartbeat
     "started"` BEFORE `git reset --hard origin/main`, which wiped the
     local write. The post-push `write_heartbeat "ok"` only updated the
     local file and got wiped on the next cycle's reset. Fix: write the
     heartbeat AFTER the reset+snapshot block, before `git add runtime/`,
     so it lands in the commit.

  2. paper_portfolio.crypto.total_trades = 8 but paper_trades.db had 20
     trades. Root cause: C3 (altcoin_reversion) and C6 (bollinger_range)
     write to DB and mutate portfolio["capital"] but DO NOT update
     total_trades / realized_pnl / wins / losses. Only execute() and
     stat_arb bump those counters. Fix: derive the four fields from the
     DB at end of every cycle in trading.live_paper_runner.
     `_reconcile_portfolio_stats_from_db()`. Self-correcting for current
     and future strategies that skip portfolio bookkeeping.

  3. (companion) .github/workflows/liveness-monitor.yml gains a second
     check that reads runtime/auto_cron_heartbeat.json's last_tick field
     and asserts age <30min. Catches the (1)-class failure independently
     of whether pushes are landing.

Files to roll:
  /home/aaats/bin/aaats-autopush.sh         <- scripts/box/aaats-autopush-v3.sh
  /home/aaats/aaats/trading/live_paper_runner.py

Rebuild aaats-paper-crypto (--no-deps); other containers untouched.

Smoke gates:
  (a) `bash -n` parses the new autopush.sh on box
  (b) `import trading.live_paper_runner` succeeds inside the container
  (c) `from trading.live_paper_runner import _reconcile_portfolio_stats_from_db`
      symbol resolves
  (d) Next cron tick (<=15min after deploy) writes a heartbeat with status
      != "started" -- verified by polling the file twice.

Rollback baseline: .rollback/2026-05-25_heartbeat_portfolio_fix/MANIFEST.txt

Note: the GitHub workflow change (.github/workflows/liveness-monitor.yml)
is NOT deployed by SCP -- it lives on github.com infra. It deploys on
`git push origin main`. Push the workflow change separately.
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
REMOTE_BIN = "/home/aaats/bin"

# (local repo path, remote absolute path on box)
FILES: list[tuple[str, str]] = [
    ("scripts/box/aaats-autopush-v3.sh", f"{REMOTE_BIN}/aaats-autopush.sh"),
    ("trading/live_paper_runner.py", f"{REMOTE_DIR}/trading/live_paper_runner.py"),
]

# Files that are NOT SCP-deployed but require `git push` to reach their
# runtime location (GitHub Actions). Listed for the operator's awareness;
# the script does NOT touch them.
GIT_PUSH_FILES: list[str] = [
    ".github/workflows/liveness-monitor.yml",
    "tests/test_portfolio_reconcile_drift_fix.py",
]

MANIFEST = (
    PROJECT_ROOT / ".rollback" / "2026-05-25_heartbeat_portfolio_fix" / "MANIFEST.txt"
)


def _ascii(line: str) -> str:
    return line.encode("ascii", "replace").decode("ascii")


def _run(
    client: paramiko.SSHClient, cmd: str, label: str, timeout: int = 300
) -> tuple[int, str]:
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
    parser = argparse.ArgumentParser(
        description="2026-05-25 heartbeat + portfolio-stats fix deploy"
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="bypass the clean-tree guard (use only in genuine emergencies)",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="skip the post-deploy heartbeat-poll verification (saves ~16min)",
    )
    args = parser.parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from tools.operator._dirty_tree_guard import check_clean

        check_clean([rel for rel, _ in FILES], allow_dirty=args.allow_dirty)
    except ImportError:
        print("WARN: dirty-tree guard not importable -- skipping (verify manually)")

    print("=" * 70)
    print("  2026-05-25 -> heartbeat write-order fix + portfolio reconciler")
    print(f"  Target: {USER}@{HOST}")
    for rel, remote in FILES:
        print(f"    {rel:60s} -> {remote}")
    print("  Rebuild: aaats-paper-crypto only (--no-deps)")
    print("=" * 70)

    if not PASSWORD:
        print("FATAL: CONTABO__SSH_PASSWORD not in .env")
        return 1
    for rel, _ in FILES:
        if not (PROJECT_ROOT / rel).exists():
            print(f"FATAL: {rel} not found locally")
            return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"\n[1/10] Connecting to {HOST}...")
    client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    print("       Connected")

    print("\n[2/10] Pre-deploy state capture...")
    _, pre_paper_image = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1",
        "pre paper-crypto image",
    )
    pre_shas: dict[str, str] = {}
    for rel, remote in FILES:
        rc, out = _run(
            client,
            f"sha256sum {remote} 2>&1 || echo 'ABSENT {remote}'",
            f"pre SHA {remote}",
        )
        pre_shas[remote] = (
            out.split()[0] if rc == 0 and "ABSENT" not in out else "ABSENT"
        )

    # Capture pre-deploy heartbeat for the verification gate later.
    _, pre_heartbeat = _run(
        client,
        "cat /srv/aaats/runtime_repo/runtime/auto_cron_heartbeat.json 2>&1 | "
        "python3 -c 'import json,sys; d=json.load(sys.stdin); "
        'print(f"last_tick={d.get(\\"last_tick\\")} status={d.get(\\"status\\")}")\' '
        "|| echo '(heartbeat file unreadable)'",
        "pre heartbeat snapshot",
    )

    print("\n[3/10] SFTP upload (LF-normalized)...")
    sftp = client.open_sftp()
    uploaded: list[tuple[str, str, str]] = []
    try:
        for rel, remote in FILES:
            local = PROJECT_ROOT / rel
            tmp = remote + ".tmp"
            content = local.read_text(encoding="utf-8").replace("\r\n", "\n")
            with sftp.open(tmp, "w") as fh:
                fh.write(content)
            uploaded.append((rel, remote, tmp))
            print(f"       wrote {tmp}")
    finally:
        sftp.close()

    print("\n[4/10] Atomic swaps + chmod...")
    for rel, remote, tmp in uploaded:
        rc, _ = _run(client, f"mv -f {tmp} {remote} && echo OK", f"swap {rel}")
        if rc != 0:
            client.close()
            return 2
        # autopush.sh needs +x; runner.py does not
        if remote.endswith(".sh"):
            _ = _run(client, f"chmod +x {remote}", f"chmod +x {remote}")

    print("\n[5/10] Bash-syntax check on new autopush.sh...")
    rc_bash, _ = _run(
        client, f"bash -n {REMOTE_BIN}/aaats-autopush.sh && echo BASH_OK", "bash -n"
    )
    smoke_a_ok = rc_bash == 0

    print("\n[6/10] Rebuilding aaats-paper-crypto (--no-deps --build)...")
    rc, _ = _run(
        client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose up -d --build --no-deps aaats-paper-crypto 2>&1 | tail -25",
        "rebuild paper-crypto",
        timeout=900,
    )
    if rc != 0:
        client.close()
        return 4

    print("\n[7/10] Settling 30s for boot + first imports...")
    _time.sleep(30)

    print("\n[8/10] Smoke gates...")
    _, post_paper_image = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1",
        "post paper-crypto image",
    )
    _, post_paper_status = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}}' 2>&1",
        "post paper-crypto status",
    )
    # (b) import resolves
    rc_b, _ = _run(
        client,
        "docker exec aaats-paper-crypto python -c 'import trading.live_paper_runner; "
        'print("IMPORT_OK")\' 2>&1',
        "smoke (b) import live_paper_runner",
        timeout=30,
    )
    smoke_b_ok = rc_b == 0
    # (c) reconciler symbol resolves
    rc_c, sym_out = _run(
        client,
        "docker exec aaats-paper-crypto python -c "
        "'from trading.live_paper_runner import _reconcile_portfolio_stats_from_db; "
        'print("SYM_OK")\' 2>&1',
        "smoke (c) reconciler symbol",
        timeout=30,
    )
    smoke_c_ok = rc_c == 0 and "SYM_OK" in sym_out

    paper_running = "running" in post_paper_status

    post_shas: dict[str, str] = {}
    for _, remote in FILES:
        rc, out = _run(client, f"sha256sum {remote}", f"post SHA {remote}")
        post_shas[remote] = out.split()[0] if rc == 0 else "(failed)"

    # (d) heartbeat freshness -- only if not skipped
    smoke_d_ok = True
    post_heartbeat = "(not polled)"
    if not args.skip_verify:
        print("\n[9/10] Verifying heartbeat write -- polling every 60s for <=17min...")
        # Cron is */15; allow up to 17min to catch the next tick + write window.
        target_status_changed = False
        for i in range(17):
            _time.sleep(60)
            rc, post_heartbeat = _run(
                client,
                "cat /srv/aaats/runtime_repo/runtime/auto_cron_heartbeat.json 2>&1 | "
                "python3 -c 'import json,sys; d=json.load(sys.stdin); "
                'print(f"last_tick={d.get(\\"last_tick\\")} status={d.get(\\"status\\")}")\' '
                "|| echo '(heartbeat unreadable)'",
                f"poll {i+1}/17",
            )
            # NEW behavior: status should land as 'cycle_active' (then 'ok'
            # at end of cycle locally). Both are acceptable; what we DON'T
            # want is 'started' carrying the same timestamp as pre-deploy.
            if (
                "cycle_active" in post_heartbeat or "ok" in post_heartbeat
            ) and pre_heartbeat.split()[0] not in post_heartbeat:
                target_status_changed = True
                break
        smoke_d_ok = target_status_changed
    else:
        print("\n[9/10] Skipping heartbeat verification (--skip-verify)")

    client.close()

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    deployed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "ROLLBACK BASELINE -- 2026-05-25 heartbeat write-order + portfolio reconciler",
        "=" * 80,
        "",
        f"DEPLOYED_AT_UTC          = {deployed_at}",
        f"PRE_PAPER_CRYPTO_IMAGE   = {pre_paper_image}",
        f"POST_PAPER_CRYPTO_IMAGE  = {post_paper_image}",
        f"POST_PAPER_CRYPTO_STATUS = {post_paper_status}",
        f"PRE_HEARTBEAT            = {pre_heartbeat}",
        f"POST_HEARTBEAT           = {post_heartbeat}",
        f"SMOKE_A_BASH_PARSE       = {smoke_a_ok}",
        f"SMOKE_B_IMPORT           = {smoke_b_ok}",
        f"SMOKE_C_SYMBOL           = {smoke_c_ok}",
        f"SMOKE_D_HEARTBEAT_TICKED = {smoke_d_ok}",
        f"GATE_PAPER_RUNNING       = {paper_running}",
        "",
        "Files (pre -> post SHAs):",
    ]
    for _, remote in FILES:
        lines.append(
            f"  {remote:55s} : {pre_shas.get(remote, '?')} -> {post_shas.get(remote, '?')}"
        )
    lines.append("")
    lines.append("Companion files (deployed via `git push`, not SCP):")
    for rel in GIT_PUSH_FILES:
        lines.append(f"  {rel}")
    lines.append("")
    lines.append("Rollback (each file individually):")
    lines.append(
        "  ssh aaats@100.95.126.39 'cp /home/aaats/bin/aaats-autopush.sh.v2.bak.20260524T095413Z "
        "/home/aaats/bin/aaats-autopush.sh'  # if rolling back the heartbeat fix"
    )
    lines.append(
        "  (no per-file backup for live_paper_runner; revert via git on workstation then redeploy)"
    )
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"  paper-crypto image:   {post_paper_image}")
    print(f"  paper-crypto status:  {post_paper_status}")
    print(f"  smoke A (bash -n):    {smoke_a_ok}")
    print(f"  smoke B (import):     {smoke_b_ok}")
    print(f"  smoke C (symbol):     {smoke_c_ok}")
    print(f"  smoke D (heartbeat):  {smoke_d_ok}")
    print(f"  pre heartbeat:        {pre_heartbeat}")
    print(f"  post heartbeat:       {post_heartbeat}")
    print(f"  MANIFEST written:     {MANIFEST}")
    print("=" * 70)
    all_ok = smoke_a_ok and smoke_b_ok and smoke_c_ok and paper_running and smoke_d_ok
    if not all_ok:
        print(
            "\nONE OR MORE GATES FAILED -- review manifest, do NOT push to github yet."
        )
        return 9
    print("\nAll gates passed. Next step:")
    print("  git add scripts/box/aaats-autopush-v3.sh trading/live_paper_runner.py \\")
    print("          .github/workflows/liveness-monitor.yml \\")
    print("          tests/test_portfolio_reconcile_drift_fix.py \\")
    print("          scripts/deploy_2026_05_25_heartbeat_portfolio_fix.py \\")
    print("          .rollback/2026-05-25_heartbeat_portfolio_fix/")
    print('  git commit -m "2026-05-25 heartbeat + portfolio drift permanent fix"')
    print("  git pull --rebase origin main && git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
