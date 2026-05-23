"""PF5.7 — Container-kill recovery smoke (Phase 2 [P2.2]).

End-to-end check that aaats-paper-crypto can be killed and recovered.
Touches the live box via paramiko, so it skips unless AAATS_BOX_SMOKE=1.

Reality check on the recovery paths (documented here so the test's
mechanics aren't misread later):

  (1) docker's compose `restart: unless-stopped` policy does NOT
      restart on `docker kill` or in-container SIGKILL of PID 1 — both
      are treated as operator-initiated stops. Verified empirically
      2026-05-23: after `docker kill aaats-paper-crypto`, status=exited
      and RestartCount=0 indefinitely.

  (2) aaats-watchdog (per deployment/docker-compose.yml) is configured
      WATCHDOG_CYCLE_INTERVAL_SEC=900, stale_threshold = 3 * cycle =
      2700s (45 minutes). This is correct for the runner-alive-but-
      stuck failure mode but unreachable in a 90s smoke window. The
      watchdog's actual restart logic is unit-tested at tests/test_watchdog.py.

This smoke therefore verifies the KILL-AND-RESTORE LOOP rather than the
auto-recovery SLA: it kills the container, verifies it is exited,
manually restarts it (simulating the long-window watchdog response),
and verifies post-restart health + dedup invariant. The 45-min watchdog
SLA is accepted by the operator-away runbook's pre-auth matrix (single
restart in a 4h window is logged-only).

Sequence:
  1. SSH to box, capture pre-test StartedAt + RestartCount.
  2. docker kill --signal SIGKILL aaats-paper-crypto.
  3. Within 30s: confirm State.Status == exited (kill was effective).
  4. docker start aaats-paper-crypto (simulating eventual watchdog restart).
  5. Within 90s: confirm State.Status == running with StartedAt > pre_ts.
  6. Exec a no-op python (proves the runner came back up cleanly).
  7. Metrics exporter still responding (observability stack intact).
  8. Sanity-check the paper_trades.db dedup invariant: distinct
     client_order_ids == count of non-null client_order_ids (no
     double-fire across the restart boundary).
"""
from __future__ import annotations

import datetime as _dt
import os
import pathlib as _pl
import time
from typing import Any

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("AAATS_BOX_SMOKE") != "1",
    reason="PF5.7 hits the live Contabo box; set AAATS_BOX_SMOKE=1 to run.",
)


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = _pl.Path(__file__).resolve().parents[2] / ".env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().split("#")[0].strip()
    return env


def _ssh_client() -> Any:
    import paramiko
    env = _load_env()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        env["CONTABO__TAILSCALE_IP"], port=22,
        username=env["CONTABO__SSH_USER"],
        password=env["CONTABO__SSH_PASSWORD"],
        timeout=30,
    )
    return client


def _run(client: Any, cmd: str, timeout: int = 30) -> tuple[int, str]:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "replace").strip()
    return rc, out


def test_pf5_7_container_kill_recovery() -> None:
    client = _ssh_client()
    try:
        # 1. Pre-test snapshot.
        rc, pre_status = _run(client,
            "docker inspect aaats-paper-crypto --format '{{.State.Status}}'")
        assert rc == 0 and pre_status == "running", (
            f"paper-crypto must be running before kill test; status={pre_status}"
        )
        _, pre_started_at = _run(client,
            "docker inspect aaats-paper-crypto --format '{{.State.StartedAt}}'")
        pre_ts = _dt.datetime.fromisoformat(pre_started_at.replace("Z", "+00:00"))
        _, pre_restart_count_s = _run(client,
            "docker inspect aaats-paper-crypto --format '{{.RestartCount}}'")
        pre_restart_count = int(pre_restart_count_s)

        # 2. Force-kill via docker (canonical PID-1-bypass).
        kill_rc, kill_out = _run(client,
            "docker kill --signal SIGKILL aaats-paper-crypto 2>&1", timeout=15)
        assert kill_rc == 0, f"docker kill failed rc={kill_rc} out={kill_out}"

        # 3. Verify the kill was effective: status should reach exited
        # within 30s. (If not, the kill silently failed and the next
        # assertion would mask it.)
        deadline = time.time() + 30
        kill_effective = False
        while time.time() < deadline:
            _, st = _run(client,
                "docker inspect aaats-paper-crypto --format '{{.State.Status}}'")
            if st == "exited":
                kill_effective = True
                break
            time.sleep(2)
        assert kill_effective, (
            "docker kill did not move paper-crypto to exited within 30s"
        )

        # 4. Simulate the watchdog's eventual restart (see module docstring
        # for why this is manual rather than auto — restart: unless-stopped
        # is not triggered by docker kill, and the watchdog SLA is 45 min).
        start_rc, start_out = _run(client,
            "docker start aaats-paper-crypto 2>&1", timeout=30)
        assert start_rc == 0, f"docker start failed rc={start_rc} out={start_out}"

        # 5. Within 90s: container reaches running with new StartedAt.
        deadline = time.time() + 90
        recovered = False
        post_ts = pre_ts
        while time.time() < deadline:
            _, post_status = _run(client,
                "docker inspect aaats-paper-crypto --format '{{.State.Status}}'")
            _, post_started_at_s = _run(client,
                "docker inspect aaats-paper-crypto --format '{{.State.StartedAt}}'")
            try:
                post_ts = _dt.datetime.fromisoformat(post_started_at_s.replace("Z", "+00:00"))
            except ValueError:
                pass
            if post_status == "running" and post_ts > pre_ts:
                recovered = True
                break
            time.sleep(3)
        assert recovered, (
            f"paper-crypto did not return to running within 90s of restart "
            f"(pre_started={pre_ts}, post_started={post_ts})"
        )

        # 6. Wait 15s for the runner to settle, then prove it's responsive.
        time.sleep(15)
        rc, healthy = _run(client,
            "docker exec aaats-paper-crypto python -c \"print('runner-alive')\" 2>&1",
            timeout=30)
        assert rc == 0 and "runner-alive" in healthy, (
            f"post-restart runner did not respond: rc={rc} out={healthy}"
        )

        # 5. Metrics exporter still responding.
        rc, metrics = _run(client,
            "curl -s --max-time 5 http://localhost:9091/metrics 2>&1 | head -5",
            timeout=15)
        assert rc == 0 and metrics, (
            f"metrics exporter (port 9091) unreachable post-restart; out={metrics!r}"
        )

        # 6. Dedup invariant: no double-fire after restart. Read-only
        # connection so we don't fight the runner's writer (which holds
        # WAL locks). Inspect the schema first; if the client_order_id
        # column doesn't exist yet (fresh DB, no trade has triggered
        # the migration), there's trivially nothing to dedup-violate
        # and the gate passes.
        dedup_cmd = (
            "docker exec aaats-paper-crypto python -c "
            "\"import sqlite3; "
            "c=sqlite3.connect('file:/app/data/paper_trades.db?mode=ro', uri=True); "
            "cols=[r[1] for r in c.execute('PRAGMA table_info(paper_trades)').fetchall()]; "
            "have=('client_order_id' in cols); "
            "n_all=c.execute('SELECT COUNT(*) FROM paper_trades WHERE client_order_id IS NOT NULL').fetchone()[0] if have else 0; "
            "n_dist=c.execute('SELECT COUNT(DISTINCT client_order_id) FROM paper_trades WHERE client_order_id IS NOT NULL').fetchone()[0] if have else 0; "
            "print(f'have_col={have} n_all={n_all} n_dist={n_dist}')\""
        )
        rc, count = _run(client, dedup_cmd, timeout=30)
        assert rc == 0, f"dedup query failed: {count}"
        parts = dict(p.split("=") for p in count.split())
        assert int(parts["n_all"]) == int(parts["n_dist"]), (
            f"client_order_id dedup violated after restart: {count}"
        )
    finally:
        client.close()
