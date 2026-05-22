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
from datetime import datetime, timezone
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

DATA_DIR = Path(os.environ.get("AAATS_DATA", "/app/data"))
HEARTBEAT_PATH = DATA_DIR / "heartbeat.json"
WATCHDOG_HEARTBEAT_PATH = DATA_DIR / "watchdog_heartbeat.json"

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


def _send_alert(msg: str) -> None:
    """Best-effort Telegram alert. Silently swallows on any failure."""
    try:
        from observability.alerts import send_alert
        send_alert(msg, market="system")
    except Exception as exc:
        log.warning("telegram send failed: %s", exc)


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
            if not ok:
                _send_alert(
                    f"[D.2] docker restart {self.target_container} FAILED — "
                    "operator intervention required"
                )
            return verb

        # verb == "escalate"
        _send_alert(
            f"[D.2] ESCALATION: heartbeat stale (age={age_str}) but rate "
            f"limit hit ({self.state.rate_limit_max} restarts in "
            f"{self.state.rate_limit_window_sec}s). No further auto-restart; "
            "operator must intervene."
        )
        return verb


def main() -> int:
    """Run forever, polling every POLL_INTERVAL_SEC."""
    logging.basicConfig(
        level=os.environ.get("WATCHDOG_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log.info(
        "watchdog starting target=%s stale_threshold=%ds poll=%ds rate=%d/%ds",
        TARGET_CONTAINER, STALE_THRESHOLD_SEC, POLL_INTERVAL_SEC,
        RATE_LIMIT_MAX_RESTARTS, RATE_LIMIT_WINDOW_SEC,
    )
    wd = Watchdog()
    while True:
        try:
            verb = wd.tick()
            _emit_self_heartbeat({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "last_decision": verb,
                "restart_count_in_window": wd.state.restart_count_in_window(time.time()),
                "target": TARGET_CONTAINER,
            })
        except Exception as exc:
            log.exception("watchdog tick raised: %s", exc)
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    sys.exit(main())
