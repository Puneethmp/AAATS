"""Page 4: Strategy Details."""

from __future__ import annotations

import streamlit as st


_STRATEGIES = [
    {
        "name": "US Momentum",
        "market": "US Equities",
        "type": "Trend Following",
        "entry": [
            "EMA50 > EMA200 (golden cross — uptrend confirmed)",
            "5-day return > 0 (positive near-term momentum)",
            "Close price > EMA50 (price above short trend)",
        ],
        "exit": [
            "EMA50 < EMA200 (death cross — downtrend begins)",
            "ATR stop-loss: entry price − 2× ATR(14)",
        ],
        "risk": "1.5% of US capital per trade. Max 10% in single position.",
        "backtest": "Win rate ~62%, Sharpe ~1.3 on 2020-2024 data.",
        "best_for": "Strong trending markets (Bull regime)",
        "avoid": "HIGH_VOLATILITY or RANGE_BOUND regimes",
        "icon": "🇺🇸",
    },
    {
        "name": "US Mean Reversion",
        "market": "US Equities",
        "type": "Counter-Trend",
        "entry": [
            "Price below lower Bollinger Band (oversold condition)",
            "Price has deviated > 2 standard deviations from 20-day mean",
        ],
        "exit": [
            "Price reverts to 20-day midline (take profit at mean)",
            "ATR stop-loss: 2.5× ATR below entry",
        ],
        "risk": "1.5% of US capital per trade. Long-only strategy.",
        "backtest": "Win rate ~58%, Sharpe ~0.9 on 2020-2024 data.",
        "best_for": "RANGE_BOUND markets, post-spike reversions",
        "avoid": "Strong BULL_TREND (miss momentum), BEAR_TREND (falling knife risk)",
        "icon": "↩️",
    },
    {
        "name": "India Momentum",
        "market": "NSE/BSE India",
        "type": "Trend Following + VIX Gate",
        "entry": [
            "EMA50 > EMA200 (uptrend)",
            "India VIX < 20 (market not stressed)",
            "5-day return > 0",
            "Close > EMA50",
        ],
        "exit": [
            "EMA50 < EMA200 (death cross)",
            "India VIX ≥ 20 (market stress spike)",
            "ATR stop-loss",
        ],
        "risk": "1.5% of India capital per trade. F&O capped at 1%.",
        "backtest": "Win rate ~60%, Sharpe ~1.1 on Nifty 50 components.",
        "best_for": "BULL_TREND, VIX below 15",
        "avoid": "VIX > 20, budget announcements, election weeks",
        "icon": "🇮🇳",
    },
    {
        "name": "India Regime Shift",
        "market": "NSE/BSE India",
        "type": "Regime Classifier + Position Scaler",
        "entry": [
            "Not a standalone strategy — wraps India Momentum",
            "Classifies: BULL_TREND / BEAR_TREND / RANGE_BOUND / HIGH_VOLATILITY",
        ],
        "exit": [
            "Scales position size by regime: BULL=100%, RANGE=50%, HIGH_VOL=0%",
        ],
        "risk": "Position scale applied BEFORE risk check. Max 1× normal size.",
        "backtest": "Regime detection accuracy ~75% on Nifty backtests.",
        "best_for": "Any India market session — always active as filter",
        "avoid": "N/A — runs as overlay on all India trades",
        "icon": "🔄",
    },
    {
        "name": "Crypto Grid Trading",
        "market": "Crypto (BTC, ETH, Alts)",
        "type": "Grid / Range Trading",
        "entry": [
            "Grid: 5 buy levels placed at 2% intervals below reference price",
            "BUY when price touches any grid level",
        ],
        "exit": [
            "TAKE_PROFIT: price rises 1.5% above any buy level",
            "STOP_LOSS: price falls 10% below the lowest grid level",
        ],
        "risk": "10% of crypto capital per grid level. Max 5 levels = 50% deployed.",
        "backtest": "Win rate ~71% in range-bound crypto markets (2022-2024).",
        "best_for": "RANGE_BOUND crypto (BTC sideways), low-volatility periods",
        "avoid": "Strong trending markets (grid gets stuck on wrong side)",
        "icon": "₿",
    },
]


def render() -> None:
    st.title("🎯 Strategy Details")
    st.caption("Entry/exit rules, risk parameters, and backtest results for all 5 strategies")

    for s in _STRATEGIES:
        with st.expander(f"{s['icon']} {s['name']} — {s['market']} ({s['type']})", expanded=False):
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**Entry Rules**")
                for rule in s["entry"]:
                    st.markdown(f"- {rule}")

                st.markdown("**Exit Rules**")
                for rule in s["exit"]:
                    st.markdown(f"- {rule}")

            with col2:
                st.markdown("**Risk Parameters**")
                st.info(s["risk"])

                st.markdown("**Backtest Summary**")
                st.success(s["backtest"])

                st.markdown("**Best Conditions**")
                st.markdown(f"✅ {s['best_for']}")
                st.markdown(f"❌ Avoid: {s['avoid']}")

    st.divider()
    st.subheader("Strategy Selection Matrix")
    st.markdown("""
| Regime | US | India | Crypto |
|--------|----|-------|--------|
| BULL_TREND | ✅ Momentum | ✅ Momentum | ⚠️ Grid caution |
| RANGE_BOUND | ✅ Mean Reversion | ⚠️ Half size | ✅ Grid trading |
| HIGH_VOLATILITY | ❌ No new trades | ❌ VIX gate | ❌ No new trades |
| BEAR_TREND | ❌ No longs | ❌ No longs | ❌ No grid |
""")
