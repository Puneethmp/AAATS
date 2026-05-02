"""
Strategy-level risk controls.

Provides per-strategy risk limits and validation.
"""

from __future__ import annotations

from dataclasses import dataclass

from foundation.logger import get_logger

_log = get_logger("strategies", "risk_controls")


@dataclass
class StrategyRiskLimits:
    """Risk limits for a single strategy."""
    
    # Position limits
    max_position_size: float = 0.1  # 10% of portfolio max
    max_positions: int = 5  # Max concurrent positions
    
    # Risk limits
    max_risk_per_trade: float = 0.02  # 2% risk per trade
    max_daily_loss: float = 0.05  # 5% max daily loss
    max_drawdown: float = 0.15  # 15% max drawdown
    
    # Exposure limits
    max_leverage: float = 1.0  # No leverage by default
    max_correlation: float = 0.7  # Max correlation with other positions
    
    # Frequency limits
    max_trades_per_day: int = 10
    max_trades_per_hour: int = 3
    min_time_between_trades_sec: int = 60  # 1 minute


class StrategyRiskControls:
    """
    Per-strategy risk control validator.
    
    Validates that strategy signals respect risk limits.
    """
    
    def __init__(self, limits: StrategyRiskLimits | None = None):
        """
        Initialize risk controls.
        
        Args:
            limits: Risk limits (uses defaults if None)
        """
        self.limits = limits or StrategyRiskLimits()
        self._log = _log
    
    def validate_position_size(
        self,
        position_size: float,
        portfolio_value: float,
    ) -> tuple[bool, str]:
        """
        Validate position size against limits.
        
        Args:
            position_size: Proposed position size (in dollars)
            portfolio_value: Current portfolio value
        
        Returns:
            Tuple of (is_valid, reason)
        """
        position_pct = position_size / portfolio_value
        
        if position_pct > self.limits.max_position_size:
            return False, (
                f"Position size {position_pct:.1%} exceeds limit "
                f"{self.limits.max_position_size:.1%}"
            )
        
        return True, "Position size OK"
    
    def validate_risk_per_trade(
        self,
        entry_price: float,
        stop_loss: float,
        position_size: float,
        portfolio_value: float,
    ) -> tuple[bool, str]:
        """
        Validate risk per trade.
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            position_size: Position size (in dollars)
            portfolio_value: Current portfolio value
        
        Returns:
            Tuple of (is_valid, reason)
        """
        # Calculate risk
        price_risk = abs(entry_price - stop_loss) / entry_price
        dollar_risk = position_size * price_risk
        portfolio_risk = dollar_risk / portfolio_value
        
        if portfolio_risk > self.limits.max_risk_per_trade:
            return False, (
                f"Risk per trade {portfolio_risk:.1%} exceeds limit "
                f"{self.limits.max_risk_per_trade:.1%}"
            )
        
        return True, "Risk per trade OK"
    
    def validate_daily_loss(
        self,
        daily_pnl: float,
        portfolio_value: float,
    ) -> tuple[bool, str]:
        """
        Validate daily loss limit.
        
        Args:
            daily_pnl: Today's PnL (negative for loss)
            portfolio_value: Current portfolio value
        
        Returns:
            Tuple of (is_valid, reason)
        """
        if daily_pnl >= 0:
            return True, "No daily loss"
        
        daily_loss_pct = abs(daily_pnl) / portfolio_value
        
        if daily_loss_pct > self.limits.max_daily_loss:
            return False, (
                f"Daily loss {daily_loss_pct:.1%} exceeds limit "
                f"{self.limits.max_daily_loss:.1%}"
            )
        
        return True, "Daily loss within limit"
    
    def validate_drawdown(
        self,
        current_value: float,
        peak_value: float,
    ) -> tuple[bool, str]:
        """
        Validate drawdown limit.
        
        Args:
            current_value: Current portfolio value
            peak_value: Peak portfolio value
        
        Returns:
            Tuple of (is_valid, reason)
        """
        if current_value >= peak_value:
            return True, "No drawdown"
        
        drawdown = (peak_value - current_value) / peak_value
        
        if drawdown > self.limits.max_drawdown:
            return False, (
                f"Drawdown {drawdown:.1%} exceeds limit "
                f"{self.limits.max_drawdown:.1%}"
            )
        
        return True, "Drawdown within limit"
    
    def validate_trade_frequency(
        self,
        trades_today: int,
        trades_this_hour: int,
        seconds_since_last_trade: int,
    ) -> tuple[bool, str]:
        """
        Validate trade frequency limits.
        
        Args:
            trades_today: Number of trades today
            trades_this_hour: Number of trades this hour
            seconds_since_last_trade: Seconds since last trade
        
        Returns:
            Tuple of (is_valid, reason)
        """
        # Check daily limit
        if trades_today >= self.limits.max_trades_per_day:
            return False, (
                f"Daily trade limit reached: {trades_today} >= "
                f"{self.limits.max_trades_per_day}"
            )
        
        # Check hourly limit
        if trades_this_hour >= self.limits.max_trades_per_hour:
            return False, (
                f"Hourly trade limit reached: {trades_this_hour} >= "
                f"{self.limits.max_trades_per_hour}"
            )
        
        # Check minimum time between trades
        if seconds_since_last_trade < self.limits.min_time_between_trades_sec:
            return False, (
                f"Too soon since last trade: {seconds_since_last_trade}s < "
                f"{self.limits.min_time_between_trades_sec}s"
            )
        
        return True, "Trade frequency OK"
    
    def validate_all(
        self,
        position_size: float,
        entry_price: float,
        stop_loss: float,
        portfolio_value: float,
        peak_value: float,
        daily_pnl: float,
        trades_today: int,
        trades_this_hour: int,
        seconds_since_last_trade: int,
    ) -> tuple[bool, list[str]]:
        """
        Validate all risk controls.
        
        Returns:
            Tuple of (all_valid, list_of_violations)
        """
        violations = []
        
        # Position size
        valid, reason = self.validate_position_size(position_size, portfolio_value)
        if not valid:
            violations.append(reason)
        
        # Risk per trade
        valid, reason = self.validate_risk_per_trade(
            entry_price, stop_loss, position_size, portfolio_value
        )
        if not valid:
            violations.append(reason)
        
        # Daily loss
        valid, reason = self.validate_daily_loss(daily_pnl, portfolio_value)
        if not valid:
            violations.append(reason)
        
        # Drawdown
        valid, reason = self.validate_drawdown(portfolio_value, peak_value)
        if not valid:
            violations.append(reason)
        
        # Trade frequency
        valid, reason = self.validate_trade_frequency(
            trades_today, trades_this_hour, seconds_since_last_trade
        )
        if not valid:
            violations.append(reason)
        
        return len(violations) == 0, violations


# Global singleton
_risk_controls = StrategyRiskControls()


def validate_all(
    position_size: float,
    entry_price: float,
    stop_loss: float,
    portfolio_value: float,
    peak_value: float,
    daily_pnl: float,
    trades_today: int,
    trades_this_hour: int,
    seconds_since_last_trade: int,
) -> tuple[bool, list[str]]:
    """Convenience function using global risk controls."""
    return _risk_controls.validate_all(
        position_size,
        entry_price,
        stop_loss,
        portfolio_value,
        peak_value,
        daily_pnl,
        trades_today,
        trades_this_hour,
        seconds_since_last_trade,
    )
