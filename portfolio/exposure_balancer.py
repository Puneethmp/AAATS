"""
Exposure Balancer

Balances portfolio exposure across strategies, markets, and sectors.

Features:
- Cross-strategy exposure tracking
- Market exposure limits
- Sector/asset class balancing
- Long/short exposure management
"""

from dataclasses import dataclass
from typing import Dict, List
from foundation.logger import logger


@dataclass
class ExposureMetrics:
    """Exposure metrics for portfolio"""
    total_long_exposure: float
    total_short_exposure: float
    net_exposure: float
    gross_exposure: float
    
    # Per-market exposure
    us_exposure: float
    india_exposure: float
    india_fo_exposure: float
    crypto_exposure: float
    
    # Exposure by strategy
    strategy_exposures: Dict[str, float]
    
    # Risk metrics
    leverage_ratio: float  # Gross exposure / capital
    is_balanced: bool
    warnings: List[str]


@dataclass
class BalancingAction:
    """Action to balance portfolio exposure"""
    strategy_id: str
    market: str
    current_exposure: float
    target_exposure: float
    action: str  # "reduce", "increase", "close"
    reason: str
    priority: int  # 1=high, 2=medium, 3=low


class ExposureBalancer:
    """
    Balances portfolio exposure across strategies and markets.
    
    Exposure limits:
    - Max gross exposure: 80% of capital
    - Max net exposure: 40% of capital
    - Max per-market exposure: 40% of capital
    - Max per-strategy exposure: 10% of capital
    """
    
    # Exposure limits
    MAX_GROSS_EXPOSURE = 0.80
    MAX_NET_EXPOSURE = 0.40
    MAX_MARKET_EXPOSURE = 0.40
    MAX_STRATEGY_EXPOSURE = 0.10
    
    # Balance thresholds
    IMBALANCE_THRESHOLD = 0.15  # 15% deviation triggers rebalancing
    
    def __init__(self, total_capital: float):
        """
        Initialize exposure balancer.
        
        Args:
            total_capital: Total portfolio capital
        """
        self.total_capital = total_capital
        self.current_exposures: Dict[str, float] = {}
        logger.info(
            "ExposureBalancer initialized",
            extra={"total_capital": total_capital}
        )
    
    def update_exposure(
        self,
        strategy_id: str,
        market: str,
        exposure: float,
        direction: str = "long"
    ):
        """
        Update exposure for a strategy.
        
        Args:
            strategy_id: Strategy identifier
            market: Market (us, india, india_fo, crypto)
            exposure: Exposure amount (positive for long, negative for short)
            direction: "long" or "short"
        """
        # Store with sign
        signed_exposure = exposure if direction == "long" else -exposure
        self.current_exposures[strategy_id] = {
            "market": market,
            "exposure": signed_exposure,
            "direction": direction
        }
        
        logger.debug(
            f"Exposure updated: {strategy_id}",
            extra={
                "strategy_id": strategy_id,
                "market": market,
                "exposure": exposure,
                "direction": direction
            }
        )
    
    def calculate_exposure_metrics(self) -> ExposureMetrics:
        """
        Calculate current portfolio exposure metrics.
        
        Returns:
            ExposureMetrics with current exposure breakdown
        """
        # Calculate total exposures
        total_long = sum(
            abs(data["exposure"]) for data in self.current_exposures.values()
            if data["exposure"] > 0
        )
        total_short = sum(
            abs(data["exposure"]) for data in self.current_exposures.values()
            if data["exposure"] < 0
        )
        net_exposure = total_long - total_short
        gross_exposure = total_long + total_short
        
        # Calculate per-market exposures
        market_exposures = {"us": 0.0, "india": 0.0, "india_fo": 0.0, "crypto": 0.0}
        for data in self.current_exposures.values():
            market = data["market"]
            if market in market_exposures:
                market_exposures[market] += abs(data["exposure"])
        
        # Strategy exposures
        strategy_exposures = {
            sid: abs(data["exposure"])
            for sid, data in self.current_exposures.items()
        }
        
        # Calculate leverage
        leverage_ratio = gross_exposure / self.total_capital if self.total_capital > 0 else 0
        
        # Check balance and generate warnings
        warnings = []
        is_balanced = True
        
        if gross_exposure > self.MAX_GROSS_EXPOSURE * self.total_capital:
            warnings.append(
                f"Gross exposure {gross_exposure:.0f} exceeds limit "
                f"{self.MAX_GROSS_EXPOSURE * self.total_capital:.0f}"
            )
            is_balanced = False
        
        if abs(net_exposure) > self.MAX_NET_EXPOSURE * self.total_capital:
            warnings.append(
                f"Net exposure {net_exposure:.0f} exceeds limit "
                f"{self.MAX_NET_EXPOSURE * self.total_capital:.0f}"
            )
            is_balanced = False
        
        for market, exposure in market_exposures.items():
            if exposure > self.MAX_MARKET_EXPOSURE * self.total_capital:
                warnings.append(
                    f"{market.upper()} exposure {exposure:.0f} exceeds limit "
                    f"{self.MAX_MARKET_EXPOSURE * self.total_capital:.0f}"
                )
                is_balanced = False
        
        for strategy_id, exposure in strategy_exposures.items():
            if exposure > self.MAX_STRATEGY_EXPOSURE * self.total_capital:
                warnings.append(
                    f"Strategy {strategy_id} exposure {exposure:.0f} exceeds limit "
                    f"{self.MAX_STRATEGY_EXPOSURE * self.total_capital:.0f}"
                )
                is_balanced = False
        
        metrics = ExposureMetrics(
            total_long_exposure=total_long,
            total_short_exposure=total_short,
            net_exposure=net_exposure,
            gross_exposure=gross_exposure,
            us_exposure=market_exposures["us"],
            india_exposure=market_exposures["india"],
            india_fo_exposure=market_exposures["india_fo"],
            crypto_exposure=market_exposures["crypto"],
            strategy_exposures=strategy_exposures,
            leverage_ratio=leverage_ratio,
            is_balanced=is_balanced,
            warnings=warnings
        )
        
        if not is_balanced:
            logger.warning(
                "Portfolio exposure imbalanced",
                extra={
                    "gross_exposure": gross_exposure,
                    "net_exposure": net_exposure,
                    "warnings": warnings
                }
            )
        
        return metrics
    
    def generate_balancing_actions(self) -> List[BalancingAction]:
        """
        Generate actions to rebalance portfolio exposure.
        
        Returns:
            List of BalancingAction objects prioritized by urgency
        """
        metrics = self.calculate_exposure_metrics()
        actions = []
        
        if metrics.is_balanced:
            logger.info("Portfolio exposure is balanced, no actions needed")
            return actions
        
        # Check gross exposure
        if metrics.gross_exposure > self.MAX_GROSS_EXPOSURE * self.total_capital:
            excess = metrics.gross_exposure - (self.MAX_GROSS_EXPOSURE * self.total_capital)
            actions.extend(
                self._reduce_gross_exposure(excess, metrics)
            )
        
        # Check net exposure
        if abs(metrics.net_exposure) > self.MAX_NET_EXPOSURE * self.total_capital:
            actions.extend(
                self._balance_net_exposure(metrics)
            )
        
        # Check per-market exposure
        for market in ["us", "india", "india_fo", "crypto"]:
            market_exposure = getattr(metrics, f"{market}_exposure")
            if market_exposure > self.MAX_MARKET_EXPOSURE * self.total_capital:
                excess = market_exposure - (self.MAX_MARKET_EXPOSURE * self.total_capital)
                actions.extend(
                    self._reduce_market_exposure(market, excess, metrics)
                )
        
        # Check per-strategy exposure
        for strategy_id, exposure in metrics.strategy_exposures.items():
            if exposure > self.MAX_STRATEGY_EXPOSURE * self.total_capital:
                excess = exposure - (self.MAX_STRATEGY_EXPOSURE * self.total_capital)
                action = BalancingAction(
                    strategy_id=strategy_id,
                    market=self.current_exposures[strategy_id]["market"],
                    current_exposure=exposure,
                    target_exposure=self.MAX_STRATEGY_EXPOSURE * self.total_capital,
                    action="reduce",
                    reason=f"Strategy exposure exceeds limit by {excess:.0f}",
                    priority=1
                )
                actions.append(action)
        
        # Sort by priority
        actions.sort(key=lambda x: x.priority)
        
        logger.info(
            f"Generated {len(actions)} balancing actions",
            extra={"num_actions": len(actions)}
        )
        
        return actions
    
    def _reduce_gross_exposure(
        self,
        excess: float,
        metrics: ExposureMetrics
    ) -> List[BalancingAction]:
        """Generate actions to reduce gross exposure"""
        actions = []
        
        # Reduce largest positions first
        sorted_strategies = sorted(
            metrics.strategy_exposures.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        remaining_excess = excess
        for strategy_id, exposure in sorted_strategies:
            if remaining_excess <= 0:
                break
            
            reduction = min(exposure * 0.3, remaining_excess)  # Reduce by 30% max
            target = exposure - reduction
            
            action = BalancingAction(
                strategy_id=strategy_id,
                market=self.current_exposures[strategy_id]["market"],
                current_exposure=exposure,
                target_exposure=target,
                action="reduce",
                reason=f"Reduce gross exposure by {reduction:.0f}",
                priority=1
            )
            actions.append(action)
            remaining_excess -= reduction
        
        return actions
    
    def _balance_net_exposure(self, metrics: ExposureMetrics) -> List[BalancingAction]:
        """Generate actions to balance net exposure"""
        actions = []
        
        if metrics.net_exposure > self.MAX_NET_EXPOSURE * self.total_capital:
            # Too long, reduce long positions or add shorts
            excess = metrics.net_exposure - (self.MAX_NET_EXPOSURE * self.total_capital)
            
            # Find largest long positions
            long_strategies = [
                (sid, data) for sid, data in self.current_exposures.items()
                if data["exposure"] > 0
            ]
            long_strategies.sort(key=lambda x: x[1]["exposure"], reverse=True)
            
            for strategy_id, data in long_strategies[:3]:  # Top 3 long positions
                reduction = min(data["exposure"] * 0.2, excess / 3)
                action = BalancingAction(
                    strategy_id=strategy_id,
                    market=data["market"],
                    current_exposure=data["exposure"],
                    target_exposure=data["exposure"] - reduction,
                    action="reduce",
                    reason="Reduce net long exposure",
                    priority=2
                )
                actions.append(action)
        
        elif metrics.net_exposure < -(self.MAX_NET_EXPOSURE * self.total_capital):
            # Too short, reduce short positions or add longs
            excess = abs(metrics.net_exposure) - (self.MAX_NET_EXPOSURE * self.total_capital)
            
            # Find largest short positions
            short_strategies = [
                (sid, data) for sid, data in self.current_exposures.items()
                if data["exposure"] < 0
            ]
            short_strategies.sort(key=lambda x: abs(x[1]["exposure"]), reverse=True)
            
            for strategy_id, data in short_strategies[:3]:  # Top 3 short positions
                reduction = min(abs(data["exposure"]) * 0.2, excess / 3)
                action = BalancingAction(
                    strategy_id=strategy_id,
                    market=data["market"],
                    current_exposure=abs(data["exposure"]),
                    target_exposure=abs(data["exposure"]) - reduction,
                    action="reduce",
                    reason="Reduce net short exposure",
                    priority=2
                )
                actions.append(action)
        
        return actions
    
    def _reduce_market_exposure(
        self,
        market: str,
        excess: float,
        metrics: ExposureMetrics
    ) -> List[BalancingAction]:
        """Generate actions to reduce market-specific exposure"""
        actions = []
        
        # Find strategies in this market
        market_strategies = [
            (sid, data) for sid, data in self.current_exposures.items()
            if data["market"] == market
        ]
        market_strategies.sort(key=lambda x: abs(x[1]["exposure"]), reverse=True)
        
        remaining_excess = excess
        for strategy_id, data in market_strategies:
            if remaining_excess <= 0:
                break
            
            reduction = min(abs(data["exposure"]) * 0.3, remaining_excess)
            target = abs(data["exposure"]) - reduction
            
            action = BalancingAction(
                strategy_id=strategy_id,
                market=market,
                current_exposure=abs(data["exposure"]),
                target_exposure=target,
                action="reduce",
                reason=f"Reduce {market.upper()} market exposure by {reduction:.0f}",
                priority=1
            )
            actions.append(action)
            remaining_excess -= reduction
        
        return actions
