"""
Session 10 [P1.6] deploy: ship C3 divergence-watcher to the box.

Adds to monitoring/daily_digest.py the operator-away D3 watcher:
day 1-7 of the D.5 soak, if cumulative C3 P&L exits [-$2, +$2] vs the
d5_day1_marker, halt C3 + pager. Marker is absent today (reset has
not run yet) so the watcher is dormant on first boot — render row
emits "watcher dormant -- awaiting reset" and no side effects fire.

Files to roll:
  monitoring/daily_digest.py            (watcher impl + render_watcher_row
                                         + enforce_c3_divergence_watcher)
  scripts/reset_paper_book_200.py       (so operator can run the reset
                                         from the box if needed)
  docs/runbooks/2026-05-23_operator_away_protocol.md  (decision matrix
                                                       additions for the
                                                       D3 watcher row)
  docs/conventions/deploy_discipline.md (import-graph guard note)

Both aaats-paper-crypto AND aaats-watchdog must be rebuilt: the watcher
is referenced from monitoring/daily_digest.py which is COPYed into both
images (deployment/Dockerfile + deployment/Dockerfile.watchdog).

Smoke gates (per session-10 prompt P1.6):
  (a) docker exec aaats-paper-crypto python -c
      "from monitoring.daily_digest import compute_c3_divergence;
       print(compute_c3_divergence)"
      returns function (proves watcher symbol shipped).
  (b) digest dry-run on watchdog renders the watcher row (with no marker
      it shows the dormant baseline -- C3 P&L row absent or "no marker"
      depending on render path).
  (c) aaats-paper-crypto reaches running status post-rebuild.

Rollback baseline: .rollback/2026-05-24_session10_watcher_deploy/MANIFEST.txt

Run:
  python scripts/deploy_session10_watcher.py [--allow-dirty]
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
    "monitoring/daily_digest.py",
    "scripts/reset_paper_book_200.py",
    "docs/runbooks/2026-05-23_operator_away_protocol.md",
    "docs/conventions/deploy_discipline.md",
]

REMOTE_MKDIRS: list[str] = [
    "monitoring",
    "scripts",
    "docs/runbooks",
    "docs/conventions",
]

MANIFEST = (
    PROJECT_ROOT
    / ".rollback"
    / "2026-05-24_session10_watcher_deploy"
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
    for line in out.splitlines()[-25:]:
        print(f"     {_ascii(line)}")
    if rc != 0 and err:
        for line in err.splitlines()[-5:]:
            print(f"     ERR: {_ascii(line)}")
    return rc, out


def main() -> int:
    parser = argparse.ArgumentParser(description="Session 10 [P1.6] watcher deploy")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from tools.operator._dirty_tree_guard import check_clean
    check_clean(FILES, allow_dirty=args.allow_dirty)

    print("=" * 70)
    print("  Session 10 deploy [P1.6] -> divergence-watcher to box")
    print(f"  Target: {USER}@{HOST}:{REMOTE_DIR}/<{len(FILES)} files>")
    print("  Rebuild: aaats-paper-crypto + aaats-watchdog (--no-deps)")
    print("=" * 70)

    if not PASSWORD:
        print("FATAL: CONTABO__SSH_PASSWORD not in .env")
        return 1
    for rel in FILES:
        if not (PROJECT_ROOT / rel).exists():
            print(f"FATAL: {rel} not found locally")
            return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"\n[1/10] Connecting to {HOST}...")
    client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    print("       Connected")

    print("\n[2/10] Pre-deploy state capture...")
    _, pre_paper_image = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1", "pre paper image")
    _, pre_watchdog_image = _run(client,
        "docker inspect aaats-watchdog --format '{{.Image}}' 2>&1", "pre watchdog image")
    _, pre_halt_state = _run(client,
        f"cat {REMOTE_DIR}/data/halt_state.json 2>&1 || echo MISSING", "pre halt_state.json")
    pre_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client,
            f"sha256sum {REMOTE_DIR}/{rel} 2>&1 || echo 'ABSENT {rel}'", f"pre SHA {rel}")
        pre_shas[rel] = out.split()[0] if rc == 0 and "ABSENT" not in out else "ABSENT"

    print("\n[3/10] mkdir -p parent dirs (defensive)...")
    for d in REMOTE_MKDIRS:
        _ = _run(client, f"mkdir -p {REMOTE_DIR}/{d}", f"mkdir -p {d}")

    print("\n[4/10] SFTP upload to .tmp (LF-normalized)...")
    sftp = client.open_sftp()
    uploaded: list[tuple[str, str, str]] = []
    try:
        for rel in FILES:
            local = PROJECT_ROOT / rel
            remote = f"{REMOTE_DIR}/{rel}"
            tmp = remote + ".tmp"
            content = local.read_text(encoding="utf-8")
            normalized = content.replace("\r\n", "\n")
            with sftp.open(tmp, "w") as fh:
                fh.write(normalized)
            uploaded.append((rel, remote, tmp))
            print(f"       wrote {tmp}")
    finally:
        sftp.close()

    print("\n[5/10] Atomic swaps...")
    for rel, remote, tmp in uploaded:
        rc, _ = _run(client, f"mv -f {tmp} {remote} && echo OK", f"swap {rel}")
        if rc != 0:
            print(f"       FAIL on {rel}")
            client.close()
            return 2

    print("\n[6/10] Rebuilding aaats-paper-crypto + aaats-watchdog (--no-deps)...")
    rc, _ = _run(client,
        f"cd {REMOTE_DIR}/deployment && "
        "docker compose up -d --build --no-deps aaats-paper-crypto aaats-watchdog 2>&1 | tail -30",
        "rebuild paper-crypto + watchdog", timeout=900)
    if rc != 0:
        print("       FAIL: containers did not come up.")
        client.close()
        return 3

    print("\n[7/10] Post-rebuild SHAs + container status...")
    _, post_paper_image = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.Image}}' 2>&1", "post paper image")
    _, post_watchdog_image = _run(client,
        "docker inspect aaats-watchdog --format '{{.Image}}' 2>&1", "post watchdog image")
    _, post_paper_status = _run(client,
        "docker inspect aaats-paper-crypto --format '{{.State.Status}}' 2>&1", "post paper status")
    _, post_watchdog_status = _run(client,
        "docker inspect aaats-watchdog --format '{{.State.Status}}' 2>&1", "post watchdog status")
    post_shas: dict[str, str] = {}
    for rel in FILES:
        rc, out = _run(client, f"sha256sum {REMOTE_DIR}/{rel}", f"post SHA {rel}")
        post_shas[rel] = out.split()[0] if rc == 0 else "(failed)"

    if "running" not in post_paper_status:
        print(f"       FAIL: paper-crypto status={post_paper_status!r}")
        client.close()
        return 4
    if "running" not in post_watchdog_status:
        print(f"       FAIL: watchdog status={post_watchdog_status!r}")
        client.close()
        return 4

    # Settle so the new image is fully up before exec-import canaries fire.
    print("\n[8/10] Settling 40s for containers to stabilize...")
    _time.sleep(40)

    print("\n[9/10] Smoke gates...")

    # Gate (a): compute_c3_divergence is importable from paper-crypto.
    rc_sym_pc, sym_pc_out = _run(client,
        "docker exec aaats-paper-crypto python -c "
        "\"from monitoring.daily_digest import compute_c3_divergence; "
        "print(compute_c3_divergence)\" 2>&1",
        "import compute_c3_divergence (paper-crypto)", timeout=30)
    smoke_a_ok = (rc_sym_pc == 0) and ("function compute_c3_divergence" in sym_pc_out)

    # Gate (a-bis): watchdog must also have the symbol — that's where the
    # digest job actually runs at 09:00 IST.
    rc_sym_wd, sym_wd_out = _run(client,
        "docker exec aaats-watchdog python -c "
        "\"from monitoring.daily_digest import compute_c3_divergence, "
        "enforce_c3_divergence_watcher, render_watcher_row; "
        "print('all imports OK')\" 2>&1",
        "import watcher symbols (watchdog)", timeout=30)
    smoke_a_bis_ok = (rc_sym_wd == 0) and ("all imports OK" in sym_wd_out)

    # Gate (b): digest dry-run renders. With no d5_day1_marker.json yet,
    # render_watcher_row returns None, so the row is simply absent — the
    # contracted "dormant" UX. Validate the digest still completes
    # (Action needed line present).
    rc_dry, dry_out = _run(client,
        "docker exec aaats-watchdog python -m monitoring.daily_digest --dry-run 2>&1 | tail -50",
        "digest dry-run (watcher dormant — no marker yet)", timeout=120)
    action_line_present = any(
        line.lstrip().startswith("Action needed:")
        for line in dry_out.splitlines()
    )
    # When marker absent, watcher row must NOT appear (proves dormant path).
    watcher_row_absent = "watcher active" not in dry_out and "watcher inactive" not in dry_out
    smoke_b_ok = (rc_dry == 0) and action_line_present and watcher_row_absent

    # Gate (c): paper-crypto container running (already verified above).
    smoke_c_ok = "running" in post_paper_status

    client.close()

    deployed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "ROLLBACK BASELINE - 2026-05-24 Session 10 [P1.6] watcher deploy",
        "=" * 80,
        "",
        f"DEPLOYED_AT_UTC               = {deployed_at}",
        f"PRE_PAPER_IMAGE_SHA           = {pre_paper_image}",
        f"POST_PAPER_IMAGE_SHA          = {post_paper_image}",
        f"PRE_WATCHDOG_IMAGE_SHA        = {pre_watchdog_image}",
        f"POST_WATCHDOG_IMAGE_SHA       = {post_watchdog_image}",
        f"POST_PAPER_STATUS             = {post_paper_status}",
        f"POST_WATCHDOG_STATUS          = {post_watchdog_status}",
        f"SMOKE_A_PAPER_SYM             = {smoke_a_ok}",
        f"SMOKE_A_BIS_WATCHDOG_SYMS     = {smoke_a_bis_ok}",
        f"SMOKE_B_DIGEST_DRY_RUN        = {smoke_b_ok}",
        f"SMOKE_C_PAPER_RUNNING         = {smoke_c_ok}",
        f"PRE_HALT_STATE                = {_ascii(pre_halt_state)[:200]}",
        "",
        "Pre-deploy file SHAs:",
    ]
    for rel in FILES:
        lines.append(f"  {rel:55s} : {pre_shas.get(rel, '?')}")
    lines.append("")
    lines.append("Post-deploy file SHAs:")
    for rel in FILES:
        lines.append(f"  {rel:55s} : {post_shas.get(rel, '?')}")
    lines.append("")
    lines.append("Smoke (a) paper-crypto import output:")
    for line in sym_pc_out.splitlines()[-5:]:
        lines.append(f"  {_ascii(line)}")
    lines.append("")
    lines.append("Smoke (a-bis) watchdog import output:")
    for line in sym_wd_out.splitlines()[-5:]:
        lines.append(f"  {_ascii(line)}")
    lines.append("")
    lines.append("Smoke (b) digest dry-run tail:")
    for line in dry_out.splitlines()[-40:]:
        lines.append(f"  {_ascii(line)}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"  paper-crypto image:       {post_paper_image}")
    print(f"  watchdog image:           {post_watchdog_image}")
    print(f"  smoke A   (paper sym):    {smoke_a_ok}")
    print(f"  smoke A'  (watchdog sym): {smoke_a_bis_ok}")
    print(f"  smoke B   (digest):       {smoke_b_ok}")
    print(f"  smoke C   (paper run):    {smoke_c_ok}")
    print(f"  MANIFEST written:         {MANIFEST}")
    print("=" * 70)
    all_ok = smoke_a_ok and smoke_a_bis_ok and smoke_b_ok and smoke_c_ok
    return 0 if all_ok else 9


if __name__ == "__main__":
    sys.exit(main())
