"""
India F&O option chain validator.
Options-specific checks: IV > 0, OI > 0, bid/ask present, lot-size multiples,
valid strike list, and far-OTM filtering.
Rejected rows are audit-logged as REJECTION events.
"""

from typing import Any

import pandas as pd

from foundation.audit_trail import AuditTrail
from foundation.logger import get_logger

_log = get_logger("india", "fo_validator")

_REQUIRED_COLUMNS: list[str] = [
    "strike",
    "option_type",
    "ltp",
    "oi",
    "change_in_oi",
    "iv",
    "bid",
    "ask",
    "volume",
]
_DEFAULT_FAR_OTM_PCT: float = 30.0


def _get_lot_size(underlying: str, config) -> int:
    """Return lot size for the underlying from config, defaulting to 1 (no check)."""
    try:
        return int(config.india.lot_sizes.get(underlying, 1))
    except (AttributeError, TypeError, ValueError):
        return 1


def _get_valid_strikes(underlying: str, config) -> list[float] | None:
    """Return configured valid strike list, or None to skip that check."""
    try:
        strikes = config.india.valid_strikes.get(underlying)
        if strikes:
            return [float(s) for s in strikes]
    except (AttributeError, TypeError):
        pass
    return None


def _get_spot_price(underlying: str, config) -> float | None:
    """Return spot price for underlying from config, or None if unavailable."""
    try:
        val = config.india.spot_prices.get(underlying)
        return float(val) if val is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _get_far_otm_pct(config) -> float:
    """Return the far-OTM distance threshold (% of spot) from config."""
    try:
        return float(config.india.far_otm_pct)
    except (AttributeError, TypeError, ValueError):
        return _DEFAULT_FAR_OTM_PCT


def validate_option_chain(
    df: pd.DataFrame,
    underlying: str,
    config,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """
    Validate NSE F&O option chain rows.

    Rejects rows with any of:
    - IV <= 0  (option pricing impossible — illiquid or stale strike)
    - OI == 0  (cannot enter or exit — no open interest)
    - bid == 0 AND ask == 0  (no market — stale or unsupported strike)
    - OI is not an integer multiple of lot_size (data integrity error)
    - strike not in configured valid strike list for this underlying
    - |strike - spot| > far_otm_pct% of spot  (far OTM — illiquid fringe strikes)

    Args:
        df:         DataFrame with columns matching _REQUIRED_COLUMNS.
        underlying: Underlying symbol, e.g. "NIFTY". Used for config lookups + audit.
        config:     AppConfig-compatible object; reads india.lot_sizes, india.valid_strikes,
                    india.spot_prices, india.far_otm_pct.

    Returns:
        (clean_df, rejections): clean_df has only valid rows with index reset;
        rejections is a list of dicts with keys [underlying, strike, option_type, reasons].

    Raises:
        ValueError: if any required column is missing from df.
    """
    if df.empty:
        return df.copy(), []

    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns for fo_validator: {missing}")

    audit = AuditTrail()
    lot_size = _get_lot_size(underlying, config)
    valid_strikes = _get_valid_strikes(underlying, config)
    spot_price = _get_spot_price(underlying, config)
    far_otm_pct = _get_far_otm_pct(config)

    # ── IV check ──────────────────────────────────────────────────────────────
    iv_mask = df["iv"] <= 0

    # ── OI check ──────────────────────────────────────────────────────────────
    oi_mask = df["oi"] == 0

    # ── No market (bid + ask both zero) ───────────────────────────────────────
    no_market_mask = (df["bid"] == 0) & (df["ask"] == 0)

    # ── Lot-size integrity ────────────────────────────────────────────────────
    # OI == 0 is already caught above; skip that case here to avoid duplicate reasons.
    if lot_size > 1:
        lot_mask = (df["oi"] > 0) & (df["oi"] % lot_size != 0)
    else:
        lot_mask = pd.Series(False, index=df.index)

    # ── Valid-strike list ─────────────────────────────────────────────────────
    if valid_strikes is not None:
        valid_set = set(valid_strikes)
        strike_mask = ~df["strike"].isin(valid_set)
    else:
        strike_mask = pd.Series(False, index=df.index)

    # ── Far-OTM filter ────────────────────────────────────────────────────────
    if spot_price is not None and spot_price > 0:
        far_otm_mask = (df["strike"] - spot_price).abs() > (
            far_otm_pct / 100.0
        ) * spot_price
    else:
        far_otm_mask = pd.Series(False, index=df.index)

    reject_mask = (
        iv_mask | oi_mask | no_market_mask | lot_mask | strike_mask | far_otm_mask
    )

    rejections: list[dict[str, Any]] = []
    for idx in df.index[reject_mask]:
        row = df.loc[idx]
        reasons: list[str] = []
        if iv_mask.loc[idx]:
            reasons.append("iv_zero_or_negative")
        if oi_mask.loc[idx]:
            reasons.append("oi_zero")
        if no_market_mask.loc[idx]:
            reasons.append("no_market_bid_ask_zero")
        if lot_mask.loc[idx]:
            reasons.append("oi_not_lot_multiple")
        if strike_mask.loc[idx]:
            reasons.append("strike_not_in_valid_list")
        if far_otm_mask.loc[idx]:
            reasons.append("far_otm_strike")

        rejections.append(
            {
                "underlying": underlying,
                "strike": float(row["strike"]),
                "option_type": str(row.get("option_type", "")),
                "reasons": reasons,
            }
        )
        _log.warning(
            f"Rejected F&O chain row {underlying} "
            f"strike={row['strike']} type={row.get('option_type', '')}: {reasons}"
        )
        audit.append(
            market="india",
            module="fo_validator",
            event_type="REJECTION",
            details={
                "underlying": underlying,
                "strike": float(row["strike"]),
                "option_type": str(row.get("option_type", "")),
                "reasons": reasons,
            },
            result="REJECTED",
            reason=f"F&O chain row rejected: {', '.join(reasons)}",
        )

    _log.info(
        f"Validated {len(df)} F&O chain rows for {underlying}: "
        f"{len(rejections)} rejected"
    )
    clean_df = df[~reject_mask].reset_index(drop=True)
    return clean_df, rejections
