from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db_session
from app.services.document import DocumentService

async def get_document_service(
    db_session: AsyncSession = Depends(get_db_session)
) -> DocumentService:
    """Dependency injection provider for DocumentService."""
    return DocumentService(db_session)
