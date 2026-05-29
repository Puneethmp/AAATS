"""Allocator-level regime gate (B.1.7 Tracks 9 + 10).

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

    print("regime_gate self-test: all assertions passed.")
