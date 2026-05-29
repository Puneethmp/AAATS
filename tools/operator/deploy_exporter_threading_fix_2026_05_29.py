#!/usr/bin/env python3
"""Deploy the exporter ThreadingHTTPServer fix (Grafana "No data" incident
2026-05-29).

Root cause: monitoring/metrics_exporter.py served metrics from a single-threaded
http.server.HTTPServer with no per-request socket timeout. One blocked client
write (Prometheus scrape connection dying mid-write -> BrokenPipe at do_GET's
self.wfile.write) wedged the only worker thread. Every subsequent scrape then
timed out ("context deadline exceeded"), up{job="aaats-metrics"} went to 0, all
aaats_* series went stale, and the Command Center dashboard showed "No data" on
every panel. Healthcheck FailingStreak was 3055 (~25h) at diagnosis time.

The dashboard JSON was NOT the cause this time — all 143 panel datasource refs
already use the correct uid "aaats-prom". (Gotcha #10 was the PRIME hypothesis;
it was disproven by evidence.)

Fix (already applied to the repo source, shipped here):
  - http.server.ThreadingHTTPServer instead of HTTPServer (daemon_threads=True)
  - MetricsHandler.timeout = 15s per-request socket timeout

This script:
  1. verifies the Telegram alert path BEFORE the destructive rebuild,
  2. captures a rollback baseline (remote sha of the file being replaced),
  3. atomic-uploads the normalized metrics_exporter.py (CRLF -> LF),
  4. rebuilds ONLY aaats-metrics (--no-deps; siblings untouched),
  5. polls assert_metrics_flowing() until up==1 + a probe metric returns,
  6. fails LOUDLY via Telegram if metrics never resume.

Maintenance-mode safe: touches only the aaats-metrics exporter. Does NOT touch
aaats-paper-crypto, strategy code, or the D.5 soak.
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import paramiko

# repo-root import of the canonical deploy helpers
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
from tools.operator import deploy_lib as dl  # noqa: E402

dl.enforce_utf8_console()

REMOTE_REPO = "/home/aaats/aaats"
EXPORTER_LOCAL = _REPO_ROOT / "monitoring" / "metrics_exporter.py"
EXPORTER_REMOTE = f"{REMOTE_REPO}/monitoring/metrics_exporter.py"
COMPOSE = f"{REMOTE_REPO}/deployment/docker-compose.yml"
SERVICE = "aaats-metrics"
CHANGE_ID = "2026-05-29_exporter_threading_fix"


def _load_env(env_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _run(client, cmd: str, timeout: int = 600) -> tuple[int, str, str]:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    return (
        rc,
        stdout.read().decode(errors="replace"),
        stderr.read().decode(errors="replace"),
    )


def main() -> int:
    env = _load_env(_REPO_ROOT / ".env")
    host = env.get("CONTABO__SSH_HOST", "100.95.126.39")
    user = env.get("CONTABO__SSH_USER", "aaats")
    password = env.get("CONTABO__SSH_PASSWORD")  # may be None -> key auth fallback

    if not EXPORTER_LOCAL.exists():
        print(f"FATAL: {EXPORTER_LOCAL} missing", file=sys.stderr)
        return 2

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    # password if present, else fall back to the ssh-agent / default key files
    client.connect(
        host,
        username=user,
        password=password,
        timeout=20,
        allow_agent=True,
        look_for_keys=True,
    )
    print(f"connected {user}@{host}")

    # 1) Telegram path must work BEFORE any destructive step (gotcha #11).
    if not dl.verify_telegram_path(client):
        client.close()
        raise SystemExit("Telegram smoke-test FAILED — aborting before rebuild.")
    print("telegram path OK")

    # 2) Rollback baseline — sha of the file we're about to replace.
    rc, remote_sha, _ = _run(
        client, f"sha256sum {EXPORTER_REMOTE} 2>/dev/null | cut -c1-16"
    )
    remote_sha = remote_sha.strip() or "(absent)"
    local_norm = dl.normalize_bytes_for_text_file(
        EXPORTER_LOCAL.read_bytes(), EXPORTER_LOCAL.name
    )
    local_sha = hashlib.sha256(local_norm).hexdigest()[:16]
    print(
        f"rollback baseline: remote={remote_sha}  ->  new(local,normalized)={local_sha}"
    )

    dl.send_telegram_message(
        client,
        f"AAATS deploy START: {CHANGE_ID} — exporter ThreadingHTTPServer fix "
        f"(Grafana 'No data' root cause). Rebuilding {SERVICE}. "
        f"baseline={remote_sha} new={local_sha}",
    )

    # 3) Atomic, CRLF-normalized upload.
    sftp = client.open_sftp()
    landed = dl.atomic_upload_normalized(sftp, EXPORTER_LOCAL, EXPORTER_REMOTE)
    sftp.close()
    print(f"uploaded {EXPORTER_REMOTE} (sha16={landed})")
    if landed != local_sha:
        print("WARN: landed sha != precomputed local sha", file=sys.stderr)

    # 4) Rebuild ONLY aaats-metrics — siblings untouched (--no-deps).
    print("rebuilding aaats-metrics (this can take a couple minutes)...")
    rc, out, err = _run(
        client,
        f"cd {REMOTE_REPO} && docker compose -f {COMPOSE} up -d --build --no-deps {SERVICE} 2>&1",
        timeout=900,
    )
    tail = (out + err).strip().splitlines()
    print("\n".join(tail[-12:]))
    if rc != 0:
        dl.send_telegram_message(
            client,
            f"AAATS deploy FAIL: {CHANGE_ID} — compose rebuild rc={rc}. Investigate.",
        )
        client.close()
        raise SystemExit(f"compose rebuild failed rc={rc}")

    # 5) Poll until Prometheus is scraping the exporter again + a probe metric
    #    returns. Scrape interval + healthcheck warm-up -> allow ~2 min.
    print("waiting for Prometheus to re-scrape the exporter...")
    ok, detail = False, "not checked"
    for attempt in range(1, 13):  # ~12 * 12s = ~2.4 min
        time.sleep(12)
        ok, detail = dl.assert_metrics_flowing(client)
        print(f"  [{attempt:2d}] {'OK ' if ok else '...'} {detail}")
        if ok:
            break

    # 6) Loud result either way.
    if ok:
        dl.send_telegram_message(
            client,
            f"AAATS deploy OK: {CHANGE_ID} — {SERVICE} rebuilt, metrics flowing again. "
            f"{detail} Dashboard should leave 'No data'.",
        )
        print("\nDEPLOY OK —", detail)
        result = 0
    else:
        dl.send_telegram_message(
            client,
            f"AAATS deploy WARN: {CHANGE_ID} — {SERVICE} rebuilt but metrics still "
            f"not flowing after ~2.4min: {detail} MANUAL CHECK REQUIRED.",
        )
        print("\nDEPLOY WARN — metrics not confirmed flowing:", detail, file=sys.stderr)
        result = 1

    client.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
