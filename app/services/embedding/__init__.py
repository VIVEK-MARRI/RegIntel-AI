from app.core.config import settings
from app.services.embedding.base import EmbeddingProvider
from app.services.embedding.bge import BGEEmbeddingProvider

# Initialize global thread-safe singleton instance from application settings
embedding_provider: EmbeddingProvider = BGEEmbeddingProvider(
    model_name=settings.EMBEDDING_MODEL_NAME,
    device=settings.EMBEDDING_DEVICE,
    normalize_embeddings=settings.EMBEDDING_NORMALIZE,
    query_instruction=settings.EMBEDDING_QUERY_INSTRUCTION
)

__all__ = [
    "EmbeddingProvider",
    "BGEEmbeddingProvider",
    "embedding_provider"
]
