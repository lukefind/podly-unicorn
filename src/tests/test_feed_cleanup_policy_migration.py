from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "s5t6u7v8w9x0_add_feed_processed_episode_retention_count.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "feed_cleanup_migration", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_schema(connection: sa.Connection) -> None:
    metadata = sa.MetaData()
    alembic_version = sa.Table(
        "alembic_version",
        metadata,
        sa.Column("version_num", sa.String(32), primary_key=True),
    )
    feed = sa.Table(
        "feed",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("rss_url", sa.Text, nullable=False),
        sa.Column("last_changed_at", sa.DateTime, nullable=True),
    )
    metadata.create_all(connection)
    connection.execute(alembic_version.insert().values(version_num="r4s5t6u7v8w9"))
    connection.execute(
        feed.insert().values(
            id=1, title="Existing feed", rss_url="https://example.com/feed.xml"
        )
    )


def _run(connection: sa.Connection, function_name: str) -> None:
    migration = _load_migration()
    migration.op = Operations(MigrationContext.configure(connection))
    getattr(migration, function_name)()


@pytest.fixture
def connection(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        _create_schema(connection)
        yield connection
    engine.dispose()


def test_upgrade_adds_nullable_column_and_preserves_existing_null_rows(connection):
    migration = _load_migration()
    assert migration.revision == "s5t6u7v8w9x0"
    assert migration.down_revision == "r4s5t6u7v8w9"
    assert (
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
        == "r4s5t6u7v8w9"
    )

    _run(connection, "upgrade")

    column = next(
        column
        for column in sa.inspect(connection).get_columns("feed")
        if column["name"] == "processed_episode_retention_count"
    )
    assert isinstance(column["type"], sa.Integer)
    assert column["nullable"] is True
    assert connection.execute(
        sa.text("SELECT processed_episode_retention_count FROM feed WHERE id = 1")
    ).scalar() is None


def test_downgrade_removes_only_the_new_column(connection):
    _run(connection, "upgrade")
    _run(connection, "downgrade")

    columns = {column["name"] for column in sa.inspect(connection).get_columns("feed")}
    assert "processed_episode_retention_count" not in columns
    assert {"id", "title", "rss_url", "last_changed_at"}.issubset(columns)
    assert connection.execute(sa.text("SELECT count(*) FROM feed")).scalar() == 1
