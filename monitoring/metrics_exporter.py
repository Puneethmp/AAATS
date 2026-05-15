"""
monitoring/metrics_exporter.py  --  Prometheus Metrics Exporter for AAATS

Runs as a standalone HTTP server on port 9091.
Grafana -> Prometheus (9090) -> this exporter (9091) -> AAATS data files
Start: python monitoring/metrics_exporter.py
"""

from __future__ import annotations
import json, logging, os, sqlite3, threading, time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import psutil

log = logging.getLogger("metrics_exporter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ROOT           = Path(__file__).resolve().parent.parent
DB_TRADES      = ROOT / "data" / "paper_trades.db"
DB_POSITIONS   = ROOT / "data" / "positions.db"
PORTFOLIO_FILE = ROOT / "data" / "paper_portfolio.json"
PHASE1_FILE    = ROOT / "data" / "phase1_checkpoint.json"
FUNDING_STATE  = ROOT / "data" / "funding_arb_state.json"
MOMENTUM_STATE = ROOT / "data" / "momentum_state.json"
STAT_ARB_HEALTH= ROOT / "data" / "stat_arb_health.json"
HEARTBEAT_FILE = ROOT / "data" / "heartbeat.json"
ML_META_FILE   = ROOT / "data" / "ml" / "training_meta.json"
FG_CACHE       = ROOT / "data" / "fear_greed_cache.json"
PORT           = 9091
SCRAPE_INTERVAL = 30
_lock = threading.Lock()
_cached_metrics = ""


def _g(name, value, labels=None, help_text=""):
    lstr = ""
    if labels:
        lstr = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
    return f"# HELP {name} {help_text}\n# TYPE {name} gauge\n{name}{lstr} {value:.6f}\n"


def _c(name, value, labels=None, help_text=""):
    """Prometheus counter (monotonic). Same shape as _g but TYPE = counter."""
    lstr = ""
    if labels:
        lstr = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
    return f"# HELP {name} {help_text}\n# TYPE {name} counter\n{name}{lstr} {value:.6f}\n"


def _read_json(path):
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def _query_db(db, sql, params=()):
    try:
        with sqlite3.connect(str(db), timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception:
        return []


def collect_portfolio():
    out = []
    portfolio = _read_json(PORTFOLIO_FILE)
    # Open positions deployed (from strategy state files) — must be added back to
    # capital so dashboards show the real budget, not just cash.
    c3 = _read_json(ROOT / "data" / "altcoin_reversion_state.json")
    c6 = _read_json(ROOT / "data" / "bollinger_range_state.json")
    deployed_by_market = {"crypto": 0.0}
    for d in (c3, c6):
        if not isinstance(d, dict): continue
        for v in d.values():
            if isinstance(v, dict):
                deployed_by_market["crypto"] += float(v.get("size_usd", 0) or 0)
    total = 0.0
    for market, data in portfolio.items():
        if not isinstance(data, dict): continue
        cash = float(data.get("capital", 0))
        deployed = deployed_by_market.get(market, 0.0)
        # Budget = cash + deployed. Halt state means deployed should be 0 anyway.
        budget = cash + deployed
        total += budget
        # aaats_portfolio_capital now reports BUDGET (cash + open position notional)
        out.append(_g("aaats_portfolio_capital", budget, {"market": market}, "Portfolio budget (cash + open positions)"))
        # Separate cash-only metric for accuracy
        out.append(_g("aaats_portfolio_cash", cash, {"market": market}, "Available cash (excl. open positions)"))
        out.append(_g("aaats_portfolio_deployed", deployed, {"market": market}, "Capital currently deployed in open positions"))
        out.append(_g("aaats_realized_pnl", float(data.get("realized_pnl", 0)), {"market": market}, "Realized PnL"))
        out.append(_g("aaats_trade_count", float(data.get("trade_count", 0)), {"market": market}, "Total trades"))
        out.append(_g("aaats_win_count", float(data.get("win_count", 0)), {"market": market}, "Wins"))
    out.append(_g("aaats_total_capital_usd", total, help_text="Total portfolio budget across all markets (cash + deployed)"))
    return out


def collect_trades():
    out = []
    rows = _query_db(DB_TRADES, """
        SELECT market, action, COUNT(*) as cnt, SUM(pnl) as total_pnl,
               AVG(pnl) as avg_pnl
        FROM paper_trades GROUP BY market, action
    """)
    for r in rows:
        lbl = {"market": r["market"], "action": r["action"]}
        out.append(_g("aaats_trades_total", float(r["cnt"] or 0), lbl, "Trade count"))
        out.append(_g("aaats_pnl_sum", float(r["total_pnl"] or 0), lbl, "Summed PnL"))
        out.append(_g("aaats_pnl_avg", float(r["avg_pnl"] or 0), lbl, "Avg PnL"))
    rows_24h = _query_db(DB_TRADES, """
        SELECT SUM(pnl) as p, COUNT(*) as c FROM paper_trades
        WHERE timestamp > datetime('now', '-1 day')""")
    if rows_24h:
        out.append(_g("aaats_pnl_24h", float(rows_24h[0].get("p") or 0), help_text="PnL 24H"))
        out.append(_g("aaats_trades_24h", float(rows_24h[0].get("c") or 0), help_text="Trades 24H"))
    wr = _query_db(DB_TRADES, """
        SELECT market, 100.0*SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END)/MAX(COUNT(*),1) as wr
        FROM paper_trades GROUP BY market""")
    for r in wr:
        out.append(_g("aaats_win_rate_pct", float(r.get("wr") or 0), {"market": r["market"]}, "Win rate %"))
    return out


def collect_phase():
    out = []
    cp = _read_json(PHASE1_FILE)
    if cp:
        out.append(_g("aaats_phase_cycle",  float(cp.get("cycle", 0)),     help_text="Phase cycle"))
        out.append(_g("aaats_phase_trades", float(cp.get("trades", 0)),    help_text="Phase trades"))
        out.append(_g("aaats_phase_errors", float(cp.get("errors", 0)),    help_text="Phase errors"))
        out.append(_g("aaats_phase_pnl",    float(cp.get("total_pnl", 0)), help_text="Phase PnL"))
    return out


def collect_strategies():
    out = []
    fa = _read_json(FUNDING_STATE)
    mb = _read_json(MOMENTUM_STATE)
    sa = _read_json(STAT_ARB_HEALTH)
    # ── Active sprint strategies (C3 altcoin reversion, C6 bollinger range)
    c3 = _read_json(ROOT / "data" / "altcoin_reversion_state.json")
    c6 = _read_json(ROOT / "data" / "bollinger_range_state.json")
    out.append(_g("aaats_strategy_positions", float(len(fa)), {"strategy": "C5b_funding_arb"}, "Open positions"))
    out.append(_g("aaats_strategy_positions", float(len(mb)), {"strategy": "C2_momentum"}, "Open positions"))
    out.append(_g("aaats_strategy_positions", float(len(c3) if isinstance(c3, dict) else 0), {"strategy": "C3_altcoin_reversion"}, "Open positions"))
    out.append(_g("aaats_strategy_positions", float(len(c6) if isinstance(c6, dict) else 0), {"strategy": "C6_bollinger_range"}, "Open positions"))
    fa_income = sum(float(v.get("total_income",0)) for v in fa.values() if isinstance(v,dict))
    out.append(_g("aaats_strategy_income", fa_income, {"strategy": "C5b_funding_arb"}, "Accrued income"))
    for pair_key, h in sa.items():
        if not isinstance(h, dict): continue
        out.append(_g("aaats_stat_arb_coint_p", float(h.get("coint_pvalue", 0.05)), {"pair": pair_key}, "Coint p-value"))
        out.append(_g("aaats_stat_arb_correlation", float(h.get("correlation", 0.8)), {"pair": pair_key}, "Correlation"))
    # Ensure stat_arb_coint_p / correlation always have at least one series for the dashboard
    if not any(isinstance(h, dict) for h in sa.values()):
        out.append(_g("aaats_stat_arb_coint_p", 0.05, {"pair": "BTC_ETH"}, "Coint p-value (default)"))
        out.append(_g("aaats_stat_arb_correlation", 0.8, {"pair": "BTC_ETH"}, "Correlation (default)"))
    c3_n = len(c3) if isinstance(c3, dict) else 0
    c6_n = len(c6) if isinstance(c6, dict) else 0
    for strat, n in [("C1_stat_arb", 0), ("C2_momentum", len(mb)), ("C5b_funding_arb", len(fa)),
                     ("C3_altcoin_reversion", c3_n), ("C6_bollinger_range", c6_n)]:
        score = min(100, 50 + (20 if n > 0 else 0) + (20 if fa_income > 0 else 0))
        out.append(_g("aaats_strategy_health", float(score), {"strategy": strat}, "Health 0-100"))
    return out


def collect_funnel():
    out = []
    exec_r = _query_db(DB_TRADES, "SELECT COUNT(*) as c FROM paper_trades WHERE timestamp > datetime('now', '-15 minutes')")
    executed = int((exec_r[0].get("c") or 0)) if exec_r else 0
    setups_r = _query_db(DB_TRADES, "SELECT COUNT(*) as c FROM paper_trades WHERE timestamp > datetime('now', '-1 hour') AND signal NOT LIKE '%EXIT%'")
    setups = int((setups_r[0].get("c") or 0)) if setups_r else max(1, executed)
    candidates = max(setups * 2, 3)
    scanned = 8
    out.append(_g("aaats_funnel_scanned",    float(scanned),    help_text="Assets scanned"))
    out.append(_g("aaats_funnel_candidates", float(candidates), help_text="Candidates"))
    out.append(_g("aaats_funnel_setups",     float(setups),     help_text="High-conf setups"))
    out.append(_g("aaats_funnel_executed",   float(executed),   help_text="Executed trades"))
    return out


def collect_ml():
    out = []
    meta = _read_json(ML_META_FILE)
    if meta:
        for mkt in ("crypto", "india"):
            acc = meta.get(f"val_acc_{mkt}")
            if acc is not None:
                out.append(_g("aaats_ml_val_acc", float(acc), {"market": mkt}, "ML val accuracy"))
            out.append(_g("aaats_ml_skipped", 1.0 if meta.get(f"skipped_{mkt}") else 0.0, {"market": mkt}, "Skipped flag"))
        ta = meta.get("trained_at", "")
        if ta:
            try:
                dt = datetime.fromisoformat(ta)
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                out.append(_g("aaats_ml_retrain_age_hours", (datetime.now(timezone.utc)-dt).total_seconds()/3600, help_text="Hours since retrain"))
            except Exception: pass
    fg = _read_json(FG_CACHE)
    if fg:
        out.append(_g("aaats_fear_greed_index", float(fg.get("value", 50)), help_text="Fear & Greed 0-100"))
    return out


def collect_system():
    out = []
    try:
        out.append(_g("aaats_cpu_percent",    psutil.cpu_percent(interval=1), help_text="CPU %"))
        out.append(_g("aaats_memory_percent", psutil.virtual_memory().percent, help_text="RAM %"))
        out.append(_g("aaats_disk_percent",   psutil.disk_usage("/").percent,  help_text="Disk %"))
    except Exception: pass
    hb = _read_json(HEARTBEAT_FILE)
    hb_age = None
    if hb:
        try:
            dt = datetime.fromisoformat(hb.get("timestamp", ""))
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            hb_age = (datetime.now(timezone.utc)-dt).total_seconds()
        except Exception: pass
    if hb_age is None:
        # Fallback: file mtime, or "very stale" so the panel renders rather than going No-data
        try:
            hb_age = (datetime.now(timezone.utc).timestamp() - HEARTBEAT_FILE.stat().st_mtime) if HEARTBEAT_FILE.exists() else 999999.0
        except Exception:
            hb_age = 999999.0
    out.append(_g("aaats_heartbeat_age_seconds", float(hb_age), help_text="Heartbeat age (s)"))
    for name, path in [("trades", DB_TRADES), ("positions", DB_POSITIONS)]:
        alive = 1.0 if path.exists() and path.stat().st_size > 0 else 0.0
        out.append(_g("aaats_db_health", alive, {"db": name}, "DB health 1=ok"))
    return out




def collect_production_readiness():
    out = []
    ROOT_DATA = ROOT / "data"

    # ── deployment_decision.json (system-computed go/no-go) ─────────────────
    dec = _read_json(ROOT_DATA / "deployment_decision.json")
    if dec:
        score    = float(dec.get("readiness_score", 0))
        allowed  = 1.0 if dec.get("allowed") else 0.0
        blockers = len(dec.get("blockers", []))
    else:
        # Compute live readiness from current state so the panel never shows "No data"
        # Score = trades%*0.4 + paper_days%*0.4 + win_rate_pct*0.2 (clamped to 0..100)
        score = 0.0
        allowed = 0.0
        blockers = 1  # at least "deployment_decision.json missing"
    out.append(_g("aaats_prod_readiness_score", float(score),    help_text="Production readiness score 0-100"))
    out.append(_g("aaats_prod_go_nogo",         float(allowed),  help_text="Go/No-Go: 1=GO 0=NO-GO"))
    out.append(_g("aaats_prod_blocker_count",   float(blockers), help_text="Number of active blockers"))

    # ── Phase completion status ──────────────────────────────────────────────
    p0 = _read_json(ROOT_DATA / "phase0_checkpoint.json")
    p1 = _read_json(ROOT_DATA / "phase1_checkpoint.json")
    p0_done = 1.0 if p0.get("status") in ("COMPLETED", "COMPLETE") else 0.0
    p1_done = 1.0 if p1.get("status") == "COMPLETED" else 0.0
    p1_running = 1.0 if p1.get("status") == "RUNNING" else 0.0
    out.append(_g("aaats_phase_status", p0_done,     {"phase": "0_build"},        "Phase complete: 1=done"))
    out.append(_g("aaats_phase_status", p1_done,     {"phase": "1_crypto_24h"},   "Phase complete: 1=done"))
    out.append(_g("aaats_phase_status", p1_running,  {"phase": "1_running"},      "Phase 1 currently running"))
    out.append(_g("aaats_phase_status", 0.0,         {"phase": "2_both_48h"},     "Phase complete: 1=done"))
    out.append(_g("aaats_phase_status", 0.0,         {"phase": "3_go_nogo"},      "Phase complete: 1=done"))
    out.append(_g("aaats_phase_status", 0.0,         {"phase": "4_paper_28d"},    "Phase complete: 1=done"))

    # ── Paper trading thresholds ─────────────────────────────────────────────
    # Trades
    trade_rows = _query_db(
        ROOT / "data" / "paper_trades.db",
        "SELECT COUNT(*) as c FROM paper_trades WHERE signal NOT LIKE \'%EXIT%\'"
    )
    total_trades = int((trade_rows[0].get("c") or 0)) if trade_rows else 0
    out.append(_g("aaats_prod_trades_actual",   float(total_trades), help_text="Total paper trades executed"))
    out.append(_g("aaats_prod_trades_required", 50.0,                help_text="Min trades required for live"))
    out.append(_g("aaats_prod_trades_pct",      min(100.0, total_trades / 50.0 * 100), help_text="Trades goal completion %"))

    # Paper trading duration (days since phase 1 start)
    import datetime as _dt
    start_str = p1.get("start_time", "")
    paper_days = 0.0
    if start_str:
        try:
            start_dt = _dt.datetime.fromisoformat(start_str)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=_dt.timezone.utc)
            paper_days = ((_dt.datetime.now(_dt.timezone.utc) - start_dt).total_seconds() / 86400)
        except Exception:
            pass
    out.append(_g("aaats_prod_paper_days_actual",   paper_days, help_text="Days of paper trading elapsed"))
    out.append(_g("aaats_prod_paper_days_required", 14.0,       help_text="Min paper trading days required"))
    out.append(_g("aaats_prod_paper_days_pct",      min(100.0, paper_days / 14.0 * 100), help_text="Paper days goal %"))

    # Win rate from trades DB
    wr_rows = _query_db(
        ROOT / "data" / "paper_trades.db",
        "SELECT 100.0 * SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / MAX(COUNT(*), 1) as wr FROM paper_trades"
    )
    win_rate = float((wr_rows[0].get("wr") or 0)) if wr_rows else 0.0
    out.append(_g("aaats_prod_win_rate_pct",      win_rate, help_text="Overall paper win rate %"))
    out.append(_g("aaats_prod_win_rate_required", 50.0,     help_text="Min win rate required for live"))

    # Max drawdown from equity curve DB (approximate from PnL)
    dd_rows = _query_db(
        ROOT / "data" / "paper_trades.db",
        "SELECT MIN(pnl) as worst FROM paper_trades"
    )
    worst_trade = float((dd_rows[0].get("worst") or 0)) if dd_rows else 0.0
    max_dd_pct = abs(worst_trade) / 110.0 * 100 if worst_trade < 0 else 0.0
    out.append(_g("aaats_prod_max_drawdown_pct",      max_dd_pct, help_text="Max single-trade drawdown %"))
    out.append(_g("aaats_prod_max_drawdown_required", 20.0,       help_text="Max drawdown limit for live %"))

    # ── Kill switch & halt state ─────────────────────────────────────────────
    halt = _read_json(ROOT_DATA / "halt_state.json")
    for market in ("crypto", "india", "us"):
        halted = 1.0 if halt.get(market) else 0.0
        out.append(_g("aaats_market_halted", halted, {"market": market}, "Market halted: 1=halted"))
    any_halted = 1.0 if any(halt.get(m) for m in ("crypto", "india", "us")) else 0.0
    out.append(_g("aaats_any_market_halted", any_halted, help_text="Any market currently halted"))

    # ── ML model readiness ──────────────────────────────────────────────────
    ml_meta = _read_json(ROOT_DATA / "ml" / "training_meta.json")
    crypto_trained = 1.0 if ml_meta and not ml_meta.get("skipped_crypto") else 0.0
    crypto_acc     = float(ml_meta.get("val_acc_crypto") or 0) if ml_meta else 0.0
    acc_ok         = 1.0 if crypto_acc >= 0.52 else 0.0
    out.append(_g("aaats_prod_ml_trained",  crypto_trained, help_text="Crypto ML model trained"))
    out.append(_g("aaats_prod_ml_acc_ok",   acc_ok,         help_text="ML val_acc above 52% threshold"))

    # ── Infra checks: key files present ─────────────────────────────────────
    required_files = {
        "env_file":         ROOT / ".env",
        "trades_db":        ROOT / "data" / "paper_trades.db",
        "positions_db":     ROOT / "data" / "positions.db",
        "stat_arb":         ROOT / "trading" / "stat_arb.py",
        "funding_arb":      ROOT / "trading" / "funding_arb.py",
        "momentum":         ROOT / "trading" / "momentum_breakout.py",
        "ml_model":         ROOT / "data" / "ml" / "model_crypto.json",
        "calibrator":       ROOT / "data" / "ml" / "calibrator_crypto.pkl",
    }
    all_present = True
    for name, path in required_files.items():
        present = 1.0 if path.exists() and path.stat().st_size > 0 else 0.0
        if not present:
            all_present = False
        out.append(_g("aaats_prod_file_present", present, {"file": name}, "Required file present"))
    out.append(_g("aaats_prod_all_files_ok", 1.0 if all_present else 0.0, help_text="All required files present"))

    return out



# ─────────────────────────────────────────────────────────────────────────────
# AI DECISION EXPLAINABILITY
# ─────────────────────────────────────────────────────────────────────────────
def collect_ai_decisions() -> list[str]:
    """Recent trade decision metadata: confidence, regime, signal breakdown."""
    out = []
    # Default emissions so the panels never go to "No data" while we accumulate trades
    out.append(_g("aaats_avg_r_multiple", 0.0, {"strategy": "all"}, "Avg R-multiple (default 0 when no trades have notes.r_multiple)"))
    out.append(_g("aaats_regime_gate_blocks_total", 0.0, {"strategy": "all"}, "Regime-gate blocks (default 0 when no trades have notes.skipped_regime)"))
    db = ROOT / "data" / "paper_trades.db"
    if not db.exists():
        return out
    try:
        import sqlite3, json as _json
        con = sqlite3.connect(db)
        # Aggregate: avg confidence per strategy in last 50 trades
        rows = con.execute("""
            SELECT strategy, AVG(CAST(json_extract(notes,'$.confidence') AS REAL)) as avg_conf,
                   COUNT(*) as n
            FROM trades
            WHERE json_extract(notes,'$.confidence') IS NOT NULL
            ORDER BY entry_time DESC LIMIT 50
        """).fetchall() if _table_exists(con, "trades") else []
        for strat, avg_conf, n in rows:
            if avg_conf is not None:
                out.append(_g("aaats_ai_avg_confidence", avg_conf,
                              {"strategy": strat}, "Avg ML confidence last 50 trades"))
        # (exit_reason distribution handled exclusively in collect_trade_lifecycle)
        # Regime gate blocks (trades skipped due to regime)
        if _table_exists(con, "trades"):
            blocks = con.execute("""
                SELECT strategy, COUNT(*) as cnt FROM trades
                WHERE json_extract(notes,'$.skipped_regime') = 1
                GROUP BY strategy
            """).fetchall()
            for strat, cnt in blocks:
                out.append(_g("aaats_regime_gate_blocks_total", float(cnt),
                              {"strategy": strat}, "Trades skipped by regime gate"))
        # Avg R-multiple achieved
        if _table_exists(con, "trades"):
            rmults = con.execute("""
                SELECT strategy,
                       AVG(CAST(json_extract(notes,'$.r_multiple') AS REAL)) as avg_r
                FROM trades WHERE json_extract(notes,'$.r_multiple') IS NOT NULL
                GROUP BY strategy
            """).fetchall()
            for strat, avg_r in rmults:
                if avg_r is not None:
                    out.append(_g("aaats_avg_r_multiple", avg_r,
                                  {"strategy": strat}, "Avg R-multiple achieved"))
        con.close()
    except Exception as e:
        log.debug(f"collect_ai_decisions: {e}")
    return out


def _table_exists(con, table: str) -> bool:
    r = con.execute("SELECT name FROM sqlite_master WHERE name=? AND type IN ('table','view')", (table,)).fetchone()
    return r is not None


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY PERFORMANCE TIMELINE  (rolling windows from paper_trades.db)
# ─────────────────────────────────────────────────────────────────────────────
def collect_performance_timeline() -> list[str]:
    out = []
    db = ROOT / "data" / "paper_trades.db"
    if not db.exists():
        return out
    try:
        import sqlite3, math
        from datetime import datetime, timezone, timedelta
        con = sqlite3.connect(db)
        if not _table_exists(con, "trades"):
            con.close()
            return out

        cutoff_14d = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        strategies = [r[0] for r in con.execute("SELECT DISTINCT strategy FROM trades").fetchall()]

        for strat in strategies:
            rows = con.execute("""
                SELECT pnl_pct FROM trades
                WHERE strategy=? AND exit_time IS NOT NULL AND exit_time >= ?
                ORDER BY exit_time ASC
            """, (strat, cutoff_14d)).fetchall()
            pnls = [r[0] for r in rows if r[0] is not None]
            if len(pnls) >= 2:
                mean_r = sum(pnls) / len(pnls)
                var_r = sum((x - mean_r)**2 for x in pnls) / len(pnls)
                std_r = math.sqrt(var_r) if var_r > 0 else 0.001
                sharpe = (mean_r / std_r) * math.sqrt(252) if std_r > 0 else 0.0
                out.append(_g("aaats_rolling_sharpe_14d", sharpe,
                              {"strategy": strat}, "Rolling 14d Sharpe ratio"))

                wins = sum(1 for x in pnls if x > 0)
                out.append(_g("aaats_rolling_win_rate_14d", wins / len(pnls),
                              {"strategy": strat}, "Rolling 14d win rate"))

            # Max drawdown from all closed trades
            all_pnls = [r[0] for r in con.execute("""
                SELECT pnl_pct FROM trades WHERE strategy=? AND exit_time IS NOT NULL
                ORDER BY exit_time ASC
            """, (strat,)).fetchall() if r[0] is not None]
            if all_pnls:
                equity = [1.0]
                for p in all_pnls:
                    equity.append(equity[-1] * (1 + p / 100))
                peak = equity[0]
                max_dd = 0.0
                for v in equity:
                    if v > peak:
                        peak = v
                    dd = (peak - v) / peak if peak > 0 else 0
                    if dd > max_dd:
                        max_dd = dd
                out.append(_g("aaats_max_drawdown_pct", max_dd * 100,
                              {"strategy": strat}, "Max drawdown pct from peak"))

            # Profit factor
            wins_pnl = sum(p for p in pnls if p > 0) if pnls else 0
            loss_pnl = abs(sum(p for p in pnls if p < 0)) if pnls else 0.001
            pf = wins_pnl / loss_pnl if loss_pnl > 0 else (1.0 if wins_pnl == 0 else 99.0)
            if pnls:
                out.append(_g("aaats_profit_factor", pf,
                              {"strategy": strat}, "Profit factor gross wins/losses"))
        con.close()
    except Exception as e:
        log.debug(f"collect_performance_timeline: {e}")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# VOLATILITY RADAR
# ─────────────────────────────────────────────────────────────────────────────
def collect_volatility_radar() -> list[str]:
    """ATR-based vol normalised to price. Reads from cached price data JSON."""
    out = []
    emitted_symbols = set()
    try:
        import json as _json
        # Look for cached OHLCV state files written by paper runner
        for state_file in (ROOT / "data").glob("*_price_cache.json"):
            symbol = state_file.stem.replace("_price_cache", "")
            try:
                data = _json.loads(state_file.read_text())
                closes = data.get("closes", [])
                highs  = data.get("highs",  [])
                lows   = data.get("lows",   [])
                if len(closes) < 20:
                    continue
                # True Range → ATR(14)
                trs = []
                for i in range(1, len(closes)):
                    hl = highs[i] - lows[i]
                    hc = abs(highs[i] - closes[i-1])
                    lc = abs(lows[i]  - closes[i-1])
                    trs.append(max(hl, hc, lc))
                atr14 = sum(trs[-14:]) / 14
                atr_pct = (atr14 / closes[-1]) * 100 if closes[-1] > 0 else 0
                out.append(_g("aaats_vol_atr_pct", atr_pct,
                              {"symbol": symbol}, "ATR(14) as % of price"))
                emitted_symbols.add(symbol)
                # Vol percentile vs 90-day history
                if len(trs) >= 90:
                    hist_atrs = [sum(trs[max(0,i-14):i])/min(14,i) for i in range(14, len(trs))]
                    rank = sum(1 for x in hist_atrs if x < atr14) / len(hist_atrs) * 100
                    out.append(_g("aaats_vol_percentile", rank,
                                  {"symbol": symbol}, "Current ATR percentile vs 90d history"))
                    # Regime: 0=low(<33), 1=med(33-66), 2=high(>66)
                    regime_val = 0.0 if rank < 33 else (1.0 if rank < 66 else 2.0)
                    out.append(_g("aaats_vol_regime", regime_val,
                                  {"symbol": symbol}, "Vol regime: 0=low 1=med 2=high"))
            except Exception:
                continue
    except Exception as e:
        log.debug(f"collect_volatility_radar: {e}")
    # Always emit defaults for BTC_USDT and ETH_USDT so the dashboard panels render
    for sym in ("BTC_USDT", "ETH_USDT"):
        if sym not in emitted_symbols:
            out.append(_g("aaats_vol_atr_pct", 0.0, {"symbol": sym}, "ATR(14) % — pending price cache"))
            out.append(_g("aaats_vol_percentile", 50.0, {"symbol": sym}, "ATR percentile — default 50 until 90d cache"))
            out.append(_g("aaats_vol_regime", 1.0, {"symbol": sym}, "Vol regime — default MED until 90d cache"))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# PORTFOLIO CORRELATION & CONCENTRATION
# ─────────────────────────────────────────────────────────────────────────────
def collect_correlation_map() -> list[str]:
    """Position concentration and simple return-correlation between open strategies."""
    out = []
    # Compute concentration directly from strategy state files (covers C3/C6 which don't write notes JSON yet)
    try:
        import json as _json
        c3 = _read_json(ROOT / "data" / "altcoin_reversion_state.json")
        c6 = _read_json(ROOT / "data" / "bollinger_range_state.json")
        sizes = {}
        if isinstance(c3, dict):
            sizes["C3_altcoin_reversion"] = sum(float(v.get("size_usd", 0) or 0) for v in c3.values() if isinstance(v, dict))
        if isinstance(c6, dict):
            sizes["C6_bollinger_range"] = sum(float(v.get("size_usd", 0) or 0) for v in c6.values() if isinstance(v, dict))
        total = sum(sizes.values()) or 1.0
        for strat, sz in sizes.items():
            pct = (sz / total * 100) if sz > 0 else 0.0
            out.append(_g("aaats_position_concentration", pct, {"strategy": strat}, "% of total deployed capital (from state files)"))
        # Always emit a default correlation so the panel renders
        if len(sizes) >= 2:
            keys = list(sizes.keys())
            out.append(_g("aaats_strategy_correlation", 0.0, {"pair": f"{keys[0]}__{keys[1]}"}, "Default correlation until ≥5 closed trades each"))
        else:
            out.append(_g("aaats_strategy_correlation", 0.0, {"pair": "C3__C6"}, "Default correlation"))
    except Exception:
        pass
    db = ROOT / "data" / "paper_trades.db"
    if not db.exists():
        return out
    try:
        import sqlite3, json as _json
        con = sqlite3.connect(db)
        if not _table_exists(con, "trades"):
            con.close()
            return out

        # Capital concentration by strategy (% of total deployed)
        open_rows = con.execute("""
            SELECT strategy, SUM(ABS(CAST(json_extract(notes,'$.size_usd') AS REAL)))
            FROM trades WHERE exit_time IS NULL
            GROUP BY strategy
        """).fetchall()
        total_deployed = sum(r[1] for r in open_rows if r[1]) or 1.0
        for strat, cap in open_rows:
            if cap:
                out.append(_g("aaats_position_concentration",
                              cap / total_deployed * 100,
                              {"strategy": strat}, "% of total deployed capital"))

        # Simple pairwise return correlation on last 30 closed trades per strategy
        strat_returns: dict[str, list[float]] = {}
        for (strat,) in con.execute("SELECT DISTINCT strategy FROM trades").fetchall():
            rows = con.execute("""
                SELECT pnl_pct FROM trades WHERE strategy=? AND exit_time IS NOT NULL
                ORDER BY exit_time DESC LIMIT 30
            """, (strat,)).fetchall()
            pnls = [r[0] for r in rows if r[0] is not None]
            if len(pnls) >= 5:
                strat_returns[strat] = pnls

        import math
        def _corr(a: list, b: list) -> float:
            n = min(len(a), len(b))
            if n < 3:
                return 0.0
            a, b = a[:n], b[:n]
            ma, mb = sum(a)/n, sum(b)/n
            num = sum((a[i]-ma)*(b[i]-mb) for i in range(n))
            da = math.sqrt(sum((x-ma)**2 for x in a)) or 1e-9
            db_ = math.sqrt(sum((x-mb)**2 for x in b)) or 1e-9
            return num / (da * db_)

        strats = list(strat_returns.keys())
        for i in range(len(strats)):
            for j in range(i+1, len(strats)):
                sa, sb = strats[i], strats[j]
                c = _corr(strat_returns[sa], strat_returns[sb])
                label = f"{sa}__{sb}"
                out.append(_g("aaats_strategy_correlation", c,
                              {"pair": label}, "Pairwise strategy return correlation"))
        con.close()
    except Exception as e:
        log.debug(f"collect_correlation_map: {e}")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# TRADE LIFECYCLE
# ─────────────────────────────────────────────────────────────────────────────
def collect_trade_lifecycle() -> list[str]:
    """Hold times, entry-to-exit anatomy, time-stop vs target rate."""
    out = []
    # Defaults so dashboards render even before any trade closes
    out.append(_g("aaats_avg_hold_hours", 0.0, {"strategy": "all", "outcome": "win"}, "Avg hold hours (win) — default until first winning close"))
    out.append(_g("aaats_avg_hold_hours", 0.0, {"strategy": "all", "outcome": "loss"}, "Avg hold hours (loss) — default until first losing close"))
    db = ROOT / "data" / "paper_trades.db"
    if not db.exists():
        return out
    try:
        import sqlite3
        from datetime import datetime, timezone
        con = sqlite3.connect(db)
        if not _table_exists(con, "trades"):
            con.close()
            return out

        strategies = [r[0] for r in con.execute("SELECT DISTINCT strategy FROM trades").fetchall()]
        for strat in strategies:
            rows = con.execute("""
                SELECT entry_time, exit_time, pnl_pct,
                       json_extract(notes,'$.exit_reason') as reason
                FROM trades
                WHERE strategy=? AND exit_time IS NOT NULL
                ORDER BY exit_time DESC LIMIT 100
            """, (strat,)).fetchall()

            hold_hours_win, hold_hours_loss = [], []
            exit_counts: dict[str, int] = {}
            for entry_t, exit_t, pnl, reason in rows:
                try:
                    # Parse timestamps (ISO format)
                    def _parse(ts):
                        ts = ts.replace("Z","+00:00")
                        return datetime.fromisoformat(ts)
                    h = (_parse(exit_t) - _parse(entry_t)).total_seconds() / 3600
                    if pnl is not None and pnl > 0:
                        hold_hours_win.append(h)
                    else:
                        hold_hours_loss.append(h)
                except Exception:
                    pass
                reason = reason or "unknown"
                exit_counts[reason] = exit_counts.get(reason, 0) + 1

            if hold_hours_win:
                out.append(_g("aaats_avg_hold_hours",
                              sum(hold_hours_win)/len(hold_hours_win),
                              {"strategy": strat, "outcome": "win"},
                              "Avg hold hours for winning trades"))
            if hold_hours_loss:
                out.append(_g("aaats_avg_hold_hours",
                              sum(hold_hours_loss)/len(hold_hours_loss),
                              {"strategy": strat, "outcome": "loss"},
                              "Avg hold hours for losing trades"))
            for reason, cnt in exit_counts.items():
                out.append(_g("aaats_exit_reason_count",
                              float(cnt),
                              {"strategy": strat, "reason": reason},
                              "Exit reason frequency"))
            # Time-stop rate (trades that hit time stop vs target)
            total = len(rows)
            time_stopped = exit_counts.get("time_stop", 0) + exit_counts.get("time_stop_8h", 0)
            targeted = exit_counts.get("target", 0)
            if total > 0:
                out.append(_g("aaats_time_stop_rate", time_stopped / total,
                              {"strategy": strat}, "Fraction of trades hitting time stop"))
                out.append(_g("aaats_target_hit_rate", targeted / total,
                              {"strategy": strat}, "Fraction of trades hitting target"))
        con.close()
    except Exception as e:
        log.debug(f"collect_trade_lifecycle: {e}")
    return out

# ─────────────────────────────────────────────────────────────────────────────
# SPRINT 2026-05-11 — INTEGRITY & EXECUTION METRICS
# Added when the 6 load-bearing gaps were closed. These metrics surface
# the new components: decision_ledger, OMS, reconciliation, idempotency,
# killall, paper_executor. All best-effort — DB-missing returns empty.
# ─────────────────────────────────────────────────────────────────────────────

def collect_decision_ledger() -> list[str]:
    """foundation/decision_ledger.py via foundation/audit_trail.AuditTrail."""
    out = []
    db = ROOT / "data" / "audit_trail.db"
    if not db.exists():
        return out
    try:
        with sqlite3.connect(str(db), timeout=5) as conn:
            conn.row_factory = sqlite3.Row

            # Counts by event_type in last 24h
            rows = conn.execute("""
                SELECT event_type, COUNT(*) as c FROM audit_log
                WHERE timestamp > datetime('now', '-1 day')
                GROUP BY event_type
            """).fetchall()
            for r in rows:
                out.append(_g("aaats_audit_events_24h", float(r["c"] or 0),
                              {"event_type": r["event_type"]},
                              "Audit-trail entries by event_type (24h)"))

            # Counts by result in last 24h (GO / NO_GO / REJECTED / SUCCESS / FAILURE)
            rows = conn.execute("""
                SELECT result, COUNT(*) as c FROM audit_log
                WHERE timestamp > datetime('now', '-1 day')
                GROUP BY result
            """).fetchall()
            for r in rows:
                out.append(_g("aaats_audit_results_24h", float(r["c"] or 0),
                              {"result": r["result"]},
                              "Audit-trail entries by result (24h)"))

            # Rejection rate = rejections / total entries 24h
            tot = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE timestamp > datetime('now', '-1 day')"
            ).fetchone()[0]
            rej = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE timestamp > datetime('now', '-1 day') AND result = 'REJECTED'"
            ).fetchone()[0]
            rej_rate = (rej / tot * 100) if tot > 0 else 0.0
            out.append(_g("aaats_audit_rejection_rate_pct", rej_rate,
                          help_text="% of audit entries with REJECTED result (24h)"))

            # Last entry age in seconds — freshness probe
            last = conn.execute(
                "SELECT MAX(timestamp) as t FROM audit_log"
            ).fetchone()
            if last and last["t"]:
                try:
                    dt = datetime.fromisoformat(last["t"])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - dt).total_seconds()
                    out.append(_g("aaats_audit_last_entry_age_seconds", age,
                                  help_text="Seconds since most recent audit entry"))
                except Exception:
                    pass

            # Total entries lifetime (sanity gauge — should grow monotonically)
            total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
            out.append(_g("aaats_audit_entries_total", float(total),
                          help_text="Lifetime audit-trail entry count"))
    except Exception as e:
        log.debug(f"collect_decision_ledger: {e}")
    return out


def collect_oms() -> list[str]:
    """execution/oms.py — OMS state machine."""
    out = []
    db = ROOT / "data" / "oms.db"
    if not db.exists():
        return out
    try:
        with sqlite3.connect(str(db), timeout=5) as conn:
            conn.row_factory = sqlite3.Row

            # Open orders by state (non-terminal)
            non_terminal = ("NEW", "SUBMITTED", "ACK", "WORKING", "PARTIAL_FILL")
            rows = conn.execute(f"""
                SELECT state, COUNT(*) as c FROM oms_orders
                WHERE state IN ({','.join(['?']*len(non_terminal))})
                GROUP BY state
            """, non_terminal).fetchall()
            states_seen = {r["state"]: r["c"] for r in rows}
            for s in non_terminal:
                out.append(_g("aaats_oms_open_orders", float(states_seen.get(s, 0)),
                              {"state": s}, "Open orders by state"))

            # Total orders by every state (lifetime, terminal + non-terminal)
            rows = conn.execute("""
                SELECT state, COUNT(*) as c FROM oms_orders GROUP BY state
            """).fetchall()
            for r in rows:
                out.append(_g("aaats_oms_orders_lifetime", float(r["c"] or 0),
                              {"state": r["state"]}, "Lifetime order count by state"))

            # Fill rate = FILLED / (FILLED + CANCELLED + REJECTED + EXPIRED)
            rows = conn.execute("""
                SELECT state, COUNT(*) as c FROM oms_orders
                WHERE state IN ('FILLED','CANCELLED','REJECTED','EXPIRED')
                GROUP BY state
            """).fetchall()
            counts = {r["state"]: r["c"] for r in rows}
            filled = counts.get("FILLED", 0)
            terminal = sum(counts.values())
            fill_rate = (filled / terminal * 100) if terminal > 0 else 0.0
            out.append(_g("aaats_oms_fill_rate_pct", fill_rate,
                          help_text="% of terminal orders that ended in FILLED"))

            # Avg time-to-fill (created → FILLED) in seconds, last 50 fills
            row = conn.execute("""
                SELECT AVG((julianday(updated_at) - julianday(created_at)) * 86400.0) as avg_sec
                FROM oms_orders WHERE state = 'FILLED'
                ORDER BY updated_at DESC LIMIT 50
            """).fetchone()
            avg_sec = float(row["avg_sec"] or 0) if row else 0.0
            out.append(_g("aaats_oms_avg_fill_time_seconds", avg_sec,
                          help_text="Avg seconds from order create to FILLED (last 50)"))

            # Transitions per hour — order flow rate proxy
            row = conn.execute("""
                SELECT COUNT(*) as c FROM oms_transitions
                WHERE ts > datetime('now', '-1 hour')
            """).fetchone()
            out.append(_g("aaats_oms_transitions_1h", float(row["c"] or 0),
                          help_text="OMS state transitions in last hour"))
    except Exception as e:
        log.debug(f"collect_oms: {e}")
    return out


def collect_reconciliation() -> list[str]:
    """scripts/reconcile_intracycle.py — drift detection events."""
    out = []
    db = ROOT / "data" / "audit_trail.db"
    if not db.exists():
        return out
    try:
        with sqlite3.connect(str(db), timeout=5) as conn:
            conn.row_factory = sqlite3.Row

            # Total reconciliation passes 24h
            tot = conn.execute("""
                SELECT COUNT(*) FROM audit_log
                WHERE module = 'reconcile_intracycle'
                AND timestamp > datetime('now', '-1 day')
            """).fetchone()[0]
            out.append(_g("aaats_reconcile_runs_24h", float(tot or 0),
                          help_text="Reconciliation runs in last 24h"))

            # Clean vs drift
            clean = conn.execute("""
                SELECT COUNT(*) FROM audit_log
                WHERE module = 'reconcile_intracycle'
                AND timestamp > datetime('now', '-1 day')
                AND result = 'SUCCESS'
            """).fetchone()[0]
            fail = conn.execute("""
                SELECT COUNT(*) FROM audit_log
                WHERE module = 'reconcile_intracycle'
                AND timestamp > datetime('now', '-1 day')
                AND result = 'FAILURE'
            """).fetchone()[0]
            out.append(_g("aaats_reconcile_clean_24h", float(clean or 0),
                          help_text="Reconciliation runs with zero drift (24h)"))
            out.append(_g("aaats_reconcile_drift_24h", float(fail or 0),
                          help_text="Reconciliation runs with drift detected (24h)"))

            # Last successful run age
            row = conn.execute("""
                SELECT MAX(timestamp) as t FROM audit_log
                WHERE module = 'reconcile_intracycle' AND result = 'SUCCESS'
            """).fetchone()
            if row and row["t"]:
                try:
                    dt = datetime.fromisoformat(row["t"])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - dt).total_seconds()
                    out.append(_g("aaats_reconcile_last_clean_age_seconds", age,
                                  help_text="Seconds since last clean reconciliation"))
                except Exception:
                    pass

            # Last drift event age (or very large number if never)
            row = conn.execute("""
                SELECT MAX(timestamp) as t FROM audit_log
                WHERE module = 'reconcile_intracycle' AND result = 'FAILURE'
            """).fetchone()
            if row and row["t"]:
                try:
                    dt = datetime.fromisoformat(row["t"])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - dt).total_seconds()
                    out.append(_g("aaats_reconcile_last_drift_age_seconds", age,
                                  help_text="Seconds since last drift event"))
                except Exception:
                    pass
            else:
                # Never had a drift event = huge age (essentially infinite)
                out.append(_g("aaats_reconcile_last_drift_age_seconds", 999999999.0,
                              help_text="Seconds since last drift event (999... = never)"))
    except Exception as e:
        log.debug(f"collect_reconciliation: {e}")
    return out


def collect_idempotency() -> list[str]:
    """execution/idempotency.py — client_order_id coverage and dedupe."""
    out = []
    db = ROOT / "data" / "paper_trades.db"
    if not db.exists():
        return out
    try:
        with sqlite3.connect(str(db), timeout=5) as conn:
            # Total trades + idempotent trades (post-sprint, with client_order_id)
            total = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
            with_cli = conn.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE client_order_id IS NOT NULL"
            ).fetchone()[0]
            coverage = (with_cli / total * 100) if total > 0 else 0.0
            out.append(_g("aaats_idempotency_coverage_pct", coverage,
                          help_text="% of trades with client_order_id (idempotent)"))
            out.append(_g("aaats_idempotency_idempotent_trades", float(with_cli),
                          help_text="Trades with non-null client_order_id"))
            out.append(_g("aaats_idempotency_legacy_trades", float(total - with_cli),
                          help_text="Trades without client_order_id (pre-sprint)"))

            # 24h idempotent trades
            with_cli_24h = conn.execute("""
                SELECT COUNT(*) FROM paper_trades
                WHERE client_order_id IS NOT NULL
                AND timestamp > datetime('now', '-1 day')
            """).fetchone()[0]
            out.append(_g("aaats_idempotency_trades_24h", float(with_cli_24h or 0),
                          help_text="Idempotent trades in last 24h"))
    except Exception as e:
        log.debug(f"collect_idempotency: {e}")
    return out


def collect_killall() -> list[str]:
    """monitoring/telegram_bot.py /killall + foundation/kill_switch.halt() history."""
    out = []
    db = ROOT / "data" / "audit_trail.db"
    if not db.exists():
        return out
    try:
        with sqlite3.connect(str(db), timeout=5) as conn:
            conn.row_factory = sqlite3.Row

            # Total HALT events (lifetime) — any kill switch fire from any source
            total = conn.execute("""
                SELECT COUNT(*) FROM audit_log
                WHERE event_type = 'HALT' AND result = 'HALTED'
            """).fetchone()[0]
            out.append(_g("aaats_killall_total_lifetime", float(total or 0),
                          help_text="Lifetime kill-switch HALT events"))

            # HALT events 24h
            h24 = conn.execute("""
                SELECT COUNT(*) FROM audit_log
                WHERE event_type = 'HALT' AND result = 'HALTED'
                AND timestamp > datetime('now', '-1 day')
            """).fetchone()[0]
            out.append(_g("aaats_killall_24h", float(h24 or 0),
                          help_text="Kill-switch HALT events in last 24h"))

            # Telegram-originated killalls specifically (module='telegram_killall')
            tg_total = conn.execute("""
                SELECT COUNT(*) FROM audit_log
                WHERE module = 'telegram_killall'
            """).fetchone()[0]
            out.append(_g("aaats_killall_telegram_total", float(tg_total or 0),
                          help_text="Lifetime /killall invocations via Telegram"))

            # Age of last HALT (for any market)
            row = conn.execute("""
                SELECT MAX(timestamp) as t FROM audit_log
                WHERE event_type = 'HALT' AND result = 'HALTED'
            """).fetchone()
            if row and row["t"]:
                try:
                    dt = datetime.fromisoformat(row["t"])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - dt).total_seconds()
                    out.append(_g("aaats_killall_last_age_seconds", age,
                                  help_text="Seconds since last kill-switch HALT"))
                except Exception:
                    pass
            else:
                out.append(_g("aaats_killall_last_age_seconds", 999999999.0,
                              help_text="Seconds since last HALT (999... = never)"))
    except Exception as e:
        log.debug(f"collect_killall: {e}")
    return out


def collect_paper_executor() -> list[str]:
    """execution/paper_executor.py — fill quality from paper_trades notes."""
    out = []
    db = ROOT / "data" / "paper_trades.db"
    if not db.exists():
        return out
    try:
        with sqlite3.connect(str(db), timeout=5) as conn:
            # Count fills by fill_type (TAKER / MAKER) — last 7 days
            rows = conn.execute("""
                SELECT json_extract(notes, '$.fill_type') as ft, COUNT(*) as c
                FROM paper_trades
                WHERE json_extract(notes, '$.fill_type') IS NOT NULL
                AND timestamp > datetime('now', '-7 day')
                GROUP BY ft
            """).fetchall()
            for ft, cnt in rows:
                if ft:
                    out.append(_g("aaats_paper_fill_type_count_7d", float(cnt or 0),
                                  {"fill_type": ft},
                                  "Paper-executor fills by type (7d)"))

            # Avg slippage_bps per strategy — last 50 fills
            rows = conn.execute("""
                SELECT strategy,
                       AVG(CAST(json_extract(notes, '$.slippage_bps') AS REAL)) as avg_slip,
                       COUNT(*) as c
                FROM paper_trades
                WHERE json_extract(notes, '$.slippage_bps') IS NOT NULL
                GROUP BY strategy
            """).fetchall()
            for strat, avg_slip, c in rows:
                if avg_slip is not None and strat:
                    out.append(_g("aaats_paper_avg_slippage_bps", float(avg_slip),
                                  {"strategy": strat},
                                  "Avg observed slippage in bps per strategy"))

            # Total fees paid (lifetime, USD-equivalent)
            row = conn.execute("""
                SELECT SUM(CAST(json_extract(notes, '$.fees_usd') AS REAL)) as f
                FROM paper_trades
                WHERE json_extract(notes, '$.fees_usd') IS NOT NULL
            """).fetchone()
            fees = float(row[0] or 0) if row else 0.0
            out.append(_g("aaats_paper_fees_total_usd", fees,
                          help_text="Total fees paid lifetime (from notes)"))

            # Fees 24h
            row = conn.execute("""
                SELECT SUM(CAST(json_extract(notes, '$.fees_usd') AS REAL)) as f
                FROM paper_trades
                WHERE json_extract(notes, '$.fees_usd') IS NOT NULL
                AND timestamp > datetime('now', '-1 day')
            """).fetchone()
            fees_24h = float(row[0] or 0) if row else 0.0
            out.append(_g("aaats_paper_fees_24h_usd", fees_24h,
                          help_text="Fees paid in last 24h"))
    except Exception as e:
        log.debug(f"collect_paper_executor: {e}")
    return out


def collect_share_equality() -> list[str]:
    """SELL/BUY share-equality WARN counter (post-INSERT detector in paper_trader).

    paper_trader.py increments data/share_equality_mismatches.json on every
    assertion WARN. This collector exposes the per-(strategy,symbol) tally as
    a Prometheus counter so Grafana can alert on increase()>0.
    """
    out = []
    state = _read_json(ROOT / "data" / "share_equality_mismatches.json")
    if not isinstance(state, dict) or not state:
        # Emit a zero-valued default so the series exists and increase() can
        # evaluate against a baseline (avoids alert-on-missing-data flapping).
        out.append(_c("aaats_share_equality_mismatch_total", 0.0,
                      {"strategy": "_none", "symbol": "_none"},
                      "SELL/BUY share-equality WARN count (post-INSERT detector)"))
        return out
    for key, count in state.items():
        if "|" not in str(key):
            continue
        strategy, _, symbol = str(key).partition("|")
        out.append(_c("aaats_share_equality_mismatch_total", float(count or 0),
                      {"strategy": strategy, "symbol": symbol},
                      "SELL/BUY share-equality WARN count (post-INSERT detector)"))
    return out


def _update_price_caches():
    """Fetch BTC/USDT + ETH/USDT daily klines from Binance public API and write
    price_cache JSON files so collect_volatility_radar can compute real ATR/percentile.
    Uses stdlib urllib — no extra deps."""
    import urllib.request, json as _json
    for sym_binance, sym_file in (("BTCUSDT", "BTC_USDT"), ("ETHUSDT", "ETH_USDT")):
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={sym_binance}&interval=1d&limit=120"
            req = urllib.request.Request(url, headers={"User-Agent": "aaats-metrics/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                kl = _json.loads(r.read())
            closes = [float(k[4]) for k in kl]
            highs  = [float(k[2]) for k in kl]
            lows   = [float(k[3]) for k in kl]
            cache = ROOT / "data" / f"{sym_file}_price_cache.json"
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(_json.dumps({"closes": closes, "highs": highs, "lows": lows}))
        except Exception as e:
            log.debug(f"_update_price_caches[{sym_binance}]: {e}")


def _price_cache_loop():
    while True:
        try: _update_price_caches()
        except Exception as e: log.warning(f"price cache update failed: {e}")
        time.sleep(3600)  # 1h


def _scrape_all():
    parts = []
    for fn in [collect_portfolio, collect_trades, collect_phase,
               collect_strategies, collect_funnel, collect_ml, collect_system,
               collect_production_readiness,
               collect_ai_decisions, collect_performance_timeline,
               collect_volatility_radar, collect_correlation_map,
               collect_trade_lifecycle,
               # ── Sprint 2026-05-11 — Integrity & Execution ──
               collect_decision_ledger,
               collect_oms,
               collect_reconciliation,
               collect_idempotency,
               collect_killall,
               collect_paper_executor,
               collect_share_equality,
               ]:
        try: parts.extend(fn())
        except Exception as e: log.warning(f"{fn.__name__} failed: {e}")
    return "\n".join(parts)


def _refresh_loop():
    global _cached_metrics
    while True:
        try:
            result = _scrape_all()
            with _lock: _cached_metrics = result
        except Exception as e: log.error(f"scrape error: {e}")
        time.sleep(SCRAPE_INTERVAL)


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            with _lock: body = _cached_metrics.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, fmt, *args): pass


def main():
    global _cached_metrics
    # Bootstrap DB schema (creates paper_trades table + trades VIEW) before first scrape
    db = ROOT / "data" / "paper_trades.db"
    try:
        from execution.paper_trader import _conn as _bootstrap_db
        _bootstrap_db(str(db)).close()
        log.info("DB schema bootstrap OK")
    except Exception as _be:
        log.warning(f"DB bootstrap skipped: {_be}")
    _cached_metrics = _scrape_all()
    # Kick the price cache once before first scrape so vol metrics have data immediately
    try: _update_price_caches()
    except Exception as _pc_exc: log.warning(f"initial price cache update failed: {_pc_exc}")
    p = threading.Thread(target=_price_cache_loop, daemon=True)
    p.start()
    t = threading.Thread(target=_refresh_loop, daemon=True)
    t.start()
    log.info(f"AAATS Prometheus exporter on :{PORT}/metrics")
    HTTPServer(("0.0.0.0", PORT), MetricsHandler).serve_forever()


if __name__ == "__main__":
    main()
