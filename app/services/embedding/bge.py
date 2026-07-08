import logging
import threading
import time
from typing import List, Optional
from app.services.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class BGEEmbeddingProvider(EmbeddingProvider):
    """BGE Embedding Provider using SentenceTransformers with lazy loading and thread-safety."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        device: Optional[str] = None,
        normalize_embeddings: bool = True,
        query_instruction: Optional[
            str
        ] = "represent this query for retrieving relevant documents: ",
    ):
        self.model_name = model_name
        self.device = device
        self.normalize_embeddings = normalize_embeddings
        self.query_instruction = query_instruction
        self._model = None
        self._dimension = None
        self._lock = threading.Lock()

    def _get_model(self):
        """Thread-safe lazy loading of the SentenceTransformer model."""
        if self._model is not None:
            return self._model

        with self._lock:
            # Double check to prevent concurrent threads from initializing the model multiple times
            if self._model is not None:
                return self._model

            # Automatically detect CPU/GPU device if none is specified
            if not self.device:
                try:
                    import torch

                    self.device = "cuda" if torch.cuda.is_available() else "cpu"
                except ImportError:
                    self.device = "cpu"

            logger.info(
                f"Loading embedding model '{self.model_name}' on device '{self.device}'..."
            )
            start_time = time.perf_counter()
            try:
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(self.model_name, device=self.device)
                self._model = model
                self._dimension = model.get_sentence_embedding_dimension()
                elapsed = (time.perf_counter() - start_time) * 1000
                logger.info(
                    f"Loaded embedding model '{self.model_name}' in {elapsed:.2f}ms. Dimension: {self._dimension}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to load embedding model '{self.model_name}': {e}",
                    exc_info=True,
                )
                raise RuntimeError(f"Could not load embedding model: {e}") from e

        return self._model

    def encode_text(self, text: str) -> List[float]:
        """Encodes a single text string into a vector embedding."""
        if not text or not str(text).strip():
            # Gracefully handle empty or whitespace-only inputs by returning a zero-vector
            dim = self.get_dimension()
            return [0.0] * dim

        model = self._get_model()
        logger.debug(f"Encoding text of length: {len(text)}")

        # SentenceTransformers encode returns a numpy array, convert to standard Python float list
        # encode() is thread-safe on a loaded model
        embedding = model.encode(text, normalize_embeddings=self.normalize_embeddings)
        return embedding.tolist()

    def encode_query(self, query: str) -> List[float]:
        """Encodes a query string with an optional instruction prefix for asymmetric retrieval."""
        if not query or not str(query).strip():
            dim = self.get_dimension()
            return [0.0] * dim

        prefix = self.query_instruction or ""
        logger.debug(f"Encoding query with prefix: '{prefix}'")
        return self.encode_text(prefix + query)

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """Encodes a list of text strings in batch."""
        if not texts:
            return []

        # Filter and handle empty string placeholders gracefully
        processed_texts = []
        for text in texts:
            if not text or not str(text).strip():
                processed_texts.append("")
            else:
                processed_texts.append(text)

        model = self._get_model()
        logger.info(f"Encoding batch of {len(texts)} texts...")
        start_time = time.perf_counter()

        embeddings = model.encode(
            processed_texts,
            normalize_embeddings=self.normalize_embeddings,
            show_progress_bar=False,
        )

        # Replace empty string vectors with proper zero-vectors
        result = []
        dim = self.get_dimension()
        for idx, emb in enumerate(embeddings):
            if processed_texts[idx] == "":
                result.append([0.0] * dim)
            else:
                result.append(emb.tolist())

        elapsed = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"Completed batch encoding of {len(texts)} texts in {elapsed:.2f}ms"
        )
        return result

    def get_dimension(self) -> int:
        """Returns the size of the vector embeddings produced by the model."""
        if self._dimension is not None:
            return self._dimension

        # Trigger lazy model loading to resolve dimension if not set
        self._get_model()
        return self._dimension

    def get_model_name(self) -> str:
        """Returns the name of the loaded model."""
        return self.model_name

    def health_check(self) -> bool:
        """Runs a validation inference pass to check system health."""
        try:
            # Force load the model if not loaded yet
            model = self._get_model()
            if model is None:
                return False
            # Run quick inference pass
            test_vector = self.encode_text("Health check probe")
            return len(test_vector) == self.get_dimension()
        except Exception as e:
            logger.error(f"Embedding service health check failed: {e}")
            return False
