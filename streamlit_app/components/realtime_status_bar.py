"""
Real-Time Status Bar Component — Displays sync status at top of dashboard.

Shows:
  - Overall system status (LIVE, DEGRADED, STALE, DISCONNECTED)
  - Per-market status indicators
  - Last heartbeat timestamps
  - Stale data warnings
"""

from __future__ import annotations

import streamlit as st

from monitoring.streamlit_sync_bridge import get_all_sync_statuses


def render() -> None:
    """Render the real-time status bar."""
    sync_statuses = get_all_sync_statuses()
    
    # Compute overall status
    if any(s.is_stale for s in sync_statuses.values()):
        overall_emoji = "🔴"
        overall_text = "DISCONNECTED"
        overall_color = "red"
    elif any(s.is_degraded for s in sync_statuses.values()):
        overall_emoji = "🟡"
        overall_text = "DEGRADED"
        overall_color = "orange"
    elif all(s.is_connected for s in sync_statuses.values()):
        overall_emoji = "🟢"
        overall_text = "LIVE"
        overall_color = "green"
    else:
        overall_emoji = "⚪"
        overall_text = "UNKNOWN"
        overall_color = "gray"
    
    # Render status bar
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    
    with col1:
        st.markdown(f"### {overall_emoji} System: **{overall_text}**")
    
    with col2:
        us_status = sync_statuses.get("us")
        if us_status:
            st.markdown(f"{us_status.status_emoji} **US**: {us_status.status_text}")
            if us_status.heartbeat_age_seconds is not None:
                st.caption(f"Heartbeat: {us_status.heartbeat_age_seconds:.0f}s ago")
        else:
            st.markdown("⚪ **US**: NO DATA")
    
    with col3:
        india_status = sync_statuses.get("india")
        if india_status:
            st.markdown(f"{india_status.status_emoji} **India**: {india_status.status_text}")
            if india_status.heartbeat_age_seconds is not None:
                st.caption(f"Heartbeat: {india_status.heartbeat_age_seconds:.0f}s ago")
        else:
            st.markdown("⚪ **India**: NO DATA")
    
    with col4:
        crypto_status = sync_statuses.get("crypto")
        if crypto_status:
            st.markdown(f"{crypto_status.status_emoji} **Crypto**: {crypto_status.status_text}")
            if crypto_status.heartbeat_age_seconds is not None:
                st.caption(f"Heartbeat: {crypto_status.heartbeat_age_seconds:.0f}s ago")
        else:
            st.markdown("⚪ **Crypto**: NO DATA")
    
    # Show warnings if any
    all_warnings = []
    for market, status in sync_statuses.items():
        if status.warnings:
            all_warnings.extend([f"[{market.upper()}] {w}" for w in status.warnings])
    
    if all_warnings:
        st.divider()
        st.warning("⚠️ **Sync Warnings:**\n\n" + "\n\n".join(f"- {w}" for w in all_warnings))
    
    st.divider()
