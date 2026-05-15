"""Check aaats-engine status and logs, then start our paper trader"""
import subprocess, sys
try:
    import paramiko
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
    import paramiko

HOST = "100.95.126.39"
USER = "aaats"
PASSWORD = "Puneeth1234"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f"Connecting to {HOST}...")
client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
print("Connected.\n")

def run(cmd, label=""):
    if label: print(f"\n=== {label} ===")
    _, out, err = client.exec_command(cmd, timeout=120)
    rc = out.channel.recv_exit_status()
    o = out.read().decode().strip()
    e = err.read().decode().strip()
    if o: print(o[-3000:])
    if e and rc != 0: print(f"ERR: {e[-300:]}")
    return rc, o

# Check aaats-engine logs (last 50 lines)
run("docker logs aaats-engine --tail 50 2>&1", "aaats-engine LOGS")

# Check what image/command aaats-engine uses
run("docker inspect aaats-engine --format '{{.Config.Image}} | CMD: {{.Config.Cmd}} | Entrypoint: {{.Config.Entrypoint}}'", "aaats-engine IMAGE/CMD")

# Find where its compose file is
run("docker inspect aaats-engine --format '{{index .Config.Labels \"com.docker.compose.project.working_dir\"}}' 2>&1", "compose working dir")

# Check our deployment dir
run("ls /home/aaats/aaats/deployment/ 2>&1", "our deployment dir")

# Try starting our paper trader (it won't conflict since different name)
run("cd /home/aaats/aaats/deployment && docker compose up aaats-paper-crypto -d 2>&1", "start aaats-paper-crypto")

# Final status
import time; time.sleep(8)
run("docker logs aaats-paper-crypto --tail 30 2>&1", "paper-crypto first logs")

client.close()
print("\nDone.")
