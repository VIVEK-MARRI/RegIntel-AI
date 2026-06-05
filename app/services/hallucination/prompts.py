"""Verification-prompt templates for the hallucination guard.

Constructs the system + user prompts that the LLM evaluator sends
to a model.  Also exposes a robust JSON parser that handles common
LLM failure modes (markdown fences, trailing prose, malformed JSON).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.answer_generation import (
    AnswerSection,
    RetrievedChunk,
)
from app.schemas.citation import Claim
from app.schemas.hallucination import ClaimVerdict

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """You are a strict faithfulness evaluator for a regulatory question-answering system.

Given a list of claims extracted from an answer and the source documents that grounded it, decide whether each claim is fully supported by the sources.

Rules
-----
1. A claim is SUPPORTED only if every fact in it is explicitly grounded in the source documents.
2. A claim is UNSUPPORTED if it introduces any information not present in the sources, or if the sources are insufficient to verify the claim.
3. Be strict — false claims can mislead regulators and the public.
4. If a claim paraphrases a source, that is still SUPPORTED, as long as no new facts are added.
5. If two sources disagree, prefer the more specific / authoritative one; do NOT mark the claim UNSUPPORTED for the disagreement alone.

Output
------
Return ONLY a single JSON object (no prose, no markdown) matching this schema:

{
  "supported_claims": [
    {"claim_id": "<id>", "claim": "<text>", "cited_chunk_ids": ["<id>"], "reason": "<short>"}
  ],
  "unsupported_claims": [
    {"claim_id": "<id>", "claim": "<text>", "reason": "<short>"}
  ],
  "overall_faithfulness": <float 0.0-1.0>
}

`overall_faithfulness` is the fraction of claims that are supported
(supported_count / total_claims).  When there are zero claims, set it to 1.0.
"""


@dataclass
class VerificationPrompts:
    """Pair of prompts ready for a provider call."""

    system_prompt: str
    user_prompt: str
    claim_count: int


def _format_chunks(chunks: List[RetrievedChunk]) -> str:
    parts: List[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        loc = []
        if chunk.source:
            loc.append(f"source={chunk.source.value}")
        if chunk.page_number is not None:
            loc.append(f"page={chunk.page_number}")
        if chunk.section:
            loc.append(f"section={chunk.section}")
        loc_str = " | ".join(loc) if loc else "no metadata"
        parts.append(
            f"[{idx}] chunk_id={chunk.chunk_id} document_id={chunk.document_id} {loc_str}\n"
            f"{chunk.content.strip()}"
        )
    return "\n\n".join(parts) if parts else "(no source documents provided)"


def _format_claims(claims: List[Claim]) -> str:
    parts: List[str] = []
    for idx, claim in enumerate(claims, start=1):
        parts.append(f"[{idx}] claim_id={claim.claim_id} section={claim.section}\n{claim.text}")
    return "\n\n".join(parts) if parts else "(no claims to verify)"


def build_verification_prompts(
    *,
    query: str,
    answer: AnswerSection,
    chunks: List[RetrievedChunk],
    claims: List[Claim],
) -> VerificationPrompts:
    """Build the (system, user) prompt pair for the LLM evaluator."""
    user_prompt = (
        f"Question:\n{query.strip()}\n\n"
        f"Answer (already split into claims):\n{_format_claims(claims)}\n\n"
        f"Source Documents (the only information you may use):\n{_format_chunks(chunks)}\n\n"
        "Return the JSON object now."
    )
    return VerificationPrompts(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        claim_count=len(claims),
    )


# ─── Response parser ────────────────────────────────────────────────────────


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"(\{.*\})", re.DOTALL)


def parse_verification_response(
    raw_text: str,
    expected_claims: List[Claim],
) -> Tuple[List[ClaimVerdict], List[ClaimVerdict], float]:
    """Parse the LLM's response into (supported, unsupported, score).

    Tolerates:
      * ``\\`\\`\\`json ... \\`\\`\\`\\`` code fences
      * trailing prose after the JSON object
      * a few common field-name variations
    """
    if not raw_text:
        return _fallback_to_claims(expected_claims, "empty LLM response")

    payload = _extract_json(raw_text)
    if payload is None:
        logger.warning("Could not extract JSON from LLM response: %s", raw_text[:200])
        return _fallback_to_claims(expected_claims, "could not parse JSON")

    supported_raw = payload.get("supported_claims") or []
    unsupported_raw = payload.get("unsupported_claims") or []
    overall = payload.get("overall_faithfulness")

    section_by_id = {c.claim_id: c.section for c in expected_claims}
    text_by_id = {c.claim_id: c.text for c in expected_claims}

    supported: List[ClaimVerdict] = []
    for entry in supported_raw:
        verdict = _to_verdict(
            entry, expected_section=section_by_id, expected_text=text_by_id, supported=True
        )
        if verdict is not None:
            supported.append(verdict)

    unsupported: List[ClaimVerdict] = []
    for entry in unsupported_raw:
        verdict = _to_verdict(
            entry, expected_section=section_by_id, expected_text=text_by_id, supported=False
        )
        if verdict is not None:
            unsupported.append(verdict)

    # Cross-check: ensure every expected claim has a verdict.  Any
    # missing claim is conservatively marked unsupported.
    seen = {v.claim_id for v in supported}
    seen.update(v.claim_id for v in unsupported)
    missing_added = False
    for claim in expected_claims:
        if claim.claim_id not in seen:
            unsupported.append(
                ClaimVerdict(
                    claim_id=claim.claim_id,
                    claim=claim.text,
                    section=claim.section,
                    supported=False,
                    confidence=0.0,
                    cited_chunk_ids=[],
                    reason="LLM did not return a verdict for this claim",
                )
            )
            missing_added = True

    # If we added any missing-verdict unsupported claims, recompute the
    # score from the actual verdict counts — the LLM-supplied overall
    # figure would be misleading.
    if missing_added or not isinstance(overall, (int, float)):
        total = len(supported) + len(unsupported)
        score = (len(supported) / total) if total else 1.0
    else:
        score = max(0.0, min(1.0, float(overall)))

    return supported, unsupported, score


def _extract_json(raw_text: str) -> Optional[Dict[str, Any]]:
    fence = _JSON_FENCE_RE.search(raw_text)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    # Find the first top-level {...} block.
    obj = _JSON_OBJECT_RE.search(raw_text)
    if obj:
        candidate = obj.group(1)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Try to balance braces.
            try:
                return json.loads(_balance_braces(candidate))
            except (json.JSONDecodeError, ValueError):
                return None
    return None


def _balance_braces(text: str) -> str:
    """Return a string where braces are balanced (cut trailing extras)."""
    depth = 0
    out: List[str] = []
    in_str = False
    esc = False
    for ch in text:
        out.append(ch)
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return "".join(out[:-1])
    return "".join(out)


def _to_verdict(
    entry: Any,
    *,
    expected_section: Dict[str, str],
    expected_text: Dict[str, str],
    supported: bool,
) -> Optional[ClaimVerdict]:
    if not isinstance(entry, dict):
        return None
    claim_id = entry.get("claim_id") or entry.get("id")
    claim_text = entry.get("claim") or entry.get("text") or ""
    if not claim_text:
        return None
    if not claim_id or claim_id not in expected_section:
        # Best-effort: match by text.
        for cid, txt in expected_text.items():
            if txt.strip() == claim_text.strip():
                claim_id = cid
                break
    if not claim_id or claim_id not in expected_section:
        # Final fallback: synthesise a deterministic id.
        claim_id = f"clm-unknown-{abs(hash(claim_text)) % 100000:05d}"
    section = expected_section.get(claim_id, "unknown")
    cited = entry.get("cited_chunk_ids") or entry.get("citations") or []
    if not isinstance(cited, list):
        cited = []
    cited_clean = [str(c) for c in cited if c is not None]
    confidence_raw = entry.get("confidence", 1.0)
    try:
        confidence = max(0.0, min(1.0, float(confidence_raw)))
    except (TypeError, ValueError):
        confidence = 1.0
    reason = str(entry.get("reason") or "")
    return ClaimVerdict(
        claim_id=claim_id,
        claim=expected_text.get(claim_id, claim_text),
        section=section,
        supported=bool(supported),
        confidence=confidence,
        cited_chunk_ids=cited_clean if supported else [],
        reason=reason,
    )


def _fallback_to_claims(
    expected: List[Claim], reason: str
) -> Tuple[List[ClaimVerdict], List[ClaimVerdict], float]:
    unsupported = [
        ClaimVerdict(
            claim_id=c.claim_id,
            claim=c.text,
            section=c.section,
            supported=False,
            confidence=0.0,
            cited_chunk_ids=[],
            reason=reason,
        )
        for c in expected
    ]
    return [], unsupported, 0.0


__all__ = [
    "build_verification_prompts",
    "parse_verification_response",
    "VerificationPrompts",
]
