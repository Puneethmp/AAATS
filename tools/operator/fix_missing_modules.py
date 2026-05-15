"""
Upload missing modules to Contabo and restart aaats-paper-crypto
"""
import subprocess, sys
try:
    import paramiko
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
    import paramiko

import tarfile, io, pathlib, time

HOST     = "100.95.126.39"
USER     = "aaats"
PASSWORD = "Puneeth1234"
REMOTE   = "/home/aaats/aaats"

# Missing modules not in original upload
MISSING = ["indicators", "execution", "decision", "observability"]
EXCLUDE = ["__pycache__", "*.pyc"]

PROJECT_ROOT = pathlib.Path(__file__).parent

def skip(s):
    for ex in EXCLUDE:
        if ex.startswith("*") and s.endswith(ex[1:]): return True
        elif not ex.startswith("*") and ex in s: return True
    return False

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f"Connecting to {HOST}...")
client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
print("Connected.\n")

def run(cmd, label=""):
    if label: print(f"\n[{label}]")
    _, out, err = client.exec_command(cmd, timeout=120)
    rc = out.channel.recv_exit_status()
    o = out.read().decode().strip()
    e = err.read().decode().strip()
    if o: print(o[-2000:])
    if e and rc != 0: print(f"ERR: {e[-400:]}")
    return rc, o

# Build tarball of missing modules only
print("Building tarball of missing modules...")
buf = io.BytesIO()
count = 0
with tarfile.open(fileobj=buf, mode='w:gz') as tar:
    for mod in MISSING:
        src = PROJECT_ROOT / mod
        if not src.exists():
            print(f"  ✗ {mod} not found locally"); continue
        for f in src.rglob("*"):
            rel = str(f.relative_to(PROJECT_ROOT))
            if not skip(rel) and f.is_file():
                tar.add(f, arcname=rel); count += 1
        print(f"  ✓ {mod}")
buf.seek(0)
data = buf.getvalue()
print(f"  {count} files, {len(data)/1024:.1f} KB\n")

# Stop the crashing container first
run("docker stop aaats-paper-crypto 2>&1 || true", "stopping paper-crypto")

# Upload and extract
print("Uploading...")
sftp = client.open_sftp()
with sftp.open("/tmp/aaats_missing.tar.gz", "wb") as f:
    f.write(data)
sftp.close()

run(f"cd {REMOTE} && tar xzf /tmp/aaats_missing.tar.gz && rm /tmp/aaats_missing.tar.gz", "extracting")
print("  ✓ Modules uploaded")

# Verify
run(f"ls {REMOTE}/indicators/ {REMOTE}/execution/ {REMOTE}/decision/ {REMOTE}/observability/ 2>&1", "verify modules on server")

# Rebuild image with all modules present
print("\nRebuilding image...")
run(f"cd {REMOTE}/deployment && docker compose build aaats-paper-crypto 2>&1 | tail -5", "docker build")

# Start container
print("\nStarting aaats-paper-crypto...")
run(f"cd {REMOTE}/deployment && docker compose up aaats-paper-crypto -d 2>&1", "docker up")

time.sleep(10)

# Get logs
run("docker logs aaats-paper-crypto --tail 40 2>&1", "first logs")

# Final status
run("docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'aaats-paper|aaats-engine|aaats-grafana'", "key containers")

client.close()
print("\nDone.")
