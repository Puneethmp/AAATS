"""
Production Readiness Dashboard Page — Displays system readiness for live deployment.

Shows:
  - Overall readiness score (0-100%)
  - Component health breakdown
  - Deployment blockers and warnings
  - Detailed validation results
  - Metrics summary
"""

from __future__ import annotations

import streamlit as st

from production_readiness.readiness_engine import generate_report


def render() -> None:
    """Render the production readiness page."""
    st.title("🏭 Production Readiness")
    st.caption("System validation for live deployment")
    
    # Generate readiness report
    with st.spinner("Generating readiness report..."):
        report = generate_report()
    
    # Overall status banner
    if report.is_ready:
        st.success(f"✅ **READY FOR LIVE DEPLOYMENT** — Score: {report.overall_score_percentage:.1f}%")
    elif report.has_blockers:
        st.error(f"❌ **NOT READY** — Score: {report.overall_score_percentage:.1f}% — {len(report.deployment_decision.blockers)} blockers")
    else:
        st.warning(f"⚠️ **NOT READY** — Score: {report.overall_score_percentage:.1f}%")
    
    st.divider()
    
    # Score visualization
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        st.metric(
            "Overall Readiness Score",
            f"{report.overall_score_percentage:.1f}%",
            delta=f"{report.overall_score_percentage - 85:.1f}% from minimum" if report.overall_score_percentage < 85 else "Ready",
            delta_color="normal" if report.overall_score_percentage >= 85 else "inverse",
        )
        
        # Progress bar
        st.progress(report.overall_score_percentage / 100.0)
    
    with col2:
        st.metric("Blockers", len(report.deployment_decision.blockers))
    
    with col3:
        st.metric("Warnings", len(report.score.warnings))
    
    st.divider()
    
    # Blockers section
    if report.deployment_decision.blockers:
        st.subheader("🚫 Deployment Blockers")
        st.error("The following issues must be resolved before live deployment:")
        for blocker in report.deployment_decision.blockers:
            st.markdown(f"- {blocker}")
        st.divider()
    
    # Warnings section
    if report.score.warnings:
        st.subheader("⚠️ Warnings")
        st.warning("The following issues should be addressed:")
        for warning in report.score.warnings:
            st.markdown(f"- {warning}")
        st.divider()
    
    # Validation results
    st.subheader("📋 Validation Results")
    
    for result in report.validation.results:
        # Status emoji
        if result.status == "PASS":
            status_emoji = "✅"
            status_color = "green"
        elif result.status == "WARNING":
            status_emoji = "⚠️"
            status_color = "orange"
        else:
            status_emoji = "❌"
            status_color = "red"
        
        # Display result
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col1:
            st.markdown(f"{status_emoji} **{result.check_name}**")
            st.caption(result.message)
        
        with col2:
            st.metric("Score", f"{result.score * 100:.0f}%")
        
        with col3:
            if result.required_for_live:
                st.markdown("🔒 **Required**")
            else:
                st.markdown("ℹ️ Optional")
        
        st.divider()
    
    # Metrics summary
    st.subheader("📊 Metrics Summary")
    
    tab1, tab2, tab3, tab4 = st.tabs([
        "📈 Paper Trading",
        "⚡ Execution",
        "🏗️ Infrastructure",
        "🛡️ Risk",
    ])
    
    with tab1:
        st.markdown("### Paper Trading Performance")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Trades", report.metrics.paper_trading.total_trades)
        
        with col2:
            st.metric("Win Rate", f"{report.metrics.paper_trading.win_rate:.1%}")
        
        with col3:
            st.metric("Total PnL", f"${report.metrics.paper_trading.total_pnl:,.2f}")
        
        with col4:
            st.metric("Max Drawdown", f"{report.metrics.paper_trading.max_drawdown:.1%}")
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Days Trading", report.metrics.paper_trading.days_trading)
        
        with col2:
            st.metric("Sharpe Ratio", f"{report.metrics.paper_trading.sharpe_ratio:.2f}")
    
    with tab2:
        st.markdown("### Execution Quality")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Orders", report.metrics.execution.total_orders)
        
        with col2:
            st.metric("Filled Orders", report.metrics.execution.filled_orders)
        
        with col3:
            st.metric("Fill Rate", f"{report.metrics.execution.fill_rate:.1%}")
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Rejected Orders", report.metrics.execution.rejected_orders)
        
        with col2:
            st.metric("Avg Fill Latency", f"{report.metrics.execution.avg_fill_latency_ms:.1f}ms")
    
    with tab3:
        st.markdown("### Infrastructure Health")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Uptime", f"{report.metrics.infrastructure.uptime_percentage:.1f}%")
        
        with col2:
            st.metric("Heartbeat Reliability", f"{report.metrics.infrastructure.heartbeat_reliability:.1%}")
        
        with col3:
            st.metric("Dashboard Sync", f"{report.metrics.infrastructure.dashboard_sync_health:.1%}")
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("API Uptime", f"{report.metrics.infrastructure.api_uptime:.1%}")
        
        with col2:
            st.metric("Recovery Success", f"{report.metrics.infrastructure.recovery_success_rate:.1%}")
    
    with tab4:
        st.markdown("### Risk Management")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Risk Violations", report.metrics.risk.risk_violations)
        
        with col2:
            st.metric("Kill Switch Triggers", report.metrics.risk.kill_switch_triggers)
    
    st.divider()
    
    # Recommendation
    st.subheader("💡 Recommendation")
    st.info(report.score.recommendation)
    
    # Refresh button
    if st.button("🔄 Refresh Report", use_container_width=True):
        st.rerun()
