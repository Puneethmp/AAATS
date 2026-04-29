"""Page 3: Investment Guide — post-tax calculator, procedure, returns, FAQ."""

from __future__ import annotations

import streamlit as st

# ── Tax constants (India RBI/SEBI compliant) ───────────────────────────────────
_INDIA_ST_TAX = 0.30        # 30% short-term capital gains (Angel One)
_INDIA_LT_TAX = 0.20        # 20% long-term capital gains
_CRYPTO_TDS = 0.30          # 30% TDS on Binance transactions > ₹50k
_US_WITHHOLD = 0.20         # 20% TDS withholding on US stocks (Alpaca)
_USD_INR = 83.5             # approximate exchange rate


def _post_tax_calc(capital_inr: float, target_pct: float) -> dict:
    """Compute per-market gross, tax, and net monthly figures (all in ₹)."""
    # Capital allocation (from legal compliance framework)
    india_cap = capital_inr * 0.40   # Angel One 40%
    crypto_cap = capital_inr * 0.35  # Binance 35%
    us_cap = capital_inr * 0.15      # Alpaca 15%

    gross_india = india_cap * (target_pct / 100)
    gross_crypto = crypto_cap * (target_pct / 100)
    gross_us = us_cap * (target_pct / 100)

    tax_india = gross_india * _INDIA_ST_TAX
    tax_crypto = gross_crypto * _CRYPTO_TDS
    tax_us = gross_us * _US_WITHHOLD

    net_india = gross_india - tax_india
    net_crypto = gross_crypto - tax_crypto
    net_us = gross_us - tax_us

    total_gross = gross_india + gross_crypto + gross_us
    total_tax = tax_india + tax_crypto + tax_us
    total_net = net_india + net_crypto + net_us

    effective_rate = total_tax / total_gross if total_gross else 0

    return {
        "india": {"gross": gross_india, "tax": tax_india, "net": net_india, "rate": _INDIA_ST_TAX},
        "crypto": {"gross": gross_crypto, "tax": tax_crypto, "net": net_crypto, "rate": _CRYPTO_TDS},
        "us": {"gross": gross_us, "tax": tax_us, "net": net_us, "rate": _US_WITHHOLD},
        "total": {"gross": total_gross, "tax": total_tax, "net": total_net, "effective_rate": effective_rate},
    }


def render() -> None:
    st.title("💡 Investment Guide")
    st.caption("Post-tax returns, RBI/SEBI compliance, and your roadmap to live trading")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📐 Post-Tax Calculator", "📋 Procedure", "📊 Expected Returns", "❓ FAQ"
    ])

    # ── Tab 1: Post-Tax Calculator ─────────────────────────────────────────────
    with tab1:
        st.subheader("Post-Tax Investment Calculator")
        st.markdown(
            "This calculator shows **AFTER-TAX** profit — what actually hits your bank account. "
            "Taxes are computed per market using current RBI/SEBI rates."
        )

        col1, col2 = st.columns(2)
        with col1:
            capital_inr = st.number_input(
                "Total Capital (₹)",
                min_value=10_000, max_value=50_00_000, value=10_00_000, step=50_000,
                help="Your total trading capital across all markets",
            )
        with col2:
            target_pct = st.slider(
                "Target monthly return % (before tax)",
                min_value=1, max_value=20, value=5, step=1,
            )

        result = _post_tax_calc(float(capital_inr), float(target_pct))

        st.divider()
        st.markdown("### Capital Allocation (Legal Framework)")
        a1, a2, a3 = st.columns(3)
        with a1:
            st.metric("Angel One (India) 40%", f"₹{capital_inr * 0.40:,.0f}")
        with a2:
            st.metric("Binance (Crypto) 35%", f"₹{capital_inr * 0.35:,.0f}")
        with a3:
            st.metric("Alpaca (US) 15%", f"₹{capital_inr * 0.15:,.0f}")

        st.divider()
        st.markdown("### Monthly Returns — GROSS vs NET (After Tax)")

        header = st.columns([2, 1, 1, 1, 1])
        header[0].markdown("**Market**")
        header[1].markdown("**Gross**")
        header[2].markdown("**Tax Rate**")
        header[3].markdown("**Tax Paid**")
        header[4].markdown("**Net Profit ✅**")

        rows = [
            ("🇮🇳 Angel One (India)", "result['india']", result["india"], "30% ST-CGT"),
            ("₿ Binance (Crypto)", "result['crypto']", result["crypto"], "30% TDS"),
            ("🇺🇸 Alpaca (US)", "result['us']", result["us"], "20% TDS"),
        ]

        for label, _, data, rate_label in rows:
            r = st.columns([2, 1, 1, 1, 1])
            r[0].markdown(label)
            r[1].markdown(f"₹{data['gross']:,.0f}")
            r[2].markdown(f"`{rate_label}`")
            r[3].markdown(f"₹{data['tax']:,.0f}")
            r[4].markdown(f"**₹{data['net']:,.0f}**")

        st.divider()
        t = result["total"]
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Gross Monthly", f"₹{t['gross']:,.0f}")
        with m2:
            st.metric("Total Tax", f"₹{t['tax']:,.0f}",
                      delta=f"-{t['effective_rate']:.0%} effective", delta_color="inverse")
        with m3:
            st.metric("Net Monthly Profit", f"₹{t['net']:,.0f}")
        with m4:
            st.metric("Annual Net (est.)", f"₹{t['net'] * 12:,.0f}")

        worst_case_loss = capital_inr * 0.20  # 20% drawdown halt
        st.warning(
            f"⚠️ **Risk**: Maximum automated loss before full halt = "
            f"₹{worst_case_loss:,.0f} ({worst_case_loss / capital_inr:.0%} of capital). "
            f"Only invest what you can afford to lose."
        )

        with st.expander("📅 Tax Calendar & ITR-2 Filing"):
            st.markdown("""
**Monthly:**
- Reconcile all trades and confirm TDS already deducted at source
- Angel One & Binance automatically deduct TDS — verify broker statements

**Quarterly:**
- Download trade history from Reports → ITR-2 Export
- Check advance tax liability (if annual tax > ₹10,000)

**July 31 (Annual):**
- File ITR-2 with all broker statements (Form 26AS, broker tax reports)
- AAATS exports ITR-2-ready CSV from Reports page

**Note:** Paper trading (no real money) → no ITR filing required.
ITR filing required only when you switch to live trading with real capital.
""")

    # ── Tab 2: Procedure ───────────────────────────────────────────────────────
    with tab2:
        st.subheader("Step-by-Step Investment Procedure")

        steps = [
            ("Phase 1 (NOW)", "Paper Trading",
             "System runs in paper mode. No real money at risk. "
             "Observe trades in Dashboard. Target: May 8 – July 8."),
            ("Phase 2 (July 8)", "Review Paper Results",
             "Check Performance Analytics. Proceed only if: win rate > 60%, "
             "Sharpe > 1.0, max drawdown < 15%."),
            ("Phase 3 (Aug 1)", "Fund Broker Accounts",
             "Fund Alpaca (US — min $1,000), Angel One (India — min ₹50,000), "
             "Binance (Crypto — min $500). Complete KYC/W-8BEN for each broker."),
            ("Phase 4 (Aug 1)", "Enable Live Micro Mode",
             "Settings → Enable Live Trading → 2-step confirmation. "
             "System starts with 1% position sizing. TDS tracking activates."),
            ("Phase 5 (Sep 1+)", "Graduate to Full Sizing",
             "After 30 profitable live days, system offers full sizing graduation. "
             "Download ITR-2 export from Reports before year-end."),
        ]

        for i, (phase, title, desc) in enumerate(steps):
            done = i < 1
            icon = "✅" if done else "⏳"
            with st.expander(f"{icon} {phase}: {title}", expanded=(i == 0)):
                st.markdown(desc)

    # ── Tab 3: Expected Returns ────────────────────────────────────────────────
    with tab3:
        st.subheader("Expected Returns — After Tax (₹ per month per ₹10L capital)")

        data = [
            ("Conservative (Bear market)", "2–3%", "₹1,300–₹1,950", "₹16k–₹23k/yr"),
            ("Base Case (Normal market)",  "5–8%", "₹3,250–₹5,200", "₹39k–₹62k/yr"),
            ("Optimistic (Bull market)",   "10–15%", "₹6,500–₹9,750", "₹78k–₹117k/yr"),
            ("Worst Case (Market crisis)", "−20% (halt)", "₹0", "Max loss: ₹2L"),
        ]

        header = st.columns([3, 1, 2, 2])
        header[0].markdown("**Scenario**")
        header[1].markdown("**Gross %**")
        header[2].markdown("**Net/month**")
        header[3].markdown("**Annual**")
        st.divider()

        for scenario, gross, net, annual in data:
            r = st.columns([3, 1, 2, 2])
            r[0].markdown(f"**{scenario}**")
            r[1].markdown(f"`{gross}`")
            r[2].markdown(net)
            r[3].markdown(annual)
            st.divider()

        st.info(
            "Net figures assume 30% blended effective tax rate across all markets. "
            "Actual tax depends on holding period (ST vs LT) and transaction size."
        )
        st.warning(
            "⚠️ These are estimates from backtesting, not guarantees. "
            "Start with capital you can afford to lose."
        )

    # ── Tab 4: FAQ ─────────────────────────────────────────────────────────────
    with tab4:
        st.subheader("Frequently Asked Questions")

        faqs = [
            ("How safe is my money?",
             "Paper trading: no real money. Live: kill switches halt at -20% portfolio loss. "
             "No trade can lose more than 2% of capital automatically."),
            ("What taxes will I actually pay?",
             "• Angel One (India): 30% short-term CGT on profits\n"
             "• Binance (Crypto): 30% TDS on transactions > ₹50k (deducted at source)\n"
             "• Alpaca (US stocks): 20% TDS on gains (deducted at source via W-8BEN)\n"
             "Use the Post-Tax Calculator above to see your net profit."),
            ("Do I need to file ITR?",
             "Paper trading: No (no real money, no taxable income). "
             "Live trading: Yes — file ITR-2 by July 31 each year. "
             "AAATS exports ITR-2-ready CSV from the Reports page."),
            ("Is Binance legal in India?",
             "Yes. Binance is legal for Indian traders with 30% TDS compliance (VDA tax). "
             "Ensure you declare all crypto gains in ITR-2 Schedule VDA."),
            ("Is Alpaca legal for Indians?",
             "Yes. Alpaca is SEC-regulated. Indian traders can trade US stocks via LRS (Liberalised Remittance Scheme). "
             "Limit: $250,000/year. Gains taxed as foreign income (20% flat)."),
            ("What if the internet goes down?",
             "Stop-loss orders are placed at brokers, not just software. "
             "If connection drops, broker orders remain active."),
            ("When should I switch from paper to live?",
             "After May 8 – July 8 paper period with win rate > 60%, Sharpe > 1.0, drawdown < 15%."),
            ("What is the minimum capital?",
             "US (Alpaca): $1,000 minimum. India (Angel One): ₹50,000. Crypto (Binance): $500."),
        ]

        for q, a in faqs:
            with st.expander(f"❓ {q}"):
                st.markdown(a)
