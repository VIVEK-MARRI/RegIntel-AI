import pytest
import os
import uuid
import pickle
from sqlalchemy import select
from app.models.document import Document, SourceEnum, StatusEnum
from app.models.chunk import DocumentChunk
from app.models.bm25 import BM25IndexMetadata
from app.repositories.bm25 import BM25IndexMetadataRepository
from app.services.bm25.service import (
    clean_tokenize,
    BM25IndexManager,
    BM25RetrieverService
)

def test_tokenizer_clean_tokenize():
    # Test normalization, punctuation removal, and stopwords filtering
    text = "The quick brown Fox jumps over the lazy Dog! And it was a nice day."
    tokens = clean_tokenize(text)
    
    # "The", "over", "the", "And", "it", "was", "a" are stopwords
    assert "fox" in tokens
    assert "dog" in tokens
    assert "quick" in tokens
    assert "brown" in tokens
    assert "jumps" in tokens
    assert "lazy" in tokens
    assert "nice" in tokens
    assert "day" in tokens
    
    # Ensure no capitals or punctuation exist
    assert "Fox" not in tokens
    assert "Dog!" not in tokens
    assert "the" not in tokens
    assert "was" not in tokens


@pytest.mark.asyncio
async def test_bm25_repository_operations(db_session):
    repo = BM25IndexMetadataRepository(db_session)
    await repo.deactivate_all()
    
    meta1 = BM25IndexMetadata(
        index_name="index_1",
        corpus_size=10,
        avg_doc_len=12.5,
        vocab_size=100,
        file_path="/tmp/idx1.pkl",
        is_active=True
    )
    meta2 = BM25IndexMetadata(
        index_name="index_2",
        corpus_size=15,
        avg_doc_len=14.2,
        vocab_size=150,
        file_path="/tmp/idx2.pkl",
        is_active=True
    )
    
    await repo.create(meta1)
    await repo.create(meta2)
    await db_session.commit()
    
    # Active metadata should return the latest updated active record
    active = await repo.get_active_metadata()
    assert active is not None
    assert active.index_name in ["index_1", "index_2"]
    
    # Deactivate all
    await repo.deactivate_all()
    await db_session.commit()
    
    active_after = await repo.get_active_metadata()
    assert active_after is None


@pytest.mark.asyncio
async def test_bm25_index_lifecycle_and_retrieval(db_session, tmp_path):
    # Setup test data
    doc_rbi = Document(
        title="RBI KYC Circular",
        source=SourceEnum.RBI,
        file_name="rbi.pdf",
        file_path="rbi.pdf",
        checksum="a" * 64,
        status=StatusEnum.UPLOADED
    )
    doc_sebi = Document(
        title="SEBI Mutual Fund Circular",
        source=SourceEnum.SEBI,
        file_name="sebi.pdf",
        file_path="sebi.pdf",
        checksum="b" * 64,
        status=StatusEnum.UPLOADED
    )
    db_session.add_all([doc_rbi, doc_sebi])
    await db_session.commit()

    try:
        chunk1 = DocumentChunk(
            document_id=doc_rbi.id,
            page_number=1,
            section="Sec 1",
            subsection="Sub 1",
            content="KYC verification requires Aadhaar card and PAN card details for diligence.",
            token_count=15
        )
        chunk2 = DocumentChunk(
            document_id=doc_rbi.id,
            page_number=2,
            section="Sec 2",
            subsection="Sub 2",
            content="Customer due diligence process should be completed within ten working days.",
            token_count=15
        )
        chunk3 = DocumentChunk(
            document_id=doc_sebi.id,
            page_number=1,
            section="Sec 1",
            subsection="Sub 1",
            content="Mutual fund investment schemes must clearly disclose asset allocation details.",
            token_count=15
        )
        db_session.add_all([chunk1, chunk2, chunk3])
        await db_session.commit()

        # 1. Initialize Index Manager
        manager = BM25IndexManager(db_session, storage_dir=str(tmp_path))
        
        # Build index
        index_name = "test_run_bm25"
        filepath = await manager.build_index(index_name)
        assert os.path.exists(filepath)
        
        # Check pickled structure
        with open(filepath, "rb") as f:
            payload = pickle.load(f)
        assert "bm25" in payload
        assert "chunk_ids" in payload
        assert len(payload["chunk_ids"]) == 3
        assert str(chunk1.id) in payload["chunk_ids"]

        # Check database metadata
        repo = BM25IndexMetadataRepository(db_session)
        active_meta = await repo.get_active_metadata()
        assert active_meta is not None
        assert active_meta.corpus_size == 3
        assert active_meta.vocab_size > 0
        assert active_meta.file_path == filepath

        # 2. Test BM25 Retriever
        retriever = BM25RetrieverService(db_session)
        
        # Query for KYC
        results = await retriever.retrieve(query="KYC Aadhaar diligence", top_k=5)
        assert len(results) >= 2
        # Aadhaar is in chunk1 content, diligence in chunk1 & chunk2.
        # So chunk1 should score highest due to matching query terms.
        assert results[0]["chunk_id"] == str(chunk1.id)
        assert results[0]["score"] > 0.0
        assert results[0]["section"] == "Sec 1"
        assert "metadata" in results[0]
        assert results[0]["metadata"]["document_title"] == "RBI KYC Circular"

        # Query with score threshold
        # Higher threshold should screen out lower scoring matches
        results_threshold = await retriever.retrieve(query="KYC Aadhaar diligence", score_threshold=1.0)
        # Check that less matches are returned compared to no threshold
        assert len(results_threshold) < len(results)

        # 3. Test Source Filtering
        results_rbi = await retriever.retrieve(query="diligence mutual fund", source=SourceEnum.RBI)
        # Even though "mutual fund" matches chunk3, source=RBI filters only doc_rbi chunks
        for r in results_rbi:
            assert r["chunk_id"] in [str(chunk1.id), str(chunk2.id)]
            assert r["chunk_id"] != str(chunk3.id)

        # 4. Test Document Filtering
        results_doc = await retriever.retrieve(query="details diligence", document_id=doc_sebi.id)
        assert len(results_doc) == 1
        assert results_doc[0]["chunk_id"] == str(chunk3.id)

        # 5. Test Index Update (auto check)
        # If count matches, update_index returns False
        updated = await manager.update_index()
        assert updated is False

        # Add a new chunk to DB
        chunk4 = DocumentChunk(
            document_id=doc_sebi.id,
            page_number=3,
            section="Sec 3",
            subsection="Sub 3",
            content="New regulatory compliance guidelines for asset management companies.",
            token_count=12
        )
        db_session.add(chunk4)
        await db_session.commit()

        # Now count doesn't match, update_index should return True and rebuild
        updated = await manager.update_index()
        assert updated is True

        # Check updated corpus size in DB metadata
        active_meta_updated = await repo.get_active_metadata()
        assert active_meta_updated.corpus_size == 4

    finally:
        # Cleanup test data
        await db_session.delete(doc_rbi)
        await db_session.delete(doc_sebi)
        await db_session.commit()
