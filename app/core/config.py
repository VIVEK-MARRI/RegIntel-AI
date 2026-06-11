from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    PROJECT_NAME: str = "RegIntel AI Document Registry"
    ENV: str = "development"
    
    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:admin@localhost:5432/regintel_db",
        description="Async PostgreSQL Database URL"
    )
    
    DATABASE_URL_SYNC: str = Field(
        default="postgresql+psycopg2://postgres:admin@localhost:5432/regintel_db",
        description="Sync PostgreSQL Database URL for migrations"
    )

    # Storage
    STORAGE_ROOT: str = Field(
        default="storage",
        description="Local storage base directory path"
    )

    # Embeddings
    EMBEDDING_MODEL_NAME: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="Name or path of the transformer model for embeddings"
    )
    EMBEDDING_DEVICE: str | None = Field(
        default=None,
        description="Computation device (cpu, cuda). Auto-detected if None"
    )
    EMBEDDING_NORMALIZE: bool = Field(
        default=True,
        description="Whether to normalize output embeddings to unit vectors"
    )
    EMBEDDING_QUERY_INSTRUCTION: str = Field(
        default="represent this query for retrieving relevant documents: ",
        description="Instruction prefix prepended to queries for BGE asymmetric retrieval"
    )
    USE_PGVECTOR_FALLBACK: bool = Field(
        default=True,
        description="Whether to fall back to sa.ARRAY(sa.Float) if the pgvector extension is not available"
    )

    # Reranker
    RERANKER_MODEL_NAME: str = Field(
        default="BAAI/bge-reranker-base",
        description="Name or path of the cross-encoder reranker model"
    )
    RERANKER_DEVICE: str | None = Field(
        default=None,
        description="Computation device for the reranker (cpu, cuda). Auto-detected if None"
    )
    RERANKER_MAX_LENGTH: int = Field(
        default=512,
        description="Maximum token length for reranker input pairs"
    )
    RERANKER_BATCH_SIZE: int = Field(
        default=32,
        description="Batch size for scoring query-chunk pairs"
    )
    RERANKER_DEFAULT_TOP_K: int = Field(
        default=5,
        description="Default number of top results to return after reranking"
    )
    RERANKER_SCORE_THRESHOLD: float = Field(
        default=0.0,
        description="Minimum reranker score to include a result"
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
