import pytest
import threading
import time
from unittest.mock import patch, MagicMock
import numpy as np
from app.services.embedding.bge import BGEEmbeddingProvider

@pytest.fixture
def mock_transformer():
    """Mocks the SentenceTransformer class to avoid network and GPU requirements during tests."""
    with patch("sentence_transformers.SentenceTransformer") as mock_class:
        mock_instance = MagicMock()
        mock_instance.get_sentence_embedding_dimension.return_value = 384

        def mock_encode(texts, normalize_embeddings=True, show_progress_bar=False):
            # Single text string encoding
            if isinstance(texts, str):
                vec = np.zeros(384)
                if texts.strip():
                    vec[0] = 1.0
                if normalize_embeddings:
                    norm = np.linalg.norm(vec)
                    if norm > 0:
                        vec = vec / norm
                return vec

            # Batch encoding
            results = []
            for t in texts:
                vec = np.zeros(384)
                if t and str(t).strip():
                    vec[0] = 1.0
                if normalize_embeddings:
                    norm = np.linalg.norm(vec)
                    if norm > 0:
                        vec = vec / norm
                results.append(vec)
            return np.array(results)

        mock_instance.encode.side_effect = mock_encode
        mock_class.return_value = mock_instance
        yield mock_class

def test_embedding_provider_metadata(mock_transformer):
    provider = BGEEmbeddingProvider(model_name="BAAI/bge-small-en-v1.5")
    
    # Check basic properties without loading model
    assert provider.get_model_name() == "BAAI/bge-small-en-v1.5"
    assert provider._model is None

    # Get dimension (triggers lazy loading)
    assert provider.get_dimension() == 384
    assert provider._model is not None
    mock_transformer.assert_called_once()

def test_encode_single_text(mock_transformer):
    provider = BGEEmbeddingProvider(model_name="BAAI/bge-small-en-v1.5")
    
    # Test valid text encoding
    emb = provider.encode_text("Hello world")
    assert len(emb) == 384
    assert emb[0] == 1.0  # Mock returns 1.0 for first element
    assert sum(emb[1:]) == 0.0

    # Test empty text returns zero-vector
    empty_emb = provider.encode_text("")
    assert len(empty_emb) == 384
    assert sum(empty_emb) == 0.0

    # Test whitespace text returns zero-vector
    whitespace_emb = provider.encode_text("   ")
    assert len(whitespace_emb) == 384
    assert sum(whitespace_emb) == 0.0

def test_encode_query_with_prefix(mock_transformer):
    provider = BGEEmbeddingProvider(
        model_name="BAAI/bge-small-en-v1.5",
        query_instruction="query_prefix: "
    )
    
    # Mock encode to inspect call args
    with patch.object(provider, "encode_text", wraps=provider.encode_text) as mock_encode_text:
        emb = provider.encode_query("my search term")
        assert len(emb) == 384
        mock_encode_text.assert_called_once_with("query_prefix: my search term")

    # Empty query fallback
    empty_emb = provider.encode_query("")
    assert len(empty_emb) == 384
    assert sum(empty_emb) == 0.0

def test_encode_batch(mock_transformer):
    provider = BGEEmbeddingProvider(model_name="BAAI/bge-small-en-v1.5")
    
    texts = ["First text", "", "Third text", "   "]
    embeddings = provider.encode_batch(texts)
    
    assert len(embeddings) == 4
    assert len(embeddings[0]) == 384
    # First is valid
    assert embeddings[0][0] == 1.0
    # Second is empty -> zero-vector
    assert sum(embeddings[1]) == 0.0
    # Third is valid
    assert embeddings[2][0] == 1.0
    # Fourth is whitespace -> zero-vector
    assert sum(embeddings[3]) == 0.0

def test_health_check(mock_transformer):
    provider = BGEEmbeddingProvider(model_name="BAAI/bge-small-en-v1.5")
    assert provider.health_check() is True

    # Health check returns False if model fails to load
    with patch.object(provider, "_get_model", side_effect=RuntimeError("GPU memory full")):
        assert provider.health_check() is False

def test_thread_safety_lazy_loading(mock_transformer):
    provider = BGEEmbeddingProvider(model_name="BAAI/bge-small-en-v1.5")
    
    # We will start 10 threads trying to encode text concurrently
    # This verifies that self._get_model() is thread-safe and only calls SentenceTransformer once.
    num_threads = 10
    barrier = threading.Barrier(num_threads)
    results = [None] * num_threads

    def worker(thread_idx):
        barrier.wait()  # Synchronize startup
        results[thread_idx] = provider.encode_text(f"Text from thread {thread_idx}")

    threads = []
    for i in range(num_threads):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # All threads should have successfully encoded
    for res in results:
        assert len(res) == 384
        assert res[0] == 1.0

    # Underlying loader should have only been invoked once due to singleton locking
    mock_transformer.assert_called_once()
