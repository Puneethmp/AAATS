# κ2 replay harness

Offline deterministic replay of v5.4's pipeline. Used to:

1. Generate a fixed **golden baseline** from the v5 SQLite tape.
2. Re-run the same pipeline and confirm a byte-identical trace ("v5 against v5").
3. (κ5) Run v6 against the same tape and diff against the baseline.

## Layout

```
v6-stack/replay/
├── __init__.py
├── tape.py                 SQLite read-only iterator over crypto_bars
├── clock.py                tape-driven virtual clock
├── injector.py             context manager: blocks network, seeds RNG
├── tracer.py               canonical JSONL writer + chain hash
├── runner.py               capture / replay entry point (CLI)
├── golden/                 captured baselines (committed)
│   └── baseline.jsonl      κ2 golden tape
└── tests/
    └── test_replay_baseline.py     pytest entry; skips cleanly if baseline absent
```

## Usage

```bash
# capture (one-shot; refuses to overwrite without --force)
bash v6-stack/scripts/k2_capture_baseline.sh

# diff replay (returns non-zero if any line differs)
python v6-stack/replay/runner.py \
    --mode=replay \
    --tape-source=data/crypto.db \
    --against=v6-stack/replay/golden/baseline.jsonl

# pytest
pytest v6-stack/replay/tests/ -v
```

## Properties

- **Read-only on `data/crypto.db`** (sqlite3 URI `mode=ro`). No mutations.
- **No network egress.** `requests.get/post` and `markets.crypto.fetcher.fetch_ohlcv` are patched to raise inside the replay context.
- **Seeded RNG.** `random.seed(42)` inside replay only; module state restored on context exit. v5 production paths are untouched.
- **Deterministic iteration.** Tape order = `(symbol ASC, timeframe ASC, timestamp ASC)`.
- **Canonical JSON.** `sort_keys=True`, `separators=(",", ":")`, floats via `repr()` for exact round-trip.

## What it does NOT do (yet)

The κ2 §8.1 skeleton emits OHLCV inputs only. Regime detection / feature
computation / signal output tracing comes after the framework's parity loop
is proven byte-clean (κ2 §8.4+). That's intentional — first prove the
framework can re-emit the same trace, then layer in v5 logic.

## Determinism risk catalogue

See `K2_REPLAY_NOTES.md` (workspace root). Updated as findings emerge.
