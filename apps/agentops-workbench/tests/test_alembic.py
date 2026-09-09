"""TDD regression - alembic config + initial migration."""
from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def alembic_config(repo_root: Path) -> Config:
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    cfg.set_main_option(
        "sqlalchemy.url", "sqlite:///" + str(repo_root / "agentops.db")
    )
    return cfg


def test_alembic_config_loads(alembic_config: Config) -> None:
    assert alembic_config.get_main_option("script_location") is not None


def test_initial_migration_present(repo_root: Path) -> None:
    versions = repo_root / "alembic" / "versions"
    assert versions.exists()
    files = list(versions.glob("*.py"))
    assert any("0001" in f.name for f in files), "missing 0001_initial.py"
