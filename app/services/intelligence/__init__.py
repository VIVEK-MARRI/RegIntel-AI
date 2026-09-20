"""Module 10 — Canonical Intelligence Pipeline public surface."""

from app.services.intelligence.pipeline import (
    IntelligencePipeline,
    PipelineContext,
    build_intelligence_pipeline,
)

__all__ = [
    "IntelligencePipeline",
    "PipelineContext",
    "build_intelligence_pipeline",
]
