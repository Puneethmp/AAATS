#!/usr/bin/env python3
"""Final checks and fixes."""

import paramiko
import time
import sys
import io
import json
import base64

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

HOST = "100.95.126.39"
USER = "aaats"
PASSWORD = "Puneeth1234"

def ssh_connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    print(f"[OK] Connected to {HOST}")
    return client

def run_cmd(client, cmd, timeout=60):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    exit_code = stdout.channel.recv_exit_status()
    return out, err, exit_code

def sec(title, content, err=None):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print('='*70)
    print(content if content.strip() else "(empty)")
    if err and err.strip():
        print(f"[STDERR] {err.strip()}")

def main():
    client = ssh_connect()

    # ================================================================
    # 1. Verify the updated prometheus.yml was written correctly
    # ================================================================
    out, err, rc = run_cmd(client, "cat /srv/aaats/compose/prometheus/prometheus.yml")
    sec("1. Current /srv/aaats/compose/prometheus/prometheus.yml", out, err)

    # Check if paper-crypto is in it
    if 'paper-crypto' not in out and 'paper_crypto' not in out:
        print("[ACTION] paper-crypto still missing! Writing now...")

        new_prom = """global:
  scrape_interval: 15s
  scrape_timeout: 10s
  external_labels:
    instance: aaats-vps
    cluster: aaats-base

scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ['127.0.0.1:9090']

  - job_name: node
    static_configs:
      - targets: ['aaats-node-exporter:9100']
        labels: { service: host }

  - job_name: cadvisor
    static_configs:
      - targets: ['aaats-cadvisor:8080']
        labels: { service: containers }

  - job_name: redis
    static_configs:
      - targets: ['aaats-redis-exporter:9121']
        labels: { service: redis }

  - job_name: postgres
    static_configs:
      - targets: ['aaats-postgres-exporter:9187']
        labels: { service: postgres }

  - job_name: engine
    metrics_path: /metrics
    static_configs:
      - targets: ['aaats-engine:9100']
        labels: { service: engine }

  - job_name: alloy
    metrics_path: /metrics
    static_configs:
      - targets: ['aaats-alloy:12345']
        labels: { service: alloy }

  - job_name: cloudflared
    metrics_path: /metrics
    static_configs:
      - targets: ['aaats-cloudflared:2000']
        labels: { service: cloudflared }

  - job_name: aaats-paper-crypto
    metrics_path: /metrics
    static_configs:
      - targets: ['aaats-paper-crypto:8001']
        labels: { service: paper-crypto }
    scrape_interval: 15s
"""
        encoded = base64.b64encode(new_prom.encode()).decode()
        out2, err2, rc2 = run_cmd(client, f"echo '{encoded}' | base64 -d > /srv/aaats/compose/prometheus/prometheus.yml")
        sec("1b. Write result", out2 or f"(exit code {rc2})", err2)

        # Verify
        out3, err3, rc3 = run_cmd(client, "cat /srv/aaats/compose/prometheus/prometheus.yml")
        sec("1c. Verify written file", out3, err3)
    else:
        print("[OK] paper-crypto IS in prometheus.yml")

    # ================================================================
    # 2. Check prometheus port binding (is it accessible from localhost?)
    # ================================================================
    out, err, rc = run_cmd(client, "docker inspect aaats-prometheus --format '{{json .NetworkSettings.Ports}}'")
    sec("2. prometheus port bindings", out, err)

    # Try to curl prometheus from inside the container network
    out, err, rc = run_cmd(client, "docker exec aaats-prometheus wget -q -O- http://127.0.0.1:9090/-/ready 2>&1 || docker exec aaats-prometheus curl -s http://127.0.0.1:9090/-/ready 2>&1 || echo 'Cannot reach prometheus internally'")
    sec("3. Prometheus ready check from inside container", out, err)

    # Try from docker network
    out, err, rc = run_cmd(client, "docker run --rm --network aaats curlimages/curl:latest -s http://aaats-prometheus:9090/api/v1/targets 2>&1 | head -200")
    sec("4. Prometheus targets via docker network curl", out[:3000], err)

    # ================================================================
    # 5. Try to reload prometheus via docker exec
    # ================================================================
    out, err, rc = run_cmd(client, "docker exec aaats-prometheus wget -q -O- --post-data='' http://127.0.0.1:9090/-/reload 2>&1 || echo 'wget failed'")
    sec("5a. Prometheus reload via wget inside container", out, err)

    # Restart and wait
    print("\n[ACTION] Restarting aaats-prometheus to pick up new config...")
    out, err, rc = run_cmd(client, "docker restart aaats-prometheus 2>&1")
    sec("5b. docker restart aaats-prometheus", out, err)
    time.sleep(10)

    # ================================================================
    # 6. Check prometheus targets from inside docker network
    # ================================================================
    out, err, rc = run_cmd(client, "docker run --rm --network aaats curlimages/curl:latest -s http://aaats-prometheus:9090/api/v1/targets 2>&1")
    sec("6. Prometheus targets after restart", out[:5000], err)

    try:
        data = json.loads(out)
        targets = data.get('data', {}).get('activeTargets', [])
        print("\n--- Active Targets ---")
        for t in targets:
            print(f"  job={t['labels'].get('job','?')}  health={t.get('health','?')}  url={t.get('scrapeUrl','?')}")
    except Exception as e:
        print(f"[WARN] Could not parse: {e}")

    # ================================================================
    # 7. Grafana — it's only on Tailscale IP, try via Tailscale
    # ================================================================
    out, err, rc = run_cmd(client, "curl -s -u admin:1ZZ6lgHOMED237XTUWD348Y7 http://100.95.126.39:3000/api/datasources 2>&1")
    sec("7. Grafana datasources via Tailscale IP", out[:2000], err)

    out, err, rc = run_cmd(client, "curl -s http://100.95.126.39:3000/api/health 2>&1")
    sec("8. Grafana health via Tailscale IP", out, err)

    # ================================================================
    # 9. paper_trades.db — find actual table names
    # ================================================================
    out, err, rc = run_cmd(client, "docker exec aaats-paper-crypto python3 -c \"import sqlite3; conn=sqlite3.connect('/app/data/paper_trades.db'); c=conn.cursor(); c.execute(\\\"SELECT name FROM sqlite_master WHERE type='table'\\\"); print([r[0] for r in c.fetchall()])\" 2>&1")
    sec("9a. paper_trades.db table names", out, err)

    # Try common table names
    for table in ['paper_trades', 'trades', 'orders', 'positions']:
        out2, err2, rc2 = run_cmd(client, f"docker exec aaats-paper-crypto python3 -c \"import sqlite3; conn=sqlite3.connect('/app/data/paper_trades.db'); c=conn.cursor(); c.execute('SELECT * FROM {table} ORDER BY rowid DESC LIMIT 5'); rows=c.fetchall(); [print(r) for r in rows]\" 2>&1")
        if 'no such table' not in out2:
            sec(f"9b. Table {table} (last 5)", out2, err2)

    # ================================================================
    # 10. Read cloudflared.env for tunnel domain info
    # ================================================================
    out, err, rc = run_cmd(client, "cat /srv/aaats/secrets/cloudflared.env 2>/dev/null || echo 'NO FILE'")
    sec("10. /srv/aaats/secrets/cloudflared.env", out, err)

    # ================================================================
    # 11. Fix paper-crypto unhealthy: check if health_check.py exists
    # ================================================================
    out, err, rc = run_cmd(client, "docker exec aaats-paper-crypto ls /app/scripts/ 2>&1 || echo 'no scripts dir'")
    sec("11a. /app/scripts/ inside paper-crypto", out, err)

    out, err, rc = run_cmd(client, "docker exec aaats-paper-crypto ls /app/ 2>&1")
    sec("11b. /app/ contents inside paper-crypto", out, err)

    # ================================================================
    # 12. Check paper-crypto metrics endpoint directly from docker network
    # ================================================================
    for port in [8001, 8000, 9091, 9100]:
        out, err, rc = run_cmd(client, f"docker run --rm --network aaats curlimages/curl:latest -s --max-time 3 http://aaats-paper-crypto:{port}/metrics 2>&1 | head -10")
        if out.strip() and 'refused' not in out.lower() and 'failed' not in out.lower():
            print(f"\n[FOUND] Metrics at aaats-paper-crypto:{port}!")
            sec(f"12. paper-crypto metrics at :{port}", out, err)
            break
        else:
            print(f"  Port {port}: {out.strip()[:80] or 'no response'}")

    # ================================================================
    # 13. cloudflared.env contents & tunnel domains
    # ================================================================
    out, err, rc = run_cmd(client, "docker exec aaats-cloudflared-bot cat /etc/cloudflared/config.yml 2>&1 || echo 'no config'")
    sec("13a. aaats-cloudflared-bot config", out, err)

    out, err, rc = run_cmd(client, "docker inspect aaats-cloudflared-bot --format '{{range .Config.Env}}{{println .}}{{end}}' 2>&1")
    sec("13b. cloudflared-bot env vars", out, err)

    out, err, rc = run_cmd(client, "docker logs aaats-cloudflared-bot --tail 30 2>&1 | grep -iE 'url|tunnel|https|domain|hostname'")
    sec("13c. cloudflared-bot logs (url/tunnel)", out, err)

    # ================================================================
    # 14. Check if there's a Grafana tunnel (what the cloudflare tunnel routes to)
    # ================================================================
    out, err, rc = run_cmd(client, "find /srv/aaats/secrets -type f 2>/dev/null | xargs ls -la 2>/dev/null")
    sec("14. Secrets directory", out, err)

    # Try to decode the tunnel token to find tunnel UUID
    tunnel_token = "eyJhIjoiMGNjMzNkYWMwOWFmMzRiMDQyMTNjMGZkMWQyMmZiN2QiLCJ0IjoiMGZiNDcyZjItYjg3Yy00NDE2LWIxZmYtYjI5MWJiNDE3NzFjIiwicyI6IlpUZGpZbU5oWmpBdE5XWmlOUzAwWmpReUxUZzROekl0TkRrM1lUZ3dPVEZtTnpVMSJ9"
    try:
        # Add padding if needed
        padded = tunnel_token + '=' * (4 - len(tunnel_token) % 4)
        decoded = base64.b64decode(padded).decode('utf-8', errors='replace')
        print(f"\n[INFO] Decoded TUNNEL_TOKEN: {decoded}")
    except Exception as e:
        print(f"[WARN] Could not decode token: {e}")

    client.close()
    print("\n[DONE] Final checks complete.")

if __name__ == "__main__":
    main()
