"""
AAATS Paper Trading HTML Dashboard Generator
=============================================
Reads data/paper_trades.db + data/paper_portfolio.json + data/paper_positions.json
Outputs a self-contained HTML file: data/paper_report.html

Run after each paper_runner cycle (the bat file calls both):
  venv\\Scripts\\python.exe trading\\generate_report.py
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


def load_equity_series() -> list[dict]:
    """Reconstruct running P&L from SELL trades for equity curve."""
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT timestamp, market, pnl FROM paper_trades "
            "WHERE action='SELL' ORDER BY timestamp ASC"
        ).fetchall()
        running = 0.0
        series  = []
        for r in rows:
            running += (r["pnl"] or 0)
            series.append({"ts": r["timestamp"][:16], "pnl": round(running, 4),
                           "market": r["market"]})
        return series
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


# ── HTML generation ───────────────────────────────────────────────────────────

def _row_class(action: str) -> str:
    return "buy" if action == "BUY" else ("sell" if action == "SELL" else "")


def _pnl_color(val) -> str:
    if val is None:
        return ""
    try:
        return "green" if float(val) >= 0 else "red"
    except Exception:
        return ""


def _fmt_pnl(val, prefix="") -> str:
    if val is None or val == "":
        return "—"
    try:
        f = float(val)
        sign = "+" if f >= 0 else ""
        return f"{prefix}{sign}{f:,.4f}"
    except Exception:
        return str(val)


def generate_html(trades: list[dict], equity: list[dict],
                  portfolio: dict, positions: dict) -> str:

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Summary stats ─────────────────────────────────────────────────────────
    sells = [t for t in trades if t.get("action") == "SELL"]
    wins  = [t for t in sells if (t.get("pnl") or 0) > 0]
    win_rate = (len(wins) / len(sells) * 100) if sells else 0.0
    total_pnl_india  = portfolio.get("india",  {}).get("realized_pnl", 0.0)
    total_pnl_crypto = portfolio.get("crypto", {}).get("realized_pnl", 0.0)
    total_trades     = len(trades)
    open_india  = positions.get("india",  {})
    open_crypto = positions.get("crypto", {})
    open_count  = len(open_india) + len(open_crypto)

    cap_india  = portfolio.get("india",  {}).get("capital", 0)
    cap_crypto = portfolio.get("crypto", {}).get("capital", 0)

    # ── Equity chart data ─────────────────────────────────────────────────────
    eq_labels = json.dumps([e["ts"] for e in equity])
    eq_data   = json.dumps([e["pnl"] for e in equity])

    # ── Trade rows ────────────────────────────────────────────────────────────
    trade_rows = ""
    for t in trades[:200]:
        rc  = _row_class(t.get("action", ""))
        pnl = _fmt_pnl(t.get("pnl"))
        pc  = _pnl_color(t.get("pnl"))
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

    # ── Open positions rows ───────────────────────────────────────────────────
    pos_rows = ""
    for sym, pos in {**{f"🇮🇳 {s}": v for s, v in open_india.items()},
                     **{f"₿ {s}": v for s, v in open_crypto.items()}}.items():
        pos_rows += (
            f'<tr>'
            f'<td>{sym}</td>'
            f'<td>{pos.get("entry_price",0):.4f}</td>'
            f'<td>{float(pos.get("shares",0)):.6f}</td>'
            f'<td>{pos.get("regime","")}</td>'
            f'<td>{(pos.get("entry_time","")[:16])}</td>'
            f'</tr>\n'
        )
    if not pos_rows:
        pos_rows = '<tr><td colspan="5" style="text-align:center;color:#888">No open positions</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="300">
<title>AAATS Paper Trading Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', sans-serif; background: #0f1117; color: #e0e0e0; padding: 20px; }}
  h1 {{ color: #00d4ff; font-size: 1.4rem; margin-bottom: 4px; }}
  .sub {{ color: #888; font-size: 0.8rem; margin-bottom: 20px; }}
  .cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 24px; }}
  .card {{ background: #1a1d27; border-radius: 10px; padding: 16px 20px; min-width: 160px; }}
  .card .label {{ font-size: 0.72rem; color: #888; text-transform: uppercase; letter-spacing: .05em; }}
  .card .value {{ font-size: 1.5rem; font-weight: 700; margin-top: 4px; }}
  .green {{ color: #00c896; }} .red {{ color: #ff4d6d; }} .blue {{ color: #00d4ff; }}
  .chart-box {{ background: #1a1d27; border-radius: 10px; padding: 16px; margin-bottom: 24px; }}
  .chart-box h2 {{ font-size: 0.9rem; color: #aaa; margin-bottom: 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  th {{ background: #1e2230; color: #aaa; padding: 8px 10px; text-align: left;
        font-weight: 600; letter-spacing: .04em; }}
  td {{ padding: 7px 10px; border-bottom: 1px solid #1e2230; }}
  tr:hover td {{ background: #1e2230; }}
  tr.buy td {{ border-left: 3px solid #00c896; }}
  tr.sell td {{ border-left: 3px solid #ff4d6d; }}
  .section {{ background: #1a1d27; border-radius: 10px; padding: 16px; margin-bottom: 20px; }}
  .section h2 {{ font-size: 0.9rem; color: #aaa; margin-bottom: 12px; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:0.75rem;
            font-weight:700; }}
  .badge-buy  {{ background:#00c89622; color:#00c896; }}
  .badge-sell {{ background:#ff4d6d22; color:#ff4d6d; }}
</style>
</head>
<body>

<h1>⚡ AAATS Paper Trading Dashboard</h1>
<p class="sub">Last updated: {now_str} &nbsp;|&nbsp; Auto-refreshes every 5 min</p>

<div class="cards">
  <div class="card">
    <div class="label">Total Trades</div>
    <div class="value blue">{total_trades}</div>
  </div>
  <div class="card">
    <div class="label">Open Positions</div>
    <div class="value blue">{open_count}</div>
  </div>
  <div class="card">
    <div class="label">Win Rate</div>
    <div class="value {'green' if win_rate>=50 else 'red'}">{win_rate:.1f}%</div>
  </div>
  <div class="card">
    <div class="label">India P&L (INR)</div>
    <div class="value {'green' if total_pnl_india>=0 else 'red'}">{'+' if total_pnl_india>=0 else ''}{total_pnl_india:,.0f}</div>
  </div>
  <div class="card">
    <div class="label">Crypto P&L (USDT)</div>
    <div class="value {'green' if total_pnl_crypto>=0 else 'red'}">{'+' if total_pnl_crypto>=0 else ''}{total_pnl_crypto:,.4f}</div>
  </div>
  <div class="card">
    <div class="label">India Capital</div>
    <div class="value">₹{cap_india:,.0f}</div>
  </div>
  <div class="card">
    <div class="label">Crypto Capital</div>
    <div class="value">${cap_crypto:,.2f}</div>
  </div>
</div>

<div class="chart-box">
  <h2>📈 Realized P&L Curve (mixed currency)</h2>
  <canvas id="equityChart" height="80"></canvas>
</div>

<div class="section">
  <h2>📂 Open Positions ({open_count})</h2>
  <table>
    <tr><th>Symbol</th><th>Entry Price</th><th>Shares</th><th>Regime</th><th>Entry Time</th></tr>
    {pos_rows}
  </table>
</div>

<div class="section">
  <h2>📋 Recent Trades (last 200)</h2>
  <table>
    <tr><th>Time</th><th>Market</th><th>Symbol</th><th>Action</th>
        <th>Shares</th><th>Price</th><th>P&L</th><th>Regime</th></tr>
    {trade_rows}
  </table>
</div>

<script>
const ctx = document.getElementById('equityChart').getContext('2d');
new Chart(ctx, {{
  type: 'line',
  data: {{
    labels: {eq_labels},
    datasets: [{{
      label: 'Cumulative P&L',
      data: {eq_data},
      borderColor: '#00d4ff',
      backgroundColor: 'rgba(0,212,255,0.08)',
      borderWidth: 2,
      pointRadius: 2,
      fill: true,
      tension: 0.3,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color:'#666', maxTicksLimit:12 }}, grid: {{ color:'#1e2230' }} }},
      y: {{ ticks: {{ color:'#666' }},               grid: {{ color:'#1e2230' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""
    return html


def main() -> None:
    trades    = load_trades()
    equity    = load_equity_series()
    portfolio = load_portfolio()
    positions = load_positions()
    html      = generate_html(trades, equity, portfolio, positions)
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"Report written → {OUT_HTML}")


if __name__ == "__main__":
    main()
