# Pager-on-5+restart-in-24h was missing (D.2 escalation was info-only)

**Discovered:** 2026-05-23 (post-incident analysis of 2026-05-23T13:29-15:30 crash loop)
**Status:** FIXED, session 12 [1]
**Severity:** Pre-departure blocker (per `docs/runbooks/2026-05-23_operator_away_protocol.md`)

## What was missing

The operator-away protocol's pre-auth matrix says:

> **Container restart by D.2 watchdog (5+ in one calendar day)** | HALT_ALL via `kill.py` CLI auto-invocation. Telegram pager-level alert.

But the watchdog code at [health/watchdog.py:235-242](../../health/watchdog.py#L235-L242) only emitted an **info-level** message on escalation:

```python
# verb == "escalate"
_send_alert(
    f"[D.2] ESCALATION: heartbeat stale (age={age_str}) but rate "
    f"limit hit ({self.state.rate_limit_max} restarts in "
    f"{self.state.rate_limit_window_sec}s). No further auto-restart; "
    "operator must intervene."
)
```

And it had no concept of "5+ in a calendar day":

- `WatchdogState.restart_history` is in-memory only — survives container exit but not watchdog process restart.
- The rate limit is 3 in a rolling 1800s (30 min), not 5 in 24h.
- The escalation message lacks the `[PAGER]` prefix and uses default severity (info-inferred).
- No call to `foundation.kill_switch.halt("crypto", ...)` — the runbook claims auto-HALT_ALL, code had no such path.

## How it surfaced (2026-05-23 incident)

The phantom-ENA crash loop produced 6 container restarts in ~2 hours (RestartCount went from 0 to 6 between 12:46Z and 14:38Z per `docker inspect`). The watchdog correctly issued the first 3 restarts in each 30-min window and then escalated, but the escalations were info-level Telegram messages that don't surface as pagers on the operator's phone. The operator (had they been AFK) would have seen no pager and no auto-halt; the bot would have continued crash-looping indefinitely until the rate-window reset, then restarted again.

## Fix shipped (session 12 [1])

[health/watchdog.py](../../health/watchdog.py) gains:

1. **Persistent restart history** — `data/watchdog_state.json` stores all restart timestamps from the last 24h. `WatchdogState.__init__` hydrates from this file; `record_restart` writes back. Survives watchdog process restart.

2. **Daily threshold + pager + auto-halt** — new `_check_daily_pager_threshold` runs after each `record_restart`. When count in last 24h ≥ `WATCHDOG_DAILY_PAGER_THRESHOLD` (default 5):
   - `send_alert(f"[PAGER] D.2 watchdog: {n} restarts in 24h ...", severity="critical")`
   - `kill_switch.halt("crypto", reason="watchdog: {n} restarts in 24h", triggered_by="watchdog_daily_threshold")`
   - Idempotent for the same window — only fires once per 5-restart-threshold-crossing.

3. **`_send_alert` severity parameter** — the helper now accepts `severity=` and forwards to `observability.alerts.send_alert` so escalation messages carry critical severity.

4. **Escalation upgrade** — the existing in-window ESCALATION path now also sends with `[PAGER]` prefix + severity="critical", since "3 restarts in 30 min and rate-limit hit" is exactly the case where a phone-buzz is warranted.

## Tests

[tests/test_pager_on_restart_storm.py](../../tests/test_pager_on_restart_storm.py) — 5 cases:

- `test_persistent_history_roundtrip` — write 7 entries, reload, assert ordering + count.
- `test_persistent_history_prunes_past_24h` — old entries (>24h) get dropped on load.
- `test_daily_threshold_fires_pager_and_halt` — recording the 5th restart in <24h fires both `send_alert([PAGER]...)` and `kill_switch.halt("crypto", ...)`.
- `test_daily_threshold_does_not_fire_below_threshold` — 4 restarts → no pager.
- `test_escalation_message_carries_pager_prefix_and_critical_severity` — the existing in-window escalation now produces a pager-level message.

## Cross-references

- `docs/runbooks/2026-05-23_operator_away_protocol.md` — the runbook line this was missing.
- `health/watchdog.py` — the file with the fix.
- `tests/test_pager_on_restart_storm.py` — the regression pin.
- 2026-05-23 ENA phantom-position incident — the bug class that surfaced this gap.
