from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.v1.alerts import router as alerts_router
from app.api.v1.answer_analytics import router as answer_analytics_router
from app.api.v1.answer_generation import router as answer_generation_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.attribution import router as attribution_router
from app.api.v1.benchmark import router as benchmark_router
from app.api.v1.bm25 import router as bm25_router
from app.api.v1.changes import router as changes_router
from app.api.v1.chunks import router as chunks_router
from app.api.v1.citation import router as citation_router
from app.api.v1.confidence import router as confidence_router
from app.api.v1.conversation import router as conversation_router
from app.api.v1.copilot import router as copilot_router
from app.api.v1.copilot_analytics import router as copilot_analytics_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.documents import router as documents_router
from app.api.v1.evaluation import router as evaluation_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.hallucination import router as hallucination_router
from app.api.v1.health import router as health_router
from app.api.v1.impact import router as impact_router
from app.api.v1.ingestion import router as ingestion_router
from app.api.v1.knowledge_graph import router as knowledge_graph_router
from app.api.v1.memory import router as memory_router
from app.api.v1.monitoring import router as monitoring_router
from app.api.v1.orchestrator import router as orchestrator_router
from app.api.v1.planning import router as planning_router
from app.api.v1.reasoning import router as reasoning_router
from app.api.v1.research import router as research_router
from app.api.v1.retrieval import router as retrieval_router
from app.api.v1.search import search_router, embeddings_router, index_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.startup import on_shutdown, on_startup
from app.middleware import (
    APIKeyMiddleware,
    APIKeyStore,
    AuditLog,
    AuditLogMiddleware,
    RateLimitMiddleware,
    RequestTracingMiddleware,
    SecurityHeadersMiddleware,
    SlidingWindowRateLimiter,
)

# Configure logging
setup_logging(level="INFO" if settings.ENV == "production" else "DEBUG")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager (replaces deprecated on_event hooks).

    Everything before ``yield`` runs on startup; everything after runs on shutdown.
    """
    # ── Startup ────────────────────────────────────────────────────────
    required_env = (
        [v.strip() for v in settings.STARTUP_REQUIRED_ENV.split(",") if v.strip()]
        if settings.STARTUP_REQUIRED_ENV
        else None
    )
    on_startup(
        app=app,
        required_env=required_env,
        storage_root=Path(settings.STORAGE_ROOT),
        raise_on_error=settings.STARTUP_RAISE_ON_ERROR,
    )
    # Wire cross-module references for the admin dashboard
    try:
        from app.api.dependencies import bind_cross_module_services

        bind_cross_module_services()
    except Exception:  # pragma: no cover - non-fatal
        pass

    yield  # application is running

    # ── Shutdown ───────────────────────────────────────────────────────
    on_shutdown(app=app)


# Mirror the FastAPI version into a module-level constant so other
# components (e.g. /api/v1/system/info) can read it without importing
# the FastAPI instance (which would create a circular import).
APP_VERSION: str = "1.0.0"

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=APP_VERSION,
    description="Central document registry for RBI and SEBI documents in RegIntel AI pipeline.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# Register custom exception handlers
register_exception_handlers(app)

# Include routes
app.include_router(documents_router, prefix="/api/v1/documents", tags=["documents"])

app.include_router(chunks_router, prefix="/api/v1/chunks", tags=["chunks"])

app.include_router(search_router, prefix="/api/v1/search", tags=["search"])

app.include_router(embeddings_router, prefix="/api/v1/embeddings", tags=["embeddings"])

app.include_router(index_router, prefix="/api/v1/index", tags=["index"])

app.include_router(analytics_router, prefix="/api/v1/analytics", tags=["analytics"])

app.include_router(bm25_router, prefix="/api/v1/bm25", tags=["bm25"])

app.include_router(retrieval_router, prefix="/api/v1", tags=["retrieval"])

app.include_router(
    answer_generation_router, prefix="/api/v1", tags=["answer-generation"]
)

app.include_router(citation_router, prefix="/api/v1", tags=["citation"])

app.include_router(confidence_router, prefix="/api/v1", tags=["confidence"])

app.include_router(hallucination_router, prefix="/api/v1", tags=["hallucination"])

app.include_router(attribution_router, prefix="/api/v1", tags=["attribution"])

app.include_router(orchestrator_router, prefix="/api/v1", tags=["orchestrator"])

app.include_router(evaluation_router, prefix="/api/v1", tags=["evaluation"])

app.include_router(answer_analytics_router, prefix="/api/v1", tags=["answer-analytics"])

app.include_router(conversation_router, prefix="/api/v1", tags=["conversation"])

app.include_router(memory_router, prefix="/api/v1", tags=["memory"])

app.include_router(copilot_router, prefix="/api/v1", tags=["copilot"])

app.include_router(planning_router, prefix="/api/v1", tags=["planning"])

app.include_router(reasoning_router, prefix="/api/v1", tags=["reasoning"])

app.include_router(feedback_router, prefix="/api/v1", tags=["feedback"])

# Module 6.7 — Copilot Analytics (registered under /api/v1/copilot/* via its own prefix)
app.include_router(
    copilot_analytics_router, prefix="/api/v1", tags=["copilot-analytics"]
)

# Module 7.1 — Regulatory Monitoring Engine
app.include_router(monitoring_router, prefix="/api/v1", tags=["monitoring"])

# Module 7.2 — Automated Regulatory Ingestion
app.include_router(ingestion_router, prefix="/api/v1", tags=["ingestion"])

# Module 7.3 — Change Detection Engine
app.include_router(changes_router, prefix="/api/v1", tags=["change-detection"])

# Module 7.4 — Impact Analysis Engine
app.include_router(impact_router, prefix="/api/v1", tags=["impact-analysis"])

# Module 7.5 — Regulatory Alerting System
app.include_router(alerts_router, prefix="/api/v1", tags=["alerting"])

# Module 7.6 — Knowledge Graph Layer
app.include_router(knowledge_graph_router, prefix="/api/v1", tags=["knowledge-graph"])

# Module 7.7 — Agentic Regulatory Research
app.include_router(research_router, prefix="/api/v1", tags=["research"])

# Module 7.8 — Executive Dashboard
app.include_router(dashboard_router, prefix="/api/v1", tags=["dashboard"])

# Module 8.1 — Compliance Risk Intelligence
from app.api.v1.compliance_risk import router as compliance_risk_router  # noqa: E402

app.include_router(compliance_risk_router, prefix="/api/v1", tags=["compliance-risk"])

# Module 8.2 — Regulatory Recommendation Engine
from app.api.v1.recommendations import router as recommendations_router  # noqa: E402

app.include_router(recommendations_router, prefix="/api/v1", tags=["recommendations"])

# Module 8.3 — Risk Forecasting Engine
from app.api.v1.forecasting import router as forecasting_router  # noqa: E402

app.include_router(forecasting_router, prefix="/api/v1", tags=["forecasting"])

# Module 8.4 — Workflow Automation Platform
from app.api.v1.workflow import router as workflow_router  # noqa: E402

app.include_router(workflow_router, prefix="/api/v1", tags=["workflow"])

# Module 8.5 — Human-in-the-Loop Review
from app.api.v1.review import router as review_router  # noqa: E402

app.include_router(review_router, prefix="/api/v1", tags=["review"])

# Module 8.6 — AI Governance Layer
from app.api.v1.governance import router as governance_router  # noqa: E402

app.include_router(governance_router, prefix="/api/v1", tags=["governance"])

# Module 8.7 — Audit & Compliance Platform
from app.api.v1.audit import router as audit_router  # noqa: E402

app.include_router(audit_router, prefix="/api/v1", tags=["audit"])

# Module 8.8 — Enterprise Administration Dashboard
from app.api.v1.admin import router as admin_router  # noqa: E402

app.include_router(admin_router, prefix="/api/v1", tags=["admin"])

# Module 9 — Multi-Agent Framework
from app.api.v1.agents import router as agents_router  # noqa: E402

app.include_router(agents_router, prefix="/api/v1", tags=["agents"])

# Module 9.4-9.6 — Intelligence Agent Layer
from app.api.v1.intelligence_agents import router as intelligence_agents_router  # noqa: E402

app.include_router(
    intelligence_agents_router, prefix="/api/v1", tags=["intelligence-agents"]
)

# Module 9.7 — Audit Agent
from app.api.v1.audit_agent import router as audit_agent_router  # noqa: E402

app.include_router(audit_agent_router, prefix="/api/v1", tags=["audit-agent"])

# Module 9.8 — Multi-Agent Orchestration Platform
from app.api.v1.orchestration import router as orchestration_router  # noqa: E402

app.include_router(orchestration_router, prefix="/api/v1", tags=["orchestration"])

# Module 9.9 — Agent Analytics Platform
from app.api.v1.agent_analytics import router as agent_analytics_router  # noqa: E402

app.include_router(agent_analytics_router, prefix="/api/v1", tags=["agent-analytics"])

# Module 6.8 — Health router (liveness / readiness / deep)
app.include_router(health_router, tags=["health"])

# Module 10.5 — Benchmark & Performance Platform
app.include_router(benchmark_router, prefix="/api/v1", tags=["benchmark"])

# Module 10.6 — Security Platform
from app.api.v1.security import router as security_router  # noqa: E402
from app.security.api_gateway import APIGateway, CORSConfig, IPAllowList  # noqa: E402
from app.security.audit_review import AuditReview  # noqa: E402
from app.security.jwt_auth import JWTConfig, JWTIssuer  # noqa: E402

app.include_router(
    security_router,
    prefix="/api/v1",
    tags=["security"],
)

# ─── Module 6.8 — Production middleware ──────────────────────────────────
# Order matters: tracing wraps everything so request_id is available to
# downstream middleware; security headers apply to all responses; rate-
# limiting and audit log run per-request.

_audit_log = AuditLog(
    persist_path=Path(settings.AUDIT_LOG_PATH) if settings.AUDIT_LOG_PERSIST else None,
)

if settings.REQUEST_TRACING_ENABLED:
    app.add_middleware(RequestTracingMiddleware)

if settings.SECURITY_HEADERS_ENABLED:
    app.add_middleware(SecurityHeadersMiddleware)

if settings.RATE_LIMIT_ENABLED:
    app.add_middleware(
        RateLimitMiddleware,
        limiter=SlidingWindowRateLimiter(),
        default_limit=settings.RATE_LIMIT_PER_MINUTE,
        window_seconds=60.0,
    )

if settings.AUDIT_LOG_ENABLED:
    app.add_middleware(AuditLogMiddleware, audit_log=_audit_log)

if settings.API_KEY_AUTH_ENABLED:
    _api_key_store = APIKeyStore()
    # In production, API keys are supplied via env / secrets manager.
    # Tests construct their own stores and override middleware as needed.
    app.add_middleware(APIKeyMiddleware, store=_api_key_store, enabled=True)


# ─── Module 10.6 — Security Platform wiring ──────────────────────────
# JWT issuer + API gateway. The JWT secret is sourced from the secrets
# manager (env → file → vault); the API gateway is configured with
# strict-by-default CORS, IP allow list, and optional request signing.


def _build_security_jwt_issuer() -> JWTIssuer:
    from app.security.secrets import SecretsManager

    sm = SecretsManager(
        env_prefix="REGINTEL_",
        cache_ttl_seconds=0,
    )
    try:
        result = sm.get(
            "jwt-secret", default=__import__("os").environ.get("REGINTEL_JWT_SECRET")
        )
    except Exception:
        result = None
    if result is None:
        # Dev fallback: a strong random secret. NEVER used in production.
        from app.security.jwt_auth import generate_development_secret

        secret = generate_development_secret()
        import logging

        logging.getLogger(__name__).warning(
            "REGINTEL_JWT_SECRET is not set — generated a development secret. "
            "Set REGINTEL_JWT_SECRET (>= 32 chars) in production."
        )
        sm.set_override("jwt-secret", secret)
        result = sm.get("jwt-secret")
    return JWTIssuer(JWTConfig(secret=result.value))


_security_jwt_issuer: JWTIssuer = _build_security_jwt_issuer()
_audit_review = AuditReview(_audit_log)
if not settings.AUTH_ENABLED:
    _cors_origins = ("*",)
else:
    _cors_origins = (
        [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
        if settings.CORS_ORIGINS
        else ()
    )
_api_gateway = APIGateway(
    cors=CORSConfig(
        allowed_origins=_cors_origins, allow_credentials=bool(_cors_origins)
    ),
    ip_allow=IPAllowList.from_cidrs(default_allow=True),
)


@app.get("/", tags=["health"], include_in_schema=False)
async def root():
    return {"status": "ok", "project": settings.PROJECT_NAME, "docs": "/docs"}


@app.get("/health", tags=["health"], include_in_schema=False)
async def health_check():
    """Simple service health check endpoint (deprecated: use /health/live)."""
    return {"status": "healthy", "project": settings.PROJECT_NAME}
