from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict

class StructureElement(BaseModel):
    type: str  # title, chapter, heading, section, subsection, clause
    title: str
    page: int
    level: int
    numbering: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class DocumentStructureResponse(BaseModel):
    document_id: UUID
    structure: List[StructureElement]

    model_config = ConfigDict(from_attributes=True)
