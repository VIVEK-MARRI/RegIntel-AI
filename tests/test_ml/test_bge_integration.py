"""BGE embedding and reranker integration tests.

These tests load the REAL sentence-transformers models and verify:
1. The embedding model produces vectors of the correct dimension.
2. Embeddings for semantically similar texts are closer than unrelated texts.
3. The reranker correctly orders (query, relevant_doc) above (query, irrelevant_doc).

These tests are SKIPPED unless sentence_transformers is installed.
They run in the dedicated `ml-tests` CI job which installs the full ML stack.
"""

from __future__ import annotations

import pytest

_ST_AVAILABLE = False
try:
    import sentence_transformers  # noqa: F401
    _ST_AVAILABLE = True
except ImportError:
    pass

pytestmark = pytest.mark.skipif(
    not _ST_AVAILABLE,
    reason="sentence_transformers not installed — run with the ML stack to enable these tests",
)

_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
_RERANKER_MODEL = "BAAI/bge-reranker-base"
_EXPECTED_DIMENSION = 384  # bge-small-en-v1.5 output dimension


class TestBGEEmbeddingProviderReal:
    """Real model load + inference tests for BGEEmbeddingProvider."""

    @pytest.fixture(scope="class")
    def provider(self):
        from app.services.embedding.bge import BGEEmbeddingProvider
        return BGEEmbeddingProvider(
            model_name=_EMBEDDING_MODEL,
            device="cpu",
            normalize_embeddings=True,
        )

    def test_model_loads_and_produces_correct_dimension(self, provider):
        """encode_text must return a vector of the expected dimension."""
        vec = provider.encode_text("Reserve Bank of India digital lending guidelines")
        assert isinstance(vec, list), f"Expected list, got {type(vec)}"
        assert len(vec) == _EXPECTED_DIMENSION, (
            f"Expected dimension {_EXPECTED_DIMENSION}, got {len(vec)}"
        )
        assert all(isinstance(v, float) for v in vec), "All elements must be floats"

    def test_get_dimension_returns_correct_value(self, provider):
        """get_dimension() must match the actual output vector length."""
        dim = provider.get_dimension()
        assert dim == _EXPECTED_DIMENSION, f"Expected {_EXPECTED_DIMENSION}, got {dim}"

    def test_query_encoding_produces_unit_vector(self, provider):
        """Normalized embeddings must have L2 norm ≈ 1.0."""
        import math
        vec = provider.encode_query("what is digital lending?")
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-3, f"Expected unit vector norm, got {norm}"

    def test_semantic_similarity_is_higher_for_related_texts(self, provider):
        """Similar regulatory text must have higher cosine similarity than unrelated text."""
        query = provider.encode_query("digital lending consent requirements")
        relevant = provider.encode_text(
            "REs shall obtain explicit informed consent from borrowers before processing personal data"
        )
        irrelevant = provider.encode_text(
            "The Eiffel Tower is a wrought-iron lattice tower in Paris, France"
        )
        # Cosine similarity (vectors are already normalized)
        def dot(a, b):
            return sum(x * y for x, y in zip(a, b))

        sim_relevant = dot(query, relevant)
        sim_irrelevant = dot(query, irrelevant)
        assert sim_relevant > sim_irrelevant, (
            f"Expected relevant similarity ({sim_relevant:.3f}) > "
            f"irrelevant similarity ({sim_irrelevant:.3f})"
        )

    def test_batch_encoding_returns_correct_count(self, provider):
        """encode_batch must return one vector per input text."""
        texts = [
            "digital lending regulation",
            "credit evaluation model",
            "borrower consent requirements",
        ]
        vecs = provider.encode_batch(texts)
        assert len(vecs) == len(texts), f"Expected {len(texts)} vectors, got {len(vecs)}"
        for i, vec in enumerate(vecs):
            assert len(vec) == _EXPECTED_DIMENSION, (
                f"Vector {i} has wrong dimension: {len(vec)}"
            )

    def test_health_check_passes(self, provider):
        """health_check() must return True with the real model loaded."""
        assert provider.health_check() is True

    def test_empty_text_returns_zero_vector(self, provider):
        """Empty string must return a zero vector of the correct dimension."""
        vec = provider.encode_text("")
        assert len(vec) == _EXPECTED_DIMENSION
        assert all(v == 0.0 for v in vec), "Expected zero vector for empty input"


class TestBGERerankerProviderReal:
    """Real model load + inference tests for BGERerankerProvider."""

    @pytest.fixture(scope="class")
    def reranker(self):
        from app.services.reranker.model import BGERerankerProvider
        return BGERerankerProvider(
            model_name=_RERANKER_MODEL,
            device="cpu",
            max_length=256,
        )

    def test_model_loads_and_scores_pair(self, reranker):
        """score_pair must return a float without error."""
        score = reranker.score_pair(
            "digital lending consent",
            "REs shall obtain explicit informed consent from borrowers",
        )
        assert isinstance(score, float), f"Expected float score, got {type(score)}"

    def test_relevant_pair_scores_higher_than_irrelevant(self, reranker):
        """A relevant (query, doc) pair must score higher than an irrelevant one."""
        query = "what consent is required for digital lending?"
        relevant_passage = (
            "REs shall obtain explicit informed consent from borrowers "
            "before collecting, storing, or processing personal data."
        )
        irrelevant_passage = "The capital of France is Paris, known for its art and culture."

        # Use score_pairs for batch efficiency
        scores = reranker.score_pairs([
            (query, relevant_passage),
            (query, irrelevant_passage),
        ])
        assert len(scores) == 2
        assert scores[0] > scores[1], (
            f"Relevant score ({scores[0]:.3f}) should be higher than "
            f"irrelevant score ({scores[1]:.3f})"
        )

    def test_score_pairs_returns_correct_count(self, reranker):
        """score_pairs must return one score per input pair."""
        pairs = [
            ("query one", "document one"),
            ("query two", "document two"),
            ("query three", "document three"),
        ]
        scores = reranker.score_pairs(pairs)
        assert len(scores) == len(pairs), (
            f"Expected {len(pairs)} scores, got {len(scores)}"
        )

    def test_empty_pairs_returns_empty_list(self, reranker):
        """score_pairs([]) must return []."""
        scores = reranker.score_pairs([])
        assert scores == []

    def test_health_check_passes(self, reranker):
        """health_check() must return True with the real model loaded."""
        assert reranker.health_check() is True
