"""κ2 tracer — canonical JSONL writer with chain hash.

Capture mode  → write one canonical JSON line per event + accumulate sha256.
Replay  mode  → read baseline file; for each emitted event compare line-for-line.

Canonical JSON form: `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=True`,
floats serialised by callers via `repr()` for round-trip precision.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class Tracer:
    def __init__(self, path: Path | str, *, mode: str):
        if mode not in ("capture", "replay"):
            raise ValueError(f"mode must be 'capture' or 'replay', got {mode!r}")
        self.path = Path(path)
        self.mode = mode
        self.count = 0
        self.chain = hashlib.sha256()
        self._fh = None
        self._baseline: list[str] | None = None
        self._mismatches = 0
        self._first_at: int | None = None

        if mode == "capture":
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.path.open("w", encoding="utf-8", newline="\n", buffering=1)
        else:
            if not self.path.is_file():
                raise FileNotFoundError(f"replay baseline not found: {self.path}")
            with self.path.open("r", encoding="utf-8") as f:
                self._baseline = [line.rstrip("\n") for line in f]

    def emit(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True)
        self.chain.update(line.encode("utf-8"))
        self.chain.update(b"\n")
        if self.mode == "capture":
            assert self._fh is not None
            self._fh.write(line + "\n")
        else:
            assert self._baseline is not None
            if self.count >= len(self._baseline):
                self._record_mismatch()
            elif self._baseline[self.count] != line:
                self._record_mismatch()
        self.count += 1

    def _record_mismatch(self) -> None:
        if self._first_at is None:
            self._first_at = self.count + 1
        self._mismatches += 1

    def close(self) -> dict:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        return {"count": self.count, "chain_hash": self.chain.hexdigest()}

    def diff_result(self) -> dict:
        # Also flag if baseline has extra rows the replay didn't reach.
        baseline_len = len(self._baseline) if self._baseline is not None else 0
        if self._baseline is not None and self.count < baseline_len:
            self._mismatches += baseline_len - self.count
            if self._first_at is None:
                self._first_at = self.count + 1
        return {
            "count": self.count,
            "baseline_count": baseline_len,
            "mismatches": self._mismatches,
            "first_at": self._first_at,
            "chain_hash": self.chain.hexdigest(