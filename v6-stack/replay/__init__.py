"""κ2 replay harness — offline deterministic replay of v5.4 pipeline.

Standalone package. Imports v5 modules read-only (via injector context).
NEVER imported by any v5 module. Used by:
  - scripts/k2_capture_baseline.sh   one-shot baseline capture
  - tests/test_replay_baseline.py    parity test (replay must match baseline)

Submodules:
  replay.tape        SQLite read-only tape iterator
  replay.clock       virtual clock (tape-driven, not wall clock)
  replay.injector    context manager: patches network + RNG; reverses on exit
  replay.tracer      canonical JSONL writer + chain hash
  replay.runner      pipeline driver (capture or replay mode)
"""

__all__ = ["tape", "clock", "injector", "tracer", "runner"]
