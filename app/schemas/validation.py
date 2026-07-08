from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class ValidationIssue(BaseModel):
    """Schema representing a single chunk validation issue."""

    chunk_id: Optional[str] = Field(
        None, description="The ID of the chunk that failed validation."
    )
    rule_name: str = Field(..., description="The name of the rule that was violated.")
    message: str = Field(
        ..., description="A detailed description of the validation issue."
    )
    severity: str = Field(
        "ERROR", description="The severity of the issue (e.g., ERROR, WARNING)."
    )


class ValidationMetrics(BaseModel):
    """Schema representing quality and size metrics for the validated chunks."""

    total_chunks: int = Field(..., description="Total number of chunks validated.")
    valid_chunk_count: int = Field(
        ..., description="Number of chunks that passed all validation rules."
    )
    invalid_chunk_count: int = Field(
        ..., description="Number of chunks that failed at least one validation rule."
    )
    average_token_count: float = Field(
        0.0, description="Average token count across valid chunks."
    )
    average_char_count: float = Field(
        0.0, description="Average character size across valid chunks."
    )
    chunk_distribution: Dict[str, int] = Field(
        default_factory=dict, description="Distribution of chunks by token range."
    )


class ValidationReport(BaseModel):
    """Schema representing the final quality validation report."""

    valid: bool = Field(
        ..., description="True if no validation errors were found, False otherwise."
    )
    issues: List[ValidationIssue] = Field(
        default_factory=list, description="List of issues detected during validation."
    )
    metrics: ValidationMetrics = Field(..., description="Calculated chunk metrics.")
    summary: str = Field(..., description="Textual summary of validation results.")
