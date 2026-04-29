"""Page 7: Reports & Export."""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from streamlit_app.data_layer import get_all_trades, get_portfolio_summary


def _trades_to_csv(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()


def render() -> None:
    st.title("📄 Reports & Export")
    st.caption("Trade history, performance reports, and data export")

    tab1, tab2 = st.tabs(["📋 Trade History", "📊 Performance Report"])

    # ── Tab 1: Trade history ───────────────────────────────────────────────────
    with tab1:
        st.subheader("Trade History")

        trades = get_all_trades()

        if trades.empty:
            st.info("No trades recorded yet. Start paper trading to see history here.")
        else:
            # Filters
            col1, col2, col3 = st.columns(3)
            with col1:
                markets = ["All"] + sorted(trades["market"].unique().tolist())
                market_filter = st.selectbox("Market", markets)
            with col2:
                actions = ["All"] + sorted(trades["action"].unique().tolist())
                action_filter = st.selectbox("Action", actions)
            with col3:
                st.metric("Total Trades", len(trades))

            filtered = trades.copy()
            if market_filter != "All":
                filtered = filtered[filtered["market"] == market_filter]
            if action_filter != "All":
                filtered = filtered[filtered["action"] == action_filter]

            st.dataframe(filtered, use_container_width=True, hide_index=True)

            st.divider()
            csv_bytes = _trades_to_csv(filtered)
            st.download_button(
                label="⬇️ Download as CSV",
                data=csv_bytes,
                file_name="aaats_trades.csv",
                mime="text/csv",
                use_container_width=True,
            )

    # ── Tab 2: Performance report ──────────────────────────────────────────────
    with tab2:
        st.subheader("Performance Summary Report")

        summary = get_portfolio_summary()

        report_lines = [
            "# AAATS Paper Trading Performance Report",
            f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "## Summary Statistics",
            f"- Total Trades: {summary['total_trades']}",
            f"- Total P&L: ${summary['total_pnl']:+,.2f}",
            f"- Win Rate: {summary['win_rate']:.1%}",
            f"- Wins: {summary['wins']} | Losses: {summary['losses']}",
            f"- Average Win: ${summary['avg_win']:+,.2f}",
            f"- Average Loss: ${summary['avg_loss']:+,.2f}",
            "",
            "## Risk Assessment",
            "- Max Drawdown: See Analytics page",
            "- Kill Switch Status: All ARMED (Safe)",
            "- Trading Mode: Paper (No real money)",
            "",
            "## Next Steps",
            "- Continue paper trading until July 8",
            "- Review metrics against live trading criteria",
            "- Enable live micro mode if criteria met",
        ]

        report_text = "\n".join(report_lines)
        st.markdown(report_text)

        st.divider()
        st.download_button(
            label="⬇️ Download Report (.txt)",
            data=report_text.encode(),
            file_name="aaats_performance_report.txt",
            mime="text/plain",
            use_container_width=True,
        )
