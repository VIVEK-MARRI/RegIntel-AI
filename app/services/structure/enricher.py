from datetime import date
from typing import Dict, Any, Optional, List
from uuid import UUID as PyUUID


class ChunkMetadataBuilder:
    """Builder pattern implementation for constructing ChunkMetadata dictionaries incrementally."""

    def __init__(self):
        self._metadata: Dict[str, Any] = {}

    def set_document_id(self, document_id: PyUUID) -> "ChunkMetadataBuilder":
        self._metadata["document_id"] = document_id
        return self

    def set_title(self, title: str) -> "ChunkMetadataBuilder":
        self._metadata["title"] = title
        return self

    def set_source(self, source: str) -> "ChunkMetadataBuilder":
        self._metadata["source"] = source
        return self

    def set_page(self, page: int) -> "ChunkMetadataBuilder":
        self._metadata["page"] = page
        return self

    def set_section(self, section: str) -> "ChunkMetadataBuilder":
        self._metadata["section"] = section
        return self

    def set_subsection(self, subsection: str) -> "ChunkMetadataBuilder":
        self._metadata["subsection"] = subsection
        return self

    def set_publication_date(
        self, publication_date: Optional[date]
    ) -> "ChunkMetadataBuilder":
        self._metadata["publication_date"] = publication_date
        return self

    def set_chunk_size(self, chunk_size: int) -> "ChunkMetadataBuilder":
        self._metadata["chunk_size"] = chunk_size
        return self

    def set_token_count(self, token_count: int) -> "ChunkMetadataBuilder":
        self._metadata["token_count"] = token_count
        return self

    def add_custom_metadata(self, key: str, value: Any) -> "ChunkMetadataBuilder":
        self._metadata[key] = value
        return self

    def build(self) -> Dict[str, Any]:
        return self._metadata


class MetadataValidator:
    """Validator class ensuring completeness and constraints on ChunkMetadata."""

    def validate(self, metadata_dict: Dict[str, Any]) -> List[str]:
        errors: List[str] = []

        # 1. Required fields
        required = [
            "document_id",
            "title",
            "source",
            "page",
            "section",
            "chunk_size",
            "token_count",
        ]
        for field in required:
            if field not in metadata_dict or metadata_dict[field] is None:
                errors.append(f"Missing required field: '{field}'")

        # 2. String completeness
        for field in ["title", "source"]:
            val = metadata_dict.get(field)
            if val is not None and not str(val).strip():
                errors.append(f"Field '{field}' cannot be empty or whitespace.")

        # 3. Range assertions
        page = metadata_dict.get("page")
        if page is not None and page <= 0:
            errors.append(f"Invalid page number: {page}. Must be positive.")

        chunk_size = metadata_dict.get("chunk_size")
        if chunk_size is not None and chunk_size <= 0:
            errors.append(f"Invalid chunk_size: {chunk_size}. Must be positive.")

        token_count = metadata_dict.get("token_count")
        if token_count is not None and token_count <= 0:
            errors.append(f"Invalid token_count: {token_count}. Must be positive.")

        return errors


class MetadataEnricher:
    """Service responsible for automatically enriching raw chunks with validated metadata."""

    def __init__(self, validator: MetadataValidator):
        self.validator = validator

    def enrich_chunk(
        self, doc_metadata: Any, chunk_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Creates a validated metadata payload and merges it with chunk details.

        Args:
            doc_metadata: Document database object (requires id, title, source, publication_date).
            chunk_data: Dictionary containing: chunk_id, content, section, subsection, page_number, token_count.
        """
        builder = ChunkMetadataBuilder()

        # Resolve source string
        source_val = doc_metadata.source
        if hasattr(source_val, "value"):
            source_str = source_val.value
        else:
            source_str = str(source_val)

        builder.set_document_id(doc_metadata.id).set_title(
            doc_metadata.title
        ).set_source(source_str).set_page(chunk_data["page_number"]).set_section(
            chunk_data["section"]
        ).set_subsection(chunk_data["subsection"]).set_publication_date(
            doc_metadata.publication_date
        ).set_chunk_size(len(chunk_data["content"])).set_token_count(
            chunk_data["token_count"]
        )

        # Capture any custom fields in chunk_data that are not standard, for extensibility
        standard_fields = {
            "chunk_id",
            "content",
            "section",
            "subsection",
            "page_number",
            "token_count",
        }
        for k, v in chunk_data.items():
            if k not in standard_fields:
                builder.add_custom_metadata(k, v)

        metadata_dict = builder.build()

        errors = self.validator.validate(metadata_dict)
        if errors:
            raise ValueError(f"Chunk metadata validation failed: {', '.join(errors)}")

        return {
            "chunk_id": chunk_data["chunk_id"],
            "content": chunk_data["content"],
            "metadata": metadata_dict,
        }
