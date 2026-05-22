#!/usr/bin/env python3
"""Follow-up diagnostics after restart."""

import paramiko
import time
import sys
import io
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os
HOST = os.environ.get("AAATS_SSH_HOST", "100.95.126.39")
USER = os.environ.get("AAATS_SSH_USER", "aaats")
PASSWORD = os.environ.get("AAATS_SSH_PASSWORD")
if not PASSWORD:
    raise SystemExit(
        "AAATS_SSH_PASSWORD env var not set. "
        "Copy .env.example to .env, fill in the password, and re-run."
    )

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

    # Wait a moment for prometheus to fully restart
    time.sleep(3)

    # ================================================================
    # A. Prometheus targets after restart
    # ================================================================
    out, err, rc = run_cmd(client, "docker exec aaats-prometheus wget -qO- 'http://localhost:9090/api/v1/targets' 2>&1")
    sec("A. Prometheus targets JSON (raw)", out[:3000], err)

    # Parse it nicely
    try:
        data = json.loads(out)
        targets = data.get('data', {}).get('activeTargets', [])
        print("\n--- Active Targets Summary ---")
        for t in targets:
            print(f"  job={t['labels'].get('job','?')}  health={t.get('health','?')}  url={t.get('scrapeUrl','?')}")
    except Exception as e:
        print(f"[WARN] Could not parse targets JSON: {e}")

    # ================================================================
    # B. Prometheus CONTAINER config vs HOST config comparison
    # ================================================================
    # The container is using a DIFFERENT config mounted from /srv/aaats/compose/
    out, err, rc = run_cmd(client, "find /srv/aaats -name 'prometheus.yml' 2>/dev/null")
    sec("B1. Find prometheus.yml in /srv/aaats", out, err)

    out, err, rc = run_cmd(client, "cat /srv/aaats/compose/prometheus.yml 2>/dev/null || echo 'NOT FOUND'")
    sec("B2. /srv/aaats/compose/prometheus.yml", out, err)

    out, err, rc = run_cmd(client, "find /srv -name 'prometheus.yml' 2>/dev/null | head -10")
    sec("B3. All prometheus.yml in /srv", out, err)

    # Get the actual mount for prometheus container
    out, err, rc = run_cmd(client, "docker inspect aaats-prometheus --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'")
    sec("B4. aaats-prometheus mounts", out, err)

    # ================================================================
    # C. Fix: Write the correct prometheus.yml to the MOUNTED path
    # ================================================================
    # First get which file is actually mounted
    out_mounts, _, _ = run_cmd(client, "docker inspect aaats-prometheus --format '{{json .Mounts}}'")
    sec("C1. prometheus mounts JSON", out_mounts, None)

    mounted_path = None
    try:
        mounts = json.loads(out_mounts)
        for m in mounts:
            if 'prometheus' in m.get('Destination', '').lower() or 'prometheus' in m.get('Source', '').lower():
                mounted_path = m.get('Source')
                print(f"[INFO] Prometheus config mounted from: {mounted_path}")
                break
        if not mounted_path and mounts:
            # Find any .yml mount
            for m in mounts:
                if '.yml' in m.get('Source', '') or 'prometheus' in m.get('Source', '').lower():
                    mounted_path = m.get('Source')
                    break
    except Exception as e:
        print(f"[WARN] Could not parse mounts: {e}")

    # Read the current mounted config
    if mounted_path:
        out, err, rc = run_cmd(client, f"cat {mounted_path}")
        sec(f"C2. Current mounted config at {mounted_path}", out, err)

        if 'paper-crypto' not in out and 'paper_crypto' not in out:
            print(f"\n[ACTION] Adding aaats-paper-crypto job to {mounted_path}")
            # Check what port the container is actually exposing
            out_inspect, _, _ = run_cmd(client, "docker inspect aaats-paper-crypto --format '{{json .NetworkSettings.Ports}}'")
            sec("C3. aaats-paper-crypto exposed ports", out_inspect, None)

            # Check what's listening inside the container
            out_listen, _, _ = run_cmd(client, "docker exec aaats-paper-crypto ss -tlnp 2>/dev/null || docker exec aaats-paper-crypto netstat -tlnp 2>/dev/null || echo 'cannot check ports'")
            sec("C4. aaats-paper-crypto listening ports", out_listen, None)

            # Check if metrics endpoint is on a different port
            for port in [8000, 8001, 9091, 9100, 8080, 5000]:
                out_curl, _, _ = run_cmd(client, f"docker exec aaats-paper-crypto curl -s http://localhost:{port}/metrics 2>/dev/null | head -5 || echo 'no response on {port}'")
                if out_curl.strip() and 'no response' not in out_curl and '#' in out_curl:
                    print(f"\n[FOUND] Metrics available at port {port}!")
                    sec(f"C5. Metrics at :{port}", out_curl, None)
                    break
                elif out_curl.strip():
                    print(f"  Port {port}: {out_curl.strip()[:80]}")

            import base64

            new_content = out.rstrip() + "\n\n  - job_name: 'aaats-paper-crypto'\n    static_configs:\n      - targets: ['aaats-paper-crypto:8001']\n    scrape_interval: 15s\n"
            encoded = base64.b64encode(new_content.encode()).decode()
            write_out, write_err, write_rc = run_cmd(client, f"echo '{encoded}' | base64 -d > {mounted_path}")
            sec("C6. Write result", write_out or f"(exit code {write_rc})", write_err)

            # Reload
            time.sleep(1)
            reload_out, reload_err, reload_rc = run_cmd(client, "docker exec aaats-prometheus wget --post-data='' -qO- 'http://localhost:9090/-/reload' 2>&1")
            sec("C7. Prometheus reload after fix", reload_out or f"(exit code {reload_rc})", reload_err)

            if reload_rc != 0 or not reload_out.strip():
                print("[ACTION] Restarting prometheus instead...")
                restart_out, _, _ = run_cmd(client, "docker restart aaats-prometheus 2>&1")
                sec("C8. docker restart aaats-prometheus", restart_out, None)
                time.sleep(8)

            # Verify targets
            time.sleep(3)
            targets_out, _, _ = run_cmd(client, "docker exec aaats-prometheus wget -qO- 'http://localhost:9090/api/v1/targets' 2>&1")
            try:
                tdata = json.loads(targets_out)
                tatargets = tdata.get('data', {}).get('activeTargets', [])
                print("\n--- Updated Targets ---")
                for t in tatargets:
                    print(f"  job={t['labels'].get('job','?')}  health={t.get('health','?')}  url={t.get('scrapeUrl','?')}")
            except Exception as e:
                sec("C9. Updated targets raw", targets_out[:2000], None)
        else:
            print(f"[OK] paper-crypto already in {mounted_path}")
    else:
        print("[WARN] No mounted path found for prometheus config")
        # The container config IS the authoritative one - check its bind mounts
        out, err, rc = run_cmd(client, "docker inspect aaats-prometheus 2>&1 | grep -A5 'Binds\\|Mounts'")
        sec("C10. prometheus Binds/Mounts", out, err)

    # ================================================================
    # D. Grafana API (with verbose)
    # ================================================================
    _gp = os.environ.get("AAATS_GRAFANA_PASSWORD")
    if not _gp:
        raise SystemExit("AAATS_GRAFANA_PASSWORD env var not set; see .env.example")
    out, err, rc = run_cmd(client, f"curl -v -u admin:{_gp} http://localhost:3000/api/datasources 2>&1")
    sec("D1. Grafana datasources (verbose)", out[:3000], err)

    out, err, rc = run_cmd(client, "curl -s http://localhost:3000/api/health 2>&1")
    sec("D2. Grafana health", out, err)

    # ================================================================
    # E. Why is aaats-paper-crypto unhealthy?
    # ================================================================
    out, err, rc = run_cmd(client, "docker inspect aaats-paper-crypto --format '{{json .State.Health}}' 2>&1")
    sec("E1. paper-crypto health state", out, err)

    out, err, rc = run_cmd(client, "docker inspect aaats-paper-crypto --format '{{json .Config.Healthcheck}}' 2>&1")
    sec("E2. paper-crypto healthcheck config", out, err)

    # ================================================================
    # F. The aaats-metrics container (status: Created) - what is it?
    # ================================================================
    out, err, rc = run_cmd(client, "docker inspect aaats-metrics 2>&1 | python3 -c \"import sys,json; d=json.load(sys.stdin)[0]; print('Image:', d['Config']['Image']); print('Cmd:', d['Config'].get('Cmd',[])); print('Status:', d['State']['Status']); print('Ports:', list(d['HostConfig']['PortBindings'].keys()) if d['HostConfig']['PortBindings'] else 'none')\"")
    sec("F1. aaats-metrics container details", out, err)

    # ================================================================
    # G. Cloudflare tunnel: what domains are configured?
    # ================================================================
    out, err, rc = run_cmd(client, "docker exec aaats-cloudflared cat /etc/cloudflared/config.yml 2>/dev/null || echo 'NO FILE'")
    sec("G1. cloudflared config inside container", out, err)

    out, err, rc = run_cmd(client, "ls /srv/aaats/compose/ 2>/dev/null || ls /home/aaats/ 2>/dev/null")
    sec("G2. Compose directory listing", out, err)

    out, err, rc = run_cmd(client, "cat /srv/aaats/compose/docker-compose.base.yml 2>/dev/null | grep -A30 'cloudflared' | head -50")
    sec("G3. docker-compose.base.yml cloudflared section", out, err)

    out, err, rc = run_cmd(client, "grep -r 'TUNNEL_TOKEN\\|tunnel_token' /srv/aaats/compose/ 2>/dev/null | grep -v Binary | head -20")
    sec("G4. TUNNEL_TOKEN in compose files", out, err)

    # ================================================================
    # H. Summary of paper trades
    # ================================================================
    out, err, rc = run_cmd(client, "find /srv/aaats /home/aaats -name 'paper_trades.db' 2>/dev/null | head -5")
    sec("H1. Find paper_trades.db", out, err)

    out, err, rc = run_cmd(client, "docker exec aaats-paper-crypto python3 -c \"import sqlite3; conn=sqlite3.connect('/app/data/paper_trades.db'); c=conn.cursor(); c.execute('SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10'); rows=c.fetchall(); [print(r) for r in rows]\" 2>&1")
    sec("H2. paper_trades.db via docker exec", out, err)

    out, err, rc = run_cmd(client, "docker exec aaats-paper-crypto find /app /data /home -name 'paper_trades.db' 2>/dev/null | head -5")
    sec("H3. Find paper_trades.db inside container", out, err)

    client.close()
    print("\n[DONE] Follow-up complete.")

if __name__ == "__main__":
    main()
