import sys
import time
import datetime

sys.path.insert(0, ".")
target = datetime.datetime(2026, 6, 11, 17, 13, tzinfo=datetime.timezone.utc)
while datetime.datetime.now(datetime.timezone.utc) < target:
    time.sleep(60)
from tools.operator.deploy_research_bed_posture_2026_06_10 import HOST, USER, PASSWORD  # noqa: E402  (deliberate: sleep-until-checkpoint before import)
import paramiko  # noqa: E402  (deliberate: sleep-until-checkpoint before import)

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASSWORD, timeout=30)
for cmd, hdr in [
    (
        "docker inspect aaats-paper-crypto --format 'health={{.State.Health.Status}} restarts={{.RestartCount}} started={{.State.StartedAt}}'",
        "container at 24h",
    ),
    ("cat /srv/aaats/runtime_repo/runtime/auto_cron_heartbeat.json", "L2 heartbeat"),
    (
        "docker logs aaats-paper-crypto --since 2026-06-11T11:30:00Z 2>&1 | grep -ciE 'error|traceback|exception'",
        "errors 11:30Z->now",
    ),
    (
        "docker logs aaats-paper-crypto 2>&1 | grep -cE '\[c3\] ENTRY |\[c6\] ENTRY |STAT_ARB ENTRY '",
        "entry lines full window",
    ),
]:
    print(f"===== {hdr} =====")
    _i, o, e = c.exec_command(cmd, timeout=120)
    o.channel.recv_exit_status()
    print(o.read().decode().strip())
c.close()
print(
    "A7_24H_CHECKPOINT_DONE", datetime.datetime.now(datetime.timezone.utc).isoformat()
)
