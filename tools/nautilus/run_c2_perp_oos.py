"""C2 momentum-breakout on BTC+ETH perps — graduation test (B.1.7 Track 7).

The orthogonal-architecture diversifier test. C2 is structurally OPPOSITE C3:
trend-following / breakout (buy strength) vs C3's mean-reversion (buy weakness).
Per-trade correlation to C3-perp should be near-zero by signal-class opposition.
This is the last untested architecture class in the existing AAATS catalog.

Strategy (4H bars, long-only, BTC+ETH perps):
  Entry (ALL true on the 4H bar close):
    - close > 20-bar rolling high (excl. current bar — pure breakout)
    - RSI(14) > 52
    - volume > 1.4 * 20-bar avg volume
    - EMA(12) > EMA(26) on 4H closes (trending regime)
    (Fear&Greed gate SKIPPED for this test — not cached. F&G is PERMISSIVE
     [skips entries only on extreme greed], so running without it is a STRICTER
     edge signal: if C2-perp passes here it passes with F&G too. Caveat labelled.)
  Exit (first match wins, evaluated each 4H bar after entry; PnL = vs entry close):
    - PnL >= +2.0%                     take-profit
    - PnL <= -1.2%                     hard stop
    - age >= 8h AND PnL >= +0.8%       time profit-protect stop
    - age >= 4h AND abs(PnL) < 0.3%    stagnation exit
  Sizing: $10/position, max 2 concurrent (BTC + ETH). Market orders both sides.

NOTE on exit semantics: this harness implements the exit conditions as ENUMERATED
in the Track 7 prompt's Strategy spec. That differs from the box module's
`trading/momentum_breakout.py:_check_exits` in two places: (a) the box time-stop
CUTS a stagnant trade after 8h if PnL < +0.8%, whereas the prompt's time stop
PROTECTS a profit by exiting after 8h if PnL >= +0.8%; (b) the box stagnation
measures move vs the previous 4H close, the prompt measures abs(PnL) vs entry.
The prompt's enumerated spec is authoritative for this graduation run; the
discrepancy is surfaced in the verdict report so the operator can decide whether
it matters for a follow-up.

The two pure indicator helpers (`_resample_4h`, `_add_indicators`) are copied
VERBATIM from trading/momentum_breakout.py — the box module cannot be imported in
the NT venv (it pulls in execution.paper_trader -> loguru, a box-only dep), and
the read-only rule forbids refactoring it. The indicator math is therefore
identical to the box's C2, only inlined.

  - DATA: real Binance USDT-M perp 1h klines, resampled to 4H in-harness.
  - FEES: Binance perp VIP-0 (maker 2bps / taker 5bps); market orders => taker.
  - FUNDING: real Binance funding applied to every open long at each 8h
    settlement it crosses (long pays when rate>0 — a cost for long-only C2),
    subtracted from realized PnL for the gate metrics (same as C3-perp funded).

    python3 tools/nautilus/run_c2_perp_oos.py

NT is a dev-only dependency (pinned in requirements-dev.txt); the box never
imports it.

Plan: docs/decisions/2026-05-28_b17_c3_supplements_plan.md (Track 7). Verdict
written to data/graduation/C2_momentum_perp_<today>.json.
"""

# ruff: noqa: E402  — sys.path bootstrap (below) must precede repo-local imports
from __future__ import annotations

import sys
import json
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.backtest.models import MakerTakerFeeModel, FillModel
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.enums import (
    AccountType,
    OmsType,
    CurrencyType,
    OrderSide,
)
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Money, Price, Quantity, Currency
from nautilus_trader.model.data import BarType
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from tools.graduation.gate import evaluate_gate, emit_report

VENUE = Venue("BINANCE")
UNIVERSE = ["BTC", "ETH"]
CLOCK = "BTC"  # BTC 4H bar drives the cycle
HIST = ROOT / "data" / "historical"
START_CAPITAL = 100.0

# --- C2 params (mirror trading/momentum_breakout.py; NOT tuned this session) ---
BREAKOUT_BARS = 20
RSI_ENTRY_MIN = 52
VOL_MULT = 1.4
TARGET_PCT = 0.020
STOP_PCT = 0.012
TIME_STOP_HOURS = 8
TIME_STOP_MIN_PCT = 0.008
STAGNATION_PCT = 0.003
STAGNATION_AGE_H = 4.0
LEG_NOTIONAL = 10.0  # $10 per position
MAX_CONCURRENT = 2
BAR_HOURS = 4  # 4H bars

# Binance PERP VIP-0 fees: maker 2bps, taker 5bps.
FEE_MAKER = Decimal("0.0002")
FEE_TAKER = Decimal("0.0005")
# 6mo window split, same cutoff as the C3-perp harness (apples-to-apples).
OOS_CUTOFF = pd.Timestamp("2026-03-28", tz="UTC")


def _money(m) -> float:
    try:
        return float(m.as_double())
    except Exception:
        return float(str(m).split()[0])


def make_ccy(code: str) -> Currency:
    try:
        return Currency.from_str(code)
    except Exception:
        return Currency(
            code, precision=8, iso4217=0, name=code, currency_type=CurrencyType.CRYPTO
        )


def make_perp(base_code: str) -> CryptoPerpetual:
    base = make_ccy(base_code)
    return CryptoPerpetual(
        instrument_id=InstrumentId(symbol=Symbol(f"{base_code}USDT-PERP"), venue=VENUE),
        raw_symbol=Symbol(f"{base_code}USDT"),
        base_currency=base,
        quote_currency=USDT,
        settlement_currency=USDT,
        is_inverse=False,
        price_precision=4,
        price_increment=Price(1e-4, precision=4),
        size_precision=6,
        size_increment=Quantity(1e-6, precision=6),
        max_quantity=Quantity(1e9, precision=6),
        min_quantity=Quantity(1e-6, precision=6),
        max_notional=None,
        min_notional=Money(1.0, USDT),
        max_price=Price(1e7, precision=4),
        min_price=Price(1e-4, precision=4),
        margin_init=Decimal(0),
        margin_maint=Decimal(0),
        maker_fee=FEE_MAKER,
        taker_fee=FEE_TAKER,
        ts_event=0,
        ts_init=0,
    )


# ---- indicator helpers — copied VERBATIM from trading/momentum_breakout.py ----
def _resample_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """Resample 1H OHLCV dataframe to 4H bars (verbatim from box C2)."""
    df = df_1h.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index, utc=True)
        except Exception:
            return pd.DataFrame()
    df = df.sort_index()
    ohlcv = (
        df[["open", "high", "low", "close", "volume"]]
        .resample("4h")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna()
    )
    return ohlcv


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """RSI(14), EMA12/26, rolling_high_20, vol_avg_20 (verbatim from box C2)."""
    out = df.copy()
    close = out["close"]
    volume = out["volume"]

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    out["rsi_14"] = 100 - (100 / (1 + rs))

    out["ema_12"] = close.ewm(span=12, adjust=False).mean()
    out["ema_26"] = close.ewm(span=26, adjust=False).mean()

    out["rolling_high_20"] = out["high"].rolling(BREAKOUT_BARS).max().shift(1)
    out["vol_avg_20"] = volume.rolling(BREAKOUT_BARS).mean()

    return out.dropna(subset=["rsi_14", "rolling_high_20", "vol_avg_20"])


def load_perp_1h(sym: str) -> pd.DataFrame:
    df = pd.read_parquet(HIST / f"{sym}_USDT_1h_perp.parquet")
    df.columns = [c.lower() for c in df.columns]
    df.index = pd.to_datetime(df["ts"], utc=True)
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def load_4h_bars(sym: str) -> pd.DataFrame:
    return _resample_4h(load_perp_1h(sym))


def load_indicators(sym: str) -> pd.DataFrame:
    """Precompute the full 4H indicator frame. Each row's indicators depend only
    on bars <= that row (rolling/ewm/shift), so indexing it at on_bar(T) is
    causally correct — no lookahead."""
    return _add_indicators(load_4h_bars(sym))


def load_funding(sym: str) -> pd.Series:
    f = HIST / f"{sym}_USDT_funding.parquet"
    if not f.exists():
        return pd.Series(dtype=float)
    df = pd.read_parquet(f)
    s = df.set_index(pd.to_datetime(df["ts_funding"], utc=True))["funding_rate"].astype(
        float
    )
    return s.sort_index()


class C2MomentumPerpStrategy(Strategy):
    """4H breakout on BTC+ETH perps with real funding applied to open longs.

    BTC 4H bar is the clock (ts_init_delta=1 so it processes after ETH at the
    same timestamp). Funding is applied each cycle after exits, before entries,
    to all still-open longs that crossed an 8h settlement in the last 4H window.
    Closed round-trips are recorded in self.trades via on_position_closed with
    funding subtracted (same exact attribution as the C3-perp funded harness).
    """

    def __init__(self, config, instruments, bar_types):
        super().__init__(config)
        self.instruments = instruments
        self.bar_types = bar_types
        self.ind = {s: load_indicators(s) for s in UNIVERSE}
        self.funding = {s: load_funding(s) for s in UNIVERSE}
        self.meta = {}  # sym -> open-position meta (incl funding_paid_usd)
        self.funding_pending_close = {}  # sym -> funding stashed at exit
        self.trades = []  # closed round-trip ledger
        self.idx = 0
        self.n_entries = 0
        self.n_exits = 0
        self.n_funding_events = 0
        # architecture diagnostic — per-gate pass counts over entry-eligible bars
        self.gate_counts = {
            "eligible_bars": 0,
            "breakout": 0,
            "rsi": 0,
            "volume": 0,
            "ema": 0,
            "all_four": 0,
        }

    def on_start(self):
        for s in UNIVERSE:
            self.subscribe_bars(self.bar_types[s])

    def _sym_of(self, bar):
        return bar.bar_type.instrument_id.symbol.value.split("USDT")[0]

    def on_position_closed(self, event):
        sym = event.instrument_id.symbol.value.split("USDT")[0]
        funding = self.funding_pending_close.pop(sym, 0.0)
        realized = _money(event.realized_pnl)  # price PnL incl. fees
        notional = abs(float(event.avg_px_open) * float(event.peak_qty)) or 1.0
        ts = event.ts_closed if event.ts_closed else event.ts_event
        self.trades.append(
            {
                "sym": sym,
                "pnl_gross": realized,
                "funding": funding,
                "pnl_net": realized - funding,
                "notional": notional,
                "ts": int(ts),
            }
        )

    def on_bar(self, bar):
        sym = self._sym_of(bar)
        if sym != CLOCK:
            return  # ETH bars only advance NT's clock; BTC drives the cycle
        self.idx += 1
        current_ts = pd.Timestamp(bar.ts_event, unit="ns", tz="UTC")

        # ---- EXIT phase (market sells; first-match-wins per prompt spec) ----
        for s in list(self.meta):
            row = self._row_at(s, current_ts)
            if row is None:
                continue
            m = self.meta[s]
            price = float(row["close"])
            pct = (price - m["entry_price"]) / m["entry_price"]
            age_h = (self.idx - m["entry_idx"]) * BAR_HOURS
            reason = None
            if pct >= TARGET_PCT:
                reason = "target"
            elif pct <= -STOP_PCT:
                reason = "hard_stop"
            elif age_h >= TIME_STOP_HOURS and pct >= TIME_STOP_MIN_PCT:
                reason = "time_profit_protect"
            elif age_h >= STAGNATION_AGE_H and abs(pct) < STAGNATION_PCT:
                reason = "stagnation"
            if reason:
                inst = self.instruments[s]
                self.submit_order(
                    self.order_factory.market(
                        inst.id, OrderSide.SELL, inst.make_qty(m["shares"])
                    )
                )
                self.n_exits += 1
                self.funding_pending_close[s] = m.get("funding_paid_usd", 0.0)
                del self.meta[s]

        # ---- FUNDING phase (after exits, before entries) ----
        prev_ts = current_ts - pd.Timedelta(hours=BAR_HOURS)
        for s, m in self.meta.items():
            s_funding = self.funding.get(s)
            if s_funding is None or len(s_funding) == 0:
                continue
            events = s_funding[
                (s_funding.index > prev_ts) & (s_funding.index <= current_ts)
            ]
            for _ts_f, rate in events.items():
                funding_cost = m["shares"] * m["entry_price"] * float(rate)
                m["funding_paid_usd"] = m.get("funding_paid_usd", 0.0) + funding_cost
                self.n_funding_events += 1

        # ---- ENTRY phase ----
        for s in UNIVERSE:
            if s in self.meta:
                continue
            row = self._row_at(s, current_ts)
            if row is None:
                continue
            self.gate_counts["eligible_bars"] += 1
            close = float(row["close"])
            breakout = close > float(row["rolling_high_20"])
            rsi_ok = float(row["rsi_14"]) > RSI_ENTRY_MIN
            vol_avg = float(row["vol_avg_20"])
            vol_ok = vol_avg > 0 and (float(row["volume"]) / vol_avg) >= VOL_MULT
            ema_ok = float(row["ema_12"]) > float(row["ema_26"])
            self.gate_counts["breakout"] += int(breakout)
            self.gate_counts["rsi"] += int(rsi_ok)
            self.gate_counts["volume"] += int(vol_ok)
            self.gate_counts["ema"] += int(ema_ok)
            if not (breakout and rsi_ok and vol_ok and ema_ok):
                continue
            self.gate_counts["all_four"] += 1
            if len(self.meta) >= MAX_CONCURRENT:
                continue
            inst = self.instruments[s]
            qty = inst.make_qty(LEG_NOTIONAL / close)
            if float(qty) <= 0:
                continue
            self.submit_order(self.order_factory.market(inst.id, OrderSide.BUY, qty))
            self.meta[s] = {
                "entry_idx": self.idx,
                "entry_price": close,
                "shares": float(qty),
                "funding_paid_usd": 0.0,
            }
            self.n_entries += 1

    def _row_at(self, sym, ts):
        df = self.ind.get(sym)
        if df is None or ts not in df.index:
            return None
        return df.loc[ts]


def _sharpe(rets):
    if len(rets) < 2 or rets.std(ddof=1) <= 1e-12:
        return 0.0
    # sqrt(60) per-trade annualization — identical to the C3 harness family.
    return float(rets.mean() / rets.std(ddof=1) * np.sqrt(60.0))


def _sharpe_pnl_for_window(rows, oos: bool):
    cut = int(OOS_CUTOFF.value)
    sub = [r for r in rows if (r["ts"] >= cut) == oos]
    if len(sub) < 2:
        return 0.0, round(float(sum(r["pnl_net"] for r in sub)), 4)
    rets = np.array(
        [r["pnl_net"] / r["notional"] if r["notional"] else 0.0 for r in sub]
    )
    return round(_sharpe(rets), 4), round(float(sum(r["pnl_net"] for r in sub)), 4)


def _metrics_from_trades(trades, start_capital=START_CAPITAL):
    rows = sorted(trades, key=lambda r: r["ts"])
    if not rows:
        return {
            "net_pnl_usd": 0.0,
            "gross_pnl_usd": 0.0,
            "funding_total_usd": 0.0,
            "n_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "sharpe": 0.0,
            "max_drawdown_pct": 0.0,
            "total_notional_usd": 0.0,
            "_rows": [],
        }
    pnls = np.array([r["pnl_net"] for r in rows])
    rets = np.array(
        [r["pnl_net"] / r["notional"] if r["notional"] else 0.0 for r in rows]
    )
    gains = pnls[pnls > 0].sum()
    losses = -pnls[pnls < 0].sum()
    equity = start_capital + np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    max_dd = float(np.max((peak - equity) / peak)) if len(equity) else 0.0
    return {
        "net_pnl_usd": round(float(pnls.sum()), 4),
        "gross_pnl_usd": round(float(sum(r["pnl_gross"] for r in rows)), 4),
        "funding_total_usd": round(float(sum(r["funding"] for r in rows)), 4),
        "total_notional_usd": round(float(sum(r["notional"] for r in rows)), 2),
        "n_trades": int(len(rows)),
        "win_rate": round(float((pnls > 0).mean()), 4),
        "profit_factor": round(float(gains / losses), 4)
        if losses > 0
        else float("inf"),
        "sharpe": round(_sharpe(rets), 4),
        "max_drawdown_pct": round(max_dd, 4),
        "_rows": rows,
    }


def run_backtest():
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="C2perp-NT-001", logging=LoggingConfig(bypass_logging=True)
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=None,
        starting_balances=[Money(START_CAPITAL, USDT)],
        fee_model=MakerTakerFeeModel(),
        fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=7),
    )
    instruments, bar_types = {}, {}
    for sym in UNIVERSE:
        inst = make_perp(sym)
        engine.add_instrument(inst)
        bt = BarType.from_str(f"{inst.id}-4-HOUR-LAST-EXTERNAL")
        instruments[sym], bar_types[sym] = inst, bt
        # CLOCK (BTC) processed LAST each timestamp (delta=1) so ETH is current.
        delta = 1 if sym == CLOCK else 0
        bars = BarDataWrangler(bt, inst).process(load_4h_bars(sym), ts_init_delta=delta)
        engine.add_data(bars)
    strat = C2MomentumPerpStrategy(StrategyConfig(), instruments, bar_types)
    engine.add_strategy(strat)
    engine.run()
    out = {
        "trades": list(strat.trades),
        "n_entries": strat.n_entries,
        "n_exits": strat.n_exits,
        "n_open_at_end": len(strat.meta),
        "n_funding_events": strat.n_funding_events,
        "gate_counts": dict(strat.gate_counts),
    }
    engine.dispose()
    return out


def main():
    print(">>> C2 momentum-breakout: BTC+ETH perps, 4H bars, MARGIN, 6mo + FUNDING")
    res = run_backtest()
    mt = _metrics_from_trades(res["trades"])
    rows = mt["_rows"]
    is_sharpe, is_pnl = _sharpe_pnl_for_window(rows, oos=False)
    oos_sharpe, oos_pnl = _sharpe_pnl_for_window(rows, oos=True)
    gc = res["gate_counts"]

    metrics = {
        "net_pnl_usd": mt["net_pnl_usd"],  # after funding
        "sharpe": oos_sharpe,  # gate G2 evaluates OOS Sharpe (after funding)
        "max_drawdown_pct": mt["max_drawdown_pct"],
        "n_trades": mt["n_trades"],
        "profit_factor": mt["profit_factor"],
        "in_sample_sharpe": is_sharpe,
        "oos_sharpe": oos_sharpe,
        # G7: market orders => no honest maker sim; pnl_at_maker_0_5 == the run.
        "pnl_at_maker_0_5": mt["net_pnl_usd"],
        # funding stats
        "funding_total_usd_paid": mt["funding_total_usd"],
        "funding_events_count": res["n_funding_events"],
        # architecture diagnostic (binding-constraint analysis)
        "gate_eligible_bars": gc["eligible_bars"],
        "gate_pass_breakout": gc["breakout"],
        "gate_pass_rsi": gc["rsi"],
        "gate_pass_volume": gc["volume"],
        "gate_pass_ema": gc["ema"],
        "gate_pass_all_four": gc["all_four"],
        "n_entries": res["n_entries"],
        "n_exits": res["n_exits"],
        "n_open_at_end": res["n_open_at_end"],
        # context (not gate inputs)
        "_gross_pnl_usd_before_funding": mt["gross_pnl_usd"],
        "_full_sharpe": mt["sharpe"],
        "_win_rate": mt["win_rate"],
        "_is_pnl_usd": is_pnl,
        "_oos_pnl_usd": oos_pnl,
        "_total_notional_usd": mt["total_notional_usd"],
        "_per_trade_pnls": [round(r["pnl_net"], 4) for r in rows],
        "_per_trade_ts": [r["ts"] for r in rows],
        "_per_trade_sym": [r["sym"] for r in rows],
        "_data": "REAL Binance USDT-M perp 1h klines resampled to 4H (verbatim box C2 resample)",
        "_fee_model": "Binance perp VIP-0 maker=2bps/taker=5bps (MakerTakerFeeModel, taker)",
        "_funding": "real Binance funding; long pays when rate>0 (cost for long-only C2)",
        "_account": "MARGIN, margin_init=0",
        "_fg_gate": "SKIPPED (F&G not cached); permissive filter -> stricter signal without it",
        "_exit_spec": "per Track 7 prompt enumeration (differs from box _check_exits time-stop direction)",
        "_window": "2025-11-28 to 2026-05-27 (6mo, 4H bars); OOS = on/after 2026-03-28",
    }
    result = evaluate_gate(metrics)
    path = emit_report(
        "C2_momentum_perp",
        metrics,
        result,
        out_dir=str(ROOT / "data" / "graduation"),
    )

    print("\n========== C2-PERP MOMENTUM GRADUATION VERDICT ==========")
    print(
        json.dumps(
            {k: v for k, v in metrics.items() if not k.startswith("_")}, indent=2
        )
    )
    print(
        f"\ngross PnL before funding: {mt['gross_pnl_usd']:+.4f}  "
        f"funding: {mt['funding_total_usd']:+.4f}  -> net {mt['net_pnl_usd']:+.4f}"
    )
    print(
        f"entries={res['n_entries']} exits={res['n_exits']} open_at_end={res['n_open_at_end']}"
    )
    print(
        f"GATE DIAGNOSTIC over {gc['eligible_bars']} entry-eligible bars: "
        f"breakout={gc['breakout']} rsi={gc['rsi']} volume={gc['volume']} "
        f"ema={gc['ema']} -> all_four={gc['all_four']}"
    )
    print(f"VERDICT: {'PASS' if result.passed else 'FAIL'}")
    for g in sorted(result.criteria):
        c = result.criteria[g]
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {g}: {c['detail']}")
    print(f"\nreport: {path}")


if __name__ == "__main__":
    main()
