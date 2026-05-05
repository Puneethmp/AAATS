# AAATS v6 storage layer

Phase κ1 deliverable. Standalone Python package; no v5 module imports it.
Hosts the Postgres + Redis access primitives the κ4 engine container will
use. Until κ3 / Gate κ-A, no protected code references this package.

## Layout

```
storage/
├── __init__.py
├── clock.py            UTC + monotonic helpers (κ1 req 9)
├── postgres.py         asyncpg pool + transaction primitive + tx_audit hook
├── redis.py            aioredis wrapper + KEYS namespace registry
├── audit.py            tracking helpers for storage.postgres tx audit
├── requirements.txt    pinned deps (asyncpg, redis, alembic, psycopg2-binary)
└── dao/
    ├── audit_log.py        SHA-256 chain DAO (κ1 req 5e)
    ├── halt.py             durable halt CST + Redis cache (κ1 req 11)
    ├── orders.py           FSM + unique client_order_id (κ1 req 5c, 5d)
    ├── positions.py        read_durable / read_cached split (κ1 req 11)
    ├── reconciliation.py   reconciliation-before-close gate (κ1 req 5b)
    ├── mode.py             single-row mode_state DAO
    ├── heartbeat.py        Redis-only HB
    ├── paper_trades.py     v5 parity append-only
    └── engine_status.py    per-market upsert
```

## Usage (engine, κ4)

```python
from storage import postgres as pg, redis as r
from storage.dao import positions, orders, halt, audit_log

# Bootstrap (in lifespan):
await pg.init_pool()
await r.init_redis()

# Risk-safe read:
state = await halt.read_durable_current_state("crypto")
if state["halted"]:
    return

# Write under audited transaction:
async with pg.transaction("orders.create_via_engine") as conn:
    oid = await orders.create(market="crypto", symbol="BTC/USDT", ...)

# Cached fast read (dashboards/bot only):
cached_positions = await positions.read_cached_open("crypto")
```

## Schema reference

Schema is defined in `v6-stack/alembic/versions/0001_baseline.py`. Quick map:

| Table | Purpose | Notes |
|---|---|---|
| aaats.tx_audit             | per-transaction audit (κ1 req 6) | written by storage.postgres |
| aaats.audit_log            | operational hash-chain log | trigger fills prev_hash + entry_hash |
| aaats.halt_audit           | halt/reset history (durable CST for halt state) | risk reads from here |
| aaats.mode_state           | paper / live (single row, CHECK id=1) | |
| aaats.positions            | open + closed positions | unique-when-open partial index |
| aaats.orders               | order FSM + state_history JSONB | unique (market, client_order_id) |
| aaats.fills                | broker-confirmed fills (append-only) | unique venue_fill_id |
| aaats.paper_trades         | v5 parity, append-only | UUID id |
| aaats.engine_status        | per-market cycle status | upsert by market PK |
| aaats.equity_curve         | drawdown source | per-market history |
| aaats.pnl_attribution      | per-trade attribution | |
| aaats.slippage             | execution-quality history | |
| aaats.settlement           | NSE T+1 | |
| aaats.partial_fills        | partial-fill state | retry queue |
| aaats.tif_orders           | TIF state | expiry scheduler |
| aaats.dlq                  | dead-letter queue | exponential backoff (no jitter) |
| aaats.checkpoints          | engine recovery checkpoints | per-market FIFO |
| aaats.reconciliation_runs  | reconciliation history | feeds the "must reconcile" gate |
| aaats.crypto_bars          | OHLCV cache | PK (symbol, timeframe, timestamp) |
| aaats.funding_rates        | F&O / perp funding | |
| aaats.balance_snapshots    | balance history (replicas) | |
| aaats.portfolio_snapshots  | portfolio history (replicas) | |
| aaats.risk_state_snapshots | risk state history (replicas) | |
| aaats.alerts_history       | alert sample (optional, sampled) | |
| aaats.risk_peaks           | DURABLE drawdown peaks | fixes v5 in-memory loss |
| compliance.audit_log       | immutable compliance log | UPDATE/DELETE blocked by trigger |

## Redis key registry

See `storage/redis.py::KEYS`. All keys begin with `aaats:`. Three categories:

- Heartbeats `aaats:hb:*` (TTL 90s)
- Control `aaats:halt:requested`, `aaats:mode`, etc.
- Caches `aaats:cache:*` (read-only for risk path; bot/dashboards consume)
- Buckets `aaats:bucket:{exchange,anthropic,telegram}` (FAD §4.5)

## Critical invariant (κ1 req 11)

**Risk decisions read durable Postgres truth, never Redis cache.**

- `halt.read_durable_current_state()` → Postgres only.
- `positions.read_durable_*()`         → Postgres only.
- `orders.read_durable_*()`            → Postgres only.
- `mode.read_durable()`                → Postgres only.

Cached reads exist (`positions.read_cached_open`, `mode.cache_set`) but are
read-only for dashboards / bot. The risk-engine adapter built in κ3 will
import only `read_durable_*`. This will be reviewed in Gate κ-A.

## Tests

`v6-stack/tests/invariants/` codifies the 5 κ1-req-5 invariants and the κ1-req-9 clock invariants. Run:

```bash
AAATS_PG_TEST_DSN=postgresql://aaats:<pwd>@localhost:5432/aaats_test \
  pytest v6-stack/tests/invariants/ -v
```
