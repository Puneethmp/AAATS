"""Pytest entry: replay v5 against captured golden baseline; expect 0 diffs.

Skips cleanly if either the tape (`data/crypto.db`) or the baseline
(`v6-stack/replay/golden/baseline.jsonl`) is absent — which keeps κ2's CI
runnable in environments that haven't captured yet.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


_WORKSPACE = Path(__file__).resolve().parents[3]
_TAPE = _WORKSPACE / "data" / "crypto.db"
_BASELINE = Path(__file__).resolve().parents[1] / "golden" / "baseline.jsonl"
_RUNNER = _WORKSPACE / "v6-stack" / "replay" / "runner.py"


@pytest.mark.skipif(not _TAPE.is_file(),     reason="data/crypto.db not present")
@pytest.mark.skipif(not _BASELINE.is_file(), reason="baseline not yet captured")
def test_replay_matches_baseline():
    cmd = [
        sys.executable, str(_RUNNER),
        "--mode=replay",
        f"--tape-source={_TAPE}",
        f"--against={_BASELINE}",
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(_WORKSPACE), timeout=120,
    )
    assert proc.returncode == 0, (
        f"replay non-zero exit: rc={proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}\n"
    )
