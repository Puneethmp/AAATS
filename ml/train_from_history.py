"""
Real-bar XGBoost training for AAATS — replaces synthetic warm start.

Pulls historical OHLCV from Binance (crypto, hourly) and Angel One (NSE,
daily — hourly is rate-limited), computes features with the same
compute_features pipeline used at inference, labels via 5-bar-forward
direction with a 0.5% dead zone, and trains separate XGBoost models for
"india" and "crypto".

Persistence layout (under /app/data/ml/ at runtime):
    model_india.json     — XGBoost native JSON
    model_crypto.json    — XGBoost native JSON
    scaler_india.pkl     — fitted StandardScaler (pickle)
    scaler_crypto.pkl    — fitted StandardScaler
    training_meta.json   — {trained_at, samples_*, val_acc_*}

Standalone:
    python -m ml.train_from_history

Importable:
    from ml.train_from_history import train_all_markets
    meta = train_all_markets()
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Make repo importable when run as a script from anywhere
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from indicators.features import compute_features
from ml.xgboost_ensemble import (
    _CRYPTO_FEATURES,
    _INDIA_FEATURES,
    ModelConfig,
    MarketModel,
)

log = logging.getLogger("ml.train_from_history")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s %(message)s")

# ── Output paths (relative to project /app on Contabo) ────────────────────────
DATA_DIR = Path(os.environ.get("ENGINE_DATA_DIR", _ROOT / "data"))
ML_DIR   = DATA_DIR / "ml"
ML_DIR.mkdir(parents=True, exist_ok=True)

# ── Labelling policy (per spec) ────────────────────────────────────────────────
FWD_HORIZON = 5
DEAD_ZONE   = 0.005   # ±0.5% — bars in this zone are dropped, not labelled

# ── Symbol universes (mirror live_paper_runner) ────────────────────────────────
CRYPTO_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT",
    "LINK/USDT", "DOT/USDT", "AVAX/USDT",
]

# (symbol, angel_token, exchange)
NSE_SYMBOLS = [
    ("HDFCBANK",   "1333",  "NSE"),
    ("ICICIBANK",  "4963",  "NSE"),
    ("KOTAKBANK",  "1922",  "NSE"),
    ("SBIN",       "3045",  "NSE"),
    ("RELIANCE",   "2885",  "NSE"),
    ("TCS",        "11536", "NSE"),
    ("INFY",       "1594",  "NSE"),
    ("HINDUNILVR", "1394",  "NSE"),
    ("ITC",        "1660",  "NSE"),
    ("MARUTI",     "10999", "NSE"),
    ("SUNPHARMA",  "3351",  "NSE"),
]


# ── Fetchers ───────────────────────────────────────────────────────────────────

def fetch_binance_history(symbol: str, n_bars: int = 4500) -> pd.DataFrame | None:
    """Fetch up to n_bars hourly OHLCV from Binance — chunked because Binance
    caps each call at 1000 bars. Default 4500 = ~6 months hourly, sufficient
    for 5-fold walk-forward CV with meaningful sample sizes per fold."""
    import ccxt
    ex = ccxt.binance({"enableRateLimit": True})
    out: list[list] = []
    since = ex.milliseconds() - n_bars * 60 * 60 * 1000
    while len(out) < n_bars:
        try:
            chunk = ex.fetch_ohlcv(symbol, "1h", since=since, limit=1000)
        except Exception as e:  # noqa: BLE001
            log.warning(f"  binance fetch {symbol}: {e}")
            return None
        if not chunk:
            break
        out.extend(chunk)
        since = chunk[-1][0] + 60 * 60 * 1000
        if len(chunk) < 1000:
            break
    if not out:
        return None
    df = pd.DataFrame(out, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="ts").reset_index(drop=True)
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df[["open", "high", "low", "close", "volume"]]


def fetch_angel_history(symbol: str, token: str, exchange: str,
                        days_back: int = 365 * 2) -> pd.DataFrame | None:
    """Daily bars from Angel One — covers ~500 trading days in 2 years."""
    try:
        import pyotp
        from SmartApi import SmartConnect
    except ImportError:
        log.warning("  smartapi-python missing — skip India fetch")
        return None

    api_key   = os.environ.get("INDIA__ANGEL_API_KEY", "")
    client_id = os.environ.get("INDIA__ANGEL_CLIENT_ID", "")
    pin       = os.environ.get("INDIA__ANGEL_PIN", "")
    totp_sec  = os.environ.get("INDIA__ANGEL_TOTP_SECRET", "")
    if not all([api_key, client_id, pin, totp_sec]):
        log.warning("  Angel One credentials missing — skip India fetch")
        return None

    # Reuse a singleton client across symbols
    global _angel_client
    if "_angel_client" not in globals() or _angel_client is None:
        cli = SmartConnect(api_key=api_key)
        totp = pyotp.TOTP(totp_sec).now()
        resp = cli.generateSession(client_id, pin, totp)
        if not resp or not resp.get("status"):
            log.warning(f"  Angel auth failed: {resp}")
            return None
        _angel_client = cli  # type: ignore[name-defined]

    from datetime import timedelta
    to_dt   = datetime.now()
    from_dt = to_dt - timedelta(days=days_back)
    try:
        resp = _angel_client.getCandleData({  # type: ignore[name-defined]
            "exchange":    exchange,
            "symboltoken": token,
            "interval":    "ONE_DAY",
            "fromdate":    from_dt.strftime("%Y-%m-%d %H:%M"),
            "todate":      to_dt.strftime("%Y-%m-%d %H:%M"),
        })
    except Exception as e:  # noqa: BLE001
        log.warning(f"  angel fetch {symbol}: {e}")
        return None
    if not resp or not resp.get("status") or not resp.get("data"):
        return None
    rows = resp["data"]
    df = pd.DataFrame([
        {"open": float(r[1]), "high": float(r[2]), "low": float(r[3]),
         "close": float(r[4]), "volume": float(r[5])}
        for r in rows
    ], index=pd.to_datetime([r[0] for r in rows], utc=True))
    return df.sort_index()


# ── Feature derivation (mirror runner._score_ml mapping) ───────────────────────

def _derive_features(df: pd.DataFrame) -> pd.DataFrame:
    """Run compute_features and add the synthesised columns the model expects."""
    feats = compute_features(df)
    close = feats["close"]
    feats["return_1d"] = feats["returns_1d"] = close.pct_change(1)
    feats["return_5d"] = feats["returns_5d"] = close.pct_change(5)
    feats["return_20d"] = feats["returns_20d"] = close.pct_change(20)
    if "ema_50" in feats:
        feats["ema_spread_pct"] = (close - feats["ema_50"]) / feats["ema_50"].replace(0, np.nan)
    else:
        feats["ema_spread_pct"] = 0.0
    if "atr_14" in feats:
        feats["atr_pct"] = feats["atr_14"] / close.replace(0, np.nan)
    feats["hist_vol_20"] = close.pct_change().rolling(20).std()
    if "volume" in feats and "volume" in df:
        vol_mean = df["volume"].rolling(20).mean()
        feats["vol_ratio"] = feats["vol_ratio_20"] = (
            df["volume"] / vol_mean.replace(0, np.nan)
        )
    feats["india_vix"] = 15.0  # constant proxy — real VIX not available in OHLCV
    return feats


# ── Labelling ──────────────────────────────────────────────────────────────────

def _label(close: pd.Series, horizon: int = FWD_HORIZON, dead: float = DEAD_ZONE) -> pd.Series:
    """5-bar-forward return; label 1 if > +0.5%, 0 if < -0.5%, NaN otherwise."""
    fwd = close.shift(-horizon) / close - 1.0
    out = pd.Series(np.nan, index=close.index)
    out[fwd > +dead] = 1.0
    out[fwd < -dead] = 0.0
    return out


def _build_xy(symbols_data: dict[str, pd.DataFrame], feature_cols: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Stack labelled samples across all symbols."""
    rows: list[np.ndarray] = []
    labels: list[float] = []
    for sym, df in symbols_data.items():
        if df is None or len(df) < 60:
            log.info(f"  skip {sym}: only {0 if df is None else len(df)} bars")
            continue
        try:
            feats = _derive_features(df)
            y = _label(feats["close"])
            X_sym = feats[feature_cols].copy()
            mask = y.notna() & X_sym.notna().all(axis=1)
            if mask.sum() == 0:
                continue
            rows.append(X_sym[mask].values)
            labels.extend(y[mask].astype(int).tolist())
            log.info(f"  {sym}: kept {int(mask.sum())} of {len(df)} bars after labeling")
        except Exception as e:  # noqa: BLE001
            log.warning(f"  feature/label {sym}: {e}")
    if not rows:
        return np.empty((0, len(feature_cols))), np.empty(0)
    return np.vstack(rows), np.asarray(labels, dtype=int)


# ── Training ───────────────────────────────────────────────────────────────────

def train_market(market: str, symbols_data: dict[str, pd.DataFrame],
                 feature_cols: list[str], min_samples: int = 500) -> dict:
    """Train one market's XGBoost on real OHLCV. Returns metadata dict."""
    from xgboost import XGBClassifier
    X, y = _build_xy(symbols_data, feature_cols)
    log.info(f"[{market}] dataset: X={X.shape}, label balance={y.mean() if len(y) else 0:.2f}")
    if len(y) < min_samples:
        log.warning(f"[{market}] only {len(y)} samples (< {min_samples}) — skipping training")
        return {"market": market, "samples": int(len(y)), "skipped": True}
    if len(np.unique(y)) < 2:
        log.warning(f"[{market}] single class only — skipping")
        return {"market": market, "samples": int(len(y)), "skipped": True}

    config = ModelConfig()
    clf = XGBClassifier(
        n_estimators=config.n_estimators, max_depth=config.max_depth,
        learning_rate=config.learning_rate, subsample=config.subsample,
        colsample_bytree=config.colsample_bytree, random_state=config.random_state,
        eval_metric=config.eval_metric, verbosity=0,
    )
    mm = MarketModel(market=market, features=feature_cols, model=clf)
    metrics = mm.fit(X, y)

    # Persist
    model_path  = ML_DIR / f"model_{market}.json"
    scaler_path = ML_DIR / f"scaler_{market}.pkl"
    mm.model.save_model(str(model_path))
    with open(scaler_path, "wb") as f:
        pickle.dump(mm.scaler, f)
    log.info(f"[{market}] saved {model_path.name} + {scaler_path.name}")
    calibrator_path = ML_DIR / f"calibrator_{market}.pkl"
    if mm.calibrator is not None:
        with open(calibrator_path, "wb") as f:
            pickle.dump(mm.calibrator, f)
        log.info(f"[{market}] calibrator saved → {calibrator_path.name}")
    else:
        log.warning(f"[{market}] calibrator is None — not saved (will use raw XGBoost probs)")

    return {
        "market":   market,
        "samples":  int(len(y)),
        "val_acc":  float(metrics["val_acc"]),
        "train_acc": float(metrics["train_acc"]),
        "skipped":  False,
    }


def train_all_markets(min_samples: int = 500) -> dict:
    """Top-level entry: fetch + train + persist for all markets."""
    log.info("════════ AAATS real-bar ML training ════════")
    meta: dict = {"trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    # ── Crypto ──
    log.info("── Crypto: Binance hourly bars ──")
    crypto_data: dict[str, pd.DataFrame] = {}
    for sym in CRYPTO_SYMBOLS:
        log.info(f"  fetching {sym}...")
        df = fetch_binance_history(sym, n_bars=4500)  # ~6mo hourly for walk-forward
        if df is not None:
            log.info(f"  {sym}: {len(df)} bars")
            crypto_data[sym] = df
        time.sleep(0.5)  # courteous
    crypto_meta = train_market("crypto", crypto_data, _CRYPTO_FEATURES, min_samples)
    meta.update({
        "samples_crypto":  crypto_meta.get("samples", 0),
        "val_acc_crypto":  crypto_meta.get("val_acc"),
        "skipped_crypto":  crypto_meta.get("skipped", False),
    })

    # ── India ──
    log.info("── India: Angel One daily bars ──")
    india_data: dict[str, pd.DataFrame] = {}
    for sym, token, exch in NSE_SYMBOLS:
        log.info(f"  fetching {sym}...")
        df = fetch_angel_history(sym, token, exch, days_back=365 * 2)
        if df is not None:
            log.info(f"  {sym}: {len(df)} bars")
            india_data[sym] = df
        time.sleep(0.4)  # angel rate-limit ~3/s
    india_meta = train_market("india", india_data, _INDIA_FEATURES, min_samples)
    meta.update({
        "samples_india":  india_meta.get("samples", 0),
        "val_acc_india":  india_meta.get("val_acc"),
        "skipped_india":  india_meta.get("skipped", False),
    })

    # Persist meta
    meta_path = ML_DIR / "training_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    log.info(f"════════ done — meta saved to {meta_path} ════════")
    log.info(json.dumps(meta, indent=2))

    # Edge warnings
    for mkt in ("india", "crypto"):
        v = meta.get(f"val_acc_{mkt}")
        if v is not None and v < 0.53:
            log.warning(
                f"⚠️  {mkt.upper()} val_acc={v:.3f} < 0.53 — model has no edge; "
                f"live ml_size_scale will pass through 1.0"
            )

    return meta


# ── Loader for the live runner ─────────────────────────────────────────────────

def load_saved_models(max_age_days: int = 7) -> dict | None:
    """Try to load saved models. Return ensemble dict or None if stale/missing."""
    from datetime import timedelta
    meta_path = ML_DIR / "training_meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text())
        trained_at = datetime.fromisoformat(meta["trained_at"])
        age = datetime.now(timezone.utc) - trained_at
        if age > timedelta(days=max_age_days):
            log.info(f"saved models are {age.days}d old (> {max_age_days}d) — will retrain")
            return None
    except Exception as e:  # noqa: BLE001
        log.warning(f"meta read failed: {e}")
        return None

    from xgboost import XGBClassifier
    ensemble: dict = {}
    for market, features in [("india", _INDIA_FEATURES), ("crypto", _CRYPTO_FEATURES)]:
        model_path  = ML_DIR / f"model_{market}.json"
        scaler_path = ML_DIR / f"scaler_{market}.pkl"
        if not (model_path.exists() and scaler_path.exists()):
            # Skip markets that were intentionally not trained (e.g. India with no credentials)
            # rather than aborting the whole load — crypto should still work.
            skipped = meta.get(f"skipped_{market}", False)
            if skipped:
                log.info(f"  [{market}] skipped at training time — omitting from ensemble")
                continue
            log.info(f"saved {market} model missing and not marked skipped — will retrain")
            return None
        try:
            clf = XGBClassifier()
            clf.load_model(str(model_path))
            with open(scaler_path, "rb") as f:
                scaler = pickle.load(f)
            mm = MarketModel(market=market, features=features, model=clf)
            mm.scaler = scaler
            mm.is_trained = True
            calibrator_path = ML_DIR / f"calibrator_{market}.pkl"
            if calibrator_path.exists():
                with open(calibrator_path, "rb") as f:
                    mm.calibrator = pickle.load(f)
                log.info(f"  [{market}] Platt calibrator loaded from {calibrator_path.name}")
            else:
                log.warning(f"  [{market}] calibrator_{market}.pkl missing — using raw XGBoost probs")
            ensemble[market] = mm
        except Exception as e:  # noqa: BLE001
            log.warning(f"load {market} failed: {e}")
            return None
    if not ensemble:
        log.warning("No models loaded — all markets skipped or missing")
        return None
    log.info(f"Loaded saved XGBoost models (trained: {meta.get('trained_at')}) markets={list(ensemble.keys())}")
    return ensemble


if __name__ == "__main__":
    train_all_markets()
