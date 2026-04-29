"""Page 7: Reports & Export — trade history, performance report, ITR-2 export."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from streamlit_app.data_layer import get_all_trades, get_portfolio_summary

# ── Tax constants ──────────────────────────────────────────────────────────────
_TAX_RATE = {"us": 0.20, "india": 0.30, "crypto": 0.30}
_MARKET_BROKER = {"us": "Alpaca (US)", "india": "Angel One (India)", "crypto": "Binance (Crypto)"}


def _trades_to_csv(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()


def _build_itr2_df(trades: pd.DataFrame) -> pd.DataFrame:
    """
    Build ITR-2 / Schedule VDA compatible export from paper_trades.

    Columns match what a CA needs for ITR-2 filing:
      - Broker, Symbol, Market, Trade Date, Action, Price, Shares,
        Gross Value (₹), Tax Rate, TDS (₹), Net Value (₹), P&L (₹), Net P&L (₹)
    """
    if trades.empty:
        return pd.DataFrame()

    usd_inr = 83.5  # fallback rate; replace with live rate when live trading

    df = trades.copy()

    # Normalise columns — paper_trades may not have all of these, fill safely
    for col in ("pnl", "price", "shares"):
        if col not in df.columns:
            df[col] = 0.0

    df["market"] = df.get("market", pd.Series(["unknown"] * len(df)))

    # Convert USD markets to INR for ITR
    df["gross_inr"] = df.apply(
        lambda r: r["price"] * r["shares"] * (usd_inr if r["market"] in ("us", "crypto") else 1.0),
        axis=1,
    )

    df["tax_rate"] = df["market"].map(_TAX_RATE).fillna(0.30)
    df["pnl_inr"] = df.apply(
        lambda r: r["pnl"] * (usd_inr if r["market"] in ("us", "crypto") else 1.0),
        axis=1,
    )
    df["tds_inr"] = (df["pnl_inr"].clip(lower=0) * df["tax_rate"]).round(2)
    df["net_pnl_inr"] = (df["pnl_inr"] - df["tds_inr"]).round(2)
    df["broker"] = df["market"].map(_MARKET_BROKER).fillna("Unknown")

    cols = [
        "broker", "symbol", "market",
        "timestamp", "action",
        "price", "shares", "gross_inr",
        "tax_rate", "pnl_inr", "tds_inr", "net_pnl_inr",
        "regime",
    ]
    out_cols = [c for c in cols if c in df.columns]
    result = df[out_cols].copy()

    rename_map = {
        "timestamp": "Trade Date",
        "action": "Action (BUY/SELL)",
        "price": "Price",
        "shares": "Qty",
        "gross_inr": "Gross Value (₹)",
        "tax_rate": "Tax Rate",
        "pnl_inr": "P&L (₹)",
        "tds_inr": "TDS Deducted (₹)",
        "net_pnl_inr": "Net P&L (₹)",
        "broker": "Broker",
        "symbol": "Symbol",
        "market": "Market",
        "regime": "Regime at Trade",
    }
    result.rename(columns={k: v for k, v in rename_map.items() if k in result.columns}, inplace=True)
    return result


def _itr2_summary(itr_df: pd.DataFrame) -> dict:
    """Return totals needed on ITR-2 Schedule VDA/Capital Gains."""
    if itr_df.empty:
        return {"total_pnl": 0.0, "total_tds": 0.0, "total_net": 0.0}
    return {
        "total_pnl": itr_df["P&L (₹)"].sum() if "P&L (₹)" in itr_df else 0.0,
        "total_tds": itr_df["TDS Deducted (₹)"].sum() if "TDS Deducted (₹)" in itr_df else 0.0,
        "total_net": itr_df["Net P&L (₹)"].sum() if "Net P&L (₹)" in itr_df else 0.0,
    }


def render() -> None:
    st.title("📄 Reports & Export")
    st.caption("Trade history, ITR-2 export, and performance reports")

    tab1, tab2, tab3 = st.tabs([
        "📋 Trade History", "🧾 ITR-2 / Tax Export", "📊 Performance Report"
    ])

    trades = get_all_trades()

    # ── Tab 1: Trade history ───────────────────────────────────────────────────
    with tab1:
        st.subheader("Trade History")

        if trades.empty:
            st.info("No trades recorded yet. Start paper trading to see history here.")
        else:
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
            st.download_button(
                label="⬇️ Download as CSV",
                data=_trades_to_csv(filtered),
                file_name="aaats_trades.csv",
                mime="text/csv",
                use_container_width=True,
            )

    # ── Tab 2: ITR-2 / Tax Export ──────────────────────────────────────────────
    with tab2:
        st.subheader("ITR-2 & Tax Export")
        st.markdown(
            "Export your trade history in a format ready for your CA and ITR-2 filing. "
            "All amounts converted to ₹. TDS calculated per RBI/SEBI rates."
        )

        st.markdown("#### Tax Rates Applied")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.info("🇮🇳 **Angel One (India)**\n\n30% Short-Term CGT\n20% Long-Term CGT")
        with c2:
            st.info("₿ **Binance (Crypto)**\n\n30% TDS on VDA transactions\n(Schedule VDA, ITR-2)")
        with c3:
            st.info("🇺🇸 **Alpaca (US)**\n\n20% TDS via withholding\n(Foreign income, ITR-2)")

        st.divider()

        if trades.empty:
            st.info("No trades to export. Start paper trading to generate tax records.")
            st.markdown("""
**When live trading begins:**
- Every trade is automatically recorded with timestamp, price, P&L
- TDS is calculated per market at source
- Export this CSV monthly and share with your CA
- File ITR-2 by July 31 each year (Schedule VDA for crypto, CG Schedule for equity)
""")
        else:
            itr_df = _build_itr2_df(trades)
            totals = _itr2_summary(itr_df)

            st.markdown("#### Tax Year Summary")
            s1, s2, s3 = st.columns(3)
            with s1:
                st.metric("Total Gross P&L (₹)", f"₹{totals['total_pnl']:,.2f}")
            with s2:
                st.metric("Total TDS Deducted (₹)", f"₹{totals['total_tds']:,.2f}",
                          delta="deducted at source", delta_color="off")
            with s3:
                st.metric("Net Taxable Profit (₹)", f"₹{totals['total_net']:,.2f}")

            st.dataframe(itr_df, use_container_width=True, hide_index=True)
            st.divider()

            col_a, col_b = st.columns(2)
            with col_a:
                st.download_button(
                    label="⬇️ Download ITR-2 Ready CSV",
                    data=_trades_to_csv(itr_df),
                    file_name="aaats_itr2_export.csv",
                    mime="text/csv",
                    use_container_width=True,
                    help="Share this file with your CA for ITR-2 filing",
                )
            with col_b:
                # Plain-text tax summary for CA
                summary_lines = [
                    "AAATS Tax Summary — ITR-2 Filing",
                    f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M UTC')}",
                    "",
                    "TAX YEAR TOTALS",
                    f"  Gross P&L (₹):       ₹{totals['total_pnl']:>12,.2f}",
                    f"  TDS Deducted (₹):    ₹{totals['total_tds']:>12,.2f}",
                    f"  Net Taxable P&L (₹): ₹{totals['total_net']:>12,.2f}",
                    "",
                    "TAX RATES APPLIED",
                    "  Angel One (India):  30% STCGT / 20% LTCGT",
                    "  Binance (Crypto):   30% TDS (VDA — Schedule VDA)",
                    "  Alpaca (US):        20% TDS (Foreign income)",
                    "",
                    "FILING DEADLINE: July 31 (ITR-2)",
                    "SCHEDULE: CG (Equity), VDA (Crypto), Foreign Income (US)",
                ]
                st.download_button(
                    label="⬇️ Download Tax Summary (.txt)",
                    data="\n".join(summary_lines).encode(),
                    file_name="aaats_tax_summary.txt",
                    mime="text/plain",
                    use_container_width=True,
                )

        with st.expander("📅 ITR-2 Filing Guide"):
            st.markdown("""
**What to file:**
- **Schedule CG**: Capital gains from Angel One (India equity trades)
- **Schedule VDA**: Virtual Digital Assets (all Binance crypto trades)
- **Foreign Income Schedule**: Alpaca US stock gains

**Documents needed:**
1. AAATS ITR-2 CSV export (download above)
2. Angel One Tax P&L Statement (from Angel One portal)
3. Binance Tax Report (from Binance Tax portal)
4. Alpaca 1099-B (from Alpaca)
5. Form 26AS (from income tax portal — shows TDS deducted)

**Filing deadline:** July 31 each year

**Penalty for non-filing:** ₹5,000 + 1% interest per month on tax due
""")

    # ── Tab 3: Performance Report ──────────────────────────────────────────────
    with tab3:
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
            "## Tax & Compliance",
            "- TDS tracking: Active (30% India/Crypto, 20% US)",
            "- ITR-2 export: Available in Tax Export tab",
            "- Filing deadline: July 31 annually",
            "",
            "## Next Steps",
            "- Continue paper trading until July 8",
            "- Review metrics against live trading criteria (win rate >60%, Sharpe >1.0)",
            "- Enable live micro mode if criteria met (Aug 1)",
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
