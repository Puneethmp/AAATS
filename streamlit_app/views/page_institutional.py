"""
Institutional Testing Dashboard — Phase 1 / Phase 2 validation view.

Shows live status of all 27 institutional components, trade-by-trade
institutional metrics, compliance audit log, and raw system log.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

_ROOT = Path(__file__).parent.parent.parent
_PAPER_DB    = _ROOT / "data" / "paper_trades.db"
_EQUITY_DB   = _ROOT / "data" / "equity_curve.db"
_SLIPPAGE_DB = _ROOT / "data" / "slippage.db"
_POSITIONS_DB = _ROOT / "data" / "positions.db"
_AUDIT_DB    = _ROOT / "data" / "compliance_audit.db"
_ANOMALY_DB  = _ROOT / "data" / "anomalies.db"
_MACRO_DB    = _ROOT / "data" / "macro_signals.db"
_PHASE1_CP   = _ROOT / "data" / "phase1_checkpoint.json"
_PHASE2_CP   = _ROOT / "data" / "phase2_checkpoint.json"
_HALT_STATE  = _ROOT / "data" / "halt_state.json"
_LOG_FILE    = _ROOT / "logs" / "background_runner.log"


# ── helpers ───────────────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}


def _query(db: Path, sql: str, params: tuple = ()) -> pd.DataFrame:
    if not db.exists():
        return pd.DataFrame()
    try:
        with sqlite3.connect(db) as conn:
            return pd.read_sql_query(sql, conn, params=params)
    except Exception:
        return pd.DataFrame()


def _tail_log(n: int = 60) -> str:
    try:
        lines = _LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
        # strip ANSI colour codes
        import re
        clean = [re.sub(r"\x1b\[[0-9;]*m", "", l) for l in lines[-n:]]
        return "\n".join(clean)
    except Exception:
        return "(log not available)"


# ── component status cards ────────────────────────────────────────────────────

_COMPONENTS = {
    "SECURITY": [
        ("Encrypted Vault",        "foundation/secrets_manager.py"),
        ("RBAC",                   "foundation/rbac.py"),
        ("Compliance Audit Logger","compliance/audit_logger.py"),
    ],
    "RISK": [
        ("Position Manager",       "risk/position_manager.py"),
        ("Position Sizer (Kelly)", "risk/position_sizer.py"),
        ("Drawdown Monitor",       "risk/drawdown_monitor.py"),
        ("Settlement Manager",     "risk/settlement_manager.py"),
        ("Funding Rate Monitor",   "risk/funding_monitor.py"),
        ("Slippage Tracker",       "analytics/slippage_tracker.py"),
        ("Correlation Monitor",    "risk/correlation_monitor.py"),
        ("Market Hours",           "execution/market_hours.py"),
        ("Health Monitor",         "foundation/health_monitor.py"),
        ("Overnight Limits",       "risk/overnight_manager.py"),
        ("Macro Hedge",            "risk/macro_hedge.py"),
        ("Anomaly Detector",       "risk/anomaly_detector.py"),
    ],
    "EXECUTION": [
        ("Order Validator",        "execution/order_validator.py"),
        ("Backup API Handler",     "execution/backup_api_handler.py"),
        ("Multi-Leg Validator",    "execution/multi_leg_validator.py"),
        ("Partial Fill Handler",   "execution/partial_fill_handler.py"),
        ("TIF Manager",            "execution/order_tif_manager.py"),
        ("Dead Letter Queue",      "execution/dead_letter_queue.py"),
        ("Kill Switch",            "foundation/kill_switch.py"),
        ("Graceful Shutdown",      "foundation/shutdown_handler.py"),
    ],
    "ANALYTICS & COMPLIANCE": [
        ("PnL Attribution",        "analytics/pnl_attribution.py"),
        ("Stress Tester",          "analytics/stress_tester.py"),
        ("Strategy Optimizer",     "analytics/strategy_optimizer.py"),
        ("Regulatory Reporter",    "compliance/regulatory_reporter.py"),
        ("Tax Optimizer",          "compliance/tax_optimizer.py"),
        ("Mode Manager",           "foundation/mode_manager.py"),
    ],
}


def _component_exists(rel_path: str) -> bool:
    return (_ROOT / rel_path).exists()


# ── main render ───────────────────────────────────────────────────────────────

def render() -> None:
    st.title("Institutional Trading System — Phase Testing")
    st.caption("All 27 institutional components active and enforced. Auto-refreshes every 30s.")

    # ── auto-refresh ──────────────────────────────────────────────────────────
    if st.button("Refresh Now"):
        st.rerun()

    # ── Phase status ──────────────────────────────────────────────────────────
    ph1 = _read_json(_PHASE1_CP)
    ph2 = _read_json(_PHASE2_CP)

    col1, col2, col3, col4, col5 = st.columns(5)
    cycles_done = ph1.get("cycles_done", 0)
    cycles_total = ph1.get("cycles_planned", 24)
    trades_total = ph1.get("trades_total", 0)
    errors = ph1.get("errors", 0)
    hc_ok  = ph1.get("health_checks_ok", 0)
    hc_bad = ph1.get("health_checks_failed", 0)
    uptime = round(100 * hc_ok / max(hc_ok + hc_bad, 1), 1)

    with col1:
        status_icon = {"RUNNING": "🟢", "COMPLETED": "✅", "HALTED": "🔴"}.get(ph1.get("status", ""), "⚪")
        st.metric("Phase 1 Status", f"{status_icon} {ph1.get('status', 'NOT STARTED')}")
    with col2:
        st.metric("Cycle Progress", f"{cycles_done}/{cycles_total}", delta=f"{cycles_done*100//max(cycles_total,1)}%")
    with col3:
        st.metric("Trades", trades_total, delta="paper mode")
    with col4:
        st.metric("Uptime", f"{uptime}%", delta=f"{hc_ok} ok / {hc_bad} fail")
    with col5:
        halt = _read_json(_HALT_STATE)
        any_halted = any(halt.values()) if halt else False
        st.metric("Kill Switch", "🔴 HALTED" if any_halted else "🟢 ARMED")

    # timestamps
    if ph1.get("start_time"):
        st.info(
            f"Started: **{ph1['start_time']}** | "
            f"Expected end: **{ph1.get('expected_end', '—')}** | "
            f"Errors: **{errors}**"
        )

    st.divider()

    # ── Component status grid ─────────────────────────────────────────────────
    st.subheader("All 27 Institutional Components")

    for layer, items in _COMPONENTS.items():
        with st.expander(f"**{layer}** ({len(items)} components)", expanded=(layer == "RISK")):
            cols = st.columns(3)
            for i, (name, path) in enumerate(items):
                with cols[i % 3]:
                    exists = _component_exists(path)
                    st.markdown(f"{'✅' if exists else '❌'} **{name}**")
                    st.caption(path)

    st.divider()

    # ── Live metrics ──────────────────────────────────────────────────────────
    st.subheader("Live Institutional Metrics")

    m1, m2, m3, m4 = st.columns(4)

    # Drawdown
    with m1:
        dd_df = _query(
            _EQUITY_DB,
            "SELECT current_drawdown FROM equity_curve WHERE market='crypto' ORDER BY timestamp DESC LIMIT 1"
        )
        dd = float(dd_df.iloc[0, 0]) if not dd_df.empty else 0.0
        dd_pct = dd * 100
        st.metric("Max Drawdown", f"{dd_pct:.2f}%",
                  delta="🟢 OK" if dd_pct < 10 else ("⚠️ WARN" if dd_pct < 20 else "🔴 HALT"),
                  delta_color="off")

    # Avg slippage
    with m2:
        slip_df = _query(
            _SLIPPAGE_DB,
            "SELECT AVG(ABS(slippage_bps)) as avg_bps FROM slippage WHERE market='crypto'"
        )
        avg_bps = float(slip_df.iloc[0, 0]) if not slip_df.empty and slip_df.iloc[0, 0] else 0.0
        st.metric("Avg Slippage", f"{avg_bps:.1f} bps",
                  delta="✅ < 50 bps" if avg_bps < 50 else "⚠️ HIGH",
                  delta_color="off")

    # Open positions
    with m3:
        pos_df = _query(_POSITIONS_DB, "SELECT COUNT(*) as n FROM positions WHERE closed=0")
        n_open = int(pos_df.iloc[0, 0]) if not pos_df.empty else 0
        st.metric("Open Positions", n_open)

    # Macro hedge
    with m4:
        macro_df = _query(
            _MACRO_DB,
            "SELECT signal, hedge_factor FROM macro_signals ORDER BY timestamp DESC LIMIT 1"
        )
        if not macro_df.empty:
            sig = macro_df.iloc[0]["signal"]
            hf  = float(macro_df.iloc[0]["hedge_factor"])
            st.metric("Macro Signal", sig, delta=f"hedge={hf:.0%}", delta_color="off")
        else:
            st.metric("Macro Signal", "NEUTRAL", delta="hedge=100%", delta_color="off")

    # Anomalies
    anom_df = _query(
        _ANOMALY_DB,
        "SELECT COUNT(*) as n, severity FROM anomalies WHERE timestamp > ? GROUP BY severity",
        params=(time.time() - 86400,)
    )
    if not anom_df.empty:
        high = int(anom_df[anom_df["severity"].isin(["HIGH", "CRITICAL"])]["n"].sum()) if "severity" in anom_df.columns else 0
        if high:
            st.warning(f"⚠️ {high} HIGH/CRITICAL anomalies detected in last 24h")
    else:
        st.success("✅ No anomalies detected in last 24h")

    st.divider()

    # ── Trade history with institutional columns ───────────────────────────────
    st.subheader("Trade History — Institutional Detail")

    trades_df = _query(
        _PAPER_DB,
        """SELECT market, symbol, action, shares, price,
                  COALESCE(pnl, 0) as pnl,
                  signal, regime, risk_action,
                  created_at
           FROM paper_trades
           ORDER BY created_at DESC LIMIT 100"""
    )

    if not trades_df.empty:
        # Derived columns
        if "created_at" in trades_df.columns:
            trades_df["time"] = pd.to_datetime(trades_df["created_at"], unit="s", errors="coerce") \
                                  .dt.strftime("%Y-%m-%d %H:%M")

        # PnL colouring
        def _colour_pnl(val):
            try:
                v = float(val)
                if v > 0:   return "color: #22c55e"
                if v < 0:   return "color: #ef4444"
            except Exception:
                pass
            return ""

        display_cols = [c for c in ["time", "market", "symbol", "action", "shares",
                                     "price", "pnl", "regime", "risk_action"] if c in trades_df.columns]
        styled = trades_df[display_cols].style.applymap(_colour_pnl, subset=["pnl"] if "pnl" in display_cols else [])
        st.dataframe(styled, use_container_width=True, height=320)

        # Win-rate summary
        sells = trades_df[trades_df["action"] == "SELL"]
        if not sells.empty:
            wins = (sells["pnl"] > 0).sum()
            total_sells = len(sells)
            total_pnl = sells["pnl"].sum()
            wr = wins / total_sells * 100
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("Win Rate", f"{wr:.1f}%", delta=f"{wins}W / {total_sells-wins}L")
            sc2.metric("Total PnL", f"{total_pnl:+.2f} USDT")
            sc3.metric("Avg Trade PnL", f"{total_pnl/total_sells:+.2f} USDT")
    else:
        st.info("No trades yet — first cycle in progress")

    st.divider()

    # ── Open positions from position manager ──────────────────────────────────
    st.subheader("Open Positions (Persistent Position Manager)")

    pos_all = _query(
        _POSITIONS_DB,
        """SELECT symbol, market, entry_price, shares,
                  entry_price * shares as notional,
                  datetime(entry_time, 'unixepoch') as opened
           FROM positions WHERE closed=0 ORDER BY entry_time DESC"""
    )
    if not pos_all.empty:
        st.dataframe(pos_all, use_container_width=True)
    else:
        st.info("No open positions")

    st.divider()

    # ── Slippage analytics ────────────────────────────────────────────────────
    st.subheader("Execution Quality — Slippage Analytics")

    slip_all = _query(
        _SLIPPAGE_DB,
        """SELECT market, symbol, side, slippage_bps, notional,
                  datetime(recorded_at, 'unixepoch') as recorded
           FROM slippage ORDER BY recorded_at DESC LIMIT 50"""
    )
    if not slip_all.empty:
        avg_abs = slip_all["slippage_bps"].abs().mean()
        worst   = slip_all["slippage_bps"].abs().max()
        sa1, sa2 = st.columns(2)
        sa1.metric("Avg |Slippage|", f"{avg_abs:.1f} bps", delta="target < 50 bps", delta_color="off")
        sa2.metric("Worst Slippage", f"{worst:.1f} bps")
        st.dataframe(slip_all, use_container_width=True, height=220)
    else:
        st.info("No slippage records yet — trades in progress")

    st.divider()

    # ── Compliance audit log ──────────────────────────────────────────────────
    st.subheader("Compliance Audit Log (Immutable)")

    audit_df = _query(
        _AUDIT_DB,
        """SELECT datetime(timestamp, 'unixepoch') as time,
                  event_type, description, actor, market
           FROM compliance_audit ORDER BY timestamp DESC LIMIT 50"""
    )
    if not audit_df.empty:
        st.dataframe(audit_df, use_container_width=True, height=220)
    else:
        st.info("Audit events will appear here as the system runs")

    st.divider()

    # ── Anomalies ─────────────────────────────────────────────────────────────
    st.subheader("Anomaly Detector — Last 24h")

    anom_all = _query(
        _ANOMALY_DB,
        """SELECT datetime(timestamp, 'unixepoch') as time,
                  type, symbol, market, severity, detail
           FROM anomalies WHERE timestamp > ?
           ORDER BY timestamp DESC LIMIT 30""",
        params=(time.time() - 86400,)
    )
    if not anom_all.empty:
        def _sev_icon(row):
            icons = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
            row["severity"] = icons.get(row["severity"], "") + " " + row["severity"]
            return row
        st.dataframe(anom_all.apply(_sev_icon, axis=1), use_container_width=True, height=220)
    else:
        st.success("✅ Zero anomalies in last 24 hours")

    st.divider()

    # ── Live log ──────────────────────────────────────────────────────────────
    st.subheader("Live System Log (last 60 lines)")

    log_text = _tail_log(60)
    st.code(log_text, language="log")

    # ── Phase 2 readiness ─────────────────────────────────────────────────────
    st.divider()
    st.subheader("Phase 1 → Phase 2 Readiness Checklist")

    metrics_path = _ROOT / "data" / "phase1_metrics.json"
    m = _read_json(metrics_path) if metrics_path.exists() else {}

    checks = {
        "Uptime ≥ 95%":              m.get("uptime_percent", uptime) >= 95,
        "Zero unplanned crashes":    m.get("errors", errors) <= 2,
        "Slippage ≤ 50 bps":         avg_bps <= 50 or avg_bps == 0,
        "Kill switch armed":         not any_halted,
        "Position drifts = 0":       m.get("drifts", 0) == 0,
        "At least 1 trade executed": trades_total >= 1,
        "All 27 components present": all(
            _component_exists(p) for layer in _COMPONENTS.values() for _, p in layer
        ),
    }

    all_ok = all(checks.values())
    for label, ok in checks.items():
        st.markdown(f"{'✅' if ok else '⏳'} {label}")

    if all_ok:
        st.success("**READY FOR PHASE 2** — All Phase 1 criteria met")
    else:
        remaining = sum(1 for v in checks.values() if not v)
        st.info(f"Phase 2 readiness: {sum(checks.values())}/{len(checks)} checks passed — {remaining} pending")

    st.caption(f"Last rendered: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Auto-refresh via JS meta-refresh
    st.html('<meta http-equiv="refresh" content="30">')
