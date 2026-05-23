"""
Session 9 deploy [0]: ship session-8 workstation changes to the box.

Session-8 commit e78005e closed the operator-halt MTM gap (split kill gate
into ENTRY/EXIT variants) and chipped 6 silent-except hits. Code was
workstation-only; this script ships it.

Files (all image-baked under aaats-paper-crypto):
  trading/live_paper_runner.py            (gate split + run_*-no-shortcircuit)
  trading/altcoin_reversion.py            (C3 _exit_gate_check wire-up)
  trading/bollinger_range.py              (C6 _exit_gate_check wire-up)
  trading/stat_arb.py                     (C1 exit_gate_check propagation)
  execution/paper_trader.py               (silent-except chip x3)
  execution/status_db.py                  (silent-except chip + logger)
  foundation/mode_manager.py              (silent-except chip)
  diagnostics/d2_ml_dist.py               (silent-except chip)
  tools/lint/silent_except_baseline.txt   (ratchet 77->71)

Rebuild only aaats-paper-crypto with --no-deps. Metrics + watchdog images
unchanged (no surfaces of those touched).

Smoke gates (per session-9 prompt):
  (a) log wording: "OPERATOR HALT - new entries blocked; open positions
      continue to MTM" appears in paper-crypto logs --since 60s (operator
      halt currently set, so the line should fire on first cycle).
  (b) docker exec aaats-paper-crypto python -c
      "from trading.live_paper_runner import apply_kill_switch_exit_gate;
       print(apply_kill_switch_exit_gate)"
      returns a function repr (proves new symbol shipped).
  (c) digest dry-run still renders Equity line non-N/A.

Rollback baseline: .rollback/2026-05-24_session8_operator_halt_gap/MANIFEST.txt

Run:
  venv\\Scripts\\python scripts\\deploy_session8_operator_halt_gap.py [--allow-dirty]
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
    "trading/live_paper_runner.py",
    "trading/altcoin_reversion.py",
    "trading/bollinger_range.py",
    "trading/stat_arb.py",
    "execution/paper_trader.py",
    "execution/status_db.py",
    "foundation/mode_manager.py",
    "diagnostics/d2_ml_dist.py",
    "tools/lint/silent_except_baseline.txt",
]

REMOTE_MKDIRS: list[str] = [
    "trading",
    "execution",
    "foundation",
    "diagnostics",
    "tools/lint",
]

MANIFEST = (
    PROJECT_ROOT
    / ".rollback"
    / "2026-05-24_session8_operator_halt_gap"
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
    parser = argparse.ArgumentParser(description="Session 9 [0] session-8 box deploy")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from tools.operator._dirty_tree_guard import check_clean
    check_clean(FILES, allow_dirty=args.allow_dirty)

    print("=" * 70)
    print("  Session 9 deploy [0] -> session-8 workstation changes")
    print(f"  Target: {USER}@{HOST}:{REMOTE_DIR}/<{len(FILES)} files>")
    print("  Rebuild: aaats-paper-crypto only (--no-deps)")
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
    _, pre_halt_state = _run(client,
        f"cat {REMOTE_DIR}/data/halt_state.json 2>&1 || echo MISSING", "pre halt_state.json")
    pre_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client,
            f"sha256sum {REMOTE_DIR}/{rel} 2>&1 || echo 'ABSENT {rel}'", f"pre SHA {rel}")
        pre_shas[rel] = out.split()[0] if rc == 0 and "ABSENT" not in out else "ABSENT"

    print("\n[3/10] mkdir -p parent dirs (defensive)...")
    for d in REMOTE_MKDIRS:
        _ = _run(client, f"mkdir -p {REMOTE_DIR}/{d}", f"mkdir -p {d}")

    print("\n[4/10] SFTP upload to .tmp (LF-normalized)...")
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

    print("\n[5/10] Atomic swaps...")
    for rel, remote, tmp in uploaded:
        rc, _ = _run(client, f"mv -f {tmp} {remote} && echo OK", f"swap {rel}")
        if rc != 0:
            print(f"       FAIL on {rel}")
            client.close()
            return 2

    print("\n[6/10] Rebuilding aaats-paper-crypto (--no-deps)...")
    rc, _ = _run(client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose up -d --build --no-deps aaats-paper-crypto 2>&1 | tail -25",
        "rebuild paper-crypto", timeout=600)
    if rc != 0:
        print("       FAIL: paper-crypto did not come up.")
        client.close()
        return 3

    print("\n[7/10] Post-rebuild SHAs + container status...")
    _, post_paper_image = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1", "post paper image")
    _, post_paper_status = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}}' 2>&1", "post paper status")
    post_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client, f"sha256sum {REMOTE_DIR}/{rel}", f"post SHA {rel}")
        post_shas[rel] = out.split()[0] if rc == 0 else "(failed)"

    if "running" not in post_paper_status:
        print(f"       FAIL: paper-crypto status={post_paper_status!r}")
        client.close()
        return 4

    # Settle: give the runner ~80s so at least one full crypto-cycle log line
    # under the new gate semantics has been emitted.
    print("\n[8/10] Settling 80s for one full cycle under new gate semantics...")
    _time.sleep(80)

    print("\n[9/10] Smoke gates...")

    # Gate (a): expect the new OPERATOR HALT wording in recent logs
    # (operator halt currently set per pre_halt_state crypto:true).
    _, recent_log = _run(client,
        "docker logs --since 90s aaats-paper-crypto 2>&1", "paper-crypto logs --since 90s")
    new_wording = (
        "OPERATOR HALT" in recent_log
        and "new entries blocked" in recent_log
        and "open positions continue to MTM" in recent_log
    )
    old_shortcircuit_wording = "Crypto market HALTED (kill switch)" in recent_log
    smoke_a_ok = new_wording and not old_shortcircuit_wording

    # Gate (b): new symbol exists in shipped runner module
    rc_sym, sym_out = _run(client,
        "docker exec aaats-paper-crypto python -c "
        "\"from trading.live_paper_runner import apply_kill_switch_exit_gate; "
        "print(apply_kill_switch_exit_gate)\" 2>&1",
        "import apply_kill_switch_exit_gate", timeout=30)
    smoke_b_ok = (rc_sym == 0) and ("function apply_kill_switch_exit_gate" in sym_out)

    # Gate (c): digest dry-run still renders Equity line non-N/A
    rc_dry, dry_out = _run(client,
        "docker exec aaats-watchdog python -m monitoring.daily_digest --dry-run 2>&1 | tail -40",
        "digest dry-run", timeout=60)
    equity_present = False
    for line in dry_out.splitlines():
        if line.lstrip().startswith("Equity") and "N/A" not in line:
            equity_present = True
            break
    smoke_c_ok = (rc_dry == 0) and equity_present

    # Gate (d): C3/C6/C1 exit-gate symbols also import cleanly under the new alias
    rc_chk, chk_out = _run(client,
        "docker exec aaats-paper-crypto python -c "
        "\"from trading.altcoin_reversion import _exit_gate_check as a; "
        "from trading.bollinger_range import _exit_gate_check as b; "
        "from trading.stat_arb import _exit_gate_check as c; "
        "print('C3=', a is not None, 'C6=', b is not None, 'C1=', c is not None)\" 2>&1",
        "strategy exit-gate imports", timeout=30)
    smoke_d_ok = (rc_chk == 0) and ("C3= True" in chk_out) and ("C6= True" in chk_out) and ("C1= True" in chk_out)

    client.close()

    deployed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "ROLLBACK BASELINE - 2026-05-24 Session 9 [0] session-8 box deploy",
        "=" * 80,
        "",
        f"DEPLOYED_AT_UTC               = {deployed_at}",
        f"PRE_PAPER_IMAGE_SHA           = {pre_paper_image}",
        f"POST_PAPER_IMAGE_SHA          = {post_paper_image}",
        f"POST_PAPER_STATUS             = {post_paper_status}",
        f"SMOKE_A_NEW_WORDING           = {smoke_a_ok}",
        f"SMOKE_B_EXIT_GATE_IMPORT      = {smoke_b_ok}",
        f"SMOKE_C_DIGEST_EQUITY         = {smoke_c_ok}",
        f"SMOKE_D_STRATEGY_IMPORTS      = {smoke_d_ok}",
        f"PRE_HALT_STATE                = {_ascii(pre_halt_state)[:200]}",
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
    lines.append("Smoke (a) recent log tail:")
    for line in recent_log.splitlines()[-25:]:
        lines.append(f"  {_ascii(line)}")
    lines.append("")
    lines.append("Smoke (b) symbol import output:")
    for line in sym_out.splitlines()[-5:]:
        lines.append(f"  {_ascii(line)}")
    lines.append("")
    lines.append("Smoke (c) digest dry-run tail:")
    for line in dry_out.splitlines()[-25:]:
        lines.append(f"  {_ascii(line)}")
    lines.append("")
    lines.append("Smoke (d) strategy imports output:")
    for line in chk_out.splitlines()[-5:]:
        lines.append(f"  {_ascii(line)}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"  paper-crypto image:       {post_paper_image}")
    print(f"  smoke A (new wording):    {smoke_a_ok}")
    print(f"  smoke B (exit-gate sym):  {smoke_b_ok}")
    print(f"  smoke C (digest equity):  {smoke_c_ok}")
    print(f"  smoke D (strat imports):  {smoke_d_ok}")
    print(f"  MANIFEST written:         {MANIFEST}")
    print("=" * 70)
    all_ok = smoke_a_ok and smoke_b_ok and smoke_c_ok and smoke_d_ok
    return 0 if all_ok else 9


if __name__ == "__main__":
    sys.exit(main())
