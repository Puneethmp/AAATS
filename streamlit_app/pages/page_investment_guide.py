"""Page 3: Investment Guide."""

from __future__ import annotations

import streamlit as st


def render() -> None:
    st.title("💡 Investment Guide")
    st.caption("Your complete roadmap from paper to live trading")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📐 Calculator", "📋 Procedure", "📊 Expected Returns", "❓ FAQ"
    ])

    # ── Tab 1: Calculator ──────────────────────────────────────────────────────
    with tab1:
        st.subheader("Position Size Calculator")
        st.markdown("Answer two questions to get your personalised trading parameters:")

        col1, col2 = st.columns(2)
        with col1:
            max_loss = st.slider(
                "How much can you afford to lose this month? ($)",
                min_value=100, max_value=10_000, value=500, step=100,
            )
        with col2:
            target_return_pct = st.slider(
                "Target monthly return (%)",
                min_value=2, max_value=20, value=5, step=1,
            )

        capital = max_loss / 0.20  # 20% max drawdown → back-calculate capital
        risk_per_trade = capital * 0.02
        monthly_profit_low = capital * (target_return_pct / 100) * 0.6
        monthly_profit_high = capital * (target_return_pct / 100) * 1.2
        worst_case = -max_loss

        st.divider()
        st.markdown("### Your Personalised Parameters")

        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Recommended Capital", f"${capital:,.0f}")
            st.metric("Risk Per Trade (2%)", f"${risk_per_trade:,.0f}")
        with m2:
            st.metric("Expected Monthly Return",
                      f"${monthly_profit_low:,.0f} – ${monthly_profit_high:,.0f}")
            st.metric("Worst-Case Month", f"${worst_case:,.0f}")
        with m3:
            st.metric("Max Drawdown", "-20%")
            safety = "✅ Safe" if capital >= 1000 else "⚠️ Increase capital"
            st.metric("Safety Assessment", safety)

        st.info(
            f"💡 With ${capital:,.0f} capital: system risks ${risk_per_trade:,.0f} per trade "
            f"and targets ${monthly_profit_low:,.0f}–${monthly_profit_high:,.0f}/month. "
            f"Maximum loss before automatic halt: ${max_loss:,.0f}."
        )

    # ── Tab 2: Procedure ───────────────────────────────────────────────────────
    with tab2:
        st.subheader("Step-by-Step Investment Procedure")

        steps = [
            ("Phase 1 (NOW)", "Paper Trading Setup",
             "System is running in paper mode. No real money at risk. "
             "Observe trades in the Dashboard. Expected duration: May 8 – July 8."),
            ("Phase 2 (July 8)", "Review Paper Results",
             "Check performance analytics. Target: >60% win rate, Sharpe > 1.0, "
             "max drawdown < 15%. If criteria met, proceed to live."),
            ("Phase 3 (Aug 1)", "Fund Broker Accounts",
             "Fund Alpaca (US), Angel One (India). Start with minimum viable capital. "
             "Do NOT fund more than you can afford to lose."),
            ("Phase 4 (Aug 1)", "Enable Live Micro Mode",
             "Go to Settings → Enable Live Trading. Two-step confirmation required. "
             "System starts with 1% position sizing (micro mode)."),
            ("Phase 5 (Sep 1+)", "Graduate to Full Sizing",
             "After 30 profitable live days, system offers graduation to full sizing. "
             "Human approval required. Only graduate if consistently profitable."),
        ]

        for i, (phase, title, desc) in enumerate(steps):
            done = i < 1  # only first step is done (paper setup)
            icon = "✅" if done else "⏳"
            with st.expander(f"{icon} {phase}: {title}", expanded=(i == 0)):
                st.markdown(desc)

    # ── Tab 3: Expected Returns ────────────────────────────────────────────────
    with tab3:
        st.subheader("Expected Returns by Scenario")

        scenarios = {
            "Conservative (Bear market)": {"monthly": "2-3%", "annual": "24-36%", "color": "blue"},
            "Base Case (Normal market)": {"monthly": "5-8%", "annual": "60-96%", "color": "green"},
            "Optimistic (Bull market)": {"monthly": "10-15%", "annual": "120-180%", "color": "orange"},
            "Worst Case (Market crisis)": {"monthly": "-20% (halt)", "annual": "N/A", "color": "red"},
        }

        for scenario, data in scenarios.items():
            col_s, col_m, col_a = st.columns([3, 1, 1])
            with col_s:
                st.markdown(f"**{scenario}**")
            with col_m:
                st.markdown(f"Monthly: `{data['monthly']}`")
            with col_a:
                st.markdown(f"Annual: `{data['annual']}`")
            st.divider()

        st.warning(
            "⚠️ **Important**: These are estimates based on backtesting, not guarantees. "
            "Past performance does not predict future results. Always start with capital you can afford to lose."
        )

    # ── Tab 4: FAQ ─────────────────────────────────────────────────────────────
    with tab4:
        st.subheader("Frequently Asked Questions")

        faqs = [
            ("How safe is my money?",
             "Paper trading uses NO real money. Live trading uses kill switches that "
             "automatically halt at -20% portfolio loss. No trade can lose more than 2% of capital."),
            ("What if the internet goes down?",
             "Open positions have stop-loss orders placed at brokers (not just software). "
             "If connection drops, orders already placed remain active."),
            ("Can I withdraw money during live trading?",
             "Yes. The system only uses deployed capital. Uninvested cash is immediately withdrawable."),
            ("What happens if Angel One API stops working?",
             "The system detects the API failure, halts India trading, and sends a Telegram alert. "
             "US and Crypto continue independently."),
            ("How do I know the system is working?",
             "Check the Dashboard every day. Active paper trades should appear. "
             "Telegram notifications fire for every signal and system event."),
            ("When should I switch from paper to live?",
             "After completing the full paper trading period (May 8 – July 8) with "
             ">60% win rate, Sharpe >1.0, and max drawdown <15%."),
            ("What is the minimum capital for live trading?",
             "US: $1,000 minimum (Alpaca has no minimum but low capital = tiny trades). "
             "India: ₹50,000 (covers margin requirements for F&O). "
             "Crypto: $500 minimum (Binance)."),
            ("Can the system lose everything?",
             "Extremely unlikely. The -20% portfolio kill switch halts ALL trading immediately. "
             "With $10,000 capital, maximum automated loss is $2,000 before full halt."),
        ]

        for q, a in faqs:
            with st.expander(f"❓ {q}"):
                st.markdown(a)
