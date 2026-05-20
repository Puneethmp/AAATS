"""
One-shot atomic deploy: G1 halt_on_critical=False -> True.

Single-line flag flip at trading/live_paper_runner.py:1764.

Doctrine (CLAUDE.md):
  1. SFTP-upload to <path>.tmp.
  2. mv -f on box (atomic).
  3. docker compose up -d --build --no-deps aaats-paper-crypto.

Captures pre/post image SHAs into
.rollback/2026-05-20_g1_halt_flip/MANIFEST.txt.

Run: venv\\Scripts\\python scripts\\deploy_g1_halt_flip.py [--allow-dirty]
"""
from __future__ import annotations

import argparse
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

FILES = [
    ("trading/live_paper_runner.py", "live_paper_runner.py"),
]

ROLLBACK_DIR = PROJECT_ROOT / ".rollback" / "2026-05-20_g1_halt_flip"
MANIFEST = ROLLBACK_DIR / "MANIFEST.txt"


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
    parser = argparse.ArgumentParser(description="G1 halt_on_critical flip deploy")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from tools.operator._dirty_tree_guard import check_clean
    from tools.operator._newdir_parity_guard import check_newdir_parity
    rel_paths = [rel for rel, _ in FILES]
    check_clean(rel_paths, allow_dirty=args.allow_dirty)
    check_newdir_parity(rel_paths, allow_dirty=args.allow_dirty, warn_only=True)

    print("=" * 65)
    print("  G1 halt_on_critical=True deploy -> aaats-paper-crypto")
    print(f"  Target: {USER}@{HOST}:{REMOTE_DIR}/<1 file>")
    print("=" * 65)

    if not PASSWORD:
        print("FATAL: CONTABO__SSH_PASSWORD not in .env")
        return 1
    for rel, _ in FILES:
        if not (PROJECT_ROOT / rel).exists():
            print(f"FATAL: {rel} not found locally")
            return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"\n[1/7] Connecting to {HOST}...")
    client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    print("       Connected")

    print("\n[2/7] Capturing pre-rebuild state...")
    _, pre_image = _run(client, "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1", "pre image")
    _, pre_restart = _run(client, "docker inspect aaats-paper-crypto --format '{{.RestartCount}}' 2>&1", "pre RestartCount")
    _, pre_runner_sha = _run(client, f"sha256sum {REMOTE_DIR}/trading/live_paper_runner.py", "pre runner SHA")

    print("\n[3/7] SFTP upload to .tmp...")
    sftp = client.open_sftp()
    uploaded = []
    try:
        for rel, _ in FILES:
            local = PROJECT_ROOT / rel
            remote = f"{REMOTE_DIR}/{rel}"
            tmp = remote + ".tmp"
            sftp.put(str(local), tmp)
            uploaded.append((rel, remote, tmp))
            print(f"       wrote {tmp}")
    finally:
        sftp.close()

    print("\n[4/7] Atomic swap (mv -f)...")
    for rel, remote, tmp in uploaded:
        rc, _ = _run(client, f"mv -f {tmp} {remote} && echo OK", f"swap {rel}")
        if rc != 0:
            print(f"       FAIL on {rel}")
            client.close()
            return 2

    print("\n[5/7] Rebuilding aaats-paper-crypto (no-deps)...")
    rc, _ = _run(
        client,
        (
            f"cd {REMOTE_DIR}/deployment && "
            "docker compose up -d --build --no-deps aaats-paper-crypto 2>&1 | tail -25"
        ),
        "build + recreate",
    )
    if rc != 0:
        print("       FAIL — container did not come up.")
        client.close()
        return 3

    print("\n[6/7] Capturing post-rebuild state...")
    _, post_image = _run(client, "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1", "post image")
    _, post_status = _run(client, "docker inspect aaats-paper-crypto --format '{{.State.Status}}' 2>&1", "State.Status")
    _, post_restart = _run(client, "docker inspect aaats-paper-crypto --format '{{.RestartCount}}' 2>&1", "post RestartCount")
    _, flag_check = _run(
        client,
        f"grep -n 'halt_on_critical=' {REMOTE_DIR}/trading/live_paper_runner.py",
        "halt_on_critical line in deployed file",
    )

    print("\n[7/7] SHA-grep deployed files...")
    for rel, remote, _ in uploaded:
        _run(client, f"sha256sum {remote}", f"box SHA {rel}")

    client.close()

    deployed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    txt = MANIFEST.read_text(encoding="utf-8")
    txt = txt.replace("PRE_REBUILD_IMAGE_SHA  =", f"PRE_REBUILD_IMAGE_SHA  = {pre_image}")
    txt = txt.replace("POST_REBUILD_IMAGE_SHA =", f"POST_REBUILD_IMAGE_SHA = {post_image}")
    txt = txt.replace("PRE_RESTART_COUNT      =", f"PRE_RESTART_COUNT      = {pre_restart}")
    txt = txt.replace("DEPLOYED_AT_UTC        =", f"DEPLOYED_AT_UTC        = {deployed_at}")
    MANIFEST.write_text(txt, encoding="utf-8")

    print("\n" + "=" * 65)
    print(f"  pre  image:   {pre_image}")
    print(f"  post image:   {post_image}")
    print(f"  status:       {post_status}")
    print(f"  RestartCount: {pre_restart} -> {post_restart}")
    print(f"  flag check:   {flag_check}")
    print(f"  MANIFEST updated: {MANIFEST}")
    print("=" * 65)
    return 0


if __name__ == "__main__":
    sys.exit(main())
