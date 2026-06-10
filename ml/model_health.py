"""
ML model-health guard (forensic-audit Phase 2).

The Phase 0 audit found the XGBoost model is (a) stale — training_meta says
2026-05-07, >30 days old — and (b) near-random (val_acc 0.5508). The mandate
requires monitoring that alerts when a model exceeds max age, and forbids a gate
that pretends to be risk management while adding no value.

This module is pure (reads a meta JSON, returns verdicts). Wire it into the
metrics exporter / weekly report to surface staleness and sub-floor accuracy.
It does NOT decide to trade — it decides whether the model is fit to be trusted.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_META = Path("data/ml/training_meta.json")

# A model older than this is stale and must be retrained (walk-forward) or the
# gate disabled. Mirrors load_saved_models(max_age_days=7).
MAX_AGE_DAYS = 7.0

# Below this validation accuracy the gate carries no information — it is dead
# weight. 0.52 is a deliberately low bar; 0.5508 (the current crypto model) is
# barely above it and should be treated as "no edge".
ACCURACY_FLOOR = 0.53


def _load(meta_path: str | Path = DEFAULT_META) -> dict:
    p = Path(meta_path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def age_days(meta: dict, now: datetime | None = None) -> float | None:
    ts = meta.get("trained_at")
    if not ts:
        return None
    try:
        trained = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if trained.tzinfo is None:
        trained = trained.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - trained).total_seconds() / 86400.0


def is_stale(
    meta: dict, max_age_days: float = MAX_AGE_DAYS, now: datetime | None = None
) -> bool:
    a = age_days(meta, now)
    # Missing/unparseable trained_at is treated as stale (fail closed).
    return True if a is None else a > max_age_days


def meets_accuracy_floor(
    meta: dict, market: str = "crypto", floor: float = ACCURACY_FLOOR
) -> bool:
    acc = meta.get(f"val_acc_{market}")
    if acc is None:
        return False
    return float(acc) >= floor


def health_report(
    meta_path: str | Path = DEFAULT_META,
    market: str = "crypto",
    now: datetime | None = None,
) -> dict:
    """Return a structured health verdict for the model.

    `trustworthy` is True only if the model is fresh AND clears the accuracy
    floor. A False here means: retrain under walk-forward, or disable the gate.
    """
    meta = _load(meta_path)
    a = age_days(meta, now)
    stale = is_stale(meta, now=now)
    acc_ok = meets_accuracy_floor(meta, market)
    acc = meta.get(f"val_acc_{market}")
    reasons: list[str] = []
    if stale:
        reasons.append(
            f"stale (age={'unknown' if a is None else f'{a:.1f}d'} > {MAX_AGE_DAYS}d)"
        )
    if not acc_ok:
        reasons.append(f"val_acc {acc} below floor {ACCURACY_FLOOR}")
    return {
        "market": market,
        "trained_at": meta.get("trained_at"),
        "age_days": None if a is None else round(a, 2),
        "val_acc": acc,
        "stale": stale,
        "meets_accuracy_floor": acc_ok,
        "trustworthy": (not stale) and acc_ok,
        "reasons": reasons,
    }


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(health_report(), indent=2))
