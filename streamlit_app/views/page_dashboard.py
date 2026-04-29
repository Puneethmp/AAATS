"""Page 1: Real-Time Dashboard."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_layer import (
    get_equity_curve,
    get_open_positions,
    get_portfolio_summary,
    get_all_trades,
)


def render() -> None:
    st.title("📊 Dashboard")
    st.caption("Real-time portfolio overview — refreshes every 30 seconds")

    summary = get_portfolio_summary()
    initial_capital = 100_000.0

    # ── Hero metrics ──────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    pnl = summary["total_pnl"]
    pnl_pct = (pnl / initial_capital) * 100

    with col1:
        st.metric(
            "Total P&L",
            f"${pnl:+,.2f}",
            delta=f"{pnl_pct:+.2f}%",
            delta_color="normal",
        )
    with col2:
        balance = initial_capital + pnl
        st.metric("Account Balance", f"${balance:,.2f}", delta=f"of ${initial_capital:,.0f}")
    with col3:
        st.metric("Win Rate", f"{summary['win_rate']:.0%}", delta=f"{summary['wins']}W / {summary['losses']}L")
    with col4:
        st.metric("Total Trades", str(summary["total_trades"]))

    st.divider()

    # ── Equity curve ──────────────────────────────────────────────────────────
    st.subheader("Equity Curve")
    equity_df = get_equity_curve(initial_capital=initial_capital)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=equity_df["date"],
        y=equity_df["equity"],
        mode="lines",
        name="Portfolio Value",
        line=dict(color="#00d4aa", width=2),
        fill="tozeroy",
        fillcolor="rgba(0, 212, 170, 0.1)",
        hovertemplate="<b>%{x}</b><br>$%{y:,.2f}<extra></extra>",
    ))
    fig.add_hline(y=initial_capital, line_dash="dash", line_color="gray",
                  annotation_text=f"Initial ${initial_capital:,.0f}")
    fig.update_layout(
        height=300,
        margin=dict(l=0, r=0, t=20, b=0),
        xaxis_title="",
        yaxis_title="Portfolio Value ($)",
        hovermode="x unified",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Market regimes ────────────────────────────────────────────────────────
    st.subheader("Market Regimes")
    r1, r2, r3 = st.columns(3)
    with r1:
        st.info("🟢 **US Market**\nBULL_TREND\nEMA50 > EMA200")
    with r2:
        st.warning("🟡 **India Market**\nRANGE_BOUND\nADX < 20")
    with r3:
        st.info("🔵 **Crypto Market**\nRANGE_BOUND\nGrid active")

    st.divider()

    # ── Active positions ──────────────────────────────────────────────────────
    st.subheader("Active Positions")
    positions = get_open_positions()
    if positions.empty:
        st.info("No open positions. System is in paper mode — monitoring markets.")
    else:
        st.dataframe(
            positions,
            use_container_width=True,
            hide_index=True,
        )

    # ── Recent trades ─────────────────────────────────────────────────────────
    st.subheader("Recent Trades (Last 10)")
    trades = get_all_trades()
    if trades.empty:
        st.info("No trades recorded yet. Paper trading will start automatically when signals fire.")
    else:
        display_cols = ["timestamp", "market", "symbol", "action", "shares", "price", "pnl", "signal"]
        available = [c for c in display_cols if c in trades.columns]
        st.dataframe(trades[available].head(10), use_container_width=True, hide_index=True)
