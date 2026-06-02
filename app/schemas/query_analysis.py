from pydantic import BaseModel, Field

class QueryAnalysisResult(BaseModel):
    """Schema representing the result of query classification and recommended strategy."""
    query: str = Field(..., description="The original user query text analyzed.")
    query_type: str = Field(..., description="Classified query type (keyword, semantic, regulation, circular, comparative, definition).")
    confidence: float = Field(..., description="Classification confidence score between 0.0 and 1.0.")
    optimal_strategy: str = Field(..., description="Determined retrieval strategy (keyword or semantic).")
