"""
India equity paper trading runner — Angel One SmartAPI.

Each cycle (every 15 min during market hours, skipped outside):
  1. Renew Angel One session via TOTP (once per day)
  2. Fetch daily OHLCV for each Nifty 50 stock
  3. Compute features + detect regime
  4. Generate signal (EMA crossover + RSI)
  5. Paper trade → data/paper_trades.db

Market hours: NSE 09:15–15:30 IST, Mon–Fri
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytz
import pyotp

from foundation.logger import get_logger
from foundation.kill_switch import is_halted
from execution.paper_trader import record_trade
from execution.status_db import upsert_status
from execution.market_hours import require_market_open
from indicators.regime_detector import RegimeDetectorConfig, get_current_regime
from risk.position_manager import PersistentPositionManager
from risk.position_sizer import PositionSizer
from risk.drawdown_monitor import DrawdownMonitor
from risk.settlement_manager import SettlementManager
from risk.correlation_monitor import CorrelationMonitor
from analytics.pnl_attribution import PnLAttribution
from analytics.slippage_tracker import SlippageTracker
from execution.order_validator import OrderValidator

_log = get_logger("execution", "india_runner")

_IST = pytz.timezone("Asia/Kolkata")
_DB = str(Path(__file__).parent.parent / "data" / "paper_trades.db")
_CAPITAL_INR = 500_000.0   # ₹5 lakh simulated capital
_POSITION_PCT = 0.05       # 5% per trade
_POLL_SECONDS = 900        # 15 min

# Top Nifty 50 watchlist: (symbol, angel_token, exchange)
_WATCHLIST = [
    ("RELIANCE",   "2885",  "NSE"),
    ("TCS",        "11536", "NSE"),
    ("HDFCBANK",   "1333",  "NSE"),
    ("INFY",       "1594",  "NSE"),
    ("ICICIBANK",  "4963",  "NSE"),
    ("HINDUNILVR", "1394",  "NSE"),
    ("SBIN",       "3045",  "NSE"),
    ("BAJFINANCE", "317",   "NSE"),
    ("BHARTIARTL", "10604", "NSE"),
    ("KOTAKBANK",  "1922",  "NSE"),
    ("LT",         "11483", "NSE"),
    ("ASIANPAINT", "236",   "NSE"),
    ("AXISBANK",   "5900",  "NSE"),
    ("MARUTI",     "10999", "NSE"),
    ("WIPRO",      "3787",  "NSE"),
    ("SUNPHARMA",  "3351",  "NSE"),
    ("TITAN",      "3506",  "NSE"),
    ("HCLTECH",    "7229",  "NSE"),
    ("ITC",        "1660",  "NSE"),
    ("NESTLEIND",  "17963", "NSE"),
]

_REGIME_CFG = RegimeDetectorConfig(
    atr_pct_high_vol=0.03,
    ema_pct_band=0.01,
    adx_trend_threshold=25.0,
    adx_range_threshold=20.0,
)


def _is_market_open() -> bool:
    now = datetime.now(_IST)
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def _get_smart_client(api_key: str, client_id: str, pin: str, totp_secret: str):
    from SmartApi import SmartConnect
    client = SmartConnect(api_key=api_key)
    totp = pyotp.TOTP(totp_secret).now()
    resp = client.generateSession(client_id, pin, totp)
    if not resp or not resp.get("status"):
        raise RuntimeError(f"Angel One auth failed: {resp}")
    _log.info(f"Angel One session established for {client_id}")
    return client


def _compute_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema_50"] = out["close"].ewm(span=50, adjust=False).mean()
    out["ema_200"] = out["close"].ewm(span=200, adjust=False).mean()
    out["ema_spread_pct"] = (out["ema_50"] - out["ema_200"]) / out["ema_200"].replace(0, float("nan"))
    delta = out["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    out["rsi_14"] = 100 - (100 / (1 + rs))
    hl = out["high"] - out["low"]
    hc = (out["high"] - out["close"].shift()).abs()
    lc = (out["low"] - out["close"].shift()).abs()
    out["atr_14"] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()
    return out


def _signal(regime: str, bar: dict) -> str:
    rsi = bar.get("rsi_14", 50)
    if regime == "BULL_TREND" and rsi < 65:
        return "BUY"
    if regime in ("BEAR_TREND", "HIGH_VOLATILITY"):
        return "SELL"
    return "HOLD"


def _fetch_ohlcv(symbol: str, token: str, exchange: str, client) -> pd.DataFrame:
    """Fetch 300 daily bars from Angel One."""
    from_date = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d %H:%M")
    to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    params = {
        "exchange": exchange,
        "symboltoken": token,
        "interval": "ONE_DAY",
        "fromdate": from_date,
        "todate": to_date,
    }
    resp = client.getCandleData(params)
    if not resp or not resp.get("status") or not resp.get("data"):
        return pd.DataFrame()
    rows = []
    for bar in resp["data"]:
        rows.append({
            "timestamp": pd.to_datetime(bar[0]),
            "open": float(bar[1]),
            "high": float(bar[2]),
            "low": float(bar[3]),
            "close": float(bar[4]),
            "volume": float(bar[5]),
        })
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


def run_once(api_key: str, client_id: str, pin: str, totp_secret: str) -> int:
    """Run one full India equity cycle. Returns number of trades executed."""
    if is_halted("india"):
        _log.warning("India market HALTED — skipping cycle")
        upsert_status("india", status="HALTED")
        return 0
    if not require_market_open("india"):
        upsert_status("india", status="MARKET_CLOSED")
        return 0
    upsert_status("india", status="RUNNING")
    trades_done = 0
    pm = PersistentPositionManager(market="india")
    sizer = PositionSizer(capital=_CAPITAL_INR)
    dd_monitor = DrawdownMonitor(market="india", initial_equity=_CAPITAL_INR)
    settlement = SettlementManager()
    corr = CorrelationMonitor()
    pnl_attr = PnLAttribution()
    slippage = SlippageTracker()
    validator = OrderValidator(market="india")

    try:
        client = _get_smart_client(api_key, client_id, pin, totp_secret)
    except Exception as exc:
        _log.error(f"Angel One auth failed: {exc}")
        upsert_status("india", status="ERROR", error=str(exc))
        return 0

    regimes_seen = []
    for symbol, token, exchange in _WATCHLIST:
        try:
            df = _fetch_ohlcv(symbol, token, exchange, client)
            if df.empty or len(df) < 50:
                _log.warning(f"{symbol}: insufficient data ({len(df)} bars)")
                continue

            df = _compute_features(df)
            regime = get_current_regime(df, _REGIME_CFG)
            regimes_seen.append(regime)
            bar = df.iloc[-1].to_dict()
            price = bar.get("close", 0.0)
            sig = _signal(regime, bar)
            _log.info(f"{symbol} | regime={regime} | signal={sig} | price={price:.2f}")

            if sig == "BUY" and not pm.has_open_position(symbol):
                open_pos = pm.get_open_positions()
                existing_syms = [p["symbol"] for p in open_pos]
                corr_ok, corr_reason = corr.check_correlation(symbol, existing_syms)
                if not corr_ok:
                    _log.info(f"{symbol}: skipped — {corr_reason}")
                    continue
                atr = bar.get("atr_14", price * 0.02)
                size = sizer.calculate_position_size(price=price, atr=atr)
                shares = round(size.shares, 2) or round((_CAPITAL_INR * _POSITION_PCT) / price, 2)
                vr = validator.validate(symbol=symbol, price=price, shares=shares)
                if not vr.valid:
                    _log.warning(f"{symbol}: order rejected — {vr.reason}")
                    continue
                pm.open_position(symbol, entry_price=price, shares=shares)
                settlement.record_trade_settlement(symbol, "BUY", shares=shares, price=price)
                record_trade(
                    db_path=_DB, market="india", symbol=symbol,
                    action="BUY", shares=shares, price=price,
                    signal=sig, regime=regime,
                )
                sizer.add_position_heat(size.risk_pct)
                trades_done += 1

            elif sig == "SELL" and pm.has_open_position(symbol):
                open_positions = pm.get_open_positions()
                entry_pos = next((p for p in open_positions if p["symbol"] == symbol), None)
                entry = entry_pos["entry_price"] if entry_pos else price
                shares = round((_CAPITAL_INR * _POSITION_PCT) / max(entry, 1e-9), 2)
                pnl = pm.close_position(symbol, exit_price=price) or 0.0
                settlement.record_trade_settlement(symbol, "SELL", shares=shares, price=price)
                slippage.record_slippage(symbol, expected=entry, actual=price, side="SELL", market="india", shares=shares)
                pnl_attr.record_trade(
                    market="india", symbol=symbol, pnl=pnl, side="SELL",
                    regime=regime, entry_price=entry, exit_price=price, shares=shares,
                )
                record_trade(
                    db_path=_DB, market="india", symbol=symbol,
                    action="SELL", shares=shares, price=price,
                    signal=sig, regime=regime, pnl=pnl,
                )
                dd_monitor.update(_CAPITAL_INR + pnl_attr.total_pnl("india"))
                trades_done += 1

        except Exception as exc:
            _log.error(f"{symbol}: error — {exc}")
            continue

    dominant = max(set(regimes_seen), key=regimes_seen.count) if regimes_seen else "UNKNOWN"
    upsert_status(
        "india",
        regime=dominant,
        symbols_scanned=len(regimes_seen),
        trades_today=trades_done,
        status="OK",
    )
    return trades_done


def run_loop(api_key: str, client_id: str, pin: str, totp_secret: str,
             poll_seconds: int = _POLL_SECONDS) -> None:
    """Continuous loop. Skips cycles outside market hours."""
    _log.info("India equity paper trading loop started.")
    while True:
        try:
            if _is_market_open():
                run_once(api_key, client_id, pin, totp_secret)
            else:
                now_ist = datetime.now(_IST).strftime("%H:%M IST")
                _log.info(f"NSE market closed ({now_ist}) — sleeping.")
                upsert_status("india", status="MARKET_CLOSED")
        except KeyboardInterrupt:
            break
        except Exception as exc:
            _log.error(f"India loop error: {exc}")
            upsert_status("india", status="ERROR", error=str(exc))
        time.sleep(poll_seconds)
