import re
import uuid
import hashlib
from typing import List, Dict, Any, Optional, Tuple
from app.core.token_utils import BaseTokenizer
from app.schemas.chunk import ChunkResponse
from app.services.page import PageService
from app.services.structure.enricher import MetadataEnricher

class HierarchicalChunker:
    """Hierarchical chunker that segments documents by regulatory section/subsection,
    and builds token-bounded chunks (500-800 tokens) with overlap (50-100 tokens).
    """

    def __init__(self, tokenizer: BaseTokenizer):
        self.tokenizer = tokenizer
        # Match section numbers (e.g. "1. Introduction" or "12. Customer Verification")
        self.section_pattern = re.compile(
            r"^\s*(?P<num>\d+)\.\s+(?P<title>[A-Za-z].*)$"
        )
        # Match subsection numbers (e.g. "1.1 Applicability" or "12.1 Verification Details")
        self.subsection_pattern = re.compile(
            r"^\s*(?P<num>\d+\.\d+)\.?\s+(?P<title>[A-Za-z].*)$"
        )
        # Exclusion patterns (headers, page footers, etc.)
        self.page_number_pattern = re.compile(
            r"^\s*(Page|page)?\s*\d+\s*(of\s*\d+)?\s*$",
            re.IGNORECASE
        )

    def _is_probable_heading(self, text: str) -> bool:
        if len(text) > 180:
            return False
        if len(re.findall(r"\.\s+[A-Z]", text)) > 0:
            return False
        return True

    def chunk_document(
        self, 
        document_id: uuid.UUID, 
        doc_title: str, 
        pages: List[Dict[str, Any]]
    ) -> List[ChunkResponse]:
        """Segments document text into hierarchical chunks based on sections/subsections."""
        segments = []
        current_section = "General"
        current_subsection = ""
        current_segment_lines: List[Tuple[str, int]] = []

        for page_idx, page in enumerate(pages):
            page_num = page.get("page_number", page_idx + 1)
            content = page.get("content", "")
            if not content:
                continue

            lines = content.split("\n")
            for line in lines:
                line_stripped = line.strip()
                if not line_stripped:
                    continue

                # Skip running footer page numbers
                if self.page_number_pattern.match(line_stripped):
                    continue

                # Check Section Heading
                sec_match = self.section_pattern.match(line_stripped)
                if sec_match:
                    title = sec_match.group("title").strip()
                    if self._is_probable_heading(title):
                        if current_segment_lines:
                            segments.append({
                                "section": current_section,
                                "subsection": current_subsection,
                                "lines": current_segment_lines
                            })
                        current_section = line_stripped
                        current_subsection = ""
                        current_segment_lines = []
                        continue

                # Check Subsection Heading
                sub_match = self.subsection_pattern.match(line_stripped)
                if sub_match:
                    title = sub_match.group("title").strip()
                    if self._is_probable_heading(title):
                        if current_segment_lines:
                            segments.append({
                                "section": current_section,
                                "subsection": current_subsection,
                                "lines": current_segment_lines
                            })
                        current_subsection = line_stripped
                        current_segment_lines = []
                        continue

                # Regular content line
                current_segment_lines.append((line_stripped, page_num))

        # Finalize last segment
        if current_segment_lines:
            segments.append({
                "section": current_section,
                "subsection": current_subsection,
                "lines": current_segment_lines
            })

        # If no segments were found (e.g., document has no section headings),
        # treat the entire content as a single "General" segment
        if not segments and current_segment_lines:
            segments.append({
                "section": "General",
                "subsection": "",
                "lines": current_segment_lines
            })

        # Chunk each segment individually
        chunks: List[ChunkResponse] = []
        for seg in segments:
            sec = seg["section"]
            sub = seg["subsection"]
            lines = seg["lines"]

            seg_chunks = self._chunk_segment_lines(document_id, doc_title, sec, sub, lines)
            chunks.extend(seg_chunks)

        return chunks

    def _chunk_segment_lines(
        self, 
        document_id: uuid.UUID,
        doc_title: str, 
        section: str, 
        subsection: str, 
        lines: List[Tuple[str, int]]
    ) -> List[ChunkResponse]:
        chunks: List[ChunkResponse] = []
        if not lines:
            return chunks

        # Prefix headers to guarantee section context remains inside every chunk
        header_prefix = f"Document: {doc_title}\n"
        header_prefix += f"Section: {section}\n"
        if subsection:
            header_prefix += f"Subsection: {subsection}\n"
        header_prefix += "\n"

        header_tokens = self.tokenizer.count_tokens(header_prefix)

        current_chunk_lines: List[Tuple[str, int]] = []
        current_tokens = header_tokens

        i = 0
        while i < len(lines):
            line_text, page_num = lines[i]
            line_tokens = self.tokenizer.count_tokens(line_text + "\n")

            # Finalize if adding the line exceeds 800 tokens and we have >= 500 tokens
            if current_tokens + line_tokens > 800 and current_tokens >= 500:
                content_text = "\n".join([line for line, _ in current_chunk_lines])
                chunk_content = header_prefix + content_text
                chunk_page = current_chunk_lines[0][1] if current_chunk_lines else page_num

                # Stable node ID generation using uuid.uuid5 and SHA-256 content hashes
                content_hash = hashlib.sha256(chunk_content.encode("utf-8")).hexdigest()
                chunk_uuid = uuid.uuid5(uuid.UUID(str(document_id)), f"{section}:{subsection}:{content_hash}")

                chunks.append(ChunkResponse(
                    chunk_id=str(chunk_uuid),
                    section=section,
                    subsection=subsection,
                    content=chunk_content,
                    token_count=current_tokens,
                    page_number=chunk_page
                ))

                # Slide window overlap (target 75 tokens)
                overlap_tokens = 0
                overlap_lines_count = 0
                for j in range(len(current_chunk_lines) - 1, -1, -1):
                    l_text, l_page = current_chunk_lines[j]
                    l_tok = self.tokenizer.count_tokens(l_text + "\n")
                    if overlap_tokens + l_tok > 75:
                        break
                    overlap_tokens += l_tok
                    overlap_lines_count += 1

                if overlap_lines_count > 0:
                    current_chunk_lines = current_chunk_lines[-overlap_lines_count:]
                    current_tokens = header_tokens + overlap_tokens
                else:
                    current_chunk_lines = []
                    current_tokens = header_tokens

            current_chunk_lines.append((line_text, page_num))
            current_tokens += line_tokens
            i += 1

        # Finalize the last remaining chunk
        if current_chunk_lines:
            content_text = "\n".join([line for line, _ in current_chunk_lines])
            chunk_content = header_prefix + content_text
            chunk_page = current_chunk_lines[0][1] if current_chunk_lines else 1

            content_hash = hashlib.sha256(chunk_content.encode("utf-8")).hexdigest()
            chunk_uuid = uuid.uuid5(uuid.UUID(str(document_id)), f"{section}:{subsection}:{content_hash}")

            chunks.append(ChunkResponse(
                chunk_id=str(chunk_uuid),
                section=section,
                subsection=subsection,
                content=chunk_content,
                token_count=current_tokens,
                page_number=chunk_page
            ))

        return chunks

class HierarchicalChunkerService:
    """Service orchestrating document retrieval and chunking parsing workflows."""

    def __init__(
        self, 
        document_service: Any, 
        page_service: PageService, 
        chunker: HierarchicalChunker,
        enricher: MetadataEnricher
    ):
        self.document_service = document_service
        self.page_service = page_service
        self.chunker = chunker
        self.enricher = enricher

    async def chunk_document_by_id(self, document_id: uuid.UUID) -> List[Dict[str, Any]]:
        """Fetches document and page metadata from database, parses hierarchical chunks, and enriches them."""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info("chunk_document_by_id called for document_id=%s", document_id)
        doc = await self.document_service.get_document_by_id(document_id)
        logger.info("Got document: %s, title=%s", doc.id, doc.title)
        pages = await self.page_service.get_document_pages(document_id, limit=2000)
        logger.info("Got %d pages", len(pages))
        pages_data = [
            {"page_number": p.page_number, "content": p.content}
            for p in pages
        ]
        for p in pages_data:
            logger.info("Page %d: content length=%d, preview=%s", p['page_number'], len(p['content']), repr(p['content'][:100]))
        raw_chunks = self.chunker.chunk_document(doc.id, doc.title, pages_data)
        logger.info("Chunker returned %d raw chunks", len(raw_chunks))

        enriched_chunks = []
        for raw in raw_chunks:
            raw_dict = {
                "chunk_id": raw.chunk_id,
                "section": raw.section,
                "subsection": raw.subsection,
                "content": raw.content,
                "token_count": raw.token_count,
                "page_number": raw.page_number
            }
            enriched = self.enricher.enrich_chunk(doc, raw_dict)
            enriched_chunks.append(enriched)

        logger.info("Returning %d enriched chunks", len(enriched_chunks))
        return enriched_chunks
