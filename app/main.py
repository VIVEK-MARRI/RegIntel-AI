from fastapi import FastAPI
from app.api.v1.documents import router as documents_router
from app.api.v1.chunks import router as chunks_router
from app.api.v1.search import search_router, embeddings_router, index_router
from app.api.v1.analytics import router as analytics_router
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

@app.get("/health", tags=["health"])
async def health_check():
    """Simple service health check endpoint."""
    return {"status": "healthy", "project": settings.PROJECT_NAME}
