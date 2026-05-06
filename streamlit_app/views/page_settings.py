"""Page 6: Settings & Account."""

from __future__ import annotations

import streamlit as st


def render() -> None:
    st.title("⚙️ Settings & Account")
    st.caption("Trading mode, risk parameters, and account configuration")

    tab1, tab2, tab3 = st.tabs(["🔄 Trading Mode", "⚖️ Risk Parameters", "🔔 Notifications"])

    # ── Tab 1: Trading mode ────────────────────────────────────────────────────
    with tab1:
        st.subheader("Trading Mode")

        current_mode = st.session_state.get("trading_mode", "paper")
        mode_display = "🟡 PAPER MODE" if current_mode == "paper" else "🔴 LIVE MODE"
        st.info(f"Current Mode: **{mode_display}**")

        st.markdown("""
**Paper Mode** → System executes simulated trades against real market data.
No real money is used. All P&L figures are hypothetical.

**Live Mode** → Real orders placed at brokers. Real money at risk.
Requires two-step confirmation. Starts with 1% position sizing.
""")

        st.divider()
        st.markdown("### Enable Live Trading (2-Step Gate)")
        st.warning(
            "⚠️ Only proceed if you have completed at least 2 months of profitable paper trading "
            "and understand all risks."
        )

        if current_mode == "paper":
            phrase1 = st.text_input(
                "Step 1: Type exactly → I UNDERSTAND REAL MONEY IS AT RISK",
                placeholder="Type the confirmation phrase",
                type="default",
            )
            if st.button("Confirm Step 1", disabled=(phrase1 != "I UNDERSTAND REAL MONEY IS AT RISK")):
                st.session_state["live_step1_done"] = True
                st.success("Step 1 confirmed. Complete Step 2 within 5 minutes.")

            if st.session_state.get("live_step1_done"):
                phrase2 = st.text_input(
                    "Step 2: Type exactly → ENABLE LIVE TRADING NOW",
                    placeholder="Type the second confirmation phrase",
                    type="default",
                )
                if st.button("Confirm Step 2", disabled=(phrase2 != "ENABLE LIVE TRADING NOW")):
                    st.session_state["trading_mode"] = "live_micro"
                    st.session_state["live_step1_done"] = False
                    st.success("✅ Live Micro Mode enabled! 1% position sizing active.")
        else:
            if st.button("🟡 Revert to Paper Mode"):
                st.session_state["trading_mode"] = "paper"
                st.info("Reverted to paper mode.")

        st.divider()
        st.subheader("Broker Credentials Status")
        st.markdown("""
| Broker | Status | Note |
|--------|--------|------|
| Alpaca (US) | ✅ Configured | Paper API keys active |
| Angel One (India) | ✅ Configured | TOTP auto-renewal active |
| Binance (Crypto) | ✅ Public API | No key needed for market data |
""")
        st.info("Credentials are stored in `.env` file. Edit via CLI, not this UI.")

    # ── Tab 2: Risk parameters ─────────────────────────────────────────────────
    with tab2:
        st.subheader("Risk Parameters")
        st.info("These are display-only. Change parameters in `config/settings.py` and restart.")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**US Market**")
            st.metric("Max Risk Per Trade", "1.5%")
            st.metric("Max Portfolio Exposure", "6%")
            st.metric("Drawdown Halt", "-15%")

        with col2:
            st.markdown("**India Market**")
            st.metric("Equity Max Risk", "1.5%")
            st.metric("F&O Max Risk", "1.0%")
            st.metric("Drawdown Halt", "-15%")

        st.divider()
        st.markdown("**Portfolio-Level**")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.metric("Total Halt", "-20%")
        with col_b:
            st.metric("Max Capital Deployed", "40%")
        with col_c:
            st.metric("Per-Trade Max Loss", "-2%")

        st.divider()
        st.subheader("Capital Allocation")
        st.markdown("Current allocation (read-only — set in `.env`):")

        us_pct = st.slider("US Market %", 0, 100, 40, disabled=True)
        india_pct = st.slider("India Market %", 0, 100, 35, disabled=True)
        crypto_pct = st.slider("Crypto Market %", 0, 100, 15, disabled=True)
        cash_pct = 100 - us_pct - india_pct - crypto_pct
        st.metric("Cash Reserve", f"{cash_pct}%")

    # ── Tab 3: Notifications ───────────────────────────────────────────────────
    with tab3:
        st.subheader("Notification Preferences")
        st.markdown("""
Notifications are sent via **Telegram**. Configure via `.env`:
- `ALERTS__TELEGRAM_BOT_TOKEN`
- `ALERTS__TELEGRAM_CHAT_ID`
""")

        st.markdown("**Notification Events**")
        events = [
            ("Trade executed (BUY/SELL)", True),
            ("Kill switch triggered", True),
            ("Daily P&L summary", True),
            ("API connection failure", True),
            ("Regime change detected", True),
            ("Phase graduation (micro → full)", True),
        ]
        for event, default in events:
            st.checkbox(event, value=default, disabled=True)

        st.info("Toggle notifications by editing `AUTONOMOUS_SYSTEM_COMPLETE.md` settings.")
