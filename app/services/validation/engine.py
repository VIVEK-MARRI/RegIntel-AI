from typing import List, Dict, Any, Optional
from app.schemas.validation import ValidationIssue, ValidationMetrics, ValidationReport
from app.services.validation.rules import (
    BaseValidationRule,
    RejectEmptyChunkRule,
    TokenThresholdRule,
    MissingSectionRule,
    DuplicateChunkRule,
    MalformedHierarchyRule,
    _get_chunk_field
)

class ChunkQualityValidator:
    """Orchestrates quality validation rules on chunks and calculates size and distribution metrics."""

    def __init__(self, rules: Optional[List[BaseValidationRule]] = None):
        """Initializes with specified rules or defaults to all standard rules."""
        if rules is not None:
            self.rules = rules
        else:
            self.rules = [
                RejectEmptyChunkRule(),
                TokenThresholdRule(min_tokens=500, max_tokens=800),
                MissingSectionRule(invalid_sections={"General"}),
                DuplicateChunkRule(),
                MalformedHierarchyRule()
            ]

    def validate_chunks(self, chunks: List[Dict[str, Any]]) -> ValidationReport:
        """Validates a batch of chunks and returns a detailed ValidationReport.

        Args:
            chunks: A list of raw or enriched chunk dictionaries.
        """
        total_chunks = len(chunks)
        invalid_indices = set()
        all_issues: List[ValidationIssue] = []

        # Run rules
        for rule in self.rules:
            # Check if the rule validates batch-wide (e.g. DuplicateChunkRule)
            if rule.name == "duplicate_chunk":
                batch_issues = rule.validate_batch(chunks)
                for issue in batch_issues:
                    all_issues.append(issue)
                    # Trace back to chunk index
                    if issue.chunk_id:
                        for idx, c in enumerate(chunks):
                            c_id = _get_chunk_field(c, "chunk_id")
                            if str(c_id) == issue.chunk_id:
                                invalid_indices.add(idx)
                                break
            else:
                # Validate chunks individually
                for idx, chunk in enumerate(chunks):
                    issue = rule.validate_chunk(chunk)
                    if issue:
                        all_issues.append(issue)
                        invalid_indices.add(idx)

        invalid_chunk_count = len(invalid_indices)
        valid_chunk_count = total_chunks - invalid_chunk_count

        # Compute averages for valid chunks only
        valid_tokens = []
        valid_chars = []
        for idx, c in enumerate(chunks):
            if idx not in invalid_indices:
                tokens = _get_chunk_field(c, "token_count")
                content = _get_chunk_field(c, "content")
                
                if tokens is not None:
                    try:
                        valid_tokens.append(int(tokens))
                    except (ValueError, TypeError):
                        pass
                if content is not None:
                    valid_chars.append(len(str(content)))

        average_token_count = (sum(valid_tokens) / len(valid_tokens)) if valid_tokens else 0.0
        average_char_count = (sum(valid_chars) / len(valid_chars)) if valid_chars else 0.0

        # Compute chunk token distribution across all chunks with a token_count
        chunk_distribution = {
            "< 100": 0,
            "100 - 300": 0,
            "300 - 500": 0,
            "500 - 800": 0,
            "> 800": 0
        }
        for c in chunks:
            tokens = _get_chunk_field(c, "token_count")
            if tokens is not None:
                try:
                    t = int(tokens)
                    if t < 100:
                        chunk_distribution["< 100"] += 1
                    elif t < 300:
                        chunk_distribution["100 - 300"] += 1
                    elif t < 500:
                        chunk_distribution["300 - 500"] += 1
                    elif t <= 800:
                        chunk_distribution["500 - 800"] += 1
                    else:
                        chunk_distribution["> 800"] += 1
                except (ValueError, TypeError):
                    pass

        # Build metrics schema
        metrics = ValidationMetrics(
            total_chunks=total_chunks,
            valid_chunk_count=valid_chunk_count,
            invalid_chunk_count=invalid_chunk_count,
            average_token_count=average_token_count,
            average_char_count=average_char_count,
            chunk_distribution=chunk_distribution
        )

        # Determine overall validity
        valid = (len(all_issues) == 0)
        
        summary = (
            f"Validated {total_chunks} chunks. "
            f"{valid_chunk_count} passed validation, "
            f"{invalid_chunk_count} failed."
        )

        return ValidationReport(
            valid=valid,
            issues=all_issues,
            metrics=metrics,
            summary=summary
        )
