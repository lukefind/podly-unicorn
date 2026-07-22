from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from flask import Flask
from flask_migrate import downgrade, upgrade

import app as app_module
from app.auth import AuthSettings
from app.extensions import db, migrate

MIGRATIONS_DIR = Path(__file__).parents[1] / "migrations"
CURRENT_MIGRATION_HEAD = "r4s5t6u7v8w9"


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _migration_app(database_path: Path) -> Flask:
    flask_app = Flask(__name__)
    flask_app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(flask_app)
    migrate.init_app(flask_app, db, directory=str(MIGRATIONS_DIR))

    # Register all model metadata before Alembic loads its environment.
    from app import models  # pylint: disable=import-outside-toplevel,unused-import

    return flask_app


def test_empty_database_upgrades_to_current_schema(tmp_path: Path) -> None:
    flask_app = _migration_app(tmp_path / "fresh.db")

    with flask_app.app_context():
        upgrade(directory=str(MIGRATIONS_DIR))

        inspector = sa.inspect(db.engine)
        tables = set(inspector.get_table_names())
        assert {
            "prompt_preset",
            "processing_statistics",
            "processing_job",
            "llm_settings",
            "llm_key_profile",
            "post",
            "feed",
        }.issubset(tables)

        assert {
            "id",
            "name",
            "description",
            "aggressiveness",
            "system_prompt",
            "user_prompt_template",
            "min_confidence",
            "is_active",
            "is_default",
            "created_at",
            "updated_at",
        }.issubset(_column_names(inspector, "prompt_preset"))
        assert {
            "post_id",
            "total_ad_segments_removed",
            "total_duration_removed_seconds",
            "original_duration_seconds",
            "processed_duration_seconds",
            "percentage_removed",
            "prompt_preset_id",
            "created_at",
            "updated_at",
        }.issubset(_column_names(inspector, "processing_statistics"))
        assert {
            "feed_id",
            "feed_title",
            "post_title",
            "trigger_source",
            "total_ad_segments_removed",
            "total_duration_removed_seconds",
            "original_duration_seconds",
            "processed_duration_seconds",
            "percentage_removed",
        }.issubset(_column_names(inspector, "processing_job"))
        assert {
            "enable_boundary_refinement",
            "enable_word_level_boundary_refiner",
        }.issubset(_column_names(inspector, "llm_settings"))
        assert {
            "processed_with_preset_id",
            "refined_ad_boundaries",
            "refined_ad_boundaries_updated_at",
        }.issubset(_column_names(inspector, "post"))
        assert "default_prompt_preset_id" in _column_names(inspector, "feed")

        migration_head = db.session.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        assert migration_head == CURRENT_MIGRATION_HEAD


def test_preset_tracking_downgrade_preserves_existing_tables_and_data(
    tmp_path: Path,
) -> None:
    flask_app = _migration_app(tmp_path / "downgrade.db")

    with flask_app.app_context():
        upgrade(revision="e2f3a4b5c6d7", directory=str(MIGRATIONS_DIR))
        db.session.execute(sa.text("""
                INSERT INTO prompt_preset (
                    name, description, aggressiveness, system_prompt,
                    user_prompt_template, min_confidence, is_active,
                    is_default, created_at, updated_at
                ) VALUES (
                    'Custom', 'keep me', 'balanced', 'system',
                    'user', 0.7, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """))
        db.session.commit()

        downgrade(revision="d1e2f3a4b5c6", directory=str(MIGRATIONS_DIR))

        inspector = sa.inspect(db.engine)
        assert "prompt_preset" in inspector.get_table_names()
        assert "processing_statistics" in inspector.get_table_names()
        assert (
            db.session.execute(
                sa.text("SELECT description FROM prompt_preset WHERE name = 'Custom'")
            ).scalar_one()
            == "keep me"
        )

        # Re-applying the repaired historical migration must tolerate the table
        # that a production database may already have from the old fallback.
        upgrade(revision="e2f3a4b5c6d7", directory=str(MIGRATIONS_DIR))
        assert (
            db.session.execute(
                sa.text("SELECT COUNT(*) FROM prompt_preset WHERE name = 'Custom'")
            ).scalar_one()
            == 1
        )


def test_startup_does_not_continue_after_migration_failure(monkeypatch) -> None:
    migration_error = RuntimeError("migration failed")
    monkeypatch.setattr(
        app_module, "upgrade", lambda: (_ for _ in ()).throw(migration_error)
    )
    create_all_calls: list[bool] = []
    monkeypatch.setattr(
        app_module.db, "create_all", lambda: create_all_calls.append(True)
    )
    monkeypatch.setattr(app_module, "_init_prompt_presets", lambda: None)
    monkeypatch.setattr(app_module, "bootstrap_admin_user", lambda _settings: None)

    auth_settings = AuthSettings(
        require_auth=False,
        admin_username="podly_admin",
        admin_password=None,
    )

    try:
        app_module._run_app_startup(auth_settings)
    except RuntimeError as exc:
        assert exc is migration_error
    else:
        raise AssertionError("startup continued after a failed migration")

    assert create_all_calls == []
