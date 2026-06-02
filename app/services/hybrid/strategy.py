from typing import List, Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)

def min_max_normalize(scores: List[float]) -> List[float]:
    """Applies min-max scaling to project scores into the [0.0, 1.0] range.
    
    If all scores are identical, maps all to 1.0.
    """
    if not scores:
        return []
    
    min_score = min(scores)
    max_score = max(scores)
    range_diff = max_score - min_score
    
    if range_diff < 1e-9:
        return [1.0] * len(scores)
        
    return [(s - min_score) / range_diff for s in scores]


class RetrievalStrategyManager:
    """Manages strategy configurations, bounds validation, and weight balances."""

    @staticmethod
    def balance_weights(dense_weight: float, bm25_weight: float) -> Tuple[float, float]:
        """Ensures weights are within bounds [0.0, 1.0] and normalized to sum to 1.0.
        
        If both are zero, defaults to 0.5 each.
        """
        # Clamp between 0.0 and 1.0
        d_w = max(0.0, min(1.0, dense_weight))
        b_w = max(0.0, min(1.0, bm25_weight))
        
        total = d_w + b_w
        if total < 1e-9:
            logger.warning("Weights sum to zero. Defaulting to dense=0.5, bm25=0.5.")
            return 0.5, 0.5
            
        return d_w / total, b_w / total
