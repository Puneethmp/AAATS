"""
scripts/reset_paper_book_200.py — D.5 day-1 reset to $200 starting equity.

Operator-away protocol prerequisite: wipes the crypto paper book and
re-seeds it with $200 starting equity per
docs/decisions/2026-05-23_doctrine_amendment_200_floor.md, gated by the
B.1.5 backtest verdict at data/backtest_results/c3_60d_summary.json.

Behaviour (in order):
  (a) Read backtest summary.
  (b) NO-GO  -> loud refusal, exit 1.
  (c) GO/PARTIAL -> proceed; PARTIAL prints divergence-watcher note.
  (d) docker compose stop aaats-paper-crypto.
  (e) docker volume rm deployment_state-crypto-paper.
  (f) docker volume create deployment_state-crypto-paper.
  (g) Seed $200: write data/paper_portfolio.json + data/state-paper/*
      with starting_equity_usd=200.0.
  (h) foundation.kill_switch.reset("crypto") via CLI in container.
  (i) docker compose up -d --no-deps aaats-paper-crypto.
  (j) Wait up to 20 min for first NONE-NONE digest. Write
      data/d5_day1_marker.json:
        {day1_at, starting_equity_usd, divergence_watcher_armed,
         watcher_window_days, c3_threshold_low_usd, c3_threshold_high_usd}.
  (k) Digest never reaches NONE -> ROLLBACK. Restore halt, exit non-zero,
      marker JSON contains failed_at + reason.

The pure-logic helpers (read_backtest_recommendation, seed_state_payload,
build_day1_marker, classify_digest_action_line) are testable without
paramiko or docker. The orchestrator main() calls into a Box object that
encapsulates SSH I/O — pass a stub Box in tests to exercise the flow.

Run:
    python scripts/reset_paper_book_200.py            # dry-run (default)
    python scripts/reset_paper_book_200.py --apply    # really do it
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib as _pl
import sys
import time as _time
from typing import Any, Callable, Protocol


PROJECT_ROOT = _pl.Path(__file__).resolve().parent.parent
BACKTEST_SUMMARY = PROJECT_ROOT / "data" / "backtest_results" / "c3_60d_summary.json"

STARTING_EQUITY_USD = 200.0
WATCHER_WINDOW_DAYS = 7
C3_THRESHOLD_LOW_USD = -2.0
C3_THRESHOLD_HIGH_USD = 2.0

# India paper book stays at its existing doctrine floor (unchanged by the
# 2026-05-23 amendment, which only raised the crypto floor 100->200).
# trading/live_paper_runner.py main() reads BOTH portfolio["crypto"]
# and portfolio["india"] at startup; omitting india from the seed
# triggers KeyError and crash-loops the container.
INDIA_STARTING_EQUITY_INR = 25000.0

DIGEST_POLL_WINDOW_SEC = 20 * 60     # 20 minutes
DIGEST_POLL_INTERVAL_SEC = 30

# State files in the bind-mounted data/ tree that the digest's
# compute_action_needed reads. Wiping the docker volume only resets
# the risk-engine peak; these files survive a volume rm because they
# live in the bind mount and must be explicitly archived for the
# post-reset digest to reach Action needed: NONE.
#
# Archive (rename to .pre_reset_<ts>) — do NOT delete; gives the
# operator a forensic trail if anything looks off post-reset.
RESET_ARCHIVED_FILES = [
    "paper_trades.db",                  # historical pnl — doctrine wipe
    "alerts_log.json",                  # open alerts count -> 0
    "strategy_halt_state.json",         # halted strategies -> none
    "strategy_exception_state.json",    # consec exception streaks -> 0
    "share_equality_mismatches.json",   # share-eq counter -> 0
    "paper_positions.json",             # any stale open positions
    "altcoin_reversion_state.json",     # C3 strategy state
    "altcoin_reversion_cooldown.json",  # C3 cooldown timer
    "bollinger_range_state.json",       # C6 strategy state
    "stat_arb_state.json",              # C1 strategy state
    "funding_arb_state.json",           # C5b strategy state
    "digest_log.json",                  # digest-sent-today log
]


# ── Pure-logic helpers (testable without SSH) ─────────────────────────────


def read_backtest_recommendation(path: _pl.Path) -> str:
    """Return the recommendation field. Raises FileNotFoundError if missing."""
    if not path.exists():
        raise FileNotFoundError(f"backtest summary not found at {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rec = payload.get("recommendation")
    if not isinstance(rec, str):
        raise ValueError(f"backtest summary at {path} has no recommendation field")
    return rec.strip().upper()


def _market_baseline(capital: float) -> dict[str, Any]:
    return {
        "capital": float(capital),
        "starting_equity": float(capital),
        "realized_pnl": 0.0,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "total_win_pct": 0.0,
        "total_loss_pct": 0.0,
        "settlement_queue": [],
    }


def seed_state_payload(
    starting_equity_usd: float,
    india_starting_equity_inr: float = INDIA_STARTING_EQUITY_INR,
) -> dict[str, Any]:
    """The data/paper_portfolio.json payload at reset moment.

    Includes BOTH markets because trading/live_paper_runner.py main()
    reads portfolio["crypto"]["capital"] AND portfolio["india"]["capital"]
    at startup. Omitting india triggers KeyError before any cycle runs.

    Mirrors the schema scripts/reset_paper_state.py uses but at the
    operator-away amendment's $200 crypto floor (india unchanged). All
    counters zeroed.
    """
    return {
        "crypto": _market_baseline(starting_equity_usd),
        "india": _market_baseline(india_starting_equity_inr),
    }


def build_day1_marker(
    day1_at: _dt.datetime,
    starting_equity_usd: float = STARTING_EQUITY_USD,
    watcher_window_days: int = WATCHER_WINDOW_DAYS,
    c3_threshold_low_usd: float = C3_THRESHOLD_LOW_USD,
    c3_threshold_high_usd: float = C3_THRESHOLD_HIGH_USD,
) -> dict[str, Any]:
    """The marker file payload. Persisted to data/d5_day1_marker.json
    on success."""
    if day1_at.tzinfo is None:
        day1_at = day1_at.replace(tzinfo=_dt.timezone.utc)
    return {
        "day1_at": day1_at.astimezone(_dt.timezone.utc).isoformat(),
        "starting_equity_usd": float(starting_equity_usd),
        "divergence_watcher_armed": True,
        "watcher_window_days": int(watcher_window_days),
        "c3_threshold_low_usd": float(c3_threshold_low_usd),
        "c3_threshold_high_usd": float(c3_threshold_high_usd),
    }


def build_failure_marker(reason: str, attempted_at: _dt.datetime) -> dict[str, Any]:
    """Marker payload written when reset rolls back. Distinguishable
    from a success marker by the failed_at field."""
    if attempted_at.tzinfo is None:
        attempted_at = attempted_at.replace(tzinfo=_dt.timezone.utc)
    return {
        "failed_at": attempted_at.astimezone(_dt.timezone.utc).isoformat(),
        "reason": reason,
        "divergence_watcher_armed": False,
    }


def classify_digest_action_line(digest_text: str) -> str:
    """Pull the 'Action needed: ...' line out of a digest body. Returns
    the literal string after the colon, or '' if the line is missing."""
    for line in digest_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("action needed:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def is_action_none(action_text: str) -> bool:
    """Strict NONE check. Accepts 'NONE' (any case) only."""
    return action_text.strip().upper() == "NONE"


# ── Box I/O abstraction (so tests can stub) ───────────────────────────────


class BoxIO(Protocol):
    """The narrow surface reset orchestration needs from the remote box."""

    def run(self, cmd: str, label: str, timeout: int = 60) -> tuple[int, str]: ...

    def write_text(self, remote_path: str, content: str, label: str) -> None: ...


# ── Orchestration ─────────────────────────────────────────────────────────


def _gate_on_backtest(rec: str) -> tuple[bool, str]:
    """Return (proceed_bool, message). Hard-coded session-9/D1 rule."""
    if rec == "NO_GO" or rec == "NO-GO":
        return False, (
            "NO-GO backtest verdict (c3_60d_summary.json) — refusing to reset.\n"
            "Bot remains in current halted state. Operator must re-evaluate "
            "on return per docs/runbooks/2026-05-23_operator_away_protocol.md."
        )
    if rec == "GO":
        return True, "GO backtest verdict — proceeding with full strategy stack."
    if rec == "PARTIAL":
        return True, (
            "PARTIAL backtest verdict — proceeding with full strategy stack "
            "(C1+C3+C6). divergence-watcher active via D3: C3 P&L outside "
            f"[${C3_THRESHOLD_LOW_USD:+.2f}, ${C3_THRESHOLD_HIGH_USD:+.2f}] "
            f"in days 1-{WATCHER_WINDOW_DAYS} auto-HALTs C3."
        )
    return False, f"unexpected recommendation '{rec}' — refusing to reset (fail-safe)"


def execute_reset(
    box: BoxIO,
    *,
    remote_dir: str,
    seed_payload: dict[str, Any],
    now_fn: Callable[[], _dt.datetime] = lambda: _dt.datetime.now(_dt.timezone.utc),
    poll_interval_sec: int = DIGEST_POLL_INTERVAL_SEC,
    poll_window_sec: int = DIGEST_POLL_WINDOW_SEC,
    sleep_fn: Callable[[float], None] = _time.sleep,
) -> tuple[int, dict[str, Any]]:
    """Run the reset against a BoxIO. Returns (exit_code, marker_payload).

    exit_code:
       0 = success, marker contains day1_at
       2 = rollback engaged, marker contains failed_at + reason
       3 = SSH / docker command failed before rollback could complete
    """
    started_at = now_fn()

    # (d) stop AND remove paper-crypto + watchdog. Both mount
    # deployment_state-crypto-paper (paper-crypto rw, watchdog ro);
    # `docker volume rm` refuses if any container EXISTS (running or
    # exited) that references the volume, so a plain `stop` is
    # insufficient — `rm -f` is the explicit remove step.
    rc, _ = box.run(
        f"cd {remote_dir}/deployment && "
        "docker compose stop aaats-paper-crypto aaats-watchdog && "
        "docker compose rm -f -s aaats-paper-crypto aaats-watchdog",
        "docker compose stop + rm aaats-paper-crypto + aaats-watchdog",
    )
    if rc != 0:
        return 3, build_failure_marker(
            "docker compose stop/rm (paper-crypto + watchdog) failed", started_at,
        )

    # (e)(f) volume rm + create.
    rc, _ = box.run(
        "docker volume rm deployment_state-crypto-paper "
        "&& docker volume create deployment_state-crypto-paper",
        "wipe + recreate state-crypto-paper volume",
    )
    if rc != 0:
        # Restore: bring containers back up so we don't leave the bot off-air.
        box.run(
            f"cd {remote_dir}/deployment && "
            "docker compose start aaats-paper-crypto aaats-watchdog",
            "rollback: start paper-crypto + watchdog after volume rm failure",
        )
        return 3, build_failure_marker("volume rm/create failed", started_at)

    # (e.5) Archive bind-mounted state files that survive a volume rm
    # and would keep the post-reset digest from reaching NONE (open
    # alerts, halted strategies, share-eq counters, historical trade pnl).
    archive_ts = started_at.strftime("%Y%m%dT%H%M%SZ")
    for rel in RESET_ARCHIVED_FILES:
        # Each archive runs independently — a missing source file is
        # NOT an error (e.g. fresh box never had funding_arb_state.json).
        box.run(
            f"if [ -e {remote_dir}/data/{rel} ]; then "
            f"  mv -f {remote_dir}/data/{rel} "
            f"     {remote_dir}/data/{rel}.pre_reset_{archive_ts}; "
            f"  echo archived; "
            f"else echo absent; fi",
            f"archive data/{rel}",
        )

    # (g) Seed $200 portfolio JSON and ensure state-paper exists.
    portfolio_json = json.dumps(seed_payload, indent=2)
    box.write_text(
        f"{remote_dir}/data/paper_portfolio.json",
        portfolio_json,
        "seed paper_portfolio.json $200",
    )
    # Bring both containers back up. paper-crypto materializes the
    # state-paper volume; watchdog needs to be running so the digest
    # poll loop below can exec into it. --no-deps so we don't disturb
    # metrics-exporter / grafana / etc.
    rc, _ = box.run(
        f"cd {remote_dir}/deployment && "
        "docker compose up -d --no-deps aaats-paper-crypto aaats-watchdog",
        "docker compose up aaats-paper-crypto + aaats-watchdog (post-seed)",
        timeout=300,
    )
    if rc != 0:
        return 3, build_failure_marker(
            "docker compose up (paper-crypto + watchdog) failed", started_at,
        )

    # (h) Clear operator halt for crypto.
    rc, _ = box.run(
        "docker exec aaats-paper-crypto python -c "
        "\"from foundation import kill_switch; "
        "kill_switch.reset('crypto', authorized_by='reset_paper_book_200', "
        "reason='D.5 day-1 reset')\"",
        "kill_switch.reset('crypto')",
        timeout=60,
    )
    if rc != 0:
        return 3, build_failure_marker(
            "kill_switch.reset(crypto) failed in container", started_at,
        )

    # (j) Wait up to poll_window for the first NONE-NONE digest dry-run.
    deadline_sec = poll_window_sec
    elapsed = 0
    seen_action_lines: list[str] = []
    while elapsed < deadline_sec:
        rc, out = box.run(
            "docker exec aaats-paper-crypto python -m monitoring.daily_digest "
            "--dry-run 2>&1 | tail -80",
            f"digest dry-run @ t={elapsed}s",
            timeout=120,
        )
        if rc == 0:
            action = classify_digest_action_line(out)
            if action:
                seen_action_lines.append(action)
                if is_action_none(action):
                    day1_at = now_fn()
                    marker = build_day1_marker(day1_at)
                    box.write_text(
                        f"{remote_dir}/data/d5_day1_marker.json",
                        json.dumps(marker, indent=2),
                        "write d5_day1_marker.json",
                    )
                    return 0, marker
        sleep_fn(poll_interval_sec)
        elapsed += poll_interval_sec

    # (k) Rollback: digest never reached NONE in the window. Halt the
    # crypto market so the bot doesn't trade on a contaminated reset.
    box.run(
        "docker exec aaats-paper-crypto python -c "
        "\"from foundation import kill_switch; "
        "kill_switch.halt('crypto', reason='reset_paper_book_200 rollback', "
        "triggered_by='reset_paper_book_200')\"",
        "rollback: halt crypto after digest-wait timeout",
        timeout=60,
    )
    reason = (
        f"digest did not reach Action needed: NONE within {poll_window_sec}s; "
        f"saw action lines: {seen_action_lines[-3:]!r}"
    )
    failure_marker = build_failure_marker(reason, started_at)
    box.write_text(
        f"{remote_dir}/data/d5_day1_marker.json",
        json.dumps(failure_marker, indent=2),
        "write d5_day1_marker.json (failure)",
    )
    return 2, failure_marker


# ── Paramiko-backed BoxIO ─────────────────────────────────────────────────


class _ParamikoBox:
    def __init__(self, client: Any) -> None:
        self._client = client

    def run(self, cmd: str, label: str, timeout: int = 60) -> tuple[int, str]:
        print(f"  -> {label}")
        _, stdout, stderr = self._client.exec_command(cmd, timeout=timeout)
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", "replace").strip()
        err = stderr.read().decode("utf-8", "replace").strip()
        for line in out.splitlines()[-25:]:
            print(f"     {line.encode('ascii', 'replace').decode('ascii')}")
        if rc != 0 and err:
            for line in err.splitlines()[-5:]:
                print(f"     ERR: {line.encode('ascii', 'replace').decode('ascii')}")
        return rc, out

    def write_text(self, remote_path: str, content: str, label: str) -> None:
        print(f"  -> {label}  [{remote_path}]")
        sftp = self._client.open_sftp()
        try:
            tmp = remote_path + ".tmp"
            with sftp.open(tmp, "w") as fh:
                fh.write(content)
            self.run(f"mv -f {tmp} {remote_path}", f"atomic-swap {remote_path}")
        finally:
            sftp.close()


def _load_env(path: _pl.Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().split("#")[0].strip()
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset paper book to $200 starting equity")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the plan and exit without touching the box (default)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually execute the reset against the box",
    )
    args = parser.parse_args(argv)

    if args.apply and args.dry_run:
        print("FATAL: --dry-run and --apply are mutually exclusive")
        return 1
    apply = bool(args.apply)
    dry_run = not apply

    print("=" * 70)
    print("  Reset paper book to $200 starting equity")
    print(f"  Mode: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"  Backtest summary: {BACKTEST_SUMMARY}")
    print("=" * 70)

    try:
        rec = read_backtest_recommendation(BACKTEST_SUMMARY)
    except (FileNotFoundError, ValueError) as exc:
        print(f"FATAL: {exc}")
        return 1
    print(f"  Backtest recommendation: {rec}")

    proceed, msg = _gate_on_backtest(rec)
    print(f"  Gate: {msg}")
    if not proceed:
        return 1

    seed_payload = seed_state_payload(STARTING_EQUITY_USD)
    print(
        f"  Seed payload: $200 floor, crypto.capital=${seed_payload['crypto']['capital']:.2f}"
    )

    if dry_run:
        print()
        print("[DRY-RUN] Re-run with --apply to actually:")
        print("    1. docker compose stop aaats-paper-crypto")
        print("    2. docker volume rm + create deployment_state-crypto-paper")
        print("    3. Seed paper_portfolio.json with $200 starting_equity")
        print("    4. docker compose up -d --no-deps aaats-paper-crypto")
        print("    5. kill_switch.reset('crypto')")
        print(
            f"    6. Wait up to {DIGEST_POLL_WINDOW_SEC // 60} min for "
            "first NONE-NONE digest"
        )
        print("    7. Write data/d5_day1_marker.json")
        return 0

    # APPLY path: connect to box via paramiko.
    env = _load_env(PROJECT_ROOT / ".env")
    host = env.get("CONTABO__TAILSCALE_IP", "100.95.126.39")
    user = env.get("CONTABO__SSH_USER", "aaats")
    password = env.get("CONTABO__SSH_PASSWORD", "")
    remote_dir = env.get("CONTABO__REMOTE_DIR", "/home/aaats/aaats")
    if not password:
        print("FATAL: CONTABO__SSH_PASSWORD not in .env")
        return 1

    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"\nConnecting to {user}@{host}...")
    client.connect(host, port=22, username=user, password=password, timeout=30)
    print("  Connected")

    try:
        box = _ParamikoBox(client)
        exit_code, marker = execute_reset(
            box,
            remote_dir=remote_dir,
            seed_payload=seed_payload,
        )
    finally:
        client.close()

    print()
    print("=" * 70)
    if exit_code == 0:
        print(f"  SUCCESS: D.5 day-1 fired at {marker['day1_at']}")
        print(f"  Marker:  data/d5_day1_marker.json on box")
        print(f"  Watcher armed: days 1-{marker['watcher_window_days']}, "
              f"[${marker['c3_threshold_low_usd']:+.2f}, "
              f"${marker['c3_threshold_high_usd']:+.2f}] on C3 P&L")
    elif exit_code == 2:
        print("  ROLLBACK: digest never reached NONE in window")
        print(f"  Reason: {marker.get('reason', 'unknown')}")
        print("  Operator halt re-engaged on crypto market")
    else:
        print(f"  FAIL: exit_code={exit_code}, reason={marker.get('reason', 'unknown')}")
    print("=" * 70)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
