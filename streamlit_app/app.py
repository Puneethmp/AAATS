"""
AAATS Trading Dashboard — Main Streamlit Entry Point.

Run with:  streamlit run streamlit_app/app.py
"""

import streamlit as st

st.set_page_config(
    page_title="AAATS Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar navigation ─────────────────────────────────────────────────────────
with st.sidebar:
    st.title("AAATS")
    st.caption("Autonomous Algorithmic Trading")
    st.divider()

    page = st.radio(
        "Navigation",
        [
            "📊 Dashboard",
            "📈 Performance Analytics",
            "💡 Investment Guide",
            "🎯 Strategy Details",
            "⚠️ Risk & Alerts",
            "⚙️ Settings & Account",
            "📄 Reports & Export",
        ],
        label_visibility="collapsed",
    )

    st.divider()

    # System status
    st.markdown("**System Status**")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("🟢 Alpaca")
        st.markdown("🟢 Angel One")
    with col2:
        st.markdown("🟢 DB")
        st.markdown("🟡 Crypto")

    st.divider()
    if st.button("🔴 HALT ALL MARKETS", type="primary", use_container_width=True):
        st.error("⚠️ Manual halt initiated. All markets paused.")
        st.session_state["manual_halt"] = True

    st.caption("Paper Mode 🟡")


# ── Page routing ───────────────────────────────────────────────────────────────
if page == "📊 Dashboard":
    from streamlit_app.pages import page_dashboard
    page_dashboard.render()

elif page == "📈 Performance Analytics":
    from streamlit_app.pages import page_analytics
    page_analytics.render()

elif page == "💡 Investment Guide":
    from streamlit_app.pages import page_investment_guide
    page_investment_guide.render()

elif page == "🎯 Strategy Details":
    from streamlit_app.pages import page_strategy
    page_strategy.render()

elif page == "⚠️ Risk & Alerts":
    from streamlit_app.pages import page_risk
    page_risk.render()

elif page == "⚙️ Settings & Account":
    from streamlit_app.pages import page_settings
    page_settings.render()

elif page == "📄 Reports & Export":
    from streamlit_app.pages import page_reports
    page_reports.render()
