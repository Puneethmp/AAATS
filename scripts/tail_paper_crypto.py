"""Tail aaats-paper-crypto logs through the first N cycles after live flip.

Streams docker logs and watches for:
  - cycle-banner lines (``== Crypto cycle done | capital=USD <X> ==``).
  - HALT events not associated with a synthetic test.
  - [ERROR] / Exception / Traceback lines.

Exits 0 if TARGET_CYCLES clean cycles complete inside TIMEOUT_MIN minutes
with zero HALT events and <= 5 transient errors. Otherwise exits 1.

Writes data/first_cycles_log.json with the observed counts.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import time

import paramiko

CYCLE_BANNER = re.compile(r"==.*Crypto cycle.*?capital=USD\s*([\d.]+)")
HALT_PATTERN = re.compile(r"HALT|RISK HALT", re.I)
ERROR_PATTERN = re.compile(r"\[ERROR\]|Exception|Traceback")

TARGET_CYCLES = 4
TIMEOUT_MIN = 90
MAX_ERRORS = 5
LOG_PATH = pathlib.Path("data") / "first_cycles_log.json"
BOX_HOST = "100.95.126.39"
BOX_USER = "aaats"
CONTAINER = "aaats-paper-crypto"


def main() -> int:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(BOX_HOST, username=BOX_USER)

    print(
        f"Tailing {CONTAINER} logs for up to {TIMEOUT_MIN}min, "
        f"looking for {TARGET_CYCLES} clean cycles..."
    )
    cycles_seen = 0
    halts_seen = 0
    errors_seen = 0
    last_capital: float | None = None
    start = time.time()

    _, stdout, _ = ssh.exec_command(
        f"docker logs -f --tail 50 {CONTAINER}"
    )
    try:
        while time.time() - start < TIMEOUT_MIN * 60:
            line = stdout.readline()
            if not line:
                break
            line = line.strip()

            m = CYCLE_BANNER.search(line)
            if m:
                cycles_seen += 1
                last_capital = float(m.group(1))
                print(
                    f"[cycle {cycles_seen}/{TARGET_CYCLES}] "
                    f"capital=${last_capital}"
                )
                if cycles_seen >= TARGET_CYCLES:
                    break

            if HALT_PATTERN.search(line) and "test" not in line.lower():
                halts_seen += 1
                print(f"[HALT DETECTED] {line}")

            if ERROR_PATTERN.search(line):
                errors_seen += 1
                print(f"[ERROR] {line}")
    finally:
        ssh.close()

    result = {
        "cycles_seen": cycles_seen,
        "halts_seen": halts_seen,
        "errors_seen": errors_seen,
        "last_capital": last_capital,
        "target_cycles": TARGET_CYCLES,
        "timeout_min": TIMEOUT_MIN,
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(result, indent=2))

    if (halts_seen > 0
            or errors_seen > MAX_ERRORS
            or cycles_seen < TARGET_CYCLES):
        print(f"FAIL: {result}", file=sys.stderr)
        return 1

    print(f"PASS: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
