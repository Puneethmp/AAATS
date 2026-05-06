"""Page 2: Performance Analytics."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from data_layer import (
    get_equity_curve,
    get_monthly_returns,
    get_portfolio_summary,
    get_strategy_breakdown,
    get_all_trades,
)


def _sharpe(equity_df) -> float:
    if len(equity_df) < 2:
        return 0.0
    returns = equity_df["equity"].pct_change().dropna()
    if returns.std() == 0:
        return 0.0
    return float((returns.mean() / returns.std()) * (252 ** 0.5))


def render() -> None:
    st.title("📈 Performance Analytics")
    st.caption("Strategy effectiveness metrics for paper trading evaluation")

    summary = get_portfolio_summary()
    equity_df = get_equity_curve()

    # ── Summary cards ─────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Win Rate", f"{summary['win_rate']:.0%}",
                  delta=f"{summary['wins']}W / {summary['losses']}L")
    with col2:
        pf = abs(summary["avg_win"] / summary["avg_loss"]) if summary["avg_loss"] != 0 else 0
        st.metric("Profit Factor", f"{pf:.2f}")
    with col3:
        sharpe = _sharpe(equity_df)
        st.metric("Sharpe Ratio (ann.)", f"{sharpe:.2f}",
                  delta="Good" if sharpe > 1.0 else "Needs improvement")
    with col4:
        if len(equity_df) > 1:
            peak = equity_df["equity"].max()
            current = equity_df["equity"].iloc[-1]
            max_dd = ((current - peak) / peak) * 100
        else:
            max_dd = 0.0
        st.metric("Max Drawdown", f"{max_dd:.1f}%",
                  delta_color="inverse")

    st.divider()

    col_left, col_right = st.columns(2)

    # ── Monthly returns ───────────────────────────────────────────────────────
    with col_left:
        st.subheader("Monthly Returns")
        monthly = get_monthly_returns()
        if monthly.empty:
            st.info("No completed trades yet for monthly breakdown.")
        else:
            colors = ["green" if v >= 0 else "red" for v in monthly["pnl"]]
            fig = go.Figure(go.Bar(
                x=monthly["month"],
                y=monthly["pnl"],
                marker_color=colors,
                hovertemplate="<b>%{x}</b><br>P&L: $%{y:+,.2f}<extra></extra>",
            ))
            fig.update_layout(
                height=300, margin=dict(l=0, r=0, t=20, b=0),
                yaxis_title="P&L ($)", xaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)

    # ── Strategy breakdown ────────────────────────────────────────────────────
    with col_right:
        st.subheader("Strategy Performance")
        breakdown = get_strategy_breakdown()
        if breakdown.empty:
            st.info("No closed trades to analyze yet.")
        else:
            breakdown["win_rate"] = breakdown["win_rate"].apply(lambda x: f"{x:.0%}")
            breakdown["avg_pnl"] = breakdown["avg_pnl"].apply(lambda x: f"${x:+.2f}")
            breakdown["total_pnl"] = breakdown["total_pnl"].apply(lambda x: f"${x:+.2f}")
            st.dataframe(breakdown, use_container_width=True, hide_index=True)

    st.divider()

    # ── Drawdown chart ────────────────────────────────────────────────────────
    st.subheader("Portfolio Drawdown Over Time")
    if len(equity_df) > 1:
        eq = equity_df["equity"]
        running_max = eq.cummax()
        drawdown_pct = (eq - running_max) / running_max * 100

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=equity_df["date"],
            y=drawdown_pct,
            mode="lines",
            fill="tozeroy",
            fillcolor="rgba(255, 80, 80, 0.2)",
            line=dict(color="red", width=1),
            hovertemplate="<b>%{x}</b><br>Drawdown: %{y:.1f}%<extra></extra>",
        ))
        fig.add_hline(y=-20, line_dash="dash", line_color="darkred",
                      annotation_text="Hard Halt -20%")
        fig.update_layout(
            height=250, margin=dict(l=0, r=0, t=20, b=0),
            yaxis_title="Drawdown (%)", xaxis_title="",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Equity history will appear here once trading begins.")

    # ── Best/Worst trades ─────────────────────────────────────────────────────
    st.subheader("Notable Trades")
    trades = get_all_trades()
    sells = trades[trades["action"] == "SELL"] if not trades.empty else trades

    if sells.empty:
        st.info("No completed trades yet.")
    else:
        col_a, col_b = st.columns(2)
        with col_a:
            best = sells.loc[sells["pnl"].idxmax()]
            st.success(
                f"**Best Trade** 🏆\n\n"
                f"{best.get('symbol', 'N/A')} — "
                f"${float(best['pnl']):+.2f}"
            )
        with col_b:
            worst = sells.loc[sells["pnl"].idxmin()]
            st.error(
                f"**Worst Trade** 📉\n\n"
                f"{worst.get('symbol', 'N/A')} — "
                f"${float(worst['pnl']):+.2f}"
            )
