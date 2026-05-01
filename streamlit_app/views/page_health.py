"""System Health Panel — lightweight real-time observability for AAATS paper trading."""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from data_layer import get_health_metrics, get_engine_status

_STALE_WARN_S  = 7_200    # 2h — runner considered stale/dead
_STALE_CAUTION = 3_900    # 65 min — slightly late (>1 cycle length)


def _age_str(seconds: int | None) -> str:
    if seconds is None:
        return "N/A"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s ago"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m ago"


def _latency_color(ms: float | None) -> str:
    if ms is None:
        return "gray"
    if ms < 10:
        return "green"
    if ms < 100:
        return "orange"
    return "red"


def render() -> None:
    st.title("System Health")
    st.caption("Live runner diagnostics — auto-refreshes every 30 s.")

    # Manual refresh + auto-refresh
    if st.button("↻ Refresh Now"):
        st.rerun()
    st.html('<meta http-equiv="refresh" content="30">')

    h = get_health_metrics()
    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    # ── ROW 1: Runner status ──────────────────────────────────────────────────
    st.subheader("Runner Status")
    c1, c2, c3, c4 = st.columns(4)

    alive       = h["runner_alive"]
    last_hb_age = h["heartbeat_age_s"]
    last_cy_age = h["last_cycle_age_s"]
    phase_status = h["phase1_status"]

    with c1:
        if alive:
            icon = "🟢" if (last_hb_age is not None and last_hb_age < _STALE_CAUTION) else "🟡"
            st.metric("Runner", f"{icon} ALIVE", delta=f"status: {h['runner_status']}", delta_color="off")
        else:
            st.metric("Runner", "🔴 DEAD / STALE",
                      delta=f"last seen: {_age_str(last_cy_age)}", delta_color="inverse")

    with c2:
        st.metric("Last Heartbeat", _age_str(last_hb_age),
                  delta=h["heartbeat_ts"][:19] if h["heartbeat_ts"] else "never",
                  delta_color="off")

    with c3:
        st.metric("Last Cycle", _age_str(last_cy_age),
                  delta=h["last_cycle_ts"][:19] if h["last_cycle_ts"] else "never",
                  delta_color="off")

    with c4:
        p_icon = {"RUNNING": "🟢", "COMPLETED": "✅", "HALTED": "🔴"}.get(phase_status, "⚪")
        planned = h["phase1_cycles_total"]
        cycle_label = (f"{h['phase1_cycles_done']}/{planned} cycles"
                       if planned else f"{h['phase1_cycles_done']} cycles")
        st.metric("Runner Cycles", cycle_label,
                  delta=f"{p_icon} {phase_status}",
                  delta_color="off")

    # Stale runner warning
    if not alive:
        st.error(
            "**Runner appears dead or stale** — no heartbeat or cycle update in >2h.  \n"
            "**Cloud:** supervisord auto-restarts it. Check `fly logs` if it stays dead.  \n"
            "**Local:** `python scripts/continuous_runner.py`"
        )
    elif last_hb_age is not None and last_hb_age > _STALE_CAUTION:
        st.warning(
            f"Runner heartbeat is {_age_str(last_hb_age)} old — may be stuck in a long cycle or sleeping."
        )

    st.divider()

    # ── ROW 2: Trade and log freshness ────────────────────────────────────────
    st.subheader("Data Freshness")
    d1, d2, d3, d4 = st.columns(4)

    with d1:
        st.metric("Last Trade", _age_str(h["last_trade_age_s"]),
                  delta=h["last_trade_ts"][:19] if h["last_trade_ts"] else "no trades",
                  delta_color="off")

    with d2:
        log_age = h["log_update_age_s"]
        log_icon = "🟢" if (log_age is not None and log_age < 3600) else "🟡"
        st.metric("Log File Freshness", _age_str(log_age),
                  delta=f"{log_icon} updated recently" if log_age and log_age < 3600
                         else "⚠️ no recent updates",
                  delta_color="off")

    with d3:
        st.metric("Streamlit Refresh", now_str,
                  delta="auto every 30s", delta_color="off")

    with d4:
        cc = h["cycle_count"]
        st.metric("Cycles Completed", str(cc),
                  delta="cumulative since start", delta_color="off")

    st.divider()

    # ── ROW 3: Performance metrics ────────────────────────────────────────────
    st.subheader("Performance")
    p1, p2, p3 = st.columns(3)

    with p1:
        db_lat = h["db_write_latency_ms"]
        if db_lat is not None:
            col = _latency_color(db_lat)
            st.metric("DB Write Latency",
                      f"{db_lat} ms",
                      delta="🟢 fast" if db_lat < 10 else ("🟡 ok" if db_lat < 100 else "🔴 slow"),
                      delta_color="off")
        else:
            st.metric("DB Write Latency", "N/A", delta_color="off")

    with p2:
        mem = h["memory_mb"]
        if mem is not None:
            st.metric("Streamlit Memory", f"{mem} MB",
                      delta="🟢 ok" if mem < 300 else "🟡 watch",
                      delta_color="off")
        else:
            st.metric("Streamlit Memory", "N/A (psutil not installed)", delta_color="off")

    with p3:
        cpu = h["cpu_pct"]
        if cpu is not None:
            st.metric("Streamlit CPU", f"{cpu:.1f}%",
                      delta="🟢 ok" if cpu < 20 else "🟡 elevated",
                      delta_color="off")
        else:
            st.metric("Streamlit CPU", "N/A", delta_color="off")

    st.divider()

    # ── ROW 4: Full engine status table ──────────────────────────────────────
    st.subheader("Engine Status (all markets)")

    status_df = get_engine_status()
    if status_df.empty:
        st.info("No engine status data yet — runner has not completed a cycle.")
    else:
        # Compute staleness for each row
        display_rows = []
        for _, row in status_df.iterrows():
            age_s = None
            hb_ts = str(row.get("heartbeat_ts") or "")
            lr_ts = str(row.get("last_run") or "")
            for ts in [hb_ts, lr_ts]:
                if ts:
                    try:
                        dt = datetime.fromisoformat(ts)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        age_s = round((datetime.now(timezone.utc) - dt).total_seconds())
                        break
                    except Exception:
                        pass
            alive_flag = (age_s is not None and age_s < _STALE_WARN_S)
            display_rows.append({
                "market":          str(row.get("market", "")),
                "status":          str(row.get("status", "")),
                "regime":          str(row.get("regime") or ""),
                "symbols_scanned": int(row.get("symbols_scanned") or 0),
                "trades_today":    int(row.get("trades_today") or 0),
                "cycle_count":     int(row.get("cycle_count") or 0),
                "last_run":        lr_ts[:19],
                "heartbeat":       hb_ts[:19],
                "age":             _age_str(age_s),
                "alive":           "🟢" if alive_flag else "🔴",
            })
        import pandas as _pd
        st.dataframe(_pd.DataFrame(display_rows), use_container_width=True, hide_index=True)

    st.divider()

    # ── ROW 5: Diagnostic checks ─────────────────────────────────────────────
    st.subheader("Diagnostic Checklist")

    checks = [
        ("Runner alive",           alive,                              "Runner heartbeat within 2h"),
        ("Runner RUNNING",         h["phase1_status"] == "RUNNING",    "checkpoint.json shows RUNNING"),
        ("Last cycle < 2h old",    (last_cy_age or 9999) < 7200,       "Engine executed within expected window"),
        ("Heartbeat < 65min",      (last_hb_age or 9999) < 3900,       "Mid-cycle heartbeat recently received"),
        ("Log files fresh",        (h["log_update_age_s"] or 9999) < 3600, "Log file updated within 1h"),
        ("DB write latency < 100ms",(h["db_write_latency_ms"] or 9999) < 100, "SQLite write is fast"),
    ]

    all_ok = True
    for label, ok, detail in checks:
        icon = "✅" if ok else "⚠️"
        if not ok:
            all_ok = False
        st.markdown(f"{icon} **{label}** — _{detail}_")

    if all_ok:
        st.success("All health checks passed — system is operating normally.")
    else:
        st.warning("One or more health checks flagged — review items above.")

    st.caption(f"Panel rendered at {now_str}")
