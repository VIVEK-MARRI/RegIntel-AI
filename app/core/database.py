from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.core.config import settings

# Create async engine.
# Free hosted Postgres (Neon, Supabase, …) mandates TLS. asyncpg does not
# understand ?sslmode=… URL params, so config strips them and exposes
# DATABASE_SSL — TLS is passed via connect_args instead (default SSL
# context trusts their public CA certificates).
connect_args = {"ssl": True} if settings.DATABASE_SSL else {}
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=True if settings.ENV == "development" else False,
    future=True,
    pool_pre_ping=True,
    connect_args=connect_args,
)

# Async session factory
async_session_factory = async_sessionmaker(
    bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database sessions.

    Commit on normal exit so that data written in one request is visible
    to subsequent requests (SQLite test DB visibility).
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
