# -*- coding: utf-8 -*-
"""Test infrastructure for TRD-443 _close_roundtrips integration tests.

Spins up an ephemeral postgres:15-alpine container on a non-prod port,
applies project schema files, exposes a SQLAlchemy engine via `test_engine`
fixture, and provides `clean_tables` for per-test isolation.

Safety: defensive guards make accidental contact with the production
container/port/database physically impossible — fixture refuses to start
if any production identifier is reached by name.
"""
import subprocess
import time
import pytest
from pathlib import Path
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TEST_CONTAINER_NAME = "polymarket_test_postgres"
TEST_DB_NAME = "polymarket_test"
TEST_DB_USER = "postgres"
TEST_DB_PASSWORD = "test_only_password"  # ephemeral; not a secret
TEST_DB_PORT = 5434  # production runs on 5433 — DO NOT change to 5433

PROJECT_ROOT = Path("/root/polymarket-bot")
SCHEMA_FILES = [
    PROJECT_ROOT / "scripts" / "init_db.sql",
    PROJECT_ROOT / "scripts" / "migration_whale_trade_roundtrips.sql",
    PROJECT_ROOT / "scripts" / "migration_phase3_007_extend_checks.sql",
]

# Structural delta from migration_phase3_006_legacy_mark.sql.
# We do NOT apply 006 in full because it is a DATA migration with
# RAISE EXCEPTION expecting exactly 530 production legacy rows.
# Applied here only the schema portion (column add) for test compat.
# See HYG-NNN follow-up (TASK 6): split 006 into 006a (schema) + 006b (data).
INLINE_DDL = """
ALTER TABLE whale_trade_roundtrips
    ADD COLUMN IF NOT EXISTS is_legacy_close BOOLEAN NOT NULL DEFAULT FALSE;
"""

# ---------------------------------------------------------------------------
# Safety guards — must NEVER be relaxed without security review
# ---------------------------------------------------------------------------

PRODUCTION_CONTAINER_NAME = "polymarket_postgres"
PRODUCTION_DB_NAME = "polymarket"
PRODUCTION_DB_PORT = 5433

assert TEST_CONTAINER_NAME.startswith("polymarket_test_"), (
    f"safety: test container name must start with 'polymarket_test_'; "
    f"got: {TEST_CONTAINER_NAME!r}"
)
assert TEST_CONTAINER_NAME != PRODUCTION_CONTAINER_NAME, (
    f"safety: test container name must differ from production "
    f"({PRODUCTION_CONTAINER_NAME!r})"
)
assert TEST_DB_PORT != PRODUCTION_DB_PORT, (
    f"safety: test port {TEST_DB_PORT} must not equal production port "
    f"{PRODUCTION_DB_PORT}"
)
assert TEST_DB_NAME != PRODUCTION_DB_NAME, (
    f"safety: test DB name must differ from production "
    f"({PRODUCTION_DB_NAME!r}); got: {TEST_DB_NAME!r}"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _container_exists(name: str) -> bool:
    """Check whether a container with given name exists (running or stopped)."""
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() == name


def _remove_container(name: str):
    """Remove container. Refuses to operate on non-test names."""
    if not name.startswith("polymarket_test_"):
        raise ValueError(
            f"refusing to remove non-test container: {name!r}. "
            f"Container names must start with 'polymarket_test_'."
        )
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _wait_for_postgres(timeout: int = 30):
    """Poll psql until the specific test database is reachable.

    We cannot use pg_isready here because it only checks that the PostgreSQL
    server is listening on the port — it does NOT confirm that the database
    named in POSTGRES_DB has been created by the image init scripts.
    Using psql against the actual DB name is the only reliable signal.
    """
    start = time.time()
    last_stderr = ""
    while time.time() - start < timeout:
        result = subprocess.run(
            [
                "docker", "exec", TEST_CONTAINER_NAME,
                "psql", "-U", TEST_DB_USER, "-d", TEST_DB_NAME,
                "-c", "SELECT 1",
            ],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return
        last_stderr = result.stderr
        time.sleep(0.5)
    raise RuntimeError(
        f"postgres database {TEST_DB_NAME!r} did not become ready in {timeout}s. "
        f"Last psql stderr: {last_stderr!r}"
    )


def _apply_schema_file(schema_file: Path):
    """Copy a .sql file into the test container and execute it via psql."""
    if not schema_file.exists():
        raise RuntimeError(f"schema file missing: {schema_file}")
    subprocess.run(
        ["docker", "cp", str(schema_file), f"{TEST_CONTAINER_NAME}:/tmp/{schema_file.name}"],
        check=True, capture_output=True,
    )
    result = subprocess.run(
        [
            "docker", "exec", TEST_CONTAINER_NAME,
            "psql", "-U", TEST_DB_USER, "-d", TEST_DB_NAME,
            "-v", "ON_ERROR_STOP=1",
            "-f", f"/tmp/{schema_file.name}",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"schema apply failed for {schema_file.name}:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_engine():
    """Session-scoped ephemeral postgres test database.

    Creates a fresh postgres:15-alpine container on TEST_DB_PORT, applies
    project schema files plus the is_legacy_close column delta, yields a
    SQLAlchemy engine, and removes the container on session teardown.

    Production container (polymarket_postgres on 5433) is never touched.
    """
    # Pre-flight: remove any stale test container (only test names allowed)
    if _container_exists(TEST_CONTAINER_NAME):
        _remove_container(TEST_CONTAINER_NAME)

    # Start fresh test container
    subprocess.run(
        [
            "docker", "run", "-d",
            "--name", TEST_CONTAINER_NAME,
            "-e", f"POSTGRES_DB={TEST_DB_NAME}",
            "-e", f"POSTGRES_USER={TEST_DB_USER}",
            "-e", f"POSTGRES_PASSWORD={TEST_DB_PASSWORD}",
            "-p", f"{TEST_DB_PORT}:5432",
            "postgres:15-alpine",
        ],
        check=True, capture_output=True,
    )

    try:
        _wait_for_postgres()

        # Apply schema files in dependency order
        for schema_file in SCHEMA_FILES:
            _apply_schema_file(schema_file)

        # Apply inline DDL for the is_legacy_close column
        # (see comment on INLINE_DDL above for rationale)
        engine = create_engine(
            f"postgresql://{TEST_DB_USER}:{TEST_DB_PASSWORD}"
            f"@localhost:{TEST_DB_PORT}/{TEST_DB_NAME}"
        )
        with engine.connect() as conn:
            conn.execute(text(INLINE_DDL))
            conn.commit()
            # Smoke: confirm engine works
            assert conn.execute(text("SELECT 1")).scalar() == 1

        yield engine

        engine.dispose()
    finally:
        # Teardown — always (even on exception)
        _remove_container(TEST_CONTAINER_NAME)


@pytest.fixture
def clean_tables(test_engine):
    """Function-scoped fixture: truncate test tables before each test.

    Uses TRUNCATE ... CASCADE so FK constraints between the three core
    tables resolve automatically. Order independence guaranteed.
    """
    with test_engine.connect() as conn:
        conn.execute(text(
            "TRUNCATE whale_trade_roundtrips, whale_trades, whales CASCADE"
        ))
        conn.commit()
    yield