from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "r3s4t5u6v7w8_make_user_download_post_id_nullable.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("nullable_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_schema(connection: sa.Connection) -> None:
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, sa.Column("id", sa.Integer, primary_key=True))
    feed = sa.Table("feed", metadata, sa.Column("id", sa.Integer, primary_key=True))
    post = sa.Table(
        "post",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("feed_id", sa.Integer, sa.ForeignKey("feed.id"), nullable=False),
    )
    downloads = sa.Table(
        "user_download",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=True),
        sa.Column("post_id", sa.Integer, nullable=False),
        sa.Column("feed_id", sa.Integer, nullable=True),
        sa.Column("downloaded_at", sa.DateTime, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], [users.c.id], name="fk_user_download_user_id"
        ),
        sa.ForeignKeyConstraint(
            ["post_id"], [post.c.id], name="fk_user_download_post_id"
        ),
        sa.ForeignKeyConstraint(
            ["feed_id"], [feed.c.id], name="fk_user_download_feed_id"
        ),
    )
    sa.Index("ix_user_download_post_id", downloads.c.post_id)
    sa.Index("ix_user_download_feed_id", downloads.c.feed_id)
    sa.Index(
        "ix_user_download_user_date", downloads.c.user_id, downloads.c.downloaded_at
    )
    metadata.create_all(connection)
    connection.execute(feed.insert().values(id=1))
    connection.execute(post.insert().values(id=1, feed_id=1))
    connection.execute(
        downloads.insert().values(
            id=1,
            post_id=1,
            feed_id=1,
            downloaded_at=datetime(2026, 7, 20, 9, 0),
        )
    )


def _run(connection: sa.Connection, function_name: str) -> None:
    migration = _load_migration()
    migration.op = Operations(MigrationContext.configure(connection))
    getattr(migration, function_name)()


def _post_id_nullable(connection: sa.Connection) -> bool:
    columns = sa.inspect(connection).get_columns("user_download")
    return next(column for column in columns if column["name"] == "post_id")["nullable"]


def _schema_details(connection: sa.Connection):
    inspector = sa.inspect(connection)
    indexes = {index["name"] for index in inspector.get_indexes("user_download")}
    foreign_keys = {
        (
            tuple(foreign_key["constrained_columns"]),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
        )
        for foreign_key in inspector.get_foreign_keys("user_download")
    }
    return indexes, foreign_keys


@pytest.fixture
def connection(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        _create_schema(connection)
        yield connection
    engine.dispose()


def test_upgrade_preserves_data_indexes_and_foreign_keys(connection) -> None:
    expected_schema = _schema_details(connection)

    _run(connection, "upgrade")

    assert _post_id_nullable(connection) is True
    assert (
        connection.execute(sa.text("SELECT count(*) FROM user_download")).scalar() == 1
    )
    assert _schema_details(connection) == expected_schema


def test_downgrade_restores_not_null_and_preserves_schema(connection) -> None:
    expected_schema = _schema_details(connection)
    _run(connection, "upgrade")

    _run(connection, "downgrade")

    assert _post_id_nullable(connection) is False
    assert (
        connection.execute(sa.text("SELECT count(*) FROM user_download")).scalar() == 1
    )
    assert _schema_details(connection) == expected_schema


def test_downgrade_refuses_to_destroy_feed_level_events(connection) -> None:
    _run(connection, "upgrade")
    connection.execute(sa.text("""
            INSERT INTO user_download (id, post_id, feed_id, downloaded_at)
            VALUES (2, NULL, 1, '2026-07-20 10:00:00')
            """))

    with pytest.raises(RuntimeError, match="NULL post_id"):
        _run(connection, "downgrade")

    assert _post_id_nullable(connection) is True
    assert (
        connection.execute(sa.text("SELECT count(*) FROM user_download")).scalar() == 2
    )
