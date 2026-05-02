"""
Crypto paper trading runner — Binance via CCXT.

Each cycle:
  1. Discover top-N USDT pairs by 24h volume on Binance
  2. For each pair: fetch OHLCV → detect regime → generate signal
  3. Paper trade → data/paper_trades.db
  4. Write live status → data/status.db

Signal: EMA crossover + RSI confirmation
  BUY  — BULL_TREND + RSI < 65 + not already long
  SELL — BEAR_TREND or HIGH_VOLATILITY + currently long
  HOLD — RANGE_BOUND or no confirmation

Run standalone:  python main.py --mode paper --market crypto
"""

from __future__ import annotations

import time
from pathlib import Path

import ccxt
import pandas as pd

from foundation.logger import get_logger
from foundation.kill_switch import is_halted
from markets.crypto.integration import CryptoConfig, run_data_cycle
from risk.engine import RiskEngine
from risk.position_manager import PersistentPositionManager
from risk.position_sizer import PositionSizer
from risk.drawdown_monitor import DrawdownMonitor
from risk.funding_monitor import FundingMonitor
from analytics.pnl_attribution import PnLAttribution
from analytics.slippage_tracker import SlippageTracker
from execution.order_validator import OrderValidator
from execution.paper_trader import record_trade
from execution.status_db import upsert_status, mark_running, write_heartbeat

_log = get_logger("execution", "crypto_runner")

_DB = str(Path(__file__).parent.parent / "data" / "paper_trades.db")
_CRYPTO_DB = str(Path(__file__).parent.parent / "data" / "crypto.db")

_TOP_N = 20                   # how many top-volume USDT pairs to scan
_CAPITAL_USDT = 10_000.0
_POSITION_PCT = 0.05          # 5% per trade
_POLL_SECONDS = 3600          # re-check every hour


def _top_usdt_symbols(n: int = _TOP_N) -> list[str]:
    """Return top-N Binance USDT pairs by 24h quote volume."""
    try:
        exchange = ccxt.binance({"enableRateLimit": True})
        tickers = exchange.fetch_tickers()
        usdt = [
            (sym, float(t.get("quoteVolume") or 0))
            for sym, t in tickers.items()
            if sym.endswith("/USDT") and t.get("quoteVolume")
        ]
        usdt.sort(key=lambda x: x[1], reverse=True)
        symbols = [sym for sym, _ in usdt[:n]]
        _log.info(f"Top {n} USDT pairs: {symbols[:5]}… (total {len(symbols)})")
        return symbols
    except Exception as exc:
        _log.error(f"Symbol scan failed: {exc} — falling back to defaults")
        return ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT"]


def _signal(regime: str, latest_bar: dict) -> str:
    rsi = latest_bar.get("rsi_14", 50)
    if regime == "BULL_TREND" and rsi < 65:
        return "BUY"
    if regime in ("BEAR_TREND", "HIGH_VOLATILITY"):
        return "SELL"
    return "HOLD"


def run_once(symbols: list[str] | None = None) -> int:
    """Run one full cycle. Returns number of trades executed."""
    if is_halted("crypto"):
        _log.warning("Crypto market HALTED — skipping cycle")
        upsert_status("crypto", status="HALTED")
        return 0

    # Mark RUNNING but preserve previous cycle's regime so dashboard stays informative
    mark_running("crypto")
    symbols = symbols or _top_usdt_symbols(_TOP_N)

    config = CryptoConfig(
        symbols=symbols,
        timeframe="1Hour",
        db_path=_CRYPTO_DB,
        lookback_hours=250,
        capital_usdt=_CAPITAL_USDT,
    )

    risk = RiskEngine(initial_portfolio=_CAPITAL_USDT * len(symbols))
    pm = PersistentPositionManager(market="crypto")
    sizer = PositionSizer(capital=_CAPITAL_USDT)
    dd_monitor = DrawdownMonitor(market="crypto", initial_equity=_CAPITAL_USDT)
    funding = FundingMonitor()
    pnl_attr = PnLAttribution()
    slippage = SlippageTracker()
    validator = OrderValidator(market="crypto")
    trades_done = 0
    regimes_seen = []

    # Check funding rates (non-fatal — network issue should not abort the cycle)
    try:
        perp_symbols = [s.replace("/USDT", "/USDT:USDT") for s in symbols[:5]]
        funding.check_funding_rates(perp_symbols)
    except Exception as _fund_exc:
        _log.warning(f"Funding rate check failed (non-fatal): {_fund_exc}")

    for i, symbol in enumerate(symbols):
        # Write heartbeat every 5 symbols so dashboard sees runner is alive mid-cycle
        if i % 5 == 0:
            write_heartbeat("crypto")
        try:
            snapshot = run_data_cycle(symbol, config)

            if snapshot.error:
                _log.error(f"{symbol}: skipping — {snapshot.error}")
                continue

            regime = snapshot.regime
            bar = snapshot.latest_bar
            price = bar.get("close", 0.0)
            regimes_seen.append(regime)

            if price <= 0:
                continue

            sig = _signal(regime, bar)
            _log.info(f"{symbol} | regime={regime} | signal={sig} | price={price:.4f}")

            if sig == "BUY" and not pm.has_open_position(symbol):
                atr = bar.get("atr_14", price * 0.02)
                size = sizer.calculate_position_size(price=price, atr=atr)
                shares = round(size.shares, 6) or round((_CAPITAL_USDT * _POSITION_PCT) / price, 6)
                vr = validator.validate(symbol=symbol, price=price, shares=shares)
                if not vr.valid:
                    _log.warning(f"{symbol}: order rejected — {vr.reason}")
                    continue
                decision = risk.check_new_order("crypto", price, shares, _CAPITAL_USDT)
                if decision.action in ("ALLOW", "REDUCE"):
                    if decision.action == "REDUCE":
                        shares = round(shares * decision.allowed_fraction, 6)
                    pm.open_position(symbol, entry_price=price, shares=shares)
                    record_trade(
                        db_path=_DB, market="crypto", symbol=symbol,
                        action="BUY", shares=shares, price=price,
                        signal=sig, regime=regime, risk_action=decision.action,
                    )
                    slippage.record_slippage(symbol=symbol, expected=price, actual=price,
                                             side="BUY", market="crypto", shares=shares)
                    sizer.add_position_heat(size.risk_pct)
                    trades_done += 1

            elif sig == "SELL" and pm.has_open_position(symbol):
                open_positions = pm.get_open_positions()
                entry_pos = next((p for p in open_positions if p["symbol"] == symbol), None)
                entry = entry_pos["entry_price"] if entry_pos else price
                shares = round((_CAPITAL_USDT * _POSITION_PCT) / max(entry, 1e-9), 6)
                pnl = pm.close_position(symbol, exit_price=price) or 0.0
                record_trade(
                    db_path=_DB, market="crypto", symbol=symbol,
                    action="SELL", shares=shares, price=price,
                    signal=sig, regime=regime, risk_action="ALLOW", pnl=pnl,
                )
                slippage.record_slippage(symbol=symbol, expected=entry, actual=price,
                                         side="SELL", market="crypto", shares=shares)
                pnl_attr.record_trade(
                    market="crypto", symbol=symbol, pnl=pnl, side="SELL",
                    regime=regime, entry_price=entry, exit_price=price, shares=shares,
                )
                risk.update_market("crypto", _CAPITAL_USDT + pnl)
                dd_monitor.update(_CAPITAL_USDT + pnl_attr.total_pnl("crypto"))
                trades_done += 1

        except Exception as _sym_exc:
            _log.error(f"{symbol}: unexpected error — {_sym_exc}")

    dominant = max(set(regimes_seen), key=regimes_seen.count) if regimes_seen else "UNKNOWN"
    upsert_status(
        "crypto",
        regime=dominant,
        symbols_scanned=len(regimes_seen),
        trades_today=trades_done,
        status="OK",
    )
    return trades_done


def run_loop(symbols: list[str] | None = None, poll_seconds: int = _POLL_SECONDS) -> None:
    """Continuous loop. Ctrl-C to stop."""
    _log.info(f"Crypto paper trading loop started. Poll: {poll_seconds}s")
    while True:
        try:
            run_once(symbols)
        except KeyboardInterrupt:
            _log.info("Crypto runner stopped.")
            break
        except Exception as exc:
            _log.error(f"Cycle error: {exc}")
            upsert_status("crypto", status="ERROR", error=str(exc))
        _log.info(f"Sleeping {poll_seconds}s…")
        time.sleep(poll_seconds)
