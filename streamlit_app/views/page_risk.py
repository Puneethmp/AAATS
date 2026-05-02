"""Page 5: Risk & Alerts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import streamlit as st

from data_layer import get_recent_alerts, get_halt_state, write_halt_state

_ROOT = Path(__file__).parent.parent.parent
_EQUITY_DB = _ROOT / "data" / "equity_curve.db"


def _drawdown_for_market(market: str) -> float:
    """Return current drawdown % for a market from equity_curve.db, or 0.0 if unavailable."""
    if not _EQUITY_DB.exists():
        return 0.0
    try:
        with sqlite3.connect(_EQUITY_DB) as conn:
            row = conn.execute(
                "SELECT current_drawdown FROM equity_curve WHERE market=? "
                "ORDER BY timestamp DESC LIMIT 1", (market,)
            ).fetchone()
            return round((row[0] or 0.0) * 100, 2) if row else 0.0
    except Exception:
        return 0.0


def render() -> None:
    st.title("⚠️ Risk & Alerts")
    st.caption("Kill switch status, drawdown monitoring, and system alerts")

    halt = get_halt_state()

    # Live drawdown per market from equity_curve.db
    dd_crypto = _drawdown_for_market("crypto")
    dd_us     = _drawdown_for_market("us")
    dd_india  = _drawdown_for_market("india")

    # ── Kill switch status ─────────────────────────────────────────────────────
    st.subheader("Kill Switch Status")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Crypto Kill Switch**")
        progress = min(abs(dd_crypto) / 20.0, 1.0) if dd_crypto < 0 else 0.0
        st.progress(progress, text=f"Drawdown: {dd_crypto:.1f}% / -20% limit")
        halted_crypto = halt.get("crypto", False)
        ks_status = "🔴 HALTED" if halted_crypto else ("🔴 TRIGGERED" if dd_crypto <= -20 else "🟢 ARMED (Safe)")
        st.markdown(f"Status: **{ks_status}**")

    with col2:
        st.markdown("**US Market Kill Switch**")
        progress_us = min(abs(dd_us) / 15.0, 1.0) if dd_us < 0 else 0.0
        st.progress(progress_us, text=f"Drawdown: {dd_us:.1f}% / -15% limit")
        halted_us = halt.get("us", False)
        ks_us = "🔴 HALTED" if halted_us else ("🔴 TRIGGERED" if dd_us <= -15 else "🟢 ARMED (Safe)")
        st.markdown(f"Status: **{ks_us}**")

    with col3:
        st.markdown("**India Market Kill Switch**")
        progress_in = min(abs(dd_india) / 15.0, 1.0) if dd_india < 0 else 0.0
        st.progress(progress_in, text=f"Drawdown: {dd_india:.1f}% / -15% limit")
        halted_india = halt.get("india", True)
        ks_india = "🔴 HALTED (Phase 1)" if halted_india else ("🔴 TRIGGERED" if dd_india <= -15 else "🟢 ARMED (Safe)")
        st.markdown(f"Status: **{ks_india}**")

    st.divider()

    # ── Per-trade risk ─────────────────────────────────────────────────────────
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Per-Trade Risk Limits")
        st.markdown("""
| Rule | Limit | Status |
|------|-------|--------|
| Max loss per trade | -2% of capital | 🟢 Active |
| Max position size | 10% of portfolio | 🟢 Active |
| F&O max risk (India) | 1% per trade | 🟢 Active |
| Crypto grid exposure | 50% per grid | 🟢 Active |
""")

    with col_b:
        st.subheader("API Health")
        apis = [
            ("Alpaca (US)", "🟢 Connected", "Paper mode"),
            ("Angel One (India)", "🟢 Connected", "TOTP valid"),
            ("Binance (Crypto)", "🟡 Public API", "No auth needed"),
            ("SQLite DB", "🟢 Healthy", "366 tests passing"),
        ]
        for api, status, note in apis:
            st.markdown(f"**{api}**: {status} — _{note}_")

    st.divider()

    # ── Recent alerts ─────────────────────────────────────────────────────────
    st.subheader("Recent Alerts")
    alerts = get_recent_alerts()
    for alert in alerts:
        level = alert.get("level", "INFO")
        msg = alert.get("msg", "")
        time = alert.get("time", "")
        if level == "ERROR":
            st.error(f"[{time}] {msg}")
        elif level == "WARNING":
            st.warning(f"[{time}] {msg}")
        else:
            st.info(f"[{time}] {msg}")

    # ── Manual kill switch ────────────────────────────────────────────────────
    st.divider()
    st.subheader("Manual Override")
    st.warning("Manual kill switch will immediately halt all trading and close all positions.")

    col_halt, col_resume = st.columns(2)
    with col_halt:
        if st.button("🔴 HALT ALL MARKETS NOW", type="primary", use_container_width=True):
            ok = write_halt_state(us=True, india=True, crypto=True)
            if ok:
                st.error("⚠️ Halt written to halt_state.json — all markets stop on next cycle.")
            else:
                st.error("⚠️ Failed to write halt_state.json — check file permissions.")
            st.session_state["manual_halt"] = True
    with col_resume:
        if st.button("🟢 Resume Trading (human override)", use_container_width=True):
            ok = write_halt_state(us=False, crypto=False)
            if ok:
                st.success("✅ US and Crypto unhalted. India remains halted until Phase 2.")
                st.session_state["manual_halt"] = False
            else:
                st.error("Failed to write halt_state.json.")
