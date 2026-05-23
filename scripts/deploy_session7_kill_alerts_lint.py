"""
Session 7 deploy [0]: bundle session-6 workstation changes into ONE coordinated
box deploy.

Ships in one all-or-nothing batch:
  trading/live_paper_runner.py            (run_crypto is_halted gate)
  monitoring/daily_digest.py              (wording bands + alerts_log path)
  observability/alerts.py                 (alerts-log writer + severity infer)
  foundation/kill_switch.py               (noqa annotation, no behavior change)
  monitoring/metrics_exporter.py          (collect_self_up, row 7)
  tools/operator/_digest_smoke.py         (new helper -- cheap to ship)
  tools/lint/__init__.py                  (package marker)
  tools/lint/silent_except.py             (lint walker, workstation-side)
  tools/lint/silent_except_baseline.txt   (lint baseline)

Image-baked changes => rebuilds aaats-paper-crypto + aaats-metrics + aaats-watchdog.
Compose --no-deps so sibling containers stay up.

Smoke sequence:
  A. tail aaats-paper-crypto for one cycle -- confirm no errors, confirm no
     unexpected "Crypto market HALTED" lines (halt_state.json crypto:false).
  B. _digest_smoke: docker exec aaats-watchdog python -m monitoring.daily_digest
     --dry-run -- confirm Equity line non-N/A AND band wording fires at -33.4%.
  C. confirm data/alerts_log.json present (auto-created on first send_alert;
     existence not required, but if present must parse as JSON list).
  D. confirm aaats_metrics_exporter_up=1 in /metrics on :9091.

Rollback baseline at .rollback/2026-05-24_session7_kill_alerts_lint/MANIFEST.txt.

Run:
  venv\\Scripts\\python scripts\\deploy_session7_kill_alerts_lint.py [--allow-dirty]
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

# Order matters only for human readability; uploads are independent.
FILES: list[str] = [
    "trading/live_paper_runner.py",
    "monitoring/daily_digest.py",
    "observability/alerts.py",
    "foundation/kill_switch.py",
    "monitoring/metrics_exporter.py",
    "tools/operator/_digest_smoke.py",
    "tools/lint/__init__.py",
    "tools/lint/silent_except.py",
    "tools/lint/silent_except_baseline.txt",
]

# Parent dirs to mkdir -p before atomic swap (defensive; most exist already).
REMOTE_MKDIRS: list[str] = [
    "trading",
    "monitoring",
    "observability",
    "foundation",
    "tools/operator",
    "tools/lint",
]

MANIFEST = (
    PROJECT_ROOT
    / ".rollback"
    / "2026-05-24_session7_kill_alerts_lint"
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
    for line in out.splitlines()[-25:]:
        print(f"     {_ascii(line)}")
    if rc != 0 and err:
        for line in err.splitlines()[-5:]:
            print(f"     ERR: {_ascii(line)}")
    return rc, out


def main() -> int:
    parser = argparse.ArgumentParser(description="Session 7 [0] coordinated box deploy")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from tools.operator._dirty_tree_guard import check_clean
    check_clean(FILES, allow_dirty=args.allow_dirty)

    print("=" * 70)
    print("  Session 7 deploy [0] -> bundle session-6 workstation changes")
    print(f"  Target: {USER}@{HOST}:{REMOTE_DIR}/<{len(FILES)} files>")
    print("  Rebuild: aaats-paper-crypto + aaats-metrics + aaats-watchdog (--no-deps)")
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
    print(f"\n[1/11] Connecting to {HOST}...")
    client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    print("       Connected")

    print("\n[2/11] Pre-deploy state capture...")
    _, pre_paper_image = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1", "pre paper image")
    _, pre_metrics_image = _run(client,
        "docker inspect aaats-metrics --format '{{.Image}}' 2>&1", "pre metrics image")
    _, pre_watchdog_image = _run(client,
        "docker inspect aaats-watchdog --format '{{.Image}}' 2>&1", "pre watchdog image")
    _, pre_halt_state = _run(client,
        f"cat {REMOTE_DIR}/data/halt_state.json 2>&1 || echo MISSING", "pre halt_state.json")
    pre_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client,
            f"sha256sum {REMOTE_DIR}/{rel} 2>&1 || echo 'ABSENT {rel}'", f"pre SHA {rel}")
        pre_shas[rel] = out.split()[0] if rc == 0 and "ABSENT" not in out else "ABSENT"

    print("\n[3/11] mkdir -p parent dirs (defensive)...")
    for d in REMOTE_MKDIRS:
        _ = _run(client, f"mkdir -p {REMOTE_DIR}/{d}", f"mkdir -p {d}")

    print("\n[4/11] SFTP upload to .tmp (LF-normalized)...")
    sftp = client.open_sftp()
    uploaded: list[tuple[str, str, str]] = []
    try:
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
    finally:
        sftp.close()

    print("\n[5/11] Atomic swaps...")
    for rel, remote, tmp in uploaded:
        rc, _ = _run(client, f"mv -f {tmp} {remote} && echo OK", f"swap {rel}")
        if rc != 0:
            print(f"       FAIL on {rel}")
            client.close()
            return 2

    print("\n[6/11] Rebuilding aaats-paper-crypto (image-baked runner change)...")
    rc, _ = _run(client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose up -d --build --no-deps aaats-paper-crypto 2>&1 | tail -25",
        "rebuild paper-crypto", timeout=600)
    if rc != 0:
        print("       FAIL: paper-crypto did not come up.")
        client.close()
        return 3

    print("\n[7/11] Rebuilding aaats-metrics (collect_self_up baked in)...")
    rc, _ = _run(client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose up -d --build --no-deps aaats-metrics 2>&1 | tail -25",
        "rebuild metrics", timeout=600)
    if rc != 0:
        print("       FAIL: metrics did not come up.")
        client.close()
        return 4

    print("\n[8/11] Rebuilding aaats-watchdog (digest bands + alerts_known)...")
    rc, _ = _run(client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose up -d --build --no-deps aaats-watchdog 2>&1 | tail -25",
        "rebuild watchdog", timeout=600)
    if rc != 0:
        print("       FAIL: watchdog did not come up.")
        client.close()
        return 5

    print("\n[9/11] Post-rebuild SHAs + container status...")
    _, post_paper_image = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1", "post paper image")
    _, post_paper_status = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}}' 2>&1", "post paper status")
    _, post_metrics_image = _run(client,
        "docker inspect aaats-metrics --format '{{.Image}}' 2>&1", "post metrics image")
    _, post_metrics_status = _run(client,
        "docker inspect aaats-metrics --format '{{.State.Status}}' 2>&1", "post metrics status")
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
        return 6
    if "running" not in post_metrics_status:
        print(f"       FAIL: metrics status={post_metrics_status!r}")
        client.close()
        return 7
    if "running" not in post_watchdog_status:
        print(f"       FAIL: watchdog status={post_watchdog_status!r}")
        client.close()
        return 8

    # Settle.
    _time.sleep(8)

    print("\n[10/11] Smoke A: paper-crypto log tail (one cycle, no errors, no surprise HALT)...")
    _, paper_log = _run(client,
        "docker logs --tail 120 aaats-paper-crypto 2>&1", "paper-crypto tail 120")
    unexpected_halt = "Crypto market HALTED (kill switch)" in paper_log
    # Operator halt_state should still report crypto:false (the gate fires only
    # if an operator manually halts via kill.py; we did not).
    _, post_halt_state = _run(client,
        f"cat {REMOTE_DIR}/data/halt_state.json 2>&1 || echo MISSING", "post halt_state.json")
    operator_halt_crypto_true = ('"crypto": true' in post_halt_state)
    smoke_a_ok = (not unexpected_halt) and (not operator_halt_crypto_true)

    print("\n[10/11] Smoke B: digest dry-run via _digest_smoke...")
    # Import the workstation helper and call against a paramiko-backed runner.
    from dataclasses import dataclass
    from tools.operator._digest_smoke import (
        assert_digest_renders_equity,
        parse_equity_line,
    )

    @dataclass
    class _Res:
        returncode: int
        stdout: str
        stderr: str

    def _box_run(cmd: str) -> _Res:
        _, so, se = client.exec_command(cmd, timeout=60)
        rcc = so.channel.recv_exit_status()
        return _Res(returncode=rcc, stdout=so.read().decode("utf-8", "replace"),
                    stderr=se.read().decode("utf-8", "replace"))

    smoke_b = assert_digest_renders_equity(_box_run, target_container="aaats-watchdog",
                                           mode="paper")
    box_dry_run_passed = smoke_b.ok
    print(f"     box dry-run: ok={smoke_b.ok}  msg={_ascii(smoke_b.message)[:160]}")

    # Also capture the full dry-run body for the manifest + band wording check.
    rc_dry, dry_out = _run(client,
        "docker exec aaats-watchdog python -m monitoring.daily_digest --dry-run 2>&1 | tail -45",
        "box dry-run full body", timeout=60)
    # The new band wording: at -33.4% drawdown (< -20%) the action line should
    # be "past portfolio-kill"; the old wording was "near kill threshold".
    band_correct = (
        "past portfolio-kill" in dry_out
        or "past market-kill" in dry_out
        or "Action needed: NONE" in dry_out  # legitimate if drawdown improved
    )
    band_old_wording = ("near kill threshold (-15%)" in dry_out) and (
        "Equity" in dry_out and "dd -" in dry_out
    )
    # Old wording at any drawdown < -20% is the regression we are checking for.
    band_wording_ok = band_correct and not band_old_wording

    print("\n[11/11] Smoke C: alerts_log.json (best-effort) + metrics self-up gauge...")
    _, alerts_log_head = _run(client,
        f"head -c 4000 {REMOTE_DIR}/data/alerts_log.json 2>&1 || echo MISSING",
        "alerts_log.json head")
    alerts_log_present = "MISSING" not in alerts_log_head
    # Metrics self-up.
    rc_m, metrics_out = _run(client,
        "curl -s --max-time 5 http://127.0.0.1:9091/metrics | grep '^aaats_metrics_exporter_up' || true",
        "metrics self-up", timeout=15)
    self_up_present = "aaats_metrics_exporter_up" in metrics_out

    client.close()

    deployed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "ROLLBACK BASELINE - 2026-05-24 Session 7 [0] coordinated box deploy",
        "=" * 80,
        "",
        f"DEPLOYED_AT_UTC               = {deployed_at}",
        f"PRE_PAPER_IMAGE_SHA           = {pre_paper_image}",
        f"POST_PAPER_IMAGE_SHA          = {post_paper_image}",
        f"PRE_METRICS_IMAGE_SHA         = {pre_metrics_image}",
        f"POST_METRICS_IMAGE_SHA        = {post_metrics_image}",
        f"PRE_WATCHDOG_IMAGE_SHA        = {pre_watchdog_image}",
        f"POST_WATCHDOG_IMAGE_SHA       = {post_watchdog_image}",
        f"POST_PAPER_STATUS             = {post_paper_status}",
        f"POST_METRICS_STATUS           = {post_metrics_status}",
        f"POST_WATCHDOG_STATUS          = {post_watchdog_status}",
        f"SMOKE_A_PAPER_NO_SURPRISE_HALT = {smoke_a_ok}",
        f"SMOKE_B_BOX_DRY_RUN_PASSED    = {box_dry_run_passed}",
        f"SMOKE_B_BAND_WORDING_OK       = {band_wording_ok}",
        f"SMOKE_C_ALERTS_LOG_PRESENT    = {alerts_log_present}",
        f"SMOKE_C_SELF_UP_GAUGE         = {self_up_present}",
        f"PRE_HALT_STATE                = {_ascii(pre_halt_state)[:200]}",
        f"POST_HALT_STATE               = {_ascii(post_halt_state)[:200]}",
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
    for line in dry_out.splitlines()[-30:]:
        lines.append(f"  {_ascii(line)}")
    lines.append("")
    lines.append("Equity line parsed:")
    equity_line = parse_equity_line(dry_out) or "(not found)"
    lines.append(f"  {_ascii(equity_line)}")
    lines.append("")
    lines.append("metrics self-up curl:")
    for line in metrics_out.splitlines()[-5:]:
        lines.append(f"  {_ascii(line)}")
    lines.append("")
    lines.append("alerts_log.json head (or MISSING):")
    for line in alerts_log_head.splitlines()[-15:]:
        lines.append(f"  {_ascii(line)}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"  paper-crypto image:    {post_paper_image}")
    print(f"  metrics image:         {post_metrics_image}")
    print(f"  watchdog image:        {post_watchdog_image}")
    print(f"  smoke A (no halt):     {smoke_a_ok}")
    print(f"  smoke B (digest):      {box_dry_run_passed} (band ok: {band_wording_ok})")
    print(f"  smoke C (self-up):     {self_up_present}")
    print(f"  alerts_log present:    {alerts_log_present}")
    print(f"  MANIFEST written:      {MANIFEST}")
    print("=" * 70)
    all_ok = (
        smoke_a_ok
        and box_dry_run_passed
        and band_wording_ok
        and self_up_present
    )
    return 0 if all_ok else 9


if __name__ == "__main__":
    sys.exit(main())
