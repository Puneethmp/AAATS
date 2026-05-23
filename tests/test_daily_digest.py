"""
tests/test_daily_digest.py - Phase D.4 daily digest.

Three buckets:
  1. Golden-output: deterministic-output test with fully-seeded fixtures.
  2. Missing-state tolerance: subsections gracefully degrade to N/A when
     their state files are absent.
  3. Action-needed trigger matrix: each trigger lights the action line.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from monitoring import daily_digest


def _make_db_with_schema(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE paper_trades ("
        "id TEXT PRIMARY KEY, timestamp TEXT, market TEXT, symbol TEXT, "
        "action TEXT, shares REAL, price REAL, value REAL, "
        "signal TEXT, regime TEXT, risk_action TEXT, pnl REAL DEFAULT 0.0, "
        "note TEXT, strategy TEXT DEFAULT ''"
        ")"
    )
    conn.execute(
        "CREATE TABLE cycle_log (timestamp TEXT NOT NULL, "
        "cycle INTEGER NOT NULL, market TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()


def _seed_full_fixture(tmp_path: Path) -> Path:
    """Create a fully-populated data dir.

    Reference time anchor: 2026-05-23T08:00:00+00:00 (13:30 IST same day).
    """
    db = tmp_path / "paper_trades.db"
    _make_db_with_schema(db)
    conn = sqlite3.connect(str(db))
    base = datetime(2026, 5, 23, 7, 0, tzinfo=timezone.utc)  # 1h before anchor
    # 1 closed C3 trade in window (BUY + SELL same cycle, profitable).
    conn.executemany(
        "INSERT INTO paper_trades "
        "(id, timestamp, market, symbol, action, shares, price, value, "
        " signal, regime, risk_action, pnl, note, strategy) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("c3-buy", base.isoformat(), "crypto", "ADA/USDT", "BUY",
             60.0, 0.25, 15.0, "BUY", "RANGE", "ALLOW", 0.0, "",
             "C3_altcoin_reversion"),
            ("c3-sell", (base + timedelta(minutes=30)).isoformat(),
             "crypto", "ADA/USDT", "SELL", 60.0, 0.27, 16.2, "SELL",
             "RANGE", "ALLOW", 1.20, "", "C3_altcoin_reversion"),
            # 1 open C6 BUY (no SELL) -- should produce unrealized.
            ("c6-buy", (base + timedelta(minutes=10)).isoformat(),
             "crypto", "DOT/USDT", "BUY", 2.0, 5.0, 10.0, "BUY",
             "TREND", "ALLOW", 0.0, "", "C6_bollinger_range"),
        ],
    )
    # 24 cycles in the last 24h. Anchor explicitly to as_of so every cycle
    # falls inside the 24h window [as_of - 24h, as_of).
    rows_cycle = []
    as_of_anchor = datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc)
    cycle_base = as_of_anchor - timedelta(hours=24)
    for i in range(24):
        rows_cycle.append((
            (cycle_base + timedelta(hours=i)).isoformat(), i, "crypto"
        ))
    conn.executemany(
        "INSERT INTO cycle_log (timestamp, cycle, market) VALUES (?, ?, ?)",
        rows_cycle,
    )
    conn.commit()
    conn.close()

    # State files
    (tmp_path / "state-paper").mkdir(exist_ok=True)
    (tmp_path / "state-paper" / "risk_engine_state.paper.json").write_text(
        json.dumps({
            "peak": 131.32,
            "last_equity": 110.50,
            "last_update_ts": 1779513912.0,
            "market_peaks": {"crypto": 131.32},
        }),
        encoding="utf-8",
    )
    (tmp_path / "strategy_exception_state.json").write_text(
        json.dumps({"C3_altcoin_reversion": {"total_exceptions": 1,
                                              "consecutive_exceptions": 0}}),
        encoding="utf-8",
    )
    (tmp_path / "strategy_halt_state.json").write_text(
        json.dumps({"C5b_funding_arb": {
            "halted": True,
            "reason": "manual disable pending unified ledger",
            "halted_at": "2026-05-15T00:00:00+00:00",
            "consecutive_exceptions": 0,
        }}),
        encoding="utf-8",
    )
    (tmp_path / "share_equality_mismatches.json").write_text(
        json.dumps({}),
        encoding="utf-8",
    )
    (tmp_path / "watchdog_heartbeat.json").write_text(
        json.dumps({"restart_count_in_window": 0, "last_decision": "ok"}),
        encoding="utf-8",
    )
    return db


# ── Golden-output test ─────────────────────────────────────────────────────


def test_full_digest_renders_expected_shape(tmp_path: Path) -> None:
    _seed_full_fixture(tmp_path)
    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    as_of = datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc)
    body = daily_digest.build_digest(
        cfg, as_of=as_of,
        container_restart_count=2,
        yesterdays_restart_count=2,  # zero new restarts in window
    )

    # Header
    assert "AAATS daily digest -- 2026-05-23" in body
    # T+N: 2026-05-23 is 11 days after rebuild anchor 2026-05-12.
    assert "T+11 since rebuild" in body

    # P&L
    assert "Realized:   $+1.20" in body
    # Unrealized: DOT open BUY (2 * 5 = 10). Without a separate price feed
    # the last_price proxy == entry price, so unrealized = 0.00.
    assert "Unrealized: $+0.00" in body
    assert "Equity:     $110.50  (peak $131.32, dd -15.9%)" in body

    # Operational
    assert "Cycles run:        24 (expected 96, 25.0% uptime)" in body
    assert "Exceptions:        1  (0 auto-halted)" in body
    assert "Container restarts: 0  (auto: 0, manual: 0)" in body
    assert "Alerts fired:      N/A" in body  # not implemented yet

    # Strategies
    assert "Firing:   C3_altcoin_reversion (2 trades), C6_bollinger_range (1 trades)" in body
    # Silent: doctrine universe minus firing minus halted
    assert "Silent:   C1_stat_arb, C2_momentum" in body
    assert "Halted:   C5b_funding_arb (since 2026-05-15, manual disable pending unified ledger)" in body

    # Action needed -- dd is -15.9% which is past the -15% market-kill band.
    assert (
        "Action needed: drawdown -15.9% past market-kill threshold (-15%); "
        "new entries blocked, open positions continue to mark-to-market"
    ) in body


# ── Missing-state tolerance ────────────────────────────────────────────────


def test_missing_state_falls_back_to_na(tmp_path: Path) -> None:
    # Only an empty DB; no state JSONs, no cycle_log rows.
    db = tmp_path / "paper_trades.db"
    _make_db_with_schema(db)
    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    as_of = datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc)
    body = daily_digest.build_digest(
        cfg, as_of=as_of,
        container_restart_count=None,
        yesterdays_restart_count=None,
    )

    # Header still renders.
    assert "AAATS daily digest -- 2026-05-23" in body
    # P&L falls back to 0 / N/A appropriately.
    assert "Realized:   $+0.00" in body
    assert "Unrealized: $+0.00" in body
    assert "Equity:     N/A" in body  # no risk state file
    # Cycles_run = 0 (cycle_log exists but is empty) -- so "0 (expected 96, 0.0% uptime)" should appear.
    assert "Cycles run:        0 (expected 96, 0.0% uptime)" in body
    # Restarts unknown (we passed None explicitly).
    assert "Container restarts: N/A" in body
    # Strategies: nothing firing, doctrine universe is silent.
    assert "Firing:   (none)" in body
    # Halted defaults to (none).
    assert "Halted:   (none)" in body
    # Action: no triggers should fire when state is absent.
    assert "Action needed: NONE" in body


def test_missing_cycle_log_table_is_tolerated(tmp_path: Path) -> None:
    db = tmp_path / "paper_trades.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE paper_trades ("
        "id TEXT PRIMARY KEY, timestamp TEXT, market TEXT, symbol TEXT, "
        "action TEXT, shares REAL, price REAL, value REAL, "
        "signal TEXT, regime TEXT, risk_action TEXT, pnl REAL DEFAULT 0.0, "
        "note TEXT, strategy TEXT DEFAULT ''"
        ")"
    )
    conn.commit()
    conn.close()
    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    as_of = datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc)
    body = daily_digest.build_digest(cfg, as_of=as_of)
    assert "Cycles run:        N/A" in body
    assert "cycle_log unavailable" in body


# ── Action-needed trigger matrix ───────────────────────────────────────────


def _fixture_with_state(tmp_path: Path, state: dict, name: str) -> Path:
    (tmp_path / name).write_text(json.dumps(state), encoding="utf-8")
    return tmp_path / name


def _empty_db(tmp_path: Path) -> Path:
    db = tmp_path / "paper_trades.db"
    _make_db_with_schema(db)
    return db


def test_action_triggers_on_drawdown_at_threshold(tmp_path: Path) -> None:
    _empty_db(tmp_path)
    (tmp_path / "state-paper").mkdir(exist_ok=True)
    (tmp_path / "state-paper" / "risk_engine_state.paper.json").write_text(
        json.dumps({"peak": 100.0, "last_equity": 90.0,
                    "last_update_ts": 1779513912.0,
                    "market_peaks": {"crypto": 100.0}}),
        encoding="utf-8",
    )
    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    body = daily_digest.build_digest(
        cfg, as_of=datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc),
        container_restart_count=0, yesterdays_restart_count=0,
    )
    assert "drawdown" in body.lower()
    assert "Action needed: NONE" not in body


# ── Kill-switch wording bands (post-2026-05-23 kill-trigger investigation) ──


def _build_with_equity(tmp_path: Path, peak: float, equity: float) -> str:
    _empty_db(tmp_path)
    (tmp_path / "state-paper").mkdir(exist_ok=True)
    (tmp_path / "state-paper" / "risk_engine_state.paper.json").write_text(
        json.dumps({"peak": peak, "last_equity": equity,
                    "last_update_ts": 1779513912.0,
                    "market_peaks": {"crypto": peak}}),
        encoding="utf-8",
    )
    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    return daily_digest.build_digest(
        cfg, as_of=datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc),
        container_restart_count=0, yesterdays_restart_count=0,
    )


def test_drawdown_band_near_threshold(tmp_path: Path) -> None:
    # -12% drawdown -> "near kill threshold" wording.
    body = _build_with_equity(tmp_path, peak=100.0, equity=88.0)
    assert "near kill threshold (-15%)" in body
    assert "past market-kill" not in body
    assert "past portfolio-kill" not in body


def test_drawdown_band_past_market_kill(tmp_path: Path) -> None:
    # -17% drawdown -> "past market-kill" wording.
    body = _build_with_equity(tmp_path, peak=100.0, equity=83.0)
    assert "past market-kill threshold (-15%)" in body
    assert "new entries blocked" in body
    assert "past portfolio-kill" not in body


def test_drawdown_band_past_portfolio_kill(tmp_path: Path) -> None:
    # -33.4% drawdown (the paper-crypto reality 2026-05-23) -> portfolio-kill band.
    body = _build_with_equity(tmp_path, peak=131.32, equity=87.45)
    assert "past portfolio-kill threshold (-20%)" in body
    assert "all new entries blocked" in body
    assert "near kill threshold" not in body


# ── alerts_log integration (session 6) ──────────────────────────────────────


def _write_alerts_log(tmp_path: Path, rows: list[dict]) -> None:
    (tmp_path / "alerts_log.json").write_text(json.dumps(rows), encoding="utf-8")


def test_alerts_log_present_switches_alerts_known_on(tmp_path: Path) -> None:
    """With alerts_log.json present, the 'N/A (alerts_log not yet populated)'
    fallback disappears and real counts render."""
    _empty_db(tmp_path)
    _write_alerts_log(tmp_path, [])  # empty list -> known but 0/0/0
    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    body = daily_digest.build_digest(
        cfg, as_of=datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc),
        container_restart_count=0, yesterdays_restart_count=0,
    )
    assert "Alerts fired:      0  (open: 0, resolved: 0)" in body
    assert "alerts_log not yet populated" not in body


def test_alerts_log_window_filter(tmp_path: Path) -> None:
    """Only rows in the [as_of - 24h, as_of) window count."""
    _empty_db(tmp_path)
    as_of = datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc)
    in_window = (as_of - timedelta(hours=2)).isoformat()
    out_of_window = (as_of - timedelta(hours=48)).isoformat()
    _write_alerts_log(tmp_path, [
        {"ts": in_window, "market": "crypto", "severity": "warn",
         "message": "in", "correlation_id": "a1"},
        {"ts": in_window, "market": "crypto", "severity": "critical",
         "message": "in2", "correlation_id": "a2"},
        {"ts": out_of_window, "market": "crypto", "severity": "warn",
         "message": "stale", "correlation_id": "a0"},
    ])
    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    body = daily_digest.build_digest(
        cfg, as_of=as_of,
        container_restart_count=0, yesterdays_restart_count=0,
    )
    assert "Alerts fired:      2  (open: 2, resolved: 0)" in body


def test_alerts_log_resolution_pairs_close_correlation(tmp_path: Path) -> None:
    """A row carrying 'unresolves': <cid> in the window cancels the open
    count for that correlation_id."""
    _empty_db(tmp_path)
    as_of = datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc)
    in_window = (as_of - timedelta(hours=2)).isoformat()
    later = (as_of - timedelta(hours=1)).isoformat()
    _write_alerts_log(tmp_path, [
        {"ts": in_window, "market": "crypto", "severity": "warn",
         "message": "fired", "correlation_id": "a1"},
        {"ts": later, "market": "crypto", "severity": "info",
         "message": "cleared", "correlation_id": "a1-resolve",
         "unresolves": "a1"},
    ])
    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    body = daily_digest.build_digest(
        cfg, as_of=as_of,
        container_restart_count=0, yesterdays_restart_count=0,
    )
    assert "Alerts fired:      1  (open: 0, resolved: 1)" in body


def test_action_triggers_on_three_open_alerts(tmp_path: Path) -> None:
    _empty_db(tmp_path)
    as_of = datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc)
    in_window = (as_of - timedelta(hours=2)).isoformat()
    rows = [
        {"ts": in_window, "market": "crypto", "severity": "warn",
         "message": f"alert {i}", "correlation_id": f"cid-{i}"}
        for i in range(3)
    ]
    _write_alerts_log(tmp_path, rows)
    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    body = daily_digest.build_digest(
        cfg, as_of=as_of,
        container_restart_count=0, yesterdays_restart_count=0,
    )
    assert "3 open alerts in last 24h" in body
    assert "Action needed: NONE" not in body


def test_action_silent_on_two_open_alerts(tmp_path: Path) -> None:
    """Threshold is >=3; two open alerts must not trip the action line."""
    _empty_db(tmp_path)
    as_of = datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc)
    in_window = (as_of - timedelta(hours=2)).isoformat()
    rows = [
        {"ts": in_window, "market": "crypto", "severity": "warn",
         "message": f"alert {i}", "correlation_id": f"cid-{i}"}
        for i in range(2)
    ]
    _write_alerts_log(tmp_path, rows)
    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    body = daily_digest.build_digest(
        cfg, as_of=as_of,
        container_restart_count=0, yesterdays_restart_count=0,
    )
    assert "Action needed: NONE" in body
    assert "open alerts in last 24h" not in body


def test_action_triggers_on_consecutive_exceptions(tmp_path: Path) -> None:
    _empty_db(tmp_path)
    _fixture_with_state(
        tmp_path,
        {"C3_altcoin_reversion": {"total_exceptions": 5, "consecutive_exceptions": 2}},
        "strategy_exception_state.json",
    )
    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    body = daily_digest.build_digest(
        cfg, as_of=datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc),
        container_restart_count=0, yesterdays_restart_count=0,
    )
    assert "C3_altcoin_reversion has 2 consec exceptions" in body
    assert "Action needed: NONE" not in body


def test_action_triggers_on_manual_restart(tmp_path: Path) -> None:
    _empty_db(tmp_path)
    (tmp_path / "watchdog_heartbeat.json").write_text(
        json.dumps({"restart_count_in_window": 0, "last_decision": "ok"}),
        encoding="utf-8",
    )
    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    body = daily_digest.build_digest(
        cfg, as_of=datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc),
        container_restart_count=5,
        yesterdays_restart_count=4,  # one new restart since yesterday
    )
    assert "manual container restart" in body
    assert "Action needed: NONE" not in body


def test_action_triggers_on_share_equality(tmp_path: Path) -> None:
    _empty_db(tmp_path)
    (tmp_path / "share_equality_mismatches.json").write_text(
        json.dumps({"C3_altcoin_reversion|TON/USDT": 4}),
        encoding="utf-8",
    )
    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    body = daily_digest.build_digest(
        cfg, as_of=datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc),
        container_restart_count=0, yesterdays_restart_count=0,
    )
    assert "share-equality mismatch counter non-zero" in body


def test_action_is_none_when_nothing_breached(tmp_path: Path) -> None:
    _empty_db(tmp_path)
    (tmp_path / "state-paper").mkdir(exist_ok=True)
    (tmp_path / "state-paper" / "risk_engine_state.paper.json").write_text(
        json.dumps({"peak": 100.0, "last_equity": 99.0,  # only -1% dd
                    "last_update_ts": 1779513912.0,
                    "market_peaks": {"crypto": 100.0}}),
        encoding="utf-8",
    )
    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    body = daily_digest.build_digest(
        cfg, as_of=datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc),
        container_restart_count=0, yesterdays_restart_count=0,
    )
    assert "Action needed: NONE" in body


# ── Send guard ─────────────────────────────────────────────────────────────


def test_digest_sent_today_guard_after_send(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _empty_db(tmp_path)
    # Block the real send_alert.
    sent_calls: list[tuple[str, str]] = []

    def fake_send_alert(msg: str, market: str = "system") -> None:
        sent_calls.append((msg, market))

    import observability.alerts as alerts_mod
    monkeypatch.setattr(alerts_mod, "send_alert", fake_send_alert)

    cfg = daily_digest.DigestConfig.from_data_dir(tmp_path)
    ist_today = datetime(2026, 5, 23, 12, 0, tzinfo=daily_digest.IST).date()
    assert not daily_digest._digest_sent_today(cfg, ist_today)

    daily_digest.build_and_send_digest(
        data_dir=tmp_path,
        as_of=datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc),
        dry_run=False,
    )
    # Log should now reflect that a send (or attempted send) happened today.
    assert daily_digest._digest_sent_today(cfg, ist_today)
    # Digest archive file should exist.
    archive = tmp_path / "digests" / "2026-05-23.txt"
    assert archive.exists()
    assert "AAATS daily digest -- 2026-05-23" in archive.read_text(encoding="utf-8")
