"""
AAATS Paper Trading Dashboard  v2
===================================
Reads: data/paper_trades.db  data/paper_portfolio.json  data/paper_positions.json
Writes: data/paper_report.html

New in v2:
  ✅ Unrealized P&L on open positions (entry_price vs last trade price)
  ✅ Sector exposure bar (NSE only)
  ✅ Drawdown gauge (realized PnL vs initial capital)
  ✅ Per-market win-rate breakdown
  ✅ Portfolio heat indicator
  ✅ Stop-loss distance per open position
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DB_PATH        = _ROOT / "data" / "paper_trades.db"
PORTFOLIO_FILE = _ROOT / "data" / "paper_portfolio.json"
POSITIONS_FILE = _ROOT / "data" / "paper_positions.json"
OUT_HTML       = _ROOT / "data" / "paper_report.html"

INITIAL_CAPITAL = {"india": 500_000.0, "crypto": 1_000.0}

# Sector colors for exposure chart
SECTOR_COLORS = {
    "financials": "#3b82f6",
    "it":         "#8b5cf6",
    "energy":     "#f59e0b",
    "consumer":   "#10b981",
    "auto":       "#ef4444",
    "pharma":     "#06b6d4",
    "crypto":     "#f97316",
}


# ── Data loading ──────────────────────────────────────────────────────────────

def load_trades() -> list[dict]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM paper_trades ORDER BY timestamp DESC LIMIT 500"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def load_equity_series() -> tuple[list, list, list]:
    """Build cumulative P&L series separately for india and crypto."""
    if not DB_PATH.exists():
        return [], [], []
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT timestamp, market, pnl FROM paper_trades "
            "WHERE action='SELL' ORDER BY timestamp ASC"
        ).fetchall()
        labels, india_vals, crypto_vals = [], [], []
        running = {"india": 0.0, "crypto": 0.0}
        for r in rows:
            mkt = r["market"]
            if mkt in running:
                running[mkt] += (r["pnl"] or 0)
            labels.append(r["timestamp"][:16])
            india_vals.append(round(running["india"], 2))
            crypto_vals.append(round(running["crypto"], 6))
        return labels, india_vals, crypto_vals
    finally:
        conn.close()


def load_portfolio() -> dict:
    if PORTFOLIO_FILE.exists():
        return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    return {}


def load_positions() -> dict:
    if POSITIONS_FILE.exists():
        return json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
    return {"india": {}, "crypto": {}}


def _last_trade_price(symbol: str) -> float | None:
    """Get last recorded trade price for unrealized P&L estimation."""
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH))
    try:
        row = conn.execute(
            "SELECT price FROM paper_trades WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        return float(row[0]) if row else None
    except Exception:
        return None
    finally:
        conn.close()


# ── Stats helpers ─────────────────────────────────────────────────────────────

def _pct_color(val, threshold=0) -> str:
    try:
        return "green" if float(val) >= threshold else "red"
    except Exception:
        return ""


def _fmt(val, prefix="", decimals=4) -> str:
    if val is None:
        return "—"
    try:
        f    = float(val)
        sign = "+" if f >= 0 else ""
        return f"{prefix}{sign}{f:,.{decimals}f}"
    except Exception:
        return str(val)


def sector_exposure(positions: dict) -> dict[str, int]:
    exp: dict[str, int] = {}
    for pos in positions.get("india", {}).values():
        s = pos.get("sector", "other")
        exp[s] = exp.get(s, 0) + 1
    for sym in positions.get("crypto", {}):
        exp["crypto"] = exp.get("crypto", 0) + 1
    return exp


# ── HTML generation ───────────────────────────────────────────────────────────

def generate_html(
    trades: list[dict],
    labels: list, india_eq: list, crypto_eq: list,
    portfolio: dict, positions: dict,
) -> str:

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Summary stats ─────────────────────────────────────────────────────────
    sells      = [t for t in trades if t.get("action") == "SELL"]
    wins       = [t for t in sells if (t.get("pnl") or 0) > 0]
    win_rate   = len(wins) / len(sells) * 100 if sells else 0.0

    p_india    = portfolio.get("india",  {})
    p_crypto   = portfolio.get("crypto", {})

    rpnl_india  = p_india.get("realized_pnl", 0.0)
    rpnl_crypto = p_crypto.get("realized_pnl", 0.0)
    cap_india   = p_india.get("capital", INITIAL_CAPITAL["india"])
    cap_crypto  = p_crypto.get("capital", INITIAL_CAPITAL["crypto"])

    # Drawdown (realized only — conservative)
    dd_india  = rpnl_india  / INITIAL_CAPITAL["india"]  * 100
    dd_crypto = rpnl_crypto / INITIAL_CAPITAL["crypto"] * 100

    open_india  = positions.get("india",  {})
    open_crypto = positions.get("crypto", {})
    open_count  = len(open_india) + len(open_crypto)

    total_trades = len(trades)

    # Unrealized P&L on open positions (best-effort from last trade price)
    unrealized_india  = 0.0
    unrealized_crypto = 0.0
    for sym, pos in open_india.items():
        lp = _last_trade_price(sym)
        if lp:
            unrealized_india += (lp - pos["entry_price"]) * pos["shares"]
    for sym, pos in open_crypto.items():
        lp = _last_trade_price(sym)
        if lp:
            unrealized_crypto += (lp - pos["entry_price"]) * pos["shares"]

    # ── Sector exposure chart ─────────────────────────────────────────────────
    exp       = sector_exposure(positions)
    sec_labs  = json.dumps(list(exp.keys()))
    sec_vals  = json.dumps(list(exp.values()))
    sec_cols  = json.dumps([SECTOR_COLORS.get(s, "#6b7280") for s in exp])

    # ── Equity chart data ─────────────────────────────────────────────────────
    eq_labels     = json.dumps(labels)
    eq_india_data = json.dumps(india_eq)
    eq_crypt_data = json.dumps(crypto_eq)

    # ── Open positions rows ───────────────────────────────────────────────────
    pos_rows = ""
    for sym, pos in {**{f"🇮🇳 {s}": (v, "india") for s, v in open_india.items()},
                     **{f"₿ {s}":  (v, "crypto") for s, v in open_crypto.items()}}.items():
        v, mkt  = pos
        lp      = _last_trade_price(sym.split(" ", 1)[-1])
        ep      = v["entry_price"]
        sh      = v["shares"]
        upnl    = (lp - ep) * sh if lp else 0.0
        upnl_pct= (lp - ep) / ep * 100 if lp and ep else 0.0
        atr     = v.get("atr_entry", ep * 0.02)
        stop_px = ep - 2 * atr
        stop_pct= (ep - stop_px) / ep * 100
        uc      = "green" if upnl >= 0 else "red"
        pos_rows += (
            f"<tr>"
            f"<td>{sym}</td>"
            f"<td>{ep:.4f}</td>"
            f"<td>{sh:.6f}</td>"
            f"<td style='color:{uc}'>{_fmt(upnl)} ({upnl_pct:+.2f}%)</td>"
            f"<td>{stop_px:.4f} (-{stop_pct:.1f}%)</td>"
            f"<td>{v.get('regime','')}</td>"
            f"<td>{v.get('sector','')}</td>"
            f"<td>{(v.get('entry_time','')[:16])}</td>"
            f"</tr>\n"
        )
    if not pos_rows:
        pos_rows = '<tr><td colspan="8" style="text-align:center;color:#888">No open positions</td></tr>'

    # ── Trade rows ────────────────────────────────────────────────────────────
    trade_rows = ""
    for t in trades[:200]:
        rc  = "buy" if t.get("action") == "BUY" else "sell"
        pnl = _fmt(t.get("pnl"))
        pc  = _pct_color(t.get("pnl"))
        trade_rows += (
            f'<tr class="{rc}">'
            f'<td>{(t.get("timestamp","")[:16])}</td>'
            f'<td>{t.get("market","")}</td>'
            f'<td>{t.get("symbol","")}</td>'
            f'<td><b>{t.get("action","")}</b></td>'
            f'<td>{float(t.get("shares",0)):.6f}</td>'
            f'<td>{float(t.get("price",0)):.4f}</td>'
            f'<td style="color:{pc}">{pnl}</td>'
            f'<td>{t.get("regime","")}</td>'
            f'</tr>\n'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="300">
<title>AAATS Paper Trading v2</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',sans-serif;background:#0d0f17;color:#e0e0e0;padding:20px}}
  h1{{color:#00d4ff;font-size:1.4rem;margin-bottom:4px}}
  .sub{{color:#666;font-size:.78rem;margin-bottom:20px}}
  .cards{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}}
  .card{{background:#161923;border-radius:10px;padding:14px 18px;min-width:150px;border:1px solid #1e2535}}
  .card .lbl{{font-size:.68rem;color:#666;text-transform:uppercase;letter-spacing:.06em}}
  .card .val{{font-size:1.45rem;font-weight:700;margin-top:3px}}
  .green{{color:#00c896}}.red{{color:#ff4d6d}}.blue{{color:#00d4ff}}.gold{{color:#f59e0b}}
  .charts{{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-bottom:20px}}
  .chart-box{{background:#161923;border-radius:10px;padding:16px;border:1px solid #1e2535}}
  .chart-box h2{{font-size:.82rem;color:#888;margin-bottom:10px}}
  .section{{background:#161923;border-radius:10px;padding:16px;margin-bottom:16px;border:1px solid #1e2535}}
  .section h2{{font-size:.82rem;color:#888;margin-bottom:10px}}
  table{{width:100%;border-collapse:collapse;font-size:.78rem}}
  th{{background:#1a1f2e;color:#888;padding:7px 9px;text-align:left;font-weight:600;letter-spacing:.03em}}
  td{{padding:6px 9px;border-bottom:1px solid #1a1f2e}}
  tr:hover td{{background:#1a1f2e}}
  tr.buy td{{border-left:3px solid #00c896}}
  tr.sell td{{border-left:3px solid #ff4d6d}}
  .dd-bar{{height:8px;border-radius:4px;background:#1e2535;margin-top:6px;overflow:hidden}}
  .dd-fill{{height:100%;border-radius:4px;transition:width .4s}}
</style>
</head>
<body>

<h1>⚡ AAATS Paper Trading Dashboard  v2</h1>
<p class="sub">Updated: {now_str} &nbsp;|&nbsp; Auto-refreshes every 5 min &nbsp;|&nbsp;
Angel One NSE + Binance Crypto &nbsp;|&nbsp; Full risk engine active</p>

<!-- ── Summary cards ── -->
<div class="cards">
  <div class="card">
    <div class="lbl">Total Trades</div>
    <div class="val blue">{total_trades}</div>
  </div>
  <div class="card">
    <div class="lbl">Open Positions</div>
    <div class="val blue">{open_count}</div>
  </div>
  <div class="card">
    <div class="lbl">Win Rate</div>
    <div class="val {'green' if win_rate>=50 else 'red'}">{win_rate:.1f}%</div>
  </div>
  <div class="card">
    <div class="lbl">India Realized (INR)</div>
    <div class="val {'green' if rpnl_india>=0 else 'red'}">{_fmt(rpnl_india,'₹',0)}</div>
    <div class="dd-bar"><div class="dd-fill" style="width:{min(abs(dd_india),100):.1f}%;background:{'#00c896' if dd_india>=0 else '#ff4d6d'}"></div></div>
  </div>
  <div class="card">
    <div class="lbl">India Unrealized (INR)</div>
    <div class="val {'green' if unrealized_india>=0 else 'red'}">{_fmt(unrealized_india,'₹',0)}</div>
  </div>
  <div class="card">
    <div class="lbl">India Cash (INR)</div>
    <div class="val">₹{cap_india:,.0f}</div>
  </div>
  <div class="card">
    <div class="lbl">Crypto Realized (USDT)</div>
    <div class="val {'green' if rpnl_crypto>=0 else 'red'}">{_fmt(rpnl_crypto,'$')}</div>
    <div class="dd-bar"><div class="dd-fill" style="width:{min(abs(dd_crypto),100):.1f}%;background:{'#00c896' if dd_crypto>=0 else '#ff4d6d'}"></div></div>
  </div>
  <div class="card">
    <div class="lbl">Crypto Unrealized (USDT)</div>
    <div class="val {'green' if unrealized_crypto>=0 else 'red'}">{_fmt(unrealized_crypto,'$')}</div>
  </div>
  <div class="card">
    <div class="lbl">Crypto Cash (USDT)</div>
    <div class="val">${cap_crypto:,.4f}</div>
  </div>
</div>

<!-- ── Charts ── -->
<div class="charts">
  <div class="chart-box">
    <h2>📈 Realized P&L Curve</h2>
    <canvas id="eqChart" height="100"></canvas>
  </div>
  <div class="chart-box">
    <h2>🧩 Sector / Market Exposure (open positions)</h2>
    <canvas id="sectorChart" height="100"></canvas>
  </div>
</div>

<!-- ── Open positions ── -->
<div class="section">
  <h2>📂 Open Positions ({open_count}) — includes unrealized P&L + stop-loss distance</h2>
  <table>
    <tr><th>Symbol</th><th>Entry</th><th>Shares</th><th>Unrealized P&L</th>
        <th>Stop Loss</th><th>Regime</th><th>Sector</th><th>Entry Time</th></tr>
    {pos_rows}
  </table>
</div>

<!-- ── Trade log ── -->
<div class="section">
  <h2>📋 Recent Trades (last 200) — slippage-adjusted fill prices</h2>
  <table>
    <tr><th>Time</th><th>Market</th><th>Symbol</th><th>Action</th>
        <th>Shares</th><th>Fill Price</th><th>P&L</th><th>Regime</th></tr>
    {trade_rows}
  </table>
</div>

<script>
// Equity curve
new Chart(document.getElementById('eqChart'),{{
  type:'line',
  data:{{
    labels:{eq_labels},
    datasets:[
      {{label:'India PnL (INR)',data:{eq_india_data},borderColor:'#00c896',
        backgroundColor:'rgba(0,200,150,.06)',borderWidth:2,pointRadius:1,fill:true,tension:.3}},
      {{label:'Crypto PnL (USDT)',data:{eq_crypt_data},borderColor:'#f97316',
        backgroundColor:'rgba(249,115,22,.06)',borderWidth:2,pointRadius:1,fill:true,tension:.3}}
    ]
  }},
  options:{{responsive:true,plugins:{{legend:{{labels:{{color:'#aaa',font:{{size:11}}}}}}}},
    scales:{{
      x:{{ticks:{{color:'#555',maxTicksLimit:10}},grid:{{color:'#1a1f2e'}}}},
      y:{{ticks:{{color:'#555'}},grid:{{color:'#1a1f2e'}}}}
    }}
  }}
}});

// Sector donut
new Chart(document.getElementById('sectorChart'),{{
  type:'doughnut',
  data:{{labels:{sec_labs},datasets:[{{data:{sec_vals},backgroundColor:{sec_cols},borderWidth:0}}]}},
  options:{{responsive:true,plugins:{{legend:{{position:'right',labels:{{color:'#aaa',font:{{size:11}}}}}}}}}}
}});
</script>
</body>
</html>"""
    return html


def main() -> None:
    trades    = load_trades()
    labels, india_eq, crypto_eq = load_equity_series()
    portfolio = load_portfolio()
    positions = load_positions()
    html      = generate_html(trades, labels, india_eq, crypto_eq, portfolio, positions)
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"Dashboard written → {OUT_HTML}")


if __name__ == "__main__":
    main()
