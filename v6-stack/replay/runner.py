"""κ2 replay runner — drive v5 pipeline from tape; emit/diff trace.

Two modes:
  --mode=capture  --tape-source <db>  --out <baseline.jsonl>
  --mode=replay   --tape-source <db>  --against <baseline.jsonl>

Both modes operate offline, read-only on the v5 SQLite tape, with the
network + RNG locked down by `replay.injector`.

For κ2 §8.1 (skeleton) we trace OHLCV inputs only. Adding regime / signal /
feature_hash to the trace is a follow-up task once the skeleton's parity
loop is proven (κ2 §8.4 + later).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Workspace root must be on sys.path so v5 modules import cleanly during
# replay. The package dir is `v6-stack/replay/`; workspace = parents[2].
_HERE = Path(__file__).resolve()
_WORKSPACE = _HERE.parents[2]
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))
# Also expose the v6-stack/replay package itself (its parent must be on path).
_V6_STACK = _HERE.parents[1]
if str(_V6_STACK) not in sys.path:
    sys.path.insert(0, str(_V6_STACK))

from replay import injector                  # noqa: E402
from replay.tape import iterate_tape, get_tape_summary  # noqa: E402
from replay.tracer import Tracer             # noqa: E402
from replay.clock import set_now             # noqa: E402

LOG = logging.getLogger("replay.runner")


def _smoke_import_v5() -> None:
    """Force-import the v5 surface k2 exercises, with the injector active.

    If any of these modules performs a network call at import time, the
    injector raises immediately - louder than discovering it during the
    iteration loop. Extend the list as k2 surface grows (section 8.4+).
    """
    import markets.crypto.fetcher  # noqa: F401
    LOG.info("smoke-import: markets.crypto.fetcher loaded under injector OK")


def run(*, tape_source: str, out: str | None = None,
        against: str | None = None, max_bars: int | None = None) -> int:
    if (out is None) == (against is None):
        raise ValueError("pass exactly one of --out (capture) / --against (replay)")
    mode = "capture" if out else "replay"
    target = Path(out or against)

    # ---------- Pre-flight tape summary (read-only, before injector) ----------
    summary = get_tape_summary(tape_source)
    LOG.info("=" * 64)
    LOG.info("k2 pre-flight tape summary: %s", summary["db_path"])
    LOG.info("  row count            : %d", summary["row_count"])
    LOG.info("  distinct symbols (%d): %s",
             summary["symbol_count"], ", ".join(summary["symbols"]))
    LOG.info("  timeframes           : %s", ", ".join(summary["timeframes"]))
    LOG.info("  timestamp min        : %s", summary["time_min"])
    LOG.info("  timestamp max        : %s", summary["time_max"])
    LOG.info("  per-(symbol,timeframe) row distribution:")
    for row in summary["per_pair"]:
        LOG.info("    %-12s %-5s rows=%-8d [%s .. %s]",
                 row["symbol"], row["timeframe"], row["rows"],
                 row["time_min"], row["time_max"])
    LOG.info("=" * 64)

    if mode == "capture" and summary["row_count"] == 0:
        LOG.error("refusing to capture from empty tape")
        return 4

    # ---------- Injector active BEFORE any v5 import ----------
    with injector.install():
        _smoke_import_v5()
        tracer = Tracer(target, mode=mode)
        for i, bar in enumerate(iterate_tape(tape_source, limit=max_bars)):
            set_now(bar.timestamp)
            event = {
                "cycle": i + 1,
                "symbol": bar.symbol,
                "timeframe": bar.timeframe,
                "ts": bar.timestamp.isoformat(),
                # `repr()` for float → exact decimal round-trip.
                "ohlcv": [repr(bar.open), repr(bar.high), repr(bar.low),
                          repr(bar.close), repr(bar.volume)],
            }
            tracer.emit(event)
        result = tracer.close()

    if mode == "capture":
        LOG.info("captured %d events → %s (chain_sha256=%s)",
                 result["count"], target, result["chain_hash"])
        return 0

    diff = tracer.diff_result()
    if diff["mismatches"] == 0 and diff["count"] == diff["baseline_count"]:
        LOG.info("replay clean: %d events identical (chain_sha256=%s)",
                 diff["count"], diff["chain_hash"])
        return 0
    LOG.error(
        "replay diverged: events=%d baseline=%d mismatches=%d first_at=%s",
        diff["count"], diff["baseline_count"], diff["mismatches"], diff["first_at"],
    )
    return 3


def main() -> int:
    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description="κ2 replay runner (offline, deterministic)")
    p.add_argument("--mode", choices=["capture", "replay"], required=True)
    p.add_argument("--tape-source", required=True, help="path to v5 SQLite (data/crypto.db)")
    p.add_argument("--out", default=None, help="capture mode: write baseline here")
    p.add_argument("--against", default=None, help="replay mode: diff against this baseline")
    p.add_argument("--max-bars", type=int, default=None,
                   help="optional cap on rows iterated (smoke testing)")
    args = p.parse_args()
    return run(
        tape_source=args.tape_source,
        out=args.out, against=args.against,
        max_bars=args.max_bars,
    )


if __name__ == "__main__":
    sys.exit(main())
