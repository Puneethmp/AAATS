"""
State checkpoint and recovery system for AAATS.

Provides crash recovery by periodically saving trading state to disk.
Enables seamless restart after crashes or VM reboots.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from foundation.logger import get_logger

_log = get_logger("infrastructure", "state_checkpoint")


@dataclass
class TradingCheckpoint:
    """Checkpoint data for trading state."""
    market: str
    timestamp: str
    cycle_count: int
    capital: float
    positions: list[dict[str, Any]]
    total_pnl: float
    daily_pnl: float
    trade_count: int
    regime: str
    status: str
    metadata: dict[str, Any]


class StateCheckpoint:
    """
    Manages state checkpointing for crash recovery.
    
    Usage:
        checkpoint = StateCheckpoint("us", checkpoint_dir="data/checkpoints")
        
        # Save state periodically
        checkpoint.save(
            cycle_count=100,
            capital=10000.0,
            positions=[{"symbol": "AAPL", "shares": 10, "entry_price": 150.0}],
            total_pnl=250.0,
            daily_pnl=50.0,
            trade_count=5,
            regime="TRENDING_UP",
            status="RUNNING",
        )
        
        # Restore after crash
        state = checkpoint.restore()
        if state:
            print(f"Restored from cycle {state.cycle_count}")
    """
    
    def __init__(
        self,
        market: str,
        checkpoint_dir: Optional[Path] = None,
        max_checkpoints: int = 10,
    ):
        """
        Initialize state checkpoint manager.
        
        Args:
            market: Market identifier (us, india, crypto)
            checkpoint_dir: Directory for checkpoint files (default: data/checkpoints)
            max_checkpoints: Maximum number of checkpoints to keep
        """
        self.market = market
        self.checkpoint_dir = checkpoint_dir or Path("data/checkpoints")
        self.max_checkpoints = max_checkpoints
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    
    def save(
        self,
        cycle_count: int,
        capital: float,
        positions: list[dict[str, Any]],
        total_pnl: float,
        daily_pnl: float,
        trade_count: int,
        regime: str,
        status: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        """
        Save current trading state to checkpoint.
        
        Args:
            cycle_count: Current cycle number
            capital: Current cash balance
            positions: List of open positions
            total_pnl: Total realized PnL
            daily_pnl: Today's PnL
            trade_count: Total number of trades
            regime: Current market regime
            status: Current status (RUNNING, IDLE, etc.)
            metadata: Additional metadata to save
        
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            checkpoint = TradingCheckpoint(
                market=self.market,
                timestamp=datetime.now(timezone.utc).isoformat(),
                cycle_count=cycle_count,
                capital=capital,
                positions=positions,
                total_pnl=total_pnl,
                daily_pnl=daily_pnl,
                trade_count=trade_count,
                regime=regime,
                status=status,
                metadata=metadata or {},
            )
            
            # Save to timestamped file
            filename = f"{self.market}_{cycle_count}_{int(datetime.now().timestamp())}.json"
            filepath = self.checkpoint_dir / filename
            
            filepath.write_text(json.dumps(asdict(checkpoint), indent=2))
            
            # Also save as "latest" for easy recovery
            latest_path = self.checkpoint_dir / f"{self.market}_latest.json"
            latest_path.write_text(json.dumps(asdict(checkpoint), indent=2))
            
            _log.debug(f"Checkpoint saved: {filename}")
            
            # Clean up old checkpoints
            self._cleanup_old_checkpoints()
            
            return True
        
        except Exception as exc:
            _log.error(f"Failed to save checkpoint: {exc}")
            return False
    
    def restore(self) -> Optional[TradingCheckpoint]:
        """
        Restore trading state from latest checkpoint.
        
        Returns:
            TradingCheckpoint if found, None otherwise
        """
        latest_path = self.checkpoint_dir / f"{self.market}_latest.json"
        
        if not latest_path.exists():
            _log.info(f"No checkpoint found for {self.market}")
            return None
        
        try:
            data = json.loads(latest_path.read_text())
            checkpoint = TradingCheckpoint(**data)
            
            _log.info(
                f"Restored checkpoint: cycle={checkpoint.cycle_count}, "
                f"capital={checkpoint.capital:.2f}, "
                f"positions={len(checkpoint.positions)}"
            )
            
            return checkpoint
        
        except Exception as exc:
            _log.error(f"Failed to restore checkpoint: {exc}")
            return None
    
    def list_checkpoints(self) -> list[Path]:
        """
        List all checkpoint files for this market.
        
        Returns:
            List of checkpoint file paths, sorted by timestamp (newest first)
        """
        pattern = f"{self.market}_*.json"
        checkpoints = sorted(
            self.checkpoint_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        
        # Exclude "latest" file
        return [p for p in checkpoints if not p.name.endswith("_latest.json")]
    
    def restore_from_file(self, filepath: Path) -> Optional[TradingCheckpoint]:
        """
        Restore from a specific checkpoint file.
        
        Args:
            filepath: Path to checkpoint file
        
        Returns:
            TradingCheckpoint if successful, None otherwise
        """
        try:
            data = json.loads(filepath.read_text())
            checkpoint = TradingCheckpoint(**data)
            _log.info(f"Restored from {filepath.name}")
            return checkpoint
        
        except Exception as exc:
            _log.error(f"Failed to restore from {filepath}: {exc}")
            return None
    
    def _cleanup_old_checkpoints(self) -> None:
        """Remove old checkpoint files beyond max_checkpoints limit."""
        checkpoints = self.list_checkpoints()
        
        if len(checkpoints) > self.max_checkpoints:
            for old_checkpoint in checkpoints[self.max_checkpoints:]:
                try:
                    old_checkpoint.unlink()
                    _log.debug(f"Removed old checkpoint: {old_checkpoint.name}")
                except Exception as exc:
                    _log.error(f"Failed to remove old checkpoint: {exc}")


def auto_checkpoint_wrapper(
    checkpoint: StateCheckpoint,
    checkpoint_interval: int = 10,
):
    """
    Decorator to automatically checkpoint state every N cycles.
    
    Usage:
        checkpoint = StateCheckpoint("us")
        
        @auto_checkpoint_wrapper(checkpoint, checkpoint_interval=10)
        def trading_cycle(state):
            # ... trading logic ...
            return state
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            
            # Extract state from result if it's a dict
            if isinstance(result, dict):
                cycle_count = result.get("cycle_count", 0)
                
                # Checkpoint every N cycles
                if cycle_count % checkpoint_interval == 0:
                    checkpoint.save(
                        cycle_count=result.get("cycle_count", 0),
                        capital=result.get("capital", 0.0),
                        positions=result.get("positions", []),
                        total_pnl=result.get("total_pnl", 0.0),
                        daily_pnl=result.get("daily_pnl", 0.0),
                        trade_count=result.get("trade_count", 0),
                        regime=result.get("regime", "UNKNOWN"),
                        status=result.get("status", "RUNNING"),
                        metadata=result.get("metadata", {}),
                    )
            
            return result
        
        return wrapper
    return decorator
