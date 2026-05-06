"""Phase κ1 — baseline v6 schema.

Revision ID: 0001
Revises: -
Create Date: 2026-05-05

Creates ALL schemas + tables that the v6 substrate depends on. After this
migration runs, the storage/dao layer can read/write the v6 substrate
without further DDL changes for the κ phase. Idempotent via
CREATE … IF NOT EXISTS where supported.

DESIGN INVARIANTS enforced at the schema level:
  - All money / price / size columns: DOUBLE PRECISION (preserves v5 float byte semantics).
  - All timestamps: TIMESTAMPTZ (UTC enforced via insertion-time helper).
  - aaats.audit_log: SHA-256 entry-hash chain, BEFORE INSERT trigger fills the chain.
  - aaats.mode_state: CHECK (id=1) — single-row enforcement.
  - aaats.orders: UNIQUE (market, client_order_id) WHERE client_order_id IS NOT NULL.
  - compliance.audit_log: BEFORE UPDATE OR DELETE trigger raises exception (append-only).
  - aaats.positions: CHECK enforcing closed/exit_*/pnl agreement.
  - aaats.tx_audit: shadow-mode-readiness transaction audit.

SAFETY:
  - downgrade() drops both schemas with CASCADE.  Use only in operator-approved
    rollback (see scripts/k1_rollback.sh + K1_MANIFEST.md).
"""

from alembic import op


# Revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


UPGRADE_SQL = r"""
-- =============================================================================
-- 0. Extensions
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;        -- digest() for SHA-256 audit chain
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";     -- gen_random_uuid() for paper_trades id

-- =============================================================================
-- 1. Schemas
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS aaats;
CREATE SCHEMA IF NOT EXISTS compliance;

-- =============================================================================
-- 2. Transaction audit  (κ1 requirement 6 — shadow-mode readiness)
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.tx_audit (
    id              BIGSERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    duration_ms     INTEGER,
    label           TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN
                      ('in_progress', 'commit', 'rollback', 'deadlock_retry')),
    affected_rows   INTEGER NOT NULL DEFAULT 0,
    error_msg       TEXT,
    pid             INTEGER,
    monotonic_ns    BIGINT
);
CREATE INDEX IF NOT EXISTS ix_tx_audit_started_at ON aaats.tx_audit (started_at DESC);
CREATE INDEX IF NOT EXISTS ix_tx_audit_status     ON aaats.tx_audit (status)
    WHERE status != 'commit';

-- =============================================================================
-- 3. Operational audit log (SHA-256 hash chain)
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.audit_log (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    market          TEXT,
    module          TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    details         JSONB NOT NULL DEFAULT '{}'::jsonb,
    result          TEXT,
    reason          TEXT,
    prev_hash       BYTEA,
    entry_hash      BYTEA NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_log_timestamp  ON aaats.audit_log (timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_audit_log_event_type ON aaats.audit_log (event_type);
CREATE INDEX IF NOT EXISTS ix_audit_log_market     ON aaats.audit_log (market) WHERE market IS NOT NULL;

-- Hash-chain trigger: computes prev_hash + entry_hash from preceding row.
CREATE OR REPLACE FUNCTION aaats.audit_log_hash_chain() RETURNS trigger AS $$
DECLARE
    last_hash BYTEA;
    payload   TEXT;
BEGIN
    -- Use FOR UPDATE to lock; serialises concurrent inserts so chain remains valid.
    SELECT entry_hash INTO last_hash
        FROM aaats.audit_log
        ORDER BY id DESC
        LIMIT 1
        FOR UPDATE;
    NEW.prev_hash := last_hash;
    -- Use deterministic UTC microsecond ISO8601 for cross-language reproducibility.
    -- (extract(epoch …)::text returns a numeric whose precision can drift when
    -- recomputed via Python float → string; the format below is identical on
    -- both sides: Postgres `to_char(..., 'YYYY-MM-DD"T"HH24:MI:SS.US')` and
    -- Python `strftime('%Y-%m-%dT%H:%M:%S.%f')` produce the same string.)
    payload := COALESCE(encode(last_hash, 'hex'), '<genesis>') || '|'
            || NEW.id::text                                   || '|'
            || to_char(NEW.timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US') || '|'
            || COALESCE(NEW.market, '')                       || '|'
            || NEW.module                                     || '|'
            || NEW.event_type                                 || '|'
            || NEW.details::text                              || '|'
            || COALESCE(NEW.result, '')                       || '|'
            || COALESCE(NEW.reason, '');
    NEW.entry_hash := digest(payload, 'sha256');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_hash_chain_trg ON aaats.audit_log;
CREATE TRIGGER audit_log_hash_chain_trg
    BEFORE INSERT ON aaats.audit_log
    FOR EACH ROW EXECUTE FUNCTION aaats.audit_log_hash_chain();

-- =============================================================================
-- 4. Halt audit (durable history)
--    Live state lives in Redis aaats:halt:requested per FAD §4.5; this table
--    is the durable transcript and the post-cutover source of truth for v5
--    backfill.
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.halt_audit (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    market          TEXT NOT NULL,
    action          TEXT NOT NULL CHECK (action IN ('halt', 'reset')),
    triggered_by    TEXT NOT NULL,
    reason          TEXT NOT NULL,
    authorized_by   TEXT
);
CREATE INDEX IF NOT EXISTS ix_halt_audit_timestamp ON aaats.halt_audit (timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_halt_audit_market    ON aaats.halt_audit (market);

-- =============================================================================
-- 5. Mode state (single-row table — CHECK enforces id=1)
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.mode_state (
    id                          INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    mode                        TEXT NOT NULL DEFAULT 'paper' CHECK (mode IN ('paper', 'live')),
    capital                     DOUBLE PRECISION NOT NULL DEFAULT 0,
    paper_trading_started_at    TIMESTAMPTZ,
    went_live_at                TIMESTAMPTZ,
    authorized_by               TEXT,
    last_updated                TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO aaats.mode_state (id, mode) VALUES (1, 'paper') ON CONFLICT (id) DO NOTHING;

-- =============================================================================
-- 6. Positions (open + closed)
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.positions (
    id              BIGSERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    market          TEXT NOT NULL,
    entry_price     DOUBLE PRECISION NOT NULL,
    shares          DOUBLE PRECISION NOT NULL,
    entry_time      TIMESTAMPTZ NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    closed          BOOLEAN NOT NULL DEFAULT FALSE,
    exit_price      DOUBLE PRECISION,
    exit_time       TIMESTAMPTZ,
    pnl             DOUBLE PRECISION,
    -- Closed positions must have all exit fields; open positions must have none.
    CONSTRAINT positions_closed_consistency CHECK (
        (closed = FALSE AND exit_price IS NULL AND exit_time IS NULL AND pnl IS NULL) OR
        (closed = TRUE  AND exit_price IS NOT NULL AND exit_time IS NOT NULL AND pnl IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS ix_positions_market_closed ON aaats.positions (market, closed);
CREATE INDEX IF NOT EXISTS ix_positions_symbol        ON aaats.positions (symbol);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_positions_open_symbol_market
    ON aaats.positions (market, symbol)
    WHERE closed = FALSE;
-- ↑ The unique-when-open index is the single-position-per-symbol invariant
--   that v5's PersistentPositionManager.open_position() enforces in code.

-- =============================================================================
-- 7. Orders (state machine)
--    UNIQUE (market, client_order_id) where client_order_id IS NOT NULL
--    is the no-duplicate invariant κ1 req 5d.
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.orders (
    id                  BIGSERIAL PRIMARY KEY,
    client_order_id     TEXT,
    market              TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    side                TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    order_type          TEXT NOT NULL,
    quantity            DOUBLE PRECISION NOT NULL CHECK (quantity > 0),
    price               DOUBLE PRECISION,
    time_in_force       TEXT,
    state               TEXT NOT NULL CHECK (state IN
                          ('CREATED','SUBMITTED','WORKING','PARTIALLY_FILLED',
                           'FILLED','CANCELLED','EXPIRED','REJECTED')),
    state_history       JSONB NOT NULL DEFAULT '[]'::jsonb,
    filled_quantity     DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_fill_price      DOUBLE PRECISION,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at        TIMESTAMPTZ,
    last_state_change   TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_orders_market_client_order_id
    ON aaats.orders (market, client_order_id)
    WHERE client_order_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_orders_market_state ON aaats.orders (market, state);
CREATE INDEX IF NOT EXISTS ix_orders_symbol       ON aaats.orders (symbol);
CREATE INDEX IF NOT EXISTS ix_orders_terminal     ON aaats.orders (state)
    WHERE state IN ('FILLED','CANCELLED','EXPIRED','REJECTED');

-- =============================================================================
-- 8. Fills (broker-confirmed, append-only)
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.fills (
    id              BIGSERIAL PRIMARY KEY,
    order_id        BIGINT NOT NULL REFERENCES aaats.orders(id) ON DELETE RESTRICT,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    quantity        DOUBLE PRECISION NOT NULL CHECK (quantity > 0),
    price           DOUBLE PRECISION NOT NULL CHECK (price >= 0),
    fee             DOUBLE PRECISION NOT NULL DEFAULT 0,
    venue_fill_id   TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_fills_order_id  ON aaats.fills (order_id);
CREATE INDEX IF NOT EXISTS ix_fills_timestamp ON aaats.fills (timestamp DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_fills_venue_id
    ON aaats.fills (venue_fill_id)
    WHERE venue_fill_id IS NOT NULL;

-- =============================================================================
-- 9. Paper trades (v5 paper_trades.db parity, append-only)
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.paper_trades (
    id              TEXT PRIMARY KEY,                -- v5 used UUID strings
    timestamp       TIMESTAMPTZ NOT NULL,
    market          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    action          TEXT NOT NULL CHECK (action IN ('BUY','SELL')),
    shares          DOUBLE PRECISION NOT NULL,
    price           DOUBLE PRECISION NOT NULL,
    value           DOUBLE PRECISION NOT NULL,
    signal          TEXT,
    regime          TEXT,
    risk_action     TEXT,
    pnl             DOUBLE PRECISION,
    note            TEXT
);
CREATE INDEX IF NOT EXISTS ix_paper_trades_timestamp     ON aaats.paper_trades (timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_paper_trades_market_symbol ON aaats.paper_trades (market, symbol);

-- =============================================================================
-- 10. Engine status (per-market cycle status)
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.engine_status (
    market              TEXT PRIMARY KEY,
    last_run            TIMESTAMPTZ NOT NULL,
    regime              TEXT,
    symbols_scanned     INTEGER NOT NULL DEFAULT 0,
    trades_today        INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL CHECK (status IN
                          ('RUNNING','OK','ERROR','HALTED','IDLE','MARKET_CLOSED')),
    error               TEXT,
    heartbeat_ts        TIMESTAMPTZ,
    cycle_count         BIGINT NOT NULL DEFAULT 0
);

-- =============================================================================
-- 11. Equity curve (drawdown source)
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.equity_curve (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    market          TEXT NOT NULL,
    equity          DOUBLE PRECISION NOT NULL,
    peak            DOUBLE PRECISION NOT NULL,
    drawdown        DOUBLE PRECISION NOT NULL,
    cycle_id        BIGINT
);
CREATE INDEX IF NOT EXISTS ix_equity_curve_market_ts ON aaats.equity_curve (market, timestamp DESC);

-- =============================================================================
-- 12. PnL attribution
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.pnl_attribution (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    trade_id        TEXT,
    market          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    strategy        TEXT,
    regime          TEXT,
    entry_price     DOUBLE PRECISION,
    exit_price      DOUBLE PRECISION,
    shares          DOUBLE PRECISION,
    pnl             DOUBLE PRECISION,
    pnl_pct         DOUBLE PRECISION,
    fees            DOUBLE PRECISION DEFAULT 0,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_pnl_market_ts ON aaats.pnl_attribution (market, timestamp DESC);

-- =============================================================================
-- 13. Slippage
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.slippage (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    market          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    expected_price  DOUBLE PRECISION NOT NULL,
    actual_price    DOUBLE PRECISION NOT NULL,
    slippage_bps    DOUBLE PRECISION NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_slippage_market_ts ON aaats.slippage (market, timestamp DESC);

-- =============================================================================
-- 14. Settlement (NSE T+1)
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.settlement (
    id              BIGSERIAL PRIMARY KEY,
    trade_id        TEXT,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    quantity        DOUBLE PRECISION NOT NULL,
    price           DOUBLE PRECISION NOT NULL,
    trade_date      DATE NOT NULL,
    settlement_date DATE NOT NULL,
    settled         BOOLEAN NOT NULL DEFAULT FALSE,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_settlement_unsettled ON aaats.settlement (settlement_date)
    WHERE settled = FALSE;

-- =============================================================================
-- 15. Partial fills
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.partial_fills (
    id              BIGSERIAL PRIMARY KEY,
    order_id        BIGINT REFERENCES aaats.orders(id) ON DELETE RESTRICT,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol          TEXT NOT NULL,
    ordered_qty     DOUBLE PRECISION NOT NULL,
    filled_qty      DOUBLE PRECISION NOT NULL,
    fill_pct        DOUBLE PRECISION NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('PENDING','COMPLETED','ABANDONED','DEAD')),
    retry_count     INTEGER NOT NULL DEFAULT 0,
    next_retry_at   TIMESTAMPTZ,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_partial_fills_status_retry ON aaats.partial_fills (status, next_retry_at)
    WHERE status = 'PENDING';

-- =============================================================================
-- 16. TIF orders
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.tif_orders (
    id              BIGSERIAL PRIMARY KEY,
    order_id        BIGINT REFERENCES aaats.orders(id) ON DELETE RESTRICT,
    tif             TEXT NOT NULL CHECK (tif IN ('GTC','GTD','IOC','FOK','DAY')),
    expires_at      TIMESTAMPTZ,
    status          TEXT NOT NULL CHECK (status IN ('ACTIVE','FILLED','CANCELLED','EXPIRED')),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_tif_orders_active_expires ON aaats.tif_orders (expires_at)
    WHERE status = 'ACTIVE';

-- =============================================================================
-- 17. Dead-letter queue
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.dlq (
    id              BIGSERIAL PRIMARY KEY,
    enqueued_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    quantity        DOUBLE PRECISION NOT NULL,
    price           DOUBLE PRECISION,
    error           TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    next_retry_at   TIMESTAMPTZ,
    status          TEXT NOT NULL CHECK (status IN ('PENDING','RESOLVED','DEAD')),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_dlq_pending_retry ON aaats.dlq (next_retry_at)
    WHERE status = 'PENDING';

-- =============================================================================
-- 18. Engine checkpoints
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.checkpoints (
    id              BIGSERIAL PRIMARY KEY,
    market          TEXT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cycle_count     BIGINT NOT NULL,
    capital         DOUBLE PRECISION NOT NULL,
    positions       JSONB NOT NULL DEFAULT '[]'::jsonb,
    total_pnl       DOUBLE PRECISION NOT NULL DEFAULT 0,
    daily_pnl       DOUBLE PRECISION NOT NULL DEFAULT 0,
    trade_count     INTEGER NOT NULL DEFAULT 0,
    regime          TEXT,
    status          TEXT NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_checkpoints_market_ts ON aaats.checkpoints (market, timestamp DESC);

-- =============================================================================
-- 19. Reconciliation runs
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.reconciliation_runs (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    market          TEXT NOT NULL,
    db_count        INTEGER NOT NULL,
    broker_count    INTEGER NOT NULL,
    drift_count     INTEGER NOT NULL DEFAULT 0,
    drift_symbols   JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings        JSONB NOT NULL DEFAULT '[]'::jsonb,
    operator_action TEXT,
    operator_signed_by TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_recon_runs_market_ts ON aaats.reconciliation_runs (market, timestamp DESC);

-- =============================================================================
-- 20. Crypto bars (OHLCV history; preserves v5 PK shape)
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.crypto_bars (
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL,
    open            DOUBLE PRECISION NOT NULL,
    high            DOUBLE PRECISION NOT NULL,
    low             DOUBLE PRECISION NOT NULL,
    close           DOUBLE PRECISION NOT NULL,
    volume          DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (symbol, timeframe, timestamp)
);

-- =============================================================================
-- 21. Funding rates (F&O / crypto perps)
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.funding_rates (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    symbol          TEXT NOT NULL,
    market          TEXT NOT NULL,
    funding_rate    DOUBLE PRECISION NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_funding_market_ts ON aaats.funding_rates (market, timestamp DESC);

-- =============================================================================
-- 22. Compliance audit (append-only — UPDATE/DELETE blocked by trigger)
-- =============================================================================
CREATE TABLE IF NOT EXISTS compliance.audit_log (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type      TEXT NOT NULL,
    description     TEXT NOT NULL,
    actor           TEXT,
    market          TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_compliance_ts        ON compliance.audit_log (timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_compliance_event     ON compliance.audit_log (event_type);

CREATE OR REPLACE FUNCTION compliance.audit_log_no_modify() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'compliance.audit_log is append-only — UPDATE/DELETE blocked';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS compliance_audit_log_no_update ON compliance.audit_log;
CREATE TRIGGER compliance_audit_log_no_update
    BEFORE UPDATE OR DELETE ON compliance.audit_log
    FOR EACH ROW EXECUTE FUNCTION compliance.audit_log_no_modify();

-- =============================================================================
-- 23. Snapshots (per-cycle informational replicas; retain 30 days)
-- =============================================================================
CREATE TABLE IF NOT EXISTS aaats.balance_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    market          TEXT NOT NULL,
    balance         DOUBLE PRECISION NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_balance_snap_ts ON aaats.balance_snapshots (timestamp DESC);

CREATE TABLE IF NOT EXISTS aaats.portfolio_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cycle_id        BIGINT,
    total_value     DOUBLE PRECISION NOT NULL,
    cash            DOUBLE PRECISION NOT NULL,
    positions_value DOUBLE PRECISION NOT NULL,
    daily_pnl       DOUBLE PRECISION,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_portfolio_snap_ts ON aaats.portfolio_snapshots (timestamp DESC);

CREATE TABLE IF NOT EXISTS aaats.risk_state_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    cycle_id        BIGINT,
    market          TEXT NOT NULL,
    portfolio_peak  DOUBLE PRECISION,
    market_peak     DOUBLE PRECISION,
    drawdown        DOUBLE PRECISION,
    halted          BOOLEAN NOT NULL DEFAULT FALSE,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_risk_snap_market_ts ON aaats.risk_state_snapshots (market, timestamp DESC);

CREATE TABLE IF NOT EXISTS aaats.alerts_history (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    source          TEXT NOT NULL,
    level           TEXT NOT NULL CHECK (level IN ('P0','P1','P2','INFO','WARN')),
    channel         TEXT,
    code            TEXT,
    title           TEXT,
    message         TEXT,
    fields          JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_alerts_hist_ts ON aaats.alerts_history (timestamp DESC);

-- =============================================================================
-- 24. Risk durable peaks (replaces v5 in-memory state — fixes RR R-?)
-- =============================================================================
-- See κ1 requirement 11: risk decisions read from Postgres, never Redis cache.
-- Redis aaats:risk:peak:* is a perf cache only; this table is the durable truth.
CREATE TABLE IF NOT EXISTS aaats.risk_peaks (
    scope           TEXT PRIMARY KEY,                    -- 'portfolio' or 'market:<m>'
    peak            DOUBLE PRECISION NOT NULL DEFAULT 0,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO aaats.risk_peaks (scope) VALUES ('portfolio') ON CONFLICT (scope) DO NOTHING;
"""


DOWNGRADE_SQL = r"""
DROP SCHEMA IF EXISTS aaats CASCADE;
DROP SCHEMA IF EXISTS compliance CASCADE;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
