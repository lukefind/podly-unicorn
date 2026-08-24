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
        sa.Column("alt_id", sa.Text, nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("author", sa.Text, nullable=True),
        sa.Column("rss_url", sa.Text, nullable=False, unique=True),
        sa.Column("image_url", sa.Text, nullable=True),
        sa.Column(
            "default_prompt_preset_id",
            sa.Integer,
            sa.ForeignKey(
                "prompt_preset.id", name="fk_feed_default_prompt_preset_id"
            ),
            nullable=True,
        ),
        sa.Column("is_hidden", sa.Boolean, nullable=False, default=False),
        sa.Column("last_changed_at", sa.DateTime, nullable=True),
    )
    prompt_preset = sa.Table(
        "prompt_preset", metadata, sa.Column("id", sa.Integer, primary_key=True)
    )
    metadata.create_all(connection)
    connection.execute(prompt_preset.insert().values(id=1))
    connection.execute(alembic_version.insert().values(version_num="r4s5t6u7v8w9"))
    connection.execute(
        feed.insert().values(
            id=1,
            alt_id="legacy-feed",
            title="Existing feed",
            description="Existing description",
            author="Existing author",
            rss_url="https://example.com/feed.xml",
            image_url="https://example.com/image.jpg",
            default_prompt_preset_id=1,
            is_hidden=False,
            last_changed_at=None,
        )
    )


def _run(connection: sa.Connection, function_name: str) -> None:
    migration = _load_migration()
    migration.op = Operations(MigrationContext.configure(connection))
    getattr(migration, function_name)()


def _feed_schema(connection: sa.Connection):
    inspector = sa.inspect(connection)
    columns = {
        column["name"]: (str(column["type"]), column["nullable"])
        for column in inspector.get_columns("feed")
    }
    unique_constraints = {
        (constraint.get("name"), tuple(constraint.get("column_names") or []))
        for constraint in inspector.get_unique_constraints("feed")
    }
    indexes = {
        (
            index["name"],
            tuple(index.get("column_names") or []),
            index.get("unique", False),
        )
        for index in inspector.get_indexes("feed")
    }
    foreign_keys = {
        (
            foreign_key.get("name"),
            tuple(foreign_key.get("constrained_columns") or []),
            foreign_key["referred_table"],
            tuple(foreign_key.get("referred_columns") or []),
        )
        for foreign_key in inspector.get_foreign_keys("feed")
    }
    return columns, unique_constraints, indexes, foreign_keys


def _feed_row(connection: sa.Connection):
    return connection.execute(
        sa.text("SELECT * FROM feed WHERE id = 1")
    ).mappings().one()


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
    original_schema = _feed_schema(connection)
    original_row = _feed_row(connection)

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

    upgraded_schema = _feed_schema(connection)
    assert upgraded_schema[0].keys() == original_schema[0].keys() | {
        "processed_episode_retention_count"
    }
    assert upgraded_schema[1:] == original_schema[1:]
    upgraded_row = _feed_row(connection)
    assert {name: upgraded_row[name] for name in original_row} == dict(original_row)


def test_downgrade_removes_only_the_new_column(connection):
    original_schema = _feed_schema(connection)
    original_row = _feed_row(connection)
    _run(connection, "upgrade")
    _run(connection, "downgrade")

    assert _feed_schema(connection) == original_schema
    assert _feed_row(connection) == original_row
