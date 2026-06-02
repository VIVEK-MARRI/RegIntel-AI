from typing import List, Optional
from pydantic import BaseModel, Field

class EmbeddingValidationIssue(BaseModel):
    """Schema representing a single embedding validation issue."""
    chunk_id: Optional[str] = Field(None, description="The ID of the chunk associated with the embedding.")
    embedding_id: Optional[str] = Field(None, description="The primary key ID of the ChunkEmbedding record.")
    rule_name: str = Field(..., description="The name of the validation rule violated.")
    message: str = Field(..., description="A detailed explanation of the issue.")
    severity: str = Field("ERROR", description="Severity: ERROR or WARNING.")

class EmbeddingValidationMetrics(BaseModel):
    """Metrics calculated during the embedding quality validation run."""
    total_chunks: int = Field(..., description="Total number of chunks in the database.")
    total_embeddings: int = Field(..., description="Total embedding records evaluated.")
    embedding_coverage: float = Field(..., description="Percentage of chunks with valid COMPLETED embeddings.")
    average_vector_norm: float = Field(..., description="Average L2 norm of valid embedding vectors.")
    invalid_embedding_count: int = Field(..., description="Total count of invalid embedding records.")
    duplicate_embedding_count: int = Field(..., description="Total count of duplicate embeddings.")

class EmbeddingValidationReport(BaseModel):
    """The final embedding validation report."""
    valid: bool = Field(..., description="True if no ERROR issues were found, False otherwise.")
    issues: List[EmbeddingValidationIssue] = Field(default_factory=list, description="List of detected validation issues.")
    metrics: EmbeddingValidationMetrics = Field(..., description="Calculated embedding metrics.")
    summary: str = Field(..., description="Textual summary of the validation run.")
