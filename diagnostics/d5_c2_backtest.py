"""
D5 — C2 Momentum-Breakout Backtest (read-only).

Replays C2 strategy logic on 12 months of 4H OHLCV + daily F&G index.
Universe: BTC/USDT, ETH/USDT (matches live C2's hard-coded universe).

Variants:
  baseline         — all gates on (F&G > 40 AND EMA12 > EMA26)
  no_fg            — F&G filter removed
  no_ema           — EMA trend filter removed
  no_fg_no_ema     — both filters removed

Per-symbol per-variant metrics:
  - trade_count, win_rate, avg_return_pct
  - annualized Sharpe (daily-equity-curve, sqrt(365))
  - max_drawdown (equity curve based)
  - profit_factor (gross_wins / abs(gross_losses))

Outputs:
  /app/data/diagnostics/d5_c2_trades_<sym>_<variant>.csv
  /app/data/diagnostics/d5_c2_equity_<sym>_<variant>.csv
  /app/data/diagnostics/d5_c2_summary.json

Run inside aaats-paper-crypto:
    docker exec aaats-paper-crypto python /app/diagnostics/d5_c2_backtest.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.request import urlopen, Request

import ccxt
import numpy as np
import pandas as pd

OUT = Path("/app/data/diagnostics")
OUT.mkdir(parents=True, exist_ok=True)

# Strategy constants — copied verbatim from trading/momentum_breakout.py
SYMBOLS = ["BTC/USDT", "ETH/USDT"]
CAPITAL_PCT       = 0.06
BREAKOUT_BARS     = 20
RSI_ENTRY_MIN     = 52
VOL_MULT          = 1.4
TARGET_PCT        = 0.020
STOP_PCT          = 0.012
TIME_STOP_HOURS   = 8
TIME_STOP_MIN_PCT = 0.008
STAGNATION_PCT    = 0.003
FG_MIN            = 40

N_BARS_4H_YEAR = 365 * 6     # ~2190 bars
INITIAL_EQUITY = 1.0


# ----------------------------------------------------------------------------
# Data fetching
# ----------------------------------------------------------------------------
def fetch_4h_year(symbol: str) -> pd.DataFrame:
    ex = ccxt.binance({"enableRateLimit": True})
    rows: list = []
    last_ts = ex.milliseconds()
    while len(rows) < N_BARS_4H_YEAR:
        target_since = last_ts - 1000 * 4 * 3600 * 1000
        batch = ex.fetch_ohlcv(symbol, "4h", since=target_since, limit=1000)
        if not batch:
            break
        rows = batch + rows
        oldest = batch[0][0]
        if oldest >= last_ts:
            break
        last_ts = oldest - 1
        if len(batch) < 1000:
            break
    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="ts_ms").sort_values("ts_ms")
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df = df.set_index("ts").drop(columns="ts_ms")
    return df.iloc[-N_BARS_4H_YEAR:]


def fetch_fg_history(days: int = 400) -> pd.Series:
    """Fetch daily Fear & Greed index from alternative.me. Returns Series indexed by date."""
    url = f"https://api.alternative.me/fng/?limit={days}&format=json"
    req = Request(url, headers={"User-Agent": "AAATS/1.0"})
    with urlopen(req, timeout=20) as r:
        data = json.loads(r.read())
    rows = [(int(x["timestamp"]), int(x["value"])) for x in data["data"]]
    df = pd.DataFrame(rows, columns=["ts_s", "fg"])
    df["ts"] = pd.to_datetime(df["ts_s"], unit="s", utc=True)
    df = df.set_index("ts").sort_index()
    return df["fg"]


# ----------------------------------------------------------------------------
# Feature engineering — matches what live C2 computes after _resample_4h + _add_indicators
# ----------------------------------------------------------------------------
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close = out["close"]
    volume = out["volume"]

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out["rsi_14"] = 100 - (100 / (1 + rs))

    out["ema_12"] = close.ewm(span=12, adjust=False).mean()
    out["ema_26"] = close.ewm(span=26, adjust=False).mean()

    out["rolling_high_20"] = out["high"].rolling(BREAKOUT_BARS).max().shift(1)
    out["vol_avg_20"] = volume.rolling(BREAKOUT_BARS).mean()

    return out.dropna(subset=["rsi_14", "rolling_high_20", "vol_avg_20"])


def attach_fg(df: pd.DataFrame, fg_series: pd.Series) -> pd.DataFrame:
    """Forward-fill daily F&G onto each 4H bar."""
    fg_daily = fg_series.resample("1D").last()  # already daily, just align
    out = df.copy()
    out["fg"] = fg_daily.reindex(out.index, method="ffill").fillna(50).astype(int)
    return out


# ----------------------------------------------------------------------------
# Backtest engine
# ----------------------------------------------------------------------------
def entry_ok(row, *, use_fg: bool, use_ema: bool) -> bool:
    breakout = row["close"] > row["rolling_high_20"]
    rsi_ok = row["rsi_14"] > RSI_ENTRY_MIN
    vol_ok = row["vol_avg_20"] > 0 and (row["volume"] / row["vol_avg_20"]) >= VOL_MULT
    bull_reg = (row["ema_12"] > row["ema_26"]) if use_ema else True
    fg_ok = (row["fg"] >= FG_MIN) if use_fg else True
    return bool(breakout and rsi_ok and vol_ok and bull_reg and fg_ok)


def check_exit(pos: dict, current_price: float, current_ts: pd.Timestamp,
               last_4h_close: float) -> tuple[bool, str]:
    entry = pos["entry_price"]
    pct = (current_price - entry) / entry

    if pct >= TARGET_PCT:
        return True, f"target({pct:.2%})"
    if pct <= -STOP_PCT:
        return True, f"hard_stop({pct:.2%})"

    age_h = (current_ts - pos["entry_ts"]).total_seconds() / 3600.0
    if age_h >= TIME_STOP_HOURS and pct < TIME_STOP_MIN_PCT:
        return True, f"time_stop(age={age_h:.1f}h,pct={pct:.2%})"

    if age_h >= 4.0:
        last_close = pos.get("last_4h_close", entry)
        if last_close > 0:
            move = abs(current_price - last_close) / last_close
            if move < STAGNATION_PCT:
                return True, f"stagnation(move={move:.3%})"

    return False, ""


def backtest_symbol(df: pd.DataFrame, *, use_fg: bool, use_ema: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (trades_df, equity_curve_df)."""
    equity = INITIAL_EQUITY
    pos: dict | None = None
    trades: list[dict] = []
    equity_rows: list[dict] = []

    for ts, row in df.iterrows():
        if pos is not None:
            exit_now, reason = check_exit(pos, float(row["close"]), ts, pos.get("last_4h_close", pos["entry_price"]))
            # Track 4H rolling close
            pos["last_4h_close"] = float(row["close"])
            if exit_now:
                exit_price = float(row["close"])
                ret_pct = (exit_price - pos["entry_price"]) / pos["entry_price"]
                # Compound 6% of equity at risk
                equity *= (1.0 + ret_pct * CAPITAL_PCT)
                trades.append({
                    "entry_ts":    pos["entry_ts"].isoformat(),
                    "exit_ts":     ts.isoformat(),
                    "entry_price": pos["entry_price"],
                    "exit_price":  exit_price,
                    "return_pct":  round(ret_pct, 6),
                    "reason":      reason,
                    "age_h":       round((ts - pos["entry_ts"]).total_seconds() / 3600.0, 2),
                })
                pos = None

        if pos is None:
            if entry_ok(row, use_fg=use_fg, use_ema=use_ema):
                pos = {
                    "entry_ts":    ts,
                    "entry_price": float(row["close"]),
                    "last_4h_close": float(row["close"]),
                }

        equity_rows.append({"ts": ts.isoformat(), "equity": equity})

    # Close any dangling position at last close
    if pos is not None:
        last_ts = df.index[-1]
        exit_price = float(df["close"].iloc[-1])
        ret_pct = (exit_price - pos["entry_price"]) / pos["entry_price"]
        equity *= (1.0 + ret_pct * CAPITAL_PCT)
        trades.append({
            "entry_ts":    pos["entry_ts"].isoformat(),
            "exit_ts":     last_ts.isoformat(),
            "entry_price": pos["entry_price"],
            "exit_price":  exit_price,
            "return_pct":  round(ret_pct, 6),
            "reason":      "end_of_data",
            "age_h":       round((last_ts - pos["entry_ts"]).total_seconds() / 3600.0, 2),
        })

    return pd.DataFrame(trades), pd.DataFrame(equity_rows)


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
def compute_metrics(trades: pd.DataFrame, equity: pd.DataFrame) -> dict:
    n = len(trades)
    if n == 0:
        return {
            "trade_count": 0, "win_rate": None, "avg_return_pct": None,
            "sharpe_ratio_annualized": None, "max_drawdown_pct": None,
            "profit_factor": None, "final_equity": float(equity["equity"].iloc[-1]) if len(equity) else 1.0,
        }

    rets = trades["return_pct"].astype(float)
    wins = rets[rets > 0]
    losses = rets[rets < 0]

    profit_factor = float(wins.sum() / abs(losses.sum())) if len(losses) and abs(losses.sum()) > 0 else float("inf")

    # Daily equity curve for Sharpe
    eq = equity.copy()
    eq["ts"] = pd.to_datetime(eq["ts"])
    eq = eq.set_index("ts").resample("1D").last().dropna()
    daily_ret = eq["equity"].pct_change().dropna()
    if len(daily_ret) > 5 and daily_ret.std() > 0:
        sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(365))
    else:
        sharpe = None

    eq_running_max = eq["equity"].cummax()
    drawdown = (eq["equity"] - eq_running_max) / eq_running_max
    max_dd = float(drawdown.min()) if len(drawdown) else 0.0

    return {
        "trade_count":     int(n),
        "win_rate":        round(float((rets > 0).mean()), 4),
        "avg_return_pct":  round(float(rets.mean()) * 100, 4),
        "sharpe_ratio_annualized": round(sharpe, 3) if sharpe is not None else None,
        "max_drawdown_pct": round(max_dd * 100, 3),
        "profit_factor":   round(profit_factor, 3) if profit_factor != float("inf") else "inf",
        "final_equity":    round(float(eq["equity"].iloc[-1]), 6),
        "total_return_pct": round((float(eq["equity"].iloc[-1]) - 1.0) * 100, 3),
    }


def verdict(m: dict) -> str:
    if m["trade_count"] is None or m["trade_count"] < 10:
        return "BROKEN"
    if m["sharpe_ratio_annualized"] is None or m["profit_factor"] is None:
        return "BROKEN"
    s = m["sharpe_ratio_annualized"]
    pf = m["profit_factor"] if m["profit_factor"] != "inf" else 99.9
    if s > 1.0 and pf > 1.3 and m["trade_count"] >= 30:
        return "VIABLE"
    if s < 0.5 or pf < 1.0:
        return "BROKEN"
    return "MARGINAL"


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
VARIANTS = [
    ("baseline",      True,  True),
    ("no_fg",         False, True),
    ("no_ema",        True,  False),
    ("no_fg_no_ema",  False, False),
]


def main() -> int:
    print("== D5 C2 momentum backtest ==")
    print(f"Universe: {SYMBOLS}")
    print(f"Variants: {[v[0] for v in VARIANTS]}")

    fg = fetch_fg_history(days=400)
    print(f"F&G fetched: {len(fg)} daily points  range [{fg.index[0].date()} .. {fg.index[-1].date()}]")

    summary: dict = {"variants": {v[0]: {"by_symbol": {}} for v in VARIANTS}}

    for sym in SYMBOLS:
        print(f"\n--- {sym} ---")
        df = fetch_4h_year(sym)
        print(f"  fetched {len(df)} 4h bars  range [{df.index[0].date()} .. {df.index[-1].date()}]")
        df = add_indicators(df)
        df = attach_fg(df, fg)
        print(f"  after indicators+fg: {len(df)} bars")

        for vname, use_fg, use_ema in VARIANTS:
            trades, equity = backtest_symbol(df, use_fg=use_fg, use_ema=use_ema)
            m = compute_metrics(trades, equity)
            v = verdict(m)
            m["verdict"] = v

            label = f"{sym.replace('/', '_')}_{vname}"
            trades.to_csv(OUT / f"d5_c2_trades_{label}.csv", index=False)
            equity.to_csv(OUT / f"d5_c2_equity_{label}.csv", index=False)
            summary["variants"][vname]["by_symbol"][sym] = m
            print(f"  [{vname:15s}] trades={m['trade_count']:3d} "
                  f"WR={m['win_rate']}  avg={m['avg_return_pct']}%  "
                  f"sharpe={m['sharpe_ratio_annualized']}  PF={m['profit_factor']}  "
                  f"DD={m['max_drawdown_pct']}%  totRet={m['total_return_pct']}%  -> {v}")

    summary["meta"] = {
        "n_bars_4h_target":      N_BARS_4H_YEAR,
        "capital_pct_per_trade": CAPITAL_PCT,
        "thresholds": {
            "viable_min_sharpe":  1.0,
            "viable_min_pf":      1.3,
            "viable_min_trades":  30,
        },
    }
    (OUT / "d5_c2_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n[OK] wrote {OUT}/d5_c2_summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
