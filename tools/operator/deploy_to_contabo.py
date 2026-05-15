"""
AAATS → Contabo Deployment Script (v2 — surgical, 2026-05-13)

Reads credentials from .env file.
Run: venv\Scripts\python deploy_to_contabo.py

v2 changes (fixes 2026-05-13 collateral-damage incident):
  • No more `docker compose down --remove-orphans` (was nuking grafana,
    metrics, telegram-bot every deploy). Now restarts ONLY the service
    whose code changed (aaats-paper-crypto).
  • Firewall step removed. Doctrine is Tailscale-only — public ports stay
    closed.
  • Status banner reflects actual exit codes; no false-success message.
  • Other observability services (grafana, prometheus, metrics, telegram-bot)
    are NEVER touched by this script. Manage them via deployment/docker-compose
    directly when needed.
"""
import subprocess, sys, os, pathlib

try:
    import paramiko
except ImportError:
    print("Installing paramiko...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
    import paramiko

import tarfile, io, time

PROJECT_ROOT = pathlib.Path(__file__).parent

# ── Load .env ────────────────────────────────────────────────────────────────
def load_env(path):
    env = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().split("#")[0].strip()
    return env

_env = load_env(PROJECT_ROOT / ".env")

HOST       = _env.get("CONTABO__TAILSCALE_IP",  "100.95.126.39")
USER       = _env.get("CONTABO__SSH_USER",     "aaats")
PASSWORD   = _env.get("CONTABO__SSH_PASSWORD", "Puneeth1234")
REMOTE_DIR = _env.get("CONTABO__REMOTE_DIR",   "/home/aaats/aaats")
TAILSCALE  = _env.get("CONTABO__TAILSCALE_IP", "100.95.126.39")
GRAFANA_PW = _env.get("CONTABO__GRAFANA_PASSWORD", "")
PORT       = 22

# ── Files to deploy ──────────────────────────────────────────────────────────
INCLUDE = [
    "trading", "foundation", "monitoring", "risk", "ml", "markets",
    "indicators", "execution", "decision", "observability",
    "deployment", "data/ml", "scripts",
    ".env", "requirements.txt",
]
EXCLUDE = ["__pycache__", "*.pyc", "venv", ".git", "node_modules",
           "paper_trades.db", "logs"]
# ─────────────────────────────────────────────────────────────────────────────

def run(client, cmd, desc="", ok_rc=(0,)):
    if desc:
        print(f"  → {desc}")
    _, stdout, stderr = client.exec_command(cmd, timeout=300)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    for line in out.splitlines()[-15:]:
        print(f"    {line}")
    if err and rc not in ok_rc:
        for line in err.splitlines()[-5:]:
            print(f"    ERR: {line}")
    return rc, out

def skip(s):
    for ex in EXCLUDE:
        if (ex.startswith("*") and s.endswith(ex[1:])) or (not ex.startswith("*") and ex in s):
            return True
    return False

def build_tarball():
    print("  Building tarball...")
    buf = io.BytesIO()
    count = 0
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for item in INCLUDE:
            src = PROJECT_ROOT / item
            if not src.exists():
                print(f"    ⚠ not found: {item}")
                continue
            if src.is_file():
                tar.add(src, arcname=item); count += 1
            else:
                for f in src.rglob("*"):
                    rel = str(f.relative_to(PROJECT_ROOT))
                    if not skip(rel) and f.is_file():
                        tar.add(f, arcname=rel); count += 1
    buf.seek(0)
    data = buf.getvalue()
    print(f"    {count} files, {len(data)/1024/1024:.1f} MB")
    return data

def main():
    print("=" * 65)
    print("  AAATS → Contabo Deployment")
    print(f"  Target: {USER}@{HOST} (Tailscale):{REMOTE_DIR}")
    print("=" * 65)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    print(f"\n[1/9] Connecting to {HOST}...")
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
    print("      ✓ Connected")

    print("\n[2/9] Server checks...")
    rc, _ = run(client, "docker --version && docker compose version 2>&1")
    if rc != 0:
        print("      ✗ Docker not found on server")
        sys.exit(1)
    run(client, "systemctl is-active docker || sudo systemctl start docker 2>&1", ok_rc=(0,1,3))
    print("      ✓ Docker OK")

    # v2: NO `docker compose down`. We restart only the service we updated
    # at step [6/8] below. Grafana / Prometheus / metrics / telegram-bot are
    # left running untouched.
    print("\n[3/8] Uploading codebase...")
    tarball = build_tarball()
    run(client, f"mkdir -p {REMOTE_DIR}")
    sftp = client.open_sftp()
    remote_tar = "/tmp/aaats_deploy.tar.gz"
    with sftp.open(remote_tar, "wb") as f:
        f.write(tarball)
    sftp.close()
    run(client, f"cd {REMOTE_DIR} && tar xzf {remote_tar} && rm {remote_tar}", "extracting")
    run(client, f"mkdir -p {REMOTE_DIR}/logs {REMOTE_DIR}/data/state {REMOTE_DIR}/data/ml")
    print("      ✓ Uploaded & extracted")

    # v2: firewall step REMOVED. Doctrine is Tailscale-only — public ports
    # 3000/9090/9091 must stay firewalled. Don't open them.
    print("\n[4/8] Firewall step skipped (Tailscale-only doctrine)")

    print("\n[5/8] Building Docker image (2–5 min)...")
    rc, _ = run(client,
        f"cd {REMOTE_DIR}/deployment && docker compose build aaats-paper-crypto 2>&1 | tail -10",
        "docker build")
    if rc != 0:
        print("      ✗ Build failed — see above")
        client.close(); sys.exit(1)
    print("      ✓ Image built")

    # v2: surgical recreate. Only aaats-paper-crypto. Other services
    # (prometheus, grafana, metrics, telegram-bot) are left alone.
    print("\n[6/8] Recreating aaats-paper-crypto with new image/config...")
    rc, _ = run(client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose up -d --no-deps --force-recreate aaats-paper-crypto 2>&1")
    if rc != 0:
        print("      ✗ Container start failed — aborting (other services untouched).")
        client.close(); sys.exit(1)
    print("      ✓ aaats-paper-crypto recreated")

    print("\n[7/8] Waiting 15s for first cycle...")
    time.sleep(15)

    print("\n[8/8] Status check & integrity verification...")
    rc, ps = run(client, "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'")
    expected_extra = ["aaats-grafana", "aaats-prometheus", "aaats-metrics", "aaats-telegram-bot"]
    missing = [s for s in expected_extra if s not in ps]
    if missing:
        print(f"      ⚠ Observability services not running: {missing}")
        print(f"      ⚠ NOTE: this deploy script no longer manages those services.")
        print(f"      ⚠ Restore via: cd {REMOTE_DIR}/deployment && docker compose up -d "
              + " ".join(missing))
    rc, _ = run(client, "docker logs aaats-paper-crypto --tail 40 2>&1", "First logs")

    # v2: honest banner — only declare success if paper-crypto is actually up.
    rc, status = run(client,
        "docker inspect -f '{{.State.Status}}/{{.State.Health.Status}}' aaats-paper-crypto 2>&1")
    healthy = "running" in status and ("healthy" in status or "starting" in status)
    print("\n" + "=" * 65)
    if healthy:
        print(f"  ✅ aaats-paper-crypto: {status}")
    else:
        print(f"  ⚠ aaats-paper-crypto: {status} — check logs")
    if missing:
        print(f"  ⚠ Missing services (not started by this script): {missing}")
    print()
    print(f"  Grafana (Tailscale): http://{TAILSCALE}:3000")
    print(f"  SSH:   ssh {USER}@{HOST}")
    print(f"  Logs:  docker logs aaats-paper-crypto -f")
    print("=" * 65)
    client.close()

if __name__ == "__main__":
    main()
