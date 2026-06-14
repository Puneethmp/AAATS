"""
Decision layer — consensus voting.

Only `consensus_voting` is live (imported by trading/live_paper_runner.py).
The ensemble aggregator, confidence scorer, and meta-coordinator were removed
2026-06-13 as never-wired dead code (AUDIT/repo_audit_2026-06-13.md).
"""

from decision.consensus_voting import (
    ConsensusVoting,
    StrategyVote,
    ConsensusResult,
)

__all__ = [
    "ConsensusVoting",
    "StrategyVote",
    "ConsensusResult",
]
