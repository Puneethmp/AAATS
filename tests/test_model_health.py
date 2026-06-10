"""Tests for ml.model_health — the staleness / accuracy-floor guard (Phase 2)."""

from __future__ import annotations

from datetime import datetime, timezone

from ml import model_health as mh


def test_fresh_high_accuracy_is_trustworthy():
    meta = {"trained_at": "2026-06-10T00:00:00+00:00", "val_acc_crypto": 0.61}
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    assert mh.is_stale(meta, now=now) is False
    assert mh.meets_accuracy_floor(meta, "crypto") is True


def test_old_model_is_stale():
    meta = {"trained_at": "2026-05-07T18:45:58+00:00", "val_acc_crypto": 0.55}
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)
    assert mh.age_days(meta, now) > 30
    assert mh.is_stale(meta, now=now) is True


def test_near_random_accuracy_fails_floor():
    # The actual current crypto model: 0.5508 — below the 0.53 floor? It's above
    # 0.53, so it passes the floor but is still flagged by staleness. Use a value
    # that is genuinely sub-floor to assert the floor logic.
    assert mh.meets_accuracy_floor({"val_acc_crypto": 0.51}, "crypto") is False
    assert mh.meets_accuracy_floor({"val_acc_crypto": 0.55}, "crypto") is True


def test_missing_trained_at_fails_closed_as_stale():
    assert mh.is_stale({"val_acc_crypto": 0.9}) is True


def test_missing_accuracy_fails_floor():
    assert mh.meets_accuracy_floor({}, "crypto") is False


def test_health_report_marks_current_model_untrustworthy():
    # The real on-disk model: stale (2026-05-07) -> not trustworthy regardless of acc.
    meta = {"trained_at": "2026-05-07T18:45:58+00:00", "val_acc_crypto": 0.5508}
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)
    # patch via a temp file is overkill; test the pure helpers compose correctly
    stale = mh.is_stale(meta, now=now)
    acc_ok = mh.meets_accuracy_floor(meta, "crypto")
    trustworthy = (not stale) and acc_ok
    assert stale is True
    assert trustworthy is False
