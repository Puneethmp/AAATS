"""Alembic env.py — reads DSN from AAATS_PG_DSN env var.

Migrations run synchronously via psycopg2; runtime is async via asyncpg
(storage/postgres.py). Two drivers, by design — the sync path keeps
migrations operator-readable and easier to roll back.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Read DSN from env (mandatory). Refuse to run with the placeholder from alembic.ini.
dsn = os.environ.get("AAATS_PG_DSN", "")
if not dsn:
    raise RuntimeError(
        "AAATS_PG_DSN env var is required for migrations. "
        "Example: postgresql+psycopg2://aaats:<password>@localhost:5432/aaats"
    )
config.set_main_option("sqlalchemy.url", dsn)

target_metadata = None  # raw-SQL migrations (op.execute) — no SQLAlchemy models in κ1


def run_migrations_offline() -> None:
    context.configure(
        url=dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transaction_per_migration=True,
            transactional_ddl=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
