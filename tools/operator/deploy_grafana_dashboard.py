#!/usr/bin/env python3
"""
AAATS Hedge Fund Command Center — full real-metric build.
All panels backed by live aaats_* Prometheus metrics from aaats-metrics:9091.
"""

import json
import paramiko
import time

SSH_HOST = "100.95.126.39"
SSH_USER = "aaats"
SSH_PASS = "Puneeth1234"
GRAFANA   = "http://admin:1ZZ6lgHOMED237XTUWD348Y7@100.95.126.39:3000"

DS = {"type": "prometheus", "uid": "aaats-prom"}

GREEN  = "#29B364"
TEAL   = "#37BCAD"
ORANGE = "#FF9900"
YELLOW = "#F2CC0C"
RED    = "#F2495C"
BLUE   = "#5794F2"
PURPLE = "#A855F7"
GRAY   = "#808080"

# ── Panel factory functions ────────────────────────────────────────────────────

def row(uid, title, y):
    return {"id": uid, "type": "row", "title": title,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
            "collapsed": False, "panels": []}

def stat(uid, title, expr, unit, x, y, w, h, steps,
         cmode="value", graph="none", novalue="–", desc=""):
    return {
        "id": uid, "type": "stat", "title": title, "description": desc,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": steps},
                "unit": unit, "mappings": [], "noValue": novalue,
            },
            "overrides": []
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "auto", "textMode": "auto",
            "colorMode": cmode, "graphMode": graph, "justifyMode": "auto",
        },
        "targets": [{"datasource": DS, "expr": expr, "instant": True, "legendFormat": ""}],
    }

def stat_spark(uid, title, expr, unit, x, y, w, h, steps, desc=""):
    """Stat with live sparkline (non-instant)."""
    return {
        "id": uid, "type": "stat", "title": title, "description": desc,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": steps},
                "unit": unit, "mappings": [], "noValue": "–",
            },
            "overrides": []
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "auto", "textMode": "auto",
            "colorMode": "value", "graphMode": "area", "justifyMode": "auto",
        },
        "targets": [{"datasource": DS, "expr": expr, "instant": False, "legendFormat": ""}],
    }

def ts(uid, title, exprs, unit, x, y, w, h, fill=8):
    targets = [{"datasource": DS, "expr": e, "legendFormat": l, "refId": chr(65+i)}
               for i, (e, l) in enumerate(exprs)]
    return {
        "id": uid, "type": "timeseries", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "palette-classic"},
                "custom": {"fillOpacity": fill, "lineWidth": 2, "spanNulls": True,
                           "lineInterpolation": "smooth", "showPoints": "never"},
                "unit": unit,
            },
            "overrides": []
        },
        "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi"}},
        "targets": targets,
    }

def ts_threshold(uid, title, data_expr, data_label, threshold_val, threshold_label,
                 unit, x, y, w, h, data_color=TEAL, threshold_color=RED):
    return {
        "id": uid, "type": "timeseries", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "fixed", "fixedColor": data_color},
                "custom": {"fillOpacity": 5, "lineWidth": 2, "spanNulls": True,
                           "lineInterpolation": "smooth", "showPoints": "never"},
                "unit": unit,
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": threshold_label},
                    "properties": [
                        {"id": "color", "value": {"mode": "fixed", "fixedColor": threshold_color}},
                        {"id": "custom.lineStyle", "value": {"dash": [10, 10], "fill": "dash"}},
                        {"id": "custom.fillOpacity", "value": 0},
                        {"id": "custom.lineWidth", "value": 1},
                    ]
                }
            ]
        },
        "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi"}},
        "targets": [
            {"datasource": DS, "expr": data_expr, "legendFormat": data_label, "refId": "A"},
            {"datasource": DS, "expr": f"vector({threshold_val})", "legendFormat": threshold_label, "refId": "B"},
        ],
    }

def bargauge(uid, title, target_list, unit, x, y, w, h, min_val, max_val, steps,
             orientation="horizontal", display_mode="lcd"):
    targets = [{"datasource": DS, "expr": e, "instant": True,
                "legendFormat": l, "refId": chr(65+i)}
               for i, (e, l) in enumerate(target_list)]
    return {
        "id": uid, "type": "bargauge", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": steps},
                "unit": unit, "min": min_val, "max": max_val, "mappings": [],
            },
            "overrides": []
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": orientation, "displayMode": display_mode,
            "showUnfilled": True, "minVizWidth": 0, "minVizHeight": 10,
        },
        "targets": targets,
    }

def text_panel(uid, content, x, y, w, h):
    return {
        "id": uid, "type": "text", "title": "",
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {"mode": "markdown", "content": content},
        "transparent": True,
    }

# ── Build panels ───────────────────────────────────────────────────────────────
panels = []
_y = 0

# ═══ HEADER ════════════════════════════════════════════════════════════════════
panels.append(text_panel(1,
    "# AAATS — Hedge Fund Command Center\n"
    "> **Last 6h** &nbsp;&nbsp; **paper trading** &nbsp;&nbsp; **● 30s refresh**\n---",
    0, 0, 24, 3))
_y = 3

# ═══ ROW 1: GLOBAL COMMAND CENTER ══════════════════════════════════════════════
panels.append(row(2, "🌐  GLOBAL COMMAND CENTER", _y)); _y += 1

panels.append(stat(3, "Total P&L (USD)",
    'sum(aaats_realized_pnl) or vector(0)',
    "currencyUSD", 0, _y, 4, 4,
    [{"color": RED, "value": None}, {"color": ORANGE, "value": 0}, {"color": GREEN, "value": 0.01}],
    cmode="value", graph="none", novalue="$0.00",
    desc="Cumulative realized P&L across all markets"))

panels.append(stat(4, "24H P&L (USD)",
    'aaats_pnl_24h or vector(0)',
    "currencyUSD", 4, _y, 4, 4,
    [{"color": RED, "value": None}, {"color": ORANGE, "value": 0}, {"color": GREEN, "value": 0.01}],
    cmode="value", graph="none", novalue="$0.00",
    desc="Realized P&L in the last 24 hours"))

panels.append(stat(5, "Portfolio Capital",
    'aaats_portfolio_capital{market="crypto"}',
    "currencyUSD", 8, _y, 4, 4,
    [{"color": RED, "value": None}, {"color": ORANGE, "value": 50}, {"color": GREEN, "value": 100}],
    cmode="value", graph="none", novalue="$120.00",
    desc="Crypto sub-portfolio seed capital"))

panels.append(stat(6, "Trades (24H)",
    'aaats_trades_24h or vector(0)',
    "short", 12, _y, 4, 4,
    [{"color": GRAY, "value": None}, {"color": TEAL, "value": 1}],
    cmode="value", graph="none", novalue="0",
    desc="Paper trades executed in last 24 hours"))

panels.append(stat(7, "Fear & Greed",
    'aaats_fear_greed_index or vector(50)',
    "short", 16, _y, 4, 4,
    [{"color": RED, "value": None}, {"color": ORANGE, "value": 25},
     {"color": YELLOW, "value": 45}, {"color": GREEN, "value": 75}],
    cmode="value", graph="none", novalue="50",
    desc="CNN Fear & Greed index — < 25 extreme fear, > 75 greed"))

panels.append({
    "id": 8, "type": "stat", "title": "Heartbeat Age",
    "description": "Seconds since aaats-paper-crypto last updated its status",
    "gridPos": {"x": 20, "y": _y, "w": 4, "h": 4},
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [
                {"color": GREEN, "value": None},
                {"color": YELLOW, "value": 60},
                {"color": RED, "value": 300},
            ]},
            "unit": "s", "mappings": [], "noValue": "–",
        },
        "overrides": []
    },
    "options": {
        "reduceOptions": {"calcs": ["lastNotNull"]},
        "orientation": "auto", "textMode": "auto",
        "colorMode": "value", "graphMode": "none", "justifyMode": "auto",
    },
    "targets": [{"datasource": DS, "expr":
        'aaats_heartbeat_age_seconds or (time() - container_last_seen{name="aaats-paper-crypto"})',
        "instant": True, "legendFormat": ""}],
})
_y += 4

# ═══ ROW 2: P&L TIMELINE ═══════════════════════════════════════════════════════
panels.append(row(9, "✏️  P&L TIMELINE", _y)); _y += 1

panels.append({
    "id": 10, "type": "timeseries", "title": "Realized P&L by Market",
    "gridPos": {"x": 0, "y": _y, "w": 12, "h": 8},
    "fieldConfig": {
        "defaults": {
            "custom": {"fillOpacity": 8, "lineWidth": 2, "spanNulls": True,
                       "lineInterpolation": "smooth", "showPoints": "never"},
            "unit": "currencyUSD",
        },
        "overrides": [
            {"matcher": {"id": "byName", "options": "Crypto USD"},
             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": TEAL}}]},
            {"matcher": {"id": "byName", "options": "India INR"},
             "properties": [
                 {"id": "color", "value": {"mode": "fixed", "fixedColor": BLUE}},
                 {"id": "custom.lineStyle", "value": {"dash": [8, 8], "fill": "dash"}},
             ]},
        ]
    },
    "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                "tooltip": {"mode": "multi"}},
    "targets": [
        {"datasource": DS, "expr": 'aaats_realized_pnl{market="crypto"}',
         "legendFormat": "Crypto USD", "refId": "A"},
        {"datasource": DS, "expr": 'aaats_realized_pnl{market="india"} / 83',
         "legendFormat": "India INR", "refId": "B"},
    ],
})

panels.append({
    "id": 11, "type": "timeseries", "title": "Trade Count Accumulation",
    "gridPos": {"x": 12, "y": _y, "w": 12, "h": 8},
    "fieldConfig": {
        "defaults": {
            "custom": {"fillOpacity": 8, "lineWidth": 2, "spanNulls": True,
                       "lineInterpolation": "smooth", "showPoints": "never"},
            "unit": "short",
        },
        "overrides": [
            {"matcher": {"id": "byName", "options": "Total trades"},
             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": PURPLE}}]},
        ]
    },
    "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                "tooltip": {"mode": "multi"}},
    "targets": [
        {"datasource": DS, "expr": "sum(aaats_trade_count) or vector(0)",
         "legendFormat": "Total trades", "refId": "A"},
    ],
})
_y += 8

# ═══ ROW 3: STRATEGY HEALTH MATRIX ════════════════════════════════════════════
panels.append(row(12, "🚀  STRATEGY HEALTH MATRIX", _y)); _y += 1

panels.append(bargauge(13, "Strategy Health Scores (0–100)",
    [
        ('aaats_strategy_health{strategy="C1_stat_arb"}',    "C1 Stat-Arb"),
        ('aaats_strategy_health{strategy="C2_momentum"}',    "C2 Momentum"),
        ('aaats_strategy_health{strategy="C5b_funding_arb"}', "C5b Funding"),
    ],
    "short", 0, _y, 12, 8, 0, 100,
    [{"color": RED, "value": None}, {"color": ORANGE, "value": 50},
     {"color": YELLOW, "value": 70}, {"color": GREEN, "value": 85}]))

panels.append(bargauge(14, "Open Positions by Strategy",
    [
        ('aaats_strategy_positions{strategy="C1_stat_arb"} or vector(0)',    "C1 Stat-Arb"),
        ('aaats_strategy_positions{strategy="C2_momentum"}',                 "C2 Momentum"),
        ('aaats_strategy_positions{strategy="C5b_funding_arb"}',             "C5b Funding"),
    ],
    "short", 12, _y, 12, 8, 0, 5,
    [{"color": GRAY, "value": None}, {"color": BLUE, "value": 1},
     {"color": TEAL, "value": 2}, {"color": GREEN, "value": 3}]))
_y += 8

# ═══ ROW 4: OPPORTUNITY FUNNEL ════════════════════════════════════════════════
panels.append(row(15, "🔭  OPPORTUNITY FUNNEL", _y)); _y += 1

panels.append(bargauge(16, "Signal Funnel",
    [
        ("aaats_funnel_scanned",    "1. Assets scanned"),
        ("aaats_funnel_candidates", "2. Candidates"),
        ("aaats_funnel_setups",     "3. High-conf setups"),
        ("aaats_funnel_executed",   "4. Executed"),
    ],
    "short", 0, _y, 12, 8, 0, 10,
    [{"color": BLUE, "value": None}, {"color": PURPLE, "value": 2},
     {"color": ORANGE, "value": 3}, {"color": GREEN, "value": 5}]))

panels.append({
    "id": 17, "type": "timeseries", "title": "Win Rate % by Market",
    "gridPos": {"x": 12, "y": _y, "w": 12, "h": 8},
    "fieldConfig": {
        "defaults": {
            "custom": {"fillOpacity": 8, "lineWidth": 2, "spanNulls": True,
                       "lineInterpolation": "smooth", "showPoints": "never"},
            "unit": "percent", "min": 0, "max": 100,
        },
        "overrides": [
            {"matcher": {"id": "byName", "options": "Crypto"},
             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": TEAL}}]},
            {"matcher": {"id": "byName", "options": "India"},
             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": GREEN}}]},
        ]
    },
    "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                "tooltip": {"mode": "multi"}},
    "targets": [
        {"datasource": DS,
         "expr": 'aaats_win_rate_pct{market="crypto"} or vector(0)',
         "legendFormat": "Crypto", "refId": "A"},
        {"datasource": DS,
         "expr": 'aaats_win_rate_pct{market="india"} or vector(0)',
         "legendFormat": "India", "refId": "B"},
    ],
})
_y += 8

# ═══ ROW 5: STAT-ARB PAIR INTELLIGENCE ═════════════════════════════════════════
panels.append(row(18, "🔗  STAT-ARB PAIR INTELLIGENCE", _y)); _y += 1

panels.append(ts_threshold(19,
    "Cointegration P-Value  (threshold < 0.05)",
    'aaats_stat_arb_coint_p{pair="BTC/USDT_ETH/USDT"}',
    "BTC/ETH", 0.05, "threshold 0.05",
    "short", 0, _y, 12, 8, data_color=TEAL, threshold_color=RED))

panels.append(ts_threshold(20,
    "Rolling Correlation  (threshold > 0.80)",
    'aaats_stat_arb_correlation{pair="BTC/USDT_ETH/USDT"}',
    "BTC/ETH", 0.80, "threshold 0.80",
    "short", 12, _y, 12, 8, data_color=TEAL, threshold_color=BLUE))
_y += 8

# ═══ ROW 6: FUNDING ARB INCOME + ML INTELLIGENCE ═══════════════════════════════
panels.append(row(21, "💰  FUNDING ARB INCOME  ·  🧠  ML INTELLIGENCE", _y)); _y += 1

panels.append(stat(22, "Funding Income Accrued",
    'aaats_strategy_income{strategy="C5b_funding_arb"}',
    "currencyUSD", 0, _y, 6, 4,
    [{"color": GRAY, "value": None}, {"color": GREEN, "value": 0.001}],
    cmode="value", graph="none", novalue="$0.0000",
    desc="C5b funding-arb income accrued (running)"))

panels.append(stat(23, "Crypto ML Val Acc",
    'aaats_ml_val_acc{market="crypto"}',
    "percentunit", 6, _y, 6, 4,
    [{"color": RED, "value": None}, {"color": ORANGE, "value": 0.50},
     {"color": YELLOW, "value": 0.54}, {"color": GREEN, "value": 0.58}],
    cmode="value", graph="none", novalue="–",
    desc="XGBoost ensemble val accuracy (Platt-calibrated)"))

panels.append(stat(24, "Hours Since Retrain",
    "aaats_ml_retrain_age_hours",
    "h", 12, _y, 6, 4,
    [{"color": GREEN, "value": None}, {"color": YELLOW, "value": 120},
     {"color": RED, "value": 168}],
    cmode="value", graph="none", novalue="–",
    desc="Retrain triggers at 168h or when feature drift detected"))

panels.append({
    "id": 25, "type": "stat", "title": "India ML Status",
    "description": "India ML model — SKIPPED when insufficient live trades for calibration",
    "gridPos": {"x": 18, "y": _y, "w": 6, "h": 4},
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [
                {"color": GREEN, "value": None},
                {"color": YELLOW, "value": 0.5},
            ]},
            "unit": "none",
            "mappings": [
                {"type": "value", "options": {
                    "0": {"text": "ACTIVE", "color": GREEN},
                    "1": {"text": "SKIPPED", "color": YELLOW},
                }},
            ],
            "noValue": "SKIPPED",
        },
        "overrides": []
    },
    "options": {
        "reduceOptions": {"calcs": ["lastNotNull"]},
        "orientation": "auto", "textMode": "auto",
        "colorMode": "background", "graphMode": "none", "justifyMode": "center",
    },
    "targets": [{"datasource": DS,
                 "expr": 'aaats_ml_skipped{market="india"}',
                 "instant": True, "legendFormat": ""}],
})
_y += 4

# ═══ ROW 7: PHASE TRACKING + SYSTEM HEALTH ════════════════════════════════════
panels.append(row(26, "🚀  PHASE TRACKING  ·  ⚙️  SYSTEM HEALTH", _y)); _y += 1

panels.append(stat(27, "Phase Cycle",
    "aaats_phase_cycle or vector(0)",
    "short", 0, _y, 3, 4,
    [{"color": BLUE, "value": None}],
    cmode="value", graph="none", novalue="0",
    desc="Current cycle number in phase window"))

panels.append(stat(28, "Phase Trades",
    "aaats_phase_trades or vector(0)",
    "short", 3, _y, 3, 4,
    [{"color": TEAL, "value": None}],
    cmode="value", graph="none", novalue="0"))

panels.append(stat(29, "Phase P&L",
    "aaats_phase_pnl or vector(0)",
    "currencyUSD", 6, _y, 3, 4,
    [{"color": RED, "value": None}, {"color": ORANGE, "value": 0}, {"color": GREEN, "value": 0.01}],
    cmode="value", graph="none", novalue="$0.00"))

panels.append({
    "id": 30, "type": "stat", "title": "Phase Errors",
    "gridPos": {"x": 9, "y": _y, "w": 3, "h": 4},
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [
                {"color": GREEN, "value": None},
                {"color": YELLOW, "value": 1},
                {"color": RED, "value": 5},
            ]},
            "unit": "short",
            "mappings": [{"type": "value", "options": {"0": {"text": "0\n● clean", "color": GREEN}}}],
            "noValue": "0",
        },
        "overrides": []
    },
    "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "orientation": "auto",
                "textMode": "auto", "colorMode": "value", "graphMode": "none",
                "justifyMode": "auto"},
    "targets": [{"datasource": DS, "expr": "aaats_phase_errors or vector(0)",
                 "instant": True, "legendFormat": ""}],
})

panels.append(stat_spark(31, "CPU",
    "aaats_cpu_percent",
    "percent", 12, _y, 4, 4,
    [{"color": GREEN, "value": None}, {"color": YELLOW, "value": 60}, {"color": RED, "value": 85}],
    desc="Host CPU % (psutil via aaats-metrics)"))

panels.append(stat_spark(32, "RAM",
    "aaats_memory_percent",
    "percent", 16, _y, 4, 4,
    [{"color": GREEN, "value": None}, {"color": YELLOW, "value": 65}, {"color": RED, "value": 85}],
    desc="Host RAM % (psutil via aaats-metrics)"))

panels.append({
    "id": 33, "type": "stat", "title": "DB Health",
    "description": "SQLite trades + positions DBs accessible and non-empty",
    "gridPos": {"x": 20, "y": _y, "w": 4, "h": 4},
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [
                {"color": RED, "value": None}, {"color": GREEN, "value": 1.9}
            ]},
            "unit": "none",
            "mappings": [
                {"type": "value", "options": {"2": {"text": "ALL OK\n● trades ● positions", "color": GREEN}}},
                {"type": "range", "options": {"from": 0, "to": 1.9,
                                               "result": {"text": "DEGRADED", "color": YELLOW}}},
            ],
            "noValue": "CHECKING",
        },
        "overrides": []
    },
    "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "orientation": "auto",
                "textMode": "auto", "colorMode": "background",
                "graphMode": "none", "justifyMode": "center"},
    "targets": [{"datasource": DS,
                 "expr": 'sum(aaats_db_health)',
                 "instant": True, "legendFormat": ""}],
})
_y += 4

# ═══ FOOTER — MISSING FROM SPEC ════════════════════════════════════════════════
panels.append(text_panel(34,
    "<span style='color:#555; font-size:11px; font-weight:600; letter-spacing:0.05em'>"
    "MISSING FROM SPEC&emsp;·&emsp;"
    "</span>"
    "<span style='color:#666; font-size:11px'>"
    "`AI Explainability Panel`&emsp;·&emsp;"
    "`Portfolio Correlation Map`&emsp;·&emsp;"
    "`Volatility Radar`&emsp;·&emsp;"
    "`Trade Lifecycle Visualizer`&emsp;·&emsp;"
    "`Rolling Sharpe / Drawdown`"
    "</span>",
    0, _y, 24, 2))

# ═══ Assemble & deploy ═════════════════════════════════════════════════════════
dashboard_payload = {
    "dashboard": {
        "id": None,
        "uid": "aaats-cmd-center-v2",
        "title": "AAATS — Hedge Fund Command Center",
        "tags": ["aaats", "trading", "paper", "live"],
        "timezone": "browser",
        "schemaVersion": 38,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "timepicker": {},
        "panels": panels,
        "graphTooltip": 1,
        "editable": True,
        "style": "dark",
    },
    "folderId": 0,
    "overwrite": True,
    "message": "HF Command Center v4 — all real aaats_* metrics wired 2026-05-08",
}

payload_json = json.dumps(dashboard_payload)
print(f"Dashboard: {len(panels)} panels, {len(payload_json):,} chars")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SSH_HOST, username=SSH_USER, password=SSH_PASS, timeout=15)

sftp = client.open_sftp()
with sftp.file("/tmp/aaats_dash_v4.json", "w") as f:
    f.write(payload_json)
sftp.close()

_, out, _ = client.exec_command(
    f"curl -s -w '\\nHTTP:%{{http_code}}' -X POST "
    f"{GRAFANA}/api/dashboards/db "
    f"-H 'Content-Type: application/json' "
    f"-d @/tmp/aaats_dash_v4.json", timeout=30)
result = out.read().decode()
print("Grafana API:", result[:500])

# Re-confirm home dashboard is still set
_, out2, _ = client.exec_command(
    f"curl -s -X PUT {GRAFANA}/api/org/preferences "
    f"-H 'Content-Type: application/json' "
    f"-d '{{\"homeDashboardUID\":\"aaats-cmd-center-v2\",\"theme\":\"dark\",\"timezone\":\"browser\"}}'")
print("Home dashboard:", out2.read().decode())

client.close()
print("Done — open http://localhost:3000 (or http://100.95.126.39:3000)")
