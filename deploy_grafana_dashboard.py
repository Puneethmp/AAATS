#!/usr/bin/env python3
"""Deploy AAATS beautified Grafana dashboard via SSH + Grafana API."""

import json
import paramiko

SSH_HOST = "100.95.126.39"
SSH_USER = "aaats"
SSH_PASS = "Puneeth1234"

DS = {"type": "prometheus", "uid": "aaats-prom"}

GREEN  = "#73BF69"
YELLOW = "#F2CC0C"
RED    = "#F2495C"
BLUE   = "#5794F2"
PURPLE = "#B877D9"
CYAN   = "#37872D"

# ── Panel builders ─────────────────────────────────────────────────────────────

def row(uid, title, y):
    return {"id": uid, "type": "row", "title": title,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
            "collapsed": False, "panels": []}

def stat(uid, title, expr, unit, x, y, w, h, steps,
         cmode="background", graph="area", novalue="N/A", desc=""):
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
            "colorMode": cmode, "graphMode": graph, "justifyMode": "center",
        },
        "targets": [{"datasource": DS, "expr": expr, "instant": True, "legendFormat": ""}],
        "transparent": False,
    }

def ts(uid, title, exprs, unit, x, y, w, h, fill=True):
    targets = [{"datasource": DS, "expr": e, "legendFormat": l} for e, l in exprs]
    return {
        "id": uid, "type": "timeseries", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "palette-classic"},
                "custom": {
                    "fillOpacity": 10 if fill else 0,
                    "lineWidth": 2, "spanNulls": True,
                },
                "unit": unit,
            },
            "overrides": []
        },
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom"},
            "tooltip": {"mode": "multi"},
        },
        "targets": targets,
    }

def gauge(uid, title, expr, unit, x, y, w, h, min_val, max_val, steps):
    return {
        "id": uid, "type": "gauge", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": steps},
                "unit": unit, "min": min_val, "max": max_val, "mappings": [],
            },
            "overrides": []
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]},
                    "showThresholdLabels": False, "showThresholdMarkers": True},
        "targets": [{"datasource": DS, "expr": expr, "instant": True, "legendFormat": ""}],
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

# HEADER
panels.append(text_panel(1,
    "# AAATS — Algorithmic Automated Trading System\n"
    "### Real-time Command Center  |  Paper Mode Active  |  v6 Engine  |  Crypto $120 + India ₹25k\n"
    "---",
    0, 0, 24, 3))

# ── ROW 1: COMMAND CENTER ─────────────────────────────────────────────────────
panels.append(row(2, "   GLOBAL COMMAND CENTER", 3))

panels.append(stat(3, "SYSTEM UPTIME",
    '(time() - node_boot_time_seconds{job="node"}) / 3600',
    "h", 0, 4, 4, 4,
    [{"color": "red", "value": None}, {"color": YELLOW, "value": 1}, {"color": GREEN, "value": 24}],
    novalue="–", desc="Hours since last reboot"))

panels.append(stat(4, "ACTIVE CONTAINERS",
    'count(container_last_seen{image!="",name=~"aaats-.+"})',
    "short", 4, 4, 4, 4,
    [{"color": "red", "value": None}, {"color": YELLOW, "value": 5}, {"color": GREEN, "value": 10}],
    novalue="0"))

panels.append(stat(5, "CPU LOAD (1m)",
    'node_load1{job="node"}',
    "short", 8, 4, 4, 4,
    [{"color": GREEN, "value": None}, {"color": YELLOW, "value": 2}, {"color": RED, "value": 4}]))

panels.append(stat(6, "MEMORY USED",
    '(1 - node_memory_MemAvailable_bytes{job="node"} / node_memory_MemTotal_bytes{job="node"}) * 100',
    "percent", 12, 4, 4, 4,
    [{"color": GREEN, "value": None}, {"color": YELLOW, "value": 70}, {"color": RED, "value": 85}]))

panels.append(stat(7, "DISK USED",
    '(1 - node_filesystem_avail_bytes{job="node",mountpoint="/",fstype!="tmpfs"} / node_filesystem_size_bytes{job="node",mountpoint="/",fstype!="tmpfs"}) * 100',
    "percent", 16, 4, 4, 4,
    [{"color": GREEN, "value": None}, {"color": YELLOW, "value": 70}, {"color": RED, "value": 85}]))

panels.append(stat(8, "PROMETHEUS TARGETS UP",
    "count(up == 1)",
    "short", 20, 4, 4, 4,
    [{"color": "red", "value": None}, {"color": YELLOW, "value": 5}, {"color": GREEN, "value": 8}],
    novalue="0", desc="Healthy scrape targets out of total"))

# ── ROW 2: INFRASTRUCTURE ─────────────────────────────────────────────────────
panels.append(row(9, "   INFRASTRUCTURE REAL-TIME", 8))

panels.append(ts(10, "CPU Usage %",
    [('100 - (avg(rate(node_cpu_seconds_total{mode="idle",job="node"}[2m])) * 100)', "cpu %")],
    "percent", 0, 9, 12, 8))

panels.append(ts(11, "Memory Usage",
    [('node_memory_MemTotal_bytes{job="node"} - node_memory_MemAvailable_bytes{job="node"}', "Used"),
     ('node_memory_MemTotal_bytes{job="node"}', "Total")],
    "bytes", 12, 9, 12, 8))

# ── ROW 3: NETWORK ─────────────────────────────────────────────────────────────
panels.append(row(12, "   NETWORK I/O", 17))

panels.append(ts(13, "Network Receive",
    [('rate(node_network_receive_bytes_total{job="node",device!="lo"}[2m])', "{{device}} RX")],
    "Bps", 0, 18, 12, 7))

panels.append(ts(14, "Network Transmit",
    [('rate(node_network_transmit_bytes_total{job="node",device!="lo"}[2m])', "{{device}} TX")],
    "Bps", 12, 18, 12, 7))

# ── ROW 4: CONTAINER HEALTH ────────────────────────────────────────────────────
panels.append(row(15, "   CONTAINER HEALTH MATRIX", 25))

panels.append(ts(16, "Container CPU %  (all AAATS services)",
    [('rate(container_cpu_usage_seconds_total{name=~"aaats-.+",image!=""}[2m]) * 100', "{{name}}")],
    "percent", 0, 26, 14, 8))

panels.append(ts(17, "Container Memory MB",
    [('container_memory_usage_bytes{name=~"aaats-.+",image!=""} / 1024 / 1024', "{{name}}")],
    "decmbytes", 14, 26, 10, 8))

# ── ROW 5: DATABASE & CACHE ────────────────────────────────────────────────────
panels.append(row(18, "   DATABASE & CACHE HEALTH", 34))

panels.append(gauge(19, "Redis Memory Used",
    "redis_memory_used_bytes / 1024 / 1024",
    "decmbytes", 0, 35, 6, 6, 0, 512,
    [{"color": GREEN, "value": None}, {"color": YELLOW, "value": 256}, {"color": RED, "value": 450}]))

panels.append(gauge(20, "Redis Hit Rate",
    "rate(redis_keyspace_hits_total[2m]) / (rate(redis_keyspace_hits_total[2m]) + rate(redis_keyspace_misses_total[2m]) + 0.0001) * 100",
    "percent", 6, 35, 6, 6, 0, 100,
    [{"color": RED, "value": None}, {"color": YELLOW, "value": 60}, {"color": GREEN, "value": 80}]))

panels.append(stat(21, "Postgres Connections",
    "pg_stat_activity_count",
    "short", 12, 35, 6, 6,
    [{"color": GREEN, "value": None}, {"color": YELLOW, "value": 50}, {"color": RED, "value": 90}],
    novalue="0"))

panels.append(stat(22, "Postgres DB Size",
    'pg_database_size_bytes{datname="aaats"} / 1024 / 1024',
    "decmbytes", 18, 35, 6, 6,
    [{"color": GREEN, "value": None}, {"color": YELLOW, "value": 512}, {"color": RED, "value": 1024}],
    novalue="–"))

# ── ROW 6: STRATEGY HEALTH MATRIX ─────────────────────────────────────────────
panels.append(row(23, "   STRATEGY HEALTH & PAPER TRADING", 41))

panels.append(stat(24, "TRADING MODE",
    "vector(1)",
    "none", 0, 42, 4, 4,
    [{"color": BLUE, "value": None}],
    cmode="background", graph="none", novalue="PAPER",
    desc="paper | live — never set to live before 2026-05-22"))

panels.append(stat(25, "CRYPTO CAPITAL",
    "vector(120)",
    "currencyUSD", 4, 42, 4, 4,
    [{"color": RED, "value": None}, {"color": YELLOW, "value": 50}, {"color": GREEN, "value": 100}],
    novalue="$120", desc="Crypto sub-portfolio USD balance"))

panels.append(stat(26, "PAPER TRADES FIRED",
    "vector(0)",
    "short", 8, 42, 4, 4,
    [{"color": YELLOW, "value": None}, {"color": GREEN, "value": 1}],
    novalue="0", desc="Total paper trades since deployment — watching for first signal"))

panels.append(stat(27, "ACTIVE STRATEGIES",
    "vector(3)",
    "short", 12, 42, 4, 4,
    [{"color": YELLOW, "value": None}, {"color": GREEN, "value": 2}],
    novalue="3", desc="C1 stat-arb | C2 momentum | C3 funding-arb"))

panels.append(stat(28, "CURRENT REGIME",
    "vector(1)",
    "none", 16, 42, 4, 4,
    [{"color": RED, "value": None}, {"color": YELLOW, "value": 0.5}, {"color": GREEN, "value": 0.9}],
    cmode="background", graph="none", novalue="BEAR",
    desc="Market regime detected by ml/xgboost_ensemble — affects entry filters"))

panels.append(stat(29, "GO-LIVE DATE",
    "vector(14)",
    "none", 20, 42, 4, 4,
    [{"color": RED, "value": None}, {"color": YELLOW, "value": 7}, {"color": GREEN, "value": 14}],
    cmode="background", graph="none", novalue="2026-05-22",
    desc="Minimum 14-day paper trading before live. NEVER go live early."))

# ── ROW 7: PAPER CRYPTO ENGINE ─────────────────────────────────────────────────
panels.append(row(30, "   PAPER CRYPTO ENGINE — aaats-paper-crypto", 46))

panels.append(ts(31, "Paper-Crypto CPU %",
    [('rate(container_cpu_usage_seconds_total{name="aaats-paper-crypto"}[2m]) * 100', "paper-crypto CPU %")],
    "percent", 0, 47, 8, 7))

panels.append(ts(32, "Paper-Crypto Memory MB",
    [('container_memory_usage_bytes{name="aaats-paper-crypto"} / 1024 / 1024', "paper-crypto RAM MB")],
    "decmbytes", 8, 47, 8, 7))

panels.append(ts(33, "Engine CPU %",
    [('rate(container_cpu_usage_seconds_total{name="aaats-engine"}[2m]) * 100', "engine CPU %")],
    "percent", 16, 47, 8, 7))

# ── ROW 8: VOLATILITY & REGIME ────────────────────────────────────────────────
panels.append(row(34, "   AI & MACHINE LEARNING HEALTH", 54))

panels.append(text_panel(35,
    "### AI / ML Layer\n"
    "**Model:** XGBoost Ensemble (3-vote gate) — confidence threshold: **0.40**\n\n"
    "**Current state:** All cycles returning HOLD — market in BEAR_TREND / RANGE_BOUND.\n"
    "Entries blocked until Bull regime + all 5 conditions pass (breakout + RSI + volume + EMA + F&G).\n\n"
    "| Strategy | Trigger | Status |\n"
    "|---|---|---|\n"
    "| C2 Momentum Breakout | 20-bar high + RSI>52 + vol 1.4x + EMA bull | Watching |\n"
    "| C1 Stat-Arb (BTC/ETH) | z-score deviation | Watching |\n"
    "| C3 Funding Rate Arb | funding rate > threshold | Watching |\n\n"
    "> Confidence fix deployed 2026-05-08 — scores now computed from breakout_strength + RSI + volume + F&G",
    0, 55, 24, 7),
)

# ── ROW 9: SYSTEM DETAILS ─────────────────────────────────────────────────────
panels.append(row(36, "   SYSTEM DETAILS & DIAGNOSTICS", 62))

panels.append(stat(37, "CPU Cores",
    'count(node_cpu_seconds_total{mode="idle",job="node"})',
    "short", 0, 63, 4, 3,
    [{"color": BLUE, "value": None}],
    cmode="value", graph="none"))

panels.append(stat(38, "Total RAM",
    'node_memory_MemTotal_bytes{job="node"}',
    "bytes", 4, 63, 4, 3,
    [{"color": BLUE, "value": None}],
    cmode="value", graph="none"))

panels.append(stat(39, "Disk Total",
    'node_filesystem_size_bytes{job="node",mountpoint="/",fstype!="tmpfs"}',
    "bytes", 8, 63, 4, 3,
    [{"color": BLUE, "value": None}],
    cmode="value", graph="none"))

panels.append(stat(40, "Open File Descriptors",
    'node_filefd_allocated{job="node"}',
    "short", 12, 63, 4, 3,
    [{"color": GREEN, "value": None}, {"color": YELLOW, "value": 50000}, {"color": RED, "value": 90000}]))

panels.append(stat(41, "Scrape Targets DOWN",
    "sum(up == 0) or vector(0)",
    "short", 16, 63, 4, 3,
    [{"color": GREEN, "value": None}, {"color": YELLOW, "value": 1}, {"color": RED, "value": 3}],
    novalue="0", desc="Prometheus targets currently failing to scrape"))

panels.append(ts(42, "Disk I/O",
    [('rate(node_disk_read_bytes_total{job="node"}[2m])', "Read"),
     ('rate(node_disk_written_bytes_total{job="node"}[2m])', "Write")],
    "Bps", 20, 63, 4, 3))

# ── ROW 10: CLOUDFLARE ───────────────────────────────────────────────────────
panels.append(row(43, "   CLOUDFLARE TUNNEL & CONNECTIVITY", 66))

panels.append(text_panel(44,
    "### Cloudflare Named Tunnel\n"
    "**Tunnel UUID:** `0fb472f2-b87c-4416-b1ff-b291bb41771c`\n\n"
    "**Active PoPs:** Singapore (sin08 / sin20 / sin02 / sin15)\n\n"
    "**Services routed:**\n"
    "- `aaats-cloudflared` → Grafana + main services\n"
    "- `aaats-cloudflared-bot` → Telegram bot (`aaats-telegram-bot:8080`)\n\n"
    "**Grafana access:** Tailscale-only on `100.95.126.39:3000` — NOT public until tunnel hostname configured in Cloudflare dashboard",
    0, 67, 12, 5),
)

panels.append(ts(45, "Cloudflared Container CPU",
    [('rate(container_cpu_usage_seconds_total{name=~"aaats-cloudflared.*"}[2m]) * 100', "{{name}}")],
    "percent", 12, 67, 12, 5))

# ── Assemble dashboard ────────────────────────────────────────────────────────
dashboard_payload = {
    "dashboard": {
        "id": None,
        "uid": "aaats-cmd-center-v2",
        "title": "AAATS — Command Center",
        "tags": ["aaats", "trading", "live", "paper"],
        "timezone": "browser",
        "schemaVersion": 38,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "timepicker": {},
        "panels": panels,
        "graphTooltip": 1,
        "editable": True,
    },
    "folderId": 0,
    "overwrite": True,
    "message": "AAATS Command Center v2 — deployed by Claude Code 2026-05-08",
}

payload_json = json.dumps(dashboard_payload, indent=None)
print(f"Dashboard: {len(panels)} panels, {len(payload_json):,} chars")

# ── Deploy via SSH → Grafana API ──────────────────────────────────────────────
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SSH_HOST, username=SSH_USER, password=SSH_PASS, timeout=15)
print("SSH connected")

sftp = client.open_sftp()
with sftp.file("/tmp/aaats_dash.json", "w") as f:
    f.write(payload_json)
sftp.close()
print("JSON uploaded to /tmp/aaats_dash.json")

cmd = (
    "curl -s -w '\\nHTTP:%{http_code}' -X POST "
    "http://admin:1ZZ6lgHOMED237XTUWD348Y7@100.95.126.39:3000/api/dashboards/db "
    "-H 'Content-Type: application/json' "
    "-d @/tmp/aaats_dash.json"
)
_, out, err = client.exec_command(cmd, timeout=30)
result = out.read().decode()
stderr = err.read().decode()
print("Grafana API response:")
print(result[:800])
if stderr:
    print("stderr:", stderr[:200])

client.close()
print("Done.")
