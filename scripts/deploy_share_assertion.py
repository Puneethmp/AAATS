"""
One-shot atomic deploy: execution/paper_trader.py -> aaats-paper-crypto.

Doctrine (CLAUDE.md):
  1. SFTP-upload to <path>.tmp
  2. mv -f <path>.tmp <path>  (atomic on the box)
  3. docker compose up -d --build --no-deps aaats-paper-crypto

Captures pre/post image SHAs into .rollback/2026-05-15_share_assertion/MANIFEST.txt.
Run: venv\\Scripts\\python scripts\\deploy_share_assertion.py
"""
from __future__ import annotations

import datetime as _dt
import pathlib as _pl
import sys

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

LOCAL_FILE = PROJECT_ROOT / "execution" / "paper_trader.py"
REMOTE_FILE = f"{REMOTE_DIR}/execution/paper_trader.py"
MANIFEST = PROJECT_ROOT / ".rollback" / "2026-05-15_share_assertion" / "MANIFEST.txt"


def _run(client: paramiko.SSHClient, cmd: str, label: str) -> tuple[int, str]:
    print(f"  -> {label}")
    _, stdout, stderr = client.exec_command(cmd, timeout=600)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    for line in out.splitlines()[-15:]:
        print(f"     {line}")
    if rc != 0 and err:
        for line in err.splitlines()[-5:]:
            print(f"     ERR: {line}")
    return rc, out


def main() -> int:
    print("=" * 65)
    print("  Share-assertion deploy -> aaats-paper-crypto")
    print(f"  Target: {USER}@{HOST}:{REMOTE_FILE}")
    print("=" * 65)

    if not LOCAL_FILE.exists():
        print(f"FATAL: {LOCAL_FILE} not found")
        return 1
    if not PASSWORD:
        print("FATAL: CONTABO__SSH_PASSWORD not in .env")
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"\n[1/6] Connecting to {HOST}...")
    client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    print("       Connected")

    print("\n[2/6] Capturing pre-rebuild state...")
    _, pre_image = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1",
        "pre image",
    )
    _, pre_restart = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.RestartCount}}' 2>&1",
        "pre RestartCount",
    )

    print("\n[3/6] SFTP upload to .tmp...")
    sftp = client.open_sftp()
    tmp_remote = REMOTE_FILE + ".tmp"
    sftp.put(str(LOCAL_FILE), tmp_remote)
    sftp.close()
    print(f"       wrote {tmp_remote}")

    print("\n[4/6] Atomic swap (mv -f)...")
    rc, _ = _run(client, f"mv -f {tmp_remote} {REMOTE_FILE} && echo OK", "swap")
    if rc != 0:
        print("       FAIL — aborting before rebuild.")
        client.close()
        return 2

    print("\n[5/6] Rebuilding aaats-paper-crypto (no-deps)...")
    rc, _ = _run(
        client,
        (
            f"cd {REMOTE_DIR}/deployment && "
            "docker compose up -d --build --no-deps aaats-paper-crypto 2>&1 | tail -25"
        ),
        "build + recreate",
    )
    if rc != 0:
        print("       FAIL — container did not come up. Image SHAs not captured.")
        client.close()
        return 3

    print("\n[6/6] Capturing post-rebuild state...")
    _, post_image = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1",
        "post image",
    )
    _, post_status = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}}' 2>&1",
        "State.Status",
    )
    _, post_restart = _run(
        client,
        "docker inspect aaats-paper-crypto --format '{{.RestartCount}}' 2>&1",
        "post RestartCount",
    )

    client.close()

    # Append SHAs to MANIFEST.
    deployed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    txt = MANIFEST.read_text(encoding="utf-8")
    txt = txt.replace(
        "PRE_REBUILD_IMAGE_SHA  =",
        f"PRE_REBUILD_IMAGE_SHA  = {pre_image}",
    )
    txt = txt.replace(
        "POST_REBUILD_IMAGE_SHA =",
        f"POST_REBUILD_IMAGE_SHA = {post_image}",
    )
    txt = txt.replace(
        "PRE_RESTART_COUNT      =",
        f"PRE_RESTART_COUNT      = {pre_restart}",
    )
    txt = txt.replace(
        "DEPLOYED_AT_UTC        =",
        f"DEPLOYED_AT_UTC        = {deployed_at}",
    )
    MANIFEST.write_text(txt, encoding="utf-8")

    print("\n" + "=" * 65)
    print(f"  pre  image:  {pre_image}")
    print(f"  post image:  {post_image}")
    print(f"  status:      {post_status}")
    print(f"  RestartCount: {pre_restart} -> {post_restart}")
    print(f"  MANIFEST updated: {MANIFEST}")
    print("=" * 65)
    return 0


if __name__ == "__main__":
    sys.exit(main())
