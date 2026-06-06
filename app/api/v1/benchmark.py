"""Re-export the benchmark router under ``app.api.v1`` for backward compat."""

from app.benchmark.api import router

__all__ = ["router"]
