"""P0.1 — Real ML stack integration test (dedicated CI job only).

This test loads the ACTUAL BGE embedding model and BGE reranker (not mocks)
and asserts:
  * the embedding provider returns a real, correctly-shaped vector, and that
    semantically-similar texts score closer than dissimilar ones;
  * the reranker orders a genuinely-relevant passage above an irrelevant one.

It is gated behind ``ML_INTEGRATION_TESTS=1`` (set in the ``ml-tests`` CI job)
because loading the models downloads weights from Hugging Face. It also
``importorskip``s when the ML stack is not installed, so it never breaks the
default test run.
"""

from __future__ import annotations

import math
import os

import pytest

pytest.importorskip("sentence_transformers")
pytest.importorskip("torch")

if not os.environ.get("ML_INTEGRATION_TESTS"):
    pytest.skip(
        "ML integration tests are disabled (set ML_INTEGRATION_TESTS=1 in the ml-tests CI job).",
        allow_module_level=True,
    )

from app.services.embedding.bge import BGEEmbeddingProvider  # noqa: E402
from app.services.reranker.model import BGERerankerProvider  # noqa: E402


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _load_embedding():
    try:
        return BGEEmbeddingProvider()
    except Exception as exc:  # model download / load may be unavailable
        pytest.skip(f"could not load embedding model: {exc}")


def _load_reranker():
    try:
        return BGERerankerProvider()
    except Exception as exc:
        pytest.skip(f"could not load reranker model: {exc}")


def test_embedding_real_vector_shape_and_similarity():
    prov = _load_embedding()
    anchor = "Know Your Customer norms require banks to verify customer identity."
    vec = prov.encode_text(anchor)
    dim = prov.get_dimension()
    assert isinstance(vec, list)
    assert len(vec) == dim
    assert all(isinstance(x, float) for x in vec)

    similar = prov.encode_text("KYC requires customer identity verification by banks.")
    unrelated = prov.encode_text("The monsoon rainfall improved rice yields in Kerala.")
    assert _cosine(vec, similar) > _cosine(vec, unrelated)


def test_reranker_orders_relevant_passage_first():
    rer = _load_reranker()
    query = "What are the KYC identity-verification requirements for banks?"
    pairs = [
        (query, "Banks must verify the identity of every customer under KYC norms."),
        (query, "A biryani recipe uses basmati rice, saffron, and whole spices."),
    ]
    scores = rer.score_pairs(pairs)
    assert len(scores) == 2
    assert scores[0] > scores[1]


@pytest.mark.skipif(
    not os.environ.get("ML_INTEGRATION_TESTS"),
    reason="P0.6 e2e copilot test — requires ML_INTEGRATION_TESTS=1",
)
def test_copilot_e2e_with_real_embeddings():
    """P0.6 — Full ingest→chat litmus test through /copilot/query.

    This test exercises the real hybrid pipeline (BGE embeddings + reranker)
    end-to-end: upload a seed document, wait for chunking, then call the
    copilot chat endpoint and assert a grounded answer with retrieval metadata.
    It runs in the ``ml-tests`` CI job which has the full ML stack installed
    and ``ML_INTEGRATION_TESTS=1`` set.
    """
    import os
    import pathlib
    import time

    # ── SQLite test database (isolated) ──────────────────────────────────
    db_path = pathlib.Path("test_copilot_e2e.db")
    if db_path.exists():
        db_path.unlink()

    # Isolated SQLite database for this test (conftest handles LLM_PROVIDER=mock).
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_copilot_e2e.db")
    os.environ.setdefault("DATABASE_URL_SYNC", "sqlite:///./test_copilot_e2e.db")
    os.environ.setdefault("ENV", "test")

    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)

    # ── Upload the seed document ─────────────────────────────────────────
    seed = pathlib.Path("seed_data/rbi_digital_lending_guidelines.txt")
    if not seed.exists():
        pytest.skip("seed document not found — cannot run e2e copilot test")

    with open(seed, "rb") as f:
        resp = client.post(
            "/api/v1/documents/upload",
            files={"file": ("guidelines.txt", f, "text/plain")},
        )
    assert resp.status_code in (
        200,
        201,
    ), f"upload failed: {resp.status_code} {resp.text}"
    doc_id = resp.json().get("document_id") or resp.json().get("id")

    # ── Wait for background chunking + embedding (model downloads can be slow) ──
    max_wait = 600
    interval = 5
    found_chunks = False
    for elapsed in range(0, max_wait, interval):
        resp = client.get(f"/api/v1/documents/{doc_id}")
        if resp.status_code == 200:
            status = resp.json().get("status", "")
            if status in ("completed", "ready", "processed"):
                found_chunks = True
                break
        # Also check chunks endpoint directly
        cresp = client.get(f"/api/v1/documents/{doc_id}/chunks")
        if cresp.status_code == 200:
            data = cresp.json()
            chunks = data if isinstance(data, list) else data.get("chunks", [])
            if len(chunks) > 0:
                found_chunks = True
                break
        time.sleep(interval)
    if not found_chunks:
        pytest.fail(
            f"no chunks found within {max_wait}s — model download may have timed out"
        )

    # ── Call /copilot/query ──────────────────────────────────────────────
    resp = client.post(
        "/api/v1/copilot/query",
        json={
            "query": "What are the key provisions of RBI's digital lending guidelines?",
            "conversation_id": "e2e-test-copilot",
        },
    )
    assert (
        resp.status_code == 200
    ), f"/copilot/query failed: {resp.status_code} {resp.text}"
    data = resp.json()
    answer = data.get("answer", {})
    assert answer.get("executive_summary"), "copilot returned empty answer"
    metadata = data.get("metadata", {})
    extra = metadata.get("extra", {})
    assert (
        extra.get("retrieval_invoked") is True
    ), "retrieval was not invoked — copilot took degraded path"
    assert len(data.get("sources", [])) > 0, "no source attributions in response"

    # ── Cleanup ──────────────────────────────────────────────────────────
    if db_path.exists():
        db_path.unlink()
