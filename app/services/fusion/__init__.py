"""Fusion package – Retrieval Fusion Engine.

Public exports::

    from app.services.fusion import FusionEngine, FusionConfig, FusionMethod
"""

from app.services.fusion.engine import (  # noqa: F401
    BaseFusionStrategy,
    FusionEngine,
    RRFStrategy,
    ScoreFusionStrategy,
    WeightedSumStrategy,
)
from app.schemas.fusion import FusedCandidate, FusionConfig, FusionMethod, FusionReport  # noqa: F401
