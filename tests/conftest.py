import asyncio
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
TEST_DATABASE_URL = f"postgresql+asyncpg://postgres:admin@localhost:5432/{TEST_DB_NAME}"
TEST_DATABASE_URL_SYNC = f"postgresql+psycopg2://postgres:admin@localhost:5432/{TEST_DB_NAME}"

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Sets up a fresh test database for the testing session and cleans it up afterwards."""
    # 1. Connect to default postgres DB and recreate the test DB
    conn = psycopg2.connect(host="localhost", dbname="postgres", user="postgres", password="admin")
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
            res = db_conn.execute(text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"))
            if res.scalar() is not None:
                db_conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                db_conn.commit()
        except Exception:
            pass
            
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    
    yield
    
    # 3. Cleanup: drop test DB
    conn = psycopg2.connect(host="localhost", dbname="postgres", user="postgres", password="admin")
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
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False
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
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
        
    app.dependency_overrides.clear()
