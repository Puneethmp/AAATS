#!/usr/bin/env python3
"""Remote diagnostics script for AAATS server via paramiko SSH."""

import paramiko
import time
import sys
import io

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

HOST = "100.95.126.39"
USER = "aaats"
PASSWORD = "Puneeth1234"
PORT = 22

def ssh_connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
    print(f"[OK] Connected to {HOST} as {USER}")
    return client

def run_cmd(client, cmd, timeout=60):
    """Run a command and return (stdout, stderr, exit_status)."""
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    exit_code = stdout.channel.recv_exit_status()
    return out, err, exit_code

def print_section(title, content, err=None):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print('='*70)
    print(content if content.strip() else "(empty output)")
    if err and err.strip():
        print(f"[STDERR] {err.strip()}")

def main():
    client = ssh_connect()

    # ================================================================
    # STEP 1 — DIAGNOSTICS
    # ================================================================
    print("\n" + "="*70)
    print("  STEP 1: DIAGNOSTICS")
    print("="*70)

    # 1a. docker ps
    out, err, rc = run_cmd(client, "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'")
    print_section("1a. docker ps", out, err)

    # 1b. docker logs aaats-paper-crypto --tail 80
    out, err, rc = run_cmd(client, "docker logs aaats-paper-crypto --tail 80 2>&1", timeout=30)
    print_section("1b. docker logs aaats-paper-crypto (tail 80)", out, err)

    # 1c. metrics endpoint
    out, err, rc = run_cmd(client, "curl -s http://localhost:8001/metrics | head -30")
    print_section("1c. curl http://localhost:8001/metrics (head 30)", out, err)

    # 1d. prometheus config
    out, err, rc = run_cmd(client, "docker exec aaats-prometheus cat /etc/prometheus/prometheus.yml 2>&1")
    print_section("1d. prometheus.yml (inside container)", out, err)

    # 1e. grafana datasources
    out, err, rc = run_cmd(client, "curl -s -u admin:1ZZ6lgHOMED237XTUWD348Y7 http://localhost:3000/api/datasources 2>&1")
    print_section("1e. Grafana datasources API", out, err)

    # 1f. cloudflared env
    out, err, rc = run_cmd(client, "docker inspect aaats-cloudflared --format '{{range .Config.Env}}{{println .}}{{end}}' 2>&1")
    print_section("1f. cloudflared container env vars", out, err)

    # 1g. grep compose for tunnel/cloudflare
    out, err, rc = run_cmd(client, "grep -iE 'tunnel|token|cloudflare' /home/aaats/aaats/deployment/docker-compose.yml 2>&1")
    print_section("1g. docker-compose.yml tunnel/token grep", out, err)

    # 1h. cloudflare config file
    out, err, rc = run_cmd(client, "cat ~/.cloudflared/config.yml 2>/dev/null || echo 'NO_CONFIG_FILE'")
    print_section("1h. ~/.cloudflared/config.yml", out, err)

    # Paper trades check
    out, err, rc = run_cmd(client, "docker logs aaats-paper-crypto --tail 200 2>&1 | grep -iE 'trade|buy|sell|order|filled|signal' | tail -30", timeout=30)
    print_section("1i. paper-crypto trade signals (last 30)", out, err)

    out, err, rc = run_cmd(client, "sqlite3 /home/aaats/aaats/data/paper_trades.db \"SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;\" 2>/dev/null || echo 'NO_DB_ACCESS'")
    print_section("1j. SQLite paper_trades.db (last 10 rows)", out, err)

    # ================================================================
    # STEP 2 — READ PROMETHEUS FILE FROM HOST (not container)
    # ================================================================
    print("\n" + "="*70)
    print("  STEP 2: Prometheus config on HOST filesystem")
    print("="*70)

    # Find prometheus.yml on host
    out, err, rc = run_cmd(client, "find /home/aaats/aaats/deployment -name 'prometheus.yml' 2>/dev/null; find /home/aaats/aaats -name 'prometheus.yml' 2>/dev/null | head -10")
    print_section("2a. Find prometheus.yml on host", out, err)
    prom_paths = [p.strip() for p in out.strip().split('\n') if p.strip()]
    print(f"Found paths: {prom_paths}")

    # Read the first found file
    host_prom_content = None
    host_prom_path = None
    for path in prom_paths:
        out2, err2, rc2 = run_cmd(client, f"cat {path}")
        if out2.strip():
            host_prom_content = out2
            host_prom_path = path
            print_section(f"2b. Contents of {path}", out2, err2)
            break

    # ================================================================
    # STEP 2 FIX — Add aaats-paper-crypto scrape job if missing
    # ================================================================
    print("\n" + "="*70)
    print("  STEP 2 FIX: Check and fix Prometheus config")
    print("="*70)

    if host_prom_content:
        if 'aaats-paper-crypto' in host_prom_content or 'paper-crypto' in host_prom_content:
            print("[OK] aaats-paper-crypto already present in prometheus.yml - no fix needed")
        else:
            print("[ACTION] aaats-paper-crypto NOT found in prometheus.yml - adding scrape job...")

            # Build the new config by appending a scrape job
            additional_job = """
  - job_name: 'aaats-paper-crypto'
    static_configs:
      - targets: ['aaats-paper-crypto:8001']
    scrape_interval: 15s
"""
            if 'scrape_configs:' in host_prom_content:
                new_content = host_prom_content.rstrip() + "\n" + additional_job + "\n"
            else:
                new_content = host_prom_content.rstrip() + "\nscrape_configs:\n" + additional_job + "\n"

            print_section("2c. NEW prometheus.yml (to be written)", new_content)

            # Write the file back using a heredoc via SSH
            # Escape single quotes in content for shell
            escaped = new_content.replace("'", "'\"'\"'")
            write_cmd = f"cat > {host_prom_path} << 'PROMEOF'\n{new_content}\nPROMEOF"

            # Use tee to write the file
            import base64
            encoded = base64.b64encode(new_content.encode()).decode()
            write_cmd2 = f"echo '{encoded}' | base64 -d > {host_prom_path}"
            out3, err3, rc3 = run_cmd(client, write_cmd2)
            print_section("2d. Write result", out3 or "(no output)", err3)

            # Verify write
            out4, err4, rc4 = run_cmd(client, f"cat {host_prom_path}")
            print_section("2e. Verify written file", out4, err4)

            # Reload prometheus
            print("\n[ACTION] Reloading Prometheus...")
            out5, err5, rc5 = run_cmd(client, "docker exec aaats-prometheus wget --post-data='' -qO- 'http://localhost:9090/-/reload' 2>&1")
            print_section("2f. Prometheus reload response", out5 or f"(exit code {rc5})", err5)

            if rc5 != 0 or "error" in (out5+err5).lower():
                print("[ACTION] Reload may have failed, restarting container...")
                out6, err6, rc6 = run_cmd(client, "docker restart aaats-prometheus 2>&1")
                print_section("2g. docker restart aaats-prometheus", out6, err6)
                time.sleep(5)

            # Verify targets
            out7, err7, rc7 = run_cmd(client, "docker exec aaats-prometheus wget -qO- 'http://localhost:9090/api/v1/targets' | python3 -c \"import sys,json; t=json.load(sys.stdin)['data']['activeTargets']; [print(x['labels']['job'], x['health']) for x in t]\" 2>&1")
            print_section("2h. Prometheus active targets", out7, err7)
    else:
        print("[WARN] Could not find or read prometheus.yml on host")
        # Try to find it elsewhere
        out8, err8, rc8 = run_cmd(client, "find / -name 'prometheus.yml' 2>/dev/null | grep -v proc | head -10")
        print_section("2i. Broad search for prometheus.yml", out8, err8)

    # Also check prometheus targets even without fix
    out_t, err_t, rc_t = run_cmd(client, "docker exec aaats-prometheus wget -qO- 'http://localhost:9090/api/v1/targets' 2>&1 | python3 -c \"import sys,json; data=json.load(sys.stdin); t=data.get('data',{}).get('activeTargets',[]); [print(x['labels'].get('job','?'), x.get('health','?'), x['scrapeUrl']) for x in t]\" 2>&1")
    print_section("2j. Current Prometheus targets (always)", out_t, err_t)

    # ================================================================
    # STEP 3 — CLOUDFLARE TUNNEL DETAILS
    # ================================================================
    print("\n" + "="*70)
    print("  STEP 3: Cloudflare tunnel details")
    print("="*70)

    out, err, rc = run_cmd(client, "docker logs aaats-cloudflared --tail 50 2>&1 | grep -iE 'url|tunnel|https|trycloudflare'")
    print_section("3a. cloudflared logs - url/tunnel lines", out, err)

    out, err, rc = run_cmd(client, "docker logs aaats-cloudflared --tail 100 2>&1")
    print_section("3b. cloudflared logs (tail 100 full)", out, err)

    # Check compose for all cloudflare-related details
    out, err, rc = run_cmd(client, "cat /home/aaats/aaats/deployment/docker-compose.yml 2>&1 | grep -A 20 -B 2 'cloudflare\\|cloudflared'")
    print_section("3c. docker-compose cloudflared block", out, err)

    # Check for TUNNEL_TOKEN in environment
    out, err, rc = run_cmd(client, "docker inspect aaats-cloudflared 2>&1")
    print_section("3d. Full docker inspect aaats-cloudflared", out, err)

    # ================================================================
    # STEP 4 — EXTRA: Grafana health + all targets JSON
    # ================================================================
    print("\n" + "="*70)
    print("  STEP 4: Additional checks")
    print("="*70)

    out, err, rc = run_cmd(client, "docker exec aaats-prometheus wget -qO- 'http://localhost:9090/api/v1/targets' 2>&1")
    print_section("4a. Full Prometheus targets JSON", out, err)

    out, err, rc = run_cmd(client, "curl -s http://localhost:3000/api/health 2>&1")
    print_section("4b. Grafana health", out, err)

    out, err, rc = run_cmd(client, "docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'")
    print_section("4c. docker ps -a (including stopped)", out, err)

    client.close()
    print("\n[DONE] All diagnostics complete.")

if __name__ == "__main__":
    main()
