"""U30 cross-sectional data loaders (Reactivation T1/T2, 2026-06-06).

Reads the artifacts produced by tools/backtest/fetch_perp_data.py --window u30:
  - data/historical/u30_universe_daily.parquet  (point-in-time top-30 membership)
  - data/historical/{SYM}_USDT_1h_perp_u30.parquet  (1h perp klines per union symbol)
  - data/historical/{SYM}_USDT_funding_u30.parquet   (8h funding per union symbol)

Exposes a daily 00:00-UTC close panel, a per-symbol funding dict, and the
date->eligible-symbol-set membership map the T1/T2 schedule builders rank within.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HIST = ROOT / "data" / "historical"
SUFFIX = "_u30"
UNIVERSE_PARQUET = HIST / "u30_universe_daily.parquet"


def load_universe() -> pd.DataFrame:
    """Long membership table [date, rank, symbol, med_qav_usd]."""
    return pd.read_parquet(UNIVERSE_PARQUET)


def membership_by_date(uni: pd.DataFrame | None = None) -> dict:
    """date(Timestamp UTC midnight) -> list[symbol] (the day's top-30, rank order)."""
    if uni is None:
        uni = load_universe()
    uni = uni.sort_values(["date", "rank"])
    out: dict = {}
    for d, grp in uni.groupby("date"):
        out[pd.Timestamp(d)] = list(grp.sort_values("rank")["symbol"])
    return out


def union_symbols(uni: pd.DataFrame | None = None) -> list[str]:
    if uni is None:
        uni = load_universe()
    return sorted(uni["symbol"].unique())


def _load_hourly_close(sym: str) -> pd.Series | None:
    p = HIST / f"{sym}_USDT_1h_perp{SUFFIX}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if df.empty:
        return None
    idx = pd.to_datetime(df["ts"], utc=True)
    return pd.Series(df["close"].astype(float).to_numpy(), index=idx).sort_index()


def load_daily_close_panel(symbols: list[str]) -> pd.DataFrame:
    """days(00:00 UTC) x symbols perp-close panel. Uses the 00:00 bar's close as
    the day's mark (exact midnight stamp)."""
    cols = {}
    for s in symbols:
        ser = _load_hourly_close(s)
        if ser is None:
            continue
        mid = ser[ser.index.hour == 0]
        mid.index = mid.index.normalize()
        mid = mid[~mid.index.duplicated(keep="last")]
        cols[s] = mid
    panel = pd.DataFrame(cols).sort_index()
    return panel


def load_funding(symbols: list[str]) -> dict:
    """{symbol -> Series(8h settlement ts -> funding_rate)}."""
    out: dict = {}
    for s in symbols:
        p = HIST / f"{s}_USDT_funding{SUFFIX}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if df.empty:
            continue
        ser = pd.Series(
            df["funding_rate"].astype(float).to_numpy(),
            index=pd.to_datetime(df["ts_funding"], utc=True),
        ).sort_index()
        out[s] = ser
    return out
