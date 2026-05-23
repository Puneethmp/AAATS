"""
Phase D.4 — Daily health digest to Telegram.

Composes one Telegram message per IST calendar day summarising:
  - 24h P&L (realized, unrealized, equity vs peak)
  - Operational state (cycle count, exceptions, restarts, alerts)
  - Strategy activity (firing, silent, halted)
  - An Action-needed line that defaults to "NONE"

Format is LOCKED in docs/decisions/2026-05-21_track_d_reliability_addendum.md
Appendix A; data-source mapping is in docs/decisions/2026-05-23_daily_digest_design.md.

The build half is a pure function (build_digest); the send half is an IO
shell (build_and_send_digest) that the aaats-watchdog poll loop dispatches
at 09:00 IST per day. CLI mode supports dry-run on workstation + box.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))
REBUILD_ANCHOR_DATE = date(2026, 5, 12)


# ── Configuration ───────────────────────────────────────────────────────────


@dataclass
class DigestConfig:
    data_dir: Path
    db_path: Path
    risk_state_path: Path
    exception_state_path: Path
    halt_state_path: Path
    share_eq_path: Path
    watchdog_heartbeat_path: Path
    digest_log_path: Path
    digests_archive_dir: Path
    alerts_log_path: Path
    target_container: str = "aaats-paper-crypto"
    cycle_interval_sec: int = 900  # paper-crypto runs every 15 min

    @classmethod
    def from_data_dir(cls, data_dir: Path | str) -> "DigestConfig":
        d = Path(data_dir)
        # The risk-engine state path now follows the A.1 per-mode discriminator.
        # Try state-paper first (post-A.1), fall back to legacy state/.
        candidates = [
            d / "state-paper" / "risk_engine_state.paper.json",
            d / "state" / "risk_engine_state.json",
        ]
        risk_path = next((c for c in candidates if c.exists()), candidates[0])
        return cls(
            data_dir=d,
            db_path=d / "paper_trades.db",
            risk_state_path=risk_path,
            exception_state_path=d / "strategy_exception_state.json",
            halt_state_path=d / "strategy_halt_state.json",
            share_eq_path=d / "share_equality_mismatches.json",
            watchdog_heartbeat_path=d / "watchdog_heartbeat.json",
            digest_log_path=d / "digest_log.json",
            digests_archive_dir=d / "digests",
            alerts_log_path=d / "alerts_log.json",
        )


# ── Section builders (pure functions) ───────────────────────────────────────


@dataclass
class SectionPnl:
    realized_24h: float | None = None
    unrealized: float | None = None
    equity: float | None = None
    peak: float | None = None
    drawdown_pct: float | None = None


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _format_money(v: float | None, *, sign: bool = True) -> str:
    if v is None:
        return "N/A"
    fmt = f"{v:+.2f}" if sign else f"{v:.2f}"
    return f"${fmt}"


def _query(cfg: DigestConfig, sql: str, params: tuple = ()) -> list[tuple]:
    if not cfg.db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(cfg.db_path))
        try:
            return list(conn.execute(sql, params).fetchall())
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def _window_bounds(as_of: datetime) -> tuple[str, str]:
    """24-hour window ending at as_of (UTC). Both bounds are ISO strings."""
    end = as_of.astimezone(timezone.utc)
    start = end - timedelta(hours=24)
    return start.isoformat(), end.isoformat()


def build_pnl_section(cfg: DigestConfig, as_of: datetime) -> SectionPnl:
    sec = SectionPnl()
    start_iso, end_iso = _window_bounds(as_of)
    # Realized — sum of pnl on SELL trades in the last 24h.
    rows = _query(
        cfg,
        "SELECT COALESCE(SUM(pnl), 0.0) FROM paper_trades "
        "WHERE action='SELL' AND timestamp >= ? AND timestamp < ?",
        (start_iso, end_iso),
    )
    if rows:
        sec.realized_24h = float(rows[0][0])

    # Unrealized — open BUY rows minus matched SELL rows; for the digest's
    # purposes we use the simpler proxy of net open BUY notional - SELL
    # notional per (market, symbol). Cross-strategy reconciliation is
    # explicitly out of scope (see design memo).
    open_rows = _query(
        cfg,
        "SELECT market, symbol, action, COALESCE(SUM(shares), 0.0), "
        "       COALESCE(SUM(value), 0.0), MAX(price) "
        "FROM paper_trades "
        "WHERE strategy NOT IN ('C5b_funding_arb', 'C1_stat_arb') "
        "GROUP BY market, symbol, action",
    )
    pos: dict[tuple[str, str], dict[str, float]] = {}
    for market, symbol, action, shares, value, last_price in open_rows:
        key = (market, symbol)
        slot = pos.setdefault(key, {"buy_shares": 0.0, "buy_value": 0.0,
                                   "sell_shares": 0.0, "sell_value": 0.0,
                                   "last_price": 0.0})
        slot["last_price"] = float(last_price or 0.0) or slot["last_price"]
        if action == "BUY":
            slot["buy_shares"] += float(shares or 0.0)
            slot["buy_value"] += float(value or 0.0)
        elif action == "SELL":
            slot["sell_shares"] += float(shares or 0.0)
            slot["sell_value"] += float(value or 0.0)

    unrealized = 0.0
    have_any_open = False
    for slot in pos.values():
        net = slot["buy_shares"] - slot["sell_shares"]
        if abs(net) < 1e-9:
            continue
        have_any_open = True
        # Approximate entry price = buy_value / buy_shares. If the symbol
        # has no remaining BUY notional, skip (closed position with tiny dust).
        if slot["buy_shares"] <= 0:
            continue
        avg_buy = slot["buy_value"] / slot["buy_shares"]
        last = slot["last_price"] or avg_buy
        unrealized += (last - avg_buy) * net
    sec.unrealized = unrealized if have_any_open else 0.0

    # Equity / peak — from the risk-engine state.
    risk = _read_json(cfg.risk_state_path)
    if isinstance(risk, dict):
        sec.equity = float(risk.get("last_equity")) if risk.get("last_equity") is not None else None
        sec.peak = float(risk.get("peak")) if risk.get("peak") is not None else None
        if sec.equity is not None and sec.peak and sec.peak > 0:
            sec.drawdown_pct = (sec.equity - sec.peak) / sec.peak * 100.0
    return sec


def render_pnl_section(sec: SectionPnl) -> str:
    lines = ["P&L (24h)"]
    lines.append(f"  Realized:   {_format_money(sec.realized_24h)}")
    lines.append(f"  Unrealized: {_format_money(sec.unrealized)}")
    if sec.equity is not None:
        peak_str = _format_money(sec.peak, sign=False) if sec.peak is not None else "N/A"
        dd_str = f"{sec.drawdown_pct:+.1f}%" if sec.drawdown_pct is not None else "N/A"
        lines.append(f"  Equity:     {_format_money(sec.equity, sign=False)}  (peak {peak_str}, dd {dd_str})")
    else:
        lines.append("  Equity:     N/A  (peak N/A, dd N/A)")
    return "\n".join(lines)


@dataclass
class SectionOps:
    cycles_run: int = 0
    cycles_expected: int = 96  # 86400 / 900
    uptime_pct: float = 0.0
    exceptions_total: int = 0
    halted_24h: int = 0
    container_restarts: int = 0
    auto_restarts: int = 0
    manual_restarts: int = 0
    alerts_fired: int = 0
    alerts_open: int = 0
    alerts_resolved: int = 0
    cycles_known: bool = True
    restarts_known: bool = True
    alerts_known: bool = False


def _count_alerts_in_window(
    alerts_log: Any,
    start_iso: str,
    end_iso: str,
) -> tuple[int, int, int]:
    """Count fired / open / resolved alerts in the 24h window.

    The log is a flat list of dict rows; ``resolved`` rows carry an
    ``unresolves`` field referencing a prior correlation_id. ``open`` =
    fired in window AND no matching resolution in window.
    """
    if not isinstance(alerts_log, list):
        return 0, 0, 0
    fired_in_window: list[dict[str, Any]] = []
    resolved_cids: set[str] = set()
    for row in alerts_log:
        if not isinstance(row, dict):
            continue
        ts = str(row.get("ts", ""))
        if not (start_iso <= ts < end_iso):
            continue
        unresolves = row.get("unresolves")
        if isinstance(unresolves, str) and unresolves:
            resolved_cids.add(unresolves)
            continue
        fired_in_window.append(row)
    fired = len(fired_in_window)
    open_n = sum(
        1 for r in fired_in_window
        if r.get("correlation_id") not in resolved_cids
    )
    resolved = len(resolved_cids)
    return fired, open_n, resolved


def build_ops_section(
    cfg: DigestConfig,
    as_of: datetime,
    container_restart_count: int | None = None,
    yesterdays_restart_count: int | None = None,
) -> SectionOps:
    sec = SectionOps()
    sec.cycles_expected = max(int(86400 / cfg.cycle_interval_sec), 1)

    start_iso, end_iso = _window_bounds(as_of)
    # cycle_log table is added by trading/live_paper_runner.py next to the
    # heartbeat write. Schema: (timestamp, cycle, market). May not exist on
    # legacy DBs — fall back to "unknown".
    rows = _query(
        cfg,
        "SELECT COUNT(*) FROM cycle_log "
        "WHERE timestamp >= ? AND timestamp < ?",
        (start_iso, end_iso),
    )
    if rows and rows[0][0] is not None:
        sec.cycles_run = int(rows[0][0])
        sec.uptime_pct = sec.cycles_run / sec.cycles_expected * 100.0
        sec.cycles_known = True
    else:
        sec.cycles_known = False

    # Exceptions — sum across all strategies.
    exc_state = _read_json(cfg.exception_state_path) or {}
    if isinstance(exc_state, dict):
        sec.exceptions_total = sum(
            int(entry.get("total_exceptions", 0))
            for entry in exc_state.values()
            if isinstance(entry, dict)
        )

    halt_state = _read_json(cfg.halt_state_path) or {}
    if isinstance(halt_state, dict):
        cutoff = (as_of - timedelta(hours=24)).astimezone(timezone.utc)
        for sid, entry in halt_state.items():
            if not isinstance(entry, dict):
                continue
            if not entry.get("halted"):
                continue
            try:
                halted_at = datetime.fromisoformat(str(entry.get("halted_at", "")))
                if halted_at.tzinfo is None:
                    halted_at = halted_at.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if halted_at >= cutoff:
                sec.halted_24h += 1

    if container_restart_count is None:
        sec.restarts_known = False
    else:
        if yesterdays_restart_count is None:
            sec.container_restarts = container_restart_count
        else:
            sec.container_restarts = max(
                container_restart_count - yesterdays_restart_count, 0
            )
        wd_hb = _read_json(cfg.watchdog_heartbeat_path) or {}
        if isinstance(wd_hb, dict):
            sec.auto_restarts = int(wd_hb.get("restart_count_in_window", 0))
        sec.auto_restarts = min(sec.auto_restarts, sec.container_restarts)
        sec.manual_restarts = sec.container_restarts - sec.auto_restarts

    alerts_log = _read_json(cfg.alerts_log_path)
    if alerts_log is not None:
        sec.alerts_known = True
        sec.alerts_fired, sec.alerts_open, sec.alerts_resolved = (
            _count_alerts_in_window(alerts_log, start_iso, end_iso)
        )

    return sec


def render_ops_section(sec: SectionOps) -> str:
    lines = ["Operational"]
    if sec.cycles_known:
        lines.append(
            f"  Cycles run:        {sec.cycles_run} "
            f"(expected {sec.cycles_expected}, {sec.uptime_pct:.1f}% uptime)"
        )
    else:
        lines.append(
            f"  Cycles run:        N/A "
            f"(expected {sec.cycles_expected}, uptime N/A — cycle_log unavailable)"
        )
    lines.append(f"  Exceptions:        {sec.exceptions_total}  ({sec.halted_24h} auto-halted)")
    if sec.restarts_known:
        lines.append(
            f"  Container restarts: {sec.container_restarts}  "
            f"(auto: {sec.auto_restarts}, manual: {sec.manual_restarts})"
        )
    else:
        lines.append("  Container restarts: N/A  (docker inspect unavailable)")
    if sec.alerts_known:
        lines.append(
            f"  Alerts fired:      {sec.alerts_fired}  "
            f"(open: {sec.alerts_open}, resolved: {sec.alerts_resolved})"
        )
    else:
        lines.append("  Alerts fired:      N/A  (alerts_log not yet populated)")
    return "\n".join(lines)


@dataclass
class SectionStrategies:
    firing: list[tuple[str, int]] = field(default_factory=list)
    silent: list[str] = field(default_factory=list)
    halted: list[tuple[str, str, str]] = field(default_factory=list)


# Doctrine universe of strategies that the runner may dispatch on crypto.
# Used only to compute "silent" — strategies that exist in code but produced
# zero trades in the window. Drift here is harmless (renamed strategy will
# just appear silent until updated).
DOCTRINE_CRYPTO_STRATS: tuple[str, ...] = (
    "C1_stat_arb",
    "C2_momentum",
    "C3_altcoin_reversion",
    "C5b_funding_arb",
    "C6_bollinger_range",
)


def build_strategies_section(cfg: DigestConfig, as_of: datetime) -> SectionStrategies:
    sec = SectionStrategies()
    start_iso, end_iso = _window_bounds(as_of)
    rows = _query(
        cfg,
        "SELECT COALESCE(strategy, ''), COUNT(*) FROM paper_trades "
        "WHERE timestamp >= ? AND timestamp < ? "
        "GROUP BY strategy ORDER BY COUNT(*) DESC LIMIT 5",
        (start_iso, end_iso),
    )
    firing_set: set[str] = set()
    for strat, count in rows:
        s = (strat or "").strip()
        if not s:
            continue
        sec.firing.append((s, int(count)))
        firing_set.add(s)
    sec.firing = sec.firing[:3]

    halt_state = _read_json(cfg.halt_state_path) or {}
    halted_set: set[str] = set()
    if isinstance(halt_state, dict):
        for sid, entry in halt_state.items():
            if isinstance(entry, dict) and entry.get("halted"):
                halted_set.add(sid)
                halted_at = str(entry.get("halted_at", ""))
                halted_date = halted_at[:10] if halted_at else "N/A"
                reason = str(entry.get("reason", ""))[:60]
                sec.halted.append((sid, halted_date, reason))

    universe = set(DOCTRINE_CRYPTO_STRATS) | firing_set | halted_set
    sec.silent = sorted(s for s in universe if s not in firing_set and s not in halted_set)
    return sec


def render_strategies_section(sec: SectionStrategies) -> str:
    lines = ["Strategies (24h)"]
    if sec.firing:
        firing_str = ", ".join(f"{s} ({n} trades)" for s, n in sec.firing)
    else:
        firing_str = "(none)"
    lines.append(f"  Firing:   {firing_str}")
    silent_str = ", ".join(sec.silent) if sec.silent else "(none)"
    lines.append(f"  Silent:   {silent_str}")
    if sec.halted:
        for sid, halted_date, reason in sec.halted:
            lines.append(f"  Halted:   {sid} (since {halted_date}, {reason})")
    else:
        lines.append("  Halted:   (none)")
    return "\n".join(lines)


# ── Action-needed ──────────────────────────────────────────────────────────


def compute_action_needed(
    cfg: DigestConfig,
    pnl: SectionPnl,
    ops: SectionOps,
    strategies: SectionStrategies,
) -> str:
    triggers: list[str] = []

    if pnl.drawdown_pct is not None and pnl.drawdown_pct <= -10.0:
        # Three bands match the kill-switch design (per
        # docs/known_issues/2026-05-23_kill_trigger_investigation.md):
        # -10 to -15  -> approach warning
        # -15 to -20  -> past market-kill, engine refuses new crypto entries
        # <= -20      -> past portfolio-kill, engine refuses entries in ALL markets
        if pnl.drawdown_pct <= -20.0:
            triggers.append(
                f"drawdown {pnl.drawdown_pct:.1f}% past portfolio-kill threshold (-20%); "
                "all new entries blocked, open positions continue to mark-to-market"
            )
        elif pnl.drawdown_pct <= -15.0:
            triggers.append(
                f"drawdown {pnl.drawdown_pct:.1f}% past market-kill threshold (-15%); "
                "new entries blocked, open positions continue to mark-to-market"
            )
        else:
            triggers.append(
                f"drawdown {pnl.drawdown_pct:.1f}% near kill threshold (-15%)"
            )

    exc_state = _read_json(cfg.exception_state_path) or {}
    if isinstance(exc_state, dict):
        for sid, entry in exc_state.items():
            if not isinstance(entry, dict):
                continue
            consec = int(entry.get("consecutive_exceptions", 0))
            if consec >= 2 and sid not in {sid2 for sid2, _, _ in strategies.halted}:
                triggers.append(f"{sid} has {consec} consec exceptions (auto-halt at 3)")

    if ops.restarts_known and ops.manual_restarts > 0:
        triggers.append(
            f"{ops.manual_restarts} manual container restart(s) in last 24h"
        )

    share_eq = _read_json(cfg.share_eq_path)
    if isinstance(share_eq, dict) and any(int(v or 0) > 0 for v in share_eq.values()):
        triggers.append("share-equality mismatch counter non-zero")

    if ops.alerts_known and ops.alerts_open >= 3:
        triggers.append(f"{ops.alerts_open} open alerts in last 24h")

    if not triggers:
        return "NONE"
    return "; ".join(triggers)


# ── C3 divergence-watcher (D3, first-week soak guard) ──────────────────────
#
# Per Cowork decision D3 (2026-05-23): for the first 7 days of the D.5
# soak, if cumulative C3 P&L (in USD, since the d5_day1_marker timestamp)
# exits the band [c3_threshold_low_usd, c3_threshold_high_usd] (default
# [-$2.00, +$2.00]), the watcher auto-HALTs C3 and pages the operator.
# After day 7, the watcher deactivates — C3's normal D.1 isolation
# becomes the only protective layer.


WATCHER_MARKER_FILENAME = "d5_day1_marker.json"


def _parse_marker_day1(marker_text: str) -> datetime | None:
    try:
        payload = json.loads(marker_text)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("day1_at")
    if not isinstance(raw, str):
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def compute_c3_divergence(
    marker: dict[str, Any] | None,
    *,
    db_path: Path | str | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any] | None:
    """Pure-function compute of the watcher state.

    Returns None if the watcher is dormant (marker missing, failed-reset
    marker, or window expired). Otherwise returns a dict with:
        pnl_since_day1_usd  : SUM of paper_trades.pnl WHERE strategy LIKE 'C3%'
                              AND timestamp >= day1_at
        days_into_watcher   : floor((now - day1_at) / 86400)
        within_window       : days_into_watcher < watcher_window_days
        threshold_breach    : 'low' | 'high' | None
        c3_threshold_low_usd, c3_threshold_high_usd, watcher_window_days
        day1_at             : ISO string
    """
    if not isinstance(marker, dict):
        return None
    if not marker.get("divergence_watcher_armed", False):
        return None
    raw_day1 = marker.get("day1_at")
    if not isinstance(raw_day1, str):
        return None
    try:
        day1 = datetime.fromisoformat(raw_day1)
    except ValueError:
        return None
    if day1.tzinfo is None:
        day1 = day1.replace(tzinfo=timezone.utc)

    now = as_of if as_of is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    window_days = int(marker.get("watcher_window_days", 7))
    low = float(marker.get("c3_threshold_low_usd", -2.0))
    high = float(marker.get("c3_threshold_high_usd", 2.0))

    days_into = max(0, int((now - day1).total_seconds() // 86400))
    within = days_into < window_days

    pnl_since_day1 = 0.0
    if db_path is not None:
        db = Path(db_path)
        if db.exists():
            try:
                with sqlite3.connect(str(db)) as conn:
                    row = conn.execute(
                        "SELECT COALESCE(SUM(pnl), 0.0) FROM paper_trades "
                        "WHERE strategy LIKE 'C3%' AND timestamp >= ?",
                        (day1.isoformat(),),
                    ).fetchone()
                    pnl_since_day1 = float(row[0]) if row and row[0] is not None else 0.0
            except sqlite3.Error:
                pnl_since_day1 = 0.0

    breach: str | None = None
    if within:
        if pnl_since_day1 < low:
            breach = "low"
        elif pnl_since_day1 > high:
            breach = "high"

    return {
        "day1_at": day1.isoformat(),
        "days_into_watcher": days_into,
        "watcher_window_days": window_days,
        "within_window": within,
        "pnl_since_day1_usd": round(pnl_since_day1, 4),
        "c3_threshold_low_usd": low,
        "c3_threshold_high_usd": high,
        "threshold_breach": breach,
    }


def render_watcher_row(divergence: dict[str, Any] | None) -> str | None:
    """Render the appended digest row. None when dormant."""
    if not divergence:
        return None
    days = divergence["days_into_watcher"]
    window = divergence["watcher_window_days"]
    pnl = divergence["pnl_since_day1_usd"]
    if not divergence["within_window"]:
        return f"C3 P&L since day-1: ${pnl:+.2f} (watcher inactive, day {days} past +{window})"
    return f"C3 P&L since day-1: ${pnl:+.2f} (watcher active, days {days}/{window})"


def _watcher_marker_path(cfg: DigestConfig) -> Path:
    return cfg.data_dir / WATCHER_MARKER_FILENAME


def enforce_c3_divergence_watcher(
    cfg: DigestConfig,
    as_of: datetime | None = None,
    *,
    halt_strategy_fn: Any = None,
    send_alert_fn: Any = None,
) -> dict[str, Any] | None:
    """Compute divergence + enforce side effects (halt C3 + pager alert)
    if the threshold band was breached inside the 7-day window.

    Side effects are best-effort and isolated — failures must not break
    digest rendering, since the digest job is itself a watchdog.

    Returns the divergence dict (or None) for downstream rendering.
    """
    marker_path = _watcher_marker_path(cfg)
    marker_text = _read_json(marker_path)
    # _read_json returns the parsed dict, not raw text.
    marker = marker_text if isinstance(marker_text, dict) else None

    divergence = compute_c3_divergence(marker, db_path=cfg.db_path, as_of=as_of)
    if not divergence:
        return None
    if not divergence["within_window"]:
        return divergence
    if not divergence["threshold_breach"]:
        return divergence

    # Breach. Halt + pager. Both side effects are best-effort.
    band = (
        f"outside [${divergence['c3_threshold_low_usd']:+.2f}, "
        f"${divergence['c3_threshold_high_usd']:+.2f}]"
    )
    reason = (
        f"C3 divergence-watcher: pnl_since_day1=${divergence['pnl_since_day1_usd']:+.2f}, "
        f"{band} window in soak day {divergence['days_into_watcher']}"
    )
    try:
        if halt_strategy_fn is None:
            from risk.strategy_halt import halt_strategy as _halt
        else:
            _halt = halt_strategy_fn
        _halt("C3_altcoin_reversion", reason=reason, consecutive_exceptions=0)
    except Exception:  # noqa: BLE001 — digest must not crash
        pass

    try:
        if send_alert_fn is None:
            from observability.alerts import send_alert as _send
        else:
            _send = send_alert_fn
        _send(
            f"[PAGER] C3 divergence-watcher: {reason}",
            market="crypto",
            severity="critical",
        )
    except Exception:  # noqa: BLE001 — digest must not crash
        pass

    return divergence


# ── Top-level builder ───────────────────────────────────────────────────────


def _get_container_restart_count(container: str) -> int | None:
    """Best-effort. Returns None if docker is not available or the call fails."""
    if not shutil.which("docker"):
        return None
    try:
        proc = subprocess.run(
            ["docker", "inspect", container, "--format", "{{.RestartCount}}"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return None
        return int(proc.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def _yesterdays_restart_count(cfg: DigestConfig) -> int | None:
    """Read the RestartCount we logged with yesterday's digest."""
    log = _read_json(cfg.digest_log_path)
    if not isinstance(log, list):
        return None
    if not log:
        return None
    last = log[-1]
    if not isinstance(last, dict):
        return None
    val = last.get("container_restart_count")
    return int(val) if isinstance(val, (int, float)) else None


def build_digest(
    cfg: DigestConfig,
    as_of: datetime | None = None,
    container_restart_count: int | None = None,
    yesterdays_restart_count: int | None = None,
) -> str:
    as_of = as_of if as_of is not None else datetime.now(timezone.utc)
    ist_today = as_of.astimezone(IST).date()
    t_plus = (ist_today - REBUILD_ANCHOR_DATE).days

    if container_restart_count is None:
        container_restart_count = _get_container_restart_count(cfg.target_container)
    if yesterdays_restart_count is None:
        yesterdays_restart_count = _yesterdays_restart_count(cfg)

    pnl = build_pnl_section(cfg, as_of)
    ops = build_ops_section(
        cfg, as_of,
        container_restart_count=container_restart_count,
        yesterdays_restart_count=yesterdays_restart_count,
    )
    strategies = build_strategies_section(cfg, as_of)
    action = compute_action_needed(cfg, pnl, ops, strategies)
    divergence = enforce_c3_divergence_watcher(cfg, as_of=as_of)
    watcher_row = render_watcher_row(divergence)

    header = f"AAATS daily digest -- {ist_today.isoformat()} (T+{t_plus} since rebuild)"
    parts = [
        header,
        "",
        render_pnl_section(pnl),
        "",
        render_ops_section(ops),
        "",
        render_strategies_section(strategies),
    ]
    if watcher_row is not None:
        parts.extend(["", watcher_row])
    parts.extend(["", f"Action needed: {action}"])
    return "\n".join(parts)


# ── Persistence helpers ────────────────────────────────────────────────────


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _digest_sent_today(cfg: DigestConfig, ist_today: date) -> bool:
    log = _read_json(cfg.digest_log_path)
    if not isinstance(log, list):
        return False
    iso = ist_today.isoformat()
    return any(
        isinstance(row, dict) and row.get("ist_date") == iso
        for row in log
    )


def _mark_digest_sent(
    cfg: DigestConfig,
    ist_today: date,
    payload: str,
    container_restart_count: int | None,
    sent: bool,
) -> None:
    log = _read_json(cfg.digest_log_path)
    if not isinstance(log, list):
        log = []
    log.append({
        "ist_date": ist_today.isoformat(),
        "sent_at_utc": datetime.now(timezone.utc).isoformat(),
        "container_restart_count": container_restart_count,
        "sent": sent,
        "bytes": len(payload),
    })
    _atomic_write_json(cfg.digest_log_path, log)

    try:
        cfg.digests_archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = cfg.digests_archive_dir / f"{ist_today.isoformat()}.txt"
        archive_path.write_text(payload, encoding="utf-8")
    except OSError:
        pass


# ── IO shell ────────────────────────────────────────────────────────────────


def build_and_send_digest(
    data_dir: Path | str | None = None,
    as_of: datetime | None = None,
    dry_run: bool = False,
) -> str:
    """Build the digest + (optionally) send to Telegram + log + archive."""
    cfg = DigestConfig.from_data_dir(
        data_dir or os.environ.get("AAATS_DATA", "/app/data")
    )
    as_of = as_of if as_of is not None else datetime.now(timezone.utc)
    ist_today = as_of.astimezone(IST).date()
    restart_count = _get_container_restart_count(cfg.target_container)
    body = build_digest(cfg, as_of=as_of, container_restart_count=restart_count)

    sent = False
    if not dry_run:
        try:
            from observability.alerts import send_alert
            send_alert(body, market="system")
            sent = True
        except Exception:
            sent = False
    _mark_digest_sent(cfg, ist_today, body, restart_count, sent)
    return body


# ── CLI ─────────────────────────────────────────────────────────────────────


def _cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AAATS daily digest builder")
    parser.add_argument("--data-dir", default=None,
                        help="override data directory (default $AAATS_DATA or /app/data)")
    parser.add_argument("--as-of", default=None,
                        help="ISO timestamp (UTC) for the digest's right window edge")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the digest to stdout, do not send to Telegram")
    args = parser.parse_args(argv)

    if args.as_of:
        try:
            as_of = datetime.fromisoformat(args.as_of)
            if as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"invalid --as-of: {args.as_of!r}", file=sys.stderr)
            return 2
    else:
        as_of = None

    body = build_and_send_digest(
        data_dir=args.data_dir,
        as_of=as_of,
        dry_run=args.dry_run,
    )
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
