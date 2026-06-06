"""Re-export the security router under ``app.api.v1`` for backward compat."""

from app.security.api import router

__all__ = ["router"]
