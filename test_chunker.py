import asyncio
import uuid
from app.core.database import async_session_factory
from app.services.document import DocumentService
from app.services.page import PageService
from app.services.structure.chunker import HierarchicalChunker
from app.core.token_utils import SimpleTokenizer
from app.services.structure.enricher import MetadataEnricher, MetadataValidator

async def test():
    db = async_session_factory()
    doc_svc = DocumentService(db)
    page_svc = PageService(db, doc_svc)
    chunker = HierarchicalChunker(tokenizer=SimpleTokenizer())
    enricher = MetadataEnricher(MetadataValidator())
    
    docs = await doc_svc.list_documents(limit=1)
    for d in docs:
        print('Doc:', d.id, '-', d.title)
        pages = await page_svc.get_document_pages(d.id, limit=10)
        pages_data = [{'page_number': p.page_number, 'content': p.content} for p in pages]
        print('Pages:', len(pages_data))
        for p in pages_data:
            print('  Page', p['page_number'], ':', repr(p['content'][:100]))
        
        raw_chunks = chunker.chunk_document(d.id, d.title, pages_data)
        print('Raw chunks:', len(raw_chunks))
        for c in raw_chunks:
            print('  Chunk:', c.chunk_id, '- section=', c.section, '- tokens=', c.token_count, '- content=', repr(c.content[:100]))
    
    await db.close()

asyncio.run(test())