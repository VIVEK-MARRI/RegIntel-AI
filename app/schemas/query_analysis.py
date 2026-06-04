from pydantic import BaseModel, Field


class QueryAnalysisResult(BaseModel):
    """Schema representing the result of query classification and recommended strategy.

    Attributes:
        query: The original user query text analyzed.
        query_type: Classified query type (keyword, semantic, regulation, circular, comparative, definition).
        confidence: Classification confidence score between 0.0 and 1.0.
        optimal_strategy: Recommended retrieval strategy (bm25, dense, hybrid).
    """
    query: str = Field(
        ...,
        description="The original user query text analyzed.",
        examples=["RBI Circular 17/2024", "what is KYC"],
    )
    query_type: str = Field(
        ...,
        description="Classified query type.",
        examples=["circular", "definition", "semantic"],
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Classification confidence score between 0.0 and 1.0.",
        examples=[0.95, 0.85],
    )
    optimal_strategy: str = Field(
        ...,
        description="Recommended retrieval strategy (bm25, dense, hybrid).",
        examples=["bm25", "dense", "hybrid"],
    )