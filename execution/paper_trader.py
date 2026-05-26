"""
Paper trade executor — writes simulated trades to data/paper_trades.db.

The Streamlit dashboard reads this DB via data_layer.py. This module is the
sole writer; the web app never writes here.

Schema v2 additions (2026-05-08):
  strategy   -- AAATS strategy ID (e.g. "C1_stat_arb", "C2_momentum", "C5b_funding_arb")
  entry_time -- ISO timestamp of position open (same as timestamp for BUY rows)
  exit_time  -- ISO timestamp of position close (NULL for open positions)
  pnl_pct    -- percentage PnL at close (NULL for open positions)
  notes      -- JSON blob: confidence, exit_reason, r_multiple, size_usd, skipped_regime
  size_usd   -- notional value of trade in USD/INR

A trades VIEW aliases paper_trades for the metrics exporter.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from foundation.logger import get_logger
from execution.idempotency import (
    dedupe_check,
    make_client_order_id,
    make_correlation_id,
)

_log = get_logger("execution", "paper_trader")

Action = Literal["BUY", "SELL"]

_CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS paper_trades ("
    "id          TEXT PRIMARY KEY,"
    "timestamp   TEXT NOT NULL,"
    "market      TEXT NOT NULL,"
    "symbol      TEXT NOT NULL,"
    "action      TEXT NOT NULL,"
    "shares      REAL NOT NULL,"
    "price       REAL NOT NULL,"
    "value       REAL NOT NULL,"
    "signal      TEXT,"
    "regime      TEXT,"
    "risk_action TEXT,"
    "pnl         REAL DEFAULT 0.0,"
    "note        TEXT,"
    "strategy    TEXT DEFAULT '',"
    "entry_time  TEXT,"
    "exit_time   TEXT,"
    "pnl_pct     REAL,"
    "notes       TEXT,"
    "size_usd    REAL DEFAULT 0.0"
    ")"
)

_VIEW_SQL = (
    "CREATE VIEW IF NOT EXISTS trades AS "
    "SELECT id, timestamp, market, symbol, action, shares, price, value, "
    "signal, regime, risk_action, pnl, note, "
    "strategy, entry_time, exit_time, pnl_pct, notes, size_usd "
    "FROM paper_trades"
)

# Migration: safely add v2 columns to any existing v1 DB
_MIGRATE_SQLS = [
    "ALTER TABLE paper_trades ADD COLUMN strategy        TEXT    DEFAULT ''",
    "ALTER TABLE paper_trades ADD COLUMN entry_time      TEXT",
    "ALTER TABLE paper_trades ADD COLUMN exit_time       TEXT",
    "ALTER TABLE paper_trades ADD COLUMN pnl_pct         REAL",
    "ALTER TABLE paper_trades ADD COLUMN notes           TEXT",
    "ALTER TABLE paper_trades ADD COLUMN size_usd        REAL    DEFAULT 0.0",
    # 2026-05-23 healer: scripts/init_db.py's CREATE schema omits
    # `value`; without this migration step a fresh DB created by
    # init_db.py FIRST (then opened by _conn) is missing the column
    # and every record_trade INSERT fails with "no such column: value".
    # Default 0.0 because ALTER TABLE ADD COLUMN cannot enforce NOT NULL
    # against existing rows; the INSERT path always passes a real value.
    "ALTER TABLE paper_trades ADD COLUMN value           REAL    DEFAULT 0.0",
    # value-with-risk_action pair: risk_action is NOT NULL in the CREATE
    # schema but absent from init_db; same healer rationale.
    "ALTER TABLE paper_trades ADD COLUMN risk_action     TEXT    DEFAULT 'ALLOW'",
    # v3 idempotency columns (gap 4) — also created via execution.idempotency
    # but kept here so a fresh DB built by paper_trader._conn() has them too.
    "ALTER TABLE paper_trades ADD COLUMN client_order_id TEXT",
    "ALTER TABLE paper_trades ADD COLUMN correlation_id  TEXT",
]


def _conn(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db_path, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute(_CREATE_SQL)
    for sql in _MIGRATE_SQLS:
        try:
            c.execute(sql)
        except sqlite3.OperationalError as exc:
            _log.debug(f"paper_trades migration noop ({sql[:40]}...): {exc}")
    # v3: UNIQUE INDEX on client_order_id — last-line dedupe guarantee
    try:
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_paper_trades_client_order_id "
            "ON paper_trades(client_order_id) WHERE client_order_id IS NOT NULL"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS ix_paper_trades_correlation_id "
            "ON paper_trades(correlation_id)"
        )
    except sqlite3.OperationalError as exc:
        _log.debug(f"paper_trades index create noop: {exc}")
    try:
        c.execute("DROP VIEW IF EXISTS trades")
        c.execute(_VIEW_SQL)
    except sqlite3.OperationalError as exc:
        _log.debug(f"paper_trades view rebuild noop: {exc}")
    c.commit()
    return c


def _check_sell_buy_share_equality(
    c: sqlite3.Connection,
    strategy: str,
    symbol: str,
    sell_shares: float,
) -> None:
    """
    Post-INSERT SELL/BUY share-equality detector (P1 guardrail, 2026-05-15).

    For each SELL row just inserted, find the FIFO-matching BUY for the same
    (strategy, symbol) — the k-th BUY in timestamp ASC order, where k = total
    SELL count for that pair (including this row). If shares differ by more
    than 1e-9, emit a warning. Detection-only: never halts, never modifies.

    The reconciler / ledger migration owns HALT decisions for share drift.
    """
    try:
        n_sells = c.execute(
            "SELECT COUNT(*) FROM paper_trades "
            "WHERE strategy = ? AND symbol = ? AND action = 'SELL'",
            (strategy, symbol),
        ).fetchone()[0]
        if n_sells <= 0:
            return
        row = c.execute(
            "SELECT shares FROM paper_trades "
            "WHERE strategy = ? AND symbol = ? AND action = 'BUY' "
            "ORDER BY timestamp ASC, id ASC LIMIT 1 OFFSET ?",
            (strategy, symbol, n_sells - 1),
        ).fetchone()
        if row is None:
            return  # orphan SELL — reconciler's problem, not this hook's
        buy_shares = float(row[0])
        delta = abs(sell_shares - buy_shares)
        if delta > 1e-9:
            _log.warning(
                "SELL/BUY share mismatch | strategy={} symbol={} "
                "buy_shares={} sell_shares={} delta={:.10f}",
                strategy,
                symbol,
                buy_shares,
                sell_shares,
                delta,
            )
            _bump_share_mismatch_counter(strategy, symbol)
    except sqlite3.OperationalError:
        # Schema variant (e.g. test DB without strategy column) — silently skip.
        return


def _bump_share_mismatch_counter(strategy: str, symbol: str) -> None:
    """Persist a per-(strategy,symbol) mismatch tally for the Prometheus exporter.

    Cross-container handoff: paper_trader (aaats-paper-crypto) writes to the
    shared data/ bind mount; metrics_exporter (aaats-metrics) reads on scrape.
    Best-effort — never blocks the trade write path.
    """
    try:
        import json as _json

        counter_path = (
            Path(__file__).resolve().parent.parent
            / "data"
            / "share_equality_mismatches.json"
        )
        state: dict[str, int] = {}
        if counter_path.exists():
            try:
                state = _json.loads(counter_path.read_text(encoding="utf-8"))
            except Exception:
                state = {}
        key = f"{strategy}|{symbol}"
        state[key] = int(state.get(key, 0)) + 1
        counter_path.write_text(_json.dumps(state), encoding="utf-8")
    except Exception:
        return


def record_trade(
    db_path: str,
    market: str,
    symbol: str,
    action: Action,
    shares: float,
    price: float,
    signal: str = "",
    regime: str = "",
    risk_action: str = "ALLOW",
    pnl: float = 0.0,
    note: str = "",
    strategy: str = "",
    entry_time: str | None = None,
    exit_time: str | None = None,
    pnl_pct: float | None = None,
    notes: dict[str, Any] | None = None,
    size_usd: float = 0.0,
    client_order_id: str | None = None,
    correlation_id: str | None = None,
    bar_ts: datetime | str | None = None,
    nonce: int = 0,
) -> str:
    """
    Insert one paper trade row. Returns the trade id (UUID4 primary key).

    Idempotency (v3 — gap 4):
      - If `client_order_id` is supplied, dedupe before insert. Duplicate
        intent returns the prior trade id and writes NOTHING new.
      - If `client_order_id` is None, derive deterministically from
        (strategy, market, symbol, action, bar_ts, nonce).
      - If `correlation_id` is None, generate a fresh uuid4 (one per intent).

    The dedupe layer + the UNIQUE INDEX in paper_trades together ensure that
    a network blip causing a retry never doubles a position.
    """
    # ── Idempotency: derive ids if caller didn't pass them ────────────────
    if client_order_id is None:
        client_order_id = make_client_order_id(
            strategy=strategy or f"{market}_directional",
            market=market,
            symbol=symbol,
            side=action,
            bar_ts=bar_ts,
            nonce=nonce,
        )
    if correlation_id is None:
        correlation_id = make_correlation_id()

    # ── Dedupe check (last-line UNIQUE INDEX is the safety net) ──────────
    existed, prior_id = dedupe_check(db_path, client_order_id)
    if existed:
        _log.warning(
            "PAPER duplicate suppressed | cli_id={} | prior_trade={} | "
            "{} {} @ {:.4f} x{:.6f} strat={}",
            client_order_id[:12],
            prior_id,
            action,
            symbol,
            price,
            shares,
            strategy or signal,
        )
        return prior_id  # caller treats this as success — same intent already recorded

    # ── Insert (regular path) ─────────────────────────────────────────────
    trade_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    value = round(shares * price, 4)

    if entry_time is None:
        entry_time = ts if action == "BUY" else None
    if size_usd == 0.0:
        size_usd = round(value, 4)

    notes_json = json.dumps(notes) if notes else None

    c = _conn(db_path)
    try:
        c.execute(
            "INSERT INTO paper_trades "
            "(id,timestamp,market,symbol,action,shares,price,value,signal,regime,"
            "risk_action,pnl,note,strategy,entry_time,exit_time,pnl_pct,notes,size_usd,"
            "client_order_id,correlation_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                trade_id,
                ts,
                market,
                symbol,
                action,
                shares,
                price,
                value,
                signal,
                regime,
                risk_action,
                pnl,
                note,
                strategy,
                entry_time,
                exit_time,
                pnl_pct,
                notes_json,
                size_usd,
                client_order_id,
                correlation_id,
            ),
        )
        c.commit()
    except sqlite3.IntegrityError as exc:
        # UNIQUE INDEX caught a race (parallel callers both passed
        # dedupe_check). Look up the winner — if found, return its id.
        # If NOT found, the IntegrityError was NOT a duplicate-race
        # but some other constraint violation (e.g. the 2026-05-23
        # bug: init_db.py declared `id INTEGER PRIMARY KEY` so writing
        # uuid strings raised "datatype mismatch", which was silently
        # treated as a duplicate and the row was never persisted).
        # Re-raise so the caller can see the failure instead of
        # accumulating orphan strategy state.
        row = c.execute(
            "SELECT id FROM paper_trades WHERE client_order_id = ?",
            (client_order_id,),
        ).fetchone()
        c.close()
        if row is None:
            _log.error(
                "PAPER record_trade IntegrityError without a winning row "
                "(client_order_id={}); re-raising — likely schema mismatch "
                "or constraint violation, NOT a duplicate race: {}",
                client_order_id[:12],
                exc,
            )
            raise
        winner = row[0]
        _log.warning(
            "PAPER duplicate race resolved by UNIQUE INDEX | cli_id={} | winner={}",
            client_order_id[:12],
            winner,
        )
        return winner
    if action == "SELL":
        _check_sell_buy_share_equality(c, strategy, symbol, shares)
    c.close()
    _log.info(
        "PAPER {} {} @ {:.4f} x{:.6f} | strat={} | regime={} | cli={} | corr={}",
        action,
        symbol,
        price,
        shares,
        strategy or signal,
        regime,
        client_order_id[:12],
        correlation_id[:8],
    )
    return trade_id


# ──────────────────────────────────────────────────────────────────────────
# Layer L5 — Ledger divergence detector (content-correctness 2026-05-24)
# ──────────────────────────────────────────────────────────────────────────
# Why this lives in paper_trader.py: the dual-ledger bug class L5 catches is
# divergence between the paper-execution layer's two outputs (paper_trades.db
# rows vs data/*_state.json strategy position files). Both are written by
# code that routes through this module's record_trade and the per-strategy
# emitters. risk/engine.py is about live risk gates (drawdown halts); ledger
# reconciliation is not its responsibility. A new top-level module was
# considered but rejected — adding cross-module imports for a concern that
# lives squarely inside paper-execution responsibilities is worse than
# expanding this file.
#
# How it differs from scripts/reconcile_intracycle.py: the existing reconciler
# runs POST-cycle, compares at the SYMBOL granularity, and HALTs the WHOLE
# runner via foundation/kill_switch on critical drift. L5 runs PRE-cycle,
# compares at the STRATEGY granularity, and halts only the offending strategy
# via risk/strategy_halt so siblings keep trading.

# Strategies whose state-file schema uses entry_alloc (pair-keyed) rather
# than size_usd (symbol-keyed). For these, the trade DB's per-symbol
# net-shares view is structurally wrong (legs are long+short, not entries),
# so we compare state's entry_alloc against the most-recent BUY-leg notional.
_PAIR_STRATEGIES: frozenset[str] = frozenset(("C1_stat_arb", "C5b_funding_arb"))

# Per-state-file → (strategy_id, notional_key) dispatch. Files that don't
# exist on a given image are silently skipped.
_STATE_FILES: dict[str, tuple[str, str]] = {
    "altcoin_reversion_state.json": ("C3_altcoin_reversion", "size_usd"),
    "bollinger_range_state.json": ("C6_bollinger_range", "size_usd"),
    "momentum_state.json": ("C2_momentum", "size_usd"),
    "stat_arb_state.json": ("C1_stat_arb", "entry_alloc"),
    "funding_arb_state.json": ("C5b_funding_arb", "size_usd"),
}

# Known strategy set for baseline-zero emission (Grafana sees "all clear"
# instead of "No-Data" when a strategy hasn't traded yet).
LEDGER_KNOWN_STRATEGIES: tuple[str, ...] = tuple(
    sid for (sid, _key) in _STATE_FILES.values()
)

# Rounding tolerance: below this, deltas are floating-point noise.
_LEDGER_ROUNDING_TOLERANCE_USD = 0.50

# Halt threshold: above this, the strategy is genuinely diverged.
_LEDGER_HALT_THRESHOLD_USD = 1.00

LEDGER_ALERT_FILENAME = "ledger_divergence_alerts.json"


class LedgerDivergenceError(RuntimeError):
    """Raised by assert_ledger_consistency_or_halt for the first strategy
    that exceeds the halt threshold. The caller is expected to catch this
    per-strategy so one bad strategy does not block its siblings — the
    halt + alert side-effects fire BEFORE the raise, so even with the
    raise being caught upstream the state mutations persist."""

    def __init__(self, strategy: str, delta_usd: float):
        super().__init__(f"{strategy}: ledger divergence ${delta_usd:.2f}")
        self.strategy = strategy
        self.delta_usd = delta_usd


def _ledger_data_dir() -> Path:
    return Path(os.environ.get("AAATS_DATA", "/app/data"))


def _read_state_notional(state_dir: Path | None = None) -> dict[str, float]:
    """Source A: per-strategy expected open notional from data/*_state.json."""
    if state_dir is None:
        state_dir = _ledger_data_dir()
    out: dict[str, float] = {}
    for fname, (strategy_id, key) in _STATE_FILES.items():
        f = state_dir / fname
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            # Some state files have been observed as [] when empty.
            out[strategy_id] = 0.0
            continue
        total = 0.0
        for pos in data.values():
            if not isinstance(pos, dict):
                continue
            try:
                total += float(pos.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
        out[strategy_id] = total
    return out


def _read_db_notional(
    db_path: str,
    pair_strategy_passthrough: dict[str, float] | None = None,
) -> dict[str, float]:
    """Source B: per-strategy open notional derived from paper_trades.db.

    Non-pair strategies: sum(net_shares × most-recent-BUY-price) over symbols.
    A position with net_shares ≤ 0 is treated as closed (skipped).

    Pair strategies (C1_stat_arb, C5b_funding_arb): trade-DB inference is
    structurally unsafe — both legs are recorded as plain BUY/SELL rows so
    the most-recent-BUY heuristic conflates LONG_A entries with LONG_B
    closing legs. Matches the reconciler's Path A posture from
    docs/known_issues/2026-05-23_btc_eth_ledger_drift.md: pair strategies
    are excluded from db-side computation; their state-file notional is
    passed through unchanged (so divergence == 0 by construction). Full
    pair-strategy divergence detection is post-soak unified-ledger work.

    pair_strategy_passthrough: caller-supplied state notionals for pair
    strategies; if provided, those values are copied through so the
    state-vs-db delta is zero. Omitting it leaves pair strategies absent
    from the result (also yielding divergence == 0 against state).
    """
    out: dict[str, float] = {}
    if not Path(db_path).exists():
        return out
    try:
        c = sqlite3.connect(db_path)
    except sqlite3.OperationalError:
        return out
    try:
        net_rows = c.execute(
            "SELECT strategy, symbol, "
            "SUM(CASE WHEN action='BUY' THEN shares ELSE -shares END) AS net_shares "
            "FROM paper_trades WHERE strategy IS NOT NULL AND strategy != '' "
            "AND strategy NOT IN ('C1_stat_arb', 'C5b_funding_arb') "
            "GROUP BY strategy, symbol"
        ).fetchall()
        last_buy_price: dict[tuple[str, str], float] = {}
        for strategy, symbol, price in c.execute(
            "SELECT strategy, symbol, price FROM paper_trades "
            "WHERE action='BUY' "
            "AND strategy NOT IN ('C1_stat_arb', 'C5b_funding_arb') "
            "ORDER BY timestamp DESC"
        ).fetchall():
            last_buy_price.setdefault((strategy, symbol), float(price))

        for strategy, symbol, net_shares in net_rows:
            if net_shares is None or float(net_shares) <= 1e-12:
                continue
            price = last_buy_price.get((strategy, symbol))
            if price is None:
                continue
            out[strategy] = out.get(strategy, 0.0) + float(net_shares) * price
    finally:
        c.close()

    # Pair strategies: pass state-side notional through unchanged.
    if pair_strategy_passthrough:
        for strategy in _PAIR_STRATEGIES:
            if strategy in pair_strategy_passthrough:
                out[strategy] = float(pair_strategy_passthrough[strategy])
    return out


def compute_ledger_divergence(
    db_path: str | None = None,
    state_dir: Path | None = None,
) -> dict[str, float]:
    """Returns {strategy: delta_usd} for any strategy where state-file notional
    differs from trade-DB-derived notional by more than $0.50 (rounding tol).

    Sign convention: positive delta means state > db (state file claims more
    open notional than the trade log supports — the more common "lost-write"
    bug); negative means db > state (orphan trade row with no state entry).
    A strategy that is flat & consistent in both views is omitted.

    Pair strategies (C1_stat_arb, C5b_funding_arb) compare state's entry_alloc
    against the most-recent BUY-leg notional — see _read_db_notional.
    """
    if db_path is None:
        db_path = os.environ.get("DB_PATH", "/app/data/paper_trades.db")
    state = _read_state_notional(state_dir=state_dir)
    db = _read_db_notional(
        db_path,
        pair_strategy_passthrough={s: state.get(s, 0.0) for s in _PAIR_STRATEGIES},
    )
    out: dict[str, float] = {}
    for s in set(state) | set(db):
        delta = state.get(s, 0.0) - db.get(s, 0.0)
        if abs(delta) > _LEDGER_ROUNDING_TOLERANCE_USD:
            out[s] = round(delta, 4)
    return out


def _write_divergence_alert(payload: dict[str, Any]) -> None:
    """Atomic temp+mv into data/ledger_divergence_alerts.json so the metrics
    exporter + Prometheus alert chain can pick it up. Cross-container handoff
    matches the data/share_equality_mismatches.json pattern."""
    try:
        f = _ledger_data_dir() / LEDGER_ALERT_FILENAME
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(f)
    except Exception as exc:
        _log.warning("ledger_divergence_alerts.json write failed: {}", exc)


def assert_ledger_consistency_or_halt(
    db_path: str | None = None,
    state_dir: Path | None = None,
) -> None:
    """Called once per cycle near the top, BEFORE any new orders.

    For each strategy whose absolute divergence exceeds $1:
      1. risk.strategy_halt.halt_strategy(...) marks it un-dispatchable.
      2. Atomically write data/ledger_divergence_alerts.json.
      3. Raise LedgerDivergenceError on the first offender (halt + alert
         side-effects persist even if the raise is caught upstream).
    For strategies in the rounding-tolerance < delta ≤ halt-threshold band,
    write a "watch_strategies" entry so the gauge surfaces the warning but
    do not halt.
    """
    from risk.strategy_halt import halt_strategy

    diverged = compute_ledger_divergence(db_path=db_path, state_dir=state_dir)
    if not diverged:
        # Clear any stale alert file so the exporter goes back to baseline-zero.
        f = _ledger_data_dir() / LEDGER_ALERT_FILENAME
        if f.exists():
            payload = {
                "last_check_utc": datetime.now(timezone.utc).isoformat(),
                "halted_strategies": {},
                "watch_strategies": {},
            }
            _write_divergence_alert(payload)
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "last_check_utc": now_iso,
        "halted_strategies": {},
        "watch_strategies": {},
    }
    first_offender: tuple[str, float] | None = None
    for strategy, delta in diverged.items():
        abs_delta = abs(delta)
        if abs_delta > _LEDGER_HALT_THRESHOLD_USD:
            reason = f"ledger divergence ${abs_delta:.2f} (state vs DB)"
            halt_strategy(strategy, reason, consecutive_exceptions=0)
            payload["halted_strategies"][strategy] = {
                "delta_usd": delta,
                "halted_at": now_iso,
                "reason": reason,
            }
            if first_offender is None:
                first_offender = (strategy, abs_delta)
        else:
            payload["watch_strategies"][strategy] = {"delta_usd": delta}

    _write_divergence_alert(payload)
    if first_offender is not None:
        s, d = first_offender
        raise LedgerDivergenceError(s, d)


# ──────────────────────────────────────────────────────────────────────────
# Layer L11 — Capital invariant guard (structural fix 2026-05-26)
# ──────────────────────────────────────────────────────────────────────────
# Closes the "silent capital drift" class of bug. Every strategy mutates
# portfolio["capital"] symmetrically (debit at entry, credit at exit + pnl).
# But there is no end-of-cycle check that asserts the books balance.
# Historical incidents (2026-05-23 phantom-ENA, 2026-05-26 morning report):
# operator sees `capital + open_positions ≠ starting_equity + realized_pnl`
# and cannot tell whether it's a real leak or a visibility gap.
#
# Definition of the invariant — at end of every cycle:
#
#   expected_capital
#     = starting_equity
#     + sum(realized_pnl from paper_trades.db, market=this market)
#     - sum(open_position_notional across ALL strategy state files)
#
# If |actual - expected| > tolerance, write an alert. If > halt threshold,
# emit a critical log line (does NOT auto-halt — operator judges first).
# Idempotent. Safe to call multiple times per cycle.
CAPITAL_INVARIANT_TOLERANCE_USD = 0.50  # rounding noise floor
CAPITAL_INVARIANT_WARN_USD = 2.00  # warn at this level
CAPITAL_INVARIANT_CRITICAL_USD = 10.00  # log critical at this level
CAPITAL_INVARIANT_ALERT_FILENAME = "capital_invariant_alerts.json"


def _read_all_open_notional(state_dir: Path) -> float:
    """Sum open-position notional across every strategy state file.

    Pair strategies use entry_alloc × 2 (long + short legs). Symbol-keyed
    strategies use size_usd. Files that don't exist contribute 0.
    """
    total = 0.0
    for fname, (_strategy_id, key) in _STATE_FILES.items():
        f = state_dir / fname
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for pos in data.values():
            if not isinstance(pos, dict):
                continue
            try:
                amount = float(pos.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            # Pair strategies: entry_alloc is per-leg, two legs open.
            multiplier = 2.0 if key == "entry_alloc" else 1.0
            total += amount * multiplier
    return total


def _read_directional_open_notional(positions_dict: dict, market: str) -> float:
    """Sum execute()-path directional positions (paper_positions.json) for
    the market. These are NOT in the strategy-state files — they're tracked
    separately by execute() via mkt_pos[symbol] = {shares, entry_price, ...}.
    """
    if not isinstance(positions_dict, dict):
        return 0.0
    mkt = positions_dict.get(market, {})
    if not isinstance(mkt, dict):
        return 0.0
    total = 0.0
    for pos in mkt.values():
        if not isinstance(pos, dict):
            continue
        try:
            shares = float(pos.get("shares", 0.0) or 0.0)
            entry_price = float(pos.get("entry_price", 0.0) or 0.0)
            total += shares * entry_price
        except (TypeError, ValueError):
            continue
    return total


def compute_capital_invariant(
    portfolio: dict,
    market: str,
    positions: dict | None = None,
    db_path: str | None = None,
    state_dir: Path | None = None,
) -> dict[str, float]:
    """Returns a dict with:
    actual_capital     — portfolio[market]["capital"]
    starting_equity    — portfolio[market]["starting_equity"]
    realized_pnl_db    — sum of pnl from paper_trades.db for market
    open_notional      — strategy_state + execute() directional positions
    expected_capital   — derived from the three above
    delta_usd          — actual - expected (positive = unexplained surplus,
                                            negative = unexplained leak)
    verdict            — "ok" | "watch" | "warn" | "critical"
    """
    if db_path is None:
        db_path = os.environ.get("DB_PATH", "/app/data/paper_trades.db")
    if state_dir is None:
        state_dir = _ledger_data_dir()

    mkt = portfolio.get(market, {}) if isinstance(portfolio, dict) else {}
    actual = float(mkt.get("capital", 0.0) or 0.0)
    starting = float(mkt.get("starting_equity", 0.0) or 0.0)

    # Realized PnL from the DB — sum over all trades for this market.
    realized = 0.0
    if Path(db_path).exists():
        try:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT COALESCE(SUM(pnl), 0.0) FROM paper_trades "
                    "WHERE market = ?",
                    (market,),
                ).fetchone()
                if row and row[0] is not None:
                    realized = float(row[0])
        except sqlite3.OperationalError:
            pass

    strategy_open = _read_all_open_notional(state_dir)
    directional_open = (
        _read_directional_open_notional(positions or {}, market) if positions else 0.0
    )
    open_notional = strategy_open + directional_open

    expected = starting + realized - open_notional
    delta = actual - expected
    abs_delta = abs(delta)

    if abs_delta <= CAPITAL_INVARIANT_TOLERANCE_USD:
        verdict = "ok"
    elif abs_delta <= CAPITAL_INVARIANT_WARN_USD:
        verdict = "watch"
    elif abs_delta <= CAPITAL_INVARIANT_CRITICAL_USD:
        verdict = "warn"
    else:
        verdict = "critical"

    return {
        "actual_capital": round(actual, 4),
        "starting_equity": round(starting, 4),
        "realized_pnl_db": round(realized, 4),
        "strategy_open_notional": round(strategy_open, 4),
        "directional_open_notional": round(directional_open, 4),
        "open_notional": round(open_notional, 4),
        "expected_capital": round(expected, 4),
        "delta_usd": round(delta, 4),
        "verdict": verdict,
    }


def assert_capital_invariant(
    portfolio: dict,
    market: str,
    positions: dict | None = None,
    db_path: str | None = None,
    state_dir: Path | None = None,
) -> dict[str, float]:
    """End-of-cycle capital invariant check. Writes alert JSON on
    watch/warn/critical. Returns the same dict as compute_capital_invariant
    so the caller can log it.

    Does NOT auto-halt — capital drift can have legitimate causes (operator
    deposit/withdrawal, mid-cycle state file corruption recovery). Halting
    on it would risk locking the operator out of a healthy bot. Instead the
    alert chain (Telegram + Grafana) surfaces it; the operator decides.
    """
    result = compute_capital_invariant(
        portfolio,
        market,
        positions=positions,
        db_path=db_path,
        state_dir=state_dir,
    )
    verdict = result["verdict"]
    delta = result["delta_usd"]

    if verdict == "ok":
        # Clear stale alert file so Grafana goes back to baseline-zero.
        f = _ledger_data_dir() / CAPITAL_INVARIANT_ALERT_FILENAME
        if f.exists():
            try:
                existing = json.loads(f.read_text(encoding="utf-8"))
                # Only overwrite if current state actually transitioned ok.
                if existing.get("verdict") != "ok":
                    payload = {
                        "last_check_utc": datetime.now(timezone.utc).isoformat(),
                        "market": market,
                        "verdict": "ok",
                        **result,
                    }
                    _write_capital_invariant_alert(payload)
            except (OSError, json.JSONDecodeError):
                pass
        return result

    # Non-OK — write alert.
    payload = {
        "last_check_utc": datetime.now(timezone.utc).isoformat(),
        "market": market,
        **result,
    }
    _write_capital_invariant_alert(payload)

    if verdict == "critical":
        _log.error(
            "[L11] CAPITAL INVARIANT CRITICAL | market=%s | delta=$%.4f | "
            "actual=$%.2f expected=$%.2f (starting=$%.2f + realized=$%.4f - open=$%.2f)",
            market,
            delta,
            result["actual_capital"],
            result["expected_capital"],
            result["starting_equity"],
            result["realized_pnl_db"],
            result["open_notional"],
        )
    elif verdict == "warn":
        _log.warning(
            "[L11] capital invariant warn | market=%s | delta=$%.4f | actual=$%.2f expected=$%.2f",
            market,
            delta,
            result["actual_capital"],
            result["expected_capital"],
        )
    else:  # watch
        _log.info(
            "[L11] capital invariant watch | market=%s | delta=$%.4f (within rounding+slip band)",
            market,
            delta,
        )

    return result


def _write_capital_invariant_alert(payload: dict[str, Any]) -> None:
    """Atomic temp+mv into data/capital_invariant_alerts.json. Cross-container
    handoff matches the L5 ledger_divergence_alerts.json pattern.
    """
    try:
        f = _ledger_data_dir() / CAPITAL_INVARIANT_ALERT_FILENAME
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(f)
    except Exception as exc:
        _log.warning("capital_invariant_alerts.json write failed: {}", exc)
