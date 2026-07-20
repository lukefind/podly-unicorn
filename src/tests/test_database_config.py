"""Tests for database path resolution in _configure_database.

The SQLite path must honor PODLY_INSTANCE_DIR (like the podcast-data paths do)
so pointing that env var at a scratch directory redirects the database too —
which is what makes sandboxed migration testing safe.
"""

from pathlib import Path

from flask import Flask

from app import _configure_database


def test_configure_database_honors_podly_instance_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("PODLY_INSTANCE_DIR", str(tmp_path))
    app = Flask(__name__)

    _configure_database(app)

    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    expected = (tmp_path / "sqlite3.db").resolve()
    assert uri == f"sqlite:///{expected}?timeout=90"


def test_configure_database_falls_back_to_repo_instance_dir(monkeypatch):
    monkeypatch.delenv("PODLY_INSTANCE_DIR", raising=False)
    app = Flask(__name__)

    _configure_database(app)

    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    repo_instance = Path(__file__).resolve().parents[1] / "instance"
    expected = (repo_instance / "sqlite3.db").resolve()
    assert uri == f"sqlite:///{expected}?timeout=90"
