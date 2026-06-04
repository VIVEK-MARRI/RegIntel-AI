from __future__ import annotations

from sqlalchemy import Float
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON, TypeDecorator


class PortableJSON(TypeDecorator):
    """Dialect-aware JSON type.

    Goal:
    - Preserve PostgreSQL JSONB behavior in production
    - Allow SQLite test execution using a SQLite-compatible JSON type

    PostgreSQL: JSONB
    Others (e.g., SQLite tests): JSON
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            # Ensure Postgres uses JSONB semantics
            return dialect.type_descriptor(JSONB())
        # SQLite tests (and other dialects): rely on SQLAlchemy's generic JSON
        # which remains load/dump compatible for Python dict payloads.
        return dialect.type_descriptor(JSON())


class PortableFloatArray(TypeDecorator):
    """Dialect-aware float array.

    - PostgreSQL: ARRAY(Float)
    - Other dialects (e.g., SQLite tests): JSON (stores a JSON array of floats)
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(Float))
        return dialect.type_descriptor(JSON())
