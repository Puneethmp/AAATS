"""
AAATS Trading Dashboard — Main Streamlit Entry Point.

Run locally:  streamlit run streamlit_app/app.py
Streamlit Cloud: sets main file to streamlit_app/app.py
"""

import sys
from pathlib import Path

# Ensure streamlit_app/ and project root are in sys.path
_APP_DIR  = str(Path(__file__).parent)
_ROOT_DIR = str(Path(__file__).parent.parent)
for _p in (_APP_DIR, _ROOT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st
from data_layer import get_engine_status, write_halt_state

st.set_page_config(
    page_title="AAATS Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Auto-refresh every 10 seconds for real-time updates
if "refresh_count" not in st.session_state:
    st.session_state.refresh_count = 0

# Increment refresh counter
st.session_state.refresh_count += 1

# ── Sidebar navigation ─────────────────────────────────────────────────────────
with st.sidebar:
    st.title("AAATS")
    st.caption("Autonomous Algorithmic Trading")
    st.divider()

    page = st.radio(
        "Navigation",
        [
            "📊 Dashboard",
            "🏥 System Health",
            "� Production Readiness",
            "�🏛️ Institutional Testing",
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

    # Live system status from status.db
    st.markdown("**System Status**")
    _icons = {"OK": "🟢", "RUNNING": "🔄", "HALTED": "🔴", "ERROR": "🔴",
              "IDLE": "⚪", "MARKET_CLOSED": "🌙"}
    try:
        _sdf = get_engine_status()
        if not _sdf.empty:
            for _, _row in _sdf.iterrows():
                _ic = _icons.get(str(_row.get("status", "IDLE")), "⚪")
                st.markdown(f"{_ic} {str(_row['market']).title()}")
        else:
            st.markdown("⚪ No runners active")
    except Exception:
        st.markdown("⚪ Status unavailable")

    st.divider()
    if st.button("🔴 HALT ALL MARKETS", type="primary", use_container_width=True):
        ok = write_halt_state(us=True, india=True, crypto=True)
        if ok:
            st.error("⚠️ Halt written — all markets stop on next cycle.")
        else:
            st.error("⚠️ Could not write halt_state.json.")
        st.session_state["manual_halt"] = True

    st.caption("Paper Mode 🟡")


# ── Real-time status bar ───────────────────────────────────────────────────────
from components import realtime_status_bar
realtime_status_bar.render()

# ── Page routing ───────────────────────────────────────────────────────────────
if page == "📊 Dashboard":
    from views import page_dashboard
    page_dashboard.render()

elif page == "🏥 System Health":
    from views import page_health
    page_health.render()

elif page == "� Production Readiness":
    from views import page_production_readiness
    page_production_readiness.render()

elif page == "�🏛️ Institutional Testing":
    from views import page_institutional
    page_institutional.render()

elif page == "📈 Performance Analytics":
    from views import page_analytics
    page_analytics.render()

elif page == "💡 Investment Guide":
    from views import page_investment_guide
    page_investment_guide.render()

elif page == "🎯 Strategy Details":
    from views import page_strategy
    page_strategy.render()

elif page == "⚠️ Risk & Alerts":
    from views import page_risk
    page_risk.render()

elif page == "⚙️ Settings & Account":
    from views import page_settings
    page_settings.render()

elif page == "📄 Reports & Export":
    from views import page_reports
    page_reports.render()
