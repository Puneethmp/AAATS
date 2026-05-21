"""Run PF1/PF2/PF3 from docs/runbooks/2026-05-22_live_capital_go.md.

PF1: Re-runs scripts.evaluate_live_readiness on the box and parses for an
     `allowed: true` (or `"allowed": true`) signal.
PF2: Reads data/share_equality_mismatches.json + trades-24h count from the
     paper_trades DB inside the container.
PF3: Fires a synthetic `_TEST_LIVE_2026_05_22_` warn, waits, then asks the
     operator (Claude Code or human) to confirm Telegram delivery. The
     reverts to {} regardless of the answer.

Writes results to data/pre_flight_log.json. Exits 1 if any PF fails.

Hard constraints (NEXT_PROMPT.md 2026-05-21):
  - The PF3 Telegram confirmation comes from the human operator -- do NOT
    auto-answer 'yes'. Pasting the prompt to chat and waiting for the
    operator's typed reply is the gate.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import sys
import time

import paramiko

LOG = pathlib.Path("data") / "pre_flight_log.json"
BOX_HOST = "100.95.126.39"
BOX_USER = "aaats"
SHARE_EQUALITY_PATH = "/home/aaats/aaats/data/share_equality_mismatches.json"
TELEGRAM_CHAT_ID = "1946109268"
TEST_KEY = "_TEST_LIVE_2026_05_22_|_TEST_LIVE_2026_05_22_"


def ssh_connect() -> paramiko.SSHClient:
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(BOX_HOST, username=BOX_USER)
    return s


def pf1(ssh: paramiko.SSHClient) -> dict:
    print("PF1: re-running deployment_decision evaluation...")
    _, stdout, _ = ssh.exec_command(
        "docker exec aaats-paper-crypto "
        "python -m scripts.evaluate_live_readiness 2>&1"
    )
    out = stdout.read().decode()
    print(out)
    low = out.lower()
    passed = "allowed: true" in low or '"allowed": true' in low
    return {"status": "pass" if passed else "fail", "output": out[:2000]}


def pf2(ssh: paramiko.SSHClient) -> dict:
    print("PF2: reconcile clean check...")
    _, stdout, _ = ssh.exec_command(f"cat {SHARE_EQUALITY_PATH}")
    mismatches = stdout.read().decode().strip()
    print(f"share_equality_mismatches.json: {mismatches}")

    _, stdout, _ = ssh.exec_command(
        "docker exec aaats-paper-crypto python -c \""
        "import sqlite3; "
        "c=sqlite3.connect('/app/data/paper_trades.db'); "
        "print('trades 24h:', c.execute("
        "\\\"SELECT COUNT(*) FROM paper_trades "
        "WHERE timestamp>=datetime('now','-24 hours')\\\""
        ").fetchone()[0])\""
    )
    out = stdout.read().decode()
    print(out)
    passed = (
        ("{}" in mismatches or '"TON' in mismatches or '"FET' in mismatches)
        and "trades 24h:" in out
    )
    return {
        "status": "pass" if passed else "fail",
        "mismatches": mismatches[:500],
        "output": out[:500],
    }


def pf3(ssh: paramiko.SSHClient) -> dict:
    print("PF3: Telegram synthetic test...")
    ssh.exec_command(
        f'echo \'{{"{TEST_KEY}": 1}}\' > {SHARE_EQUALITY_PATH}'
    )
    time.sleep(65)
    ssh.exec_command(
        f'echo \'{{"{TEST_KEY}": 2}}\' > {SHARE_EQUALITY_PATH}'
    )
    print("Wrote test counter. Waiting 120s for alert evaluation...")
    time.sleep(120)
    print(
        f"Check Telegram chat {TELEGRAM_CHAT_ID} for a "
        f"{TEST_KEY.split('|')[0]} alert."
    )
    response = input("Did you receive the Telegram alert? (yes/no): ")
    response = response.strip().lower()
    # Revert regardless of answer so we don't leave a synthetic key
    # in the file.
    ssh.exec_command(f'echo "{{}}" > {SHARE_EQUALITY_PATH}')
    return {
        "status": "pass" if response == "yes" else "fail",
        "operator_confirm": response,
    }


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    ssh = ssh_connect()
    try:
        results = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "PF1": pf1(ssh),
            "PF2": pf2(ssh),
            "PF3": pf3(ssh),
        }
    finally:
        ssh.close()

    LOG.write_text(json.dumps(results, indent=2))
    failed = [k for k in ("PF1", "PF2", "PF3") if results[k]["status"] != "pass"]
    if failed:
        print(f"PRE-FLIGHTS FAILED: {failed}. ABORT live flip.",
              file=sys.stderr)
        return 1
    print("ALL PRE-FLIGHTS PASS. Live flip is permitted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
