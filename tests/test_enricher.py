import uuid
import pytest
from datetime import date
from app.services.structure.enricher import ChunkMetadataBuilder, MetadataValidator, MetadataEnricher

# Dummy Document model wrapper for testing
class DummyDoc:
    def __init__(self, id, title, source, publication_date):
        self.id = id
        self.title = title
        self.source = source
        self.publication_date = publication_date

def test_chunk_metadata_builder():
    doc_id = uuid.uuid4()
    builder = ChunkMetadataBuilder()
    
    builder.set_document_id(doc_id) \
           .set_title("Test Doc") \
           .set_source("SEBI") \
           .set_page(5) \
           .set_section("Section 1") \
           .set_subsection("Subsection 1.1") \
           .set_publication_date(date(2026, 5, 20)) \
           .set_chunk_size(450) \
           .set_token_count(120) \
           .add_custom_metadata("custom_score", 0.95)
           
    meta = builder.build()
    
    assert meta["document_id"] == doc_id
    assert meta["title"] == "Test Doc"
    assert meta["source"] == "SEBI"
    assert meta["page"] == 5
    assert meta["section"] == "Section 1"
    assert meta["subsection"] == "Subsection 1.1"
    assert meta["publication_date"] == date(2026, 5, 20)
    assert meta["chunk_size"] == 450
    assert meta["token_count"] == 120
    assert meta["custom_score"] == 0.95

def test_metadata_validator():
    validator = MetadataValidator()
    
    # 1. Valid Dict
    valid_dict = {
        "document_id": uuid.uuid4(),
        "title": "KYC Guide",
        "source": "RBI",
        "page": 1,
        "section": "General",
        "subsection": "",
        "publication_date": date(2026, 5, 1),
        "chunk_size": 200,
        "token_count": 50
    }
    assert len(validator.validate(valid_dict)) == 0
    
    # 2. Invalid Page (<= 0)
    invalid_page = valid_dict.copy()
    invalid_page["page"] = 0
    errors = validator.validate(invalid_page)
    assert len(errors) > 0
    assert any("page number" in e for e in errors)
    
    # 3. Missing Required Fields
    missing_fields = valid_dict.copy()
    del missing_fields["title"]
    errors = validator.validate(missing_fields)
    assert len(errors) > 0
    assert any("Missing required field" in e for e in errors)

def test_metadata_enricher_success_and_failure():
    validator = MetadataValidator()
    enricher = MetadataEnricher(validator)
    
    doc = DummyDoc(
        id=uuid.uuid4(),
        title="RBI Cybersecurity Standard",
        source="RBI",
        publication_date=date(2026, 5, 25)
    )
    
    chunk_data = {
        "chunk_id": "chunk-123",
        "content": "This is content of cybersecurity chunks.",
        "section": "1. Controls",
        "subsection": "",
        "page_number": 3,
        "token_count": 80,
        "classification": "high"  # Custom field to test extension
    }
    
    # 1. Success
    enriched = enricher.enrich_chunk(doc, chunk_data)
    assert enriched["chunk_id"] == "chunk-123"
    assert enriched["content"] == "This is content of cybersecurity chunks."
    
    meta = enriched["metadata"]
    assert meta["document_id"] == doc.id
    assert meta["title"] == "RBI Cybersecurity Standard"
    assert meta["source"] == "RBI"
    assert meta["page"] == 3
    assert meta["section"] == "1. Controls"
    assert meta["chunk_size"] == len(chunk_data["content"])
    assert meta["token_count"] == 80
    assert meta["classification"] == "high"  # preserved dynamically!
    
    # 2. Failure (raises ValueError)
    bad_chunk_data = chunk_data.copy()
    bad_chunk_data["page_number"] = -1
    with pytest.raises(ValueError, match="metadata validation failed"):
        enricher.enrich_chunk(doc, bad_chunk_data)
