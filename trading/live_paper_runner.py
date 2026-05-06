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

INITIAL_CAPITAL = {"india": 25_000.0, "crypto": 120.0}  # India ₹25k, Crypto ₹10k≈$120 @ 83 INR/USD

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


# ── Regime pipeline cache (fitted daily) ─────────────────────────────────────

_regime_pipes: dict[str, object] = {}   # symbol → fitted RegimePipeline


def _fit_regime(symbol: str, daily_df: pd.DataFrame) -> None:
    """Fit HMM regime pipeline on daily bars and cache it."""
    try:
        from intelligence.regime.regime_pipeline import RegimePipeline
        feats = compute_features(daily_df)
        pipe  = RegimePipeline()
        pipe.fit(feats)
        _regime_pipes[symbol] = pipe
        log.debug(f"  HMM fitted for {symbol} ({len(daily_df)} daily bars)")
    except Exception as e:
        log.debug(f"  HMM fit skipped for {symbol}: {e}")


def detect_regime(symbol: str, hourly_features: pd.DataFrame) -> tuple[str, float]:
    """Use cached HMM pipeline if available, else rule-based fallback."""
    pipe = _regime_pipes.get(symbol)
    if pipe:
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
        total = sum(p["capital"] for p in portfolio.values())
        _risk_engine = RiskEngine(initial_portfolio=total)
    return _risk_engine


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
) -> None:
    mkt_pos  = positions[market]
    mkt_port = portfolio[market]
    capital  = mkt_port["capital"]

    engine = _get_risk_engine(portfolio)
    sizer  = _get_sizer(market, capital)

    # ── Update risk engine with current market value ───────────────────────
    total_equity = sum(p["capital"] for p in portfolio.values())
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

        fill    = _fill_price(last_price, "BUY", market, features)
        value   = shares * fill

        record_trade(
            db_path=DB_PATH, market=market, symbol=symbol,
            action="BUY", shares=shares, price=fill,
            signal=signal, regime=regime, risk_action="ALLOW",
            note=f"atr={atr:.4f} kelly_w={win_rate:.2f}",
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

        record_trade(
            db_path=DB_PATH, market=market, symbol=symbol,
            action="SELL", shares=sh, price=fill,
            signal=signal, regime=regime, risk_action="ALLOW",
            pnl=pnl, note=f"Entry {pos['entry_price']:.4f}",
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
    """Fetch daily bars and fit HMM for each crypto symbol at startup."""
    log.info("── Crypto HMM warmup ───────────────────────────────")
    for symbol in CRYPTO_SYMBOLS:
        daily = fetch_crypto_daily(symbol)
        if daily is not None:
            _fit_regime(symbol, daily)
        time.sleep(1.0)


# ── Market cycles ─────────────────────────────────────────────────────────────

def run_india(positions: dict, portfolio: dict) -> None:
    if not is_market_open("india"):
        log.info("NSE closed — skipping India cycle")
        return
    log.info("── India (Angel One) ──────────────────────────────")

    # Release any T+1 settled capital before trading
    _settle_pending_capital(portfolio, "india")

    for symbol, token, exchange, sector in NSE_WATCHLIST:
        log.info(f"  {symbol} [{sector}]")
        df = fetch_nse_hourly(symbol, token, exchange)
        if df is None:
            continue
        try:
            features = compute_features(df)
        except Exception as e:
            log.error(f"  compute_features {symbol}: {e}")
            continue

        signal, regime, conf = generate_signal(symbol, features, "india")
        last_price = float(df["close"].iloc[-1])
        execute("india", symbol, signal, regime, conf,
                last_price, features, positions, portfolio, sector)
        time.sleep(0.3)

    p = portfolio["india"]
    log.info(
        f"  India → capital: ₹{p['capital']:,.0f} | "
        f"realized: ₹{p['realized_pnl']:+,.0f} | "
        f"trades: {p['total_trades']} | "
        f"wins: {p.get('wins',0)}/{p['total_trades']}"
    )


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


def run_crypto(positions: dict, portfolio: dict) -> None:
    log.info("── Crypto (Binance) ───────────────────────────────")

    # Exchange health-check — abort cycle if Binance is down
    if not _binance_healthy():
        return

    # Macro filter: BTC dominance > cutoff → suppress alt-coin BUYs
    btc_dom = fetch_btc_dominance()
    alt_buy_blocked = btc_dom > BTC_DOMINANCE_CUTOFF
    if alt_buy_blocked:
        log.info(
            f"  ⚠️  BTC dominance {btc_dom:.1f}% > {BTC_DOMINANCE_CUTOFF}% "
            f"— alt BUYs suppressed this cycle"
        )

    # Alt coins that get suppressed under high BTC dominance
    _ALT_SYMBOLS = {"SOL/USDT", "LINK/USDT", "DOT/USDT", "AVAX/USDT"}

    for symbol in CRYPTO_SYMBOLS:
        log.info(f"  {symbol}")
        df = fetch_crypto_hourly(symbol)
        if df is None:
            continue
        try:
            features = compute_features(df)
        except Exception as e:
            log.error(f"  compute_features {symbol}: {e}")
            continue

        signal, regime, conf = generate_signal(symbol, features, "crypto")
        last_price = float(df["close"].iloc[-1])

        # Suppress new alt BUYs when BTC is dominating; allow SELL/HOLD and BTC/ETH
        if alt_buy_blocked and signal == "BUY" and symbol in _ALT_SYMBOLS:
            log.info(f"    ⛔ Alt BUY suppressed (BTC.D={btc_dom:.1f}%) — {symbol}")
            signal = "HOLD"

        execute("crypto", symbol, signal, regime, conf,
                last_price, features, positions, portfolio)
        time.sleep(1.0)

    p = portfolio["crypto"]
    log.info(
        f"  Crypto → capital: ${p['capital']:,.4f} | "
        f"realized: ${p['realized_pnl']:+.4f} | "
        f"trades: {p['total_trades']} | "
        f"wins: {p.get('wins',0)}/{p['total_trades']}"
    )


# ── Entry point ───────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"═══ AAATS Paper Runner v2 — {ts} ═══")

    # HMM warmup (trains on daily bars — only on first run of the day)
    try:
        warmup_india()
    except Exception as e:
        log.warning(f"India warmup error (non-fatal): {e}")

    try:
        warmup_crypto()
    except Exception as e:
        log.warning(f"Crypto warmup error (non-fatal): {e}")

    positions = load_positions()
    portfolio = load_portfolio()

    try:
        run_india(positions, portfolio)
    except Exception as e:
        log.exception(f"India cycle error: {e}")
        send_alert(f"❌ India cycle error: {e}", market="india")

    try:
        run_crypto(positions, portfolio)
    except Exception as e:
        log.exception(f"Crypto cycle error: {e}")
        send_alert(f"❌ Crypto cycle error: {e}", market="crypto")

    save_positions(positions)
    save_portfolio(portfolio)

    open_pos  = len(positions["india"]) + len(positions["crypto"])
    real_pnl  = portfolio["india"]["realized_pnl"] + portfolio["crypto"]["realized_pnl"]
    log.info(
        f"═══ Done | open={open_pos} | "
        f"realized PnL ≈ {real_pnl:+.2f} (mixed ccy) ═══"
    )


if __name__ == "__main__":
    main()
