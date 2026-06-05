"""Module 5.4 — Hallucination Guard (second-pass verification).

Pipeline
--------

::

    AnswerSection  +  RetrievedChunk[]
        ↓
    ┌──────────────────────────────┐
    │ LLM-based FaithfulnessEval  │ (primary)
    └──────────────┬───────────────┘
                   ↓
    Lexical fallback (if LLM fails or method=lexical)
                   ↓
    HallucinationGuardService (combine / select)
                   ↓
    FaithfulnessResponse

The guard is **deterministic offline** by default (uses
:class:`LexicalFaithfulnessChecker`) and only invokes the LLM when
``method=LLM`` is requested and a provider is configured.  This
matches the spec's "second-pass verification" — the LLM is the
authoritative judge when available, the lexical checker is a safety
net for tests and degraded mode.
"""

from __future__ import annotations

from app.services.hallucination.evaluator import (
    FaithfulnessEvaluator,
    MockFaithfulnessProvider,
    VerificationResult,
)
from app.services.hallucination.lexical import (
    LexicalFaithfulnessChecker,
)
from app.services.hallucination.prompts import (
    build_verification_prompts,
    parse_verification_response,
)
from app.services.hallucination.service import (
    HallucinationGuardService,
    build_default_hallucination_guard,
)

__all__ = [
    "HallucinationGuardService",
    "build_default_hallucination_guard",
    "FaithfulnessEvaluator",
    "MockFaithfulnessProvider",
    "VerificationResult",
    "LexicalFaithfulnessChecker",
    "build_verification_prompts",
    "parse_verification_response",
]
