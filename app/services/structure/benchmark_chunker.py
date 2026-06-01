import time
import uuid
import statistics
from typing import List
from app.core.token_utils import SimpleTokenizer
from app.services.structure.chunker import HierarchicalChunker
from app.schemas.chunk import ChunkResponse

def run_chunker_benchmark(pages_count: int = 10, lines_per_page: int = 50) -> dict:
    """Simulates document chunking over complex mock page workloads to evaluate performance."""
    tokenizer = SimpleTokenizer()
    chunker = HierarchicalChunker(tokenizer)
    doc_id = uuid.uuid4()
    doc_title = "Benchmark Cybersecurity Guidelines"
    
    # 1. Generate realistic regulatory content (multiple chapters, sections, subsections, and paragraphs)
    pages = []
    current_line_idx = 0
    for page_num in range(1, pages_count + 1):
        content_lines = []
        if page_num == 1:
            content_lines.append("Reserve Bank of India")
            content_lines.append("Cybersecurity Standards")
            content_lines.append("CHAPTER I")
            content_lines.append("Introduction")
            
        for line_idx in range(lines_per_page):
            current_line_idx += 1
            if current_line_idx % 40 == 0:
                sec_num = current_line_idx // 40
                content_lines.append(f"{sec_num}. Regulatory Control Area {sec_num}")
            elif current_line_idx % 20 == 0:
                sec_num = current_line_idx // 40
                sub_num = (current_line_idx % 40) // 20
                if sec_num > 0:
                    content_lines.append(f"{sec_num}.{sub_num} Control Implementation Details")
                else:
                    content_lines.append("1.1 Basic Security Standards")
            else:
                content_lines.append(
                    "The institution shall establish a robust and secure technological infrastructure "
                    f"to mitigate risks and manage operational compliance guidelines on line {current_line_idx}."
                )
        pages.append({
            "page_number": page_num,
            "content": "\n".join(content_lines)
        })

    # 2. Run chunker benchmark
    start_time = time.perf_counter()
    chunks = chunker.chunk_document(doc_id, doc_title, pages)
    end_time = time.perf_counter()
    
    execution_time_ms = (end_time - start_time) * 1000
    
    # 3. Calculate metrics
    chunk_count = len(chunks)
    token_counts = [c.token_count for c in chunks]
    
    mean_tokens = statistics.mean(token_counts) if token_counts else 0
    min_tokens = min(token_counts) if token_counts else 0
    max_tokens = max(token_counts) if token_counts else 0
    std_dev_tokens = statistics.stdev(token_counts) if len(token_counts) > 1 else 0
    
    metrics = {
        "document_pages_count": pages_count,
        "total_lines_processed": pages_count * lines_per_page,
        "chunk_count": chunk_count,
        "execution_time_ms": execution_time_ms,
        "avg_time_per_page_ms": execution_time_ms / pages_count,
        "tokens_mean": mean_tokens,
        "tokens_min": min_tokens,
        "tokens_max": max_tokens,
        "tokens_std_dev": std_dev_tokens
    }
    
    return metrics

if __name__ == "__main__":
    import json
    res = run_chunker_benchmark(pages_count=20, lines_per_page=60)
    print(json.dumps(res, indent=2))
