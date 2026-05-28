"""C3 altcoin-reversion validated on NautilusTrader — the graduation harness.

This is the "research brain" half of the NT+AAATS pipeline (see
docs/decisions/2026-05-27_nt_final_extraction_for_success.md). It runs C3 inside
NautilusTrader's deterministic backtest engine with a REALISTIC cost model
(MakerTakerFeeModel @ Binance VIP-0 + FillModel) over 6 months of cached 1h
bars, computes the graduation-gate metrics (G1..G7), and emits a graduation
report via tools/graduation/gate.py.

Why NT instead of tools/backtest/c3_replay.py: the replay applies a symmetric
slippage to a bar-close fill and charges ZERO fees, so it cannot distinguish
"C3 survives taker fees" from "C3 dies to fills." NT charges real maker/taker
fees and models limit-fill probability — the actual live-viability question.

C3's strategy logic is REUSED VERBATIM from trading/altcoin_reversion.py (the
same pure functions tools/backtest/c3_replay.py imports). Only the driver and
the cost model change. Run:

    python3 tools/nautilus/run_c3_oos.py          # full pipeline + gate

NT is a dev-only dependency (pinned in requirements-dev.txt); the box never
imports it.
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
    TimeInForce,
)
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Money, Price, Quantity, Currency
from nautilus_trader.model.data import BarType
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from trading import altcoin_reversion as c3
from tools.graduation.gate import evaluate_gate, emit_report

VENUE = Venue("BINANCE")
UNIVERSE = ["SOL", "LINK", "AVAX", "DOT"]
BTCSYM = "BTC"
HIST = ROOT / "data" / "historical"
START_CAPITAL = 100.0
# Binance VIP-0 spot fee, both maker and taker = 10 bps (0.001).
FEE = Decimal("0.001")
# 6mo window split: first ~120d in-sample, last ~60d out-of-sample.
OOS_CUTOFF = pd.Timestamp("2026-03-28", tz="UTC")


def make_ccy(code: str) -> Currency:
    try:
        return Currency.from_str(code)
    except Exception:
        return Currency(
            code, precision=8, iso4217=0, name=code, currency_type=CurrencyType.CRYPTO
        )


def make_pair(base_code: str) -> CurrencyPair:
    base = make_ccy(base_code)
    return CurrencyPair(
        instrument_id=InstrumentId(symbol=Symbol(f"{base_code}USDT"), venue=VENUE),
        raw_symbol=Symbol(f"{base_code}USDT"),
        base_currency=base,
        quote_currency=USDT,
        price_precision=4,
        size_precision=6,
        price_increment=Price(1e-4, precision=4),
        size_increment=Quantity(1e-6, precision=6),
        lot_size=None,
        max_quantity=Quantity(1e9, precision=6),
        min_quantity=Quantity(1e-6, precision=6),
        max_notional=None,
        min_notional=Money(1.0, USDT),
        max_price=Price(1e6, precision=4),
        min_price=Price(1e-4, precision=4),
        margin_init=Decimal(0),
        margin_maint=Decimal(0),
        maker_fee=FEE,
        taker_fee=FEE,
        ts_event=0,
        ts_init=0,
    )


def load_df(sym: str) -> pd.DataFrame:
    df = pd.read_parquet(HIST / f"{sym}_USDT_1h.parquet")
    df.columns = [c.lower() for c in df.columns]
    df.index = pd.to_datetime(df["ts"], utc=True)
    return df[["open", "high", "low", "close", "volume"]].astype(float)


class C3Strategy(Strategy):
    """Drives C3's pure entry/exit logic over NT bar events.

    BTC is the synchronization clock: alt bars for timestamp T are processed
    before the BTC bar for T (BTC bars get ts_init_delta=1), so when the BTC
    bar fires every alt buffer is current as of T — no look-ahead.

    maker=False: MARKET (taker) entries, fill immediately.
    maker=True:  LIMIT entries (fill probability governed by FillModel);
                 exits stay MARKET so positions always close.
    """

    def __init__(self, config, instruments, bar_types, maker: bool):
        super().__init__(config)
        self.instruments = instruments
        self.bar_types = bar_types
        self.maker = maker
        self.closes = {s: [] for s in UNIVERSE + [BTCSYM]}
        self.meta = {}  # sym -> entry meta (confirmed filled)
        self.pending = {}  # client_order_id -> entry context awaiting fill
        self.cooldown = {}  # sym -> bar_idx_until
        self.idx = 0
        self.n_entries = 0
        self.n_exits = 0

    def on_start(self):
        for s in UNIVERSE + [BTCSYM]:
            self.subscribe_bars(self.bar_types[s])

    def _sym_of(self, bar):
        return bar.bar_type.instrument_id.symbol.value[:-4]  # strip USDT

    def on_order_filled(self, event):
        # Confirm maker entry fills (market entries are recorded inline).
        coid = event.client_order_id
        ctx = self.pending.pop(coid, None)
        if ctx is None:
            return
        sym = ctx["sym"]
        self.meta[sym] = {
            "entry_idx": ctx["idx"],
            "max_z": ctx["z"],
            "entry_z": ctx["z"],
            "entry_price": float(event.last_px),
            "shares": float(event.last_qty),
        }

    def on_bar(self, bar):
        s = self._sym_of(bar)
        self.closes[s].append(float(bar.close))
        if s != BTCSYM:
            return
        self.idx += 1
        # Drop stale unfilled maker entry limits — each bar gets a fresh shot.
        if self.maker:
            for o in list(self.cache.orders_open(strategy_id=self.id)):
                if o.side == OrderSide.BUY:
                    self.cancel_order(o)
            self.pending.clear()

        btc_df = pd.DataFrame({"close": self.closes[BTCSYM]})
        if len(btc_df) < c3.LOOKBACK_BARS + 5:
            return

        # ---- EXIT phase (always MARKET so positions close) ----
        for sym in list(self.meta):
            alt_df = pd.DataFrame({"close": self.closes[sym]})
            z = c3._compute_z_score(alt_df, btc_df, lookback=c3.LOOKBACK_BARS)
            if z is None:
                continue
            m = self.meta[sym]
            if z > m["max_z"]:
                m["max_z"] = z
            age = self.idx - m["entry_idx"]
            reason = None
            if z >= c3.Z_TARGET:
                reason = "z_overshoot"
            elif (
                m["max_z"] >= c3.Z_TRAILING_MIN
                and (m["max_z"] - z) >= c3.Z_TRAILING_DROP
            ):
                reason = "z_trailing"
            elif z <= c3.Z_HARD_STOP:
                reason = "z_hard_stop"
            elif age >= c3.TIME_STOP_HOURS:
                reason = f"time_stop_{c3.TIME_STOP_HOURS}h"
            if reason:
                inst = self.instruments[sym]
                self.submit_order(
                    self.order_factory.market(
                        inst.id, OrderSide.SELL, inst.make_qty(m["shares"])
                    )
                )
                self.n_exits += 1
                mark = float(alt_df["close"].iloc[-1])
                if (
                    reason in ("z_hard_stop", f"time_stop_{c3.TIME_STOP_HOURS}h")
                    and m["shares"] * (mark - m["entry_price"]) < 0
                ):
                    self.cooldown[sym] = self.idx + c3.COOLDOWN_HOURS
                del self.meta[sym]

        # ---- ENTRY phase ----
        if c3._rsi(btc_df["close"], period=14) < c3.BTC_RSI_MIN:
            return
        acct = self.portfolio.account(VENUE)
        cash = float(acct.balance_total(USDT)) if acct else START_CAPITAL
        for sym in UNIVERSE:
            if sym in self.meta or f"{sym}/USDT" in c3.DENYLIST_SYMBOLS:
                continue
            if sym in self.cooldown and self.cooldown[sym] > self.idx:
                continue
            if len(self.meta) + len(self.pending) >= c3.MAX_CONCURRENT:
                break
            alt_df = pd.DataFrame({"close": self.closes[sym]})
            if len(alt_df) < c3.LOOKBACK_BARS + 5:
                continue
            z = c3._compute_z_score(alt_df, btc_df, lookback=c3.LOOKBACK_BARS)
            if z is None or z >= c3.Z_ENTRY:
                continue
            size_usd, why = c3._compute_trade_size(
                cash, len(self.meta), c3._realized_daily_vol(alt_df)
            )
            if size_usd <= 0:
                continue
            price = float(alt_df["close"].iloc[-1])
            inst = self.instruments[sym]
            qty = inst.make_qty(size_usd / price)
            if float(qty) <= 0:
                continue
            if self.maker:
                order = self.order_factory.limit(
                    inst.id,
                    OrderSide.BUY,
                    qty,
                    inst.make_price(price),
                    time_in_force=TimeInForce.GTC,
                )
                self.submit_order(order)
                self.pending[order.client_order_id] = {
                    "sym": sym,
                    "z": z,
                    "idx": self.idx,
                }
            else:
                self.submit_order(
                    self.order_factory.market(inst.id, OrderSide.BUY, qty)
                )
                self.meta[sym] = {
                    "entry_idx": self.idx,
                    "max_z": z,
                    "entry_z": z,
                    "entry_price": price,
                    "shares": float(qty),
                }
            self.n_entries += 1


def _metrics_from_positions(positions_df, start_capital=START_CAPITAL):
    """Compute gate metrics from NT positions report (DataFrame).

    NB: engine.cache.positions_closed() collapses to one per instrument under
    NETTING — useless. engine.trader.generate_positions_report() returns the
    actual per-round-trip rows (open→close), which is what we want.
    """

    def _num(x):
        if x is None:
            return 0.0
        if isinstance(x, str):
            return float(x.split()[0])
        return float(x)

    rows = []
    for _, p in positions_df.iterrows():
        pnl = _num(p["realized_pnl"])
        notional = abs(_num(p["avg_px_open"]) * _num(p["peak_qty"])) or 1.0
        ts = p["ts_closed"]
        ts_ns = int(ts.value) if hasattr(ts, "value") else int(ts)
        rows.append({"pnl": pnl, "ret": pnl / notional, "ts": ts_ns})
    rows.sort(key=lambda r: r["ts"])
    if not rows:
        return {
            "net_pnl_usd": 0.0,
            "n_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "sharpe": 0.0,
            "max_drawdown_pct": 0.0,
        }
    pnls = np.array([r["pnl"] for r in rows])
    rets = np.array([r["ret"] for r in rows])
    gains = pnls[pnls > 0].sum()
    losses = -pnls[pnls < 0].sum()
    # per-trade Sharpe annualized at ~60 trades/yr (matches c3_replay convention)
    sharpe = (
        float(rets.mean() / rets.std(ddof=1) * np.sqrt(60.0))
        if len(rets) >= 2 and rets.std(ddof=1) > 1e-9
        else 0.0
    )
    # drawdown on the cumulative-PnL equity curve
    equity = start_capital + np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    max_dd = float(np.max((peak - equity) / peak)) if len(equity) else 0.0
    return {
        "net_pnl_usd": round(float(pnls.sum()), 4),
        "n_trades": int(len(rows)),
        "win_rate": round(float((pnls > 0).mean()), 4),
        "profit_factor": round(float(gains / losses), 4)
        if losses > 0
        else float("inf"),
        "sharpe": round(sharpe, 4),
        "max_drawdown_pct": round(max_dd, 4),
        "_rows": rows,
    }


def run_backtest(maker: bool):
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="C3-NT-001", logging=LoggingConfig(bypass_logging=True)
        )
    )
    prob = 0.5 if maker else 1.0
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=None,
        starting_balances=[Money(START_CAPITAL, USDT)],
        fee_model=MakerTakerFeeModel(),
        fill_model=FillModel(prob_fill_on_limit=prob, prob_slippage=0.0, random_seed=7),
    )
    instruments, bar_types = {}, {}
    for sym in UNIVERSE + [BTCSYM]:
        inst = make_pair(sym)
        engine.add_instrument(inst)
        bt = BarType.from_str(f"{inst.id}-1-HOUR-LAST-EXTERNAL")
        instruments[sym], bar_types[sym] = inst, bt
        bars = BarDataWrangler(bt, inst).process(
            load_df(sym), ts_init_delta=(1 if sym == BTCSYM else 0)
        )
        engine.add_data(bars)
    engine.add_strategy(C3Strategy(StrategyConfig(), instruments, bar_types, maker))
    engine.run()
    positions_df = engine.trader.generate_positions_report()
    engine.dispose()
    return positions_df


def _sharpe_pnl_for_window(rows, oos: bool):
    cut = int(OOS_CUTOFF.value)  # ns
    sub = [r for r in rows if (r["ts"] >= cut) == oos]
    if len(sub) < 2:
        return 0.0, sum(r["pnl"] for r in sub)
    rets = np.array([r["ret"] for r in sub])
    sh = (
        float(rets.mean() / rets.std(ddof=1) * np.sqrt(60.0))
        if rets.std(ddof=1) > 1e-9
        else 0.0
    )
    return round(sh, 4), round(float(sum(r["pnl"] for r in sub)), 4)


def main():
    print(">>> Run A: MARKET / taker (10bps), 6mo, prob_fill_on_limit=1.0")
    taker = run_backtest(maker=False)
    mt = _metrics_from_positions(taker)
    is_sharpe, is_pnl = _sharpe_pnl_for_window(mt["_rows"], oos=False)
    oos_sharpe, oos_pnl = _sharpe_pnl_for_window(mt["_rows"], oos=True)

    print(">>> Run B: LIMIT / maker, prob_fill_on_limit=0.5 (G7 robustness)")
    maker = run_backtest(maker=True)
    mm = _metrics_from_positions(maker)

    metrics = {
        "net_pnl_usd": mt["net_pnl_usd"],
        "sharpe": oos_sharpe,  # gate evaluates OOS Sharpe
        "max_drawdown_pct": mt["max_drawdown_pct"],
        "n_trades": mt["n_trades"],
        "profit_factor": mt["profit_factor"],
        "in_sample_sharpe": is_sharpe,
        "oos_sharpe": oos_sharpe,
        "pnl_at_maker_0_5": mm["net_pnl_usd"],
        # context (not gate inputs)
        "_full_sharpe": mt["sharpe"],
        "_win_rate": mt["win_rate"],
        "_is_pnl_usd": is_pnl,
        "_oos_pnl_usd": oos_pnl,
        "_fee_model": "Binance VIP-0 maker=taker=10bps (MakerTakerFeeModel)",
        "_window": "2025-11-28 to 2026-05-27 (6mo, 1h bars); OOS = last ~60d",
    }
    result = evaluate_gate(metrics)
    path = emit_report(
        "C3_altcoin_reversion",
        metrics,
        result,
        out_dir=str(ROOT / "data" / "graduation"),
    )

    print("\n================ C3 GRADUATION VERDICT ================")
    print(
        json.dumps(
            {k: v for k, v in metrics.items() if not k.startswith("_")}, indent=2
        )
    )
    print(f"\nVERDICT: {'PASS' if result.passed else 'FAIL'}")
    for g in sorted(result.criteria):
        c = result.criteria[g]
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {g}: {c['detail']}")
    print(f"\nreport: {path}")


if __name__ == "__main__":
    main()
