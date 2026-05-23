"""
Hotfix deploy: 2026-05-23 phantom-position incident.

Ships the phantom-position fix from commit c71291e/11b0874 and recovers
the running soak from a state where:
  - paper_trades.db has the broken init_db schema (id INTEGER)
  - altcoin_reversion_state.json holds an orphan ENA/USDT position
  - operator halt is engaged on crypto
  - reconciler halts every cycle on the orphan
  - container is in a restart-loop

The d5_day1_marker.json is PRESERVED (soak baseline stays 2026-05-23T12:46:32Z).
The watcher's pnl_since_day1 will read $0.00 (no trades survived), which is
factually correct for the recovered state.

Steps:
  1. SCP fixed source files.
  2. docker compose stop + rm paper-crypto + watchdog (so volume + DB file
     locks release cleanly).
  3. Archive the broken paper_trades.db + altcoin_reversion_state.json
     (rename to .pre_hotfix_<ts>) for forensic preservation.
  4. Run scripts/init_db.py against /app/data/paper_trades.db to create a
     fresh table with the CORRECT schema (id TEXT PRIMARY KEY).
  5. Clear operator halt on crypto.
  6. docker compose up --build --no-deps paper-crypto + watchdog.
  7. Wait ~60s for first cycle.
  8. Verify: container running healthy, no reconciler halt, halt_state.json
     crypto=false, d5_day1_marker.json preserved.

Rollback baseline: .rollback/2026-05-23_session11_hotfix_orphan_position/MANIFEST.txt
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
    "scripts/init_db.py",
    "execution/paper_trader.py",
    "trading/altcoin_reversion.py",
    "trading/bollinger_range.py",
    "trading/stat_arb.py",
]

REMOTE_MKDIRS: list[str] = ["scripts", "execution", "trading"]

MANIFEST = (
    PROJECT_ROOT
    / ".rollback"
    / "2026-05-23_session11_hotfix_orphan_position"
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
    for line in out.splitlines()[-20:]:
        print(f"     {_ascii(line)}")
    if rc != 0 and err:
        for line in err.splitlines()[-5:]:
            print(f"     ERR: {_ascii(line)}")
    return rc, out


def main() -> int:
    parser = argparse.ArgumentParser(description="Session 11 [hotfix] phantom-position deploy")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from tools.operator._dirty_tree_guard import check_clean
    check_clean(FILES, allow_dirty=args.allow_dirty)

    print("=" * 70)
    print("  Session 11 [hotfix] -> phantom-position fix")
    print(f"  Target: {USER}@{HOST}:{REMOTE_DIR}/<{len(FILES)} files>")
    print("  Rebuild: aaats-paper-crypto + aaats-watchdog (--no-deps)")
    print("  Recovery: wipe broken paper_trades.db + orphan altcoin state")
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
    print(f"\n[1/12] Connecting to {HOST}...")
    client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    print("       Connected")

    archive_ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print("\n[2/12] Pre-deploy state capture...")
    _, pre_paper_image = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1", "pre paper image")
    _, pre_watchdog_image = _run(client,
        "docker inspect aaats-watchdog --format '{{.Image}}' 2>&1", "pre watchdog image")
    _, pre_halt_state = _run(client,
        f"cat {REMOTE_DIR}/data/halt_state.json 2>&1 || echo MISSING", "pre halt_state.json")
    pre_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client,
            f"sha256sum {REMOTE_DIR}/{rel} 2>&1 || echo 'ABSENT {rel}'", f"pre SHA {rel}")
        pre_shas[rel] = out.split()[0] if rc == 0 and "ABSENT" not in out else "ABSENT"

    print("\n[3/12] mkdir -p parent dirs (defensive)...")
    for d in REMOTE_MKDIRS:
        _ = _run(client, f"mkdir -p {REMOTE_DIR}/{d}", f"mkdir -p {d}")

    print("\n[4/12] SFTP upload to .tmp (LF-normalized)...")
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

    print("\n[5/12] Atomic swaps...")
    for rel, remote, tmp in uploaded:
        rc, _ = _run(client, f"mv -f {tmp} {remote} && echo OK", f"swap {rel}")
        if rc != 0:
            print(f"       FAIL on {rel}")
            client.close()
            return 2

    print("\n[6/12] Stop + rm paper-crypto + watchdog...")
    rc, _ = _run(client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose stop aaats-paper-crypto aaats-watchdog && "
        "docker compose rm -f -s aaats-paper-crypto aaats-watchdog",
        "stop + rm containers")
    if rc != 0:
        print("       FAIL: containers did not stop cleanly")
        client.close()
        return 3

    print("\n[7/12] Archive broken state files...")
    _run(client,
        f"if [ -e {REMOTE_DIR}/data/paper_trades.db ]; then "
        f"  mv -f {REMOTE_DIR}/data/paper_trades.db "
        f"     {REMOTE_DIR}/data/paper_trades.db.pre_hotfix_{archive_ts}; "
        f"  echo archived paper_trades.db; "
        f"else echo paper_trades.db absent; fi",
        f"archive paper_trades.db (broken schema)")
    _run(client,
        f"if [ -e {REMOTE_DIR}/data/altcoin_reversion_state.json ]; then "
        f"  mv -f {REMOTE_DIR}/data/altcoin_reversion_state.json "
        f"     {REMOTE_DIR}/data/altcoin_reversion_state.json.pre_hotfix_{archive_ts}; "
        f"  echo archived altcoin_reversion_state.json; "
        f"else echo altcoin_reversion_state.json absent; fi",
        f"archive altcoin_reversion_state.json (orphan ENA)")
    # Also archive paper_positions.json + bollinger_range_state.json
    # to be safe (any reconciler-relevant state in the bind mount).
    _run(client,
        f"if [ -e {REMOTE_DIR}/data/paper_positions.json ]; then "
        f"  mv -f {REMOTE_DIR}/data/paper_positions.json "
        f"     {REMOTE_DIR}/data/paper_positions.json.pre_hotfix_{archive_ts}; fi",
        "archive paper_positions.json")
    _run(client,
        f"if [ -e {REMOTE_DIR}/data/bollinger_range_state.json ]; then "
        f"  mv -f {REMOTE_DIR}/data/bollinger_range_state.json "
        f"     {REMOTE_DIR}/data/bollinger_range_state.json.pre_hotfix_{archive_ts}; fi",
        "archive bollinger_range_state.json")
    # Reconciler may have left a halt note in strategy_halt_state — clear it
    # so C3 isn't permanently halted post-recovery.
    _run(client,
        f"if [ -e {REMOTE_DIR}/data/strategy_halt_state.json ]; then "
        f"  mv -f {REMOTE_DIR}/data/strategy_halt_state.json "
        f"     {REMOTE_DIR}/data/strategy_halt_state.json.pre_hotfix_{archive_ts}; fi",
        "archive strategy_halt_state.json")

    print("\n[8/12] Clear operator halt on crypto (write halt_state.json directly)...")
    sftp = client.open_sftp()
    try:
        with sftp.open(f"{REMOTE_DIR}/data/halt_state.json.tmp", "w") as fh:
            fh.write('{"us": true, "india": true, "crypto": false}\n')
    finally:
        sftp.close()
    _run(client,
        f"mv -f {REMOTE_DIR}/data/halt_state.json.tmp {REMOTE_DIR}/data/halt_state.json",
        "atomic-swap halt_state.json (crypto: false)")

    print("\n[9/12] Rebuild aaats-paper-crypto + aaats-watchdog (--no-deps, --build)...")
    rc, _ = _run(client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose up -d --build --no-deps aaats-paper-crypto aaats-watchdog "
        "2>&1 | tail -30",
        "rebuild paper-crypto + watchdog", timeout=900)
    if rc != 0:
        print("       FAIL: containers did not come up")
        client.close()
        return 4

    print("\n[10/12] Settling 90s for one full cycle...")
    _time.sleep(90)

    print("\n[11/12] Post-rebuild verification...")
    _, post_paper_image = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1", "post paper image")
    _, post_watchdog_image = _run(client,
        "docker inspect aaats-watchdog --format '{{.Image}}' 2>&1", "post watchdog image")
    _, post_paper_status = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}} health={{.State.Health.Status}} restart={{.RestartCount}}' 2>&1",
        "post paper status")
    _, post_watchdog_status = _run(client,
        "docker inspect aaats-watchdog --format '{{.State.Status}}' 2>&1",
        "post watchdog status")
    _, post_halt_state = _run(client,
        f"cat {REMOTE_DIR}/data/halt_state.json", "post halt_state.json")
    _, marker_check = _run(client,
        f"cat {REMOTE_DIR}/data/d5_day1_marker.json", "d5_day1_marker.json preserved")
    _, recon_check = _run(client,
        "docker logs --since 90s aaats-paper-crypto 2>&1 | grep -iE 'reconcil|orphan|critical' | tail -10",
        "reconciler tail (should NOT show HALTED)")
    _, schema_check = _run(client,
        "docker exec aaats-paper-crypto python -c "
        "\"import sqlite3; c=sqlite3.connect('file:/app/data/paper_trades.db?mode=ro', uri=True); "
        "cols=[r[1] for r in c.execute('PRAGMA table_info(paper_trades)').fetchall()]; "
        "ok='value' in cols and 'risk_action' in cols; "
        "print(f'schema_complete={ok} cols={cols}')\"",
        "post-fix schema check")
    post_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client, f"sha256sum {REMOTE_DIR}/{rel}", f"post SHA {rel}")
        post_shas[rel] = out.split()[0] if rc == 0 else "(failed)"

    paper_ok = "running" in post_paper_status and "restart=0" in post_paper_status
    watchdog_ok = "running" in post_watchdog_status
    halt_ok = '"crypto": false' in post_halt_state
    marker_ok = "divergence_watcher_armed" in marker_check and "true" in marker_check
    recon_ok = "RECONCILIATION HALTED" not in recon_check
    schema_ok = "schema_complete=True" in schema_check

    client.close()

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    deployed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "ROLLBACK BASELINE - 2026-05-23 Session 11 [hotfix] phantom-position",
        "=" * 80,
        "",
        f"DEPLOYED_AT_UTC               = {deployed_at}",
        f"ARCHIVE_TS_SUFFIX             = .pre_hotfix_{archive_ts}",
        f"PRE_PAPER_IMAGE_SHA           = {pre_paper_image}",
        f"POST_PAPER_IMAGE_SHA          = {post_paper_image}",
        f"PRE_WATCHDOG_IMAGE_SHA        = {pre_watchdog_image}",
        f"POST_WATCHDOG_IMAGE_SHA       = {post_watchdog_image}",
        f"POST_PAPER_STATUS             = {post_paper_status}",
        f"POST_WATCHDOG_STATUS          = {post_watchdog_status}",
        f"GATE_PAPER_RUNNING            = {paper_ok}",
        f"GATE_WATCHDOG_RUNNING         = {watchdog_ok}",
        f"GATE_OPERATOR_HALT_CLEAR      = {halt_ok}",
        f"GATE_D5_MARKER_PRESERVED      = {marker_ok}",
        f"GATE_RECONCILER_CLEAN         = {recon_ok}",
        f"GATE_SCHEMA_COMPLETE          = {schema_ok}",
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
    lines.append("Reconciler tail (post-rebuild):")
    for line in recon_check.splitlines()[-15:]:
        lines.append(f"  {_ascii(line)}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"  paper-crypto image:       {post_paper_image}")
    print(f"  watchdog image:           {post_watchdog_image}")
    print(f"  GATE paper running:       {paper_ok}")
    print(f"  GATE watchdog running:    {watchdog_ok}")
    print(f"  GATE operator-halt clear: {halt_ok}")
    print(f"  GATE d5 marker preserved: {marker_ok}")
    print(f"  GATE reconciler clean:    {recon_ok}")
    print(f"  GATE schema complete:     {schema_ok}")
    print(f"  MANIFEST written:         {MANIFEST}")
    print("=" * 70)
    all_ok = paper_ok and watchdog_ok and halt_ok and marker_ok and recon_ok and schema_ok
    return 0 if all_ok else 9


if __name__ == "__main__":
    sys.exit(main())
