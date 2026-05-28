"""Fetch Binance USDT-M perpetual 1h klines + funding-rate history (B.1.7 T4b).

Public Binance futures endpoints (no auth, free, rate-limited at 2400 req/min):
  - klines:  GET https://fapi.binance.com/fapi/v1/klines
  - funding: GET https://fapi.binance.com/fapi/v1/fundingRate

For each of [BTC, SOL, LINK, AVAX, DOT] over 2025-11-28 -> 2026-05-27, writes:
  data/historical/{SYM}_USDT_1h_perp.parquet   (ts, open, high, low, close, volume)
  data/historical/{SYM}_USDT_funding.parquet   (ts_funding, funding_rate)

Idempotent: skips a symbol whose parquets already exist and cover the window.

Used by tools/nautilus/run_c3_perp_funded_oos.py — the HONEST C3-perp
graduation test (real perp prices + funding payments, no spot proxy).
Workstation research only; the box never imports this.

    python tools/backtest/fetch_perp_data.py
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HIST = ROOT / "data" / "historical"
SYMBOLS = ["BTC", "SOL", "LINK", "AVAX", "DOT"]

FAPI = "https://fapi.binance.com"
# Match the spot cache window (2025-11-28 15:00 -> 2026-05-27 14:00 UTC).
WIN_START = pd.Timestamp("2025-11-28T15:00:00Z")
WIN_END = pd.Timestamp("2026-05-27T15:00:00Z")  # exclusive upper bound
START_MS = int(WIN_START.timestamp() * 1000)
END_MS = int(WIN_END.timestamp() * 1000)


def _get(url: str) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": "aaats-b17-fetch"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (public Binance)
        return json.loads(resp.read().decode())


def fetch_klines(sym: str) -> pd.DataFrame:
    """Paginate 1h klines for {sym}USDT perp over the window (limit=1000)."""
    pair = f"{sym}USDT"
    rows: list[list] = []
    cursor = START_MS
    while cursor < END_MS:
        url = (
            f"{FAPI}/fapi/v1/klines?symbol={pair}&interval=1h"
            f"&startTime={cursor}&endTime={END_MS}&limit=1000"
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
    df = df[(df["ts"] >= WIN_START) & (df["ts"] < WIN_END)]
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    return df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def fetch_funding(sym: str) -> pd.DataFrame:
    """Funding-rate history for {sym}USDT perp over the window (8h cadence)."""
    pair = f"{sym}USDT"
    rows: list[dict] = []
    cursor = START_MS
    while cursor < END_MS:
        url = (
            f"{FAPI}/fapi/v1/fundingRate?symbol={pair}"
            f"&startTime={cursor}&endTime={END_MS}&limit=1000"
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
    df = df[(df["ts_funding"] >= WIN_START) & (df["ts_funding"] < WIN_END)]
    return df[["ts_funding", "funding_rate"]].reset_index(drop=True)


def _covers(parquet: Path, ts_col: str) -> bool:
    if not parquet.exists():
        return False
    try:
        df = pd.read_parquet(parquet)
        ts = pd.to_datetime(df[ts_col], utc=True)
        # klines: require near-full window. funding: just require it spans the window.
        return ts.min() <= WIN_START + pd.Timedelta(
            hours=2
        ) and ts.max() >= WIN_END - pd.Timedelta(days=2)
    except Exception:
        return False


def main() -> int:
    HIST.mkdir(parents=True, exist_ok=True)
    for sym in SYMBOLS:
        kpath = HIST / f"{sym}_USDT_1h_perp.parquet"
        fpath = HIST / f"{sym}_USDT_funding.parquet"

        if _covers(kpath, "ts"):
            kdf = pd.read_parquet(kpath)
            print(f"{sym} klines: cached ({len(kdf)} bars) — skip")
        else:
            kdf = fetch_klines(sym)
            kdf.to_parquet(kpath, index=False)
            print(
                f"{sym} klines: fetched {len(kdf)} bars "
                f"{kdf['ts'].min()} -> {kdf['ts'].max()}"
            )

        if _covers(fpath, "ts_funding"):
            fdf = pd.read_parquet(fpath)
            print(f"{sym} funding: cached ({len(fdf)} events) — skip")
        else:
            fdf = fetch_funding(sym)
            fdf.to_parquet(fpath, index=False)
            mean_bps = fdf["funding_rate"].mean() * 10000 if len(fdf) else 0.0
            print(
                f"{sym} funding: fetched {len(fdf)} events "
                f"(mean {mean_bps:+.3f} bps/8h)"
            )
    print("\nperp data fetch complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
