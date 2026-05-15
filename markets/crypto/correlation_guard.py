"""
markets/crypto/correlation_guard.py  —  Block over-concentration in correlated alts
==================================================================================

PURPOSE
-------
The scanner can return 5 strong candidates that are ALL in the same cluster
(e.g., 5 L1 alts when ETH is rallying). Without this guard, you'd open 5
positions and effectively make 1 concentrated bet — when the cluster rotates
out, all 5 stop out simultaneously.

This module enforces "no more than N positions per correlation cluster."
Simple, static cluster table; no real-time Pearson math needed at this
capital level (premature, fragile, and high-variance on small samples).

CLUSTERS (each symbol belongs to exactly one)
---------------------------------------------
- MAJOR     : BTC, ETH
- L1_ALT    : SOL, AVAX, DOT, NEAR, ATOM, ADA, FTM, ALGO, EGLD, ICP, APT, SUI, SEI, TIA, INJ
- L2        : ARB, OP, MATIC, IMX, STRK, ZK
- DEFI      : UNI, AAVE, CRV, LDO, MKR, GMX, DYDX, COMP, CAKE, SUSHI, PENDLE, RDNT
- MEME      : DOGE, SHIB, PEPE, BONK, WIF, FLOKI, MEME
- AI        : RNDR, FET, TAO, AGIX, OCEAN, NMR
- GAMING    : AXS, GALA, IMX, SAND, MANA, ENJ, RON
- INFRA     : LINK, FIL, GRT, AR, RUNE, INJ, AKT
- OTHER     : everything else

Cap: max 3 positions per cluster (configurable below).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# ── Cluster cap ───────────────────────────────────────────────────────────────
MAX_PER_CLUSTER = 3   # max simultaneous open positions in same cluster


# ── Static cluster mapping ────────────────────────────────────────────────────
_CLUSTER_TABLE: dict[str, str] = {}

def _register(cluster: str, *symbols: str) -> None:
    for s in symbols:
        _CLUSTER_TABLE[s.upper()] = cluster

_register("MAJOR",  "BTC", "ETH")
_register("L1_ALT",
    "SOL", "AVAX", "DOT", "NEAR", "ATOM", "ADA", "FTM", "ALGO", "EGLD",
    "ICP", "APT", "SUI", "SEI", "TIA", "INJ", "KAS", "TON")
_register("L2", "ARB", "OP", "MATIC", "IMX", "STRK", "ZK", "MANTA")
_register("DEFI",
    "UNI", "AAVE", "CRV", "LDO", "MKR", "GMX", "DYDX", "COMP",
    "CAKE", "SUSHI", "PENDLE", "RDNT", "JUP", "RAY")
_register("MEME",
    "DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI", "MEME", "BOME", "MEW")
_register("AI",
    "RNDR", "FET", "TAO", "AGIX", "OCEAN", "NMR", "WLD")
_register("GAMING",
    "AXS", "GALA", "SAND", "MANA", "ENJ", "RON", "BEAM", "PIXEL", "ACE")
_register("INFRA",
    "LINK", "FIL", "GRT", "AR", "RUNE", "AKT", "HNT", "NMR")


def _base_of(symbol: str) -> str:
    """Extract base asset from 'BTC/USDT' → 'BTC'."""
    return symbol.split("/")[0].upper() if "/" in symbol else symbol.upper()


def cluster_of(symbol: str) -> str:
    """Return the cluster name for a symbol. Unknown → 'OTHER'."""
    return _CLUSTER_TABLE.get(_base_of(symbol), "OTHER")


# ── Public guard ──────────────────────────────────────────────────────────────
def filter_by_cluster_caps(
    proposed: list[str],
    open_symbols: list[str],
    max_per_cluster: int = MAX_PER_CLUSTER,
) -> list[str]:
    """
    Filter `proposed` such that adding them to `open_symbols` does not
    exceed `max_per_cluster` in any single cluster.

    Proposed list is consumed IN ORDER — earlier entries win ties.

    Args:
        proposed:        symbols the allocator wants to enter this cycle
        open_symbols:    symbols already held (any strategy)
        max_per_cluster: cap per cluster

    Returns:
        culled `proposed` list (subset, same order)
    """
    counts: dict[str, int] = {}
    for s in open_symbols:
        c = cluster_of(s)
        counts[c] = counts.get(c, 0) + 1

    allowed = []
    rejected_by_cluster = {}
    for sym in proposed:
        c = cluster_of(sym)
        if counts.get(c, 0) >= max_per_cluster:
            rejected_by_cluster[c] = rejected_by_cluster.get(c, []) + [sym]
            continue
        allowed.append(sym)
        counts[c] = counts.get(c, 0) + 1

    if rejected_by_cluster:
        log.info("[corr_guard] rejected by cluster cap: %s",
                 {c: syms for c, syms in rejected_by_cluster.items()})
    if allowed:
        log.info("[corr_guard] allowed (post-cluster): %s  cluster_load=%s",
                 allowed,
                 {c: n for c, n in counts.items() if n > 0})
    return allowed


def filter_plan_by_clusters(
    plan: dict[str, list[str]],
    open_symbols: list[str],
    max_per_cluster: int = MAX_PER_CLUSTER,
) -> dict[str, list[str]]:
    """
    Apply cluster caps across an entire allocation plan (multi-strategy).
    Strategies are processed in dict iteration order; clusters count
    across strategies so the cap is global.
    """
    counts: dict[str, int] = {}
    for s in open_symbols:
        c = cluster_of(s)
        counts[c] = counts.get(c, 0) + 1

    out: dict[str, list[str]] = {}
    for strat, syms in plan.items():
        allowed = []
        for sym in syms:
            c = cluster_of(sym)
            if counts.get(c, 0) >= max_per_cluster:
                log.info("[corr_guard] %s skip %s (cluster %s already at cap)",
                         strat, sym, c)
                continue
            allowed.append(sym)
            counts[c] = counts.get(c, 0) + 1
        out[strat] = allowed
    return out
