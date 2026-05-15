"""
config/doctrine.py — Cross-module constants that anchor risk and capital math.

These values are deliberately doctrinal: they should not be inferred from
runtime state (which can drift after restarts, position-state corruption,
or partial fills). Anything imported from here is treated as ground truth
by the risk engine, the reconciler, and the live paper runner.
"""

from __future__ import annotations

# Locked starting equity for the paper-trading account.
# The risk engine seeds its drawdown peak with this value when no persisted
# peak exists on disk. Do NOT recompute from sum(positions) — when positions
# get reset or a fresh state file is written, that derivation collapses
# the peak to current cash and silently masks live drawdown.
LOCKED_STARTING_EQUITY: float = 110.0
