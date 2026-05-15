"""
AAATS Live Paper Trading Runner  v2 — Institutional Grade
==========================================================
Markets : India NSE (Angel One SmartAPI) + Crypto (Binance via CCXT)
Schedule: Hourly via Windows Task Scheduler

Upgrades over v1
----------------
✅ ATR-based position sizing  (PositionSizer — Kelly + 2×ATR stop + heat limit)
✅ RiskEngine gate on every order  (portfolio -20% / market -15% drawdown halts)
✅ Sector caps: max 2 open NSE positions per sector simultaneously
✅ VWAP deviation as 4th independent vote  (uncorrelated with EMA/RSI/MACD)
✅ Realistic slippage model  (NSE 0.05%, Crypto 0.10% Binance taker fee)
✅ Daily-bar HMM training at startup; hourly bars for execution signals
✅ Telegram alerts on every trade, halt, and error
✅ Angel One session refreshes at market open each day (not rolling 23 h)
✅ Rebalanced NSE watchlist: 20 stocks, 6 sectors, hard cap 2 open per sector
✅ Unrealized P&L tracked per position; total equity = cash + open book value
✅ Win-rate and avg-win/loss rolling stats for live Kelly calibration

State files (persist between runs)
-----------------------------------
  data/paper_positions.json   — open positions per market
  data/paper_portfolio.json   — cash, realized PnL, trade stats
  logs/paper_runner.log       — execution log

Run manually (from project root):
  venv\\Scripts\\python.exe trading\\live_paper_runner.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ── project root ──────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── AAATS imports ─────────────────────────────────────────────────────────────
from indicators.features import compute_features
from execution.paper_trader import record_trade
from execution.market_hours import is_market_open
from decision.consensus_voting import ConsensusVoting, StrategyVote
from risk.engine import RiskEngine, RiskDecision
from risk.position_sizer import PositionSizer
from observability.alerts import send_alert
from config.doctrine import LOCKED_STARTING_EQUITY

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH        = str(_ROOT / "data" / "paper_trades.db")
POSITIONS_FILE = _ROOT / "data" / "paper_positions.json"
PORTFOLIO_FILE = _ROOT / "data" / "paper_portfolio.json"
LOG_FILE       = _ROOT / "logs" / "paper_runner.log"
ENV_FILE       = _ROOT / ".env"

N_BARS_HOURLY  = 120   # hourly bars for signal generation (needs ≥50)
N_BARS_DAILY   = 500   # daily bars for HMM regime training

# Slippage model (fraction of price)
SLIPPAGE = {"india": 0.0005, "crypto": 0.001}   # NSE 0.05%, Binance 0.10%

# Portfolio heat caps
MAX_PORTFOLIO_HEAT = 0.20  # max 20 % total risk deployed
MAX_SECTOR_OPEN    = 2     # max open NSE positions per sector

# ── NSE watchlist: 20 stocks across 6 sectors ─────────────────────────────────
# (symbol, angel_token, exchange, sector)
NSE_WATCHLIST = [
    # Financials (6 stocks → max 2 open at a time)
    ("HDFCBANK",   "1333",  "NSE", "financials"),
    ("ICICIBANK",  "4963",  "NSE", "financials"),
    ("KOTAKBANK",  "1922",  "NSE", "financials"),
    ("SBIN",       "3045",  "NSE", "financials"),
    ("BAJFINANCE", "317",   "NSE", "financials"),
    ("AXISBANK",   "5900",  "NSE", "financials"),
    # IT (4 stocks → max 2 open)
    ("TCS",        "11536", "NSE", "it"),
    ("INFY",       "1594",  "NSE", "it"),
    ("HCLTECH",    "7229",  "NSE", "it"),
    ("WIPRO",      "3787",  "NSE", "it"),
    # Energy / Infra (2 stocks)
    ("RELIANCE",   "2885",  "NSE", "energy"),
    ("LT",         "11483", "NSE", "energy"),
    # Consumer / FMCG (4 stocks → max 2 open)
    ("HINDUNILVR", "1394",  "NSE", "consumer"),
    ("ITC",        "1660",  "NSE", "consumer"),
    ("NESTLEIND",  "17963", "NSE", "consumer"),
    ("ASIANPAINT", "236",   "NSE", "consumer"),
    # Auto (2 stocks)
    ("MARUTI",     "10999", "NSE", "auto"),
    ("BAJAJ-AUTO", "16669", "NSE", "auto"),
    # Pharma (2 stocks)
    ("SUNPHARMA",  "3351",  "NSE", "pharma"),
    ("DRREDDY",    "881",   "NSE", "pharma"),
]

# Crypto: diversified 6-symbol universe with lower intra-bucket correlation
# BTC dominance (BTC.D) fetched separately as a macro regime filter.
CRYPTO_SYMBOLS = [
    "BTC/USDT",    # anchor / store-of-value bucket
    "ETH/USDT",    # smart-contract platform bucket
    "SOL/USDT",    # alt L1 — BTC correlation ~0.70
    "LINK/USDT",   # oracle / DeFi infra — BTC beta ~0.65
    "DOT/USDT",    # cross-chain / parachain — lower DeFi correlation
    "AVAX/USDT",   # alt L1 — partially uncorrelated with SOL
]

# BTC dominance threshold: when BTC dominance > 58%, alts underperform — reduce alt exposure
BTC_DOMINANCE_CUTOFF = 58.0   # % — above this, skip SOL/LINK/DOT/AVAX BUYs

INITIAL_CAPITAL = {"india": 0.0, "crypto": 110.0}  # India halted (capital=0); Crypto budget=$110

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("paper_runner")


# ── .env parser ───────────────────────────────────────────────────────────────

def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.split("#")[0].strip()
    return env


_ENV = _load_env()


def _e(key: str, default: str = "") -> str:
    import os
    return os.environ.get(key, _ENV.get(key, default))


# ── State helpers ─────────────────────────────────────────────────────────────

def _load_json(path: Path, default: dict) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def load_positions() -> dict:
    return _load_json(POSITIONS_FILE, {"india": {}, "crypto": {}})


def save_positions(p: dict) -> None:
    _save_json(POSITIONS_FILE, p)


def load_portfolio() -> dict:
    default = {
        m: {
            "capital":           INITIAL_CAPITAL[m],
            "realized_pnl":      0.0,
            "total_trades":      0,
            "wins":              0,
            "losses":            0,
            "total_win_pct":     0.0,
            "total_loss_pct":    0.0,
            # T+1 settlement queue: list of {"amount": float, "settles_on": "YYYY-MM-DD"}
            "settlement_queue":  [],
        }
        for m in ("india", "crypto")
    }
    return _load_json(PORTFOLIO_FILE, default)


# ── T+1 Settlement queue (India NSE) ─────────────────────────────────────────

def _settle_pending_capital(portfolio: dict, market: str) -> None:
    """
    Move settled capital back into available balance.
    NSE T+1: proceeds from a SELL settle the next trading day.
    Call this at the start of each India cycle.
    """
    if market != "india":
        return
    p = portfolio[market]
    queue = p.get("settlement_queue", [])
    if not queue:
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    settled, pending = [], []
    for item in queue:
        if item["settles_on"] <= today:
            settled.append(item["amount"])
        else:
            pending.append(item)
    if settled:
        released = sum(settled)
        p["capital"] += released
        p["settlement_queue"] = pending
        log.info(f"  ✅ T+1 settled: ₹{released:,.0f} now available ({len(settled)} trade(s))")


def _queue_settlement(portfolio: dict, market: str, amount: float) -> None:
    """Lock SELL proceeds for T+1 settlement instead of releasing instantly."""
    if market != "india":
        return
    from datetime import timedelta
    # Find next trading day (skip weekends; holiday calendar in market_hours)
    settle_date = datetime.now(timezone.utc).date() + timedelta(days=1)
    while settle_date.weekday() >= 5:   # skip Saturday/Sunday
        settle_date += timedelta(days=1)
    portfolio[market].setdefault("settlement_queue", []).append({
        "amount":      amount,
        "settles_on":  settle_date.strftime("%Y-%m-%d"),
    })
    log.info(f"  🕐 T+1: ₹{amount:,.0f} queued → settles {settle_date}")


def save_portfolio(p: dict) -> None:
    _save_json(PORTFOLIO_FILE, p)


# ── Win-rate stats for Kelly calibration ──────────────────────────────────────

def _kelly_params(portfolio: dict, market: str) -> tuple[float, float, float]:
    """Return (win_rate, avg_win_pct, avg_loss_pct) from trade history."""
    p     = portfolio[market]
    wins  = max(1, p.get("wins", 0))
    total = max(2, p.get("total_trades", 0))
    win_rate  = wins / total
    avg_win   = p.get("total_win_pct", 0.03) / max(wins, 1)
    avg_loss  = p.get("total_loss_pct", 0.02) / max(total - wins, 1)
    return (
        max(0.35, min(0.70, win_rate)),
        max(0.01, avg_win),
        max(0.005, avg_loss),
    )


# ── Angel One session management ──────────────────────────────────────────────

_angel_client       = None
_angel_refresh_date = None   # date object — refresh once per calendar day


def _get_angel_client(force: bool = False):
    global _angel_client, _angel_refresh_date
    today = date.today()
    if not force and _angel_client and _angel_refresh_date == today:
        return _angel_client

    import pyotp
    from SmartApi import SmartConnect

    api_key   = _e("INDIA__ANGEL_API_KEY")
    client_id = _e("INDIA__ANGEL_CLIENT_ID")
    pin       = _e("INDIA__ANGEL_PIN")
    totp_sec  = _e("INDIA__ANGEL_TOTP_SECRET")

    if not all([api_key, client_id, pin, totp_sec]):
        raise RuntimeError("Angel One credentials missing from .env")

    client = SmartConnect(api_key=api_key)
    totp   = pyotp.TOTP(totp_sec).now()
    resp   = client.generateSession(client_id, pin, totp)

    if not resp or not resp.get("status"):
        raise RuntimeError(f"Angel One auth failed: {resp}")

    _angel_client       = client
    _angel_refresh_date = today
    log.info(f"Angel One session refreshed for {today}")
    return client


# ── Binance exchange singleton ────────────────────────────────────────────────

_binance = None


def _get_binance():
    global _binance
    if _binance:
        return _binance
    import ccxt
    _binance = ccxt.binance({
        "apiKey":          _e("CRYPTO__BINANCE_API_KEY"),
        "secret":          _e("CRYPTO__BINANCE_SECRET_KEY"),
        "enableRateLimit": True,
    })
    return _binance


# ── Regime pipeline cache (fitted on hourly bars, refreshed every 4H) ────────

_regime_pipes: dict[str, object] = {}        # symbol → fitted RegimePipeline
_regime_fit_ts: dict[str, datetime] = {}     # symbol → last fit timestamp
_REGIME_REFIT_HOURS = 4                      # refit HMM every 4 hours


def _fit_regime(symbol: str, hourly_df: pd.DataFrame) -> None:
    """Fit HMM regime pipeline on hourly bars and cache it with timestamp."""
    try:
        from intelligence.regime.regime_pipeline import RegimePipeline
        pipe = RegimePipeline()
        pipe.fit(hourly_df)                  # fits directly on hourly OHLCV
        _regime_pipes[symbol] = pipe
        _regime_fit_ts[symbol] = datetime.now(timezone.utc)
        log.debug(f"  HMM fitted for {symbol} ({len(hourly_df)} hourly bars)")
    except Exception as e:
        log.debug(f"  HMM fit skipped for {symbol}: {e}")


def _regime_is_stale(symbol: str) -> bool:
    """Return True if HMM was never fit or was fit more than 4H ago."""
    ts = _regime_fit_ts.get(symbol)
    if ts is None:
        return True
    age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    return age_h >= _REGIME_REFIT_HOURS


def detect_regime(symbol: str, hourly_features: pd.DataFrame) -> tuple[str, float]:
    """Use cached HMM pipeline if fresh, else rule-based fallback."""
    pipe = _regime_pipes.get(symbol)
    if pipe and not _regime_is_stale(symbol):
        try:
            sig = pipe.detect(hourly_features)
            return sig.label, sig.confidence
        except Exception:
            pass
    return _rule_regime(hourly_features)


def _rule_regime(f: pd.DataFrame) -> tuple[str, float]:
    last    = f.iloc[-1]
    adx     = float(last.get("adx_14",  0) or 0)
    ema12   = float(last.get("ema_12",  last.get("close", 1)) or 1)
    ema26   = float(last.get("ema_26",  last.get("close", 1)) or 1)
    close   = float(last.get("close",   1) or 1)
    atr14   = float(last.get("atr_14",  close * 0.01) or close * 0.01)
    atr_pct = atr14 / close if close else 0.01

    if atr_pct > 0.04:
        return "HIGH_VOLATILITY", 0.72
    if adx > 25:
        return ("BULL_TREND", min(0.5 + adx / 100, 0.95)) if ema12 > ema26 \
               else ("BEAR_TREND", min(0.5 + adx / 100, 0.95))
    return "RANGE_BOUND", 0.60


# ── Data fetching ─────────────────────────────────────────────────────────────

def _angel_candles(token: str, exchange: str,
                   interval: str, days_back: int) -> pd.DataFrame:
    client  = _get_angel_client()
    to_dt   = datetime.now()
    from_dt = to_dt - timedelta(days=days_back)
    params  = {
        "exchange":    exchange,
        "symboltoken": token,
        "interval":    interval,
        "fromdate":    from_dt.strftime("%Y-%m-%d %H:%M"),
        "todate":      to_dt.strftime("%Y-%m-%d %H:%M"),
    }
    resp = client.getCandleData(params)
    if not resp or not resp.get("status") or not resp.get("data"):
        return pd.DataFrame()
    rows = resp["data"]
    df   = pd.DataFrame([
        {"open": float(r[1]), "high": float(r[2]),
         "low":  float(r[3]), "close": float(r[4]),
         "volume": float(r[5])}
        for r in rows
    ], index=pd.to_datetime([r[0] for r in rows], utc=True))
    return df.sort_index()


def fetch_nse_daily(symbol: str, token: str, exchange: str) -> pd.DataFrame | None:
    """500 daily bars for HMM training."""
    try:
        df = _angel_candles(token, exchange, "ONE_DAY", 700)
        if len(df) < 100:
            return None
        return df.tail(N_BARS_DAILY)
    except Exception as e:
        log.debug(f"  {symbol} daily fetch: {e}")
        return None


def fetch_nse_hourly(symbol: str, token: str, exchange: str) -> pd.DataFrame | None:
    """120 hourly bars for signal generation."""
    try:
        df = _angel_candles(token, exchange, "ONE_HOUR", 14)
        if len(df) < 30:
            log.warning(f"  {symbol}: only {len(df)} hourly bars")
            return None
        return df.tail(N_BARS_HOURLY)
    except Exception as e:
        log.error(f"  {symbol} hourly fetch: {e}")
        return None


def fetch_crypto_daily(symbol: str) -> pd.DataFrame | None:
    """500 daily bars from Binance for HMM training."""
    try:
        exchange = _get_binance()
        ohlcv    = exchange.fetch_ohlcv(symbol, "1d", limit=N_BARS_DAILY)
        if not ohlcv or len(ohlcv) < 100:
            return None
        df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])
        df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df[["open","high","low","close","volume"]]
    except Exception as e:
        log.debug(f"  {symbol} daily fetch: {e}")
        return None


def fetch_btc_dominance() -> float:
    """
    Fetch approximate BTC dominance from Binance total market cap proxy.
    Falls back to 50.0 if unavailable (neutral — no suppression).

    Method: BTC/USDT 24h volume vs top-10 combined volume as a dominance proxy.
    Not a perfect replica of CoinMarketCap BTC.D, but directionally accurate
    and avoids external API dependencies.
    """
    try:
        ex = _get_binance()
        tickers = ex.fetch_tickers([
            "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
            "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
        ])
        total_vol = sum(
            (t.get("quoteVolume") or 0.0) for t in tickers.values()
        )
        btc_vol = (tickers.get("BTC/USDT") or {}).get("quoteVolume") or 0.0
        if total_vol > 0:
            dom = (btc_vol / total_vol) * 100.0
            log.info(f"  BTC dominance proxy: {dom:.1f}%")
            return dom
    except Exception as e:
        log.warning(f"  BTC dominance fetch failed (using 50.0): {e}")
    return 50.0


def fetch_crypto_hourly(symbol: str) -> pd.DataFrame | None:
    """120 hourly bars from Binance for signal generation."""
    try:
        exchange = _get_binance()
        ohlcv    = exchange.fetch_ohlcv(symbol, "1h", limit=N_BARS_HOURLY)
        if not ohlcv or len(ohlcv) < 30:
            log.warning(f"  {symbol}: insufficient bars")
            return None
        df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])
        df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df[["open","high","low","close","volume"]]
    except Exception as e:
        log.error(f"  {symbol} hourly fetch: {e}")
        return None


# ── Strategy votes ────────────────────────────────────────────────────────────

def _vote(sid: str, market: str, signal: str, conf: float) -> StrategyVote:
    return StrategyVote(
        strategy_id=sid, market=market, signal=signal,
        confidence=max(0.0, min(1.0, conf)),
        health_score=80.0,
        timestamp=datetime.now(timezone.utc).timestamp(),
    )


def vote_ema(f: pd.DataFrame, market: str, regime: str) -> StrategyVote:
    """EMA 12/26 crossover — trend following."""
    last, prev = f.iloc[-1], f.iloc[-2] if len(f) > 1 else f.iloc[-1]
    e12  = float(last.get("ema_12", 0) or 0)
    e26  = float(last.get("ema_26", 0) or 0)
    p12  = float(prev.get("ema_12", 0) or 0)
    p26  = float(prev.get("ema_26", 0) or 0)
    rsi  = float(last.get("rsi_14", 50) or 50)

    cross_up = (e12 > e26) and (p12 <= p26)
    cross_dn = (e12 < e26) and (p12 >= p26)

    if cross_up or (e12 > e26 and regime == "BULL_TREND" and rsi < 68):
        return _vote("ema_crossover", market, "BUY",  0.78 if cross_up else 0.55)
    if cross_dn or (e12 < e26 and regime == "BEAR_TREND" and rsi > 32):
        return _vote("ema_crossover", market, "SELL", 0.78 if cross_dn else 0.55)
    return _vote("ema_crossover", market, "HOLD", 0.55)


def vote_rsi(f: pd.DataFrame, market: str, regime: str) -> StrategyVote:
    """RSI mean-reversion — best in RANGE_BOUND."""
    rsi = float(f.iloc[-1].get("rsi_14", 50) or 50)
    w   = 0.80 if regime == "RANGE_BOUND" else 0.40
    if rsi < 30:
        return _vote("rsi_reversion", market, "BUY",  w * 0.90)
    if rsi > 70:
        return _vote("rsi_reversion", market, "SELL", w * 0.90)
    return _vote("rsi_reversion", market, "HOLD", 0.50)


def vote_momentum(f: pd.DataFrame, market: str, regime: str) -> StrategyVote:
    """Return-5 + MACD momentum — confirms trend direction."""
    last = f.iloc[-1]
    ret5 = float(last.get("return_5", 0) or 0)
    macd = float(last.get("macd",     0) or 0)
    sigL = float(last.get("macd_signal", 0) or 0)
    w    = 0.72 if regime in ("BULL_TREND", "BEAR_TREND") else 0.38
    if ret5 > 0.005 and macd > sigL:
        return _vote("momentum", market, "BUY",  w * 0.82)
    if ret5 < -0.005 and macd < sigL:
        return _vote("momentum", market, "SELL", w * 0.82)
    return _vote("momentum", market, "HOLD", 0.48)


def vote_vwap(f: pd.DataFrame, market: str, regime: str) -> StrategyVote:
    """
    VWAP deviation — genuinely uncorrelated with EMA/RSI/MACD.

    Logic (institutional price action):
      Price > VWAP → buyers are paying above average institutional cost → bullish
      Price < VWAP → sellers are dominant → bearish
    Confirmation needed from regime:
      Only emit strong signal when regime agrees.
    """
    last  = f.iloc[-1]
    close = float(last.get("close", 0) or 0)
    vwap  = float(last.get("vwap",  last.get("close", close)) or close)
    if vwap <= 0 or close <= 0:
        return _vote("vwap", market, "HOLD", 0.45)

    dev = (close - vwap) / vwap   # positive = price above VWAP

    # Strong VWAP signal: price ≥0.15% above VWAP in bull trend → BUY
    if dev > 0.0015 and regime in ("BULL_TREND", "RANGE_BOUND"):
        conf = min(0.75, 0.55 + abs(dev) * 40)
        return _vote("vwap", market, "BUY", conf)
    # Bearish: price ≥0.15% below VWAP in bear or high-vol regime
    if dev < -0.0015 and regime in ("BEAR_TREND", "HIGH_VOLATILITY"):
        conf = min(0.75, 0.55 + abs(dev) * 40)
        return _vote("vwap", market, "SELL", conf)
    return _vote("vwap", market, "HOLD", 0.48)


def vote_bollinger(f: pd.DataFrame, market: str, regime: str) -> StrategyVote:
    """
    Bollinger %B mean-reversion — strongest in RANGE_BOUND, suppressed in trends.

    bb_pct = (close - lower) / (upper - lower)
      < 0.10  → near/below lower band → BUY (oversold)
      > 0.90  → near/above upper band → SELL (overbought)
    """
    last   = f.iloc[-1]
    bb_pct = float(last.get("bb_pct", 0.5) or 0.5)
    w      = 0.78 if regime == "RANGE_BOUND" else 0.42
    if bb_pct < 0.10:
        return _vote("bollinger", market, "BUY",  w * (1.0 - bb_pct * 5))
    if bb_pct > 0.90:
        return _vote("bollinger", market, "SELL", w * ((bb_pct - 0.5) * 1.5))
    return _vote("bollinger", market, "HOLD", 0.48)


def vote_macd_hist(f: pd.DataFrame, market: str, regime: str) -> StrategyVote:
    """
    MACD histogram (macd - signal) — momentum acceleration.

    Independent of EMA/momentum: looks at the *rate of change* of MACD itself,
    which is the second derivative of price. Picks up turns earlier.
    """
    if len(f) < 2:
        return _vote("macd_hist", market, "HOLD", 0.45)
    last, prev = f.iloc[-1], f.iloc[-2]
    h_now  = float(last.get("macd_hist", 0) or 0)
    h_prev = float(prev.get("macd_hist", 0) or 0)
    rsi    = float(last.get("rsi_14", 50) or 50)

    rising  = h_now > h_prev
    falling = h_now < h_prev

    # Bullish: histogram positive AND rising → BUY confirmation
    if h_now > 0 and rising and rsi < 70:
        w = 0.74 if regime in ("BULL_TREND", "RANGE_BOUND") else 0.45
        return _vote("macd_hist", market, "BUY", w)
    # Bearish: histogram negative AND falling → SELL confirmation
    if h_now < 0 and falling and rsi > 30:
        w = 0.74 if regime in ("BEAR_TREND", "HIGH_VOLATILITY") else 0.45
        return _vote("macd_hist", market, "SELL", w)
    # Zero-line cross detection — early signal
    if h_prev <= 0 < h_now:
        return _vote("macd_hist", market, "BUY",  0.68)
    if h_prev >= 0 > h_now:
        return _vote("macd_hist", market, "SELL", 0.68)
    return _vote("macd_hist", market, "HOLD", 0.48)


# Lowered threshold (0.55 → 0.45) + 6 strategies (was 4) → more signals pass.
# 6 votes × 0.45 ≈ 3 votes minimum on the dominant side to clear consensus.
_voter = ConsensusVoting(
    min_agreement_threshold=0.45,
    veto_confidence_threshold=0.85,
    uncertainty_threshold=0.45,
)


def generate_signal(symbol: str, features: pd.DataFrame,
                    market: str) -> tuple[str, str, float]:
    """Returns (signal, regime, confidence)."""
    regime, r_conf = detect_regime(symbol, features)

    votes  = [
        vote_ema(features,        market, regime),
        vote_rsi(features,        market, regime),
        vote_momentum(features,   market, regime),
        vote_vwap(features,       market, regime),
        vote_bollinger(features,  market, regime),   # mean-reversion (strong in RANGE_BOUND)
        vote_macd_hist(features,  market, regime),   # momentum-of-momentum (early turns)
    ]
    result = _voter.vote(votes)
    signal = result.final_signal

    # HIGH_VOLATILITY override: only SELL (to reduce exposure), never BUY
    if regime == "HIGH_VOLATILITY" and r_conf > 0.65:
        if signal == "BUY":
            signal = "HOLD"

    log.info(
        f"    regime={regime}({r_conf:.2f}) "
        f"votes={result.vote_breakdown} → {signal} "
        f"(agree={result.agreement_score:.2f} conf={result.consensus_confidence:.2f})"
    )
    return signal, regime, result.consensus_confidence


# ── Risk + sizing ─────────────────────────────────────────────────────────────

_risk_engine: RiskEngine | None = None
_sizers: dict[str, PositionSizer] = {}


def _get_risk_engine(portfolio: dict) -> RiskEngine:
    global _risk_engine
    if _risk_engine is None:
        # Doctrinal seed: never derive starting equity from current cash, which
        # collapses to current_value after a state reset and silently masks
        # live drawdown. The peak is then loaded from STATE_FILE if present.
        _risk_engine = RiskEngine(initial_portfolio=LOCKED_STARTING_EQUITY)
    return _risk_engine


def _strategy_state_book_value() -> float:
    """
    Sum of size_usd across data/*_state.json from external strategies.

    The runner only owns positions written through ``execute()`` (those land
    in paper_positions.json). Standalone strategies — altcoin_reversion,
    bollinger_range, etc. — keep their own state files. Without counting
    them here the runner's mark-to-market equity collapses to cash alone
    and the kill switch over-reports drawdown after a restart.
    """
    data_dir = _ROOT / "data"
    if not data_dir.is_dir():
        return 0.0
    total = 0.0
    for state_file in data_dir.glob("*_state.json"):
        if "cooldown" in state_file.name:
            continue
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(state, dict):
            continue
        for pos in state.values():
            if not isinstance(pos, dict):
                continue
            try:
                size_usd = float(pos.get("size_usd", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if size_usd > 0:
                total += size_usd
    return total


def _compute_current_equity(
    positions: dict,
    portfolio: dict,
    market: str,
    symbol: str,
    last_price: float,
) -> float:
    """
    Total mark-to-market equity = cash across all markets + open book value
    (runner-tracked positions + standalone strategy state files).

    For the symbol currently being processed we use ``last_price``; for every
    other runner-tracked position we fall back to the stored ``entry_price``
    (the most recent mark we have on hand without re-querying the venue).
    Standalone strategy positions are valued at their last-recorded
    ``size_usd``; this is the canonical Source A used by the reconciler.
    """
    cash = sum(float(p.get("capital", 0.0) or 0.0) for p in portfolio.values())
    open_value = 0.0
    for mkt_name, mkt_positions in positions.items():
        for sym, pos in mkt_positions.items():
            shares = float(pos.get("shares", 0.0) or 0.0)
            if shares == 0.0:
                continue
            if mkt_name == market and sym == symbol:
                mark = float(last_price)
            else:
                mark = float(pos.get("entry_price", 0.0) or 0.0)
            open_value += shares * mark
    open_value += _strategy_state_book_value()
    return cash + open_value


def _get_sizer(market: str, capital: float) -> PositionSizer:
    if market not in _sizers:
        _sizers[market] = PositionSizer(
            capital=capital,
            max_position_pct=0.08,     # max 8% per position (Kelly will usually be less)
            max_portfolio_heat=MAX_PORTFOLIO_HEAT,
            kelly_fraction=0.5,
        )
    else:
        _sizers[market].update_capital(capital)
    return _sizers[market]


def _sector_count(positions: dict, sector: str) -> int:
    """Count open NSE positions in a given sector."""
    return sum(
        1 for sym, pos in positions["india"].items()
        if pos.get("sector") == sector
    )


# ── Circuit-breaker guard (India NSE) ────────────────────────────────────────

def _nse_circuit_tripped(features: pd.DataFrame, last_price: float) -> bool:
    """
    Return True if the stock is near its NSE intraday circuit-breaker band.
    NSE freezes trading at ±10% from previous close. We skip BUYs at ±9%
    to avoid chasing a halt and getting stuck in a position with no exit.
    """
    try:
        prev_close = float(features["close"].iloc[-2])
        if prev_close <= 0:
            return False
        move_pct = abs(last_price - prev_close) / prev_close
        if move_pct >= 0.09:
            log.info(
                f"    ⚡ Circuit breaker guard: {move_pct:.1%} move "
                f"(prev_close={prev_close:.2f}) — skip BUY"
            )
            return True
    except (IndexError, KeyError, TypeError):
        pass
    return False


# ── Slippage-adjusted fill price (with dynamic scaling for crypto) ─────────────

def _fill_price(price: float, action: str, market: str,
                features: pd.DataFrame | None = None) -> float:
    """
    India: fixed 0.05% (NSE market impact + brokerage).
    Crypto: dynamic — base 0.10% scaled by 24h volatility.
      - Low vol  (returns stddev < 1%): 0.10%
      - Normal   (1–3%):                0.15%
      - High vol (3–5%):                0.25%
      - Extreme  (>5%):                 0.40% cap
    """
    base_slip = SLIPPAGE.get(market, 0.001)

    if market == "crypto" and features is not None and len(features) >= 24:
        try:
            returns = features["close"].pct_change().dropna().tail(24)
            vol = float(returns.std())          # 24-bar rolling stddev of 1h returns
            if vol > 0.05:
                dyn_slip = 0.004                # 0.40% cap
            elif vol > 0.03:
                dyn_slip = 0.0025
            elif vol > 0.01:
                dyn_slip = 0.0015
            else:
                dyn_slip = base_slip            # 0.10% base
            if dyn_slip != base_slip:
                log.debug(f"    Dynamic slippage: {dyn_slip:.2%} (vol={vol:.3%})")
            base_slip = dyn_slip
        except Exception:
            pass

    return price * (1 + base_slip) if action == "BUY" else price * (1 - base_slip)


# ── Paper trade execution ─────────────────────────────────────────────────────

def execute(
    market: str,
    symbol: str,
    signal: str,
    regime: str,
    confidence: float,
    last_price: float,
    features: pd.DataFrame,
    positions: dict,
    portfolio: dict,
    sector: str = "",
    ml_size_scale: float = 1.0,   # XGBoost confidence multiplier (0.5 or 1.0)
    strategy: str = "",           # AAATS strategy ID for observability
) -> None:
    mkt_pos  = positions[market]
    mkt_port = portfolio[market]
    capital  = mkt_port["capital"]

    engine = _get_risk_engine(portfolio)
    sizer  = _get_sizer(market, capital)

    # ── Update risk engine with mark-to-market equity ─────────────────────
    # Cash alone hides drawdown: when capital is consumed by an open position
    # the cash balance falls but the equity is unchanged. Using cash + open
    # book value as the input lets the kill switch see the real picture.
    total_equity = _compute_current_equity(positions, portfolio, market, symbol, last_price)
    engine.update_portfolio(total_equity)
    decision = engine.update_market(market, capital)

    if decision.action in ("HALT_ALL", "HALT_MARKET"):
        log.warning(f"  🛑 RISK HALT [{market}]: {decision.reason}")
        send_alert(f"🛑 HALT {market.upper()} — {decision.reason}", market=market)
        return

    # ── BUY logic ──────────────────────────────────────────────────────────
    if signal == "BUY" and symbol not in mkt_pos:

        # Sector cap (NSE only)
        if market == "india" and sector and _sector_count(positions, sector) >= MAX_SECTOR_OPEN:
            log.info(f"    ⛔ Sector cap reached for '{sector}' — skip BUY {symbol}")
            return

        # Circuit-breaker guard (NSE only) — skip BUYs within 9% of daily band
        if market == "india" and _nse_circuit_tripped(features, last_price):
            return

        # ATR-based position sizing
        atr      = float(features.iloc[-1].get("atr_14", last_price * 0.015) or last_price * 0.015)
        win_rate, avg_win, avg_loss = _kelly_params(portfolio, market)
        size_res = sizer.calculate_position_size(last_price, atr, win_rate, avg_win, avg_loss)
        shares   = size_res.shares

        if shares <= 0:
            log.info(f"    ⚠️  Sizer returned 0 shares for {symbol} — skip")
            return

        # Risk engine gate
        gate = engine.check_new_order(market, last_price, shares, capital)
        if gate.action == "REDUCE":
            shares *= gate.allowed_fraction
        elif gate.action not in ("ALLOW", "REDUCE"):
            log.warning(f"    🛑 Risk gate blocked {symbol}: {gate.reason}")
            return

        # ML confidence scaling (0.5 = half size when model is uncertain)
        if ml_size_scale < 1.0:
            shares *= ml_size_scale
            log.info(f"    🤖 ML scale={ml_size_scale:.1f} → {shares:.6f} sh")

        fill    = _fill_price(last_price, "BUY", market, features)
        value   = shares * fill

        _entry_ts = datetime.now(timezone.utc).isoformat()
        record_trade(
            db_path=DB_PATH, market=market, symbol=symbol,
            action="BUY", shares=shares, price=fill,
            signal=signal, regime=regime, risk_action="ALLOW",
            note=f"atr={atr:.4f} kelly_w={win_rate:.2f} ml_scale={ml_size_scale:.1f}",
            strategy=strategy or f"{market}_directional",
            entry_time=_entry_ts, size_usd=round(value, 4),
            notes={"confidence": round(confidence, 4), "ml_scale": ml_size_scale,
                   "atr_entry": round(atr, 6), "risk_pct": round(size_res.risk_pct, 4)},
        )
        mkt_pos[symbol] = {
            "shares":      shares,
            "entry_price": fill,
            "entry_time":  datetime.now(timezone.utc).isoformat(),
            "regime":      regime,
            "sector":      sector,
            "atr_entry":   atr,
            "risk_pct":    size_res.risk_pct,
        }
        sizer.add_position_heat(size_res.risk_pct)
        mkt_port["capital"]      -= value
        mkt_port["total_trades"] += 1

        log.info(
            f"  ✅ BUY  {symbol} @ {fill:.4f} "
            f"| {shares:.6f} sh | val={value:.2f} "
            f"| atr={atr:.4f} | risk={size_res.risk_pct:.2%} | {size_res.method}"
        )
        send_alert(
            f"✅ BUY {symbol} @ {fill:.4f} | {shares:.4f} sh "
            f"| val={value:.2f} | regime={regime}({confidence:.2f})",
            market=market,
        )

    # ── SELL logic ─────────────────────────────────────────────────────────
    elif signal == "SELL" and symbol in mkt_pos:
        pos    = mkt_pos.pop(symbol)
        sh     = pos["shares"]
        fill   = _fill_price(last_price, "SELL", market, features)
        pnl    = (fill - pos["entry_price"]) * sh
        value  = fill * sh

        _exit_ts  = datetime.now(timezone.utc).isoformat()
        _pnl_pct  = round(pnl / max(pos["entry_price"] * sh, 1e-9) * 100, 4)
        record_trade(
            db_path=DB_PATH, market=market, symbol=symbol,
            action="SELL", shares=sh, price=fill,
            signal=signal, regime=regime, risk_action="ALLOW",
            pnl=pnl, note=f"Entry {pos['entry_price']:.4f}",
            strategy=strategy or f"{market}_directional",
            entry_time=pos.get("entry_time"), exit_time=_exit_ts,
            pnl_pct=_pnl_pct, size_usd=round(sh * pos["entry_price"], 4),
            notes={"confidence": round(confidence, 4), "exit_reason": "signal",
                   "r_multiple": round(_pnl_pct / max(pos.get("risk_pct", 0.01)*100, 0.01), 2)},
        )
        sizer.remove_position_heat(pos.get("risk_pct", 0.01))

        # T+1 settlement: lock proceeds for next trading day (India NSE only)
        if market == "india":
            _queue_settlement(portfolio, market, value)
            # realized PnL is booked now; only capital availability is deferred
        else:
            mkt_port["capital"] += value

        mkt_port["realized_pnl"]  += pnl
        mkt_port["total_trades"]  += 1

        entry_pct = abs(pnl) / max(pos["entry_price"] * sh, 1e-9)
        if pnl > 0:
            mkt_port["wins"]          += 1
            mkt_port["total_win_pct"] += entry_pct
        else:
            mkt_port["losses"]         += 1
            mkt_port["total_loss_pct"] += entry_pct

        icon = "🟢" if pnl >= 0 else "🔴"
        log.info(
            f"  {icon} SELL {symbol} @ {fill:.4f} "
            f"| PnL={pnl:+.4f} ({pnl/(pos['entry_price']*sh)*100:+.2f}%)"
        )
        send_alert(
            f"{icon} SELL {symbol} @ {fill:.4f} "
            f"| PnL={pnl:+.4f} | regime={regime}",
            market=market,
        )

    # ── Stop-loss check for existing positions ─────────────────────────────
    elif symbol in mkt_pos:
        pos       = mkt_pos[symbol]
        pnl_pct   = (last_price - pos["entry_price"]) / pos["entry_price"]
        atr_stop  = pos.get("atr_entry", last_price * 0.02) * 2.0
        stop_pct  = atr_stop / pos["entry_price"]
        if pnl_pct < -stop_pct:
            log.info(f"  🛑 STOP-LOSS {symbol}: {pnl_pct:.2%} < -{stop_pct:.2%}")
            # Force SELL via recursive call with overridden signal
            execute(market, symbol, "SELL", regime, confidence, last_price,
                    features, positions, portfolio, sector)
        else:
            log.info(f"  ⏸  HOLD {symbol} @ {last_price:.4f} (open PnL={pnl_pct:+.2%})")
    else:
        log.info(f"  ⏸  HOLD {symbol} @ {last_price:.4f}")


# ── Market startup: HMM training ──────────────────────────────────────────────

def warmup_india() -> None:
    """Fetch daily bars and fit HMM for each NSE symbol at startup."""
    log.info("── India HMM warmup ────────────────────────────────")
    for symbol, token, exchange, _ in NSE_WATCHLIST:
        daily = fetch_nse_daily(symbol, token, exchange)
        if daily is not None and len(daily) >= 100:
            _fit_regime(symbol, daily)
        time.sleep(0.2)


def warmup_crypto() -> None:
    """Fetch hourly bars and fit HMM for each crypto symbol at startup."""
    log.info("── Crypto HMM warmup ───────────────────────────────")
    for symbol in CRYPTO_SYMBOLS:
        hourly = fetch_crypto_hourly(symbol)
        if hourly is not None:
            _fit_regime(symbol, hourly)
        time.sleep(1.0)


def _binance_healthy() -> bool:
    """
    Ping Binance before starting the crypto cycle.
    Returns False (+ logs + Telegram alert) if the exchange is unreachable.
    Binance has ~2-3 outages per year; skipping the cycle is safer than trading
    on stale/incomplete data.
    """
    try:
        ex = _get_binance()
        ex.fetch_time()          # lightweight ping — returns server timestamp
        return True
    except Exception as e:
        msg = f"⚠️ Binance unreachable — skipping crypto cycle: {e}"
        log.warning(msg)
        send_alert(msg, market="crypto")
        return False


# ── ML confidence scoring (XGBoost) ──────────────────────────────────────────

_ml_ensemble: dict | None = None


def _init_ml_ensemble() -> dict | None:
    """
    Load or train the XGBoost ensemble.
    Order of preference:
      1. Load saved models from data/ml/ if present and < 7 days old (real-bar trained)
      2. Train fresh from real history via ml.train_from_history (writes saved models)
      3. Synthetic warm-start fallback (lets the engine still run if 1+2 fail)
    Returns None only if xgboost itself is unavailable.
    """
    # ── 1. Try loading saved real-bar models ──────────────────────────────────
    try:
        from ml.train_from_history import load_saved_models
        saved = load_saved_models(max_age_days=7)
        if saved:
            import json as _json
            from pathlib import Path as _Path
            meta_path = _Path(DB_PATH).parent / "ml" / "training_meta.json"
            try:
                meta = _json.loads(meta_path.read_text())
                trained_at = meta.get("trained_at", "?")
                log.info(
                    f"✅ Loaded saved XGBoost models (trained: {trained_at}) — "
                    f"val_acc india={meta.get('val_acc_india')} crypto={meta.get('val_acc_crypto')}"
                )
            except Exception:
                log.info("✅ Loaded saved XGBoost models")
            return saved
    except Exception as exc:
        log.warning(f"saved-model load skipped: {exc}")

    # ── 2. Train fresh from real history (writes saved models for next time) ──
    try:
        from ml.train_from_history import train_all_markets, load_saved_models
        log.info("Training new XGBoost models from history (real bars)...")
        meta = train_all_markets(min_samples=500)
        # Reload from disk so we get the persisted version
        saved = load_saved_models(max_age_days=7)
        if saved:
            log.info(
                f"✅ Real-history training complete — "
                f"val_acc india={meta.get('val_acc_india')} crypto={meta.get('val_acc_crypto')}"
            )
            return saved
    except Exception as exc:
        log.warning(f"real-history training failed (will fall back): {exc}")

    # ── 3. Synthetic fallback (last resort) ───────────────────────────────────
    try:
        from ml.xgboost_ensemble import build_ensemble, train_all
        ensemble = build_ensemble()
        train_all(ensemble)
        log.info("⚠️  XGBoost ensemble ready (SYNTHETIC fallback — not predictive)")
        return ensemble
    except Exception as exc:
        log.warning(f"XGBoost ensemble unavailable (non-fatal): {exc}")
        return None


def _score_ml(features: pd.DataFrame, market: str) -> float:
    """
    Return ML confidence [0, 1] for the latest bar.
    Maps feature names to what XGBoost was trained on.
    Returns 0.55 (neutral pass-through) if model not available.
    """
    global _ml_ensemble
    if _ml_ensemble is None:
        return 0.55  # neutral — don't block trades when model missing

    try:
        from ml.xgboost_ensemble import score_signal
        last = features.iloc[-1]

        # Build feature row — map compute_features() names to model feature names
        row: dict[str, float] = {}
        col = lambda k, d=0.0: float(last.get(k, d) or d)

        # Returns (compute_features uses "returns", model expects "return_Nd")
        close_arr = features["close"].values
        if len(close_arr) >= 2:
            row["returns_1d"] = row["return_1d"] = float(
                (close_arr[-1] - close_arr[-2]) / max(close_arr[-2], 1e-9)
            )
        if len(close_arr) >= 6:
            row["returns_5d"] = row["return_5d"] = float(
                (close_arr[-1] - close_arr[-6]) / max(close_arr[-6], 1e-9)
            )
        if len(close_arr) >= 21:
            row["returns_20d"] = row["return_20d"] = float(
                (close_arr[-1] - close_arr[-21]) / max(close_arr[-21], 1e-9)
            )

        row["rsi_14"]        = col("rsi_14", 50.0)
        row["macd"]          = col("macd", 0.0)
        row["adx_14"]        = col("adx_14", 25.0)
        row["atr_14"]        = col("atr_14", 0.01)
        row["atr_pct"]       = col("atr_14", 0.01) / max(float(last.get("close", 1)), 1e-9)
        row["india_vix"]     = col("india_vix", 15.0)
        row["vol_ratio"]     = row["vol_ratio_20"] = col("vol_ratio_20", 1.0)

        # EMA spread %  = (close - ema50) / ema50
        ema50 = col("ema_50", float(last.get("close", 1)))
        price = col("close", 1.0)
        row["ema_spread_pct"] = (price - ema50) / max(ema50, 1e-9)

        row["hist_vol_20"] = float(
            features["close"].pct_change().dropna().tail(20).std()
        ) if len(features) >= 20 else 0.02

        confidence = score_signal(market, row, _ml_ensemble)
        log.debug(f"    🤖 ML confidence={confidence:.3f} (market={market})")
        return confidence

    except Exception as exc:
        log.debug(f"    ML scoring failed (non-fatal): {exc}")
        return 0.55


def _ml_position_scale(confidence: float) -> float:
    """Map ML confidence to position size multiplier (1.0 / 0.5 / 0.0)."""
    try:
        from ml.xgboost_ensemble import position_scale_from_confidence
        return position_scale_from_confidence(confidence)
    except Exception:
        return 1.0  # pass-through if model unavailable


# ── Sentiment: Fear & Greed index (crypto only) ───────────────────────────────

_fear_greed_cache: dict = {}   # {"score": int, "ts": float}


def fetch_fear_greed() -> int | None:
    """
    Fetch current Fear & Greed index from alternative.me (free, no auth).
    Returns integer 0-100, or None on failure.
    Cached for 30 minutes to avoid hammering the API.
    """
    import time as _time
    now = _time.time()
    if _fear_greed_cache and now - _fear_greed_cache.get("ts", 0) < 1800:
        return _fear_greed_cache["score"]

    try:
        import urllib.request, json as _json
        with urllib.request.urlopen(
            "https://api.alternative.me/fng/?limit=1", timeout=5
        ) as resp:
            data = _json.loads(resp.read())
            score = int(data["data"][0]["value"])
            _fear_greed_cache.update({"score": score, "ts": now})
            classification = data["data"][0].get("value_classification", "")
            log.info(f"  📊 Fear & Greed: {score} ({classification})")
            return score
    except Exception as exc:
        log.debug(f"  Fear & Greed fetch failed (non-fatal): {exc}")
        return None


def _crypto_sentiment_gate(signal: str) -> str:
    """
    Apply Fear & Greed filter to crypto signals.

    Logic (contrarian — markets mean-revert):
      score < 20 (Extreme Fear)   → BUY signal boosted (stays BUY)
      score 20-30 (Fear)          → BUY signal passes unchanged
      score 70-80 (Greed)         → BUY signal downgraded to HOLD
      score > 80 (Extreme Greed)  → BUY blocked (market overbought)
      score > 85 (Euphoria)       → SELL signal boosted (stays SELL)
    """
    score = fetch_fear_greed()
    if score is None:
        return signal   # no data → pass through

    if signal == "BUY":
        if score > 80:
            log.info(f"    🟡 Fear&Greed={score} (Extreme Greed) → BUY → HOLD")
            return "HOLD"
        if score > 70:
            log.info(f"    🟡 Fear&Greed={score} (Greed) → BUY downgraded → HOLD")
            return "HOLD"

    if signal == "SELL" and score < 20:
        log.info(f"    🟡 Fear&Greed={score} (Extreme Fear) → SELL → HOLD (buy-the-fear)")
        return "HOLD"

    return signal


# ── ATR trailing stop (all markets) ──────────────────────────────────────────

def _check_trailing_stops(
    market: str,
    last_prices: dict[str, float],
    features_map: dict[str, pd.DataFrame],
    positions: dict,
    portfolio: dict,
) -> None:
    """
    Force-SELL any position that has moved 2.5× ATR against entry.
    Runs before the main signal loop each cycle.
    Prevents holding through regime changes or blow-up moves.
    """
    mkt_pos  = positions[market]
    mkt_port = portfolio[market]
    sizer    = _get_sizer(market, mkt_port["capital"])

    to_stop: list[str] = []
    for sym, pos in mkt_pos.items():
        price = last_prices.get(sym)
        if price is None:
            continue
        atr_entry = pos.get("atr_entry", price * 0.015)
        entry     = pos["entry_price"]
        stop_dist = 2.5 * atr_entry
        loss      = entry - price   # positive if price fell below entry

        if loss >= stop_dist:
            to_stop.append(sym)
            log.warning(
                f"  🛑 ATR TRAILING STOP {sym} | entry={entry:.4f} "
                f"price={price:.4f} loss={loss:.4f} > 2.5×ATR={stop_dist:.4f}"
            )

    for sym in to_stop:
        if sym not in mkt_pos:
            continue
        pos   = mkt_pos.pop(sym)
        sh    = pos["shares"]
        price = last_prices[sym]
        feat  = features_map.get(sym)
        fill  = _fill_price(price, "SELL", market, feat)
        pnl   = (fill - pos["entry_price"]) * sh
        value = fill * sh

        _atr_exit_ts = datetime.now(timezone.utc).isoformat()
        _atr_pnl_pct = round(pnl / max(pos["entry_price"] * sh, 1e-9) * 100, 4)
        record_trade(
            db_path=DB_PATH, market=market, symbol=sym,
            action="SELL", shares=sh, price=fill,
            signal="SELL", regime=pos.get("regime", "UNKNOWN"),
            risk_action="ATR_STOP",
            pnl=pnl, note=f"ATR trailing stop | entry={pos['entry_price']:.4f}",
            strategy=f"{market}_directional",
            entry_time=pos.get("entry_time"), exit_time=_atr_exit_ts,
            pnl_pct=_atr_pnl_pct, size_usd=round(sh * pos["entry_price"], 4),
            notes={"exit_reason": "atr_trailing_stop", "confidence": 0.0,
                   "r_multiple": round(_atr_pnl_pct / max(pos.get("risk_pct", 0.01)*100, 0.01), 2)},
        )
        sizer.remove_position_heat(pos.get("risk_pct", 0.01))

        if market == "india":
            _queue_settlement(portfolio, market, value)
        else:
            mkt_port["capital"] += value

        mkt_port["realized_pnl"] += pnl
        mkt_port["total_trades"] += 1
        if pnl > 0:
            mkt_port["wins"] += 1
        else:
            mkt_port["losses"] += 1

        send_alert(
            f"🛑 STOP {sym} @ {fill:.4f} | PnL={pnl:+.4f} (ATR trailing stop)",
            market=market,
        )


# ── India NSE market runner ───────────────────────────────────────────────────



# -- India NSE market runner --------------------------------------------------

def run_india(positions: dict, portfolio: dict) -> None:
    """Run one India NSE paper-trading cycle across the full watchlist."""
    try:
        from foundation.kill_switch import is_halted as _is_halted
        if _is_halted("india"):
            log.warning("India market HALTED (kill switch) — skipping cycle")
            return
    except ImportError:
        pass
    from execution.market_hours import require_market_open
    if not require_market_open("india"):
        return

    _settle_pending_capital(portfolio, "india")
    log.info("== NSE cycle | capital=INR %.2f ==", portfolio["india"]["capital"])

    client = _get_angel_client()
    if client is None:
        log.error("  Angel One client unavailable -- skipping NSE cycle")
        return

    # Prefetch prices + features for ATR trailing stop
    last_prices: dict = {}
    features_map: dict = {}

    for sym, token, exch, sector in NSE_WATCHLIST:
        try:
            hourly = fetch_nse_hourly(sym, token, exch)
            if hourly is None or len(hourly) < 50:
                continue
            feat = compute_features(hourly)
            if feat is None or feat.empty:
                continue
            price = float(feat["close"].iloc[-1])
            last_prices[sym] = price
            features_map[sym] = feat
            # Write price cache for Grafana volatility radar
            try:
                import json as _json
                cache_key = sym.replace("/", "_")
                cache_path = _ROOT / "data" / f"{cache_key}_price_cache.json"
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                _bars = hourly.tail(200)
                cache_path.write_text(_json.dumps({
                    "closes": [float(x) for x in _bars["close"].tolist()],
                    "highs":  [float(x) for x in _bars["high"].tolist()],
                    "lows":   [float(x) for x in _bars["low"].tolist()],
                    "symbol": sym,
                }, separators=(",", ":")), encoding="utf-8")
            except Exception as _ce:
                log.debug("  Price cache write %s: %s", sym, _ce)
        except Exception as exc:
            log.debug("  Prefetch %s: %s", sym, exc)

    # ATR trailing stops first
    _check_trailing_stops("india", last_prices, features_map, positions, portfolio)

    # Signal loop
    for sym, token, exch, sector in NSE_WATCHLIST:
        try:
            feat = features_map.get(sym)
            if feat is None:
                continue
            price = last_prices.get(sym)
            if price is None:
                continue

            log.info("  [%s] price=%.2f", sym, price)
            signal, regime, conf = generate_signal(sym, feat, "india")

            # ML confidence gate
            ml_conf = _score_ml(feat, "india")
            ml_scale = _ml_position_scale(ml_conf)
            if ml_scale == 0.0:
                log.info("    ML gate: conf=%.3f -> SKIP %s", ml_conf, signal)
                continue

            execute(
                market="india", symbol=sym, signal=signal,
                regime=regime, confidence=conf,
                last_price=price, features=feat,
                positions=positions, portfolio=portfolio,
                sector=sector, ml_size_scale=ml_scale,
            )
        except Exception as exc:
            log.error("  NSE %s error: %s", sym, exc, exc_info=True)

    # Statistical arbitrage: HDFCBANK / ICICIBANK pair
    try:
        from trading.stat_arb import run_stat_arb_india
        run_stat_arb_india(portfolio, fetch_nse_hourly)
    except Exception as exc:
        log.error("  NSE stat_arb error: %s", exc, exc_info=True)

    save_positions(positions)
    save_portfolio(portfolio)
    log.info("== NSE cycle done | capital=INR %.2f ==", portfolio["india"]["capital"])


# -- Crypto market runner -----------------------------------------------------

def run_crypto(positions: dict, portfolio: dict) -> None:
    """Run one crypto paper-trading cycle across CRYPTO_SYMBOLS."""
    log.info("== Crypto cycle | capital=USD %.2f ==", portfolio["crypto"]["capital"])

    if not _binance_healthy():
        log.warning("  Binance unreachable -- skipping crypto cycle")
        return

    btc_dom = fetch_btc_dominance()
    alt_buy_allowed = btc_dom < BTC_DOMINANCE_CUTOFF
    if not alt_buy_allowed:
        log.info("  BTC dominance=%.1f%% > %.1f%% -> suppress alt BUYs",
                 btc_dom, BTC_DOMINANCE_CUTOFF)

    # Prefetch prices + features for ATR trailing stop
    last_prices: dict = {}
    features_map: dict = {}

    for sym in CRYPTO_SYMBOLS:
        try:
            hourly = fetch_crypto_hourly(sym)
            if hourly is None or len(hourly) < 50:
                continue
            feat = compute_features(hourly)
            if feat is None or feat.empty:
                continue
            price = float(feat["close"].iloc[-1])
            last_prices[sym] = price
            features_map[sym] = feat
        except Exception as exc:
            log.debug("  Prefetch %s: %s", sym, exc)

    # Refit stale HMMs using already-fetched hourly data (free — data is in hand)
    for sym, hourly in {s: fetch_crypto_hourly(s) for s in CRYPTO_SYMBOLS
                        if _regime_is_stale(s)}.items():
        if hourly is not None:
            _fit_regime(sym, hourly)

    # ATR trailing stops first
    _check_trailing_stops("crypto", last_prices, features_map, positions, portfolio)

    # Signal loop
    for sym in CRYPTO_SYMBOLS:
        try:
            feat = features_map.get(sym)
            if feat is None:
                continue
            price = last_prices.get(sym)
            if price is None:
                continue

            log.info("  [%s] price=%.4f | BTC.D=%.1f%%", sym, price, btc_dom)

            is_alt = sym not in ("BTC/USDT", "ETH/USDT")
            signal, regime, conf = generate_signal(sym, feat, "crypto")

            if is_alt and not alt_buy_allowed and signal == "BUY":
                log.info("    BTC.D filter: skip BUY %s", sym)
                continue

            # Fear & Greed sentiment gate
            signal = _crypto_sentiment_gate(signal)

            # ML confidence gate
            ml_conf = _score_ml(feat, "crypto")
            ml_scale = _ml_position_scale(ml_conf)
            if ml_scale == 0.0:
                log.info("    ML gate: conf=%.3f -> SKIP %s", ml_conf, signal)
                continue

            execute(
                market="crypto", symbol=sym, signal=signal,
                regime=regime, confidence=conf,
                last_price=price, features=feat,
                positions=positions, portfolio=portfolio,
                ml_size_scale=ml_scale,
            )
        except Exception as exc:
            log.error("  Crypto %s error: %s", sym, exc, exc_info=True)

    # Statistical arbitrage: BTC/ETH spread
    try:
        from trading.stat_arb import run_stat_arb_crypto
        run_stat_arb_crypto(portfolio, fetch_crypto_hourly)
    except Exception as exc:
        log.error("  Crypto stat_arb error: %s", exc, exc_info=True)

    # Funding rate arbitrage: BTC/ETH delta-neutral (C5b)
    # HALTED 2026-05-15: see docs/known_issues/2026-05-15_c5b_halt.md
    # Schema delta ($25 per-leg BUY vs $50 round-trip SELL) would fire the
    # share-equality assertion as $25 WARN on every close. Re-enable only after
    # unified-ledger spec Q1-Q4 resolves dual-leg accounting.
    # try:
    #     from trading.funding_arb import run_funding_arb_crypto
    #     run_funding_arb_crypto(portfolio["crypto"])
    # except Exception as exc:
    #     log.error("  Funding arb error: %s", exc, exc_info=True)

    # 4H Momentum Breakout: BTC/ETH only (C2)
    try:
        from trading.momentum_breakout import run_momentum_breakout_crypto
        run_momentum_breakout_crypto(portfolio["crypto"], fetch_crypto_hourly)
    except Exception as exc:
        log.error("  Momentum breakout error: %s", exc, exc_info=True)

    # Altcoin Beta Mean Reversion: SOL/LINK/AVAX vs BTC (C3)
    try:
        from trading.altcoin_reversion import run_altcoin_reversion_crypto
        run_altcoin_reversion_crypto(portfolio["crypto"], fetch_crypto_hourly)
    except Exception as exc:
        log.error("  Altcoin reversion error: %s", exc, exc_info=True)

    save_positions(positions)
    save_portfolio(portfolio)
    log.info("== Crypto cycle done | capital=USD %.2f ==", portfolio["crypto"]["capital"])


# -- Main scheduler -----------------------------------------------------------

CYCLE_INTERVAL_SEC = 900   # 15-minute cycles


def main(market: str = "crypto") -> None:
    """
    Main paper-trading scheduler.

    Args:
        market: "crypto" | "india" | "both"
                Passed from paper_loop.py --market flag.
    """
    global _ml_ensemble
    log.info("=" * 60)
    log.info("AAATS Live Paper Trader v2.1 starting  [market=%s]", market)
    log.info("  Cycle    : %d seconds (15 min)", CYCLE_INTERVAL_SEC)
    log.info("  ML       : XGBoost confidence gating")
    log.info("  Strategies: C1 stat-arb, C2 momentum, C3 alt-reversion, C5b funding-arb")

    # Load persistent state
    positions = load_positions()
    portfolio  = load_portfolio()
    log.info("  Portfolio: crypto=USD%.2f  india=INR%.2f",
             portfolio["crypto"]["capital"], portfolio["india"]["capital"])

    # Warm up HMM regime models
    if market in ("crypto", "both"):
        try:
            warmup_crypto()
        except Exception as exc:
            log.warning("Crypto warmup error: %s", exc)

    if market in ("india", "both"):
        try:
            warmup_india()
        except Exception as exc:
            log.warning("India warmup error: %s", exc)

    # Load ML ensemble once at startup
    try:
        _ml_ensemble = _init_ml_ensemble()
        log.info("  ML ensemble loaded OK")
    except Exception as exc:
        log.warning("  ML ensemble unavailable: %s", exc)

    log.info("Starting main loop...")
    cycle = 0
    while True:
        cycle += 1
        cycle_start = time.time()
        log.info("── Cycle %d ─────────────────────────────────────", cycle)

        if market in ("crypto", "both"):
            try:
                run_crypto(positions, portfolio)
            except Exception as exc:
                log.error("run_crypto error: %s", exc, exc_info=True)

        if market in ("india", "both"):
            try:
                run_india(positions, portfolio)
            except Exception as exc:
                log.error("run_india error: %s", exc, exc_info=True)

        elapsed = time.time() - cycle_start
        sleep_sec = max(0, CYCLE_INTERVAL_SEC - elapsed)
        log.info("  Cycle %d done in %.1fs — sleeping %.0fs", cycle, elapsed, sleep_sec)
        time.sleep(sleep_sec)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="AAATS paper trading runner")
    ap.add_argument("--market", default="crypto",
                    choices=["crypto", "india", "both"],
                    help="Market(s) to run (default: crypto)")
    args = ap.parse_args()
    main(market=args.market)
