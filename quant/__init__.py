"""quant — next-generation AAATS research & trading framework.

This package is the "factory": a thin, standard set of contracts that wrap the
crown-jewel validation harness (tools/nautilus/* + tools/graduation/gate.py) so
that adding a new strategy candidate is a ~100-line module instead of a fork of
the live runner.

Design rules (from the 2026-06-14 next-gen architecture review):
  - Strategies are THIN: a strategy produces a *scores panel* and declares its
    construction intent (metadata). It owns no DB, no fees, no execution.
  - The framework owns ALL boilerplate: ranking->weights, neutrality,
    vol-targeting, cost/fill models, walk-forward, null control, the gate.
  - Lifecycle is explicit metadata + a registry, never folders-by-hand.
  - Nothing here imports or mutates the live trading path. The running paper
    bot is untouched by this package.

Status: SKELETON (2026-06-14). The dollar-neutral / taker defaults are runnable
and reproduce the T2-class construction. B1's risk-managed constructor and maker
fill model are the next increment (see candidates/ and README.md).
"""

__all__ = ["base"]
__version__ = "0.1.0-skeleton"
