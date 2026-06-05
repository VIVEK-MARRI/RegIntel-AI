from fastapi import FastAPI
from app.api.v1.documents import router as documents_router
from app.api.v1.chunks import router as chunks_router
from app.api.v1.search import search_router, embeddings_router, index_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.bm25 import router as bm25_router
from app.api.v1.retrieval import router as retrieval_router
from app.api.v1.answer_generation import router as answer_generation_router
from app.api.v1.citation import router as citation_router
from app.api.v1.confidence import router as confidence_router
from app.api.v1.hallucination import router as hallucination_router
from app.api.v1.attribution import router as attribution_router
from app.api.v1.orchestrator import router as orchestrator_router
from app.api.v1.evaluation import router as evaluation_router
from app.api.v1.answer_analytics import router as answer_analytics_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging

# Configure logging
setup_logging(level="INFO" if settings.ENV == "production" else "DEBUG")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Central document registry for RBI and SEBI documents in RegIntel AI pipeline.",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Register custom exception handlers
register_exception_handlers(app)

# Include routes
app.include_router(
    documents_router,
    prefix="/api/v1/documents",
    tags=["documents"]
)

app.include_router(
    chunks_router,
    prefix="/api/v1/chunks",
    tags=["chunks"]
)

app.include_router(
    search_router,
    prefix="/api/v1/search",
    tags=["search"]
)

app.include_router(
    embeddings_router,
    prefix="/api/v1/embeddings",
    tags=["embeddings"]
)

app.include_router(
    index_router,
    prefix="/api/v1/index",
    tags=["index"]
)

app.include_router(
    analytics_router,
    prefix="/api/v1/analytics",
    tags=["analytics"]
)

app.include_router(
    bm25_router,
    prefix="/api/v1/bm25",
    tags=["bm25"]
)

app.include_router(
    retrieval_router,
    prefix="/api/v1",
    tags=["retrieval"]
)

app.include_router(
    answer_generation_router,
    prefix="/api/v1",
    tags=["answer-generation"]
)

app.include_router(
    citation_router,
    prefix="/api/v1",
    tags=["citation"]
)

app.include_router(
    confidence_router,
    prefix="/api/v1",
    tags=["confidence"]
)

app.include_router(
    hallucination_router,
    prefix="/api/v1",
    tags=["hallucination"]
)

app.include_router(
    attribution_router,
    prefix="/api/v1",
    tags=["attribution"]
)

app.include_router(
    orchestrator_router,
    prefix="/api/v1",
    tags=["orchestrator"]
)

app.include_router(
    evaluation_router,
    prefix="/api/v1",
    tags=["evaluation"]
)

app.include_router(
    answer_analytics_router,
    prefix="/api/v1",
    tags=["answer-analytics"]
)

@app.get("/health", tags=["health"])
async def health_check():
    """Simple service health check endpoint."""
    return {"status": "healthy", "project": settings.PROJECT_NAME}
