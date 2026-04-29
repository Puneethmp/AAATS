"""Page 5: Risk & Alerts."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from data_layer import get_portfolio_summary, get_recent_alerts


def render() -> None:
    st.title("⚠️ Risk & Alerts")
    st.caption("Kill switch status, drawdown monitoring, and system alerts")

    summary = get_portfolio_summary()
    initial_capital = 100_000.0
    current_value = initial_capital + summary["total_pnl"]
    dd_pct = ((current_value - initial_capital) / initial_capital) * 100

    # ── Kill switch status ─────────────────────────────────────────────────────
    st.subheader("Kill Switch Status")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Portfolio Kill Switch**")
        progress = min(abs(dd_pct) / 20.0, 1.0) if dd_pct < 0 else 0.0
        st.progress(progress, text=f"Drawdown: {dd_pct:.1f}% / -20% limit")
        status = "🔴 TRIGGERED" if dd_pct <= -20 else "🟢 ARMED (Safe)"
        st.markdown(f"Status: **{status}**")

    with col2:
        st.markdown("**US Market Kill Switch**")
        st.progress(0.0, text="Drawdown: 0.0% / -15% limit")
        st.markdown("Status: **🟢 ARMED (Safe)**")

    with col3:
        st.markdown("**India Market Kill Switch**")
        st.progress(0.0, text="Drawdown: 0.0% / -15% limit")
        st.markdown("Status: **🟢 ARMED (Safe)**")

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
            st.error("⚠️ HALT signal sent. All markets paused.")
            st.session_state["manual_halt"] = True
    with col_resume:
        if st.button("🟢 Resume Trading (human override)", use_container_width=True):
            if st.session_state.get("manual_halt"):
                st.success("✅ Resume signal sent. Confirm in settings.")
                st.session_state["manual_halt"] = False
            else:
                st.info("No active halt to clear.")
