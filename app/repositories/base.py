from typing import Generic, Type, TypeVar, Optional, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.document import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    def __init__(self, model: Type[ModelType], db_session: AsyncSession):
        self.model = model
        self.db_session = db_session

    async def get(self, id: any) -> Optional[ModelType]:
        """Fetch model instance by ID."""
        return await self.db_session.get(self.model, id)

    async def list(self, skip: int = 0, limit: int = 100) -> Sequence[ModelType]:
        """Fetch multiple model instances."""
        query = select(self.model).offset(skip).limit(limit)
        result = await self.db_session.execute(query)
        return result.scalars().all()

    async def create(self, obj: ModelType) -> ModelType:
        """Create new model instance."""
        self.db_session.add(obj)
        await self.db_session.flush()
        return obj

    async def delete(self, obj: ModelType) -> None:
        """Delete model instance."""
        await self.db_session.delete(obj)
        await self.db_session.flush()
