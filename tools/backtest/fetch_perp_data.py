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
}


def _get(url: str) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": "aaats-b17-fetch"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (public Binance)
        return json.loads(resp.read().decode())


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Binance perp klines + funding")
    parser.add_argument(
        "--window",
        choices=["current", "earlier", "both"],
        default="both",
        help="which 6mo window to fetch (default: both)",
    )
    args = parser.parse_args(argv)
    HIST.mkdir(parents=True, exist_ok=True)
    names = ["current", "earlier"] if args.window == "both" else [args.window]
    for name in names:
        _run_window(name)
    print("\nperp data fetch complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
