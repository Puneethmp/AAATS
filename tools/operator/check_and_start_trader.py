"""
Check Contabo container status and start aaats-paper-crypto
"""
import subprocess, sys
try:
    import paramiko
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
    import paramiko

HOST = "100.95.126.39"
USER = "aaats"
PASSWORD = "Puneeth1234"
DEPLOY_DIR = "/home/aaats/aaats/deployment"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f"Connecting to {HOST}...")
client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
print("Connected.\n")

def run(cmd, label=""):
    if label: print(f"[{label}]")
    _, out, err = client.exec_command(cmd, timeout=120)
    rc = out.channel.recv_exit_status()
    o = out.read().decode().strip()
    e = err.read().decode().strip()
    if o: print(o[-3000:])
    if e and rc not in (0,): print(f"STDERR: {e[-500:]}")
    return rc, o

# Show all running containers
run("docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'", "ALL CONTAINERS")

# Check logs of paper crypto if it exists
print("\n--- Checking aaats-paper-crypto ---")
rc, _ = run("docker inspect aaats-paper-crypto 2>&1 | head -5")
if rc != 0:
    print("\nContainer doesn't exist. Attempting to start from deployment dir...")
    run(f"ls {DEPLOY_DIR}/", "deployment dir contents")
    rc2, _ = run(f"cd {DEPLOY_DIR} && docker compose up aaats-paper-crypto -d 2>&1", "docker compose up paper-crypto")
    if rc2 != 0:
        print("\nTrying with explicit compose file...")
        run(f"cd {DEPLOY_DIR} && cat docker-compose.yml | grep -A 5 'paper-crypto'", "service definition")
else:
    run("docker logs aaats-paper-crypto --tail 50 2>&1", "paper-crypto logs")

# Show final status
print("\n--- FINAL STATUS ---")
run("docker ps --format 'table {{.Names}}\t{{.Status}}'", "running containers")

client.close()
print("\nDone.")
