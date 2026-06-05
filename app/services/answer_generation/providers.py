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
        """Build a deterministic, parser-friendly answer from the prompt.

        Pulls the actual question (right after the ``Question:`` marker)
        and the real chunk ids (lines starting with ``Chunk ID:``) so the
        output round-trips through the section parser.
        """
        lines = [ln for ln in user_prompt.splitlines() if ln.strip()]
        question = "Unknown question."
        chunk_ids: List[str] = []
        for idx, ln in enumerate(lines):
            stripped = ln.strip()
            lower = stripped.lower()
            if lower.startswith("question:") and idx + 1 < len(lines):
                question = lines[idx + 1].strip()
            # Accept both "Chunk ID: <id>" and "[1] Chunk ID: <id>" forms.
            if "chunk id:" in lower:
                tail = lower.split("chunk id:", 1)[1].strip()
                if tail:
                    chunk_ids.append(tail)
            if lower.startswith("now produce"):
                break
        if not chunk_ids:
            chunk_ids = ["chunk-1"]

        summary = (
            f"Executive Summary: {question} The regulatory framework "
            "outlines specific compliance obligations summarised below."
        )
        detail = (
            "Detailed Explanation: The retrieved regulatory chunks provide "
            "grounded guidance on the query. The explanation combines the "
            "rules from the cited sources and explains their application in "
            "practice. Key obligations, applicability thresholds, and "
            "reporting requirements are addressed in sequence to give the "
            "reader a complete picture."
        )
        evidence = "Supporting Evidence:\n" + ", ".join(chunk_ids)
        refs = (
            "Key Regulatory References: Master Circular on KYC, RBI Act 1934, "
            "Prevention of Money Laundering Act 2002."
        )
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
    """Google Gemini provider (async)."""

    name = LLMProviderName.GEMINI

    def __init__(
        self,
        *,
        model: str = "gemini-1.5-flash",
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
            import google.generativeai as genai  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - import guard
            self._init_error = ImportError(
                "The 'google-generativeai' package is not installed. "
                "Install with: pip install google-generativeai"
            )
            self._init_error.__cause__ = exc
            return

        try:
            genai.configure(api_key=self.api_key)  # type: ignore[attr-defined]
            self._client = genai.GenerativeModel(self.model)  # type: ignore[attr-defined]
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
            raise self._init_error or RuntimeError("Gemini client unavailable")

        # google-generativeai exposes async via generate_content_async.
        try:
            response = await self._client.generate_content_async(
                contents=[system_prompt, user_prompt],
                generation_config={
                    "max_output_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
        except AttributeError:
            # Sync fallback (older versions) – run in a thread.
            import asyncio

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.generate_content(
                    [system_prompt, user_prompt],
                    generation_config={
                        "max_output_tokens": max_tokens,
                        "temperature": temperature,
                    },
                ),
            )

        text = (getattr(response, "text", "") or "").strip()
        usage = getattr(response, "usage_metadata", None) or {}
        return LLMResponse(
            text=text,
            prompt_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            completion_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
            total_tokens=int(getattr(usage, "total_token_count", 0) or 0),
            model=self.model,
            provider=self.name.value,
            raw={"finish_reason": _first_finish_reason(response)},
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

        try:
            stream = await self._client.generate_content_async(
                contents=[system_prompt, user_prompt],
                generation_config={
                    "max_output_tokens": max_tokens,
                    "temperature": temperature,
                },
                stream=True,
            )
            async for event in stream:
                piece = getattr(event, "text", None)
                if piece:
                    yield piece
        except AttributeError:
            # No streaming support – fall back to full response chunked.
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
