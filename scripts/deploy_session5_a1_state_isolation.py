"""
Session 5 deploy [1]: A.1 state isolation box deploy.

OPERATOR-APPROVED 2026-05-23 (Cowork ack): no ask-first step. Pre-approved
because the compose change retains the legacy state-crypto volume in the
top-level volumes block as rollback baseline, and the migration script is
idempotent + source-untouched.

Files shipped together (all-or-nothing):
  deployment/docker-compose.yml      (per-mode mounts + AAATS_RISK_STATE_DIR env)
  risk/engine.py                     (_state_file_path() with mode discriminator)
  scripts/migrate_state_to_per_mode.sh  (one-time state-crypto -> state-crypto-paper)

Sequence (per docs/decisions/2026-05-22_state_isolation_design.md status log):
  1. SFTP each file to <path>.tmp -> atomic mv -f.
  2. docker stop aaats-paper-crypto (source volume becomes idle).
  3. bash scripts/migrate_state_to_per_mode.sh on box (copies + renames legacy state).
  4. docker compose up -d --build --no-deps aaats-paper-crypto (mounts per-mode vols).
  5. Verify post-deploy log line confirms paper peak loaded from
     /app/data/state-paper/risk_engine_state.paper.json.

Rollback path: if peak resets (no per-mode file found), the compose change
can be reverted by re-mounting state-crypto:/app/data/state and removing
the AAATS_RISK_STATE_DIR env (state-crypto contents are untouched).

Run:
  venv\\Scripts\\python scripts\\deploy_session5_a1_state_isolation.py [--allow-dirty]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import pathlib as _pl
import sys
import time as _time

import paramiko

PROJECT_ROOT = _pl.Path(__file__).resolve().parent.parent


def _load_env(path: _pl.Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().split("#")[0].strip()
    return env


_env = _load_env(PROJECT_ROOT / ".env")
HOST = _env.get("CONTABO__TAILSCALE_IP", "100.95.126.39")
USER = _env.get("CONTABO__SSH_USER", "aaats")
PASSWORD = _env.get("CONTABO__SSH_PASSWORD", "")
REMOTE_DIR = _env.get("CONTABO__REMOTE_DIR", "/home/aaats/aaats")

FILES: list[str] = [
    "deployment/docker-compose.yml",
    "risk/engine.py",
    "scripts/migrate_state_to_per_mode.sh",
]

MANIFEST = (
    PROJECT_ROOT
    / ".rollback"
    / "2026-05-23_session5_a1_state_isolation"
    / "MANIFEST.txt"
)


def _ascii(line: str) -> str:
    return line.encode("ascii", "replace").decode("ascii")


def _run(client: paramiko.SSHClient, cmd: str, label: str, timeout: int = 600) -> tuple[int, str]:
    print(f"  -> {label}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    for line in out.splitlines()[-20:]:
        print(f"     {_ascii(line)}")
    if rc != 0 and err:
        for line in err.splitlines()[-5:]:
            print(f"     ERR: {_ascii(line)}")
    return rc, out


def main() -> int:
    parser = argparse.ArgumentParser(description="Session 5 [1] A.1 state isolation deploy")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from tools.operator._dirty_tree_guard import check_clean
    check_clean(FILES, allow_dirty=args.allow_dirty)

    print("=" * 65)
    print("  Session 5 deploy [1] -> A.1 state isolation (per-mode volumes)")
    print(f"  Target: {USER}@{HOST}:{REMOTE_DIR}/<{len(FILES)} files>")
    print("=" * 65)

    if not PASSWORD:
        print("FATAL: CONTABO__SSH_PASSWORD not in .env")
        return 1
    for rel in FILES:
        if not (PROJECT_ROOT / rel).exists():
            print(f"FATAL: {rel} not found locally")
            return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"\n[1/11] Connecting to {HOST}...")
    client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    print("       Connected")

    print("\n[2/11] Pre-deploy capture...")
    _, pre_paper_image = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1", "pre paper image")
    _, pre_paper_status = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}}' 2>&1", "pre paper status")
    _, pre_paper_restart = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.RestartCount}}' 2>&1", "pre paper RestartCount")
    # Capture the legacy peak so we have a rollback reference number.
    _, pre_peak = _run(client,
        "docker run --rm -v state-crypto:/from:ro alpine cat /from/risk_engine_state.json "
        "2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get(\"peak\"))' "
        "2>/dev/null || echo UNKNOWN",
        "pre legacy state-crypto peak")
    _, pre_volumes = _run(client,
        "docker volume ls --format '{{.Name}}' | grep -E '^state-crypto' | sort",
        "pre state-crypto* volumes")

    pre_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client,
            f"sha256sum {REMOTE_DIR}/{rel} 2>&1 || echo 'ABSENT {rel}'", f"pre SHA {rel}")
        pre_shas[rel] = out.split()[0] if rc == 0 and "ABSENT" not in out else "ABSENT"

    print("\n[3/11] SFTP upload to .tmp...")
    sftp = client.open_sftp()
    uploaded: list[tuple[str, str, str]] = []
    try:
        for rel in FILES:
            local = PROJECT_ROOT / rel
            remote = f"{REMOTE_DIR}/{rel}"
            tmp = remote + ".tmp"
            sftp.put(str(local), tmp)
            uploaded.append((rel, remote, tmp))
            print(f"       wrote {tmp}")
    finally:
        sftp.close()

    print("\n[4/11] Atomic swaps...")
    for rel, remote, tmp in uploaded:
        rc, _ = _run(client, f"mv -f {tmp} {remote} && echo OK", f"swap {rel}")
        if rc != 0:
            print(f"       FAIL on {rel}")
            client.close()
            return 2

    print("\n[5/11] Stopping aaats-paper-crypto (source volume becomes idle)...")
    rc, _ = _run(client,
        "docker stop aaats-paper-crypto 2>&1 || true", "docker stop paper-crypto")
    # Confirm stopped.
    _, mid_status = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}}' 2>&1", "mid paper status")
    if "running" in mid_status:
        print("       FAIL: paper-crypto still running after stop.")
        client.close()
        return 3

    print("\n[6/11] Running migration script on box...")
    rc, mig_out = _run(client,
        f"cd {REMOTE_DIR} && bash scripts/migrate_state_to_per_mode.sh 2>&1",
        "migrate_state_to_per_mode.sh",
        timeout=180,
    )
    if rc != 0:
        print(f"       FAIL: migration script returned {rc}. Investigate before bringing paper-crypto back up.")
        client.close()
        return 4

    print("\n[7/11] Rebuilding aaats-paper-crypto with per-mode mounts...")
    rc, _ = _run(client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose up -d --build --no-deps aaats-paper-crypto 2>&1 | tail -30",
        "compose up --build paper-crypto",
        timeout=600,
    )
    if rc != 0:
        print("       FAIL: paper-crypto did not come up.")
        client.close()
        return 5

    print("\n[8/11] Post-rebuild state + SHAs...")
    _, post_paper_image = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1", "post paper image")
    _, post_paper_status = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}}' 2>&1", "post paper status")
    _, post_volumes = _run(client,
        "docker volume ls --format '{{.Name}}' | grep -E '^state-crypto' | sort",
        "post state-crypto* volumes")
    _, post_mounts = _run(client,
        "docker inspect aaats-paper-crypto --format '{{range .Mounts}}{{.Name}}:{{.Destination}} {{end}}' 2>&1",
        "post paper-crypto mounts")
    post_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client, f"sha256sum {REMOTE_DIR}/{rel}", f"post SHA {rel}")
        post_shas[rel] = out.split()[0] if rc == 0 else "(failed)"

    if "running" not in post_paper_status:
        print(f"       FAIL: paper-crypto status={post_paper_status!r}")
        client.close()
        return 6

    print("\n[9/11] Waiting 25s for first log lines + state-load message...")
    _time.sleep(25)
    rc, peak_logs = _run(client,
        "docker logs --tail 200 aaats-paper-crypto 2>&1 | "
        "grep -iE 'peak loaded|risk engine|state.+loaded|risk_engine_state' | tail -10",
        "peak-loaded log line search",
    )

    paper_peak_path_seen = "state-paper/risk_engine_state.paper.json" in peak_logs
    rollback_to_locked = "LOCKED_STARTING_EQUITY" in peak_logs and not paper_peak_path_seen

    print("\n[10/11] Reading paper-mode peak from new volume...")
    _, post_peak = _run(client,
        "docker run --rm -v state-crypto-paper:/to:ro alpine cat /to/risk_engine_state.paper.json "
        "2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get(\"peak\"))' "
        "2>/dev/null || echo UNKNOWN",
        "post per-mode peak (state-crypto-paper)")

    print("\n[11/11] Writing MANIFEST...")
    client.close()

    deployed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "ROLLBACK BASELINE - 2026-05-23 Session 5 [1] A.1 state isolation",
        "=" * 80,
        "",
        f"DEPLOYED_AT_UTC          = {deployed_at}",
        f"PRE_PAPER_IMAGE_SHA      = {pre_paper_image}",
        f"POST_PAPER_IMAGE_SHA     = {post_paper_image}",
        f"PRE_PAPER_STATUS         = {pre_paper_status}",
        f"POST_PAPER_STATUS        = {post_paper_status}",
        f"PRE_PAPER_RESTART_COUNT  = {pre_paper_restart}",
        "",
        f"PRE_PEAK_legacy_state-crypto       = {pre_peak}",
        f"POST_PEAK_state-crypto-paper       = {post_peak}",
        f"PAPER_PEAK_PATH_IN_LOGS_SEEN       = {paper_peak_path_seen}",
        f"ROLLBACK_TO_LOCKED_STARTING_EQUITY = {rollback_to_locked}",
        "",
        f"PRE_VOLUMES  = {pre_volumes!r}",
        f"POST_VOLUMES = {post_volumes!r}",
        f"POST_MOUNTS  = {post_mounts}",
        "",
        "Pre-deploy file SHAs (box, captured immediately before swap):",
    ]
    for rel in FILES:
        lines.append(f"  {rel:50s} : {pre_shas.get(rel, '?')}")
    lines.append("")
    lines.append("Post-deploy file SHAs (box, after rebuild):")
    for rel in FILES:
        lines.append(f"  {rel:50s} : {post_shas.get(rel, '?')}")
    lines.append("")
    lines.append("Migration-script stdout:")
    for line in mig_out.splitlines()[-30:]:
        lines.append(f"  {_ascii(line)}")
    lines.append("")
    lines.append("Peak-loaded log lines observed:")
    for line in peak_logs.splitlines()[-10:]:
        lines.append(f"  {_ascii(line)}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 65)
    print(f"  paper-crypto image:   {post_paper_image}")
    print(f"  paper-crypto status:  {post_paper_status}")
    print(f"  pre peak (legacy):    {pre_peak}")
    print(f"  post peak (paper):    {post_peak}")
    print(f"  paper-mode path seen in logs: {paper_peak_path_seen}")
    print(f"  rollback (locked equity) flag: {rollback_to_locked}")
    print(f"  MANIFEST written:     {MANIFEST}")
    print("=" * 65)
    return 0 if (paper_peak_path_seen or post_peak not in ("UNKNOWN", "None", "")) and not rollback_to_locked else 7


if __name__ == "__main__":
    sys.exit(main())
