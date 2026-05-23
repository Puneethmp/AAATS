"""
Heartbeat watchdog — Phase D.2 (2026-05-22).

Runs as a tiny sidecar container next to `aaats-paper-crypto`. Tails
``data/heartbeat.json`` (the FLAT schema written by the runner). When the
heartbeat goes stale (age > ``STALE_THRESHOLD_SEC`` = 3 × cycle interval),
fires a Telegram alert and restarts the trading container via the host
Docker socket. Restarts are rate-limited to 3 inside a 30-minute window;
the 4th detection inside that window escalates (Telegram-only, no further
restart) so the watchdog cannot itself become a restart-thrash failure
mode.

Detection is **decoupled** from the host Docker healthcheck — Docker
``healthy`` has historically been a load-bearing lie (cf.
``docs/specs/reliability_failure_modes.md`` rows 3, 21). The trading
heartbeat file is the authoritative liveness signal.

Architecture:
    health/watchdog.py
        WatchdogState     — pure-logic decision machine, easily unit-tested.
        Watchdog          — IO shell: file reads, docker restart, Telegram.
        main()            — loops at POLL_INTERVAL_SEC; emits a self-heartbeat.

Compose service: see deployment/Dockerfile.watchdog + the `aaats-watchdog`
entry in deployment/docker-compose.yml.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time as _time_obj, timedelta, timezone
from pathlib import Path
from typing import Iterable

# ── Configuration ────────────────────────────────────────────────────────────

# Runner cycle interval (paper-crypto). The runner writes a heartbeat at
# the end of each cycle, so 3 × this interval is the latest a healthy
# container's heartbeat could reasonably be.
CYCLE_INTERVAL_SEC = int(os.environ.get("WATCHDOG_CYCLE_INTERVAL_SEC", "900"))
STALE_THRESHOLD_SEC = 3 * CYCLE_INTERVAL_SEC
POLL_INTERVAL_SEC = int(os.environ.get("WATCHDOG_POLL_INTERVAL_SEC", "60"))
RATE_LIMIT_MAX_RESTARTS = int(os.environ.get("WATCHDOG_MAX_RESTARTS", "3"))
RATE_LIMIT_WINDOW_SEC = int(os.environ.get("WATCHDOG_RATE_WINDOW_SEC", "1800"))

# Daily pager threshold (2026-05-23 session 12 [1] fix). Per the
# operator-away protocol: "5+ container restarts in one calendar day"
# triggers a pager-level Telegram alert + auto-HALT_ALL via kill_switch.
# Implemented as a rolling 24h window (TTL=86400s) of restart timestamps
# persisted to data/watchdog_state.json so the count survives the
# watchdog process restarting.
DAILY_RESTART_PAGER_THRESHOLD = int(os.environ.get("WATCHDOG_DAILY_PAGER_THRESHOLD", "5"))
DAILY_RESTART_TTL_SEC = 24 * 3600

DATA_DIR = Path(os.environ.get("AAATS_DATA", "/app/data"))
HEARTBEAT_PATH = DATA_DIR / "heartbeat.json"
WATCHDOG_HEARTBEAT_PATH = DATA_DIR / "watchdog_heartbeat.json"
WATCHDOG_STATE_PATH = DATA_DIR / "watchdog_state.json"

# D.4 daily digest dispatch: fire once per IST calendar day at >= DIGEST_HOUR_IST
# (default 09:00 IST). Guard with a digest_log.json check so the watchdog's
# 60-second poll only sends one message per day.
IST = timezone(timedelta(hours=5, minutes=30))
DIGEST_HOUR_IST = int(os.environ.get("WATCHDOG_DIGEST_HOUR_IST", "9"))
DIGEST_DISABLED = os.environ.get("WATCHDOG_DIGEST_DISABLED", "0") in ("1", "true", "True")

TARGET_CONTAINER = os.environ.get("WATCHDOG_TARGET", "aaats-paper-crypto")
DOCKER_BIN = os.environ.get("DOCKER_BIN", "/usr/bin/docker")

log = logging.getLogger("watchdog")


# ── Decision state ──────────────────────────────────────────────────────────


@dataclass
class WatchdogState:
    """Pure-logic decision machine — no IO. Unit-tested directly.

    Decisions returned by ``classify``:
      - ``"ok"``        — heartbeat is fresh; no action.
      - ``"missing"``   — heartbeat file absent / unreadable; treated as stale
                          but logged differently for diagnostics.
      - ``"restart"``   — heartbeat stale + rate-limit window has capacity.
      - ``"escalate"``  — heartbeat stale + rate-limit exhausted; Telegram-only.
    """

    stale_threshold_sec: float = STALE_THRESHOLD_SEC
    rate_limit_max: int = RATE_LIMIT_MAX_RESTARTS
    rate_limit_window_sec: float = RATE_LIMIT_WINDOW_SEC
    restart_history: deque[float] = field(default_factory=deque)

    def _prune_history(self, now_ts: float) -> None:
        cutoff = now_ts - self.rate_limit_window_sec
        while self.restart_history and self.restart_history[0] < cutoff:
            self.restart_history.popleft()

    def classify(
        self,
        heartbeat_ts: float | None,
        now_ts: float,
    ) -> str:
        """Return the decision verb for the current heartbeat snapshot."""
        self._prune_history(now_ts)

        if heartbeat_ts is None:
            decision_base = "missing"
        else:
            age = now_ts - heartbeat_ts
            if age <= self.stale_threshold_sec:
                return "ok"
            decision_base = "stale"

        if len(self.restart_history) >= self.rate_limit_max:
            return "escalate"
        return "restart" if decision_base != "missing" else "restart_missing"

    def record_restart(self, now_ts: float) -> None:
        """Record a restart attempt at ``now_ts`` for rate-limit accounting."""
        self.restart_history.append(now_ts)

    def restart_count_in_window(self, now_ts: float) -> int:
        self._prune_history(now_ts)
        return len(self.restart_history)


# ── IO shell ────────────────────────────────────────────────────────────────


def _read_heartbeat_ts(path: Path) -> float | None:
    """Return the heartbeat timestamp as a unix epoch, or None on failure."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        ts_str = raw.get("timestamp")
        if not isinstance(ts_str, str):
            return None
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        log.warning("heartbeat read failed: %s", exc)
        return None


def _send_alert(msg: str, severity: str | None = None, market: str = "system") -> None:
    """Best-effort Telegram alert. Silently swallows on any failure.

    severity: forwarded to observability.alerts.send_alert when supplied
    (valid values: 'info' | 'warn' | 'critical'). None lets the alerts
    module auto-infer from the message body."""
    try:
        from observability.alerts import send_alert
        kwargs: dict[str, str] = {"market": market}
        if severity is not None:
            kwargs["severity"] = severity
        send_alert(msg, **kwargs)
    except Exception as exc:
        log.warning("telegram send failed: %s", exc)


def _load_persistent_restart_history(now_ts: float | None = None) -> list[float]:
    """Read restart timestamps from WATCHDOG_STATE_PATH, dropping entries
    older than DAILY_RESTART_TTL_SEC. Returns an empty list on any read
    failure (the watchdog must remain functional even if the state file
    is missing/corrupt)."""
    now_ts = time.time() if now_ts is None else now_ts
    cutoff = now_ts - DAILY_RESTART_TTL_SEC
    try:
        raw = json.loads(WATCHDOG_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(raw, dict):
        return []
    history = raw.get("restart_history_24h", [])
    if not isinstance(history, list):
        return []
    out: list[float] = []
    for ts in history:
        try:
            f = float(ts)
        except (TypeError, ValueError):
            continue
        if f >= cutoff:
            out.append(f)
    return out


def _save_persistent_restart_history(history: list[float]) -> None:
    """Write the restart-history list back to WATCHDOG_STATE_PATH. Atomic."""
    try:
        WATCHDOG_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = WATCHDOG_STATE_PATH.with_suffix(".tmp")
        payload = {"restart_history_24h": list(history)}
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(WATCHDOG_STATE_PATH)
    except OSError as exc:
        log.warning("watchdog_state.json write failed: %s", exc)


def _check_daily_pager_threshold(
    history: list[float],
    threshold: int = DAILY_RESTART_PAGER_THRESHOLD,
    target_market: str = "crypto",
) -> bool:
    """If the rolling 24h restart count meets the pager threshold, fire
    a pager-level Telegram alert AND auto-halt the trading market.

    Returns True when the threshold path fired (caller may want to skip
    further actions). Idempotent against the *same* count crossing —
    successive restarts above the threshold each refire, since the cost
    of a duplicate pager is small compared to missing a real failure."""
    if len(history) < threshold:
        return False

    msg = (
        f"[PAGER] D.2 watchdog: {len(history)} restarts of "
        f"aaats-paper-crypto in last 24h (threshold {threshold}). "
        f"Auto-halting {target_market}. Operator intervention required."
    )
    _send_alert(msg, severity="critical", market=target_market)

    try:
        from foundation import kill_switch
        kill_switch.halt(
            target_market,
            reason=f"watchdog: {len(history)} restarts in 24h",
            triggered_by="watchdog_daily_threshold",
        )
    except Exception as exc:
        log.error("kill_switch.halt(%s) failed: %s", target_market, exc)
    return True


def _restart_container(container: str = TARGET_CONTAINER) -> bool:
    """Run ``docker restart <container>``. Returns True on success."""
    try:
        proc = subprocess.run(
            [DOCKER_BIN, "restart", container],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode == 0:
            log.info("restarted %s: %s", container, proc.stdout.strip())
            return True
        log.error(
            "docker restart %s failed rc=%d stderr=%s",
            container, proc.returncode, proc.stderr.strip(),
        )
        return False
    except (subprocess.SubprocessError, OSError) as exc:
        log.error("docker restart %s raised: %s", container, exc)
        return False


def _emit_self_heartbeat(payload: dict) -> None:
    """Write the watchdog's own heartbeat (for meta-observability)."""
    try:
        WATCHDOG_HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = WATCHDOG_HEARTBEAT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(WATCHDOG_HEARTBEAT_PATH)
    except OSError:
        pass


# ── Main loop ───────────────────────────────────────────────────────────────


class Watchdog:
    """IO shell around WatchdogState. Real instances also do file IO + Telegram."""

    def __init__(
        self,
        heartbeat_path: Path = HEARTBEAT_PATH,
        target_container: str = TARGET_CONTAINER,
        state: WatchdogState | None = None,
    ):
        self.heartbeat_path = heartbeat_path
        self.target_container = target_container
        self.state = state if state is not None else WatchdogState()
        # 24h cumulative restart counter, distinct from the in-memory
        # rate-limit window. Hydrated from data/watchdog_state.json so a
        # watchdog process restart doesn't reset the 24h count.
        self._daily_history: list[float] = _load_persistent_restart_history()
        if self._daily_history:
            log.info(
                "watchdog hydrated %d restart timestamps from %s (last 24h)",
                len(self._daily_history), WATCHDOG_STATE_PATH,
            )

    def tick(self, now_ts: float | None = None) -> str:
        """One observation + decision + action. Returns the decision verb."""
        now_ts = time.time() if now_ts is None else now_ts
        heartbeat_ts = _read_heartbeat_ts(self.heartbeat_path)
        verb = self.state.classify(heartbeat_ts, now_ts)

        if verb == "ok":
            return verb

        age_str = (
            f"{int(now_ts - heartbeat_ts)}s"
            if heartbeat_ts is not None else "missing"
        )
        log.warning("watchdog tick: %s (heartbeat age=%s)", verb, age_str)

        if verb in ("restart", "restart_missing"):
            msg = (
                f"[D.2] heartbeat stale (age={age_str}) — restarting "
                f"{self.target_container} "
                f"(restart {self.state.restart_count_in_window(now_ts) + 1}/"
                f"{self.state.rate_limit_max} in window)"
            )
            _send_alert(msg)
            ok = _restart_container(self.target_container)
            self.state.record_restart(now_ts)
            # Persist + check the 24h pager threshold (session 12 [1] fix
            # for "5+ restarts/calendar day" pre-auth row in the
            # operator-away runbook).
            self._daily_history.append(now_ts)
            # Prune in-place to 24h.
            cutoff = now_ts - DAILY_RESTART_TTL_SEC
            self._daily_history = [t for t in self._daily_history if t >= cutoff]
            _save_persistent_restart_history(self._daily_history)
            _check_daily_pager_threshold(self._daily_history)
            if not ok:
                _send_alert(
                    f"[PAGER] [D.2] docker restart {self.target_container} "
                    "FAILED — operator intervention required",
                    severity="critical",
                )
            return verb

        # verb == "escalate" — 3 restarts in 30 min and rate-limit hit.
        # This is exactly the failure mode that warrants a phone-buzz,
        # so upgrade to pager-level (session 12 [1] fix). The cumulative
        # 24h threshold above also catches this independently if 5+
        # restarts have happened across multiple rate windows.
        _send_alert(
            f"[PAGER] [D.2] ESCALATION: heartbeat stale (age={age_str}) but rate "
            f"limit hit ({self.state.rate_limit_max} restarts in "
            f"{self.state.rate_limit_window_sec}s). No further auto-restart; "
            "operator must intervene.",
            severity="critical",
        )
        return verb


def _maybe_dispatch_digest(now_utc: datetime | None = None) -> str | None:
    """Fire the daily digest if it's after 09:00 IST and not yet sent today.

    Returns the IST date string the digest was sent for, or None if no send
    happened this tick (either too early in the day, or already sent).
    Exceptions are swallowed — a digest failure must NEVER kill the watchdog.
    """
    if DIGEST_DISABLED:
        return None
    now_utc = now_utc if now_utc is not None else datetime.now(timezone.utc)
    ist_now = now_utc.astimezone(IST)
    if ist_now.hour < DIGEST_HOUR_IST:
        return None
    try:
        from monitoring.daily_digest import (
            DigestConfig, _digest_sent_today, build_and_send_digest,
        )
    except Exception as exc:
        log.warning("daily_digest import failed: %s", exc)
        return None
    try:
        cfg = DigestConfig.from_data_dir(DATA_DIR)
        if _digest_sent_today(cfg, ist_now.date()):
            return None
        build_and_send_digest(data_dir=DATA_DIR, as_of=now_utc, dry_run=False)
        log.info("[digest] sent %s", ist_now.date().isoformat())
        return ist_now.date().isoformat()
    except Exception as exc:
        log.exception("daily digest dispatch failed: %s", exc)
        return None


def main() -> int:
    """Run forever, polling every POLL_INTERVAL_SEC."""
    logging.basicConfig(
        level=os.environ.get("WATCHDOG_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log.info(
        "watchdog starting target=%s stale_threshold=%ds poll=%ds rate=%d/%ds "
        "digest_hour_ist=%d digest_disabled=%s",
        TARGET_CONTAINER, STALE_THRESHOLD_SEC, POLL_INTERVAL_SEC,
        RATE_LIMIT_MAX_RESTARTS, RATE_LIMIT_WINDOW_SEC,
        DIGEST_HOUR_IST, DIGEST_DISABLED,
    )
    wd = Watchdog()
    while True:
        try:
            verb = wd.tick()
            digest_sent_for = _maybe_dispatch_digest()
            _emit_self_heartbeat({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "last_decision": verb,
                "restart_count_in_window": wd.state.restart_count_in_window(time.time()),
                "target": TARGET_CONTAINER,
                "last_digest_sent_for": digest_sent_for,
            })
        except Exception as exc:
            log.exception("watchdog tick raised: %s", exc)
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    sys.exit(main())
