"""Alembic environment — connects to the Lakebase branch named by LAKEBASE_BRANCH_ID.

DDL is applied to whichever branch the environment points at, so the same migrations run
against feature branches locally and against `production` in CI. Credentials require live
SDK auth, so offline mode is disabled.
"""
from __future__ import annotations

from sqlalchemy import create_engine, event, pool, text

from alembic import context
from todo.config import get_settings
from todo.models import SCHEMA, Base

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    raise RuntimeError(
        "Offline mode is not supported: Lakebase credentials require live SDK auth. "
        "Run `alembic upgrade head` online with a valid Databricks profile."
    )


def run_migrations_online() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url(), poolclass=pool.NullPool)

    @event.listens_for(engine, "do_connect")
    def _refresh_oauth_password(dialect, conn_rec, cargs, cparams):
        cparams["password"] = settings.get_password()

    with engine.connect() as connection:
        # Ensure the app-owned schema exists before Alembic touches its version table.
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=SCHEMA,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
