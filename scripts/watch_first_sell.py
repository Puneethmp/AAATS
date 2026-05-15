"""
Watch aaats-paper-crypto logs for the first natural SELL post-deploy.

Polls `docker logs --since <since>` every 30s. When a `PAPER SELL ...`
line appears, prints it + the matching BUY row's shares from
data/paper_trades.db, plus the WARN line iff the share-assertion fired.
Exits 0 on first detected SELL.

Run: venv\\Scripts\\python scripts\\watch_first_sell.py
"""
from __future__ import annotations

import pathlib
import re
import sys
import time

import paramiko

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_env(path: pathlib.Path) -> dict[str, str]:
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

SINCE = "10m"  # initial lookback; subsequent polls reset to most-recent-window
POLL_SEC = 30
MAX_WAIT_SEC = 3600  # one hour ceiling, then bail with rc=2

# match: "PAPER SELL TON/USDT @ 2.0780 x1.513140 | strat=C3_altcoin_reversion | ..."
SELL_RE = re.compile(
    r"PAPER SELL ([^ ]+) @ ([\d.]+) x([\d.]+).*strat=(\S+)"
)
WARN_RE = re.compile(r"SELL/BUY share mismatch")


def _ssh() -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    return c


def _run(c: paramiko.SSHClient, cmd: str) -> str:
    _, stdout, _ = c.exec_command(cmd, timeout=120)
    stdout.channel.recv_exit_status()
    return stdout.read().decode(errors="replace")


def _verify_in_db(c: paramiko.SSHClient, symbol: str, strategy: str) -> str:
    py = (
        "import sqlite3,json;"
        "c=sqlite3.connect('/app/data/paper_trades.db');"
        f"sells=c.execute(\"SELECT shares,timestamp FROM paper_trades WHERE strategy=? AND symbol=? AND action='SELL' ORDER BY timestamp DESC, id DESC LIMIT 1\", ({strategy!r}, {symbol!r})).fetchall();"
        f"ns=c.execute(\"SELECT COUNT(*) FROM paper_trades WHERE strategy=? AND symbol=? AND action='SELL'\", ({strategy!r}, {symbol!r})).fetchone()[0];"
        f"buys=c.execute(\"SELECT shares,timestamp FROM paper_trades WHERE strategy=? AND symbol=? AND action='BUY' ORDER BY timestamp ASC, id ASC LIMIT 1 OFFSET ?\", ({strategy!r}, {symbol!r}, ns-1)).fetchall();"
        "print(json.dumps({'sell':sells[0] if sells else None, 'fifo_buy':buys[0] if buys else None, 'n_sells':ns}))"
    )
    return _run(c, f'docker exec aaats-paper-crypto python -c "{py}"').strip()


def main() -> int:
    print("[watch] connecting...")
    c = _ssh()
    print(f"[watch] connected. Polling docker logs every {POLL_SEC}s (max {MAX_WAIT_SEC}s)")

    waited = 0
    while waited < MAX_WAIT_SEC:
        logs = _run(
            c,
            f"docker logs aaats-paper-crypto --since {SINCE} 2>&1 | grep -E 'PAPER SELL|SELL/BUY share mismatch' || true",
        )
        sell_lines = [ln for ln in logs.splitlines() if "PAPER SELL" in ln]
        warn_lines = [ln for ln in logs.splitlines() if WARN_RE.search(ln)]

        if sell_lines:
            print("\n========== FIRST POST-DEPLOY SELL ==========")
            print(sell_lines[0])
            m = SELL_RE.search(sell_lines[0])
            if m:
                symbol, price, shares, strategy = m.group(1), m.group(2), m.group(3), m.group(4)
                print(f"\nparsed: symbol={symbol} strategy={strategy} sell_price={price} sell_shares={shares}")
                print("\n[db check]")
                db_json = _verify_in_db(c, symbol, strategy)
                print(db_json)
                try:
                    import json as _json
                    payload = _json.loads(db_json)
                    sell_row = payload.get("sell")
                    buy_row = payload.get("fifo_buy")
                    if sell_row and buy_row:
                        s_shares = float(sell_row[0]); b_shares = float(buy_row[0])
                        print(
                            f"\n[delta] sell_shares={s_shares!r} fifo_buy_shares={b_shares!r} "
                            f"delta={abs(s_shares - b_shares):.12f} "
                            f"sell_ts={sell_row[1]} buy_ts={buy_row[1]}"
                        )
                except Exception as e:
                    print(f"[delta] could not compute delta: {e}")
            if warn_lines:
                print("\n!!!!! SELL/BUY share-assertion WARN fired !!!!!")
                for w in warn_lines:
                    print(w)
            else:
                print("\nshare-assertion: NO WARN — equality holds on first SELL.")
            c.close()
            return 0

        time.sleep(POLL_SEC)
        waited += POLL_SEC
        print(f"[watch] no SELL yet ({waited}s elapsed)")

    print(f"\n[watch] timed out after {MAX_WAIT_SEC}s with no SELL.")
    c.close()
    return 2


if __name__ == "__main__":
    sys.exit(main())
