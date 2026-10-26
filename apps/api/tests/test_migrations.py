"""Migrations against a real PostGIS database: up, no drift from the models, and down.

Needs STARBOARD_TEST_DATABASE_URL (CI sets it for its PostGIS service); skipped otherwise.
The database it names is emptied.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

DATABASE_URL = os.environ.get("STARBOARD_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="STARBOARD_TEST_DATABASE_URL names no test database"
)


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "STARBOARD_DATABASE_URL": DATABASE_URL or ""}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_migrations_build_the_model_tables_and_come_down_again():
    down = _alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr
    up = _alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
    drift = _alembic("check")
    assert drift.returncode == 0, drift.stdout + drift.stderr
    down = _alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr
