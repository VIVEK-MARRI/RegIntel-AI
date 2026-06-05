"""Answer Generation Engine (Module 5.1).

Public surface
--------------
* :class:`AnswerGeneratorService`  – high-level orchestrator.
* :class:`PromptBuilder`            – converts retrieval chunks into a
  source-aware prompt.
* :class:`LLMProvider` (ABC)        – pluggable LLM backend.

The engine accepts :class:`~app.schemas.answer_generation.RetrievedChunk`
objects produced by the hybrid retrieval layer and emits a structured
:class:`~app.schemas.answer_generation.AnswerGenerationResponse`.
"""

from __future__ import annotations

from app.services.answer_generation.providers import (
    BaseLLMProvider,
    GeminiProvider,
    LLMResponse,
    LiteLLMProvider,
    MockLLMProvider,
    OpenAIProvider,
    get_provider,
)
from app.services.answer_generation.prompt_builder import (
    PromptBuilder,
    PromptBundle,
)
from app.services.answer_generation.service import (
    AnswerGeneratorService,
    AnswerGeneratorTelemetry,
    build_default_service,
    parse_sections,
)

__all__ = [
    "AnswerGeneratorService",
    "AnswerGeneratorTelemetry",
    "build_default_service",
    "parse_sections",
    "PromptBuilder",
    "PromptBundle",
    "BaseLLMProvider",
    "LLMResponse",
    "OpenAIProvider",
    "GeminiProvider",
    "LiteLLMProvider",
    "MockLLMProvider",
    "get_provider",
]
