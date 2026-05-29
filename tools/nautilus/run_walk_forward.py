"""Track F walk-forward — FINAL ARBITER of the perp-edge program (2026-05-30).

Operator-APPROVED frozen spec. The 5-part criterion below is committed BEFORE the
results are seen; NO threshold is tuned to output, and the verdict is terminal:
all five met -> GO (real regime-robust edge); any one missed -> NO-GO, stop the
strategy hunt, escalate the doctrine fork.

Design (frozen):
  - Data: maximum contiguous 6-symbol perp klines+funding (data/historical/*_contig).
  - Rolling-origin: 4mo train / 2mo OOS, step 2mo, NON-OVERLAPPING OOS, >=10 folds.
    The strategies are NOT fitted (parameters are frozen — C3 gate_version=1, TSMOM
    L=336h/REBAL=24h), so "train" is warm-up/context only; each strategy is run ONCE
    continuously over the full contiguous history on a $100 book, and trades are
    bucketed into the tiled OOS windows by CLOSE timestamp. (C3 sizing compounds
    over 36mo — realistic; per-trade returns are sizing-invariant so the fold
    Sharpes/DD are robust, and net signs are preserved.)
  - Primary unit: static EQUAL-WEIGHT C3+TSMOM ensemble (50/50 sleeves, $100 book).
  - Diagnostic (reported, NOT gated): each factor alone; inverse-vol weighting;
    per-fold regime tags.

PRE-REGISTERED ROBUSTNESS CRITERION (frozen; robust iff ALL FIVE):
  (1) ensemble OOS net > 0 in >= 60% of folds;
  (2) median per-fold OOS Sharpe >= 0.5  (per-trade sqrt(60), the harness family
      convention — used for the small per-fold samples);
  (3) pooled-OOS Sharpe >= 1.0, on DAILY equity-curve returns concatenated across
      all OOS windows. "Annualized identically to G2" is not literally portable
      (G2 is a per-trade sqrt(60) proxy); per the explicit "daily returns, not a
      per-trade sqrt scaling", we use the standard 24/7-crypto daily annualization
      sqrt(365) at the frozen >=1.0 bar. Raw daily mean/std are reported so the
      verdict's robustness to the annualization choice is visible;
  (4) worst single-fold max drawdown <= 20%;
  (5) NULL CONTROL: the real ensemble pooled-OOS daily Sharpe exceeds the 95th
      percentile of a sign-shuffled control (each OOS trade's pnl sign flipped at
      random; 1000 shuffles; seed 7).

    .venv-nt/Scripts/python tools/nautilus/run_walk_forward.py
"""

# ruff: noqa: E402  — sys.path bootstrap (below) must precede repo-local imports
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

HIST = ROOT / "data" / "historical"

import tools.nautilus.run_c3_perp_funded_oos as c3
import tools.nautilus.run_perp_tsmom_oos as tsmom

GATE_V = 1  # C3 best gate (divergence)
SEED = 7
N_SHUFFLE = 1000
TRAIN_MO, OOS_MO, STEP_MO = 4, 2, 2
ANN_DAILY = np.sqrt(365.0)  # 24/7-crypto daily annualization (criteria 3 & 5)
ANN_TRADE = np.sqrt(60.0)  # per-trade, harness-family convention (criterion 2)
BOOK = 100.0
SLEEVE = 0.5  # equal-weight: 50% of the book to each strategy


# --- monkeypatch C3 loaders to read the contiguous parquet (no harness edit) ---
def _c3_load_perp_contig(sym):
    df = pd.read_parquet(HIST / f"{sym}_USDT_1h_perp_contig.parquet")
    df.columns = [c.lower() for c in df.columns]
    df.index = pd.to_datetime(df["ts"], utc=True)
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def _c3_load_funding_contig(sym):
    f = HIST / f"{sym}_USDT_funding_contig.parquet"
    if not f.exists():
        return pd.Series(dtype=float)
    df = pd.read_parquet(f)
    s = (
        df.set_index(pd.to_datetime(df["ts_funding"], utc=True))["funding_rate"]
        .astype(float)
        .sort_index()
    )
    return s.sort_index()


c3.load_perp_df = _c3_load_perp_contig
c3.load_funding = _c3_load_funding_contig


def _ledger(rows):
    return [
        {"pnl_net": r["pnl_net"], "notional": r["notional"], "ts": int(r["ts"])}
        for r in rows
    ]


def c3_ledger(maker):
    return _ledger(c3.run_backtest(maker=maker, gate_version=GATE_V)["trades"])


def tsmom_ledger(fee):
    trades, _ = tsmom._backtest("contig", fee)
    return _ledger(trades)


def _sharpe(returns, ann):
    r = np.asarray(returns, dtype=float)
    if len(r) < 2 or r.std(ddof=1) <= 1e-12:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * ann)


def _span():
    btc = pd.read_parquet(HIST / "BTC_USDT_1h_perp_contig.parquet")
    ts = pd.to_datetime(btc["ts"], utc=True)
    return ts.min(), ts.max()


def _folds(start, end):
    folds = []
    first_oos = start + pd.DateOffset(months=TRAIN_MO)
    lo = first_oos
    while lo + pd.DateOffset(months=OOS_MO) <= end:
        hi = lo + pd.DateOffset(months=OOS_MO)
        folds.append((lo, hi))
        lo = lo + pd.DateOffset(months=STEP_MO)
    return folds


def _in(trades, lo, hi):
    loi, hii = int(lo.value), int(hi.value)
    return [t for t in trades if loi <= t["ts"] < hii]


def _daily_returns(trades, lo, hi):
    """Ensemble realized daily-return series over [lo,hi): each trade's 0.5*pnl_net
    assigned to its close day; return = daily PnL / BOOK; all calendar days incl 0s."""
    days = pd.date_range(
        lo.floor("D"), (hi - pd.Timedelta(hours=1)).floor("D"), freq="D", tz="UTC"
    )
    pnl = pd.Series(0.0, index=days)
    for t in trades:
        d = pd.Timestamp(t["ts"], tz="UTC").floor("D")
        if d in pnl.index:
            pnl.loc[d] += SLEEVE * t["pnl_net"]
    return (pnl / BOOK).to_numpy()


def main():
    start, end = _span()
    span_mo = (end - start).days / 30.44
    print(f"contiguous span: {start.date()} -> {end.date()}  (~{span_mo:.1f} mo)")
    # per-symbol listing/coverage (survivorship/listing-bias check)
    print("per-symbol contiguous coverage (earliest bar = listing-or-floor):")
    for s in tsmom.UNIVERSE:
        k = pd.read_parquet(HIST / f"{s}_USDT_1h_perp_contig.parquet")
        kts = pd.to_datetime(k["ts"], utc=True)
        print(f"   {s:5} {kts.min().date()} -> {kts.max().date()}  ({len(k)} bars)")

    folds = _folds(start, end)
    print(f"\n{len(folds)} non-overlapping 2mo OOS folds (4mo train, step 2mo)")
    if len(folds) < 10:
        print(
            "WARNING: <10 folds — insufficient contiguous history for the frozen design."
        )

    print("\nrunning C3 (NT, taker) + TSMOM (taker) once over contiguous history...")
    # Taker is the gated case (market-order rules); maker is not part of the frozen
    # criterion, so only the taker ledgers are run.
    c3_t = c3_ledger(False)
    ts_t = tsmom_ledger(tsmom.FEE_TAKER)
    ens_t = c3_t + ts_t  # equal-weight taker ensemble trade pool

    # contiguous BTC closes for regime tagging (diagnostic only)
    btc = _c3_load_perp_contig("BTC")["close"]

    # ---- per-fold ensemble metrics (equal-weight, taker) ----
    print(
        f"\n{'fold':>4} | {'OOS window':<23} | {'ntr':>4} | {'net':>8} | {'fold Shrp':>9} | {'maxDD':>6} | regime"
    )
    print("-" * 92)
    fold_nets, fold_sharpes, fold_dds = [], [], []
    for i, (lo, hi) in enumerate(folds):
        tf = _in(ens_t, lo, hi)
        tf_sorted = sorted(tf, key=lambda x: x["ts"])
        net = SLEEVE * sum(t["pnl_net"] for t in tf)
        rets = [t["pnl_net"] / t["notional"] for t in tf]
        sh = _sharpe(rets, ANN_TRADE)
        if tf_sorted:
            eq = BOOK + np.cumsum([SLEEVE * t["pnl_net"] for t in tf_sorted])
            peak = np.maximum.accumulate(eq)
            dd = float(np.max((peak - eq) / peak))
        else:
            dd = 0.0
        fold_nets.append(net)
        fold_sharpes.append(sh)
        fold_dds.append(dd)
        # regime tag (diagnostic): BTC 60d return to fold start + 30d realized vol
        bt = btc[btc.index < lo]
        reg = "n/a"
        if len(bt) > 24 * 60:
            r60 = bt.iloc[-1] / bt.iloc[-24 * 60] - 1
            vol = float(
                np.std(np.diff(np.log(bt.iloc[-24 * 30 :].to_numpy())))
            ) * np.sqrt(24)
            reg = f"BTC60d {r60:+.0%} vol{vol:.2%}"
        print(
            f"{i:>4} | {lo.date()}->{hi.date()} | {len(tf):>4} | {net:>+8.2f} | {sh:>+9.2f} | {dd:>6.1%} | {reg}"
        )

    frac_pos = float(np.mean([n > 0 for n in fold_nets]))
    med_sharpe = float(np.median(fold_sharpes))
    worst_dd = float(np.max(fold_dds))

    # ---- pooled-OOS daily (criteria 3 & 5) ----
    pooled_lo, pooled_hi = folds[0][0], folds[-1][1]
    daily = _daily_returns(ens_t, pooled_lo, pooled_hi)
    pooled_sharpe = _sharpe(daily, ANN_DAILY)
    pooled_mean, pooled_std = float(daily.mean()), float(daily.std(ddof=1))

    # null control: sign-shuffle each OOS trade's pnl, rebuild pooled daily Sharpe
    oos_trades = _in(ens_t, pooled_lo, pooled_hi)
    rng = np.random.default_rng(SEED)
    base = np.array([t["pnl_net"] for t in oos_trades])
    tdays = pd.DatetimeIndex(
        [pd.Timestamp(t["ts"], tz="UTC").floor("D") for t in oos_trades]
    )
    day_index = pd.date_range(
        pooled_lo.floor("D"),
        (pooled_hi - pd.Timedelta(hours=1)).floor("D"),
        freq="D",
        tz="UTC",
    )
    day_pos = {d: k for k, d in enumerate(day_index)}
    idx = np.array([day_pos[d] for d in tdays])
    null = np.empty(N_SHUFFLE)
    for j in range(N_SHUFFLE):
        signs = rng.choice([-1.0, 1.0], size=len(base))
        dp = np.zeros(len(day_index))
        np.add.at(dp, idx, SLEEVE * base * signs)
        null[j] = _sharpe(dp / BOOK, ANN_DAILY)
    null_p95 = float(np.percentile(null, 95))

    # ---- diagnostics (NOT gated) ----
    def pooled_daily_sharpe(trades):
        return _sharpe(_daily_returns(trades, pooled_lo, pooled_hi), ANN_DAILY)

    c3_only_sh = pooled_daily_sharpe(c3_t)
    ts_only_sh = pooled_daily_sharpe(ts_t)
    c3_oos = _in(c3_t, pooled_lo, pooled_hi)
    ts_oos = _in(ts_t, pooled_lo, pooled_hi)
    c3_vol = np.std([t["pnl_net"] / t["notional"] for t in c3_oos], ddof=1) or 1e9
    ts_vol = np.std([t["pnl_net"] / t["notional"] for t in ts_oos], ddof=1) or 1e9
    wv = np.array([1 / c3_vol, 1 / ts_vol])
    wv = wv / wv.sum()
    iv_net = sum(wv[0] * t["pnl_net"] for t in c3_oos) + sum(
        wv[1] * t["pnl_net"] for t in ts_oos
    )

    # ===== CRITERION SCORING (FROZEN) =====
    c1 = frac_pos >= 0.60
    c2 = med_sharpe >= 0.50
    c3c = pooled_sharpe >= 1.0
    c4 = worst_dd <= 0.20
    c5 = pooled_sharpe > null_p95
    allc = c1 and c2 and c3c and c4 and c5

    print("\n" + "=" * 92)
    print("PRE-REGISTERED 5-PART CRITERION (frozen; no tuning to results)")
    print("=" * 92)
    print(
        f"  (1) folds OOS net>0 fraction : {frac_pos:.1%}  (>=60%)        -> {'PASS' if c1 else 'FAIL'}"
    )
    print(
        f"  (2) median per-fold OOS Shrp : {med_sharpe:+.3f}  (>=0.50)      -> {'PASS' if c2 else 'FAIL'}"
    )
    print(
        f"  (3) pooled-OOS daily Sharpe  : {pooled_sharpe:+.3f}  (>=1.0; sqrt365; daily mean {pooled_mean:+.5f} std {pooled_std:.5f}) -> {'PASS' if c3c else 'FAIL'}"
    )
    print(
        f"  (4) worst single-fold maxDD  : {worst_dd:.1%}  (<=20%)         -> {'PASS' if c4 else 'FAIL'}"
    )
    print(
        f"  (5) null control: real {pooled_sharpe:+.3f} vs sign-shuffle p95 {null_p95:+.3f} -> {'PASS' if c5 else 'FAIL'}"
    )
    print(
        f"\n  DIAGNOSTIC (not gated): C3-only pooled daily Sharpe {c3_only_sh:+.3f} | TSMOM-only {ts_only_sh:+.3f}"
    )
    print(
        f"  DIAGNOSTIC inverse-vol weights (C3,TSMOM)=({wv[0]:.2f},{wv[1]:.2f}) pooled-OOS net {iv_net:+.2f}"
    )
    print(
        f"  ensemble pooled-OOS net (equal-weight): {SLEEVE * sum(t['pnl_net'] for t in oos_trades):+.2f} over {len(oos_trades)} trades"
    )

    print("\n" + "=" * 92)
    print(
        f"TERMINAL VERDICT: {'GO — regime-robust edge (all 5 met)' if allc else 'NO-GO — edge not robust'}"
    )
    if not allc:
        missed = [n for n, ok in zip("12345", [c1, c2, c3c, c4, c5]) if not ok]
        print(f"  criteria missed: {', '.join(missed)}")
        print(
            "  => STOP the strategy hunt. Do NOT iterate/re-spec. Escalate the doctrine fork to operator."
        )
    else:
        print(
            "  => write GO + Track F infra sequencing (B1->B4->B2->B3->F.5). No infra/flip this session."
        )


if __name__ == "__main__":
    main()
