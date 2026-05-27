"""C3 regime gate proposal + re-test for B.1.5 Phase 5.

Workflow:
  1. Compute window-aggregate regime features on BTC bars for W1-W5.
  2. Identify W2's fingerprint (>1 std from MARGINAL-window mean).
  3. Propose a per-bar trailing-window gate.
  4. Re-run C3 across all 5 windows at slip 0 and 22 bps, gate applied.
  5. Verdict: ROBUST / GATE-PROMISING / GATE-INEFFECTIVE.

Run via: python tools/backtest/_c3_regime_gate_oneoff.py
Saves: data/backtest_results/c3_regime_gate_2026_05_27.json
"""

from __future__ import annotations

import io
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.backtest.c3_replay import (  # noqa: E402
    summarize_trades,
    BTC_SYMBOL,
)
from trading import altcoin_reversion as c3mod  # noqa: E402

HIST = ROOT / "data" / "historical"
UNIVERSE = sorted({BTC_SYMBOL, *c3mod.SYMBOLS})
BARS_PER_DAY = 24
WINDOW_DAYS = 60
STRIDE_DAYS = 30
WARMUP = 35
SLIP_LEVELS = [0.0, 22.0]
TRAILING_LOOKBACK = 60  # bars; matches C3 LOOKBACK_BARS
BBAND_PERIOD = 20

# Window verdicts from Phase 4 (cross-referenced):
PHASE4_VERDICT = {
    "W1": "MARGINAL",
    "W2": "DEAD",
    "W3": "MARGINAL",
    "W4": "MARGINAL",
    "W5": "MARGINAL",
}
PHASE4_UNGATED_PNL0 = {
    "W1": 3.7437,
    "W2": -1.1782,
    "W3": 1.5005,
    "W4": 4.0951,
    "W5": 6.7924,
}


def load(sym: str) -> pd.DataFrame:
    p = HIST / (sym.replace("/", "_") + "_1h.parquet")
    df = pd.read_parquet(p)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts").reset_index(drop=True)


def align_bars() -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp]]:
    bars = {s: load(s) for s in UNIVERSE}
    common = None
    for df in bars.values():
        ts = set(df["ts"])
        common = ts if common is None else common & ts
    assert common is not None
    common_sorted = sorted(common)
    for s in bars:
        bars[s] = (
            bars[s][bars[s]["ts"].isin(common_sorted)]
            .sort_values("ts")
            .reset_index(drop=True)
        )
    return bars, common_sorted


# ─── Regime feature computation (window-aggregate) ──────────────────────


def realized_vol_annualized(closes: np.ndarray) -> float:
    log_ret = np.diff(np.log(closes))
    return float(np.std(log_ret, ddof=1) * np.sqrt(8760))


def trend_strength(closes: np.ndarray) -> float:
    """abs(OLS slope of close vs index) / mean(close). Unit: per-bar fraction."""
    n = len(closes)
    x = np.arange(n, dtype=float)
    x = x - x.mean()
    y = closes - closes.mean()
    if (x * x).sum() < 1e-12:
        return 0.0
    slope = (x * y).sum() / (x * x).sum()
    return float(abs(slope) / closes.mean())


def autocorrelation_lag1(closes: np.ndarray) -> float:
    log_ret = np.diff(np.log(closes))
    if len(log_ret) < 3:
        return 0.0
    a = log_ret[:-1]
    b = log_ret[1:]
    if a.std() < 1e-12 or b.std() < 1e-12:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def bband_width_mean(closes: np.ndarray, period: int = BBAND_PERIOD) -> float:
    s = pd.Series(closes)
    mid = s.rolling(period).mean()
    std = s.rolling(period).std(ddof=0)
    width = (4.0 * std) / mid  # upper - lower = 4 * std (using n_std=2)
    return float(width.dropna().mean())


def directional_pct(closes: np.ndarray) -> float:
    return float(abs(closes[-1] - closes[0]) / closes[0])


def max_drawdown_pct(closes: np.ndarray) -> float:
    peak = np.maximum.accumulate(closes)
    dd = (peak - closes) / peak
    return float(dd.max())


def window_features(btc_df: pd.DataFrame, ws: int, we: int) -> dict:
    closes = btc_df["close"].iloc[ws:we].values.astype(float)
    return {
        "realized_vol_annualized": realized_vol_annualized(closes),
        "trend_strength_per_bar": trend_strength(closes),
        "autocorrelation_lag1": autocorrelation_lag1(closes),
        "bband_width_mean": bband_width_mean(closes),
        "directional_pct": directional_pct(closes),
        "max_drawdown_pct": max_drawdown_pct(closes),
    }


# ─── Trailing-window features (per-bar gate computation) ───────────────


def trailing_features(btc_df: pd.DataFrame, idx: int) -> dict | None:
    """Compute gate features on bars [idx - TRAILING_LOOKBACK + 1 : idx + 1]."""
    if idx < TRAILING_LOOKBACK:
        return None
    closes = (
        btc_df["close"].iloc[idx - TRAILING_LOOKBACK + 1 : idx + 1].values.astype(float)
    )
    return {
        "trend_strength": trend_strength(closes),
        "directional_pct": directional_pct(closes),
        "realized_vol_ann": realized_vol_annualized(closes),
    }


# ─── Gate-enabled C3 replay (entry hook only) ──────────────────────────


def make_gate(thresholds: dict):
    """Return a callable: gate(btc_df, idx) -> bool (True = allow entry)."""

    def gate(btc_df: pd.DataFrame, idx: int) -> bool:
        feats = trailing_features(btc_df, idx)
        if feats is None:
            return False
        for key, (op, val) in thresholds.items():
            x = feats[key]
            if op == "<" and not (x < val):
                return False
            elif op == "<=" and not (x <= val):
                return False
            elif op == ">" and not (x > val):
                return False
            elif op == ">=" and not (x >= val):
                return False
        return True

    return gate


def replay_c3_gated(
    bars_by_symbol,
    start_idx,
    end_idx,
    starting_capital,
    slippage_bps,
    universe,
    gate_fn,
) -> tuple[dict, int]:
    """C3 replay that calls gate_fn(btc_df, idx) before each entry attempt.

    Re-implements the loop from c3_replay.replay_c3 with a single addition:
    when an entry would be initiated, gate_fn must return True. Counts
    excluded entries.
    """
    from tools.backtest.c3_replay import (
        _compute_z,
        _rsi,
        _realized_vol,
        _compute_trade_size,
        _slice_until,
        Z_ENTRY,
        Z_HARD_STOP,
        Z_TRAILING_MIN,
        Z_TRAILING_DROP,
        Z_TARGET,
        TIME_STOP_HOURS,
        BTC_RSI_MIN,
        COOLDOWN_HOURS,
        DENYLIST_SYMBOLS,
        MAX_CONCURRENT,
    )

    btc_df = bars_by_symbol[BTC_SYMBOL]
    n_bars = min(
        len(btc_df),
        min(len(bars_by_symbol[s]) for s in universe if s in bars_by_symbol),
    )
    end_idx = min(end_idx, n_bars)

    capital = float(starting_capital)
    peak = capital
    max_dd = 0.0
    positions: dict = {}
    cooldown: dict = {}
    trades: list = []
    excluded = 0

    for idx in range(start_idx, end_idx):
        # Exit pass
        to_close = []
        for sym, pos in positions.items():
            if sym not in bars_by_symbol:
                continue
            alt_df = _slice_until(bars_by_symbol[sym], idx)
            b_df = _slice_until(btc_df, idx)
            z = _compute_z(alt_df, b_df, lookback=60)
            if z is None:
                continue
            if z > pos["max_z"]:
                pos["max_z"] = z
            age_h = idx - pos["entry_idx"]
            reason = None
            if z >= Z_TARGET:
                reason = "z_overshoot"
            elif (
                pos["max_z"] >= Z_TRAILING_MIN and (pos["max_z"] - z) >= Z_TRAILING_DROP
            ):
                reason = "z_trailing"
            elif z <= Z_HARD_STOP:
                reason = "z_hard_stop"
            elif age_h >= TIME_STOP_HOURS:
                reason = f"time_stop_{TIME_STOP_HOURS}h"
            if reason:
                bar_close = float(alt_df["close"].iloc[-1])
                fill = bar_close * (1.0 - slippage_bps / 10_000.0)
                to_close.append((sym, pos, fill, reason))
        for sym, pos, fill, reason in to_close:
            pnl = pos["shares"] * (fill - pos["entry_price"])
            capital += pos["size_usd"] + pnl
            trades.append(
                {
                    "symbol": sym,
                    "entry_idx": pos["entry_idx"],
                    "exit_idx": idx,
                    "entry_price": pos["entry_price"],
                    "exit_price": fill,
                    "shares": pos["shares"],
                    "size_usd": pos["size_usd"],
                    "pnl_usd": pnl,
                    "entry_z": pos["entry_z"],
                    "max_z": pos["max_z"],
                    "exit_reason": reason,
                }
            )
            if reason in ("z_hard_stop", f"time_stop_{TIME_STOP_HOURS}h") and pnl < 0:
                cooldown[sym] = idx + COOLDOWN_HOURS
            del positions[sym]

        # Equity tracking
        unreal = 0.0
        for sym, pos in positions.items():
            if sym in bars_by_symbol:
                mark = float(bars_by_symbol[sym]["close"].iloc[idx])
                unreal += pos["shares"] * (mark - pos["entry_price"])
        equity = capital + sum(p["size_usd"] for p in positions.values()) + unreal
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd

        # Entry pass
        btc_slice = _slice_until(btc_df, idx)
        if len(btc_slice) < 20:
            continue
        btc_rsi = _rsi(btc_slice["close"], period=14)
        if btc_rsi < BTC_RSI_MIN:
            continue

        for sym in universe:
            if sym in positions:
                continue
            if sym in DENYLIST_SYMBOLS:
                continue
            if len(positions) >= MAX_CONCURRENT:
                break
            if cooldown.get(sym, -1) > idx:
                continue
            if sym not in bars_by_symbol:
                continue
            alt_df = _slice_until(bars_by_symbol[sym], idx)
            if len(alt_df) < 60 + 10:
                continue
            z = _compute_z(alt_df, btc_slice, lookback=60)
            if z is None or z > Z_ENTRY:
                continue
            # ─── REGIME GATE ───
            if not gate_fn(btc_df, idx):
                excluded += 1
                continue
            # Size
            symvol = _realized_vol(alt_df)
            size_usd, _ = _compute_trade_size(
                capital=capital,
                open_positions=len(positions),
                symbol_vol=symvol,
            )
            if size_usd <= 0:
                continue
            entry_price = float(alt_df["close"].iloc[-1]) * (
                1.0 + slippage_bps / 10_000.0
            )
            shares = size_usd / entry_price
            capital -= size_usd
            positions[sym] = {
                "entry_idx": idx,
                "entry_price": entry_price,
                "shares": shares,
                "size_usd": size_usd,
                "entry_z": z,
                "max_z": z,
            }

    return (
        {
            "trades": trades,
            "final_capital": capital + sum(p["size_usd"] for p in positions.values()),
            "starting_capital": starting_capital,
            "peak_capital": peak,
            "max_drawdown_pct": max_dd,
            "bars_evaluated": end_idx - start_idx,
        },
        excluded,
    )


# ─── Main driver ──────────────────────────────────────────────────────


def classify_window(pnl: float, sharpe: float, breakeven_proxy: float) -> str:
    if pnl <= 0:
        return "DEAD"
    if breakeven_proxy >= 22.0 and sharpe > 0.3:
        return "MARGINAL"
    if breakeven_proxy >= 22.0 and sharpe > 0.8:
        return "STRONG"
    if sharpe <= 0.3:
        return "DEAD"
    return "MARGINAL"


def interp_bp_from_two(p0: float, p22: float) -> float | None:
    """Linear-interpolate break-even between two sweep points."""
    if p0 <= 0:
        return 0.0
    if p22 > 0:
        return None  # still positive at 22 bps; can't compute upper bound from 2 pts
    if p0 == p22:
        return 0.0
    return float(0.0 + (0.0 - p0) * (22.0 - 0.0) / (p22 - p0))


def main() -> int:
    bars, common = align_bars()
    btc_df = bars[BTC_SYMBOL]
    n = len(common)
    bars_per_window = WINDOW_DAYS * BARS_PER_DAY
    bars_per_stride = STRIDE_DAYS * BARS_PER_DAY

    # ── STEP 1: window-aggregate regime features ──
    print("=" * 72, flush=True)
    print("STEP 1 — Regime features per window (BTC bars)", flush=True)
    print("=" * 72, flush=True)
    win_meta = []
    feat_keys = [
        "realized_vol_annualized",
        "trend_strength_per_bar",
        "autocorrelation_lag1",
        "bband_width_mean",
        "directional_pct",
        "max_drawdown_pct",
    ]
    print(
        f"{'Win':>3} {'rv_ann':>8} {'trend_pb':>10} {'ac1':>7} "
        f"{'bbw':>7} {'dir%':>7} {'dd%':>7}  verdict",
        flush=True,
    )
    for w in range(5):
        ws = w * bars_per_stride
        we = ws + bars_per_window
        if we > n:
            break
        feats = window_features(btc_df, ws, we)
        win_id = f"W{w + 1}"
        verdict = PHASE4_VERDICT[win_id]
        win_meta.append(
            {
                "window_id": win_id,
                "start_idx": ws,
                "end_idx": we,
                "start_ts": str(common[ws]),
                "end_ts": str(common[we - 1]),
                "features": feats,
                "phase4_verdict": verdict,
                "phase4_pnl_at_0bps": PHASE4_UNGATED_PNL0[win_id],
            }
        )
        print(
            f"{win_id:>3} "
            f"{feats['realized_vol_annualized']:>8.3f} "
            f"{feats['trend_strength_per_bar']:>10.2e} "
            f"{feats['autocorrelation_lag1']:>+7.3f} "
            f"{feats['bband_width_mean']:>7.4f} "
            f"{feats['directional_pct']:>7.3f} "
            f"{feats['max_drawdown_pct']:>7.3f}  "
            f"{verdict}",
            flush=True,
        )

    # ── STEP 2: identify W2 fingerprint ──
    print("\n" + "=" * 72, flush=True)
    print("STEP 2 — W2 fingerprint (deviation from MARGINAL-window mean)", flush=True)
    print("=" * 72, flush=True)
    w2 = next(w for w in win_meta if w["window_id"] == "W2")
    marginals = [w for w in win_meta if w["window_id"] != "W2"]
    fingerprint = {}
    for key in feat_keys:
        vals = np.array([w["features"][key] for w in marginals])
        mean = float(vals.mean())
        std = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
        w2val = w2["features"][key]
        z = (w2val - mean) / std if std > 1e-12 else 0.0
        fingerprint[key] = {
            "w2_value": w2val,
            "marginal_mean": mean,
            "marginal_std": std,
            "w2_z_score": z,
        }
        flag = "*** FINGERPRINT" if abs(z) > 1.0 else ""
        print(
            f"  {key:25} W2={w2val:+.4f}  marg_mean={mean:+.4f}  "
            f"marg_std={std:.4f}  z={z:+.2f}  {flag}",
            flush=True,
        )

    fingerprint_features = [
        k for k, v in fingerprint.items() if abs(v["w2_z_score"]) > 1.0
    ]
    if not fingerprint_features:
        print(
            "\n!!! W2 does not differ from MARGINAL windows by >1 std on any "
            "feature. Gate concept may not apply — surface to operator.",
            flush=True,
        )
        out = {
            "strategy": "c3",
            "phase": "B.1.5 phase 5 regime gate",
            "step1_features": win_meta,
            "step2_fingerprint": fingerprint,
            "step3_gate_proposal": None,
            "step4_gated_results": None,
            "aggregate_verdict": "GATE-INEFFECTIVE-NO-FINGERPRINT",
        }
        out_path = ROOT / "data" / "backtest_results" / "c3_regime_gate_2026_05_27.json"
        out_path.write_text(json.dumps(out, default=str, indent=2))
        print(f"\nSaved: {out_path}", flush=True)
        return 0

    print(f"\nFingerprint features (|z|>1.0): {fingerprint_features}", flush=True)

    # ── STEP 3: propose gate ──
    # Use the top 2-3 features with highest |z|, sign-aware
    print("\n" + "=" * 72, flush=True)
    print("STEP 3 — Gate threshold proposal", flush=True)
    print("=" * 72, flush=True)
    ranked = sorted(
        fingerprint_features,
        key=lambda k: -abs(fingerprint[k]["w2_z_score"]),
    )
    gate_features = ranked[:3]
    gate_spec = {}
    # The gate features used for the LIVE gate must be computable on a trailing
    # 60-bar window (TRAILING_LOOKBACK). Of the 6 window-aggregate features,
    # 3 have direct trailing analogs: trend_strength, directional_pct,
    # realized_vol_ann. We use those that survived the fingerprint AND are
    # trailing-computable.
    trailing_compatible = {
        "trend_strength_per_bar": "trend_strength",
        "directional_pct": "directional_pct",
        "realized_vol_annualized": "realized_vol_ann",
    }
    for key in gate_features:
        if key not in trailing_compatible:
            continue
        live_key = trailing_compatible[key]
        w2v = fingerprint[key]["w2_value"]
        marg_mean = fingerprint[key]["marginal_mean"]
        marg_std = fingerprint[key]["marginal_std"]
        # Direction: if W2 > marginals, gate is "live_key < threshold"
        # threshold = midpoint between worst-MARGINAL value and W2 value
        marginal_vals = [w["features"][key] for w in marginals]
        if w2v > marg_mean:
            # W2 high — gate blocks high values
            worst_marginal = max(marginal_vals)
            threshold = (w2v + worst_marginal) / 2.0
            op = "<"
        else:
            # W2 low — gate blocks low values
            worst_marginal = min(marginal_vals)
            threshold = (w2v + worst_marginal) / 2.0
            op = ">"
        gate_spec[live_key] = {
            "operator": op,
            "threshold": threshold,
            "w2_value": w2v,
            "worst_compatible_marginal": worst_marginal,
            "marginal_mean": marg_mean,
            "marginal_std": marg_std,
            "z_score": fingerprint[key]["w2_z_score"],
            "rationale": (
                f"W2 {key}={w2v:.4f} (z={fingerprint[key]['w2_z_score']:+.2f} vs "
                f"marginal mean {marg_mean:.4f}). Threshold at midpoint between "
                f"W2 and worst-side MARGINAL ({worst_marginal:.4f})."
            ),
        }
    if not gate_spec:
        print(
            "\n!!! Fingerprint features are not trailing-computable. "
            "Need different approach.",
            flush=True,
        )
        return 1

    print("Proposed gate (live-computable on trailing 60-bar BTC window):", flush=True)
    thresholds_for_gate: dict = {}
    for k, v in gate_spec.items():
        op = v["operator"]
        thr = v["threshold"]
        thresholds_for_gate[k] = (op, thr)
        print(
            f"  ALLOW entry IFF {k} {op} {thr:.4f}   "
            f"(W2={v['w2_value']:.4f}, worst-marg={v['worst_compatible_marginal']:.4f})",
            flush=True,
        )

    # ── STEP 4: gated re-test ──
    print("\n" + "=" * 72, flush=True)
    print("STEP 4 — Gated C3 re-test (slip 0 and 22 bps)", flush=True)
    print("=" * 72, flush=True)
    gate_fn = make_gate(thresholds_for_gate)
    gated_results = []
    for w in range(5):
        ws = w * bars_per_stride
        we = ws + bars_per_window
        if we > n:
            break
        start_idx = ws + WARMUP
        end_idx = we
        win_id = f"W{w + 1}"
        win_block = {
            "window_id": win_id,
            "rows": [],
            "ungated_pnl_at_0bps": PHASE4_UNGATED_PNL0[win_id],
            "phase4_verdict": PHASE4_VERDICT[win_id],
        }
        for slip in SLIP_LEVELS:
            r, excluded = replay_c3_gated(
                bars_by_symbol=bars,
                start_idx=start_idx,
                end_idx=end_idx,
                starting_capital=100.0,
                slippage_bps=slip,
                universe=list(c3mod.SYMBOLS),
                gate_fn=gate_fn,
            )
            s = summarize_trades(r["trades"], end_idx - start_idx)
            win_block["rows"].append(
                {
                    "slip_bps": slip,
                    "n_trades": s["n_trades"],
                    "n_excluded_by_gate": excluded,
                    "pnl_usd": round(s["pnl_usd"], 4),
                    "sharpe": round(s["sharpe"], 3),
                    "win_rate": round(s["win_rate"], 3),
                    "profit_factor": (
                        round(s["profit_factor"], 3)
                        if s["profit_factor"] != float("inf")
                        else "inf"
                    ),
                    "max_drawdown_pct": round(r["max_drawdown_pct"], 4),
                }
            )
        # Derive a break-even proxy from the two slip points
        p0 = win_block["rows"][0]["pnl_usd"]
        p22 = win_block["rows"][1]["pnl_usd"]
        be = interp_bp_from_two(p0, p22)
        win_block["breakeven_bps_proxy"] = be
        verdict_gated = classify_window(
            pnl=p0,
            sharpe=win_block["rows"][0]["sharpe"],
            breakeven_proxy=be if be is not None else 50.0,
        )
        win_block["gated_verdict"] = verdict_gated
        gated_results.append(win_block)
        # Print row summary
        r0 = win_block["rows"][0]
        r22 = win_block["rows"][1]
        ungate = PHASE4_UNGATED_PNL0[win_id]
        degr = ((ungate - r0["pnl_usd"]) / abs(ungate) * 100.0) if ungate != 0 else 0.0
        print(
            f"  {win_id}: ungated_pnl0={ungate:+.4f}  gated_pnl0={r0['pnl_usd']:+.4f} "
            f"(degr={degr:+.1f}%)  gated_sh0={r0['sharpe']:+.2f}  "
            f"gated_pnl22={r22['pnl_usd']:+.4f}  "
            f"n_excluded={r0['n_excluded_by_gate']}  -> {verdict_gated}",
            flush=True,
        )

    # ── Cross-window aggregate verdict ──
    verdicts = [w["gated_verdict"] for w in gated_results]
    dead_count = sum(1 for v in verdicts if v == "DEAD")
    good_count = len(verdicts) - dead_count
    # Degradation check: for MARGINAL/STRONG ungated windows (W1, W3, W4, W5),
    # how much did gated PnL drop relative to ungated?
    margin_windows = [w for w in gated_results if w["phase4_verdict"] != "DEAD"]
    max_degradation = 0.0
    for w in margin_windows:
        u = w["ungated_pnl_at_0bps"]
        g = w["rows"][0]["pnl_usd"]
        if u > 0:
            degr = (u - g) / u
            if degr > max_degradation:
                max_degradation = degr

    if dead_count == 0 and good_count >= 4 and max_degradation < 0.20:
        aggregate = "ROBUST"
    elif dead_count == 0 and good_count >= 4 and max_degradation < 0.50:
        aggregate = "GATE-PROMISING"  # W2 fixed but some over-filter
    elif dead_count >= 1:
        aggregate = "GATE-INEFFECTIVE"
    else:
        aggregate = "GATE-PROMISING"

    print("\n" + "=" * 72, flush=True)
    print(f"AGGREGATE VERDICT: {aggregate}", flush=True)
    print(
        f"  Gated verdicts: {verdicts}  "
        f"(DEAD={dead_count}, MARGINAL/STRONG={good_count})",
        flush=True,
    )
    print(
        f"  Max degradation on ungated-MARGINAL windows: {max_degradation:.1%}",
        flush=True,
    )

    out = {
        "strategy": "c3",
        "phase": "B.1.5 phase 5 regime gate",
        "data_window": f"{common[0]} to {common[-1]} ({n} 1h bars)",
        "universe": UNIVERSE,
        "trailing_lookback_bars": TRAILING_LOOKBACK,
        "slippage_levels_bps": SLIP_LEVELS,
        "step1_window_features": win_meta,
        "step2_fingerprint": fingerprint,
        "step2_fingerprint_features": fingerprint_features,
        "step3_gate_spec": gate_spec,
        "step3_gate_live_thresholds": {
            k: {"operator": v[0], "threshold": v[1]}
            for k, v in thresholds_for_gate.items()
        },
        "step4_gated_results": gated_results,
        "aggregate_verdict": aggregate,
        "max_degradation_pct": max_degradation,
        "gated_verdict_distribution": {
            "STRONG": sum(1 for v in verdicts if v == "STRONG"),
            "MARGINAL": sum(1 for v in verdicts if v == "MARGINAL"),
            "DEAD": sum(1 for v in verdicts if v == "DEAD"),
        },
    }
    out_path = ROOT / "data" / "backtest_results" / "c3_regime_gate_2026_05_27.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, default=str, indent=2))
    print(f"\nSaved: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
