import asyncio
import os

# ── Test environment overrides (must be set BEFORE any app imports) ──────────
# Force pgvector fallback so tests run on Postgres without requiring the
# pgvector extension (which may not be installed in the local/CI environment).
# Production Docker uses USE_PGVECTOR_FALLBACK=false (with the extension).
os.environ.setdefault("USE_PGVECTOR_FALLBACK", "true")

# Lift rate limit ceiling for the test suite so the M5-M8 services can be
# exercised in a single pytest run without 429s. Production keeps the
# default 60/min cap.
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

# Use mock LLM provider by default so the test suite is hermetic.
# Individual tests that need a real provider override via monkeypatch.
os.environ.setdefault("LLM_PROVIDER", "mock")

# ── Local test DB: fall back to postgres/admin if no override is set ─────────
# .env targets the Docker DB (regintel:regintel_dev_pass). For local test runs
# the actual local Postgres typically only has the postgres superuser.
# Set TEST_DATABASE_URL_SYNC in your shell to point at your real test Postgres
# instance. If unset, we fall back to the postgres/admin local dev default.
if not os.environ.get("TEST_DATABASE_URL_SYNC") and not os.environ.get("TEST_DATABASE_URL_OVERRIDE"):
    # Only apply the local default if DATABASE_URL looks like docker credentials
    _raw_db = os.environ.get("DATABASE_URL", "")
    if "regintel:" in _raw_db or "@db:" in _raw_db:
        # Docker credentials detected — force-override with local postgres for test runs.
        # Use os.environ[] (not setdefault) because the value is already set from .env.
        os.environ["DATABASE_URL"] = (
            "postgresql+asyncpg://postgres:admin@localhost:5432/regintel_db"
        )
        os.environ["DATABASE_URL_SYNC"] = (
            "postgresql+psycopg2://postgres:admin@localhost:5432/regintel_db"
        )


import pytest
import pytest_asyncio
import psycopg2
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from httpx import AsyncClient, ASGITransport
from app.core.config import settings
from app.core.database import get_db_session
from app.models.document import Base
from app.main import app

TEST_DB_NAME = "regintel_test_db"
IS_SQLITE = settings.DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    TEST_DATABASE_URL = settings.DATABASE_URL
    TEST_DATABASE_URL_SYNC = settings.DATABASE_URL_SYNC
else:
    # Priority order for test DB credentials:
    #   1. TEST_DATABASE_URL env var (explicit override — CI, Docker)
    #   2. Parse from DATABASE_URL (honours .env overrides)
    #   3. Fallback: postgres/admin@localhost (local dev default)
    #
    # The dedicated TEST_DATABASE_URL var lets CI / local dev set test
    # credentials independently of the production DATABASE_URL in .env.
    _explicit = os.environ.get("TEST_DATABASE_URL_SYNC") or os.environ.get("TEST_DATABASE_URL_OVERRIDE")
    if _explicit:
        # Ensure the test DB name is used
        import re as _re
        _explicit_sync = _explicit if "psycopg2" in _explicit else _explicit.replace(
            "postgresql+asyncpg", "postgresql+psycopg2"
        )
        TEST_DATABASE_URL_SYNC = _re.sub(r"/\w+$", f"/{TEST_DB_NAME}", _explicit_sync)
        TEST_DATABASE_URL = TEST_DATABASE_URL_SYNC.replace(
            "postgresql+psycopg2", "postgresql+asyncpg"
        )
        _db_match = _re.match(
            r"postgresql\+\w+://([^:]+):([^@]+)@([^:/]+):?(\d+)?/\w+",
            TEST_DATABASE_URL_SYNC,
        )
        if _db_match:
            _db_user, _db_pass, _db_host, _db_port = _db_match.groups()
            _db_port = _db_port or "5432"
        else:
            _db_user, _db_pass, _db_host, _db_port = "postgres", "admin", "localhost", "5432"
    else:
        import re as _re
        # Parse credentials from DATABASE_URL (set before app imports above).
        # Substitute 'db' (docker service name) with 'localhost' for local dev runs.
        _raw_url = os.environ.get("DATABASE_URL") or settings.DATABASE_URL
        _db_match = _re.match(
            r"postgresql\+\w+://([^:]+):([^@]+)@([^:/]+):?(\d+)?/\w+",
            _raw_url,
        )
        if _db_match:
            _db_user, _db_pass, _db_host, _db_port = _db_match.groups()
            _db_port = _db_port or "5432"
            # Substitute docker service name 'db' with localhost for local test runs
            if _db_host == "db":
                _db_host = "localhost"
        else:
            _db_user, _db_pass, _db_host, _db_port = "postgres", "admin", "localhost", "5432"

        TEST_DATABASE_URL = (
            f"postgresql+asyncpg://{_db_user}:{_db_pass}@{_db_host}:{_db_port}/{TEST_DB_NAME}"
        )
        TEST_DATABASE_URL_SYNC = (
            f"postgresql+psycopg2://{_db_user}:{_db_pass}@{_db_host}:{_db_port}/{TEST_DB_NAME}"

        )




@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Sets up a fresh test database for the testing session and cleans it up afterwards."""
    if IS_SQLITE:
        # SQLite: recreate the file and create all tables. No external service.
        sync_url = TEST_DATABASE_URL_SYNC
        db_path = sync_url.split("///", 1)[-1] if "///" in sync_url else ""
        if db_path and os.path.exists(db_path):
            os.remove(db_path)
        from sqlalchemy import create_engine

        sync_engine = create_engine(sync_url)
        Base.metadata.create_all(sync_engine)
        sync_engine.dispose()
        yield
        if db_path and os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass
        return

    # 1. Connect to default postgres DB and recreate the test DB
    # Use credentials derived from DATABASE_URL (set at module level above).
    _pg_connect_kwargs = dict(
        host=_db_host,
        port=int(_db_port),
        dbname="postgres",
        user=_db_user,
        password=_db_pass,
    )
    conn = psycopg2.connect(**_pg_connect_kwargs)
    conn.autocommit = True
    cur = conn.cursor()

    # Terminate active sessions on test db
    cur.execute(
        f"SELECT pg_terminate_backend(pg_stat_activity.pid) "
        f"FROM pg_stat_activity "
        f"WHERE pg_stat_activity.datname = '{TEST_DB_NAME}' AND pid <> pg_backend_pid();"
    )
    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME};")
    cur.execute(f"CREATE DATABASE {TEST_DB_NAME};")
    cur.close()
    conn.close()

    # 2. Setup tables using sync engine
    from sqlalchemy import create_engine, text

    sync_engine = create_engine(TEST_DATABASE_URL_SYNC)

    # Conditionally create vector extension if available
    with sync_engine.connect() as db_conn:
        try:
            res = db_conn.execute(
                text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
            )
            if res.scalar() is not None:
                db_conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                db_conn.commit()
        except Exception:
            pass

    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    yield

    # 3. Cleanup: drop test DB
    conn = psycopg2.connect(**_pg_connect_kwargs)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        f"SELECT pg_terminate_backend(pg_stat_activity.pid) "
        f"FROM pg_stat_activity "
        f"WHERE pg_stat_activity.datname = '{TEST_DB_NAME}' AND pid <> pg_backend_pid();"
    )
    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME};")
    cur.close()
    conn.close()


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    policy = asyncio.get_event_loop_policy()
    res_loop = policy.new_event_loop()
    yield res_loop
    res_loop.close()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides a transactional db session that rolls back after each test."""
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async_session_factory = async_sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )

    async with async_session_factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provides an AsyncClient targeting the application with injected test db session."""

    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
