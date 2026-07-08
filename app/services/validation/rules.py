from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Set
import re
from app.schemas.validation import ValidationIssue


def _get_chunk_field(chunk: Dict[str, Any], field: str) -> Any:
    """Helper method to extract fields from either raw or enriched chunk structures."""
    # Outer level check
    if field in chunk:
        return chunk[field]

    # Metadata level check
    metadata = chunk.get("metadata")
    if isinstance(metadata, dict):
        if field == "page_number" and "page" in metadata:
            return metadata["page"]
        if field in metadata:
            return metadata[field]

    # Key mapping / fallbacks
    if field == "chunk_id" and "id" in chunk:
        return chunk["id"]
    if field == "page_number" and "page" in chunk:
        return chunk["page"]

    return None


class BaseValidationRule(ABC):
    """Abstract base class for chunk quality validation rules."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for the rule."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the rule checks."""
        pass

    def validate_chunk(
        self, chunk: Dict[str, Any], context: Dict[str, Any] = None
    ) -> Optional[ValidationIssue]:
        """Validates a single chunk. Returns a ValidationIssue if invalid, else None."""
        return None

    def validate_batch(
        self, chunks: List[Dict[str, Any]], context: Dict[str, Any] = None
    ) -> List[ValidationIssue]:
        """Validates a batch of chunks. Default implementation loops over validate_chunk."""
        issues = []
        for chunk in chunks:
            issue = self.validate_chunk(chunk, context)
            if issue:
                issues.append(issue)
        return issues


class RejectEmptyChunkRule(BaseValidationRule):
    """Rule ensuring the chunk content is not empty or whitespace."""

    @property
    def name(self) -> str:
        return "reject_empty_chunk"

    @property
    def description(self) -> str:
        return "Rejects chunks with empty or whitespace-only content."

    def validate_chunk(
        self, chunk: Dict[str, Any], context: Dict[str, Any] = None
    ) -> Optional[ValidationIssue]:
        content = _get_chunk_field(chunk, "content")
        chunk_id = _get_chunk_field(chunk, "chunk_id")

        if not content or not str(content).strip():
            return ValidationIssue(
                chunk_id=str(chunk_id) if chunk_id else None,
                rule_name=self.name,
                message="Chunk content is empty or contains only whitespace.",
                severity="ERROR",
            )
        return None


class TokenThresholdRule(BaseValidationRule):
    """Rule validating chunk token counts fall within predefined min/max bounds."""

    def __init__(self, min_tokens: int = 500, max_tokens: int = 800):
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens

    @property
    def name(self) -> str:
        return "token_threshold"

    @property
    def description(self) -> str:
        return f"Validates that chunk token count is between {self.min_tokens} and {self.max_tokens}."

    def validate_chunk(
        self, chunk: Dict[str, Any], context: Dict[str, Any] = None
    ) -> Optional[ValidationIssue]:
        tokens = _get_chunk_field(chunk, "token_count")
        chunk_id = _get_chunk_field(chunk, "chunk_id")

        if tokens is None:
            return ValidationIssue(
                chunk_id=str(chunk_id) if chunk_id else None,
                rule_name=self.name,
                message="Missing token_count metadata.",
                severity="ERROR",
            )

        try:
            tokens_int = int(tokens)
        except (ValueError, TypeError):
            return ValidationIssue(
                chunk_id=str(chunk_id) if chunk_id else None,
                rule_name=self.name,
                message=f"Invalid token_count type or value: {tokens}.",
                severity="ERROR",
            )

        if tokens_int < self.min_tokens:
            return ValidationIssue(
                chunk_id=str(chunk_id) if chunk_id else None,
                rule_name=self.name,
                message=f"Chunk token count ({tokens_int}) is below the minimum threshold of {self.min_tokens} tokens.",
                severity="ERROR",
            )

        if tokens_int > self.max_tokens:
            return ValidationIssue(
                chunk_id=str(chunk_id) if chunk_id else None,
                rule_name=self.name,
                message=f"Chunk token count ({tokens_int}) is above the maximum threshold of {self.max_tokens} tokens.",
                severity="ERROR",
            )

        return None


class MissingSectionRule(BaseValidationRule):
    """Rule ensuring the chunk has valid, non-placeholder section metadata."""

    def __init__(self, invalid_sections: Optional[Set[str]] = None):
        self.invalid_sections = (
            invalid_sections if invalid_sections is not None else {"General"}
        )

    @property
    def name(self) -> str:
        return "missing_section"

    @property
    def description(self) -> str:
        return "Rejects chunks with missing, empty, or default placeholder section metadata."

    def validate_chunk(
        self, chunk: Dict[str, Any], context: Dict[str, Any] = None
    ) -> Optional[ValidationIssue]:
        section = _get_chunk_field(chunk, "section")
        chunk_id = _get_chunk_field(chunk, "chunk_id")

        if not section or not str(section).strip():
            return ValidationIssue(
                chunk_id=str(chunk_id) if chunk_id else None,
                rule_name=self.name,
                message="Section metadata is missing or empty.",
                severity="ERROR",
            )

        stripped_section = str(section).strip()
        if stripped_section in self.invalid_sections:
            return ValidationIssue(
                chunk_id=str(chunk_id) if chunk_id else None,
                rule_name=self.name,
                message=f"Section metadata is set to default placeholder: '{stripped_section}'.",
                severity="ERROR",
            )

        return None


class DuplicateChunkRule(BaseValidationRule):
    """Rule identifying duplicate chunks in the batch by ID or content hash."""

    @property
    def name(self) -> str:
        return "duplicate_chunk"

    @property
    def description(self) -> str:
        return "Rejects duplicate chunks by ID or content in the validation batch."

    def validate_batch(
        self, chunks: List[Dict[str, Any]], context: Dict[str, Any] = None
    ) -> List[ValidationIssue]:
        issues = []
        seen_ids: Set[str] = set()
        seen_contents: Set[str] = set()

        for chunk in chunks:
            chunk_id = _get_chunk_field(chunk, "chunk_id")
            content = _get_chunk_field(chunk, "content")

            str_chunk_id = str(chunk_id) if chunk_id else None

            if str_chunk_id:
                if str_chunk_id in seen_ids:
                    issues.append(
                        ValidationIssue(
                            chunk_id=str_chunk_id,
                            rule_name=self.name,
                            message=f"Duplicate chunk ID '{str_chunk_id}' detected in the batch.",
                            severity="ERROR",
                        )
                    )
                seen_ids.add(str_chunk_id)

            if content:
                # Normalize spaces and lowercase for content duplication checks
                normalized_content = " ".join(str(content).split()).lower()
                if normalized_content in seen_contents:
                    issues.append(
                        ValidationIssue(
                            chunk_id=str_chunk_id,
                            rule_name=self.name,
                            message="Duplicate chunk content detected in the batch.",
                            severity="ERROR",
                        )
                    )
                seen_contents.add(normalized_content)

        return issues


class MalformedHierarchyRule(BaseValidationRule):
    """Rule ensuring the hierarchy matches logical regulatory parent-child structures."""

    @property
    def name(self) -> str:
        return "malformed_hierarchy"

    @property
    def description(self) -> str:
        return "Detects structural hierarchy issues and numbering mismatches."

    def validate_chunk(
        self, chunk: Dict[str, Any], context: Dict[str, Any] = None
    ) -> Optional[ValidationIssue]:
        section = _get_chunk_field(chunk, "section")
        subsection = _get_chunk_field(chunk, "subsection")
        chunk_id = _get_chunk_field(chunk, "chunk_id")

        str_chunk_id = str(chunk_id) if chunk_id else None

        # 1. Subsection defined but Section is empty or placeholder
        if subsection and str(subsection).strip():
            if (
                not section
                or not str(section).strip()
                or str(section).strip() == "General"
            ):
                return ValidationIssue(
                    chunk_id=str_chunk_id,
                    rule_name=self.name,
                    message=f"Subsection '{subsection}' is defined, but parent section is missing or default 'General'.",
                    severity="ERROR",
                )

            # 2. Extract numbering sequence to check for mismatch (e.g. Section 3 with Subsection 1.1)
            # Find digits, e.g. "Chapter II. 12" -> "12" or "1. Introduction" -> "1"
            sec_num_match = re.search(r"\b(\d+)\b", str(section))
            sub_num_match = re.search(r"\b(\d+\.\d+)\b", str(subsection))

            if sec_num_match and sub_num_match:
                sec_num = sec_num_match.group(1)
                sub_num = sub_num_match.group(1)

                # e.g., "12.1" must start with "12."
                if not sub_num.startswith(f"{sec_num}."):
                    return ValidationIssue(
                        chunk_id=str_chunk_id,
                        rule_name=self.name,
                        message=f"Hierarchy prefix mismatch: Subsection numbering '{sub_num}' does not match parent Section number '{sec_num}'.",
                        severity="ERROR",
                    )

        return None
