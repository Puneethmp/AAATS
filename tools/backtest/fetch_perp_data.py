"""Fetch Binance USDT-M perpetual 1h klines + funding-rate history (B.1.7 T4b).

Public Binance futures endpoints (no auth, free, rate-limited at 2400 req/min):
  - klines:  GET https://fapi.binance.com/fapi/v1/klines
  - funding: GET https://fapi.binance.com/fapi/v1/fundingRate

Two windows are supported (B.1.7 Track 8 added the earlier window for the
C3-perp window-robustness test):
  - current  (2025-11-28 -> 2026-05-27): the B.1.6/Track-4b graduation window.
      data/historical/{SYM}_USDT_1h_perp.parquet
      data/historical/{SYM}_USDT_funding.parquet
  - earlier  (2024-11-28 -> 2025-05-27): the prior-year robustness window.
      data/historical/{SYM}_USDT_1h_perp_earlier.parquet
      data/historical/{SYM}_USDT_funding_earlier.parquet

Idempotent: skips a symbol whose parquets already exist and cover the window.

Used by tools/nautilus/run_c3_perp_funded_oos.py (current) and
run_c3_perp_funded_earlier_oos.py (earlier) — the HONEST C3-perp graduation +
robustness tests (real perp prices + funding payments, no spot proxy).
Workstation research only; the box never imports this.

    python tools/backtest/fetch_perp_data.py --window both      # default
    python tools/backtest/fetch_perp_data.py --window earlier
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HIST = ROOT / "data" / "historical"
# Both windows carry ETH as of B.1.7 Track F (2026-05-30): the C7 funding-arb
# candidate and any majors-based perp edge need ETH on BOTH windows for the
# dual-window graduation gate. (Earlier window originally skipped ETH to shorten
# the C3-perp robustness fetch; that universe is now BTC + ETH + 4 alts.)
SYMBOLS_CURRENT = ["BTC", "ETH", "SOL", "LINK", "AVAX", "DOT"]
SYMBOLS_EARLIER = ["BTC", "ETH", "SOL", "LINK", "AVAX", "DOT"]

FAPI = "https://fapi.binance.com"

# Window registry: name -> (start, end_exclusive, file_suffix, symbols).
WINDOWS = {
    "current": (
        pd.Timestamp("2025-11-28T15:00:00Z"),
        pd.Timestamp("2026-05-27T15:00:00Z"),
        "",
        SYMBOLS_CURRENT,
    ),
    "earlier": (
        pd.Timestamp("2024-11-28T00:00:00Z"),
        pd.Timestamp("2025-05-28T00:00:00Z"),  # exclusive -> last bar 2025-05-27 23:00
        "_earlier",
        SYMBOLS_EARLIER,
    ),
    # Track F walk-forward (2026-05-30): MAXIMUM contiguous history for the
    # rolling-origin robustness test. Target ~36mo back from the current-window
    # end; all 6 perps listed well before 2023-05 so the floor (24mo) is cleared.
    # If fetch_klines returns fewer bars (later listing), the actual ts.min() is
    # the listing date — recorded by the caller, flagged for survivorship bias.
    "contig": (
        pd.Timestamp("2023-05-28T00:00:00Z"),
        pd.Timestamp("2026-05-27T15:00:00Z"),  # = current-window end
        "_contig",
        SYMBOLS_CURRENT,  # all 6: BTC ETH SOL LINK AVAX DOT
    ),
}


def _get(url: str) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": "aaats-b17-fetch"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (public Binance)
        return json.loads(resp.read().decode())


def _get_safe(url: str) -> list | None:
    """_get that returns None on HTTP 4xx (symbol not fetchable as {base}USDT)
    instead of raising — so one bad symbol in a 500-symbol sweep can't abort it."""
    try:
        return _get(url)
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            return None
        raise
    except (urllib.error.URLError, TimeoutError, UnicodeEncodeError, ValueError):
        return None


def fetch_klines(
    sym: str, win_start: pd.Timestamp, win_end: pd.Timestamp
) -> pd.DataFrame:
    """Paginate 1h klines for {sym}USDT perp over the window (limit=1000)."""
    pair = f"{sym}USDT"
    start_ms = int(win_start.timestamp() * 1000)
    end_ms = int(win_end.timestamp() * 1000)
    rows: list[list] = []
    cursor = start_ms
    while cursor < end_ms:
        url = (
            f"{FAPI}/fapi/v1/klines?symbol={pair}&interval=1h"
            f"&startTime={cursor}&endTime={end_ms}&limit=1000"
        )
        batch = _get(url)
        if not batch:
            break
        rows.extend(batch)
        last_open = batch[-1][0]
        cursor = last_open + 3_600_000  # next hour
        if len(batch) < 1000:
            break
        time.sleep(0.3)  # gentle; limit is 2400/min
    df = pd.DataFrame(
        rows,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "qav",
            "trades",
            "tbav",
            "tqav",
            "ignore",
        ],
    )
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
    df = df[(df["ts"] >= win_start) & (df["ts"] < win_end)]
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    return df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def fetch_funding(
    sym: str, win_start: pd.Timestamp, win_end: pd.Timestamp
) -> pd.DataFrame:
    """Funding-rate history for {sym}USDT perp over the window (8h cadence)."""
    pair = f"{sym}USDT"
    start_ms = int(win_start.timestamp() * 1000)
    end_ms = int(win_end.timestamp() * 1000)
    rows: list[dict] = []
    cursor = start_ms
    while cursor < end_ms:
        url = (
            f"{FAPI}/fapi/v1/fundingRate?symbol={pair}"
            f"&startTime={cursor}&endTime={end_ms}&limit=1000"
        )
        batch = _get(url)
        if not batch:
            break
        rows.extend(batch)
        last_ft = batch[-1]["fundingTime"]
        cursor = last_ft + 1  # advance past last event
        if len(batch) < 1000:
            break
        time.sleep(0.3)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["ts_funding"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["funding_rate"] = df["fundingRate"].astype(float)
    df = (
        df.drop_duplicates(subset="ts_funding")
        .sort_values("ts_funding")
        .reset_index(drop=True)
    )
    df = df[(df["ts_funding"] >= win_start) & (df["ts_funding"] < win_end)]
    return df[["ts_funding", "funding_rate"]].reset_index(drop=True)


def _covers(
    parquet: Path, ts_col: str, win_start: pd.Timestamp, win_end: pd.Timestamp
) -> bool:
    if not parquet.exists():
        return False
    try:
        df = pd.read_parquet(parquet)
        ts = pd.to_datetime(df[ts_col], utc=True)
        # klines: require near-full window. funding: just require it spans the window.
        return ts.min() <= win_start + pd.Timedelta(
            hours=2
        ) and ts.max() >= win_end - pd.Timedelta(days=2)
    except Exception:
        return False


def _run_window(name: str) -> None:
    win_start, win_end, suffix, symbols = WINDOWS[name]
    print(f"\n=== window '{name}': {win_start} -> {win_end} (suffix '{suffix}') ===")
    for sym in symbols:
        kpath = HIST / f"{sym}_USDT_1h_perp{suffix}.parquet"
        fpath = HIST / f"{sym}_USDT_funding{suffix}.parquet"

        if _covers(kpath, "ts", win_start, win_end):
            kdf = pd.read_parquet(kpath)
            print(f"{sym} klines: cached ({len(kdf)} bars) - skip")
        else:
            kdf = fetch_klines(sym, win_start, win_end)
            kdf.to_parquet(kpath, index=False)
            print(
                f"{sym} klines: fetched {len(kdf)} bars "
                f"{kdf['ts'].min()} -> {kdf['ts'].max()}"
            )

        if _covers(fpath, "ts_funding", win_start, win_end):
            fdf = pd.read_parquet(fpath)
            print(f"{sym} funding: cached ({len(fdf)} events) - skip")
        else:
            fdf = fetch_funding(sym, win_start, win_end)
            fdf.to_parquet(fpath, index=False)
            mean_bps = fdf["funding_rate"].mean() * 10000 if len(fdf) else 0.0
            print(
                f"{sym} funding: fetched {len(fdf)} events "
                f"(mean {mean_bps:+.3f} bps/8h)"
            )


# ──────────────────────────────────────────────────────────────────────────
# U30 cross-sectional point-in-time universe (Reactivation T1/T2, 2026-06-06)
# ──────────────────────────────────────────────────────────────────────────
#
# Frozen by docs/decisions/2026-06-06_reactivation_thesis_portfolio_preregistration.md
# §3 "Common to T1/T2 — Universe U30". Resolves, at each daily 00:00 UTC rebalance
# date t, the top-30 Binance USDT-M perpetuals by trailing-30d MEDIAN daily quote
# volume among symbols with onboardDate <= t-90d. Daily resolution serves both T1
# (daily rebalance) and T2 (weekly, a subset of the daily dates).
#
# SURVIVORSHIP HONESTY NOTE (registered limitation): /fapi/v1/exchangeInfo returns
# only CURRENTLY-listed symbols. Symbols delisted before today are absent and their
# klines are not retrievable from the public endpoint. Point-in-time ENTRY
# (onboardDate >= t-90d gate) is enforced exactly; the delist side cannot be
# reconstructed offline, so a residual survivorship bias toward symbols that
# survived to 2026-06 remains. This OVER-states alt-perp robustness if anything
# (dead alts were typically the worst performers), so a FAIL under this bias is
# only more decisive; a PASS would require the separately-specced extended
# validation to source point-in-time delisted history before any capital.

U30_START = pd.Timestamp("2023-05-28T00:00:00Z")
U30_END = pd.Timestamp("2026-05-27T00:00:00Z")  # exclusive daily-rebalance horizon
U30_SIZE = 30
U30_MIN_AGE_DAYS = 90
U30_VOL_LOOKBACK_DAYS = 30
U30_SUFFIX = "_u30"
U30_UNIVERSE_PARQUET = HIST / "u30_universe_daily.parquet"

_KLINE_COLS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "qav",
    "trades",
    "tbav",
    "tqav",
    "ignore",
]


def fetch_exchange_info_perps() -> dict:
    """Return {base_asset: {symbol, onboard(Timestamp UTC), status}} for every
    USDT-M PERPETUAL currently on Binance futures. See survivorship note above."""
    info = _get(f"{FAPI}/fapi/v1/exchangeInfo")
    out: dict[str, dict] = {}
    for s in info["symbols"]:
        if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT":
            out[s["baseAsset"]] = {
                "symbol": s["symbol"],
                "onboard": pd.to_datetime(s["onboardDate"], unit="ms", utc=True),
                "status": s.get("status"),
            }
    return out


def fetch_daily_quote_volume(
    sym: str, win_start: pd.Timestamp, win_end: pd.Timestamp
) -> pd.Series:
    """Daily quote-asset volume (USDT) for {sym}USDT perp over the window.
    Used only to rank the universe — NOT a price/PnL input (anti-snooping safe)."""
    pair = f"{sym}USDT"
    start_ms = int(win_start.timestamp() * 1000)
    end_ms = int(win_end.timestamp() * 1000)
    rows: list[list] = []
    cursor = start_ms
    while cursor < end_ms:
        url = (
            f"{FAPI}/fapi/v1/klines?symbol={pair}&interval=1d"
            f"&startTime={cursor}&endTime={end_ms}&limit=1500"
        )
        batch = _get_safe(url)
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1][0] + 86_400_000  # next day
        if len(batch) < 1500:
            break
        time.sleep(0.15)
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows, columns=_KLINE_COLS)
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["qav"] = df["qav"].astype(float)
    return df.drop_duplicates(subset="ts").set_index("ts")["qav"].sort_index()


def resolve_u30_universe(
    start: pd.Timestamp = U30_START,
    end: pd.Timestamp = U30_END,
    write: bool = True,
) -> pd.DataFrame:
    """Build the point-in-time daily top-30 universe membership table.

    Returns a long DataFrame [date, rank, symbol, med_qav_usd]. Writes it to
    U30_UNIVERSE_PARQUET when ``write``. The union of `symbol` across all dates
    is the set needing 1h klines + funding (fetched by fetch_u30_market_data).
    """
    info = fetch_exchange_info_perps()
    bases = sorted(info)
    print(f"exchangeInfo: {len(bases)} USDT-M perp candidates (currently listed)")
    vol_start = start - pd.Timedelta(days=U30_VOL_LOOKBACK_DAYS + 5)
    qav: dict[str, pd.Series] = {}
    for i, b in enumerate(bases):
        s = fetch_daily_quote_volume(b, vol_start, end)
        if len(s):
            qav[b] = s
        if (i + 1) % 50 == 0:
            print(f"  daily-volume fetched {i + 1}/{len(bases)}")
    vol_df = pd.DataFrame(qav).sort_index()
    print(f"daily-volume panel: {vol_df.shape[0]} days x {vol_df.shape[1]} symbols")

    rebal_days = pd.date_range(start, end - pd.Timedelta(days=1), freq="D", tz="UTC")
    lookback = pd.Timedelta(days=U30_VOL_LOOKBACK_DAYS)
    min_age = pd.Timedelta(days=U30_MIN_AGE_DAYS)
    rows: list[dict] = []
    for t in rebal_days:
        win = vol_df.loc[(vol_df.index > t - lookback) & (vol_df.index <= t)]
        if win.empty:
            continue
        med = win.median(axis=0, skipna=True)
        elig = [
            b
            for b in med.index
            if pd.notna(med[b]) and med[b] > 0 and info[b]["onboard"] <= t - min_age
        ]
        ranked = med[elig].sort_values(ascending=False).head(U30_SIZE)
        for rank, (b, v) in enumerate(ranked.items(), start=1):
            rows.append({"date": t, "rank": rank, "symbol": b, "med_qav_usd": float(v)})
    uni = pd.DataFrame(rows)
    if write:
        uni.to_parquet(U30_UNIVERSE_PARQUET, index=False)
    union = sorted(uni["symbol"].unique())
    print(
        f"resolved {len(rebal_days)} daily universes; UNION = {len(union)} symbols:\n"
        f"  {', '.join(union)}"
    )
    return uni


def fetch_u30_market_data(
    symbols: list[str] | None = None,
    win_start: pd.Timestamp = U30_START,
    win_end: pd.Timestamp = pd.Timestamp("2026-05-27T15:00:00Z"),
    suffix: str = U30_SUFFIX,
) -> None:
    """Fetch 1h klines + 8h funding for each symbol in the U30 union (or an
    explicit list), with the given file suffix. Idempotent (skips covered)."""
    if symbols is None:
        uni = pd.read_parquet(U30_UNIVERSE_PARQUET)
        symbols = sorted(uni["symbol"].unique())
    HIST.mkdir(parents=True, exist_ok=True)
    print(
        f"\n=== U30 market data: {len(symbols)} symbols, {win_start} -> {win_end} ==="
    )
    for i, sym in enumerate(symbols):
        kpath = HIST / f"{sym}_USDT_1h_perp{suffix}.parquet"
        fpath = HIST / f"{sym}_USDT_funding{suffix}.parquet"
        if _covers(kpath, "ts", win_start, win_end):
            print(f"[{i + 1}/{len(symbols)}] {sym} klines cached - skip")
        else:
            kdf = fetch_klines(sym, win_start, win_end)
            kdf.to_parquet(kpath, index=False)
            span = f"{kdf['ts'].min()} -> {kdf['ts'].max()}" if len(kdf) else "EMPTY"
            print(f"[{i + 1}/{len(symbols)}] {sym} klines {len(kdf)} bars {span}")
        if _covers(fpath, "ts_funding", win_start, win_end):
            print(f"           {sym} funding cached - skip")
        else:
            fdf = fetch_funding(sym, win_start, win_end)
            fdf.to_parquet(fpath, index=False)
            print(f"           {sym} funding {len(fdf)} events")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Binance perp klines + funding")
    parser.add_argument(
        "--window",
        choices=["current", "earlier", "both", "contig", "u30"],
        default="both",
        help=(
            "which window to fetch (default: both; 'contig' = max-contiguous "
            "walk-forward history; 'u30' = resolve+fetch the cross-sectional "
            "point-in-time universe for the T1/T2 reactivation theses)"
        ),
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="comma-separated base assets (e.g. BTC,ETH,SOL); overrides --window's "
        "symbol set. Used with --start/--end/--suffix for ad-hoc fetches.",
    )
    parser.add_argument(
        "--start", default=None, help="ISO start (UTC), e.g. 2023-05-28"
    )
    parser.add_argument("--end", default=None, help="ISO end (UTC, exclusive)")
    parser.add_argument("--suffix", default=U30_SUFFIX, help="parquet filename suffix")
    parser.add_argument(
        "--resolve-only",
        action="store_true",
        help="(u30) resolve the universe membership table only; skip 1h/funding fetch",
    )
    args = parser.parse_args(argv)
    HIST.mkdir(parents=True, exist_ok=True)

    # Ad-hoc explicit symbol-list + date-range mode (the new CLI surface).
    if args.symbols:
        syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        ws = pd.Timestamp(args.start, tz="UTC") if args.start else U30_START
        we = (
            pd.Timestamp(args.end, tz="UTC")
            if args.end
            else pd.Timestamp("2026-05-27T15:00:00Z")
        )
        fetch_u30_market_data(syms, ws, we, args.suffix)
        print("\nperp data fetch complete.")
        return 0

    if args.window == "u30":
        ws = pd.Timestamp(args.start, tz="UTC") if args.start else U30_START
        we = pd.Timestamp(args.end, tz="UTC") if args.end else U30_END
        resolve_u30_universe(ws, we, write=True)
        if not args.resolve_only:
            fetch_u30_market_data(
                None, ws, pd.Timestamp("2026-05-27T15:00:00Z"), args.suffix
            )
        print("\nperp data fetch complete.")
        return 0

    names = ["current", "earlier"] if args.window == "both" else [args.window]
    for name in names:
        _run_window(name)
    print("\nperp data fetch complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
