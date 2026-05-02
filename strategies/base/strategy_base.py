"""
Base strategy class for all AAATS strategies.

All strategies inherit from StrategyBase and implement:
  - generate_signals(df, config) -> pd.DataFrame
  - Support for paper/shadow/research modes
  - Risk control integration
  - Performance tracking
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

import pandas as pd

from foundation.logger import get_logger

_log = get_logger("strategies", "base")


class StrategyMode(Enum):
    """Strategy execution modes."""
    PAPER = "paper"          # Paper trading (simulated execution)
    SHADOW = "shadow"        # Shadow mode (track signals but don't execute)
    RESEARCH = "research"    # Research mode (backtest only, no live signals)
    LIVE = "live"           # Live trading (real execution)


@dataclass
class StrategyConfig:
    """Base configuration for all strategies."""
    mode: StrategyMode = StrategyMode.PAPER
    enabled: bool = True
    max_position_size: float = 0.1  # 10% of portfolio max
    max_risk_per_trade: float = 0.02  # 2% risk per trade
    confidence_threshold: float = 0.6  # Minimum confidence to trade
    
    # Risk controls
    respect_regime_filter: bool = True
    respect_volatility_filter: bool = True
    respect_liquidity_filter: bool = True
    
    # Performance tracking
    track_performance: bool = True
    log_signals: bool = True


class StrategyBase(ABC):
    """
    Abstract base class for all trading strategies.
    
    All strategies must implement:
      - generate_signals(df, config) -> pd.DataFrame
    
    Strategies automatically get:
      - Mode management (paper/shadow/research/live)
      - Risk control integration
      - Performance tracking
      - Logging
    """
    
    def __init__(
        self,
        name: str,
        market: str,
        config: StrategyConfig | None = None,
    ):
        """
        Initialize strategy.
        
        Args:
            name: Strategy name (e.g., "momentum", "mean_reversion")
            market: Market identifier ("us", "india", "crypto")
            config: Strategy configuration (optional)
        """
        self.name = name
        self.market = market
        self.config = config or StrategyConfig()
        self._log = get_logger(f"strategy.{market}", name)
        
        self._log.info(
            f"Initialized {name} strategy for {market} market "
            f"(mode={self.config.mode.value})"
        )
    
    @abstractmethod
    def generate_signals(
        self,
        df: pd.DataFrame,
        config: Any | None = None,
    ) -> pd.DataFrame:
        """
        Generate trading signals from feature-engineered data.
        
        Args:
            df: DataFrame with OHLCV + features
            config: Strategy-specific configuration (optional)
        
        Returns:
            DataFrame with added columns:
              - signal: "BUY", "SELL", or "HOLD"
              - confidence: 0.0-1.0 (signal confidence)
              - stop_loss: Stop loss price (optional)
              - take_profit: Take profit price (optional)
        
        Raises:
            ValueError: If required columns are missing
        """
        pass
    
    def validate_dataframe(self, df: pd.DataFrame, required_cols: set[str]) -> None:
        """
        Validate that DataFrame has required columns.
        
        Args:
            df: DataFrame to validate
            required_cols: Set of required column names
        
        Raises:
            ValueError: If required columns are missing
        """
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(
                f"{self.name} strategy: missing required columns {sorted(missing)}"
            )
    
    def is_enabled(self) -> bool:
        """Check if strategy is enabled."""
        return self.config.enabled
    
    def get_mode(self) -> StrategyMode:
        """Get current strategy mode."""
        return self.config.mode
    
    def set_mode(self, mode: StrategyMode) -> None:
        """Set strategy mode."""
        self._log.info(f"Switching mode: {self.config.mode.value} → {mode.value}")
        self.config.mode = mode
    
    def should_execute(self, confidence: float) -> bool:
        """
        Check if signal should be executed based on confidence threshold.
        
        Args:
            confidence: Signal confidence (0.0-1.0)
        
        Returns:
            True if confidence >= threshold, False otherwise
        """
        return confidence >= self.config.confidence_threshold
    
    def apply_risk_filters(
        self,
        df: pd.DataFrame,
        regime: str | None = None,
        volatility: float | None = None,
    ) -> pd.DataFrame:
        """
        Apply risk filters to signals.
        
        Args:
            df: DataFrame with signals
            regime: Current market regime (optional)
            volatility: Current volatility level (optional)
        
        Returns:
            DataFrame with filtered signals
        """
        if not self.config.respect_regime_filter:
            return df
        
        # Filter signals based on regime
        if regime and "signal" in df.columns:
            # Example: Don't trade mean reversion in strong trends
            if "reversion" in self.name.lower() and regime in ["BULL", "BEAR"]:
                self._log.debug(f"Filtering signals due to {regime} regime")
                df = df.copy()
                df.loc[df["signal"].isin(["BUY", "SELL"]), "signal"] = "HOLD"
        
        # Filter signals based on volatility
        if volatility and self.config.respect_volatility_filter:
            if volatility > 0.5:  # High volatility threshold
                self._log.debug(f"Filtering signals due to high volatility ({volatility:.2f})")
                df = df.copy()
                df.loc[df["signal"].isin(["BUY", "SELL"]), "signal"] = "HOLD"
        
        return df
    
    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name={self.name}, "
            f"market={self.market}, "
            f"mode={self.config.mode.value})"
        )
