"""One-shot: confirm the deployed paper_trader.py contains the new helper."""
from __future__ import annotations

import pathlib

import paramiko

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_env(p):
    env = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().split("#")[0].strip()
    return env


e = _load_env(PROJECT_ROOT / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    e.get("CONTABO__TAILSCALE_IP", "100.95.126.39"),
    port=22,
    username=e.get("CONTABO__SSH_USER", "aaats"),
    password=e.get("CONTABO__SSH_PASSWORD", ""),
    timeout=30,
)
for label, cmd in [
    ("host file", "grep -c _check_sell_buy_share_equality /home/aaats/aaats/execution/paper_trader.py"),
    ("container file", "docker exec aaats-paper-crypto grep -c _check_sell_buy_share_equality /app/execution/paper_trader.py"),
    ("call site", "docker exec aaats-paper-crypto grep -n 'if action == \"SELL\"' /app/execution/paper_trader.py"),
]:
    _, so, _ = c.exec_command(cmd, timeout=30)
    so.channel.recv_exit_status()
    print(f"{label}: {so.read().decode().strip()}")
c.close()
