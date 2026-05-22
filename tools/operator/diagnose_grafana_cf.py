"""
1. Diagnose why Grafana shows no data from aaats-paper-crypto
2. Extract Cloudflare tunnel details from running container
"""
import subprocess, sys
try:
    import paramiko
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
    import paramiko

import pathlib, json, re

import os
HOST     = os.environ.get("AAATS_SSH_HOST", "100.95.126.39")
USER     = os.environ.get("AAATS_SSH_USER", "aaats")
PASSWORD = os.environ.get("AAATS_SSH_PASSWORD")
if not PASSWORD:
    raise SystemExit(
        "AAATS_SSH_PASSWORD env var not set. "
        "Copy .env.example to .env, fill in the password, and re-run."
    )
REMOTE   = "/home/aaats/aaats"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f"Connecting to {HOST}...")
client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
print("Connected.\n")

def run(cmd, label="", silent=False):
    if label and not silent: print(f"\n=== {label} ===")
    _, out, err = client.exec_command(cmd, timeout=60)
    rc = out.channel.recv_exit_status()
    o = out.read().decode().strip()
    e = err.read().decode().strip()
    if o and not silent: print(o[-3000:])
    if e and rc != 0 and not silent: print(f"ERR: {e[-300:]}")
    return rc, o

# ── 1. Check all running containers + ports ──────────────────────────────────
run("docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'", "ALL CONTAINERS")

# ── 2. Check aaats-metrics (Prometheus exporter for paper-crypto) ────────────
run("docker ps | grep -E 'metrics|exporter|prometheus'", "metrics containers")
run("docker logs aaats-metrics --tail 20 2>&1 || echo 'no aaats-metrics container'", "aaats-metrics logs")

# ── 3. Check what Prometheus is scraping ─────────────────────────────────────
run("docker exec aaats-prometheus cat /etc/prometheus/prometheus.yml 2>&1 | head -60", "prometheus config")

# ── 4. Check if paper-crypto metrics are reachable by Prometheus ─────────────
run("docker exec aaats-prometheus wget -qO- http://aaats-metrics:9091/metrics 2>&1 | head -10 || "
    "docker exec aaats-prometheus wget -qO- http://localhost:9091/metrics 2>&1 | head -10 || "
    "echo 'metrics endpoint not reachable'", "metrics reachability")

# ── 5. Check Grafana datasource ───────────────────────────────────────────────
run("docker exec aaats-grafana cat /etc/grafana/provisioning/datasources/datasource.yml 2>&1 || "
    "docker exec aaats-grafana find /etc/grafana -name '*.yml' 2>&1 | head -10", "grafana datasource")

# ── 6. Check paper-crypto metrics output ─────────────────────────────────────
run("docker exec aaats-paper-crypto python -c "
    "\"import sys; sys.path.insert(0,'/app'); from monitoring.metrics_exporter import MetricsExporter; print('exporter ok')\" 2>&1 || "
    "echo 'exporter check failed'", "paper-crypto exporter check")

# ── 7. Paper-crypto logs (latest) ────────────────────────────────────────────
run("docker logs aaats-paper-crypto --tail 30 2>&1", "paper-crypto latest logs")

# ── 8. Cloudflare tunnel details ─────────────────────────────────────────────
print("\n=== CLOUDFLARE DETAILS ===")
rc, cf_env = run("docker inspect aaats-cloudflared --format '{{json .Config.Env}}' 2>&1", silent=True)
if rc == 0 and cf_env:
    try:
        envs = json.loads(cf_env)
        for e in envs:
            if any(k in e.upper() for k in ['TUNNEL','TOKEN','CF_','CLOUDFLARE','ACCOUNT','ZONE']):
                print(f"  {e}")
    except:
        print(cf_env[:1000])

rc, cf_cmd = run("docker inspect aaats-cloudflared --format '{{json .Config.Cmd}}' 2>&1", silent=True)
if rc == 0:
    print(f"  CMD: {cf_cmd}")

# Also check cloudflared-bot
rc, cfb_env = run("docker inspect aaats-cloudflared-bot --format '{{json .Config.Env}}' 2>&1", silent=True)
if rc == 0 and cfb_env:
    try:
        envs = json.loads(cfb_env)
        for e in envs:
            if any(k in e.upper() for k in ['TUNNEL','TOKEN','CF_','CLOUDFLARE','ACCOUNT','ZONE','GRAFANA','URL']):
                print(f"  BOT: {e}")
    except:
        pass

# Check compose file for cloudflare config
run(f"find /home/aaats -name 'docker-compose*.yml' -not -path '*/venv/*' 2>/dev/null | head -5", "compose files")
rc, cf_compose = run("find /home/aaats -name 'docker-compose*.yml' -not -path '*/venv/*' 2>/dev/null | head -3", silent=True)
for f in cf_compose.splitlines():
    run(f"grep -A 10 'cloudflare' {f} 2>/dev/null | head -30", f"cloudflare in {f}")

# Check /etc/cloudflared or ~/.cloudflared
run("cat /home/aaats/.cloudflared/config.yml 2>/dev/null || "
    "find /home/aaats -name '*.json' -path '*cloudflare*' 2>/dev/null | head -3", "cloudflared config files")

client.close()
print("\nDone.")
