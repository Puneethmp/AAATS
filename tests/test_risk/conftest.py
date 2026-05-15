"""
tests/test_risk/conftest.py — isolate the risk-engine STATE_FILE per test.

Without this, the persisted drawdown peak from one test leaks into the next
(and onto the developer machine's disk). Every test in this directory gets
a fresh tmp_path-scoped STATE_FILE.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import risk.engine as risk_engine_module


@pytest.fixture(autouse=True)
def _isolate_risk_state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        risk_engine_module,
        "STATE_FILE",
        tmp_path / "risk_engine_state.json",
    )
