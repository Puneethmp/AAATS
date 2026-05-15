"""
Verification suite for the 2026-05-13 AAATS fix pack (v2).
Smoke test only - does not touch the live bot.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running from either workspace mount or repo root.
for candidate in ("/sessions/compassionate-cool-johnson/mnt/Puneeth", "."):
    p = Path(candidate)
    if (p / "markets").is_dir():
        sys.path.insert(0, str(p.resolve()))
        break

PASS = "[PASS]"
FAIL = "[FAIL]"
fail_count = 0


def check(label, condition, detail=""):
    global fail_count
    tag = PASS if condition else FAIL
    if not condition:
        fail_count += 1
    suffix = "  (" + detail + ")" if detail else ""
    print("  " + tag + " " + label + suffix)


def test_universe_imports():
    print("\n# 1. Universe module imports cleanly")
    try:
        from markets.crypto import universe
        check("import universe", True)
        check("_DENY_LIST present",
              hasattr(universe, "_DENY_LIST"),
              "size=" + str(len(universe._DENY_LIST)))
        check("FALLBACK_UNIVERSE present",
              len(universe.FALLBACK_UNIVERSE) > 0,
              "count=" + str(len(universe.FALLBACK_UNIVERSE)))
        check("MAX_24H_DROP_PCT defined",
              hasattr(universe, "MAX_24H_DROP_PCT"),
              "val=" + str(universe.MAX_24H_DROP_PCT))
    except Exception as e:
        check("import universe failed: " + str(e), False)


def test_denylist():
    print("\n# 2. Deny-list rejects yesterday's report symbols")
    from markets.crypto.universe import _is_denied
    for bad in ["LUNC", "PENGU", "PEPE", "SHIB", "FLOKI", "WIF", "BONK"]:
        check("_is_denied(" + bad + ")", _is_denied(bad))
    for good in ["SOL", "LINK", "AVAX", "ARB", "OP", "MATIC", "NEAR", "ATOM"]:
        check("_is_denied(" + good + ") = False", not _is_denied(good))


def test_passes_filters():
    print("\n# 3. _passes_filters rejects bad tickers")
    from markets.crypto.universe import _passes_filters
    good = {"last": 100.0, "bid": 99.95, "ask": 100.05,
            "quoteVolume": 10_000_000, "percentage": 0.02}
    crash = {"last": 100.0, "bid": 99.95, "ask": 100.05,
             "quoteVolume": 10_000_000, "percentage": -0.25}
    pump = {"last": 100.0, "bid": 99.95, "ask": 100.05,
            "quoteVolume": 10_000_000, "percentage": 0.80}

    ok, reason = _passes_filters("SOL/USDT", good)
    check("SOL/USDT (good) passes", ok, "reason=" + reason)

    ok, reason = _passes_filters("LUNC/USDT", good)
    check("LUNC/USDT denied even with good metrics", not ok, "reason=" + reason)

    ok, reason = _passes_filters("FOO/USDT", crash)
    check("crashing token rejected -25pct", not ok, "reason=" + reason)

    ok, reason = _passes_filters("FOO/USDT", pump)
    check("pumping token rejected +80pct", not ok, "reason=" + reason)


def test_c3_imports():
    print("\n# 4. C3 strategy v2 constants present")
    try:
        from trading import altcoin_reversion as ar
        check("import altcoin_reversion", True)
        check("SIZING_MODE=FIXED", ar.SIZING_MODE == "FIXED")
        check("POSITION_USD=10 (base)", ar.POSITION_USD == 10.0)
        check("VOL_REF=0.04", ar.VOL_REF == 0.04)
        check("MIN_SIZE_SCALE=0.5", ar.MIN_SIZE_SCALE == 0.5)
        check("MAX_SIZE_SCALE=1.5", ar.MAX_SIZE_SCALE == 1.5)
        check("Z_TARGET=0.5 (overshoot catch)", ar.Z_TARGET == 0.5)
        check("Z_TRAILING_MIN=-0.3", ar.Z_TRAILING_MIN == -0.3)
        check("Z_TRAILING_DROP=0.4", ar.Z_TRAILING_DROP == 0.4)
        check("COOLDOWN_HOURS=24", ar.COOLDOWN_HOURS == 24)
        check("MAX_CONCURRENT=11", ar.MAX_CONCURRENT == 11)
    except Exception as e:
        check("c3 import failed: " + str(e), False)


def test_cooldown_helpers():
    print("\n# 5. Cooldown helpers work")
    from trading import altcoin_reversion as ar
    cooldown = {}
    ar._set_cooldown("LUNC/USDT", cooldown, hours=24)
    cooling, hrs = ar._is_cooling_down("LUNC/USDT", cooldown)
    check("set + check returns True", cooling, "hrs=" + str(round(hrs, 1)))
    check("cooldown hours approx 24", abs(hrs - 24) < 0.1)
    cooling2, _ = ar._is_cooling_down("SOL/USDT", cooldown)
    check("untouched symbol not in cooldown", not cooling2)


def test_vol_adjusted_sizing():
    print("\n# 6. Vol-adjusted sizing math")
    from trading import altcoin_reversion as ar

    # None vol -> falls back to base $10
    size, reason = ar._compute_trade_size(110.0, 0, symbol_vol=None)
    check("vol=None -> base $10", size == 10.0, "got=" + str(size))

    # Reference vol (4%) -> $10 unscaled
    size, reason = ar._compute_trade_size(110.0, 0, symbol_vol=0.04)
    check("vol=4pct (ref) -> $10", abs(size - 10.0) < 0.01, "got=" + str(size))

    # High vol (8%) -> scale 0.5 clamp -> $5
    size, reason = ar._compute_trade_size(110.0, 0, symbol_vol=0.08)
    check("vol=8pct (high) -> $5 floor", abs(size - 5.0) < 0.01, "got=" + str(size))

    # Low vol (2%) -> scale 2.0 clamped to 1.5x -> $15
    size, reason = ar._compute_trade_size(110.0, 0, symbol_vol=0.02)
    check("vol=2pct (low) -> $15 ceiling", abs(size - 15.0) < 0.01, "got=" + str(size))

    # Mid-high vol (5%) -> 0.04/0.05 = 0.8 -> $8
    size, reason = ar._compute_trade_size(110.0, 0, symbol_vol=0.05)
    check("vol=5pct -> $8", abs(size - 8.0) < 0.01, "got=" + str(size))

    # Mid-low vol (3%) -> 0.04/0.03 = 1.333 -> $13.33
    size, reason = ar._compute_trade_size(110.0, 0, symbol_vol=0.03)
    check("vol=3pct -> approx $13.33", abs(size - 13.33) < 0.05, "got=" + str(size))

    # Concurrent cap still works
    size, reason = ar._compute_trade_size(110.0, 11, symbol_vol=0.04)
    check("11 open -> REFUSE", size == 0.0, "reason=" + reason)

    # Insufficient capital still rejected
    size, reason = ar._compute_trade_size(4.0, 0, symbol_vol=0.04)
    check("$4 cap -> REFUSE", size == 0.0, "reason=" + reason)


def test_trailing_exit():
    print("\n# 7. Trailing-exit logic")
    from trading import altcoin_reversion as ar
    from datetime import datetime, timedelta, timezone

    fresh_ts = datetime.now(timezone.utc).isoformat()

    # Fresh entry, max=current=-1.6 -> no exit
    pos = {"entry_ts": fresh_ts, "entry_z": -1.6, "max_z": -1.6}
    exit_now, reason = ar._should_exit(pos, current_z=-1.6)
    check("fresh entry -> no exit", not exit_now, "reason=" + reason)

    # Trailing not armed (max_z=-0.8 < Z_TRAILING_MIN=-0.3)
    pos = {"entry_ts": fresh_ts, "entry_z": -1.6, "max_z": -0.8}
    exit_now, reason = ar._should_exit(pos, current_z=-1.6)
    check("max_z=-0.8 (below arm) -> no exit", not exit_now, "reason=" + reason)

    # Trailing armed (max_z=-0.2) but drop only 0.2 < 0.4 -> no exit
    pos = {"entry_ts": fresh_ts, "entry_z": -1.6, "max_z": -0.2}
    exit_now, reason = ar._should_exit(pos, current_z=-0.4)
    check("max_z=-0.2 drop=0.2 -> no exit", not exit_now, "reason=" + reason)

    # Trailing armed AND drop=0.5 -> exit z_trailing
    pos = {"entry_ts": fresh_ts, "entry_z": -1.6, "max_z": -0.2}
    exit_now, reason = ar._should_exit(pos, current_z=-0.7)
    check("max_z=-0.2 drop=0.5 -> z_trailing",
          exit_now and reason == "z_trailing", "reason=" + reason)

    # Extreme overshoot z>=0.5 -> z_overshoot
    pos = {"entry_ts": fresh_ts, "entry_z": -1.6, "max_z": 0.5}
    exit_now, reason = ar._should_exit(pos, current_z=0.5)
    check("z=0.5 -> z_overshoot",
          exit_now and reason == "z_overshoot", "reason=" + reason)

    # Hard stop z<=-2.6
    pos = {"entry_ts": fresh_ts, "entry_z": -1.6, "max_z": -1.6}
    exit_now, reason = ar._should_exit(pos, current_z=-2.7)
    check("z=-2.7 -> z_hard_stop",
          exit_now and reason == "z_hard_stop", "reason=" + reason)

    # Time stop after 25h
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    pos = {"entry_ts": old_ts, "entry_z": -1.6, "max_z": -1.0}
    exit_now, reason = ar._should_exit(pos, current_z=-1.0)
    check("25h old -> time_stop",
          exit_now and reason.startswith("time_stop"), "reason=" + reason)


def test_realized_vol():
    print("\n# 8. Realized-vol helper")
    import pandas as pd
    import numpy as np
    from trading import altcoin_reversion as ar

    np.random.seed(42)
    hourly_returns = np.random.normal(0, 0.01, 500)
    closes = 100 * np.exp(np.cumsum(hourly_returns))
    df = pd.DataFrame({"close": closes})

    v = ar._realized_daily_vol(df)
    expected = 0.01 * np.sqrt(24)
    check("synthetic 1pct hourly -> ~4.9pct daily",
          v is not None and abs(v - expected) < 0.01,
          "got=" + str(round(v, 4) if v else None) + " exp=" + str(round(expected, 4)))

    tiny = pd.DataFrame({"close": [100, 101, 102]})
    v = ar._realized_daily_vol(tiny)
    check("insufficient data -> None", v is None, "got=" + str(v))


if __name__ == "__main__":
    test_universe_imports()
    test_denylist()
    test_passes_filters()
    test_c3_imports()
    test_cooldown_helpers()
    test_vol_adjusted_sizing()
    test_trailing_exit()
    test_realized_vol()

    print("\n" + ("-" * 50))
    if fail_count == 0:
        print("All checks PASSED")
        sys.exit(0)
    else:
        print(str(fail_count) + " checks FAILED")
        sys.exit(1)
