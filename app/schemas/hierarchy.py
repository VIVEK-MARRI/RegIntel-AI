from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class HierarchyNode(BaseModel):
    node_id: str
    node_type: str  # document, chapter, section, subsection, clause
    title: str
    parent_id: Optional[str] = None
    page: int
    level: int
    numbering: Optional[str] = None
    children: List["HierarchyNode"] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

class DocumentHierarchyResponse(BaseModel):
    document_id: UUID
    root: HierarchyNode

    model_config = ConfigDict(from_attributes=True)
