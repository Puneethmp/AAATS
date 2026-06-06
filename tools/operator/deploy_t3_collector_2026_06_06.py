#!/usr/bin/env python3
"""Deploy the T3 positioning collector (Reactivation, 2026-06-06).

Installs scripts/box/aaats-t3-oi-collector.py + its U30 symbol list on the box and
schedules it hourly via crontab. The collector forward-captures OI + premium-index
snapshots into an append-only SQLite (/home/aaats/t3/t3_positioning.db) so the
DATA-GATED T3 thesis (pre-reg §3 T3) can be backtested once >=9 months accumulate.

deploy_lib discipline (gotchas catalogue):
  - enforce_utf8_console (#4); atomic_upload_normalized (#1/#2/#9);
  - verify_telegram_path BEFORE the crontab change (#11), send_telegram_message around it.

Additive + maintenance-safe: touches NOTHING in the trading containers, the D.5 soak,
or origin/main runtime. Just a new stdlib cron on the box.

    python tools/operator/deploy_t3_collector_2026_06_06.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import paramiko

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
from tools.operator import deploy_lib as dl  # noqa: E402

dl.enforce_utf8_console()

BIN_DIR = "/home/aaats/bin"
T3_DIR = "/home/aaats/t3"
COLLECTOR_LOCAL = _REPO_ROOT / "scripts" / "box" / "aaats-t3-oi-collector.py"
SYMS_LOCAL = _REPO_ROOT / "scripts" / "box" / "t3_u30_symbols.txt"
COLLECTOR_REMOTE = f"{BIN_DIR}/aaats-t3-oi-collector.py"
SYMS_REMOTE = f"{BIN_DIR}/t3_u30_symbols.txt"
CRON_MARKER = "AAATS-T3-COLLECTOR"
CRON_LINE = (
    f"7 * * * * /usr/bin/python3 {COLLECTOR_REMOTE} "
    f">> {T3_DIR}/collector.log 2>&1  # {CRON_MARKER}"
)
CHANGE_ID = "2026-06-06_t3_oi_collector"


def _load_env(env_path: Path) -> dict:
    out = {}
    if not env_path.exists():
        return out
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _run(client, cmd: str, timeout: int = 120) -> tuple[int, str, str]:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    return (
        rc,
        stdout.read().decode(errors="replace"),
        stderr.read().decode(errors="replace"),
    )


def main() -> int:
    if not COLLECTOR_LOCAL.exists() or not SYMS_LOCAL.exists():
        print("FATAL: collector or symbol list missing locally", file=sys.stderr)
        return 2

    env = _load_env(_REPO_ROOT / ".env")
    host = env.get("CONTABO__SSH_HOST", "100.95.126.39")
    user = env.get("CONTABO__SSH_USER", "aaats")
    password = env.get("CONTABO__SSH_PASSWORD")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        username=user,
        password=password,
        timeout=20,
        allow_agent=True,
        look_for_keys=True,
    )
    print(f"connected {user}@{host}")

    # verify Telegram BEFORE the crontab change (#11)
    if not dl.verify_telegram_path(client):
        client.close()
        raise SystemExit("Telegram smoke-test FAILED — aborting before cron install.")
    print("telegram path OK")

    _run(client, f"mkdir -p {BIN_DIR} {T3_DIR}")
    dl.send_telegram_message(
        client,
        f"AAATS deploy START: {CHANGE_ID} — installing hourly T3 OI/premium "
        f"collector (data-gated thesis forward-capture).",
    )

    sftp = client.open_sftp()
    s1 = dl.atomic_upload_normalized(sftp, COLLECTOR_LOCAL, COLLECTOR_REMOTE)
    s2 = dl.atomic_upload_normalized(sftp, SYMS_LOCAL, SYMS_REMOTE)
    sftp.close()
    _run(client, f"chmod +x {COLLECTOR_REMOTE}")
    print(f"uploaded collector (sha16={s1}) + symbols (sha16={s2})")

    # idempotent crontab install (marker-guarded)
    cron_install = (
        "crontab -l 2>/dev/null > /tmp/aaats_ct.$$ || true; "
        f"if grep -q '{CRON_MARKER}' /tmp/aaats_ct.$$; then echo CRON_EXISTS; "
        f"else printf '%s\\n' \"{CRON_LINE}\" >> /tmp/aaats_ct.$$ && "
        "crontab /tmp/aaats_ct.$$ && echo CRON_INSTALLED; fi; "
        "rm -f /tmp/aaats_ct.$$"
    )
    rc, out, err = _run(client, cron_install)
    print(f"crontab: {out.strip()} {err.strip()}")

    # one synchronous test tick — must write rows
    print("running one test tick...")
    rc, out, err = _run(client, f"/usr/bin/python3 {COLLECTOR_REMOTE}", timeout=120)
    print((out + err).strip()[-500:])

    rc2, cnt, _ = _run(
        client,
        f'/usr/bin/python3 -c "import sqlite3;'
        f"c=sqlite3.connect('{T3_DIR}/t3_positioning.db');"
        f"print('rows=',c.execute('select count(*) from oi_snapshots').fetchone()[0],"
        f"'symbols=',c.execute('select count(distinct symbol) from oi_snapshots').fetchone()[0])\"",
    )
    cnt = cnt.strip()
    print(f"db check: {cnt}")

    rc3, crontab_now, _ = _run(client, "crontab -l 2>/dev/null | grep T3 || true")
    ok = (
        rc == 0
        and "rows=" in cnt
        and "rows= 0" not in cnt
        and CRON_MARKER in crontab_now
    )
    dl.send_telegram_message(
        client,
        f"AAATS deploy {'OK' if ok else 'WARN'}: {CHANGE_ID} — T3 collector installed, "
        f"hourly cron {'active' if CRON_MARKER in crontab_now else 'MISSING'}. "
        f"first tick: {cnt}.",
    )
    client.close()
    if not ok:
        print("DEPLOY WARN — verify manually", file=sys.stderr)
        return 1
    print("DEPLOY OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
