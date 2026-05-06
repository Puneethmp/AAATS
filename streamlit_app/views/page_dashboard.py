"""Page 1: Real-Time Dashboard."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_layer import (
    get_equity_curve,
    get_open_positions,
    get_portfolio_summary,
    get_all_trades,
    get_engine_status,
    get_health_metrics,
)

_STATUS_ICON = {
    "OK":            "🟢",
    "RUNNING":       "🔄",
    "MARKET_CLOSED": "🌙",
    "IDLE":          "⚪",
    "ERROR":         "🔴",
}


def _age_label(last_run_iso: str) -> str:
    """Human-readable time since last cycle."""
    try:
        dt = datetime.fromisoformat(last_run_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        mins = int(delta.total_seconds() // 60)
        if mins < 1:
            return "just now"
        if mins < 60:
            return f"{mins}m ago"
        return f"{mins // 60}h {mins % 60}m ago"
    except Exception:
        return "unknown"


def render() -> None:
    st.title("📊 Dashboard")

    # Auto-refresh every 30 s
    st.html('<meta http-equiv="refresh" content="30">')

    # ── Stale runner banner ───────────────────────────────────────────────────
    try:
        _h = get_health_metrics()
        if not _h["runner_alive"]:
            st.error(
                "**Runner appears dead** — no heartbeat in >2h.  "
                "Restart: `python scripts/phase1_runner.py`"
            )
        elif _h.get("last_cycle_age_s") and _h["last_cycle_age_s"] > 3900:
            st.warning(
                f"Runner last reported **{_h['last_cycle_age_s'] // 60}m ago** — "
                "may be sleeping or processing a slow cycle."
            )
    except Exception:
        pass

    summary = get_portfolio_summary()
    initial_capital = 100_000.0

    # ── Hero metrics ──────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    pnl = summary["total_pnl"]
    pnl_pct = (pnl / initial_capital) * 100
    with col1:
        st.metric("Total P&L", f"${pnl:+,.2f}", delta=f"{pnl_pct:+.2f}%")
    with col2:
        st.metric("Account Balance", f"${initial_capital + pnl:,.2f}",
                  delta=f"of ${initial_capital:,.0f}")
    with col3:
        st.metric("Win Rate", f"{summary['win_rate']:.0%}",
                  delta=f"{summary['wins']}W / {summary['losses']}L")
    with col4:
        st.metric("Total Trades", str(summary["total_trades"]))

    st.divider()

    # ── Live bot status ───────────────────────────────────────────────────────
    st.subheader("🤖 Bot Status — Live Engine")

    status_df = get_engine_status()

    if status_df.empty:
        st.warning(
            "No engine status yet. Start the bot:  "
            "`python main.py --mode paper --market all`"
        )
    else:
        cols = st.columns(len(status_df))
        for col, (_, row) in zip(cols, status_df.iterrows()):
            icon = _STATUS_ICON.get(row.get("status", "IDLE"), "⚪")
            with col:
                st.markdown(f"### {icon} {row['market'].upper()}")
                st.markdown(f"**Regime:** `{row.get('regime') or 'N/A'}`")
                st.markdown(f"**Symbols scanned:** {row.get('symbols_scanned', 0)}")
                st.markdown(f"**Trades today:** {row.get('trades_today', 0)}")
                st.markdown(f"**Last run:** {_age_label(row.get('last_run', ''))}")
                if row.get("error"):
                    st.error(row["error"][:80])

    st.divider()

    # ── Equity curve ──────────────────────────────────────────────────────────
    st.subheader("Equity Curve")
    equity_df = get_equity_curve(initial_capital=initial_capital)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=equity_df["date"], y=equity_df["equity"],
        mode="lines", name="Portfolio Value",
        line=dict(color="#00d4aa", width=2),
        fill="tozeroy", fillcolor="rgba(0,212,170,0.1)",
        hovertemplate="<b>%{x}</b><br>$%{y:,.2f}<extra></extra>",
    ))
    fig.add_hline(y=initial_capital, line_dash="dash", line_color="gray",
                  annotation_text=f"Initial ${initial_capital:,.0f}")
    fig.update_layout(height=280, margin=dict(l=0, r=0, t=20, b=0),
                      xaxis_title="", yaxis_title="Portfolio Value ($)",
                      hovermode="x unified", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Active positions ──────────────────────────────────────────────────────
    st.subheader("Active Positions")
    positions = get_open_positions()
    if positions.empty:
        st.info("No open positions — bot is monitoring markets.")
    else:
        st.dataframe(positions, use_container_width=True, hide_index=True)

    # ── Recent trades ─────────────────────────────────────────────────────────
    st.subheader("Recent Trades (Last 20)")
    trades = get_all_trades()
    if trades.empty:
        st.info("No trades yet. Start the bot to begin paper trading.")
    else:
        display_cols = ["timestamp", "market", "symbol", "action", "shares",
                        "price", "pnl", "signal", "regime"]
        available = [c for c in display_cols if c in trades.columns]
        st.dataframe(
            trades[available].head(20),
            use_container_width=True,
            hide_index=True,
        )

    st.caption(f"Last page load: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} — auto-refreshes every 30s")
