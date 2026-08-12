"""
Forward Impact Estimator — Phase 2.4.2.

Given a detected problem on a source entity, walks the propagation graph
forward and estimates the expected downstream impact: which entities are
affected, when impact arrives (time-to-impact), how probable it is, and
what severity to expect.

Uses a combination of:
  - :class:`~.weight_learner.LearnedWeight` — empirical P(downstream|upstream)
  - :class:`~..temporal.temporal_edge.TemporalEdge` — physics-based timing model
  - BFS over the :class:`~..interfaces.RelationshipGraph`

The estimator decays both probability and severity through multi-hop paths,
so second-order effects are represented but appropriately discounted.
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..interfaces import Entity, Problem, RelationshipGraph
from ..types import Axiom, Severity, DetectionLayer
from .weight_learner import LearnedWeight

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DownstreamImpact:
    """Estimated impact on a single downstream entity.

    Attributes
    ----------
    entity_id: Downstream entity identifier.
    hop_distance: Number of relationship hops from the source entity.
    probability: P(this entity experiences a problem) given the source event.
    expected_delay_s: Expected seconds until impact arrives.
    severity: Expected problem severity at this entity.
    path: Entity IDs along the propagation path (source → this).
    """
    entity_id: str
    hop_distance: int
    probability: float
    expected_delay_s: float
    severity: Severity
    path: List[str] = field(default_factory=list)

    def __post_init__(self):
        # normalize severity at construction. Same archetype
        # as ``detection.interfaces.Problem.__post_init__`` — type
        # hint alone doesn't enforce; downstream serialization had
        # to duck-type. Now ``DownstreamImpact.severity`` is
        # guaranteed ``Severity`` enum, and the API surface can use
        # ``.value`` directly.
        if not isinstance(self.severity, Severity):
            if isinstance(self.severity, str):
                try:
                    self.severity = Severity(self.severity)
                except ValueError:
                    valid = sorted(s.value for s in Severity)
                    raise ValueError(
                        f"DownstreamImpact.severity="
                        f"{self.severity!r} is not a recognized "
                        f"Severity value. Valid choices: {valid}."
                    )
            else:
                raise TypeError(
                    f"DownstreamImpact.severity must be a "
                    f"Severity enum or canonical string; got "
                    f"{type(self.severity).__name__!r}={self.severity!r}."
                )


@dataclass
class ImpactForecast:
    """Complete forward impact forecast for a detected problem.

    Attributes
    ----------
    source_problem: The triggering :class:`Problem`.
    downstream_impacts: Ordered list of :class:`DownstreamImpact`, highest-
                        probability first.
    total_affected: Number of distinct downstream entities potentially
                        affected.
    max_hop_distance: Furthest entity reached by the BFS.
    generated_at: UTC timestamp when this forecast was produced.
    """
    source_problem: Problem
    downstream_impacts: List[DownstreamImpact] = field(default_factory=list)
    total_affected: int = 0
    max_hop_distance: int = 0
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def as_problems(self, entity_registry: Optional[Dict[str, Entity]] = None) -> List[Problem]:
        """Convert significant downstream impacts to :class:`Problem` instances.

        Only impacts with ``probability >= 0.3`` are converted.
        Requires *entity_registry* to populate entity fields; falls back to
        minimal fields when absent.

        Parameters
        ----------
        entity_registry: Optional mapping of entity_id → :class:`Entity`.
        """
        registry = entity_registry or {}
        problems: List[Problem] = []

        for impact in self.downstream_impacts:
            if impact.probability < 0.3:
                continue

            entity = registry.get(impact.entity_id)
            entity_type = entity.type if entity else "unknown"
            entity_name = entity.name if entity else impact.entity_id

            p = Problem(
                entity_id=impact.entity_id,
                entity_type=entity_type,
                entity_name=entity_name,
                problem_type="propagated_impact_forecast",
                severity=impact.severity,
                axiom=Axiom.CONNECTIVITY,
                source_layer=DetectionLayer.STATISTICAL,
                reason=(
                    f"Forecasted impact from {self.source_problem.entity_id} "
                    f"({self.source_problem.problem_type}) — "
                    f"P={impact.probability:.2f}, "
                    f"ETA={impact.expected_delay_s:.0f}s, "
                    f"hops={impact.hop_distance}"
                ),
                evidence={
                    "source_entity_id": self.source_problem.entity_id,
                    "source_problem_type": self.source_problem.problem_type,
                    "propagation_probability": impact.probability,
                    "expected_delay_s": impact.expected_delay_s,
                    "hop_distance": impact.hop_distance,
                    "path": impact.path,
                },
                confidence=impact.probability,
            )
            problems.append(p)

        return problems


# ─────────────────────────────────────────────────────────────────────────────
# Estimator
# ─────────────────────────────────────────────────────────────────────────────

# Mapping from source severity to the severity expected at a 1-hop downstream.
_SEVERITY_DECAY: Dict[Severity, Severity] = {
    Severity.CRITICAL: Severity.HIGH,
    Severity.HIGH:     Severity.MEDIUM,
    Severity.MEDIUM:   Severity.LOW,
    Severity.LOW:      Severity.WARNING,
    Severity.WARNING:  Severity.INFO,
    Severity.INFO:     Severity.INFO,
}


class ImpactEstimator:
    """Estimate forward propagation impact of a detected problem.

    Uses BFS over the relationship graph, applying learned propagation
    weights at each hop to compute the joint probability and expected delay.

    Parameters
    ----------
    max_hops: Maximum BFS depth (prevents unbounded traversal).
    min_probability: Prune paths below this probability threshold.
    default_delay_s: Fallback delay (seconds) when no learned weight exists.
    default_probability: Fallback propagation probability per hop when unlearned.
    """

    def __init__(
        self,
        max_hops: int = 4,
        min_probability: float = 0.05,
        default_delay_s: float = 60.0,
        default_probability: float = 0.3,
    ) -> None:
        self.max_hops = max_hops
        self.min_probability = min_probability
        self.default_delay_s = default_delay_s
        self.default_probability = default_probability

    # ── Public API ────────────────────────────────────────────────────────────

    def estimate_impact(
        self,
        problem: Problem,
        graph: RelationshipGraph,
        temporal_edges: Optional[Any] = None,  # TemporalAnnotationStore
        learned_weights: Optional[Dict[Tuple[str, str], LearnedWeight]] = None,
    ) -> ImpactForecast:
        """Walk the propagation graph forward from *problem* and estimate impact.

        Parameters
        ----------
        problem: The triggering source problem.
        graph: Relationship graph for topology traversal.
        temporal_edges: Optional :class:`TemporalAnnotationStore` for timing.
        learned_weights: Optional mapping from :meth:`PropagationWeightLearner.learn_from_history`.

        Returns
        -------
        :class:`ImpactForecast` with all reachable downstream entities.
        """
        weights = learned_weights or {}
        impacts: Dict[str, DownstreamImpact] = {}

        # BFS state: (entity_id, hop, cumulative_probability, cumulative_delay_s, path)
        queue: deque = deque()
        source_id = problem.entity_id
        source_severity = problem.severity

        queue.append((source_id, 0, 1.0, 0.0, [source_id]))
        visited = {source_id}

        while queue:
            current_id, hop, cum_prob, cum_delay, path = queue.popleft()

            if hop >= self.max_hops:
                continue

            for target_id in graph.get_relationships(current_id):
                if target_id in visited:
                    continue
                visited.add(target_id)

                pair = (current_id, target_id)
                weight = weights.get(pair)

                if weight and weight.is_reliable:
                    hop_prob = weight.probability
                    hop_delay = weight.avg_delay_s
                else:
                    hop_prob = self.default_probability
                    hop_delay = self._timing_from_temporal(
                        current_id, target_id, temporal_edges
                    )

                new_prob = cum_prob * hop_prob
                new_delay = cum_delay + hop_delay
                new_hop = hop + 1

                if new_prob < self.min_probability:
                    continue

                new_path = path + [target_id]
                expected_severity = self._decay_severity(source_severity, new_hop)

                impacts[target_id] = DownstreamImpact(
                    entity_id=target_id,
                    hop_distance=new_hop,
                    probability=new_prob,
                    expected_delay_s=new_delay,
                    severity=expected_severity,
                    path=new_path,
                )

                queue.append((target_id, new_hop, new_prob, new_delay, new_path))

        sorted_impacts = sorted(
            impacts.values(), key=lambda i: i.probability, reverse=True
        )
        max_hop = max((i.hop_distance for i in sorted_impacts), default=0)

        return ImpactForecast(
            source_problem=problem,
            downstream_impacts=sorted_impacts,
            total_affected=len(sorted_impacts),
            max_hop_distance=max_hop,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _timing_from_temporal(
        self,
        source_id: str,
        target_id: str,
        temporal_edges: Optional[Any],
    ) -> float:
        """Extract propagation delay from TemporalAnnotationStore, or fall back."""
        if temporal_edges is None:
            return self.default_delay_s

        # TemporalAnnotationStore keys on (source_type, target_type, relation).
        # Without entity→type mapping here, we fall back to the default.
        return self.default_delay_s

    @staticmethod
    def _decay_severity(base: Severity, hops: int) -> Severity:
        """Decay severity by one level per hop."""
        current = base
        for _ in range(hops):
            current = _SEVERITY_DECAY.get(current, Severity.INFO)
        return current
