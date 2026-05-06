"""
AAATS Live Paper Trading Runner
================================
Runs hourly via Windows Task Scheduler.

Markets:
  - India NSE  — Angel One SmartAPI (credentials from .env)
  - Crypto     — Binance via CCXT  (credentials from .env)

Pipeline per symbol each hour:
  Fetch 1h OHLCV
    → compute_features()          (EMA/RSI/ATR/ADX/VWAP/Bollinger/MACD)
    → RegimePipeline.detect()     (HMM + rule-based consensus)
    → 3 x StrategyVote            (EMA crossover, RSI reversion, Momentum)
    → ConsensusVoting.vote()      (democratic signal aggregation)
    → Position sizing (5 % of capital)
    → execution.paper_trader.record_trade()

State files (persist between runs):
  data/paper_positions.json   — open positions per market
  data/paper_portfolio.json   — running capital & P&L
  logs/paper_runner.log       — execution log

Run manually:
  venv\\Scripts\\python.exe trading\\live_paper_runner.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
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

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH        = str(_ROOT / "data" / "paper_trades.db")
POSITIONS_FILE = _ROOT / "data" / "paper_positions.json"
PORTFOLIO_FILE = _ROOT / "data" / "paper_portfolio.json"
LOG_FILE       = _ROOT / "logs" / "paper_runner.log"
ENV_FILE       = _ROOT / ".env"

N_BARS         = 120       # hourly bars fetched (needs ≥50 for indicators)
POSITION_PCT   = 0.05      # 5 % of capital per trade

# NSE watchlist: (display_symbol, angel_token, exchange)
NSE_WATCHLIST = [
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
]

CRYPTO_SYMBOLS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]

INITIAL_CAPITAL = {
    "india":  500_000.0,   # INR 5 lakh
    "crypto":   1_000.0,   # USDT 1 000
}

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
_fmt = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(
    level=logging.INFO, format=_fmt,
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("paper_runner")


# ── .env loader (no pydantic dependency) ──────────────────────────────────────

def _load_env() -> dict[str, str]:
    """Parse key=value lines from .env, ignore comments and blanks."""
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        log.warning(f".env not found at {ENV_FILE}")
        return env
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().split("#")[0].strip()   # strip inline comments
    return env


_ENV = _load_env()


def _e(key: str, default: str = "") -> str:
    """Get env var — checks os.environ first, then .env file."""
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
        m: {"capital": INITIAL_CAPITAL[m], "realized_pnl": 0.0, "total_trades": 0}
        for m in ("india", "crypto")
    }
    return _load_json(PORTFOLIO_FILE, default)


def save_portfolio(p: dict) -> None:
    _save_json(PORTFOLIO_FILE, p)


# ── Angel One (India NSE) ─────────────────────────────────────────────────────

_angel_client = None          # module-level singleton
_angel_token_expiry = None    # datetime of token expiry


def _get_angel_client():
    """Return authenticated SmartConnect instance, refreshing session if needed."""
    global _angel_client, _angel_token_expiry

    now = datetime.now(timezone.utc)
    if _angel_client and _angel_token_expiry and now < _angel_token_expiry:
        return _angel_client

    import pyotp
    from SmartApi import SmartConnect

    api_key  = _e("INDIA__ANGEL_API_KEY")
    client_id= _e("INDIA__ANGEL_CLIENT_ID")
    pin      = _e("INDIA__ANGEL_PIN")
    totp_sec = _e("INDIA__ANGEL_TOTP_SECRET")

    if not all([api_key, client_id, pin, totp_sec]):
        raise RuntimeError("Angel One credentials missing from .env")

    client = SmartConnect(api_key=api_key)
    totp   = pyotp.TOTP(totp_sec).now()
    resp   = client.generateSession(client_id, pin, totp)

    if not resp or not resp.get("status"):
        raise RuntimeError(f"Angel One auth failed: {resp}")

    _angel_client       = client
    _angel_token_expiry = now + timedelta(hours=23)   # tokens valid ~24 h
    log.info(f"Angel One session established (client={client_id})")
    return client


def fetch_nse_ohlcv(symbol: str, token: str, exchange: str) -> pd.DataFrame | None:
    """Fetch last N_BARS of 1-hour OHLCV from Angel One."""
    try:
        client    = _get_angel_client()
        to_dt     = datetime.now()
        from_dt   = to_dt - timedelta(days=12)    # 12 calendar days → ~120 hourly NSE bars
        params    = {
            "exchange":    exchange,
            "symboltoken": token,
            "interval":    "ONE_HOUR",
            "fromdate":    from_dt.strftime("%Y-%m-%d %H:%M"),
            "todate":      to_dt.strftime("%Y-%m-%d %H:%M"),
        }
        resp = client.getCandleData(params)
        if not resp or not resp.get("status") or not resp.get("data"):
            log.warning(f"{symbol}: Angel One returned no data — {resp}")
            return None

        rows = []
        for bar in resp["data"]:
            rows.append({
                "open": float(bar[1]), "high": float(bar[2]),
                "low":  float(bar[3]), "close": float(bar[4]),
                "volume": float(bar[5]),
            })
            ts = pd.to_datetime(bar[0], utc=True)

        df = pd.DataFrame(rows)
        df.index = pd.to_datetime(
            [bar[0] for bar in resp["data"]], utc=True
        )
        df = df.sort_index().tail(N_BARS)

        if len(df) < 30:
            log.warning(f"{symbol}: only {len(df)} bars — skipping")
            return None
        return df
    except RuntimeError:
        raise
    except Exception as e:
        log.error(f"{symbol} fetch failed: {e}")
        return None


# ── Binance (Crypto) ──────────────────────────────────────────────────────────

_binance_exchange = None   # module-level singleton


def _get_binance():
    global _binance_exchange
    if _binance_exchange:
        return _binance_exchange
    import ccxt
    _binance_exchange = ccxt.binance({
        "apiKey":        _e("CRYPTO__BINANCE_API_KEY"),
        "secret":        _e("CRYPTO__BINANCE_SECRET_KEY"),
        "enableRateLimit": True,
    })
    return _binance_exchange


def fetch_crypto_ohlcv(symbol: str) -> pd.DataFrame | None:
    """Fetch last N_BARS of 1-hour OHLCV from Binance."""
    try:
        exchange = _get_binance()
        ohlcv    = exchange.fetch_ohlcv(symbol, "1h", limit=N_BARS)
        if not ohlcv or len(ohlcv) < 30:
            log.warning(f"{symbol}: insufficient Binance data")
            return None
        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
        df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df[["open", "high", "low", "close", "volume"]].tail(N_BARS)
    except Exception as e:
        log.error(f"{symbol} Binance fetch failed: {e}")
        return None


# ── Regime detection ──────────────────────────────────────────────────────────

def detect_regime(features: pd.DataFrame) -> tuple[str, float]:
    """RegimePipeline with HMM; falls back to rule-based on any failure."""
    try:
        from intelligence.regime.regime_pipeline import RegimePipeline
        pipe   = RegimePipeline()
        split  = max(len(features) - 20, 30)
        pipe.fit(features.iloc[:split])
        sig    = pipe.detect(features)
        return sig.label, sig.confidence
    except Exception as e:
        log.debug(f"RegimePipeline fallback: {e}")
        return _rule_regime(features)


def _rule_regime(f: pd.DataFrame) -> tuple[str, float]:
    last    = f.iloc[-1]
    adx     = float(last.get("adx_14", 0) or 0)
    ema12   = float(last.get("ema_12", last.get("close", 1)) or 1)
    ema26   = float(last.get("ema_26", last.get("close", 1)) or 1)
    close   = float(last.get("close", 1) or 1)
    atr14   = float(last.get("atr_14", close * 0.01) or close * 0.01)
    atr_pct = atr14 / close if close else 0.01

    if atr_pct > 0.04:
        return "HIGH_VOLATILITY", 0.70
    if adx > 25:
        return ("BULL_TREND", min(0.5 + adx / 100, 0.95)) if ema12 > ema26 \
               else ("BEAR_TREND", min(0.5 + adx / 100, 0.95))
    return "RANGE_BOUND", 0.60


# ── Strategy votes ────────────────────────────────────────────────────────────

def _vote(sid: str, market: str, signal: str, conf: float) -> StrategyVote:
    return StrategyVote(
        strategy_id=sid, market=market, signal=signal,
        confidence=conf, health_score=80.0,
        timestamp=datetime.now(timezone.utc).timestamp(),
    )


def ema_vote(f: pd.DataFrame, market: str, regime: str) -> StrategyVote:
    last, prev = f.iloc[-1], f.iloc[-2] if len(f) > 1 else f.iloc[-1]
    e12, e26   = float(last.get("ema_12", 0) or 0), float(last.get("ema_26", 0) or 0)
    p12, p26   = float(prev.get("ema_12", 0) or 0), float(prev.get("ema_26", 0) or 0)
    rsi        = float(last.get("rsi_14", 50) or 50)
    cross_up   = (e12 > e26) and (p12 <= p26)
    cross_dn   = (e12 < e26) and (p12 >= p26)
    above      = e12 > e26

    if cross_up or (above and regime == "BULL_TREND" and rsi < 70):
        return _vote("ema_crossover", market, "BUY",  0.75 if cross_up else 0.55)
    if cross_dn or (not above and regime == "BEAR_TREND" and rsi > 30):
        return _vote("ema_crossover", market, "SELL", 0.75 if cross_dn else 0.55)
    return _vote("ema_crossover", market, "HOLD", 0.60)


def rsi_vote(f: pd.DataFrame, market: str, regime: str) -> StrategyVote:
    rsi    = float(f.iloc[-1].get("rsi_14", 50) or 50)
    w      = 0.80 if regime == "RANGE_BOUND" else 0.45
    if rsi < 32:
        return _vote("rsi_reversion", market, "BUY",  w * 0.85)
    if rsi > 68:
        return _vote("rsi_reversion", market, "SELL", w * 0.85)
    return _vote("rsi_reversion", market, "HOLD", 0.55)


def momentum_vote(f: pd.DataFrame, market: str, regime: str) -> StrategyVote:
    last    = f.iloc[-1]
    ret5    = float(last.get("return_5", 0) or 0)
    macd    = float(last.get("macd", 0) or 0)
    sig_ln  = float(last.get("macd_signal", 0) or 0)
    w       = 0.70 if regime in ("BULL_TREND", "BEAR_TREND") else 0.40
    if ret5 > 0.005 and macd > sig_ln:
        return _vote("momentum", market, "BUY",  w * 0.80)
    if ret5 < -0.005 and macd < sig_ln:
        return _vote("momentum", market, "SELL", w * 0.80)
    return _vote("momentum", market, "HOLD", 0.50)


_voter = ConsensusVoting(
    min_agreement_threshold=0.55,
    veto_confidence_threshold=0.85,
    uncertainty_threshold=0.45,
)


def generate_signal(features: pd.DataFrame, market: str) -> tuple[str, str, float]:
    """Returns (signal, regime, confidence)."""
    regime, r_conf = detect_regime(features)
    votes  = [ema_vote(features, market, regime),
              rsi_vote(features, market, regime),
              momentum_vote(features, market, regime)]
    result = _voter.vote(votes)
    signal = result.final_signal

    if regime == "HIGH_VOLATILITY" and r_conf > 0.65:
        signal = "HOLD"

    log.info(f"  regime={regime}({r_conf:.2f}) votes={result.vote_breakdown} "
             f"→ {signal} (agree={result.agreement_score:.2f})")
    return signal, regime, result.consensus_confidence


# ── Paper trade execution ─────────────────────────────────────────────────────

def execute(market: str, symbol: str, signal: str, regime: str,
            confidence: float, price: float,
            positions: dict, portfolio: dict) -> None:
    mkt_pos  = positions[market]
    mkt_port = portfolio[market]
    capital  = mkt_port["capital"]

    if signal == "BUY" and symbol not in mkt_pos:
        value  = capital * POSITION_PCT
        shares = value / price if price > 0 else 0
        if shares <= 0:
            return
        record_trade(db_path=DB_PATH, market=market, symbol=symbol,
                     action="BUY", shares=shares, price=price,
                     signal=signal, regime=regime, risk_action="ALLOW")
        mkt_pos[symbol]      = {"shares": shares, "entry_price": price,
                                 "entry_time": datetime.now(timezone.utc).isoformat(),
                                 "regime": regime}
        mkt_port["capital"]      -= value
        mkt_port["total_trades"] += 1
        log.info(f"  ✅ BUY  {symbol} @ {price:.4f} | {shares:.6f} sh | val={value:.2f}")

    elif signal == "SELL" and symbol in mkt_pos:
        pos   = mkt_pos.pop(symbol)
        sh    = pos["shares"]
        pnl   = (price - pos["entry_price"]) * sh
        record_trade(db_path=DB_PATH, market=market, symbol=symbol,
                     action="SELL", shares=sh, price=price,
                     signal=signal, regime=regime, risk_action="ALLOW",
                     pnl=pnl, note=f"Entry {pos['entry_price']:.4f}")
        mkt_port["capital"]      += price * sh
        mkt_port["realized_pnl"] += pnl
        mkt_port["total_trades"] += 1
        icon = "🟢" if pnl >= 0 else "🔴"
        log.info(f"  {icon} SELL {symbol} @ {price:.4f} | PnL={pnl:+.4f}")

    else:
        log.info(f"  ⏸  HOLD {symbol} @ {price:.4f}")


# ── Market cycles ─────────────────────────────────────────────────────────────

def run_india(positions: dict, portfolio: dict) -> None:
    if not is_market_open("india"):
        log.info("NSE closed — skipping India cycle")
        return
    log.info("── India (Angel One) ──────────────────────────────")
    for symbol, token, exchange in NSE_WATCHLIST:
        log.info(f"  {symbol}")
        df = fetch_nse_ohlcv(symbol, token, exchange)
        if df is None:
            continue
        try:
            features = compute_features(df)
        except Exception as e:
            log.error(f"  compute_features {symbol}: {e}")
            continue
        signal, regime, conf = generate_signal(features, "india")
        execute("india", symbol, signal, regime, conf,
                float(df["close"].iloc[-1]), positions, portfolio)
        time.sleep(0.3)

    p = portfolio["india"]
    log.info(f"  India capital: ₹{p['capital']:,.0f} | PnL: ₹{p['realized_pnl']:+,.0f} "
             f"| trades: {p['total_trades']}")


def run_crypto(positions: dict, portfolio: dict) -> None:
    log.info("── Crypto (Binance) ───────────────────────────────")
    for symbol in CRYPTO_SYMBOLS:
        log.info(f"  {symbol}")
        df = fetch_crypto_ohlcv(symbol)
        if df is None:
            continue
        try:
            features = compute_features(df)
        except Exception as e:
            log.error(f"  compute_features {symbol}: {e}")
            continue
        signal, regime, conf = generate_signal(features, "crypto")
        execute("crypto", symbol, signal, regime, conf,
                float(df["close"].iloc[-1]), positions, portfolio)
        time.sleep(1.0)

    p = portfolio["crypto"]
    log.info(f"  Crypto capital: ${p['capital']:,.2f} | PnL: ${p['realized_pnl']:+.4f} "
             f"| trades: {p['total_trades']}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"═══ AAATS Paper Runner — {ts} ═══")

    positions = load_positions()
    portfolio = load_portfolio()

    try:
        run_india(positions, portfolio)
    except Exception as e:
        log.exception(f"India cycle error: {e}")

    try:
        run_crypto(positions, portfolio)
    except Exception as e:
        log.exception(f"Crypto cycle error: {e}")

    save_positions(positions)
    save_portfolio(portfolio)

    open_pos  = len(positions["india"]) + len(positions["crypto"])
    total_pnl = portfolio["india"]["realized_pnl"] + portfolio["crypto"]["realized_pnl"]
    log.info(f"═══ Done | open={open_pos} | realized PnL ≈ {total_pnl:+.2f} (mixed ccy) ═══")


if __name__ == "__main__":
    main()
