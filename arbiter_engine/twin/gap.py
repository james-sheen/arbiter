"""
Gap Resolution Pipeline — three-tier escalation: Auto -> LLM -> Human.

Maps to the confidence gates from ConfidenceGatedDetector:
  MISSING_NODE -> entity_type_min (0.6)
  MISSING_EDGE -> relationship_min (0.5)
  MISSING_PROPERTY -> indicator_min (0.7)
  MISSING_THRESHOLD-> indicator_min (0.7)
  MISSING_DYNAMICS -> relaxed (0.5)
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .topology import TopologyGap, GapType, ResolutionStrategy

logger = logging.getLogger(__name__)


@dataclass
class ResolutionResult:
    """Result of a gap resolution attempt."""
    resolved: bool
    value: Optional[Any] = None
    confidence: float = 0.0
    strategy_used: ResolutionStrategy = ResolutionStrategy.AUTO_DISCOVER
    reason: str = ""


# Confidence thresholds per gap type (matching ConfidenceGates).
GAP_CONFIDENCE_THRESHOLDS: Dict[GapType, float] = {
    GapType.MISSING_NODE: 0.6,
    GapType.MISSING_EDGE: 0.5,
    GapType.MISSING_PROPERTY: 0.7,
    GapType.MISSING_THRESHOLD: 0.7,
    GapType.MISSING_DYNAMICS: 0.5,
}


class GapResolver:
    """Three-tier gap resolution pipeline.

    Tier 1: Auto-discover (statistical inference from data)
    Tier 2: LLM inference (reasoning from context)
    Tier 3: Human-provided (operator feedback)

    Each tier must meet a minimum confidence threshold (per gap type)
    before the gap is considered resolved.
    """

    def __init__(
        self,
        auto_resolvers: Optional[Dict[GapType, Callable]] = None,
        llm_resolver: Optional[Callable] = None,
        human_resolver: Optional[Callable] = None,
        confidence_threshold: float = 0.7,
    ):
        self._auto_resolvers = auto_resolvers or {}
        self._llm_resolver = llm_resolver
        self._human_resolver = human_resolver
        self._confidence_threshold = confidence_threshold

    def resolve(self, gap: TopologyGap) -> ResolutionResult:
        """Attempt to resolve a gap through three-tier escalation."""
        min_confidence = GAP_CONFIDENCE_THRESHOLDS.get(
            gap.gap_type, self._confidence_threshold
        )

        # Tier 1: Auto-discover
        auto_resolver = self._auto_resolvers.get(gap.gap_type)
        if auto_resolver:
            try:
                result = auto_resolver(gap)
                gap.resolution_attempts.append({
                    'strategy': ResolutionStrategy.AUTO_DISCOVER.value,
                    'result': 'resolved' if result.resolved else 'failed',
                    'confidence': result.confidence,
                })
                if result.resolved and result.confidence >= min_confidence:
                    return result
            except Exception as e:
                logger.warning(
                    "Auto-resolve failed for gap %s: %s", gap.location, e
                )

        # Tier 2: LLM inference
        if self._llm_resolver:
            try:
                result = self._llm_resolver(gap)
                gap.resolution_attempts.append({
                    'strategy': ResolutionStrategy.LLM_INFER.value,
                    'result': 'resolved' if result.resolved else 'failed',
                    'confidence': result.confidence,
                })
                if result.resolved and result.confidence >= min_confidence:
                    return result
            except Exception as e:
                logger.warning(
                    "LLM-resolve failed for gap %s: %s", gap.location, e
                )

        # Tier 3: Human provide
        if self._human_resolver:
            try:
                result = self._human_resolver(gap)
                gap.resolution_attempts.append({
                    'strategy': ResolutionStrategy.HUMAN_PROVIDE.value,
                    'result': 'resolved' if result.resolved else 'pending',
                    'confidence': result.confidence,
                })
                if result.resolved:
                    return result
            except Exception as e:
                logger.warning(
                    "Human-resolve failed for gap %s: %s", gap.location, e
                )

        return ResolutionResult(
            resolved=False, reason="All resolution tiers exhausted"
        )

    def resolve_batch(
        self,
        gaps: List[TopologyGap],
        max_resolutions: int = 20,
    ) -> List[ResolutionResult]:
        """Resolve multiple gaps, up to max_resolutions."""
        results = []
        for gap in gaps[:max_resolutions]:
            results.append(self.resolve(gap))
        return results
