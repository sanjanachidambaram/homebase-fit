"""Alembic environment: connects with DATABASE_URL (app/config.py) through psycopg 3. The migrations are plain SQL
(op.execute), so there is no SQLAlchemy model to autogenerate from: each schema change is a hand-written revision.
The connection is made by psycopg itself (creator=), so DATABASE_URL may be a URL or a key=value connection string."""

import psycopg
from alembic import context
from sqlalchemy import create_engine, pool

from app import config as app_config


def run_migrations_offline() -> None:   # `alembic upgrade head --sql`: print the SQL instead of running it
    context.configure(dialect_name="postgresql", literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = app_config.database_url()
    engine = create_engine("postgresql+psycopg://", poolclass=pool.NullPool,
                           creator=lambda: psycopg.connect(url, prepare_threshold=None))
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
