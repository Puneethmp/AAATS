"""Allocator-level regime gate (B.1.7 Tracks 9 + 10 + 11).

Pure-function regime filter that blocks NEW strategy entries during a sustained
BTC-vs-alts decoupling regime — the regime Track 8 diagnosed as fatal to
C3-perp (BTC up while alts bleed makes "buy cheap alt vs BTC" mean-reversion a
falling knife). This implements the locked 2026-05-27 decision
(feedback_regime_filtering_at_allocator): regime filtering belongs at the
allocator as a capital/exposure gate, NOT as a per-bar gate inside a single
strategy's entry hook.

v1 signal (Track 9) — rolling 30-day return divergence between BTC and the C3
universe alts:
    BTC_30d_ret = BTC.close[t] / BTC.close[t - lookback] - 1
    alt_30d_ret = mean( ALT.close[t] / ALT.close[t - lookback] - 1
                        for ALT in universe )
    divergence  = BTC_30d_ret - alt_30d_ret

A large positive divergence means BTC is outperforming alts over the trailing
month — i.e. BTC dominance rising / alts decoupling downward. BLOCK entries when
divergence > +0.08 (~3-sigma over 30d; principled, not swept).

v2 signal (Track 10) — ADDS a rolling 30-day BTC-alt correlation axis, ANDed
with the divergence gate. Track 9 showed divergence-alone is correctly-targeted
but insufficient: the earlier window was STRUCTURALLY BTC-favoring (mean
divergence +0.089 over 6mo), so a level threshold can't separate "structurally
elevated" from "spike." Correlation directly measures C3's mean-reversion thesis
assumption — alts and BTC moving TOGETHER — and is structurally independent of
the divergence level. v2 BLOCKS when EITHER signal fails:
    divergence ALLOW: divergence <= +0.08
    correlation ALLOW: 30d rolling Pearson(BTC hourly ret, mean-alt hourly ret)
                       >= +0.50

Both thresholds are principled values picked once (div +0.08 from Track 9,
unchanged; corr +0.50), NOT swept to discriminate the two test windows.

v3 signal (Track 11) — ADDS a longer-horizon relative-strength DRIFT axis, ANDed
with the divergence gate (correlation dropped: Track 10 proved it inert — it
never blocked a single bar in either window because BTC-alt hourly correlation
stayed 0.72-0.90 throughout; the damage was relative DRIFT, not decorrelation).
Track 10 named the drift/trend signal as the LAST cheap entry-gate experiment.

The drift axis measures the magnitude of the regression-fitted slope of the alt
basket's log relative-strength vs BTC over a 60-day lookback (LONGER than the
30d divergence lookback, so it captures persistent multi-month drift rather than
the 30d return level the divergence gate already sees):
    rs_t      = mean_alt( log(alt_close_t) - log(btc_close_t) )   # basket log-RS
    drift     = OLS_slope(rs_t vs bar_index over 60d) * 60d_bars  # fitted net move
    drift ALLOW: |drift| < +0.08   (range-bound enough for mean-reversion)
v3 BLOCKS when EITHER divergence (>0.08) OR |drift| (>=0.08) fails.

The drift threshold +0.08 is picked ONCE a priori, justified from the diagnosed
six-month failure magnitude — NOT swept. The mildest failing alt of the earlier
window (LINK) drifted -0.267 log-RS vs BTC over 6mo (4344 bars) = -6.15e-5/bar;
scaled to the 1440-bar (60d) lookback that is -0.089, rounded to 0.08 (also
pleasingly symmetric with the divergence threshold). A 60d trailing trend at or
above this magnitude means the basket is trending against BTC as hard as the
weakest leg of the known-fatal regime — too strong a directional drift for a
mean-reversion thesis to hold.

These functions take plain lists/arrays of closes/returns and no NT objects, so
they are unit-testable in isolation and reusable for any future strategy class.

    python3 tools/nautilus/regime_gate.py   # self-test on synthetic series
"""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

LOOKBACK_BARS = 720  # 30 days of 1h bars
DIVERGENCE_THRESHOLD = 0.08  # block entries when BTC outruns alts by >8% / 30d
CORRELATION_THRESHOLD = 0.50  # block entries when BTC-alt 30d corr drops below this
DRIFT_LOOKBACK_BARS = (
    1440  # 60 days of 1h bars — LONGER than the 30d divergence lookback
)
DRIFT_THRESHOLD = 0.08  # block when |60d regression-fitted basket log-RS drift| >= this


def compute_30d_divergence(
    btc_closes: Sequence[float],
    alt_closes_dict: Mapping[str, Sequence[float]],
    lookback_bars: int = LOOKBACK_BARS,
) -> float | None:
    """Rolling-30d (BTC - mean-alt) return divergence at the latest bar.

    Returns None when there is not yet ``lookback_bars`` of history for BTC or
    for any alt — the caller treats "uncomputable" as regime-OK (you cannot
    assess a 30-day regime in the first 30 days; don't block on missing data).
    """
    if btc_closes is None or len(btc_closes) <= lookback_bars:
        return None
    base = btc_closes[-1 - lookback_bars]
    if base == 0:
        return None
    btc_ret = btc_closes[-1] / base - 1.0

    alt_rets: list[float] = []
    for closes in alt_closes_dict.values():
        if closes is None or len(closes) <= lookback_bars:
            continue
        b = closes[-1 - lookback_bars]
        if b == 0:
            continue
        alt_rets.append(closes[-1] / b - 1.0)
    if not alt_rets:
        return None

    return float(btc_ret - sum(alt_rets) / len(alt_rets))


def is_regime_ok(
    divergence: float | None, threshold: float = DIVERGENCE_THRESHOLD
) -> bool:
    """True if new entries are ALLOWED this cycle.

    None (uncomputable) -> allow. Otherwise allow iff divergence <= threshold;
    a divergence above the threshold means BTC is decoupling upward from alts and
    new C3-class entries are blocked.
    """
    if divergence is None:
        return True
    return divergence <= threshold


def compute_30d_correlation(
    btc_returns: Sequence[float],
    alt_returns_dict: Mapping[str, Sequence[float]],
    lookback_bars: int = LOOKBACK_BARS,
) -> float | None:
    """Rolling-30d Pearson correlation of BTC vs mean-alt hourly returns.

    Inputs are HOURLY return series (e.g. log returns). The mean-alt series is
    the pointwise (per-hour) equal-weight mean of the alt return series. Returns
    the Pearson correlation over the trailing ``lookback_bars`` returns, or None
    when there is insufficient history or either series is constant over the
    window (caller treats None as regime-OK, matching the divergence helper).

    A LOW correlation means alts and BTC have decoupled — C3's mean-reversion
    thesis (alts and the BTC reference co-moving) no longer holds.
    """
    if btc_returns is None or len(btc_returns) < lookback_bars:
        return None
    alt_arrays: list[np.ndarray] = []
    for r in alt_returns_dict.values():
        if r is None or len(r) < lookback_bars:
            continue
        alt_arrays.append(np.asarray(r[-lookback_bars:], dtype=float))
    if not alt_arrays:
        return None

    btc = np.asarray(btc_returns[-lookback_bars:], dtype=float)
    mean_alt = np.mean(np.vstack(alt_arrays), axis=0)
    if btc.std() < 1e-12 or mean_alt.std() < 1e-12:
        return None
    return float(np.corrcoef(btc, mean_alt)[0, 1])


def is_regime_ok_v2(
    divergence: float | None,
    correlation: float | None,
    div_threshold: float = DIVERGENCE_THRESHOLD,
    corr_threshold: float = CORRELATION_THRESHOLD,
) -> bool:
    """v2 combined gate: ALLOW only if BOTH signals allow (block if EITHER fails).

    Divergence component reuses is_regime_ok (divergence <= div_threshold, None
    -> allow). Correlation component allows iff correlation >= corr_threshold
    (None -> allow). A drop below corr_threshold OR a divergence spike blocks.
    """
    div_ok = is_regime_ok(divergence, div_threshold)
    corr_ok = correlation is None or correlation >= corr_threshold
    return div_ok and corr_ok


def compute_drift_trend(
    btc_closes: Sequence[float],
    alt_closes_dict: Mapping[str, Sequence[float]],
    lookback_bars: int = DRIFT_LOOKBACK_BARS,
) -> float | None:
    """Regression-fitted net drift of the alt-basket log relative-strength vs BTC.

    Builds the equal-weight basket log relative-strength series over the trailing
    ``lookback_bars``::

        rs_t = mean_alt( log(alt_close_t) - log(btc_close_t) )

    fits ``rs_t ~ a + b * t`` by ordinary least squares (t = bar index 0..N-1),
    and returns ``b * lookback_bars`` — the fitted line's total rise across the
    window, i.e. the regression-SMOOTHED net relative drift (distinct from the
    divergence gate's two-endpoint 30d return). Positive => the alt basket is
    trending UP vs BTC over the window; negative => alts bleeding vs BTC (the
    Track-8 failure regime). The slope is offset-invariant, so averaging
    different-scale alts' log-RS levels is sound (slope of the mean = mean of the
    per-alt slopes).

    Returns None when there is not yet ``lookback_bars`` of history for BTC or for
    any alt (caller treats None as regime-OK, matching the other helpers).
    """
    if btc_closes is None or len(btc_closes) < lookback_bars:
        return None
    btc = np.log(np.asarray(btc_closes[-lookback_bars:], dtype=float))

    rs_arrays: list[np.ndarray] = []
    for closes in alt_closes_dict.values():
        if closes is None or len(closes) < lookback_bars:
            continue
        alt = np.log(np.asarray(closes[-lookback_bars:], dtype=float))
        rs_arrays.append(alt - btc)
    if not rs_arrays:
        return None

    rs = np.mean(np.vstack(rs_arrays), axis=0)
    t = np.arange(lookback_bars, dtype=float)
    slope = float(np.polyfit(t, rs, 1)[0])
    return slope * lookback_bars


def is_regime_ok_v3(
    divergence: float | None,
    drift: float | None,
    div_threshold: float = DIVERGENCE_THRESHOLD,
    drift_threshold: float = DRIFT_THRESHOLD,
) -> bool:
    """v3 combined gate: ALLOW only if BOTH divergence (v1) AND drift allow.

    Divergence component reuses is_regime_ok (divergence <= div_threshold, None
    -> allow). Drift component allows iff |drift| < drift_threshold (None ->
    allow). A persistent relative trend (|drift| >= threshold) in EITHER
    direction OR a divergence spike blocks new entries.
    """
    div_ok = is_regime_ok(divergence, div_threshold)
    drift_ok = drift is None or abs(drift) < drift_threshold
    return div_ok and drift_ok


if __name__ == "__main__":
    # Self-test on synthetic series — no NT, no data files needed.
    n = 1000
    flat_btc = [100.0] * n
    flat_alt = [50.0] * n
    div = compute_30d_divergence(flat_btc, {"A": flat_alt, "B": flat_alt})
    assert div is not None and abs(div) < 1e-9, div
    assert is_regime_ok(div) is True

    # BTC +12% over the lookback, alts flat -> divergence ~ +0.12 > 0.08 -> BLOCK.
    up_btc = [100.0] * (n - 1) + [112.0]
    div2 = compute_30d_divergence(up_btc, {"A": flat_alt, "B": flat_alt})
    assert div2 is not None and abs(div2 - 0.12) < 1e-9, div2
    assert is_regime_ok(div2) is False

    # Insufficient history -> None -> allow.
    assert compute_30d_divergence([100.0] * 10, {"A": [50.0] * 10}) is None
    assert is_regime_ok(None) is True

    # BTC down with alts (both -20%) -> divergence ~0 -> ALLOW (range-bound ALT/BTC).
    down_btc = [100.0] * (n - 1) + [80.0]
    down_alt = [50.0] * (n - 1) + [40.0]
    div3 = compute_30d_divergence(down_btc, {"A": down_alt})
    assert div3 is not None and abs(div3) < 1e-9, div3
    assert is_regime_ok(div3) is True

    # --- v2 correlation + combined gate ---
    rng = np.random.default_rng(7)
    base = rng.standard_normal(800)
    # Perfectly co-moving alt -> corr ~ +1 -> correlation ALLOWs.
    corr_hi = compute_30d_correlation(list(base), {"A": list(base)}, lookback_bars=720)
    assert corr_hi is not None and corr_hi > 0.99, corr_hi
    assert is_regime_ok_v2(0.0, corr_hi) is True  # both signals allow

    # Anti-correlated alt (decoupled) -> corr ~ -1 < 0.5 -> BLOCK even if div ok.
    corr_lo = compute_30d_correlation(list(base), {"A": list(-base)}, lookback_bars=720)
    assert corr_lo is not None and corr_lo < -0.99, corr_lo
    assert is_regime_ok_v2(0.0, corr_lo) is False  # correlation fails the AND

    # Divergence spike blocks even when correlation is fine.
    assert is_regime_ok_v2(0.20, corr_hi) is False

    # Insufficient history -> None corr -> correlation defaults to ALLOW.
    assert compute_30d_correlation(list(base[:10]), {"A": list(base[:10])}) is None
    assert is_regime_ok_v2(0.0, None) is True

    # --- v3 drift-trend + combined gate ---
    lb = 1440
    # Flat relative-strength (alt and BTC move identically) -> drift ~ 0 -> ALLOW.
    flat_pair_btc = [100.0 * (1.001**i) for i in range(lb + 5)]
    flat_pair_alt = [50.0 * (1.001**i) for i in range(lb + 5)]  # same growth rate
    drift_flat = compute_drift_trend(flat_pair_btc, {"A": flat_pair_alt})
    assert drift_flat is not None and abs(drift_flat) < 1e-6, drift_flat
    assert is_regime_ok_v3(0.0, drift_flat) is True

    # Alt bleeding vs BTC at -0.0002/bar -> drift ~ -0.288 over 1440 bars -> BLOCK.
    down_alt_pair = [50.0 * np.exp(-0.0002 * i) for i in range(lb + 5)]
    drift_down = compute_drift_trend([100.0] * (lb + 5), {"A": down_alt_pair})
    assert drift_down is not None and abs(drift_down + 0.288) < 0.01, drift_down
    assert is_regime_ok_v3(0.0, drift_down) is False  # |drift| >= 0.08 blocks

    # A mild relative trend just under threshold passes; a divergence spike still blocks.
    mild_alt = [
        50.0 * np.exp(-0.00003 * i) for i in range(lb + 5)
    ]  # ~ -0.043 over 1440
    drift_mild = compute_drift_trend([100.0] * (lb + 5), {"A": mild_alt})
    assert drift_mild is not None and abs(drift_mild) < 0.08, drift_mild
    assert is_regime_ok_v3(0.0, drift_mild) is True
    assert is_regime_ok_v3(0.20, drift_mild) is False  # divergence fails the AND

    # Insufficient history -> None drift -> drift defaults to ALLOW.
    assert compute_drift_trend([100.0] * 10, {"A": [50.0] * 10}) is None
    assert is_regime_ok_v3(0.0, None) is True

    print("regime_gate self-test: all assertions passed.")
