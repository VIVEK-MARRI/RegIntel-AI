"""LLM provider adapters for the Answer Generation Engine.

Each provider implements the :class:`BaseLLMProvider` interface.  The
service layer talks only to this abstract base, so swapping providers
(OpenAI → Gemini → LiteLLM → Mock) requires no changes to the
service / API code.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from app.schemas.answer_generation import LLMProviderName

logger = logging.getLogger(__name__)


# ─── Provider Result Container ────────────────────────────────────────────────


@dataclass
class LLMResponse:
    """Standardised response returned by every provider."""

    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    provider: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


# ─── Abstract Base ────────────────────────────────────────────────────────────


class BaseLLMProvider:
    """Abstract LLM provider.

    Concrete providers must implement :meth:`generate` and may override
    :meth:`stream`.  The base class enforces a ``name`` property and
    keeps common metadata.
    """

    name: LLMProviderName = LLMProviderName.MOCK

    def __init__(self, *, model: str = "mock-default", **kwargs: Any) -> None:
        self.model = model
        self._kwargs = kwargs

    # ── public API ──────────────────────────────────────────────────────────
    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> LLMResponse:
        raise NotImplementedError

    async def stream(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        # Default: non-streaming generate → yield whole text in one go.
        result = await self.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        for piece in _chunk_text(result.text, size=40):
            yield piece

    # ── helpers ─────────────────────────────────────────────────────────────
    def describe(self) -> Dict[str, Any]:
        return {
            "provider": self.name.value,
            "model": self.model,
        }


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _chunk_text(text: str, size: int = 40) -> List[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


# ─── Mock Provider (default; deterministic, no external deps) ────────────────


class MockLLMProvider(BaseLLMProvider):
    """Deterministic provider used in tests and local dev.

    It parses the chunks from the user prompt and synthesises a
    structured answer that round-trips through the section parser in
    :class:`app.services.answer_generation.service.AnswerGeneratorService`.
    """

    name = LLMProviderName.MOCK

    def __init__(self, *, model: str = "mock-default", **kwargs: Any) -> None:
        super().__init__(model=model, **kwargs)
        self.call_count: int = 0
        self.last_system_prompt: str = ""
        self.last_user_prompt: str = ""

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> LLMResponse:
        self.call_count += 1
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt

        text = self._synthesise_answer(user_prompt)
        prompt_tokens = max(1, len(user_prompt.split()))
        completion_tokens = max(1, len(text.split()))

        return LLMResponse(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            model=self.model,
            provider=self.name.value,
        )

    async def stream(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        result = await self.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        for piece in _chunk_text(result.text, size=64):
            yield piece

    @staticmethod
    def _synthesise_answer(user_prompt: str) -> str:
        """Build a content-grounded answer from the actual chunk content."""
        lines = [ln for ln in user_prompt.splitlines() if ln.strip()]
        question = "Unknown question."
        chunks: List[Dict[str, str]] = []
        current: Dict[str, str] = {}
        collecting_content = False
        content_parts: List[str] = []

        for ln in lines:
            stripped = ln.strip()
            lower = stripped.lower()
            if lower.startswith("question:") and not chunks:
                idx = lines.index(ln)
                if idx + 1 < len(lines):
                    question = lines[idx + 1].strip()
            if lower.startswith("[") and "chunk id:" in lower:
                if current:
                    if content_parts:
                        current["content"] = " ".join(content_parts)
                    chunks.append(current)
                current = {"raw_id": lower.split("chunk id:", 1)[1].strip()}
                collecting_content = False
                content_parts = []
            elif lower.startswith("source:"):
                current["source"] = stripped.split(":", 1)[1].strip()
            elif lower.startswith("document:"):
                current["document"] = stripped.split(":", 1)[1].strip()
            elif lower.startswith("section:"):
                current["section"] = stripped.split(":", 1)[1].strip()
            elif lower.startswith("subsection:"):
                current["subsection"] = stripped.split(":", 1)[1].strip()
            elif lower.startswith("content:"):
                collecting_content = True
                content_parts.append(stripped[len("content:"):].strip())
            elif collecting_content and not lower.startswith("[") and not lower.startswith("now produce"):
                content_parts.append(stripped)

        if current:
            if content_parts:
                current["content"] = " ".join(content_parts)
            chunks.append(current)

        if not chunks:
            chunks = [{"raw_id": "chunk-1", "content": "No chunk data available."}]

        # Build executive summary from the question + first chunk's key point.
        first_content = chunks[0].get("content", "")
        # Strip "Document: ... Section: ..." prefix from content for clean summary
        for prefix in ["Document:", "Section:", "Subsection:"]:
            if prefix in first_content:
                first_content = first_content.split(prefix, 1)[-1]
        summary_lead = first_content.strip().lstrip(".").strip()[:300] if first_content else ""
        summary = (
            f"Executive Summary: {question.strip()}"
            + (f" {summary_lead}" if summary_lead else "")
        )

        # Detailed explanation: enumerate each chunk's contribution.
        detail_parts: List[str] = ["Detailed Explanation:"]
        for i, c in enumerate(chunks, 1):
            doc = c.get("document", c.get("source", "Regulatory Source"))
            section = c.get("section", "")
            content = c.get("content", "")
            # Strip the "Document: ..." / "Section: ..." prefix from content
            clean_lines: List[str] = []
            for cl in content.split("Document:"):
                last = cl.rsplit("Section:", 1)[-1] if "Section:" in cl else cl
                clean_lines.append(last.strip().lstrip(".").strip())
            snippet = " ".join(clean_lines)[:400] if clean_lines else (content[:400] if content else "")
            label = f" according to {doc}" if doc else ""
            if section:
                label += f" ({section})"
            detail_parts.append(f"\n{i}.{label}: {snippet}")
        detail = "".join(detail_parts)

        # Supporting evidence: chunk IDs.
        evidence_ids = [c.get("raw_id", f"chunk-{i}") for i, c in enumerate(chunks, 1)]
        evidence = "Supporting Evidence:\n" + ", ".join(evidence_ids)

        # Regulatory references: unique document titles.
        refs_seen: List[str] = []
        for c in chunks:
            doc_title = c.get("document", "")
            if doc_title and doc_title not in refs_seen:
                refs_seen.append(doc_title)
            src = c.get("source", "")
            if src and src not in refs_seen and src != doc_title:
                refs_seen.append(src)
        if not refs_seen:
            refs_seen = ["RBI Act 1934", "SEBI Act 1992", "IRDAI Act 1999"]
        refs = "Key Regulatory References: " + ", ".join(refs_seen)

        return "\n\n".join([summary, detail, evidence, refs])


# ─── OpenAI Provider ─────────────────────────────────────────────────────────


class OpenAIProvider(BaseLLMProvider):
    """OpenAI Chat Completions provider (async)."""

    name = LLMProviderName.OPENAI

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, **kwargs)
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.api_base = api_base or os.getenv("OPENAI_API_BASE")
        self.timeout = timeout
        self._client: Any = None
        self._init_error: Optional[Exception] = None

        if not self.api_key:
            self._init_error = RuntimeError(
                "OPENAI_API_KEY is not configured; OpenAIProvider cannot be used."
            )
            return

        try:
            from openai import AsyncOpenAI  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - import guard
            self._init_error = ImportError(
                "The 'openai' package is not installed. "
                "Install with: pip install openai"
            )
            self._init_error.__cause__ = exc
            return

        try:
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base=self.api_base,
                timeout=self.timeout,
            )
        except Exception as exc:  # pragma: no cover - construction guard
            self._init_error = exc
            return

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> LLMResponse:
        if self._init_error is not None or self._client is None:
            raise self._init_error or RuntimeError("OpenAI client unavailable")

        completion = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = (completion.choices[0].message.content or "").strip()
        usage = getattr(completion, "usage", None) or {}
        return LLMResponse(
            text=text,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
            model=self.model,
            provider=self.name.value,
            raw={"id": getattr(completion, "id", None)},
        )

    async def stream(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        if self._init_error is not None or self._client is None:
            raise self._init_error or RuntimeError("OpenAI client unavailable")

        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        async for event in stream:
            try:
                delta = event.choices[0].delta.content or ""
            except (AttributeError, IndexError):
                delta = ""
            if delta:
                yield delta


# ─── Gemini Provider ─────────────────────────────────────────────────────────


class GeminiProvider(BaseLLMProvider):
    """Google Gemini provider using google-genai SDK."""

    name = LLMProviderName.GEMINI

    def __init__(
        self,
        *,
        model: str = "gemini-2.5-flash",
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, **kwargs)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv(
            "GOOGLE_API_KEY", ""
        )
        self.timeout = timeout
        self._client: Any = None
        self._init_error: Optional[Exception] = None

        if not self.api_key:
            self._init_error = RuntimeError(
                "GEMINI_API_KEY is not configured; GeminiProvider cannot be used."
            )
            return

        try:
            from google import genai  # type: ignore[import-not-found]
        except Exception as exc:
            self._init_error = ImportError(
                "The 'google-genai' package is not installed. "
                "Install with: pip install google-genai"
            )
            self._init_error.__cause__ = exc
            return

        try:
            self._client = genai.Client(api_key=self.api_key)
        except Exception as exc:
            self._init_error = exc
            return

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> LLMResponse:
        if self._init_error is not None or self._client is None:
            raise self._init_error or RuntimeError("Gemini client unavailable")

        from google.genai import types

        try:
            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=[system_prompt, user_prompt],
                config=types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                ),
            )
        except Exception as exc:
            logger.exception("Gemini generate failed: %s", exc)
            raise

        text = (getattr(response, "text", None) or "").strip()
        usage = getattr(response, "usage_metadata", None) or {}
        return LLMResponse(
            text=text,
            prompt_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            completion_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
            total_tokens=int(getattr(usage, "total_token_count", 0) or 0),
            model=self.model,
            provider=self.name.value,
            raw={"finish_reason": getattr(response, "finish_reason", None)},
        )

    async def stream(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        if self._init_error is not None or self._client is None:
            raise self._init_error or RuntimeError("Gemini client unavailable")

        from google.genai import types

        try:
            async for event in await self._client.aio.models.generate_content_stream(
                model=self.model,
                contents=[system_prompt, user_prompt],
                config=types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                ),
            ):
                piece = getattr(event, "text", None)
                if piece:
                    yield piece
        except Exception as exc:
            logger.exception("Gemini stream failed: %s", exc)
            # Fallback to non-streaming chunked.
            response = await self.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            for piece in _chunk_text(response.text, size=40):
                yield piece


def _first_finish_reason(response: Any) -> Optional[str]:
    try:
        return response.candidates[0].finish_reason  # type: ignore[index]
    except Exception:  # pragma: no cover
        return None


# ─── LiteLLM Provider ────────────────────────────────────────────────────────


class LiteLLMProvider(BaseLLMProvider):
    """LiteLLM unified gateway (100+ providers)."""

    name = LLMProviderName.LITELLM

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, **kwargs)
        self.api_key = api_key or os.getenv("LITELLM_API_KEY", "") or os.getenv(
            "OPENAI_API_KEY", ""
        )
        self.api_base = api_base or os.getenv("LITELLM_API_BASE")
        self.timeout = timeout
        self._init_error: Optional[Exception] = None
        self._acompletion: Any = None

        try:
            from litellm import acompletion  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - import guard
            self._init_error = ImportError(
                "The 'litellm' package is not installed. "
                "Install with: pip install litellm"
            )
            self._init_error.__cause__ = exc
            return

        self._acompletion = acompletion

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> LLMResponse:
        if self._init_error is not None or self._acompletion is None:
            raise self._init_error or RuntimeError("LiteLLM unavailable")

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.timeout:
            kwargs["timeout"] = self.timeout

        response = await self._acompletion(**kwargs)
        text = _extract_litellm_text(response)
        usage = _extract_litellm_usage(response)
        return LLMResponse(
            text=text,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
            model=self.model,
            provider=self.name.value,
            raw={"id": getattr(response, "id", None)},
        )

    async def stream(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        if self._init_error is not None or self._acompletion is None:
            raise self._init_error or RuntimeError("LiteLLM unavailable")

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.timeout:
            kwargs["timeout"] = self.timeout

        response = await self._acompletion(**kwargs)
        async for event in response:
            delta = _extract_litellm_delta(event)
            if delta:
                yield delta


def _extract_litellm_text(response: Any) -> str:
    try:
        return (response["choices"][0]["message"]["content"] or "").strip()
    except Exception:  # pragma: no cover - shape varies
        return ""


def _extract_litellm_delta(event: Any) -> str:
    try:
        return event["choices"][0]["delta"].get("content", "") or ""
    except Exception:  # pragma: no cover
        return ""


def _extract_litellm_usage(response: Any) -> Dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
    }


# ─── Provider Factory ────────────────────────────────────────────────────────


def get_provider(
    provider: LLMProviderName,
    *,
    model: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    timeout: float = 30.0,
) -> BaseLLMProvider:
    """Factory: instantiate a provider by enum value.

    Defaults to :class:`MockLLMProvider` for safety in dev/test.
    """
    if provider == LLMProviderName.OPENAI:
        return OpenAIProvider(
            model=model, api_key=api_key, api_base=api_base, timeout=timeout
        )
    if provider == LLMProviderName.GEMINI:
        return GeminiProvider(model=model, api_key=api_key, timeout=timeout)
    if provider == LLMProviderName.LITELLM:
        return LiteLLMProvider(
            model=model, api_key=api_key, api_base=api_base, timeout=timeout
        )
    return MockLLMProvider(model=model)
