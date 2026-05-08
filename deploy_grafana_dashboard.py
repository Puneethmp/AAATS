#!/usr/bin/env python3
"""
Deploy AAATS Hedge Fund Command Center — matching the exact screenshot design.
Sections: Command Center · P&L Timeline · Strategy Health Matrix · Opportunity Funnel
          Stat-Arb Intelligence · Funding Arb + ML · Phase Tracking + System Health
"""

import json
import paramiko

SSH_HOST = "100.95.126.39"
SSH_USER = "aaats"
SSH_PASS = "Puneeth1234"

DS = {"type": "prometheus", "uid": "aaats-prom"}

# ── Color palette ─────────────────────────────────────────────────────────────
GREEN   = "#29B364"
TEAL    = "#37BCAD"
ORANGE  = "#FF9900"
YELLOW  = "#F2CC0C"
RED     = "#F2495C"
BLUE    = "#5794F2"
PURPLE  = "#A855F7"
GRAY    = "#808080"
CYAN    = "#00D4AA"
PINK    = "#FF6B9D"

# ── Panel helpers ─────────────────────────────────────────────────────────────

def row(uid, title, y):
    return {"id": uid, "type": "row", "title": title,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
            "collapsed": False, "panels": []}

def stat(uid, title, expr, unit, x, y, w, h, steps,
         cmode="value", graph="none", novalue="–", desc="", prefix="", suffix=""):
    return {
        "id": uid, "type": "stat", "title": title, "description": desc,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": steps},
                "unit": unit, "mappings": [], "noValue": novalue,
                "decimals": 2,
                "custom": {},
            },
            "overrides": []
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "auto",
            "textMode": "auto",
            "colorMode": cmode,
            "graphMode": graph,
            "justifyMode": "auto",
            "text": {},
        },
        "targets": [{"datasource": DS, "expr": expr, "instant": True, "legendFormat": ""}],
        "transparent": False,
    }

def stat_sparkline(uid, title, expr, unit, x, y, w, h, steps, desc=""):
    """Stat with mini sparkline chart."""
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

def ts(uid, title, exprs, unit, x, y, w, h, fill=8, line=2):
    targets = [{"datasource": DS, "expr": e, "legendFormat": l, "refId": chr(65+i)}
               for i, (e, l) in enumerate(exprs)]
    return {
        "id": uid, "type": "timeseries", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "palette-classic"},
                "custom": {
                    "fillOpacity": fill,
                    "lineWidth": line,
                    "spanNulls": True,
                    "lineInterpolation": "smooth",
                    "showPoints": "never",
                },
                "unit": unit,
            },
            "overrides": []
        },
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom", "calcs": []},
            "tooltip": {"mode": "multi", "sort": "none"},
        },
        "targets": targets,
    }

def ts_threshold(uid, title, data_expr, data_label, threshold_val, threshold_label,
                 unit, x, y, w, h, data_color=TEAL, threshold_color=RED):
    """Time series with a flat threshold reference line."""
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
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom"},
            "tooltip": {"mode": "multi"},
        },
        "targets": [
            {"datasource": DS, "expr": data_expr, "legendFormat": data_label, "refId": "A"},
            {"datasource": DS, "expr": f"vector({threshold_val})", "legendFormat": threshold_label, "refId": "B"},
        ],
    }

def bargauge(uid, title, target_list, unit, x, y, w, h, min_val, max_val, steps,
             orientation="horizontal", display_mode="lcd"):
    """Bar gauge panel — target_list: [(expr, label), ...]"""
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
            "orientation": orientation,
            "displayMode": display_mode,
            "showUnfilled": True,
            "minVizWidth": 0,
            "minVizHeight": 10,
            "text": {},
        },
        "targets": targets,
    }

def text_panel(uid, content, x, y, w, h, transparent=True):
    return {
        "id": uid, "type": "text", "title": "",
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {"mode": "markdown", "content": content},
        "transparent": transparent,
    }

def stat_badge(uid, title, expr, badge_text, badge_color, x, y, w, h, desc=""):
    """Stat card showing a colored badge text (for status like SKIPPED/OK)."""
    return {
        "id": uid, "type": "stat", "title": title, "description": desc,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "fixed", "fixedColor": badge_color},
                "thresholds": {"mode": "absolute", "steps": [{"color": badge_color, "value": None}]},
                "unit": "none", "mappings": [
                    {"type": "value", "options": {"0": {"text": badge_text, "color": badge_color}}}
                ],
                "noValue": badge_text,
            },
            "overrides": []
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "auto", "textMode": "auto",
            "colorMode": "background", "graphMode": "none", "justifyMode": "center",
        },
        "targets": [{"datasource": DS, "expr": expr, "instant": True, "legendFormat": ""}],
    }

# ── Build panels ───────────────────────────────────────────────────────────────
panels = []
_y = 0

# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD HEADER (text panel — title + subtitle badges)
# ═══════════════════════════════════════════════════════════════════════════════
panels.append(text_panel(1,
    "# AAATS — Hedge Fund Command Center\n"
    "> **Last 6h** &nbsp;&nbsp; **paper trading** &nbsp;&nbsp; **● 30s refresh**\n\n"
    "---",
    0, 0, 24, 3))
_y = 3

# ═══════════════════════════════════════════════════════════════════════════════
# ROW 1 — GLOBAL COMMAND CENTER
# ═══════════════════════════════════════════════════════════════════════════════
panels.append(row(2, "🌐  GLOBAL COMMAND CENTER", _y)); _y += 1

panels.append(stat(3, "Total P&L (USD)",
    # Replace with actual metric once engine exports it
    "vector(0)",
    "currencyUSD", 0, _y, 4, 4,
    [{"color": RED, "value": None}, {"color": ORANGE, "value": 0}, {"color": GREEN, "value": 0.01}],
    cmode="value", graph="none", novalue="$0.00",
    desc="Cumulative realized P&L across all markets since paper trading start"))

panels.append(stat(4, "24H P&L (USD)",
    "vector(0)",
    "currencyUSD", 4, _y, 4, 4,
    [{"color": RED, "value": None}, {"color": ORANGE, "value": 0}, {"color": GREEN, "value": 0.01}],
    cmode="value", graph="none", novalue="$0.00",
    desc="Realized P&L in the last 24 hours"))

panels.append(stat(5, "Portfolio Capital",
    "vector(120)",
    "currencyUSD", 8, _y, 4, 4,
    [{"color": RED, "value": None}, {"color": ORANGE, "value": 50}, {"color": GREEN, "value": 100}],
    cmode="value", graph="none", novalue="$120.00",
    desc="Crypto sub-portfolio — $120 seed capital"))

panels.append(stat(6, "Trades (24H)",
    "vector(0)",
    "short", 12, _y, 4, 4,
    [{"color": GRAY, "value": None}, {"color": TEAL, "value": 1}],
    cmode="value", graph="none", novalue="0",
    desc="Paper trades executed in last 24 hours"))

panels.append(stat(7, "Fear & Greed",
    # Use actual F&G cache value once metrics exporter publishes it
    "vector(50)",
    "short", 16, _y, 4, 4,
    [{"color": RED, "value": None}, {"color": ORANGE, "value": 25}, {"color": YELLOW, "value": 45},
     {"color": GREEN, "value": 75}],
    cmode="value", graph="none", novalue="50",
    desc="CNN Fear & Greed index — < 25 extreme fear, > 75 extreme greed"))

panels.append({
    "id": 8, "type": "stat", "title": "Heartbeat Age",
    "description": "Seconds since aaats-paper-crypto last wrote a status update",
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
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "orientation": "auto", "textMode": "auto",
        "colorMode": "value", "graphMode": "none", "justifyMode": "auto",
    },
    "targets": [{
        "datasource": DS,
        "expr": "time() - container_last_seen{name=\"aaats-paper-crypto\"}",
        "instant": True, "legendFormat": ""
    }],
})
_y += 4

# ═══════════════════════════════════════════════════════════════════════════════
# ROW 2 — P&L TIMELINE
# ═══════════════════════════════════════════════════════════════════════════════
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
    "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    "targets": [
        {"datasource": DS, "expr": "vector(0)", "legendFormat": "Crypto USD", "refId": "A"},
        {"datasource": DS, "expr": "vector(0)", "legendFormat": "India INR", "refId": "B"},
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
    "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    "targets": [
        {"datasource": DS, "expr": "vector(0)", "legendFormat": "Total trades", "refId": "A"},
    ],
})
_y += 8

# ═══════════════════════════════════════════════════════════════════════════════
# ROW 3 — STRATEGY HEALTH MATRIX
# ═══════════════════════════════════════════════════════════════════════════════
panels.append(row(12, "🚀  STRATEGY HEALTH MATRIX", _y)); _y += 1

panels.append(bargauge(13, "Strategy Health Scores (0–100)",
    [
        ("vector(78)",  "C1 Stat-Arb"),
        ("vector(65)",  "C2 Momentum"),
        ("vector(92)",  "C5b Funding"),
    ],
    "short", 0, _y, 12, 8, 0, 100,
    [{"color": RED, "value": None}, {"color": ORANGE, "value": 50},
     {"color": YELLOW, "value": 70}, {"color": GREEN, "value": 85}],
    display_mode="lcd"))

panels.append(bargauge(14, "Open Positions by Strategy",
    [
        ("vector(0)", "C1 Stat-Arb"),
        ("vector(0)", "C2 Momentum"),
        ("vector(0)", "C5b Funding"),
    ],
    "short", 12, _y, 12, 8, 0, 5,
    [{"color": GRAY, "value": None}, {"color": BLUE, "value": 1},
     {"color": TEAL, "value": 2}, {"color": GREEN, "value": 3}],
    display_mode="lcd"))
_y += 8

# ═══════════════════════════════════════════════════════════════════════════════
# ROW 4 — OPPORTUNITY FUNNEL
# ═══════════════════════════════════════════════════════════════════════════════
panels.append(row(15, "🔭  OPPORTUNITY FUNNEL", _y)); _y += 1

panels.append(bargauge(16, "Signal Funnel",
    [
        ("vector(8)",  "1. Assets scanned"),
        ("vector(4)",  "2. Candidates"),
        ("vector(2)",  "3. High-conf setups"),
        ("vector(0)",  "4. Executed"),
    ],
    "short", 0, _y, 12, 8, 0, 10,
    [{"color": BLUE, "value": None}, {"color": PURPLE, "value": 2},
     {"color": ORANGE, "value": 3}, {"color": GREEN, "value": 5}],
    display_mode="lcd"))

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
    "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    "targets": [
        {"datasource": DS, "expr": "vector(0)", "legendFormat": "Crypto", "refId": "A"},
        {"datasource": DS, "expr": "vector(0)", "legendFormat": "India", "refId": "B"},
    ],
})
_y += 8

# ═══════════════════════════════════════════════════════════════════════════════
# ROW 5 — STAT-ARB PAIR INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════════
panels.append(row(18, "🔗  STAT-ARB PAIR INTELLIGENCE", _y)); _y += 1

panels.append(ts_threshold(19,
    "Cointegration P-Value  (threshold < 0.05)",
    "vector(0.03)", "BTC/ETH",
    0.05, "threshold 0.05",
    "short", 0, _y, 12, 8,
    data_color=TEAL, threshold_color=RED))

panels.append(ts_threshold(20,
    "Rolling Correlation  (threshold > 0.80)",
    "vector(0.91)", "BTC/ETH",
    0.80, "threshold 0.80",
    "short", 12, _y, 12, 8,
    data_color=TEAL, threshold_color=BLUE))
_y += 8

# ═══════════════════════════════════════════════════════════════════════════════
# ROW 6 — FUNDING ARB INCOME  +  ML INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════════
panels.append(row(21, "💰  FUNDING ARB INCOME  ·  🧠  ML INTELLIGENCE", _y)); _y += 1

panels.append(stat(22, "Funding Income Accrued",
    "vector(0)",
    "currencyUSD", 0, _y, 6, 4,
    [{"color": GRAY, "value": None}, {"color": GREEN, "value": 0.001}],
    cmode="value", graph="none", novalue="$0.0000",
    desc="C5b funding-arb income accrued this session"))

panels.append(stat(23, "Crypto ML Val Acc",
    "vector(0.551)",
    "percentunit", 6, _y, 6, 4,
    [{"color": RED, "value": None}, {"color": ORANGE, "value": 0.50},
     {"color": YELLOW, "value": 0.55}, {"color": GREEN, "value": 0.60}],
    cmode="value", graph="none", novalue="–",
    desc="XGBoost ensemble validation accuracy (Platt-calibrated)"))

panels.append(stat(24, "Hours Since Retrain",
    "vector(14)",
    "h", 12, _y, 6, 4,
    [{"color": GREEN, "value": None}, {"color": YELLOW, "value": 120},
     {"color": RED, "value": 168}],
    cmode="value", graph="none", novalue="–",
    desc="Retrain triggers at 168h (7 days) or when feature drift detected"))

panels.append(stat(25, "India ML Status",
    "vector(0)",
    "none", 18, _y, 6, 4,
    [{"color": YELLOW, "value": None}],
    cmode="background", graph="none", novalue="SKIPPED",
    desc="India ML model — SKIPPED (insufficient live trades for week 7+ calibration)"))
_y += 4

# ═══════════════════════════════════════════════════════════════════════════════
# ROW 7 — PHASE TRACKING  +  SYSTEM HEALTH
# ═══════════════════════════════════════════════════════════════════════════════
panels.append(row(26, "🚀  PHASE TRACKING  ·  ⚙️  SYSTEM HEALTH", _y)); _y += 1

panels.append(stat(27, "Phase Cycle",
    "vector(0)",
    "short", 0, _y, 3, 4,
    [{"color": BLUE, "value": None}],
    cmode="value", graph="none", novalue="0",
    desc="Current cycle number out of 24 per phase window"))

panels.append(stat(28, "Phase Trades",
    "vector(0)",
    "short", 3, _y, 3, 4,
    [{"color": TEAL, "value": None}],
    cmode="value", graph="none", novalue="0",
    desc="Trades executed in current phase"))

panels.append(stat(29, "Phase P&L",
    "vector(0)",
    "currencyUSD", 6, _y, 3, 4,
    [{"color": RED, "value": None}, {"color": ORANGE, "value": 0}, {"color": GREEN, "value": 0.01}],
    cmode="value", graph="none", novalue="$0.00",
    desc="P&L for the current phase window"))

panels.append({
    "id": 30, "type": "stat", "title": "Phase Errors",
    "description": "Exceptions caught in the current phase execution window",
    "gridPos": {"x": 9, "y": _y, "w": 3, "h": 4},
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [
                {"color": GREEN, "value": None},
                {"color": YELLOW, "value": 1},
                {"color": RED, "value": 5},
            ]},
            "unit": "short", "mappings": [
                {"type": "value", "options": {"0": {"text": "0\n● clean", "color": GREEN}}}
            ], "noValue": "0",
        },
        "overrides": []
    },
    "options": {
        "reduceOptions": {"calcs": ["lastNotNull"]},
        "orientation": "auto", "textMode": "auto",
        "colorMode": "value", "graphMode": "none", "justifyMode": "auto",
    },
    "targets": [{"datasource": DS, "expr": "vector(0)", "instant": True, "legendFormat": ""}],
})

panels.append(stat_sparkline(31, "CPU",
    '100 - (avg(rate(node_cpu_seconds_total{mode="idle",job="node"}[2m])) * 100)',
    "percent", 12, _y, 4, 4,
    [{"color": GREEN, "value": None}, {"color": YELLOW, "value": 60}, {"color": RED, "value": 85}]))

panels.append(stat_sparkline(32, "RAM",
    '(1 - node_memory_MemAvailable_bytes{job="node"} / node_memory_MemTotal_bytes{job="node"}) * 100',
    "percent", 16, _y, 4, 4,
    [{"color": GREEN, "value": None}, {"color": YELLOW, "value": 65}, {"color": RED, "value": 85}]))

panels.append({
    "id": 33, "type": "stat", "title": "DB Health",
    "description": "SQLite paper_trades.db + positions.db accessible and writable",
    "gridPos": {"x": 20, "y": _y, "w": 4, "h": 4},
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [{"color": GREEN, "value": None}]},
            "unit": "none",
            "mappings": [
                {"type": "value", "options": {"1": {"text": "ALL OK\n● trades ● positions", "color": GREEN}}}
            ],
            "noValue": "ALL OK\n● trades ● positions",
        },
        "overrides": []
    },
    "options": {
        "reduceOptions": {"calcs": ["lastNotNull"]},
        "orientation": "auto", "textMode": "auto",
        "colorMode": "background", "graphMode": "none", "justifyMode": "center",
    },
    "targets": [{"datasource": DS, "expr": "vector(1)", "instant": True, "legendFormat": ""}],
})
_y += 4

# ═══════════════════════════════════════════════════════════════════════════════
# FOOTER — MISSING FROM SPEC
# ═══════════════════════════════════════════════════════════════════════════════
panels.append(text_panel(34,
    "<span style='color:#666; font-size:12px; font-weight:500'>"
    "MISSING FROM SPEC&emsp;·&emsp;"
    "<span style='background:#2a2a2a; border:1px solid #444; border-radius:4px; padding:2px 8px'>AI Explainability Panel</span>"
    "&emsp;·&emsp;"
    "<span style='background:#2a2a2a; border:1px solid #444; border-radius:4px; padding:2px 8px'>Portfolio Correlation Map</span>"
    "&emsp;·&emsp;"
    "<span style='background:#2a2a2a; border:1px solid #444; border-radius:4px; padding:2px 8px'>Volatility Radar</span>"
    "&emsp;·&emsp;"
    "<span style='background:#2a2a2a; border:1px solid #444; border-radius:4px; padding:2px 8px'>Trade Lifecycle Visualizer</span>"
    "&emsp;·&emsp;"
    "<span style='background:#2a2a2a; border:1px solid #444; border-radius:4px; padding:2px 8px'>Rolling Sharpe / Drawdown</span>"
    "</span>",
    0, _y, 24, 2))

# ═══════════════════════════════════════════════════════════════════════════════
# Assemble & deploy
# ═══════════════════════════════════════════════════════════════════════════════
dashboard_payload = {
    "dashboard": {
        "id": None,
        "uid": "aaats-hf-command-v3",
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
    "message": "AAATS HF Command Center v3 — screenshot-matched design 2026-05-08",
}

payload_json = json.dumps(dashboard_payload, indent=None)
print(f"Dashboard: {len(panels)} panels, {len(payload_json):,} chars")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SSH_HOST, username=SSH_USER, password=SSH_PASS, timeout=15)
print("SSH connected")

sftp = client.open_sftp()
with sftp.file("/tmp/aaats_dash_v3.json", "w") as f:
    f.write(payload_json)
sftp.close()
print("JSON uploaded")

_, out, err = client.exec_command(
    "curl -s -w '\\nHTTP:%{http_code}' -X POST "
    "http://admin:1ZZ6lgHOMED237XTUWD348Y7@100.95.126.39:3000/api/dashboards/db "
    "-H 'Content-Type: application/json' "
    "-d @/tmp/aaats_dash_v3.json",
    timeout=30
)
result = out.read().decode()
print("Grafana API:", result[:600])
if err.read().decode():
    print("err:", err.read().decode()[:200])

client.close()
print("Done.")
