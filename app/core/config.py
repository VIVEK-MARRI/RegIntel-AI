from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, model_validator
from typing import Self
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


import re

_SCHEME_RE = re.compile(r"^postgres(?:ql)?(?:\+[^:/?#]+)?://", re.IGNORECASE)


def _normalise_postgres_url(url: str, driver: str) -> str:
    """Normalise a Postgres URL to a SQLAlchemy URL with the given driver.

    Managed providers (Render, Heroku, Supabase, Neon, …) hand out bare
    ``postgres://`` / ``postgresql://`` URLs. Our async engine needs
    ``postgresql+asyncpg://`` and Alembic needs ``postgresql+psycopg2://``,
    so rewrite the scheme while preserving everything else. Already-dialected
    URLs (``…+asyncpg://``, ``…+psycopg2://``) are re-targeted too — this is
    what makes the DATABASE_URL_SYNC auto-derivation work.
    """
    if not url:
        return url
    m = _SCHEME_RE.match(url)
    if m:
        return f"postgresql+{driver}://" + url[m.end():]
    return url


_SSL_TRUE = {"require", "required", "true", "1", "yes", "verify-ca", "verify-full"}


def _extract_ssl(url: str, *, strip: bool) -> tuple[str, bool]:
    """Detect an SSL requirement in a DB URL's query string.

    Returns ``(url, ssl_required)``. When ``strip`` is true the SSL params
    are removed from the URL (asyncpg rejects unknown connect kwargs, so
    the async URL goes through ``connect_args`` instead). The sync URL
    keeps ``sslmode=require`` because libpq honours it natively.
    """
    if not url or "?" not in url:
        return url, False
    try:
        parts = urlsplit(url)
    except Exception:
        return url, False
    params = parse_qsl(parts.query, keep_blank_values=True)
    kept = []
    ssl_required = False
    for key, value in params:
        low_key, low_val = key.lower(), value.lower()
        if low_key == "sslmode" and low_val in _SSL_TRUE:
            ssl_required = True
            if not strip:
                kept.append((key, value))
        elif low_key == "ssl" and low_val in _SSL_TRUE:
            # asyncpg-style flag: honour it, but only libpq understands
            # sslmode, so rewrite it for the sync URL.
            ssl_required = True
            if not strip:
                kept.append(("sslmode", "require"))
        else:
            kept.append((key, value))
    clean = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment)
    )
    # Drop a dangling "?" when nothing remains.
    if clean.endswith("?"):
        clean = clean[:-1]
    return clean, ssl_required


class Settings(BaseSettings):
    PROJECT_NAME: str = "RegIntel AI Document Registry"
    ENV: str = "development"

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:admin@localhost:5432/regintel_db",
        description="Async PostgreSQL Database URL",
    )

    DATABASE_URL_SYNC: str = Field(
        default="postgresql+psycopg2://postgres:admin@localhost:5432/regintel_db",
        description="Sync PostgreSQL Database URL for migrations",
    )

    DATABASE_SSL: bool = Field(
        default=False,
        description="Force TLS for database connections. Auto-enabled when "
        "either DATABASE_URL carries ?sslmode=require (Neon, Supabase, …).",
    )

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _coerce_async_url(cls, v: object) -> object:
        if isinstance(v, str):
            return _normalise_postgres_url(v, "asyncpg")
        return v

    @field_validator("DATABASE_URL_SYNC", mode="before")
    @classmethod
    def _coerce_sync_url(cls, v: object) -> object:
        if isinstance(v, str):
            return _normalise_postgres_url(v, "psycopg2")
        return v

    @model_validator(mode="after")
    def _derive_sync_url(self) -> Self:
        # Many deploys export only DATABASE_URL (or leave the sync var
        # empty). Derive the sync URL for Alembic whenever it is missing,
        # empty, or still the local-dev default.
        default_sync = "postgresql+psycopg2://postgres:admin@localhost:5432/regintel_db"
        async_default = "postgresql+asyncpg://postgres:admin@localhost:5432/regintel_db"
        sync_missing = (not (self.DATABASE_URL_SYNC or "").strip()) or (
            self.DATABASE_URL_SYNC == default_sync
        )
        if sync_missing and self.DATABASE_URL != async_default:
            object.__setattr__(
                self,
                "DATABASE_URL_SYNC",
                _normalise_postgres_url(self.DATABASE_URL, "psycopg2"),
            )
        # TLS: strip SSL params from the async URL (asyncpg rejects unknown
        # connect kwargs — TLS goes through connect_args instead) while the
        # sync URL keeps ?sslmode=require for libpq. Auto-enable unless the
        # operator explicitly set DATABASE_SSL.
        clean_async, async_ssl = _extract_ssl(self.DATABASE_URL, strip=True)
        clean_sync, sync_ssl = _extract_ssl(self.DATABASE_URL_SYNC, strip=False)
        object.__setattr__(self, "DATABASE_URL", clean_async)
        object.__setattr__(self, "DATABASE_URL_SYNC", clean_sync)
        if not self.DATABASE_SSL and (async_ssl or sync_ssl):
            object.__setattr__(self, "DATABASE_SSL", True)
        return self

    # Storage
    STORAGE_ROOT: str = Field(
        default="storage", description="Local storage base directory path"
    )

    # Embeddings
    EMBEDDING_MODEL_NAME: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="Name or path of the transformer model for embeddings",
    )
    EMBEDDING_DEVICE: str | None = Field(
        default=None,
        description="Computation device (cpu, cuda). Auto-detected if None",
    )
    EMBEDDING_NORMALIZE: bool = Field(
        default=True,
        description="Whether to normalize output embeddings to unit vectors",
    )
    EMBEDDING_QUERY_INSTRUCTION: str = Field(
        default="represent this query for retrieving relevant documents: ",
        description="Instruction prefix prepended to queries for BGE asymmetric retrieval",
    )
    USE_PGVECTOR_FALLBACK: bool = Field(
        default=True,
        description="Whether to fall back to sa.ARRAY(sa.Float) if the pgvector extension is not available",
    )

    # Reranker
    RERANKER_MODEL_NAME: str = Field(
        default="BAAI/bge-reranker-base",
        description="Name or path of the cross-encoder reranker model",
    )
    RERANKER_DEVICE: str | None = Field(
        default=None,
        description="Computation device for the reranker (cpu, cuda). Auto-detected if None",
    )
    RERANKER_MAX_LENGTH: int = Field(
        default=512, description="Maximum token length for reranker input pairs"
    )
    RERANKER_BATCH_SIZE: int = Field(
        default=32, description="Batch size for scoring query-chunk pairs"
    )
    RERANKER_DEFAULT_TOP_K: int = Field(
        default=5, description="Default number of top results to return after reranking"
    )
    RERANKER_SCORE_THRESHOLD: float = Field(
        default=0.0, description="Minimum reranker score to include a result"
    )

    # ─── LLM / Answer Generation (Module 5.1) ────────────────────────────────
    LLM_PROVIDER: str = Field(
        default="mock",
        description="Default LLM provider (openai | gemini | litellm | mock)",
    )
    LLM_MODEL: str = Field(
        default="gpt-4o-mini",
        description="Default LLM model identifier",
    )
    LLM_API_KEY: str = Field(
        default="",
        description="API key for the active LLM provider",
    )
    LLM_API_BASE: str | None = Field(
        default=None,
        description="Optional custom base URL for the LLM provider",
    )
    LLM_TIMEOUT_SEC: float = Field(
        default=30.0,
        ge=1.0,
        description="Per-request LLM timeout in seconds",
    )
    LLM_MAX_RETRIES: int = Field(
        default=2,
        ge=0,
        description="Number of retries on transient LLM errors",
    )
    ANSWER_DEFAULT_TEMPERATURE: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="Default sampling temperature for answer generation",
    )
    ANSWER_DEFAULT_MAX_TOKENS: int = Field(
        default=1200,
        ge=64,
        le=8000,
        description="Default max output tokens for answer generation",
    )
    ANSWER_CONTEXT_TOKEN_BUDGET: int = Field(
        default=6000,
        ge=512,
        description="Soft cap on prompt tokens reserved for retrieved-chunk context",
    )
    ANSWER_STREAMING_ENABLED: bool = Field(
        default=True,
        description="If true, the streaming endpoint is available",
    )

    # ─── Module 10 — Canonical Intelligence Pipeline ──────────────────────────
    INTELLIGENCE_TOP_K: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Default number of chunks to retrieve for the canonical intelligence endpoint",
    )
    CONFIDENCE_THRESHOLD_HIGH: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Confidence at or above this value → answer returned directly without governance review",
    )
    CONFIDENCE_THRESHOLD_LOW: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        description="Confidence below this value → governance review task created (requires_review=True)",
    )
    ABSTENTION_THRESHOLD: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Confidence below this value AND no evidence → system abstains (abstained=True)",
    )

    # ─── Module 6.8 — Production Readiness ────────────────────────────────
    RATE_LIMIT_ENABLED: bool = Field(
        default=True,
        description="If true, RateLimitMiddleware is enabled",
    )
    RATE_LIMIT_PER_MINUTE: int = Field(
        default=60,
        ge=1,
        description="Default per-minute request limit per identity (IP or API key)",
    )
    API_KEY_AUTH_ENABLED: bool = Field(
        default=False,
        description="If true, require X-Api-Key header on all non-exempt paths",
    )
    SECURITY_HEADERS_ENABLED: bool = Field(
        default=True,
        description="If true, SecurityHeadersMiddleware adds standard headers",
    )
    AUDIT_LOG_ENABLED: bool = Field(
        default=True,
        description="If true, AuditLogMiddleware records each request",
    )
    AUDIT_LOG_PERSIST: bool = Field(
        default=False,
        description="If true, audit log entries are also written to JSONL",
    )
    AUDIT_LOG_PATH: str = Field(
        default="storage/audit/audit.log",
        description="Path for the JSONL audit log when AUDIT_LOG_PERSIST is true",
    )
    REQUEST_TRACING_ENABLED: bool = Field(
        default=True,
        description="If true, RequestTracingMiddleware assigns/propagates X-Request-ID",
    )
    STARTUP_REQUIRED_ENV: str = Field(
        default="",
        description="Comma-separated list of required env vars for startup validation",
    )
    STARTUP_RAISE_ON_ERROR: bool = Field(
        default=False,
        description="If true, startup validation raises on errors",
    )

    # ─── Security ─────────────────────────────────────────────────
    AUTH_ENABLED: bool = Field(
        default=True,
        description="If false, all auth checks are bypassed for public demo mode",
    )
    CORS_ORIGINS: str = Field(
        default="",
        description="Comma-separated allowed CORS origins (empty = same-origin only)",
    )
    AUTH_MAX_FAILED_ATTEMPTS: int = Field(
        default=5,
        ge=0,
        description="Failed login attempts before temporary lockout (0 = disabled)",
    )
    AUTH_LOCKOUT_DURATION_SECONDS: int = Field(
        default=300,
        ge=1,
        description="Lockout duration in seconds after max failed attempts",
    )

    # ─── Bootstrapping & docs visibility ────────────────────────
    SEED_DEFAULT_USERS: bool = Field(
        default=False,
        description="If true, seed the dev-only default users even in production. "
        "Keep FALSE in production: the weak dev passwords must never exist there. "
        "Bootstrap the first admin via ADMIN_SEED_EMAIL/PASSWORD instead.",
    )
    ADMIN_SEED_EMAIL: str = Field(
        default="",
        description="Email of the initial admin to create on empty storage "
        "in production. Empty = seed nothing.",
    )
    ADMIN_SEED_PASSWORD: str = Field(
        default="",
        description="Password for the initial production admin (min 12 chars). "
        "Provide via env/secret manager only — never commit it.",
    )
    ENABLE_API_DOCS: bool = Field(
        default=False,
        description="Expose /docs, /redoc and /openapi.json in production. "
        "Docs are always on outside production.",
    )

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
