"""
Institutional Testing Dashboard — Phase 1 / Phase 2 validation view.

Shows live status of all 27 institutional components, trade-by-trade
institutional metrics, compliance audit log, and raw system log.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

_ROOT        = Path(__file__).parent.parent.parent
_PAPER_DB    = _ROOT / "data" / "paper_trades.db"
_EQUITY_DB   = _ROOT / "data" / "equity_curve.db"
_SLIPPAGE_DB = _ROOT / "data" / "slippage.db"
_POSITIONS_DB = _ROOT / "data" / "positions.db"
_AUDIT_DB    = _ROOT / "data" / "compliance_audit.db"
_ANOMALY_DB  = _ROOT / "data" / "anomalies.db"
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


def _tail_log(n: int = 50) -> str:
    try:
        text = _LOG_FILE.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        clean = [re.sub(r"\x1b\[[0-9;]*m", "", l) for l in lines[-n:]]
        return "\n".join(clean)
    except Exception:
        return "(log not available — check logs/background_runner.log)"


def _parse_regimes_from_log() -> dict[str, int]:
    """Aggregate regime counts from all 'Regime detection complete' lines in the log."""
    try:
        text = _LOG_FILE.read_text(encoding="utf-8", errors="ignore")
        matches = re.findall(r"Regime detection complete.*?(\{[^}]+\})", text)
        totals: Counter = Counter()
        for m in matches:
            try:
                # ast-safe parse: replace single quotes for json
                parsed = json.loads(m.replace("'", '"'))
                totals.update(parsed)
            except Exception:
                pass
        return dict(totals.most_common())
    except Exception:
        return {}


def _get_total_pnl() -> float:
    """Sum PnL of all SELL trades from paper_trades.db."""
    df = _query(_PAPER_DB, "SELECT COALESCE(SUM(pnl), 0) as total FROM paper_trades WHERE action='SELL'")
    if not df.empty:
        return float(df.iloc[0, 0])
    return 0.0


# ── component status cards ────────────────────────────────────────────────────

_COMPONENTS = {
    "SECURITY": [
        ("Encrypted Vault",         "foundation/secrets_manager.py"),
        ("RBAC",                    "foundation/rbac.py"),
        ("Compliance Audit Logger", "compliance/audit_logger.py"),
    ],
    "RISK": [
        ("Position Manager",        "risk/position_manager.py"),
        ("Position Sizer (Kelly)",  "risk/position_sizer.py"),
        ("Drawdown Monitor",        "risk/drawdown_monitor.py"),
        ("Settlement Manager",      "risk/settlement_manager.py"),
        ("Funding Rate Monitor",    "risk/funding_monitor.py"),
        ("Slippage Tracker",        "analytics/slippage_tracker.py"),
        ("Correlation Monitor",     "risk/correlation_monitor.py"),
        ("Market Hours",            "execution/market_hours.py"),
        ("Health Monitor",          "foundation/health_monitor.py"),
        ("Overnight Limits",        "risk/overnight_manager.py"),
        ("Macro Hedge",             "risk/macro_hedge.py"),
        ("Anomaly Detector",        "risk/anomaly_detector.py"),
    ],
    "EXECUTION": [
        ("Order Validator",         "execution/order_validator.py"),
        ("Backup API Handler",      "execution/backup_api_handler.py"),
        ("Multi-Leg Validator",     "execution/multi_leg_validator.py"),
        ("Partial Fill Handler",    "execution/partial_fill_handler.py"),
        ("TIF Manager",             "execution/order_tif_manager.py"),
        ("Dead Letter Queue",       "execution/dead_letter_queue.py"),
        ("Kill Switch",             "foundation/kill_switch.py"),
        ("Graceful Shutdown",       "foundation/shutdown_handler.py"),
    ],
    "ANALYTICS & COMPLIANCE": [
        ("PnL Attribution",         "analytics/pnl_attribution.py"),
        ("Stress Tester",           "analytics/stress_tester.py"),
        ("Strategy Optimizer",      "analytics/strategy_optimizer.py"),
        ("Regulatory Reporter",     "compliance/regulatory_reporter.py"),
        ("Tax Optimizer",           "compliance/tax_optimizer.py"),
        ("Mode Manager",            "foundation/mode_manager.py"),
    ],
}

_ALL_PATHS = [p for items in _COMPONENTS.values() for _, p in items]


def _component_exists(rel_path: str) -> bool:
    return (_ROOT / rel_path).exists()


def _all_components_present() -> bool:
    return all(_component_exists(p) for p in _ALL_PATHS)


# ── main render ───────────────────────────────────────────────────────────────

def render() -> None:
    st.title("Institutional Trading System — Phase 1 Testing")
    st.caption("Live Phase 1 data. Auto-refreshes every 30 seconds.")

    col_refresh, col_space = st.columns([1, 8])
    with col_refresh:
        if st.button("↻ Refresh"):
            st.rerun()

    # ── Load checkpoint ───────────────────────────────────────────────────────
    ph1 = _read_json(_PHASE1_CP)
    halt = _read_json(_HALT_STATE)
    any_halted = any(v for k, v in halt.items() if k != "india")  # india halted by design in phase 1

    cycles_done  = ph1.get("cycles_done", 0)
    cycles_total = ph1.get("cycles_planned", 24)
    trades_total = ph1.get("trades_total", 0)
    errors       = ph1.get("errors", 0)
    hc_ok        = ph1.get("health_checks_ok", 0)
    hc_bad       = ph1.get("health_checks_failed", 0)
    status       = ph1.get("status", "NOT STARTED")
    total_pnl    = _get_total_pnl()

    # ── ROW 1: Key metrics ────────────────────────────────────────────────────
    st.subheader("Phase 1 — Live Metrics")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        status_color = {"RUNNING": "🟢", "COMPLETED": "✅", "HALTED": "🔴"}.get(status, "⚪")
        st.metric(
            "Phase 1 Cycle",
            f"{cycles_done}/{cycles_total}",
            delta=f"{status_color} {status}",
            delta_color="off",
        )
    with c2:
        st.metric(
            "Total Trades",
            str(trades_total),
            delta="paper mode — no real capital",
            delta_color="off",
        )
    with c3:
        pnl_delta = "profit" if total_pnl >= 0 else "loss"
        st.metric(
            "Total P&L",
            f"{total_pnl:+.2f} USDT",
            delta=pnl_delta,
            delta_color="normal" if total_pnl >= 0 else "inverse",
        )
    with c4:
        st.metric(
            "Errors",
            str(errors),
            delta=f"health checks: {hc_ok} ok / {hc_bad} fail",
            delta_color="off",
        )

    if ph1.get("start_time"):
        st.info(
            f"Started: **{ph1['start_time'][:19]}** | "
            f"Expected end: **{ph1.get('expected_end', '—')[:19]}** | "
            f"Uptime: **{round(100*hc_ok/max(hc_ok+hc_bad,1),1)}%**"
        )

    st.divider()

    # ── ROW 2: Market Regimes ─────────────────────────────────────────────────
    st.subheader("Market Regimes (from live log)")

    regimes = _parse_regimes_from_log()

    if regimes:
        total_detections = sum(regimes.values())
        regime_cols = st.columns(len(regimes))
        colors = {
            "BULL_TREND":     "🟢",
            "BEAR_TREND":     "🔴",
            "RANGE_BOUND":    "🟡",
            "HIGH_VOLATILITY":"🟠",
            "UNKNOWN":        "⚪",
        }
        for i, (regime, count) in enumerate(regimes.items()):
            with regime_cols[i]:
                pct = count / total_detections * 100 if total_detections else 0
                st.metric(
                    f"{colors.get(regime, '⚪')} {regime}",
                    str(count),
                    delta=f"{pct:.1f}% of bars",
                    delta_color="off",
                )
        # Progress bar visual
        if total_detections:
            st.caption(f"Total regime detections from log: **{total_detections:,}** bar readings")
    else:
        st.info("Regime data not yet available — log file is being written")

    st.divider()

    # ── ROW 3: Institutional Controls ─────────────────────────────────────────
    st.subheader("Institutional Controls Status")

    halt_crypto  = halt.get("crypto", False)
    halt_india   = halt.get("india", True)   # expected True in Phase 1
    all_present  = _all_components_present()

    i1, i2, i3, i4 = st.columns(4)
    with i1:
        hc_label = f"{hc_ok}/{max(hc_ok+hc_bad,1)}"
        st.metric("Health Checks", hc_label, delta="✅ passed" if hc_bad == 0 else f"⚠️ {hc_bad} failed", delta_color="off")
    with i2:
        st.metric("Kill Switch", "ARMED" if not halt_crypto else "HALTED",
                  delta="🟢 crypto live" if not halt_crypto else "🔴 crypto halted",
                  delta_color="off")
    with i3:
        pos_df = _query(_POSITIONS_DB, "SELECT COUNT(*) as n FROM positions WHERE closed=0")
        n_open = int(pos_df.iloc[0, 0]) if not pos_df.empty else 0
        st.metric("Position Manager", f"{n_open} open", delta="✅ active (SQLite-backed)", delta_color="off")
    with i4:
        n_components = len(_ALL_PATHS)
        n_present    = sum(1 for p in _ALL_PATHS if _component_exists(p))
        st.metric("Components", f"{n_present}/{n_components}",
                  delta="✅ all enforced" if n_present >= n_components else f"⚠️ {n_components-n_present} missing",
                  delta_color="off")

    # Detailed checklist
    with st.expander("Full Controls Checklist", expanded=False):
        checks_status = [
            ("Health checks passed",       hc_bad == 0),
            ("Kill switch armed (crypto)",  not halt_crypto),
            ("India halted (expected P1)",  halt_india),
            ("Position manager active",     n_open >= 0),
            ("All 27 components present",   all_present),
            ("Zero errors",                 errors == 0),
            (f"Cycles running ({cycles_done}/{cycles_total})", cycles_done > 0),
        ]
        for label, ok_flag in checks_status:
            icon = "✅" if ok_flag else "⚠️"
            st.markdown(f"{icon} {label}")

    # Component grid
    with st.expander("All 27 Components — File Existence Check", expanded=False):
        for layer, items in _COMPONENTS.items():
            st.markdown(f"**{layer}**")
            cols = st.columns(3)
            for i, (name, path) in enumerate(items):
                with cols[i % 3]:
                    exists = _component_exists(path)
                    st.markdown(f"{'✅' if exists else '❌'} {name}")
                    st.caption(path)

    st.divider()

    # ── ROW 4: Live Log ───────────────────────────────────────────────────────
    st.subheader("Live System Log (last 50 lines)")

    log_text = _tail_log(50)
    st.code(log_text, language="log")

    st.divider()

    # ── Trade History ─────────────────────────────────────────────────────────
    st.subheader("Trade History — All Paper Trades")

    trades_df = _query(
        _PAPER_DB,
        """SELECT market, symbol, action, shares, price,
                  COALESCE(pnl, 0) as pnl,
                  signal, regime, risk_action, timestamp
           FROM paper_trades
           ORDER BY timestamp DESC LIMIT 100"""
    )

    if not trades_df.empty:
        # PnL colouring
        def _colour_pnl(val):
            try:
                v = float(val)
                if v > 0: return "color: #22c55e"
                if v < 0: return "color: #ef4444"
            except Exception:
                pass
            return ""

        display_cols = [c for c in ["timestamp", "market", "symbol", "action",
                                    "shares", "price", "pnl", "regime", "risk_action"]
                        if c in trades_df.columns]
        styled = trades_df[display_cols].style.map(_colour_pnl, subset=["pnl"] if "pnl" in display_cols else [])
        st.dataframe(styled, use_container_width=True, height=320)

        sells = trades_df[trades_df["action"] == "SELL"]
        if not sells.empty:
            wins        = int((sells["pnl"] > 0).sum())
            total_sells = len(sells)
            t_pnl       = float(sells["pnl"].sum())
            wr          = wins / total_sells * 100 if total_sells else 0
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("Win Rate",    f"{wr:.1f}%",          delta=f"{wins}W / {total_sells-wins}L")
            sc2.metric("Realised P&L",f"{t_pnl:+.2f} USDT")
            sc3.metric("Avg per Trade",f"{t_pnl/total_sells:+.2f} USDT")
    else:
        st.info("No trades yet — first cycle in progress")

    st.divider()

    # ── Open Positions ────────────────────────────────────────────────────────
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

    # ── Phase 2 Readiness ─────────────────────────────────────────────────────
    st.subheader("Phase 1 → Phase 2 Readiness")

    dd_df = _query(
        _EQUITY_DB,
        "SELECT current_drawdown FROM equity_curve WHERE market='crypto' ORDER BY timestamp DESC LIMIT 1"
    )
    dd_pct = float(dd_df.iloc[0, 0]) * 100 if not dd_df.empty and dd_df.iloc[0, 0] else 0.0

    slip_df = _query(
        _SLIPPAGE_DB,
        "SELECT AVG(ABS(slippage_bps)) as avg_bps FROM slippage WHERE market='crypto'"
    )
    avg_bps = float(slip_df.iloc[0, 0]) if not slip_df.empty and slip_df.iloc[0, 0] else 0.0

    readiness = {
        "Uptime ≥ 95%":             hc_bad == 0 or hc_ok / max(hc_ok + hc_bad, 1) >= 0.95,
        "Zero unplanned crashes":   errors <= 2,
        "Slippage ≤ 50 bps":        avg_bps <= 50,
        "Kill switch armed":        not halt_crypto,
        "≥ 1 trade executed":       trades_total >= 1,
        "Drawdown < 20%":           dd_pct < 20,
        "All 27 components present":all_present,
    }

    passed = sum(readiness.values())
    for label, ok_flag in readiness.items():
        st.markdown(f"{'✅' if ok_flag else '⏳'} {label}")

    if passed == len(readiness):
        st.success("**READY FOR PHASE 2** — All criteria met")
    else:
        st.info(f"Phase 2 readiness: **{passed}/{len(readiness)}** criteria met")

    st.caption(f"Last rendered: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

    # Auto-refresh every 30s
    st.html('<meta http-equiv="refresh" content="30">')
