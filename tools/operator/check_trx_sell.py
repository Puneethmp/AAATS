"""Read the C6 TRX/USDT BUY/SELL pair from the live DB and print exact shares."""
from __future__ import annotations

import pathlib
import paramiko

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

def _env(p):
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().split("#")[0].strip()
    return out

e = _env(PROJECT_ROOT / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    e.get("CONTABO__TAILSCALE_IP", "100.95.126.39"),
    port=22,
    username=e.get("CONTABO__SSH_USER", "aaats"),
    password=e.get("CONTABO__SSH_PASSWORD", ""),
    timeout=30,
)

# Write a small python helper into the container then exec it — avoids shell escaping hell.
helper = r'''
import sqlite3, json
c = sqlite3.connect("/app/data/paper_trades.db")
STRAT = "C6_bollinger_range"
SYM   = "TRX/USDT"
buys = c.execute(
    "SELECT shares, timestamp, id, price FROM paper_trades "
    "WHERE strategy=? AND symbol=? AND action='BUY' "
    "ORDER BY timestamp ASC, id ASC",
    (STRAT, SYM),
).fetchall()
sells = c.execute(
    "SELECT shares, timestamp, id, price FROM paper_trades "
    "WHERE strategy=? AND symbol=? AND action='SELL' "
    "ORDER BY timestamp ASC, id ASC",
    (STRAT, SYM),
).fetchall()
print("BUY rows:", len(buys))
for b in buys[-5:]:
    print(" ", b)
print("SELL rows:", len(sells))
for s in sells[-5:]:
    print(" ", s)
if sells:
    k = len(sells)
    fifo_buy = buys[k-1] if k-1 < len(buys) else None
    last_sell = sells[-1]
    print()
    print("FIFO pairing for the k-th SELL (k =", k, "):")
    print("  SELL:", last_sell)
    print("  BUY :", fifo_buy)
    if fifo_buy:
        delta = abs(float(last_sell[0]) - float(fifo_buy[0]))
        print(f"  delta = {delta:.12f}")
        print(f"  equal_to_1e-9 = {delta <= 1e-9}")
        print(f"  equal_to_8dp  = {round(delta, 8) == 0.0}")
'''
sftp = c.open_sftp()
with sftp.open("/tmp/check_trx_sell.py", "w") as f:
    f.write(helper)
sftp.close()
_, so, se = c.exec_command("docker cp /tmp/check_trx_sell.py aaats-paper-crypto:/tmp/check_trx_sell.py && docker exec aaats-paper-crypto python /tmp/check_trx_sell.py", timeout=60)
so.channel.recv_exit_status()
print(so.read().decode())
err = se.read().decode().strip()
if err:
    print("STDERR:", err)
c.close()
