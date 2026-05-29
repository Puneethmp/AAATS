"""tools/operator/deploy_lib.py — durable deploy helpers (sprint 2026-05-26).

Closes the recurring deploy-machinery failure class identified after the
2026-05-26 structural-fix deploy. Across the 2026-05-15 → 2026-05-26 window,
9+ distinct manual interventions were required per deploy, all from the
same set of root causes. Each one is logged here once, with the structural
fix beside it. Every future deploy script in tools/operator/ should import
from this module instead of reinventing.

Recurring failure modes addressed:

  1. CRLF line endings break .sh files on box (bit twice in 2026-05-26 alone)
     → atomic_upload_normalized() strips CRLF for textual extensions.
  2. paramiko SFTP binary mode preserves Windows CRLF
     → Same fix; covers .sh/.py/.yml/.json/.md/.txt.
  3. tarfile.add() preserves bytes as-is
     → normalize_bytes_for_text_file() can be applied to TarInfo addfile.
  4. Windows cp1252 console crashes on Unicode arrows in print()
     → enforce_utf8_console() reconfigures stdout/stderr at script entry.
  5. Box auto-cron races every 15 min during push (forced stash/rebase/pop)
     → auto_rebase_or_stash() handles the dance.
  6. Cowork sandbox leaves stale .git/index.lock Windows must clear
     → clear_stale_git_locks() removes the usual suspects.
  7. Pre-commit ruff auto-reformat racing commit
     → preflight_ruff_format() runs format+check before staging.
  8. Grafana dashboard mount path is /srv/aaats/compose/grafana/dashboards/
     (NOT deployment/grafana/dashboards/ in the repo)
     → GRAFANA_HOST_MOUNT constant + push_grafana_dashboard() that writes
     to both the repo path AND the live mount path.
  9. Soft-fail docker cp pollutes autopush log every cycle for files that
     legitimately don't exist (C5b disabled, share-eq never triggered)
     → container_file_exists() + smart_cp_state() guards.

Idempotent + safe to re-import. No side effects at import time.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable

# ──────────────────────────────────────────────────────────────────────────
# Constants — durable facts about box layout
# ──────────────────────────────────────────────────────────────────────────

LINE_ENDING_NORMALIZE_EXTS: frozenset[str] = frozenset(
    (".sh", ".py", ".yml", ".yaml", ".json", ".md", ".txt", ".env", ".cfg", ".ini")
)

# Real Grafana host mount as of 2026-05-26 (per CLAUDE.md: aaats-base project
# lives at /srv/aaats/compose/; aaats-paper-crypto's project lives at
# /home/aaats/aaats/deployment/). The Grafana container reads dashboards
# from the aaats-base project's mount, NOT the deployment/ project's.
GRAFANA_HOST_MOUNT: str = "/srv/aaats/compose/grafana/dashboards"

# Files that don't always exist on the box. Used by autopush + deploy to
# silently skip rather than log a cp failure every cycle.
EPHEMERAL_STATE_FILES: frozenset[str] = frozenset(
    (
        "funding_arb_state.json",  # C5b disabled
        "share_equality_mismatches.json",  # only written when WARN fires
        "capital_invariant_alerts.json",  # only written on non-ok verdict
        "momentum_state.json",  # C2 not yet active
        "strategy_halt_state.json",  # only written when a strategy halts
        "ledger_divergence_alerts.json",  # only written on divergence
    )
)

# Hard-required snapshot files. Missing one of these = real deploy failure.
HARD_REQUIRED_STATE_FILES: frozenset[str] = frozenset(
    ("paper_trades.db", "paper_positions.json", "paper_portfolio.json")
)

# Provisioned datasource UID — from
# /srv/aaats/compose/grafana/provisioning/datasources/prometheus.yml.
# NOT the literal string "prometheus" that Grafana dashboards sometimes
# default to. Bit during 2026-05-26 v3 dashboard rollout: 143 panel-level
# uid references to "prometheus" all rendered "No data" because the actual
# provisioned datasource has uid "aaats-prom". Confirmed by:
#   ssh aaats@100.95.126.39 'curl -s -u admin:<pw> http://localhost:3000/api/datasources'
PROMETHEUS_DATASOURCE_UID: str = "aaats-prom"


def grafana_datasource_ref() -> dict:
    """Canonical Grafana datasource ref for a dashboard panel. Use this in
    every dashboard JSON generator so the UID is right by construction.

    Returns the dict that goes into both panel-level "datasource" and each
    target's "datasource" field. Replaces ad-hoc {"type": "prometheus",
    "uid": "prometheus"} literals — that "prometheus" UID does NOT match
    the provisioned datasource and causes "No data" everywhere.
    """
    return {"type": "prometheus", "uid": PROMETHEUS_DATASOURCE_UID}


# ──────────────────────────────────────────────────────────────────────────
# Line-ending normalization
# ──────────────────────────────────────────────────────────────────────────


def normalize_bytes_for_text_file(data: bytes, filename: str) -> bytes:
    """Strip CRLF→LF + strip UTF-8 BOM for files whose extension is in
    LINE_ENDING_NORMALIZE_EXTS. Pass binary files through unchanged.

    The single line that has bitten every Windows→Linux deploy in this repo
    since 2026-05-15.
    """
    ext = Path(filename).suffix.lower()
    if ext not in LINE_ENDING_NORMALIZE_EXTS:
        return data
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def normalize_local_file_in_place(path: Path) -> bool:
    """Apply normalize_bytes_for_text_file to a local file. Returns True if
    the file was modified. Safe for both Cowork-mount and native Windows.
    """
    raw = path.read_bytes()
    fixed = normalize_bytes_for_text_file(raw, path.name)
    if fixed != raw:
        path.write_bytes(fixed)
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────
# SFTP atomic upload with normalization
# ──────────────────────────────────────────────────────────────────────────


def atomic_upload_normalized(sftp, local_path: Path, remote_path: str) -> str:
    """Upload via .tmp + posix_rename atomic swap, normalizing line endings
    for textual files. Returns sha16 of the bytes that landed on the box
    (post-normalization), which is what should be checksummed for rollback.
    """
    raw = local_path.read_bytes()
    normalized = normalize_bytes_for_text_file(raw, local_path.name)
    sha = hashlib.sha256(normalized).hexdigest()[:16]
    tmp = remote_path + ".tmp"
    with sftp.file(tmp, "wb") as f:
        f.write(normalized)
    sftp.posix_rename(tmp, remote_path)
    return sha


# ──────────────────────────────────────────────────────────────────────────
# Windows console encoding (cp1252 → utf-8)
# ──────────────────────────────────────────────────────────────────────────


def enforce_utf8_console() -> None:
    """Set Windows console to UTF-8 + reconfigure stdout/stderr. Idempotent.
    Call once at the top of any deploy script that might print() emojis or
    Unicode arrows. Without this, scripts that work on macOS/Linux crash
    on Windows the moment they print a non-ASCII char.
    """
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────────
# Git hygiene — locks + auto-rebase before push
# ──────────────────────────────────────────────────────────────────────────


def clear_stale_git_locks(repo_root: Path) -> list[str]:
    """Remove .git/index.lock and friends. Returns list of files cleared.
    Cowork sandbox leaves these behind when it can't unlink on the mount;
    Windows can clear them safely since Cowork has exited.
    """
    cleared: list[str] = []
    git_dir = Path(repo_root) / ".git"
    if not git_dir.exists():
        return cleared
    for lockname in (
        "index.lock",
        "HEAD.lock",
        "config.lock",
        "packed-refs.lock",
        "MERGE_HEAD.lock",
    ):
        p = git_dir / lockname
        if p.exists():
            try:
                p.unlink()
                cleared.append(str(p))
            except OSError:
                pass
    return cleared


def _git(*args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


def auto_rebase_or_stash(
    branch: str = "main", repo_root: Path | None = None
) -> tuple[bool, str]:
    """Pre-push hygiene: fetch, stash if dirty, pull --rebase, pop stash.
    Returns (success, message). Handles the box auto-cron 15-min race.

    Note: the box's auto-cron commits ONLY runtime/ files; the workstation
    work touches everything else. So the rebase should almost always be
    clean (no overlapping files). This handles the rare case where
    overlap occurs by failing loudly rather than silent merge.
    """
    rc, _, err = _git("fetch", "origin", branch, cwd=repo_root)
    if rc != 0:
        return False, f"git fetch failed: {err.strip()}"

    rc, out, _ = _git("status", "--porcelain", cwd=repo_root)
    dirty = bool(out.strip())
    stashed = False
    if dirty:
        rc, _, err = _git(
            "stash", "push", "-u", "-m", "deploy-auto-stash", cwd=repo_root
        )
        stashed = rc == 0
        if not stashed:
            return False, f"git stash failed: {err.strip()}"

    rc, _, err = _git("pull", "--rebase", "origin", branch, cwd=repo_root)
    if rc != 0:
        # restore stash before bailing
        if stashed:
            _git("stash", "pop", cwd=repo_root)
        return False, f"git pull --rebase failed: {err.strip()}"

    if stashed:
        rc, _, err = _git("stash", "pop", cwd=repo_root)
        if rc != 0:
            return False, f"git stash pop failed: {err.strip()}"

    return True, f"rebased onto origin/{branch}"


# ──────────────────────────────────────────────────────────────────────────
# Pre-commit ruff preflight
# ──────────────────────────────────────────────────────────────────────────


def preflight_ruff_format(
    paths: Iterable[Path], repo_root: Path | None = None
) -> tuple[bool, str]:
    """Run `ruff format` then `ruff check --fix` on the given paths BEFORE
    git add. Prevents the pre-commit hook from reformatting at commit time
    and forcing a re-stage. Idempotent. Returns (ok, message).

    Falls back to silent no-op if ruff is not installed (the operator may
    legitimately skip ruff in some workflows).
    """
    py_paths = [str(p) for p in paths if str(p).endswith(".py") and Path(p).exists()]
    if not py_paths:
        return True, "no .py paths to ruff"
    try:
        r1 = subprocess.run(
            ["ruff", "format", *py_paths], capture_output=True, text=True, cwd=repo_root
        )
        r2 = subprocess.run(
            ["ruff", "check", "--fix", *py_paths],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
    except FileNotFoundError:
        return True, "ruff not installed; skipping preflight"
    msg = (r1.stdout + r1.stderr + r2.stdout + r2.stderr).strip()
    return (
        r1.returncode == 0 and r2.returncode in (0, 1)
    ), msg or "ruff preflight done"


# ──────────────────────────────────────────────────────────────────────────
# Remote dir provisioning
# ──────────────────────────────────────────────────────────────────────────


def ensure_remote_dirs(client, paths: Iterable[str]) -> None:
    """mkdir -p on the box for each remote path's PARENT dir. Idempotent.

    `paths` are absolute remote FILE paths (NOT dir paths). The function
    extracts each parent via PurePosixPath(p).parent and mkdir -p's the
    parents in a single SSH round-trip.

    Right:
        ensure_remote_dirs(client, [
            "/home/aaats/aaats/data/capital_invariant_baseline.json",
            "/home/aaats/aaats/docs/known_issues/foo.md",
        ])
        # → mkdir -p /home/aaats/aaats/data /home/aaats/aaats/docs/known_issues

    Wrong (creates the WRONG dirs):
        ensure_remote_dirs(client, [
            "/home/aaats/aaats/data",
            "/home/aaats/aaats/docs/known_issues",
        ])
        # → mkdir -p /home/aaats/aaats /home/aaats/aaats/docs
        # → the actual target dirs are NEVER created; upload fails downstream.

    Tripped on the 2026-05-27 L11 baseline deploy; the name reads like
    "ensure these dirs exist" but the body makes parents. Either pass
    list(CHANGED_FILES.values()) directly (the file paths you're about
    to upload) or compose your own dir list and don't use this helper.
    """
    dirs: set[str] = set()
    for p in paths:
        parent = str(PurePosixPath(p).parent)
        if parent and parent not in ("/", "."):
            dirs.add(parent)
    if not dirs:
        return
    cmd = " && ".join(f"mkdir -p {d}" for d in sorted(dirs))
    _, stdout, _ = client.exec_command(cmd, timeout=30)
    stdout.channel.recv_exit_status()  # wait


# ──────────────────────────────────────────────────────────────────────────
# Grafana dashboard push — repo + live mount
# ──────────────────────────────────────────────────────────────────────────


def push_grafana_dashboard(
    sftp, client, local_dashboard: Path, remote_dir: str = GRAFANA_HOST_MOUNT
) -> tuple[str, str]:
    """Push a dashboard JSON to BOTH the repo's deployment/grafana/dashboards/
    (for git source-of-truth) AND the live Grafana host mount at
    /srv/aaats/compose/grafana/dashboards/ (where the running Grafana
    container actually reads from).

    Without writing to the live mount, repo dashboards are invisible to
    the running Grafana — bit in 2026-05-26 deploy.

    Returns (repo_remote_path, live_remote_path).
    """
    fname = local_dashboard.name
    repo_remote = f"/home/aaats/aaats/deployment/grafana/dashboards/{fname}"
    live_remote = f"{remote_dir}/{fname}"
    ensure_remote_dirs(client, [repo_remote, live_remote])
    atomic_upload_normalized(sftp, local_dashboard, repo_remote)
    atomic_upload_normalized(sftp, local_dashboard, live_remote)
    return repo_remote, live_remote


# ──────────────────────────────────────────────────────────────────────────
# Container existence guard for docker cp
# ──────────────────────────────────────────────────────────────────────────


def container_file_exists(client, container: str, container_path: str) -> bool:
    """Cheap existence check inside a docker container. Used by smart_cp_state
    to skip cp commands for ephemeral state files that legitimately don't
    exist yet (e.g. C5b state when C5b is disabled).
    """
    cmd = f"docker exec {container} test -f {container_path}"
    _, stdout, _ = client.exec_command(cmd, timeout=10)
    return stdout.channel.recv_exit_status() == 0


def smart_cp_state(
    client,
    container: str,
    container_path: str,
    host_path: str,
    silent_on_missing: bool = True,
) -> tuple[bool, str]:
    """docker cp guarded by file existence inside the container.

    Returns (success, status_message). When silent_on_missing is True (the
    default for ephemeral state), a missing source file is treated as
    success-with-skip rather than failure, so logs stay clean.
    """
    if silent_on_missing and not container_file_exists(
        client, container, container_path
    ):
        return True, "skip (not present in container)"
    cmd = f"timeout 15 docker cp {container}:{container_path} {host_path}"
    _, stdout, stderr = client.exec_command(cmd, timeout=30)
    rc = stdout.channel.recv_exit_status()
    if rc != 0:
        return False, f"cp failed: {stderr.read().decode().strip()}"
    return True, "cp ok"


# ──────────────────────────────────────────────────────────────────────────
# Telegram alerts — operator courtesy messages during deploys
# ──────────────────────────────────────────────────────────────────────────

# Canonical Telegram credential source on the box. Mirrors
# scripts/box/aaats-cron-alert.sh (the path proven to work — the 2026-05-27
# DB-FREEZE alert was sent via this exact extraction pattern). Do NOT use
# /srv/aaats/secrets/telegram_bot_token — that file is stale (HTTP 404
# from api.telegram.org/getMe). Phase 2 sqrt-fix deploy hit this and its
# pre/post alerts silently no-op'd.
TELEGRAM_ENV_FILE: str = "/home/aaats/aaats/.env"
TELEGRAM_TOKEN_VAR: str = "ALERTS__TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_VAR: str = "ALERTS__TELEGRAM_CHAT_ID"


def _shell_extract_env_var(env_file: str, var_name: str) -> str:
    """Build a shell snippet matching aaats-cron-alert.sh's extraction:
    grep ^VAR= | head -1 | cut -d= -f2- | strip-quotes."""
    return (
        f"grep -E '^{var_name}=' {env_file} | head -1 | "
        f"cut -d= -f2- | tr -d '\"' | tr -d \"'\""
    )


def verify_telegram_path(
    client,
    env_file: str = TELEGRAM_ENV_FILE,
    token_var: str = TELEGRAM_TOKEN_VAR,
) -> bool:
    """Smoke-test the Telegram alert path BEFORE any destructive deploy step.

    Reads ``token_var`` from ``env_file`` on the box (via SSH, using
    aaats-cron-alert.sh's exact extraction pattern), then calls
    ``api.telegram.org/bot<TOKEN>/getMe``. Returns True on HTTP 200,
    False otherwise. On False, prints the failure mode to stderr so the
    caller can fail-fast.

    Why this exists: Phase 2 sqrt-fix deploy (2026-05-27) used the wrong
    token path (``/srv/aaats/secrets/telegram_bot_token``, returns 404).
    Pre/post-rebuild Telegram alerts silently no-op'd; the Sharpe-panel
    jump went out unannounced. A real future rebuild that genuinely
    breaks something would go unobserved the same way.

    Canonical token source is ``/home/aaats/aaats/.env`` on the box,
    matching ``scripts/box/aaats-cron-alert.sh``.

    Caller contract: deploy scripts that send pre/post alerts MUST call
    this before the destructive step and ``SystemExit`` on False. The
    cost of a failed smoke is "rotate the token, re-run"; the cost of
    skipping the smoke is "deploy disaster goes silent."
    """
    extract_token = _shell_extract_env_var(env_file, token_var)
    cmd = (
        f"TOK=$({extract_token}); "
        f'if [ -z "$TOK" ]; then echo MISSING; exit 2; fi; '
        f"curl -sS --max-time 10 -o /tmp/.tg_smoke -w '%{{http_code}}' "
        f'"https://api.telegram.org/bot${{TOK}}/getMe"'
    )
    _, stdout, stderr = client.exec_command(cmd, timeout=20)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    last = out.splitlines()[-1] if out else ""
    if last == "200":
        return True
    sys.stderr.write(
        f"[telegram] smoke verify FAILED: env_file={env_file} "
        f"token_var={token_var} rc={rc} last_line={last!r} stderr={err[:200]!r}\n"
    )
    return False


def send_telegram_message(
    client,
    text: str,
    env_file: str = TELEGRAM_ENV_FILE,
    token_var: str = TELEGRAM_TOKEN_VAR,
    chat_id_var: str = TELEGRAM_CHAT_ID_VAR,
) -> bool:
    """Send a Telegram message FROM THE BOX (where credentials live).

    Mirrors ``aaats-cron-alert.sh``'s extraction + curl pattern, so
    deploys and cron use the same credential source. Returns True on
    HTTP 200, False otherwise.

    Always call :func:`verify_telegram_path` first if the message matters
    (pre/post deploy alerts, etc.) so you fail-fast before any destructive
    step rather than silently no-op'ing.
    """
    extract_token = _shell_extract_env_var(env_file, token_var)
    extract_chat = _shell_extract_env_var(env_file, chat_id_var)
    text_quoted = shlex.quote(text)
    cmd = (
        f"TOK=$({extract_token}); "
        f"CHAT=$({extract_chat}); "
        f'if [ -z "$TOK" ] || [ -z "$CHAT" ]; then echo MISSING; exit 2; fi; '
        f"curl -sS --max-time 15 -o /tmp/.tg_resp -w '%{{http_code}}' -X POST "
        f'"https://api.telegram.org/bot${{TOK}}/sendMessage" '
        f"-d chat_id=${{CHAT}} "
        f"--data-urlencode text={text_quoted}"
    )
    _, stdout, _ = client.exec_command(cmd, timeout=20)
    stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    last = out.splitlines()[-1] if out else ""
    return last == "200"


# ──────────────────────────────────────────────────────────────────────────
# Grafana "No data" recurrence guards (sprint 2026-05-29)
# ──────────────────────────────────────────────────────────────────────────
#
# The aaats-cmd-center dashboard has gone to "No data" on every panel twice,
# from two unrelated root causes that look identical to the operator:
#
#   1. 2026-05-26 — dashboard JSON hard-coded panel datasource uid "prometheus"
#      instead of the provisioned uid "aaats-prom" (143 refs). Queries resolved
#      to a non-existent datasource. Caught at DEPLOY time by
#      preflight_assert_no_prometheus_uid() below.
#
#   2. 2026-05-29 — the single-threaded exporter HTTPServer hung on a blocked
#      client write, so Prometheus scrapes timed out (context deadline
#      exceeded), up{job="aaats-metrics"}=0, and every aaats_* series went
#      stale. The dashboard JSON was perfectly correct. Caught AFTER deploy by
#      assert_metrics_flowing() below (and prevented from recurring by the
#      ThreadingHTTPServer fix in monitoring/metrics_exporter.py).
#
# A Grafana deploy path should run BOTH guards: the UID guard before pushing,
# and the flow assertion after rebuilding/pushing — so a dashboard that lands
# on "No data" can never pass a deploy silently again.

# Prometheus is published only on the container-internal :9090 (no host port),
# so queries must run inside the prom container.
PROMETHEUS_CONTAINER: str = "aaats-prometheus"
METRICS_SCRAPE_JOB: str = "aaats-metrics"


def preflight_assert_no_prometheus_uid(paths: Iterable[Path]) -> tuple[bool, str]:
    """Refuse to deploy any dashboard JSON that still hard-codes the datasource
    uid ``"prometheus"`` instead of the provisioned ``"aaats-prom"``
    (PROMETHEUS_DATASOURCE_UID). Mirrors the deploy_lib no-reinvent discipline:
    the UID should come from grafana_datasource_ref(), never a literal.

    Scans only ``*.json`` files in ``paths``. Returns (ok, detail). ``ok`` is
    False if any file contains a ``"uid": "prometheus"`` reference, listing the
    offending files so the caller can SystemExit before the push.

    This is the deploy-time half of the Grafana "No data" guard pair; the
    runtime half is assert_metrics_flowing().
    """
    bad_uid = re.compile(r'"uid"\s*:\s*"prometheus"')
    offenders: list[str] = []
    scanned = 0
    for p in paths:
        p = Path(p)
        if p.suffix.lower() != ".json" or not p.exists():
            continue
        scanned += 1
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if bad_uid.search(text):
            offenders.append(p.name)
    if offenders:
        return False, (
            f'datasource uid "prometheus" found in {len(offenders)} dashboard '
            f"file(s): {', '.join(offenders)}. Use "
            f"grafana_datasource_ref() -> uid={PROMETHEUS_DATASOURCE_UID!r}. "
            "This causes 'No data' on every panel (gotcha #10)."
        )
    return True, f"UID guard OK ({scanned} dashboard JSON scanned, none stale)"


def _prom_query(client, promql: str, prom_container: str = PROMETHEUS_CONTAINER):
    """Run an instant PromQL query inside the Prometheus container and return
    the parsed ``data.result`` list (empty list on any failure). POSTs the
    query as form data via wget so label-matchers/braces need no URL-encoding.
    """
    # wget is present in the prom image; POST avoids URL-encoding {job="..."}.
    cmd = (
        f"docker exec {prom_container} wget -qO- "
        f"--post-data={shlex.quote('query=' + promql)} "
        f"http://localhost:9090/api/v1/query"
    )
    _, stdout, _ = client.exec_command(cmd, timeout=20)
    stdout.channel.recv_exit_status()
    raw = stdout.read().decode().strip()
    try:
        doc = json.loads(raw)
        if doc.get("status") != "success":
            return []
        return doc.get("data", {}).get("result", [])
    except (ValueError, AttributeError):
        return []


def assert_metrics_flowing(
    client,
    job: str = METRICS_SCRAPE_JOB,
    probe_metric: str = "aaats_portfolio_capital",
    prom_container: str = PROMETHEUS_CONTAINER,
) -> tuple[bool, str]:
    """Post-deploy verification that the exporter is actually being scraped and
    emitting data — not merely that its container started.

    Asserts, via Prometheus (queried inside ``prom_container`` because :9090 is
    not host-published):
      (a) ``up{job=<job>} == 1`` — the target is being scraped successfully, and
      (b) ``<probe_metric>`` returns at least one sample — real series flowing.

    Returns (ok, detail). On failure the detail names which assertion failed so
    the caller can SystemExit / send_telegram_message and fail the deploy
    loudly. A Grafana dashboard that deploys to "No data" because the exporter
    never came back must NEVER pass a deploy silently (2026-05-29 incident).
    """
    up = _prom_query(client, f'up{{job="{job}"}}', prom_container)
    up_val = None
    if up:
        try:
            up_val = up[0]["value"][1]
        except (KeyError, IndexError, TypeError):
            up_val = None
    if up_val != "1":
        return False, (
            f'up{{job="{job}"}} = {up_val!r} (expected "1"). Exporter is not '
            "being scraped — Grafana will show 'No data'. Check the "
            f"{job} container health and the aaats network attachment."
        )
    series = _prom_query(client, probe_metric, prom_container)
    if not series:
        return False, (
            f"{probe_metric} returned 0 series though up==1. Exporter is up but "
            "emitting no aaats_* metrics — collectors likely erroring."
        )
    return True, (
        f'up{{job="{job}"}}=1 and {probe_metric} has {len(series)} series — '
        "metrics flowing."
    )
