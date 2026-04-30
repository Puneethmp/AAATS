"""
Correlation monitor for AAATS.

Ensures portfolio positions are not over-correlated (avoids hidden concentration risk).
Blocks new positions when pairwise correlation with existing holdings exceeds threshold.

Usage:
    from risk.correlation_monitor import CorrelationMonitor
    cm = CorrelationMonitor(max_correlation=0.85)
    ok = cm.check_correlation("ETH/USDT", existing_symbols=["BTC/USDT"], prices_df=df)
"""

from __future__ import annotations

from foundation.logger import get_logger

_log = get_logger("risk", "correlation_monitor")


class CorrelationMonitor:
    """
    Monitors pairwise correlation between new and existing positions.
    Uses price returns to compute rolling correlation.

    Args:
        max_correlation: Maximum allowed pairwise Pearson correlation (default 0.85).
        lookback: Number of periods to compute correlation over (default 20).
    """

    def __init__(self, max_correlation: float = 0.85, lookback: int = 20) -> None:
        self._max_corr = max_correlation
        self._lookback = lookback
        self._returns_cache: dict[str, list[float]] = {}

    def update_prices(self, symbol: str, prices: list[float]) -> None:
        """Update rolling price history for a symbol."""
        if len(prices) < 2:
            return
        returns = [(prices[i] / prices[i - 1]) - 1.0 for i in range(1, len(prices))]
        self._returns_cache[symbol] = returns[-self._lookback:]

    def check_correlation(
        self,
        new_symbol: str,
        existing_symbols: list[str],
    ) -> tuple[bool, str]:
        """
        Check if adding new_symbol would create over-correlation with existing positions.
        Returns (True, "OK") or (False, reason).
        """
        if new_symbol not in self._returns_cache:
            return True, "OK (no data)"

        new_ret = self._returns_cache[new_symbol]
        for existing in existing_symbols:
            if existing not in self._returns_cache or existing == new_symbol:
                continue
            ex_ret = self._returns_cache[existing]
            corr = self._pearson(new_ret, ex_ret)
            if corr is not None and corr > self._max_corr:
                reason = (
                    f"{new_symbol} corr with {existing}: {corr:.2f} > {self._max_corr:.2f} — skipping"
                )
                _log.warning(f"CORRELATION BLOCKED: {reason}")
                return False, reason
        return True, "OK"

    @staticmethod
    def _pearson(x: list[float], y: list[float]) -> float | None:
        n = min(len(x), len(y))
        if n < 5:
            return None
        x, y = x[-n:], y[-n:]
        mx = sum(x) / n
        my = sum(y) / n
        num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
        dx = sum((xi - mx) ** 2 for xi in x) ** 0.5
        dy = sum((yi - my) ** 2 for yi in y) ** 0.5
        if dx * dy == 0:
            return None
        return num / (dx * dy)
