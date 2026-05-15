"""
AAATS Diagnose + Fix: Grafana data gap & Cloudflare creds
Runs on Windows, SSHes into Contabo via Tailscale (paramiko).
Saves output to diagnose_output.txt in same folder.
"""
import sys, os, pathlib

BASE = pathlib.Path(__file__).parent
OUTPUT_FILE = BASE / "diagnose_output.txt"
ENV_FILE = BASE / ".env"

# ── Load .env ──────────────────────────────────────────────────────────────
_env = {}
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            _env[k.strip()] = v.strip()

HOST     = _env.get("CONTABO__TAILSCALE_IP", "100.95.126.39")
USER     = _env.get("CONTABO__SSH_USER",     "aaats")
PASSWORD = _env.get("CONTABO__SSH_PASSWORD", "Puneeth1234")

try:
    import paramiko
except ImportError:
    os.system(f'"{sys.executable}" -m pip install paramiko -q')
    import paramiko

lines = []
def log(s=""):
    print(s)
    lines.append(s)

log("=" * 60)
log("AAATS DIAGNOSTIC — Grafana + Cloudflare")
log("=" * 60)
log(f"Connecting to {USER}@{HOST} ...")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect(HOST, username=USER, password=PASSWORD, timeout=20)
    log("Connected OK\n")
except Exception as e:
    log(f"CONNECTION FAILED: {e}")
    OUTPUT_FILE.write_text("\n".join(lines))
    sys.exit(1)

def run(cmd, timeout=30):
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace").strip()
    err = stderr.read().decode(errors="replace").strip()
    return out, err

# ── 1. Container status ────────────────────────────────────────────────────
log("── CONTAINERS ──────────────────────────────────────────────")
out, _ = run("docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>&1")
log(out)
log()

# ── 2. aaats-paper-crypto last 50 log lines ───────────────────────────────
log("── aaats-paper-crypto LOGS (last 50) ───────────────────────")
out, _ = run("docker logs aaats-paper-crypto --tail 50 2>&1")
log(out)
log()

# ── 3. aaats-paper-crypto metrics endpoint ───────────────────────────────
log("── METRICS CHECK (curl :8001/metrics) ──────────────────────")
out, _ = run("curl -s http://localhost:8001/metrics 2>&1 | head -40")
log(out if out else "(empty)")
log()

# Check other ports too
for port in [8000, 8001, 8080, 9090]:
    out2, _ = run(f"curl -s --max-time 3 http://localhost:{port}/metrics 2>&1 | head -5")
    if out2 and "aaats" in out2.lower():
        log(f"  PORT {port} has AAATS metrics!")
        log(out2)

# ── 4. Prometheus scrape config ───────────────────────────────────────────
log("── PROMETHEUS SCRAPE CONFIG ────────────────────────────────")
out, _ = run("cat /home/aaats/aaats/deployment/prometheus.yml 2>/dev/null || "
             "find /home/aaats -name 'prometheus*.yml' 2>/dev/null | head -5")
log(out if out else "(not found)")
log()

# Also check what prometheus is actually scraping
out, _ = run("curl -s http://localhost:9090/api/v1/targets 2>&1 | python3 -c \""
             "import sys,json; d=json.load(sys.stdin); "
             "[print(t['discoveredLabels'].get('__address__','?'), t['health']) "
             "for t in d.get('data',{}).get('activeTargets',[])]\" 2>&1")
log("Prometheus active targets:")
log(out if out else "(could not query)")
log()

# ── 5. paper-crypto container env (metrics port) ──────────────────────────
log("── paper-crypto CONTAINER ENV ──────────────────────────────")
out, _ = run("docker inspect aaats-paper-crypto --format '{{range .Config.Env}}{{println .}}{{end}}' 2>&1 | grep -iE 'metric|port|host' | head -20")
log(out if out else "(no metric/port env vars)")
log()

# ── 6. Cloudflare details ─────────────────────────────────────────────────
log("── CLOUDFLARE TUNNEL ────────────────────────────────────────")

# Check aaats-cloudflared env
out, _ = run("docker inspect aaats-cloudflared --format '{{range .Config.Env}}{{println .}}{{end}}' 2>&1")
log("aaats-cloudflared env:")
log(out if out else "(container not found or no env)")
log()

# Check aaats-cloudflared-bot env
out, _ = run("docker inspect aaats-cloudflared-bot --format '{{range .Config.Env}}{{println .}}{{end}}' 2>&1")
log("aaats-cloudflared-bot env:")
log(out if out else "(container not found or no env)")
log()

# Check cloudflared config file
out, _ = run("cat /home/aaats/.cloudflared/config.yml 2>/dev/null || "
             "find /home/aaats -name 'config.yml' 2>/dev/null | xargs cat 2>/dev/null | head -40")
log("~/.cloudflared/config.yml:")
log(out if out else "(not found)")
log()

# Get tunnel list
out, _ = run("docker exec aaats-cloudflared cloudflared tunnel list 2>&1 | head -20")
log("cloudflared tunnel list:")
log(out if out else "(failed)")
log()

# Check compose file for cloudflare token
out, _ = run("grep -iE 'tunnel|token|cloudflare' /home/aaats/aaats/deployment/docker-compose.yml 2>/dev/null | head -30")
log("docker-compose.yml cloudflare references:")
log(out if out else "(not found)")
log()

# ── 7. Prometheus config path ─────────────────────────────────────────────
log("── PROMETHEUS CONTAINER CONFIG ─────────────────────────────")
out, _ = run("docker inspect aaats-prometheus --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}\n{{end}}' 2>&1")
log("Prometheus volume mounts:")
log(out)

out, _ = run("docker exec aaats-prometheus cat /etc/prometheus/prometheus.yml 2>&1")
log("prometheus.yml (from container):")
log(out if out else "(failed)")
log()

# ── 8. Grafana datasource ─────────────────────────────────────────────────
log("── GRAFANA DATASOURCE ───────────────────────────────────────")
out, _ = run("curl -s -u admin:1ZZ6lgHOMED237XTUWD348Y7 http://localhost:3000/api/datasources 2>&1")
log(out if out else "(failed)")
log()

# ── 9. Check docker-compose.yml for paper-crypto metrics port ────────────
log("── docker-compose.yml ports for paper-crypto ───────────────")
out, _ = run("grep -A 20 'aaats-paper-crypto' /home/aaats/aaats/deployment/docker-compose.yml 2>/dev/null | head -30")
log(out if out else "(not found)")
log()

client.close()
log("=" * 60)
log("DIAGNOSTIC COMPLETE")
log("=" * 60)

# Save output
OUTPUT_FILE.write_text("\n".join(lines))
print(f"\n\nOutput saved to: {OUTPUT_FILE}")
