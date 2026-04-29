"""
Strategy Registry.

Central lookup table mapping (market, strategy_name) to signal-generation callables.
All registered strategies share the same interface:
  generate_signals(df, config=None) -> pd.DataFrame

Usage:
    from strategies.registry import get_strategy, list_strategies
    fn = get_strategy("us", "momentum")
    result = fn(features_df)
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from foundation.logger import get_logger

_log = get_logger("system", "strategy_registry")

# Type alias for strategy callables
SignalFn = Callable[..., pd.DataFrame]

_REGISTRY: dict[tuple[str, str], SignalFn] = {}


def register(market: str, name: str) -> Callable[[SignalFn], SignalFn]:
    """Decorator that registers a generate_signals function."""
    def decorator(fn: SignalFn) -> SignalFn:
        key = (market.lower(), name.lower())
        if key in _REGISTRY:
            _log.warning(f"Overwriting existing strategy: market={market}, name={name}")
        _REGISTRY[key] = fn
        _log.info(f"Registered strategy: market={market}, name={name}")
        return fn
    return decorator


def get_strategy(market: str, name: str) -> SignalFn:
    """
    Retrieve a registered strategy by market and name.

    Args:
        market: "us", "india", or "crypto"
        name:   Strategy name (e.g. "momentum", "mean_reversion", "grid_trading")

    Returns:
        The generate_signals callable for the requested strategy.

    Raises:
        KeyError: If no strategy is registered for (market, name).
    """
    key = (market.lower(), name.lower())
    if key not in _REGISTRY:
        available = [f"{m}/{n}" for m, n in sorted(_REGISTRY)]
        raise KeyError(
            f"No strategy registered for market='{market}', name='{name}'. "
            f"Available: {available}"
        )
    return _REGISTRY[key]


def list_strategies() -> list[dict[str, str]]:
    """Return all registered strategies as a list of {market, name} dicts."""
    return [{"market": m, "name": n} for m, n in sorted(_REGISTRY)]


def _register_all() -> None:
    """Auto-register all built-in strategies at import time."""
    from strategies.us.momentum import generate_signals as us_momentum
    from strategies.us.mean_reversion import generate_signals as us_mean_rev
    from strategies.india.momentum import generate_signals as india_momentum
    from strategies.india.regime_shift import detect_regime as india_regime
    from strategies.crypto.grid_trading import generate_signals as crypto_grid

    _REGISTRY[("us", "momentum")] = us_momentum
    _REGISTRY[("us", "mean_reversion")] = us_mean_rev
    _REGISTRY[("india", "momentum")] = india_momentum
    _REGISTRY[("india", "regime_shift")] = india_regime
    _REGISTRY[("crypto", "grid_trading")] = crypto_grid


_register_all()
