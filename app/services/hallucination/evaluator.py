"""LLM-based :class:`FaithfulnessEvaluator`.

Wraps any :class:`BaseLLMProvider` (from Module 5.1 — OpenAI /
Gemini / LiteLLM / Mock) to perform second-pass verification:

    1. Extract claims from the answer.
    2. Build the verification prompt pair.
    3. Call the provider.
    4. Parse the JSON response into :class:`ClaimVerdict` objects.

The evaluator never raises on a bad LLM response — it always
returns a :class:`VerificationResult` so the caller can decide
whether to fall back to the lexical checker.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.schemas.answer_generation import (
    AnswerSection,
    RetrievedChunk,
)
from app.schemas.citation import Claim
from app.schemas.hallucination import ClaimVerdict
from app.services.answer_generation.providers import BaseLLMProvider
from app.services.citation.claim_extractor import ClaimExtractor
from app.services.hallucination.prompts import (
    build_verification_prompts,
    parse_verification_response,
)

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Outcome of a single LLM verification call."""

    supported: List[ClaimVerdict] = field(default_factory=list)
    unsupported: List[ClaimVerdict] = field(default_factory=list)
    faithfulness_score: float = 0.0
    raw_response: str = ""
    provider: str = ""
    model: str = ""
    latency_ms: float = 0.0
    total_tokens: int = 0
    error: Optional[str] = None
    claims: List[Claim] = field(default_factory=list)


class FaithfulnessEvaluator:
    """LLM-based second-pass verifier."""

    def __init__(
        self,
        *,
        provider: BaseLLMProvider,
        extractor: Optional[ClaimExtractor] = None,
        max_tokens: int = 1500,
        temperature: float = 0.0,
    ) -> None:
        self.provider = provider
        self.extractor = extractor or ClaimExtractor()
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def verify(
        self,
        *,
        query: str,
        answer: AnswerSection,
        chunks: List[RetrievedChunk],
    ) -> VerificationResult:
        claims = self.extractor.extract_all(
            [
                ("executive_summary", answer.executive_summary),
                ("detailed_explanation", answer.detailed_explanation),
            ]
        )
        if not claims:
            provider_label = (
                self.provider.name
                if isinstance(self.provider.name, str)
                else getattr(self.provider.name, "value", "unknown")
            )
            return VerificationResult(
                faithfulness_score=1.0,
                provider=provider_label,
                model=self.provider.model,
                claims=[],
            )

        prompts = build_verification_prompts(
            query=query, answer=answer, chunks=chunks, claims=claims
        )
        t0 = time.perf_counter()
        try:
            response = await self.provider.generate(
                system_prompt=prompts.system_prompt,
                user_prompt=prompts.user_prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
        except Exception as exc:
            logger.exception("LLM verification provider call failed")
            provider_label = (
                self.provider.name
                if isinstance(self.provider.name, str)
                else getattr(self.provider.name, "value", "unknown")
            )
            return VerificationResult(
                provider=provider_label,
                model=self.provider.model,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                error=str(exc),
                claims=claims,
            )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        supported, unsupported, score = parse_verification_response(
            response.text, expected_claims=claims
        )
        provider_label = (
            self.provider.name
            if isinstance(self.provider.name, str)
            else getattr(self.provider.name, "value", "unknown")
        )
        return VerificationResult(
            supported=supported,
            unsupported=unsupported,
            faithfulness_score=score,
            raw_response=response.text,
            provider=response.provider or provider_label,
            model=response.model or self.provider.model,
            latency_ms=latency_ms,
            total_tokens=response.total_tokens,
            claims=claims,
        )


# ─── Mock LLM provider that the evaluator can be wired to ──────────────────


class MockFaithfulnessProvider(BaseLLMProvider):
    """Deterministic LLM stub for the faithfulness evaluator.

    Emits a JSON payload that mimics what a real LLM would return,
    computed from the user prompt's claims and chunks.  Used by tests
    and the offline benchmark.
    """

    name = "mock-faithfulness"  # type: ignore[assignment]

    def __init__(self, *, model: str = "mock-faithfulness-v1", **kwargs) -> None:
        super().__init__(model=model, **kwargs)
        self.last_prompt: str = ""
        self.call_count: int = 0
        self.threshold: float = 0.15

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1500,
        temperature: float = 0.0,
    ) -> "LLMResponse":  # noqa: F821
        from app.services.answer_generation.providers import LLMResponse
        from app.services.citation.mapper import token_overlap

        self.last_prompt = user_prompt
        self.call_count += 1

        # Parse claims and chunk contents from the user prompt.
        claims = _extract_claims_from_prompt(user_prompt)
        chunks = _extract_chunks_from_prompt(user_prompt)

        supported = []
        unsupported = []
        for cid, ctext, csection in claims:
            best = None
            for chid, ccontent in chunks:
                score = token_overlap(ctext, ccontent)
                if best is None or score > best[1]:
                    best = (chid, score)
            if best is None or best[1] < self.threshold:
                unsupported.append(
                    {
                        "claim_id": cid,
                        "claim": ctext,
                        "reason": f"no chunk exceeded threshold ({self.threshold:.2f})",
                    }
                )
            else:
                supported.append(
                    {
                        "claim_id": cid,
                        "claim": ctext,
                        "cited_chunk_ids": [best[0]],
                        "reason": f"lexical overlap {best[1]:.2f}",
                    }
                )
        total = len(supported) + len(unsupported)
        overall = (len(supported) / total) if total else 1.0
        payload = {
            "supported_claims": supported,
            "unsupported_claims": unsupported,
            "overall_faithfulness": overall,
        }
        text = json.dumps(payload, indent=2)
        provider_label = (
            self.name
            if isinstance(self.name, str)
            else getattr(self.name, "value", "mock-faithfulness")
        )
        return LLMResponse(
            text=text,
            prompt_tokens=max(1, len(user_prompt.split())),
            completion_tokens=max(1, len(text.split())),
            total_tokens=max(1, len(user_prompt.split())) + max(1, len(text.split())),
            model=self.model,
            provider=provider_label,
        )


def _extract_claims_from_prompt(prompt: str) -> List[Tuple[str, str, str]]:
    """Return list of (claim_id, claim_text, section) tuples from a mock prompt."""
    out: List[Tuple[str, str, str]] = []
    in_claims = False
    current: List[str] = []
    current_meta: dict = {}
    for raw_line in prompt.splitlines():
        line = raw_line.rstrip()
        if "Answer (already split into claims):" in line:
            in_claims = True
            continue
        if in_claims and line.startswith("Source Documents"):
            break
        if not in_claims:
            continue
        if line.startswith("[") and "] claim_id=" in line:
            # Start of a new claim block.
            if current:
                out.append(
                    (
                        current_meta.get("claim_id", ""),
                        "\n".join(current).strip(),
                        current_meta.get("section", "unknown"),
                    )
                )
            current = []
            current_meta = _parse_claim_header(line)
            continue
        if line:
            current.append(line)
    if current:
        out.append(
            (
                current_meta.get("claim_id", ""),
                "\n".join(current).strip(),
                current_meta.get("section", "unknown"),
            )
        )
    return out


def _parse_claim_header(line: str) -> dict:
    meta: dict = {}
    # Format: [1] claim_id=clm-xxx section=executive_summary
    parts = line.split(" ", 2)
    if len(parts) >= 2:
        tail = parts[-1]
        for token in tail.split():
            if "=" in token:
                k, _, v = token.partition("=")
                meta[k] = v
    return meta


def _extract_chunks_from_prompt(prompt: str) -> List[Tuple[str, str]]:
    """Return list of (chunk_id, content) tuples from a mock prompt."""
    out: List[Tuple[str, str]] = []
    in_chunks = False
    header: Optional[dict] = None
    buf: List[str] = []
    for line in prompt.splitlines():
        if "Source Documents" in line:
            in_chunks = True
            continue
        if not in_chunks:
            continue
        if line.startswith("Return the JSON object now."):
            break
        if line.startswith("[") and "] chunk_id=" in line:
            if header is not None:
                out.append((header.get("chunk_id", ""), "\n".join(buf).strip()))
            header = _parse_header_meta(line)
            buf = []
            continue
        if header is not None:
            buf.append(line)
    if header is not None:
        out.append((header.get("chunk_id", ""), "\n".join(buf).strip()))
    return out


def _parse_claim_header(line: str) -> dict:
    return _parse_header_meta(line)


def _parse_chunk_header(line: str) -> dict:
    return _parse_header_meta(line)


def _parse_header_meta(line: str) -> dict:
    """Parse all ``key=value`` tokens on a line."""
    meta: dict = {}
    for token in line.split():
        if "=" in token:
            k, _, v = token.partition("=")
            meta[k] = v
    return meta


__all__ = [
    "FaithfulnessEvaluator",
    "MockFaithfulnessProvider",
    "VerificationResult",
]
