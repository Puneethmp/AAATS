"""Allocator-level regime gate (B.1.7 Track 9).

Pure-function regime filter that blocks NEW strategy entries during a sustained
BTC-vs-alts decoupling regime — the regime Track 8 diagnosed as fatal to
C3-perp (BTC up while alts bleed makes "buy cheap alt vs BTC" mean-reversion a
falling knife). This implements the locked 2026-05-27 decision
(feedback_regime_filtering_at_allocator): regime filtering belongs at the
allocator as a capital/exposure gate, NOT as a per-bar gate inside a single
strategy's entry hook.

Signal — rolling 30-day return divergence between BTC and the C3 universe alts:
    BTC_30d_ret = BTC.close[t] / BTC.close[t - lookback] - 1
    alt_30d_ret = mean( ALT.close[t] / ALT.close[t - lookback] - 1
                        for ALT in universe )
    divergence  = BTC_30d_ret - alt_30d_ret

A large positive divergence means BTC is outperforming alts over the trailing
month — i.e. BTC dominance rising / alts decoupling downward.

Threshold (PRINCIPLED, not swept from the test data): BLOCK new entries when
divergence > +0.08 (BTC outperforming alts by >8% over rolling 30d). ~8%/30d is
roughly a 3-sigma move in normal markets and qualitatively matches the "BTC
decoupling" intuition. The number was chosen by characterization, not optimized
to discriminate the two B.1.7 test windows.

These functions take plain lists/arrays of closes and no NT objects, so they are
unit-testable in isolation and reusable for any future strategy class.

    python3 tools/nautilus/regime_gate.py   # self-test on synthetic series
"""

from __future__ import annotations

from typing import Mapping, Sequence

LOOKBACK_BARS = 720  # 30 days of 1h bars
DIVERGENCE_THRESHOLD = 0.08  # block entries when BTC outruns alts by >8% / 30d


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

    print("regime_gate self-test: all assertions passed.")
