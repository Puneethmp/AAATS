"""C3-perp HONEST graduation test — proper perp klines + funding (B.1.7 T4b).

The Track 4 signal test (run_c3_perp_oos.py) showed C3's edge survives perp
FEES (PF 1.41, PASS) but deliberately ignored funding and used spot bars as a
price proxy. This harness is the honest version that determines whether
C3-perp actually graduates:

  - DATA: real Binance USDT-M perp 1h klines (data/historical/{SYM}_USDT_1h_perp
    .parquet), fetched by tools/backtest/fetch_perp_data.py. No spot proxy.
  - FEES: Binance perp VIP-0 (maker 2bps / taker 5bps), as Track 4.
  - FUNDING: real Binance funding-rate history applied to every open long at
    each 8h settlement it crosses. Binance USDT-M convention: funding_rate > 0
    => LONGS PAY shorts (a cost for C3, which is long-only); < 0 => longs
    RECEIVE. funding_cost = shares * entry_price * rate, accumulated per
    position and SUBTRACTED from realized PnL for the gate metrics.

Gate metrics are computed from the strategy's own per-trade ledger (built in
on_position_closed, which carries NT's realized_pnl incl. fees) minus the
tracked funding — NOT from generate_positions_report, so the funding deduction
is exact per round-trip. Positions open at backtest end never fire
on_position_closed and are excluded (consistent with the C3b harness).

C3 logic is REUSED VERBATIM from trading/altcoin_reversion.py (box module, kept
read-only). Only the venue economics (perp fees + funding) and the data change.

    python3 tools/nautilus/run_c3_perp_funded_oos.py

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
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Money, Price, Quantity, Currency
from nautilus_trader.model.data import BarType
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from trading import altcoin_reversion as c3
from tools.graduation.gate import evaluate_gate, emit_report
from tools.nautilus.regime_gate import (
    CORRELATION_THRESHOLD,
    DRIFT_THRESHOLD,
    compute_30d_correlation,
    compute_30d_divergence,
    compute_drift_trend,
    is_regime_ok,
    is_regime_ok_v2,
    is_regime_ok_v3,
)

VENUE = Venue("BINANCE")
UNIVERSE = ["SOL", "LINK", "AVAX", "DOT"]
BTCSYM = "BTC"
HIST = ROOT / "data" / "historical"
START_CAPITAL = 100.0
# Binance PERP VIP-0 fees: maker 2bps, taker 5bps (read off the instrument).
FEE_MAKER = Decimal("0.0002")
FEE_TAKER = Decimal("0.0005")
# 6mo window split: first ~120d in-sample, last ~60d out-of-sample.
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
        max_price=Price(1e6, precision=4),
        min_price=Price(1e-4, precision=4),
        margin_init=Decimal(0),
        margin_maint=Decimal(0),
        maker_fee=FEE_MAKER,
        taker_fee=FEE_TAKER,
        ts_event=0,
        ts_init=0,
    )


def load_perp_df(sym: str) -> pd.DataFrame:
    """Real perp 1h klines (NOT the spot proxy used in the signal test)."""
    df = pd.read_parquet(HIST / f"{sym}_USDT_1h_perp.parquet")
    df.columns = [c.lower() for c in df.columns]
    df.index = pd.to_datetime(df["ts"], utc=True)
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def load_funding(sym: str) -> pd.Series:
    f = HIST / f"{sym}_USDT_funding.parquet"
    if not f.exists():
        return pd.Series(dtype=float)
    df = pd.read_parquet(f)
    s = df.set_index(pd.to_datetime(df["ts_funding"], utc=True))["funding_rate"].astype(
        float
    )
    return s.sort_index()


class C3PerpFundedStrategy(Strategy):
    """C3 on perp instruments with real funding applied to open longs.

    BTC is the clock (ts_init_delta=1). Funding is applied each hour after the
    exit phase, before the entry phase, to all still-open longs that crossed an
    8h settlement in the last hour. Closed round-trips are recorded in
    self.trades via on_position_closed with funding subtracted.
    """

    def __init__(
        self, config, instruments, bar_types, maker: bool, gate_version: int = 0
    ):
        super().__init__(config)
        self.instruments = instruments
        self.bar_types = bar_types
        self.maker = maker
        self.gate_version = gate_version  # 0 off | 1 div | 2 +corr | 3 +drift
        self.closes = {s: [] for s in UNIVERSE + [BTCSYM]}
        self.funding = {s: load_funding(s) for s in UNIVERSE + [BTCSYM]}
        self.meta = {}  # sym -> open-position meta (incl funding_paid_usd)
        self.pending = {}  # client_order_id -> entry context awaiting fill
        self.cooldown = {}  # sym -> bar_idx_until
        self.funding_pending_close = {}  # sym -> funding_paid_usd stashed at SELL
        self.trades = []  # closed round-trip ledger (pnl_gross, funding, pnl_net)
        self.n_funding_events = 0
        self.idx = 0
        self.n_entries = 0
        self.n_exits = 0
        # allocator-level regime gate diagnostics (Tracks 9 + 10)
        self.n_gate_eval = 0  # cycles where the gate ran (divergence computable)
        self.n_gate_blocked = 0  # cycles where the gate blocked entries
        self.gate_blocked_months = {}  # "YYYY-MM" -> blocked count
        self.divergences = []  # all computable divergence values (for diagnosis)
        self.correlations = []  # all computable correlation values (v2)
        self.drifts = []  # all computable 60d drift values (v3)
        self.n_block_div_only = 0  # v2/v3: blocked by divergence signal alone
        self.n_block_corr_only = 0  # v2: blocked by correlation signal alone
        self.n_block_drift_only = 0  # v3: blocked by drift signal alone
        self.n_block_both = 0  # v2/v3: blocked by both signals together

    def on_start(self):
        for s in UNIVERSE + [BTCSYM]:
            self.subscribe_bars(self.bar_types[s])

    def _sym_of(self, bar):
        return bar.bar_type.instrument_id.symbol.value.split("USDT")[0]

    def on_order_filled(self, event):
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
            "funding_paid_usd": 0.0,
        }

    def on_position_closed(self, event):
        sym = event.instrument_id.symbol.value.split("USDT")[0]
        funding = self.funding_pending_close.pop(sym, 0.0)
        realized = _money(event.realized_pnl)  # price PnL incl. fees
        notional = abs(float(event.avg_px_open) * float(event.peak_qty)) or 1.0
        ts = event.ts_closed if event.ts_closed else event.ts_event
        self.trades.append(
            {
                "pnl_gross": realized,
                "funding": funding,
                "pnl_net": realized - funding,
                "notional": notional,
                "ts": int(ts),
            }
        )

    def on_bar(self, bar):
        s = self._sym_of(bar)
        self.closes[s].append(float(bar.close))
        if s != BTCSYM:
            return
        self.idx += 1
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
                # Stash accumulated funding for this position so on_position_closed
                # (fires after the SELL fills) can attribute it to the trade.
                self.funding_pending_close[sym] = m.get("funding_paid_usd", 0.0)
                del self.meta[sym]

        # ---- FUNDING phase (after exits, before entries) ----
        current_ts = pd.Timestamp(bar.ts_event, unit="ns", tz="UTC")
        prev_ts = current_ts - pd.Timedelta(hours=1)
        for sym, m in self.meta.items():
            s_funding = self.funding.get(sym)
            if s_funding is None or len(s_funding) == 0:
                continue
            events = s_funding[
                (s_funding.index > prev_ts) & (s_funding.index <= current_ts)
            ]
            for _ts_f, rate in events.items():
                # long perp pays funding when rate>0, receives when rate<0
                funding_cost = m["shares"] * m["entry_price"] * float(rate)
                m["funding_paid_usd"] = m.get("funding_paid_usd", 0.0) + funding_cost
                self.n_funding_events += 1

        # ---- REGIME GATE (allocator-level; gates NEW exposure, never exits) ----
        # gate_version: 0 off | 1 divergence (T9) | 2 +correlation (T10) | 3 +drift (T11)
        if self.gate_version > 0:
            divergence = compute_30d_divergence(
                self.closes[BTCSYM], {a: self.closes[a] for a in UNIVERSE}
            )
            if divergence is not None:
                self.n_gate_eval += 1
                self.divergences.append(divergence)
                correlation = None
                drift = None
                if self.gate_version == 2:
                    btc_rets = np.diff(np.log(self.closes[BTCSYM]))
                    alt_rets = {a: np.diff(np.log(self.closes[a])) for a in UNIVERSE}
                    correlation = compute_30d_correlation(btc_rets, alt_rets)
                    if correlation is not None:
                        self.correlations.append(correlation)
                elif self.gate_version == 3:
                    drift = compute_drift_trend(
                        self.closes[BTCSYM], {a: self.closes[a] for a in UNIVERSE}
                    )
                    if drift is not None:
                        self.drifts.append(drift)
                if self.gate_version == 1:
                    ok = is_regime_ok(divergence)
                elif self.gate_version == 2:
                    ok = is_regime_ok_v2(divergence, correlation)
                else:  # v3: divergence AND drift
                    ok = is_regime_ok_v3(divergence, drift)
                if not ok:
                    self.n_gate_blocked += 1
                    div_fail = not is_regime_ok(divergence)
                    if self.gate_version == 2:
                        corr_fail = (
                            correlation is not None
                            and correlation < CORRELATION_THRESHOLD
                        )
                        if div_fail and corr_fail:
                            self.n_block_both += 1
                        elif div_fail:
                            self.n_block_div_only += 1
                        else:
                            self.n_block_corr_only += 1
                    elif self.gate_version == 3:
                        drift_fail = drift is not None and abs(drift) >= DRIFT_THRESHOLD
                        if div_fail and drift_fail:
                            self.n_block_both += 1
                        elif div_fail:
                            self.n_block_div_only += 1
                        else:
                            self.n_block_drift_only += 1
                    month = pd.Timestamp(bar.ts_event, unit="ns", tz="UTC").strftime(
                        "%Y-%m"
                    )
                    self.gate_blocked_months[month] = (
                        self.gate_blocked_months.get(month, 0) + 1
                    )
                    return  # block all NEW entries this cycle; holds continue

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
                    "funding_paid_usd": 0.0,
                }
            self.n_entries += 1


def _metrics_from_trades(trades, start_capital=START_CAPITAL):
    """Gate metrics from the strategy's closed-trade ledger, funding-adjusted.

    pnl_net = NT realized_pnl (price PnL incl. fees) - funding_paid.
    """
    rows = sorted(trades, key=lambda r: r["ts"])
    if not rows:
        return {
            "net_pnl_usd": 0.0,
            "n_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "sharpe": 0.0,
            "max_drawdown_pct": 0.0,
            "_rows": [],
        }
    pnls = np.array([r["pnl_net"] for r in rows])
    rets = np.array(
        [r["pnl_net"] / r["notional"] if r["notional"] else 0.0 for r in rows]
    )
    gains = pnls[pnls > 0].sum()
    losses = -pnls[pnls < 0].sum()
    sharpe = (
        float(rets.mean() / rets.std(ddof=1) * np.sqrt(60.0))
        if len(rets) >= 2 and rets.std(ddof=1) > 1e-9
        else 0.0
    )
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
        "sharpe": round(sharpe, 4),
        "max_drawdown_pct": round(max_dd, 4),
        "_rows": rows,
    }


def _sharpe_pnl_for_window(rows, oos: bool):
    cut = int(OOS_CUTOFF.value)
    sub = [r for r in rows if (r["ts"] >= cut) == oos]
    if len(sub) < 2:
        return 0.0, sum(r["pnl_net"] for r in sub)
    rets = np.array(
        [r["pnl_net"] / r["notional"] if r["notional"] else 0.0 for r in sub]
    )
    sh = (
        float(rets.mean() / rets.std(ddof=1) * np.sqrt(60.0))
        if rets.std(ddof=1) > 1e-9
        else 0.0
    )
    return round(sh, 4), round(float(sum(r["pnl_net"] for r in sub)), 4)


def run_backtest(maker: bool, gate_version: int = 0):
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="C3perpFunded-NT-001", logging=LoggingConfig(bypass_logging=True)
        )
    )
    prob = 0.5 if maker else 1.0
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=None,
        starting_balances=[Money(START_CAPITAL, USDT)],
        fee_model=MakerTakerFeeModel(),
        fill_model=FillModel(prob_fill_on_limit=prob, prob_slippage=0.0, random_seed=7),
    )
    instruments, bar_types = {}, {}
    for sym in UNIVERSE + [BTCSYM]:
        inst = make_perp(sym)
        engine.add_instrument(inst)
        bt = BarType.from_str(f"{inst.id}-1-HOUR-LAST-EXTERNAL")
        instruments[sym], bar_types[sym] = inst, bt
        bars = BarDataWrangler(bt, inst).process(
            load_perp_df(sym), ts_init_delta=(1 if sym == BTCSYM else 0)
        )
        engine.add_data(bars)
    strat = C3PerpFundedStrategy(
        StrategyConfig(), instruments, bar_types, maker, gate_version
    )
    engine.add_strategy(strat)
    engine.run()
    out = {
        "trades": list(strat.trades),
        "n_funding_events": strat.n_funding_events,
        "n_gate_eval": strat.n_gate_eval,
        "n_gate_blocked": strat.n_gate_blocked,
        "gate_blocked_months": dict(strat.gate_blocked_months),
        "divergences": list(strat.divergences),
        "correlations": list(strat.correlations),
        "drifts": list(strat.drifts),
        "n_block_div_only": strat.n_block_div_only,
        "n_block_corr_only": strat.n_block_corr_only,
        "n_block_drift_only": strat.n_block_drift_only,
        "n_block_both": strat.n_block_both,
    }
    engine.dispose()
    return out


def evaluate(
    gate_version: int = 0,
    strategy_name: str = "C3_perp_funded",
    emit: bool = True,
    verbose: bool = True,
):
    """Run taker + maker backtests and build the gate metrics dict.

    gate_version: 0 off | 1 divergence-only (Track 9) | 2 divergence AND
    correlation (Track 10). Returns (metrics, result, taker_out, mt, path).
    Default (0) reproduces the ungated B.1.6 Track-4b graduation report; the
    Track-9/10 drivers call it with gate_version=1/2 and the gated report names.
    """
    if verbose:
        print(
            f">>> Run A: MARKET / taker (5bps perp) + FUNDING, 6mo, prob=1.0 "
            f"(gate_version={gate_version})"
        )
    taker = run_backtest(maker=False, gate_version=gate_version)
    mt = _metrics_from_trades(taker["trades"])
    is_sharpe, is_pnl = _sharpe_pnl_for_window(mt["_rows"], oos=False)
    oos_sharpe, oos_pnl = _sharpe_pnl_for_window(mt["_rows"], oos=True)

    if verbose:
        print(">>> Run B: LIMIT / maker (2bps perp) + FUNDING, prob=0.5 (G7)")
    maker = run_backtest(maker=True, gate_version=gate_version)
    mm = _metrics_from_trades(maker["trades"])

    total_notional = mt["total_notional_usd"] or 1.0
    funding_total = mt["funding_total_usd"]
    gate_eval = taker.get("n_gate_eval", 0)
    gate_blocked = taker.get("n_gate_blocked", 0)
    metrics = {
        "net_pnl_usd": mt["net_pnl_usd"],  # after funding
        "sharpe": oos_sharpe,  # gate evaluates OOS Sharpe (after funding)
        "max_drawdown_pct": mt["max_drawdown_pct"],
        "n_trades": mt["n_trades"],
        "profit_factor": mt["profit_factor"],
        "in_sample_sharpe": is_sharpe,
        "oos_sharpe": oos_sharpe,
        "pnl_at_maker_0_5": mm["net_pnl_usd"],
        # funding stats (required for the next session's diagnosis)
        "funding_total_usd_paid": funding_total,
        "funding_avg_bps_per_trade": round(funding_total / total_notional * 10000, 4),
        "funding_events_count": taker["n_funding_events"],
        # regime-gate diagnostics (Tracks 9 + 10)
        "gate_version": gate_version,
        "gate_active_pct": round(100.0 * gate_blocked / gate_eval, 2)
        if gate_eval
        else 0.0,
        "gate_blocked_bars": gate_blocked,
        "gate_eval_bars": gate_eval,
        "gate_block_div_only": taker.get("n_block_div_only", 0),
        "gate_block_corr_only": taker.get("n_block_corr_only", 0),
        "gate_block_drift_only": taker.get("n_block_drift_only", 0),
        "gate_block_both": taker.get("n_block_both", 0),
        "mean_correlation_30d": round(float(np.mean(taker["correlations"])), 4)
        if taker.get("correlations")
        else None,
        "mean_drift_60d": round(float(np.mean(taker["drifts"])), 4)
        if taker.get("drifts")
        else None,
        "drift_eval_bars": len(taker.get("drifts", [])),
        # context (not gate inputs)
        "_gross_pnl_usd_before_funding": mt["gross_pnl_usd"],
        "_full_sharpe": mt["sharpe"],
        "_win_rate": mt["win_rate"],
        "_is_pnl_usd": is_pnl,
        "_oos_pnl_usd": oos_pnl,
        "_total_notional_usd": mt["total_notional_usd"],
        "_gate_blocked_months": taker.get("gate_blocked_months", {}),
        "_data": "REAL Binance USDT-M perp 1h klines (fetch_perp_data.py)",
        "_fee_model": "Binance perp VIP-0 maker=2bps/taker=5bps (MakerTakerFeeModel)",
        "_funding": "real Binance funding-rate history; long pays when rate>0",
        "_account": "MARGIN, margin_init=0",
        "_regime_gate": "v1: 30d div>0.08 blocks; v2: AND 30d corr<0.5; v3: AND |60d log-RS drift|>=0.08",
        "_window": "2025-11-28 to 2026-05-27 (6mo, 1h bars); OOS = last ~60d",
    }
    result = evaluate_gate(metrics)
    path = (
        emit_report(
            strategy_name, metrics, result, out_dir=str(ROOT / "data" / "graduation")
        )
        if emit
        else None
    )
    return metrics, result, taker, mt, path


def main():
    metrics, result, taker, mt, path = evaluate()
    print("\n========== C3-PERP FUNDED GRADUATION VERDICT (honest) ==========")
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
        f"VERDICT: {'PASS' if result.passed else 'FAIL'}  (honest -- funding included)"
    )
    for g in sorted(result.criteria):
        c = result.criteria[g]
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {g}: {c['detail']}")
    print(f"\nreport: {path}")


if __name__ == "__main__":
    main()
