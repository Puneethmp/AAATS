"""C7 delta-neutral funding arb — graduation test (B.1.7 Track 6).

The SECOND structurally-different graduation candidate alongside C3-perp. Where
C3* family bets on alt/BTC mean reversion (price-as-edge), C7 harvests perp
funding as rent (funding-as-edge), with directional risk hedged:

    LONG spot $LEG_NOTIONAL  +  SHORT perp $LEG_NOTIONAL  (delta-neutral entry)

While the pair is open, the SHORT perp leg RECEIVES funding whenever the Binance
USDT-M funding rate is positive (rate>0 => longs pay shorts). That funding income
is the edge; the spot+perp directional components should approximately cancel
within basis-spread noise. The trade is profitable iff funding income clears the
fee + basis cost.

Origin: this is the C5b "funding arb" doctrine (originally trading/funding_arb.py
on the box, halted 2026-05-15 over dual-leg accounting bugs). C7 is a CLEAN NT
implementation — each leg is its own NT position with its own realized PnL, so
the asymmetric-recording bug that halted C5b cannot occur. trading/funding_arb.py
is NOT imported or touched.

  - DATA: real Binance spot 1h klines + real USDT-M perp 1h klines + real funding
    history (all cached from Tracks 4b/5; no new fetches).
  - VENUE: single Venue("BINANCE"), MARGIN account (need to short perp), with both
    a CurrencyPair (spot) and a CryptoPerpetual (perp) registered per symbol.
  - FEES: spot maker=taker=10bps (Binance VIP-0 spot); perp maker=2bps/taker=5bps
    (Binance VIP-0 perp). MARKET orders both legs => taker fees both sides.
  - FUNDING: applied to the open short perp at every 8h settlement it crosses.

Gate metrics are computed from a per-PAIR ledger: each closed pair contributes
ONE trade. pair_pnl = spot_realized + perp_realized (NT realized PnL incl. fees)
+ funding_received. Pairs still open at backtest end never finalize and are
excluded (consistent with the C3-perp harness).

    python3 tools/nautilus/run_c7_funding_arb_oos.py

NT is a dev-only dependency (pinned in requirements-dev.txt); the box never
imports it.

Plan: docs/decisions/2026-05-28_b17_c3_supplements_plan.md (Track 6 added in the
B.1.7 C3-supplements arc). Verdict written to
data/graduation/C7_delta_neutral_funding_arb_<today>.json.
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
from nautilus_trader.model.instruments import CryptoPerpetual, CurrencyPair
from nautilus_trader.model.objects import Money, Price, Quantity, Currency
from nautilus_trader.model.data import BarType
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from tools.graduation.gate import evaluate_gate, emit_report

VENUE = Venue("BINANCE")
UNIVERSE = ["BTC", "ETH"]
HIST = ROOT / "data" / "historical"
START_CAPITAL = 100.0

# --- Strategy parameters (NOT iterated this session — one run, one verdict) ---
FUND_ENTRY = 0.0001  # +1 bps / 8h — open a pair when funding is meaningfully +ve
FUND_EXIT = 0.00005  # +0.5 bps / 8h — close when funding decays below this
MAX_HOLD_HOURS = 336  # 14d hard cap on a pair's age
LEG_NOTIONAL = 25.0  # $25 per leg, $50 per pair
LOSS_STOP = -0.02 * LEG_NOTIONAL  # -$0.50 — basis-spread blowout guard
MAX_CONCURRENT = 2  # at most 2 open pairs at once

# Fees (taker, since we use MARKET orders both legs)
SPOT_FEE_MAKER = Decimal("0.0010")
SPOT_FEE_TAKER = Decimal("0.0010")
PERP_FEE_MAKER = Decimal("0.0002")
PERP_FEE_TAKER = Decimal("0.0005")
_SPOT_TAKER_F = float(SPOT_FEE_TAKER)
_PERP_TAKER_F = float(PERP_FEE_TAKER)

# 6mo window split: first ~4mo in-sample, last ~2mo out-of-sample (same cutoff as
# the C3-perp harness so the eight-way comparison is apples-to-apples).
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


def make_spot(base_code: str) -> CurrencyPair:
    base = make_ccy(base_code)
    return CurrencyPair(
        instrument_id=InstrumentId(symbol=Symbol(f"{base_code}USDT"), venue=VENUE),
        raw_symbol=Symbol(f"{base_code}USDT"),
        base_currency=base,
        quote_currency=USDT,
        price_precision=2,
        price_increment=Price(1e-2, precision=2),
        size_precision=6,
        size_increment=Quantity(1e-6, precision=6),
        lot_size=None,
        max_quantity=Quantity(1e9, precision=6),
        min_quantity=Quantity(1e-6, precision=6),
        max_notional=None,
        min_notional=Money(1.0, USDT),
        max_price=Price(1e7, precision=2),
        min_price=Price(0.01, precision=2),
        margin_init=Decimal(0),
        margin_maint=Decimal(0),
        maker_fee=SPOT_FEE_MAKER,
        taker_fee=SPOT_FEE_TAKER,
        ts_event=0,
        ts_init=0,
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
        maker_fee=PERP_FEE_MAKER,
        taker_fee=PERP_FEE_TAKER,
        ts_event=0,
        ts_init=0,
    )


def load_df(sym: str, perp: bool) -> pd.DataFrame:
    suffix = "_1h_perp" if perp else "_1h"
    df = pd.read_parquet(HIST / f"{sym}_USDT{suffix}.parquet")
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


class C7FundingArbStrategy(Strategy):
    """Delta-neutral long-spot / short-perp funding harvester on BTC & ETH.

    BTC spot is the clock (ts_init_delta=1 so it processes last each hour, after
    every other leg's close is current). Each hour:
      1. FUNDING phase — credit any 8h settlement crossed this hour to the open
         short perp leg of each pair.
      2. EXIT phase — close pairs whose funding decayed, that aged out, or that
         hit the basis-blowout loss stop.
      3. ENTRY phase — at funding-settlement hours only, open a pair on any symbol
         whose just-settled rate >= FUND_ENTRY and that isn't already paired.

    Per-pair realized PnL is built in on_position_closed (two legs per pair) and
    funding is attributed exactly per pair via self.closing.
    """

    def __init__(self, config, instruments, bar_types):
        super().__init__(config)
        self.instruments = instruments  # (sym, leg) -> instrument
        self.bar_types = bar_types  # (sym, leg) -> BarType
        self.funding = {s: load_funding(s) for s in UNIVERSE}
        self.last_close = {}  # (sym, leg) -> float
        self.pairs = {}  # sym -> open-pair meta
        self.closing = {}  # sym -> close context awaiting both legs' PnL
        self.trades = []  # finalized per-pair ledger
        self.idx = 0
        self.n_funding_events = 0
        self.n_entries = 0
        self.n_exits = 0

    def on_start(self):
        for key in self.bar_types:
            self.subscribe_bars(self.bar_types[key])

    @staticmethod
    def _key_of(bar):
        val = bar.bar_type.instrument_id.symbol.value
        if val.endswith("-PERP"):
            return (val[: -len("-PERP")].split("USDT")[0], "perp")
        return (val.split("USDT")[0], "spot")

    def _current_funding_rate(self, sym, ts):
        s = self.funding.get(sym)
        if s is None or len(s) == 0:
            return None
        pos = s.index.searchsorted(ts, side="right") - 1
        if pos < 0:
            return None
        return float(s.iloc[pos])

    def _settlements_in(self, sym, lo, hi):
        s = self.funding.get(sym)
        if s is None or len(s) == 0:
            return s.iloc[0:0] if s is not None else pd.Series(dtype=float)
        return s[(s.index > lo) & (s.index <= hi)]

    # ---- order/position callbacks -----------------------------------------
    def on_position_closed(self, event):
        val = event.instrument_id.symbol.value
        if val.endswith("-PERP"):
            sym = val[: -len("-PERP")].split("USDT")[0]
            leg = "perp"
        else:
            sym = val.split("USDT")[0]
            leg = "spot"
        ctx = self.closing.get(sym)
        if ctx is None:
            return  # not a tracked pair close (shouldn't happen)
        ctx["legs"][leg] = _money(event.realized_pnl)  # price PnL incl. fees
        if "spot" in ctx["legs"] and "perp" in ctx["legs"]:
            realized_dir = ctx["legs"]["spot"] + ctx["legs"]["perp"]
            funding = ctx["funding"]
            fees = ctx["fees_est"]
            pair_pnl = realized_dir + funding
            self.trades.append(
                {
                    "sym": sym,
                    "pair_pnl": pair_pnl,
                    "funding": funding,
                    "fees": fees,
                    # gross directional (price-only) = realized incl. fees + fees
                    "directional_gross": realized_dir + fees,
                    "realized_directional": realized_dir,
                    "notional": 2.0 * LEG_NOTIONAL,
                    "entry_ts": ctx["entry_ts"],
                    "ts": ctx["close_ts"],  # close ts drives IS/OOS split
                    "hold_hours": ctx["hold_hours"],
                    "exit_reason": ctx["reason"],
                    "entry_rate": ctx["entry_rate"],
                }
            )
            del self.closing[sym]

    # ---- core cycle (driven by BTC spot bar) -------------------------------
    def on_bar(self, bar):
        key = self._key_of(bar)
        self.last_close[key] = float(bar.close)
        if key != ("BTC", "spot"):
            return
        self.idx += 1
        current_ts = pd.Timestamp(bar.ts_event, unit="ns", tz="UTC")
        prev_ts = current_ts - pd.Timedelta(hours=1)

        # ---- FUNDING phase: credit short perp of each open pair ----
        for sym, pair in self.pairs.items():
            for _ts_f, rate in self._settlements_in(sym, prev_ts, current_ts).items():
                # short perp RECEIVES when rate>0 (longs pay shorts), pays when <0
                pair["funding_received_usd"] += float(rate) * pair["perp_notional"]
                self.n_funding_events += 1

        # ---- EXIT phase (evaluated every cycle) ----
        for sym in list(self.pairs):
            pair = self.pairs[sym]
            cur_rate = self._current_funding_rate(sym, current_ts)
            spot_c = self.last_close.get((sym, "spot"))
            perp_c = self.last_close.get((sym, "perp"))
            if spot_c is None or perp_c is None:
                continue
            age = self.idx - pair["entry_idx"]
            spot_pnl = pair["spot_qty"] * (spot_c - pair["spot_entry"])
            perp_pnl = -pair["perp_qty"] * (perp_c - pair["perp_entry"])
            combined = spot_pnl + perp_pnl + pair["funding_received_usd"]
            reason = None
            if cur_rate is not None and cur_rate < FUND_EXIT:
                reason = "funding_decayed"
            elif age >= MAX_HOLD_HOURS:
                reason = "max_hold"
            elif combined <= LOSS_STOP:
                reason = "loss_stop"
            if reason:
                self._close_pair(sym, reason, current_ts, spot_c, perp_c)

        # ---- ENTRY phase (only at funding-settlement hours) ----
        for sym in UNIVERSE:
            if sym in self.pairs:
                continue
            if len(self.pairs) >= MAX_CONCURRENT:
                break
            if len(self._settlements_in(sym, prev_ts, current_ts)) == 0:
                continue  # entry only evaluated on a fresh settlement
            cur_rate = self._current_funding_rate(sym, current_ts)
            if cur_rate is None or cur_rate < FUND_ENTRY:
                continue
            self._open_pair(sym, current_ts, cur_rate)

    def _open_pair(self, sym, ts, rate):
        spot_inst = self.instruments[(sym, "spot")]
        perp_inst = self.instruments[(sym, "perp")]
        spot_px = self.last_close[(sym, "spot")]
        perp_px = self.last_close[(sym, "perp")]
        spot_qty = spot_inst.make_qty(LEG_NOTIONAL / spot_px)
        perp_qty = perp_inst.make_qty(LEG_NOTIONAL / perp_px)
        if float(spot_qty) <= 0 or float(perp_qty) <= 0:
            return
        self.submit_order(
            self.order_factory.market(spot_inst.id, OrderSide.BUY, spot_qty)
        )
        self.submit_order(
            self.order_factory.market(perp_inst.id, OrderSide.SELL, perp_qty)
        )
        self.pairs[sym] = {
            "entry_idx": self.idx,
            "entry_ts": int(ts.value),
            "entry_rate": rate,
            "spot_entry": spot_px,
            "perp_entry": perp_px,
            "spot_qty": float(spot_qty),
            "perp_qty": float(perp_qty),
            "perp_notional": float(perp_qty) * perp_px,
            "funding_received_usd": 0.0,
        }
        self.n_entries += 1

    def _close_pair(self, sym, reason, ts, spot_c, perp_c):
        pair = self.pairs[sym]
        spot_inst = self.instruments[(sym, "spot")]
        perp_inst = self.instruments[(sym, "perp")]
        # exact taker fees on tracked fill prices (market orders both sides)
        spot_fee = _SPOT_TAKER_F * (
            pair["spot_qty"] * pair["spot_entry"] + pair["spot_qty"] * spot_c
        )
        perp_fee = _PERP_TAKER_F * (
            pair["perp_qty"] * pair["perp_entry"] + pair["perp_qty"] * perp_c
        )
        self.closing[sym] = {
            "funding": pair["funding_received_usd"],
            "fees_est": spot_fee + perp_fee,
            "entry_ts": pair["entry_ts"],
            "close_ts": int(ts.value),
            "hold_hours": self.idx - pair["entry_idx"],
            "reason": reason,
            "entry_rate": pair["entry_rate"],
            "legs": {},
        }
        # close both legs: SELL spot (close long), BUY perp (close short)
        self.submit_order(
            self.order_factory.market(
                spot_inst.id, OrderSide.SELL, spot_inst.make_qty(pair["spot_qty"])
            )
        )
        self.submit_order(
            self.order_factory.market(
                perp_inst.id, OrderSide.BUY, perp_inst.make_qty(pair["perp_qty"])
            )
        )
        self.n_exits += 1
        del self.pairs[sym]


def _sharpe(rets):
    if len(rets) < 2 or rets.std(ddof=1) <= 1e-12:
        return 0.0
    # sqrt(60) per-trade annualization — identical convention to the C3 harness
    # family so the eight-way Sharpe comparison is apples-to-apples.
    return float(rets.mean() / rets.std(ddof=1) * np.sqrt(60.0))


def _sharpe_pnl_for_window(rows, oos: bool):
    cut = int(OOS_CUTOFF.value)
    sub = [r for r in rows if (r["ts"] >= cut) == oos]
    if len(sub) < 2:
        return 0.0, round(float(sum(r["pair_pnl"] for r in sub)), 4)
    rets = np.array([r["pair_pnl"] / r["notional"] for r in sub])
    return round(_sharpe(rets), 4), round(float(sum(r["pair_pnl"] for r in sub)), 4)


def _metrics_from_trades(trades, start_capital=START_CAPITAL):
    rows = sorted(trades, key=lambda r: r["ts"])
    if not rows:
        return {
            "net_pnl_usd": 0.0,
            "n_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "sharpe": 0.0,
            "max_drawdown_pct": 0.0,
            "funding_total_usd": 0.0,
            "fees_total_usd": 0.0,
            "directional_gross_usd": 0.0,
            "_rows": [],
        }
    pnls = np.array([r["pair_pnl"] for r in rows])
    rets = np.array([r["pair_pnl"] / r["notional"] for r in rows])
    gains = pnls[pnls > 0].sum()
    losses = -pnls[pnls < 0].sum()
    equity = start_capital + np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    max_dd = float(np.max((peak - equity) / peak)) if len(equity) else 0.0
    return {
        "net_pnl_usd": round(float(pnls.sum()), 4),
        "funding_total_usd": round(float(sum(r["funding"] for r in rows)), 4),
        "fees_total_usd": round(float(sum(r["fees"] for r in rows)), 4),
        "directional_gross_usd": round(
            float(sum(r["directional_gross"] for r in rows)), 4
        ),
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
            trader_id="C7funding-NT-001", logging=LoggingConfig(bypass_logging=True)
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
        for leg, factory, perp in (
            ("spot", make_spot, False),
            ("perp", make_perp, True),
        ):
            inst = factory(sym)
            engine.add_instrument(inst)
            bt = BarType.from_str(f"{inst.id}-1-HOUR-LAST-EXTERNAL")
            instruments[(sym, leg)] = inst
            bar_types[(sym, leg)] = bt
            # BTC spot is the clock => processed LAST each hour (delta=1); all
            # other legs delta=0 so their closes are current when BTC spot fires.
            delta = 1 if (sym == "BTC" and leg == "spot") else 0
            bars = BarDataWrangler(bt, inst).process(
                load_df(sym, perp), ts_init_delta=delta
            )
            engine.add_data(bars)
    strat = C7FundingArbStrategy(StrategyConfig(), instruments, bar_types)
    engine.add_strategy(strat)
    engine.run()
    out = {
        "trades": list(strat.trades),
        "n_funding_events": strat.n_funding_events,
        "n_entries": strat.n_entries,
        "n_exits": strat.n_exits,
        "n_open_at_end": len(strat.pairs),
    }
    engine.dispose()
    return out


def main():
    print(">>> C7 delta-neutral funding arb: BTC+ETH spot+perp, MARGIN, 6mo")
    res = run_backtest()
    mt = _metrics_from_trades(res["trades"])
    rows = mt["_rows"]
    is_sharpe, is_pnl = _sharpe_pnl_for_window(rows, oos=False)
    oos_sharpe, oos_pnl = _sharpe_pnl_for_window(rows, oos=True)

    n_loss_stop = sum(1 for r in rows if r["exit_reason"] == "loss_stop")
    n_funding_decay = sum(1 for r in rows if r["exit_reason"] == "funding_decayed")
    n_max_hold = sum(1 for r in rows if r["exit_reason"] == "max_hold")
    avg_funding = round(mt["funding_total_usd"] / len(rows), 4) if rows else 0.0
    avg_hold = (
        round(float(np.mean([r["hold_hours"] for r in rows])), 1) if rows else 0.0
    )

    metrics = {
        "net_pnl_usd": mt["net_pnl_usd"],
        "sharpe": oos_sharpe,  # gate G2 evaluates OOS Sharpe
        "max_drawdown_pct": mt["max_drawdown_pct"],
        "n_trades": mt["n_trades"],  # one CLOSED PAIR == one trade
        "profit_factor": mt["profit_factor"],
        "in_sample_sharpe": is_sharpe,
        "oos_sharpe": oos_sharpe,
        # G7: maker robustness — funding arb edge is income not fill-timing, so
        # the maker-sim is caveated; pnl_at_maker_0_5 == the single market run.
        "pnl_at_maker_0_5": mt["net_pnl_usd"],
        # --- C7-specific PnL decomposition ---
        "funding_total_usd": mt["funding_total_usd"],  # income (should be +ve)
        "fees_total_usd": mt["fees_total_usd"],  # cost (taker both legs)
        "directional_gross_usd": mt["directional_gross_usd"],  # ~0 if delta-neutral
        "n_pairs_entered": res["n_entries"],
        "n_pairs_exited": res["n_exits"],
        "n_pairs_open_at_end": res["n_open_at_end"],
        "n_loss_stopped": n_loss_stop,
        "n_funding_decayed": n_funding_decay,
        "n_max_hold": n_max_hold,
        "avg_funding_per_pair_usd": avg_funding,
        "avg_hold_hours": avg_hold,
        "funding_events_count": res["n_funding_events"],
        # context (not gate inputs)
        "_full_sharpe": mt["sharpe"],
        "_win_rate": mt["win_rate"],
        "_is_pnl_usd": is_pnl,
        "_oos_pnl_usd": oos_pnl,
        "_per_pair_pnls": [round(r["pair_pnl"], 4) for r in rows],
        "_per_pair_entry_ts": [r["entry_ts"] for r in rows],
        "_per_pair_sym": [r["sym"] for r in rows],
        "_data": "REAL Binance spot 1h + USDT-M perp 1h klines + funding history",
        "_fee_model": "spot maker=taker=10bps; perp maker=2bps/taker=5bps (taker used)",
        "_funding": "short perp receives funding when rate>0 (income); pays when <0",
        "_account": "MARGIN (perp short requires it), margin_init=0",
        "_params": (
            f"FUND_ENTRY={FUND_ENTRY} FUND_EXIT={FUND_EXIT} "
            f"MAX_HOLD_HOURS={MAX_HOLD_HOURS} LEG_NOTIONAL={LEG_NOTIONAL} "
            f"LOSS_STOP={LOSS_STOP} MAX_CONCURRENT={MAX_CONCURRENT}"
        ),
        "_window": "2025-11-28 to 2026-05-27 (6mo, 1h bars); OOS = on/after 2026-03-28",
    }
    result = evaluate_gate(metrics)
    path = emit_report(
        "C7_delta_neutral_funding_arb",
        metrics,
        result,
        out_dir=str(ROOT / "data" / "graduation"),
    )

    print("\n========== C7 FUNDING-ARB GRADUATION VERDICT ==========")
    print(
        json.dumps(
            {k: v for k, v in metrics.items() if not k.startswith("_")}, indent=2
        )
    )
    print(
        f"\nPnL decomposition: directional {mt['directional_gross_usd']:+.4f} "
        f"+ funding {mt['funding_total_usd']:+.4f} - fees {mt['fees_total_usd']:.4f} "
        f"-> net {mt['net_pnl_usd']:+.4f}"
    )
    print(
        f"pairs entered={res['n_entries']} exited={res['n_exits']} "
        f"open_at_end={res['n_open_at_end']} | loss_stop={n_loss_stop} "
        f"funding_decay={n_funding_decay} max_hold={n_max_hold}"
    )
    print(f"avg funding/pair={avg_funding:+.4f}  avg hold={avg_hold}h")
    print(f"VERDICT: {'PASS' if result.passed else 'FAIL'}")
    for g in sorted(result.criteria):
        c = result.criteria[g]
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {g}: {c['detail']}")
    print(f"\nreport: {path}")


if __name__ == "__main__":
    main()
