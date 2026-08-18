"""
Propagation Weight Learner — Phase 2.4.1.

Learns empirical propagation weights from historical problem co-occurrence.

For each pair of entities (source → target) connected in the relationship
graph, the learner watches whether a problem on the source entity is
followed by a problem on the target entity within a configurable time
window. After sufficient observations it computes:

  - ``probability`` — P(target_problem | source_problem)
  - ``avg_delay_s`` — mean seconds between source and target problem
  - ``std_delay_s`` — spread of the delay distribution
  - ``confidence`` — reliability of the estimate (function of sample size)

These weights are consumed by :class:`ImpactEstimator` to forecast the
expected downstream impact of newly detected problems.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..clock import now_utc
from ..interfaces import Problem, RelationshipGraph

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LearnedWeight:
    """Empirically learned propagation weight for a (source, target) entity pair.

    Attributes
    ----------
    observed_co_occurrences: Number of times the target had a problem after
                                the source.
    total_source_occurrences: Total number of source problem events observed.
    probability: Fraction of source events followed by a target event.
    avg_delay_s: Mean delay in seconds (source → target problem).
    std_delay_s: Standard deviation of the delay.
    confidence: Reliability score (0–1), grows with sample size.
    last_updated: UTC timestamp of the last learning call.
    """
    observed_co_occurrences: int = 0
    total_source_occurrences: int = 0
    probability: float = 0.0
    avg_delay_s: float = 0.0
    std_delay_s: float = 0.0
    confidence: float = 0.0
    last_updated: datetime = field(default_factory=now_utc)

    @property
    def is_reliable(self) -> bool:
        """True when enough samples exist for the estimate to be trustworthy."""
        return self.total_source_occurrences >= 5 and self.confidence >= 0.3


# ─────────────────────────────────────────────────────────────────────────────
# Learner
# ─────────────────────────────────────────────────────────────────────────────

class PropagationWeightLearner:
    """Learn propagation weights from historical problem co-occurrence.

    Parameters
    ----------
    co_occurrence_window: Maximum delay between source and target problems
                           for them to count as co-occurring.
    min_confidence_samples: Minimum source occurrences for ``confidence=1.0``.
    """

    def __init__(
        self,
        co_occurrence_window: timedelta = timedelta(minutes=15),
        min_confidence_samples: int = 20,
    ) -> None:
        self.co_occurrence_window = co_occurrence_window
        self.min_confidence_samples = min_confidence_samples
        # (source_entity_id, target_entity_id) → LearnedWeight
        self._weights: Dict[Tuple[str, str], LearnedWeight] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def learn_from_history(
        self,
        problems: List[Problem],
        graph: RelationshipGraph,
    ) -> Dict[Tuple[str, str], LearnedWeight]:
        """Analyse historical problems and update propagation weights.

        For each problem on a source entity, searches for subsequent problems
        on directly connected downstream entities within the co-occurrence
        window.

        Parameters
        ----------
        problems: All historical :class:`Problem` instances, in any order.
        graph: Relationship graph defining entity connectivity.

        Returns
        -------
        Mapping of ``(source_entity_id, target_entity_id)`` → :class:`LearnedWeight`.
        """
        if not problems:
            return self._weights

        # Group problems by entity, sorted by detection time.
        by_entity: Dict[str, List[Problem]] = defaultdict(list)
        for p in problems:
            by_entity[p.entity_id].append(p)
        for entity_id in by_entity:
            by_entity[entity_id].sort(key=lambda p: p.detected_at)

        # For each source problem, check downstream entities for co-occurrence.
        window_s = self.co_occurrence_window.total_seconds()

        # Track per-pair delays for this learning run.
        # (source_id, target_id) → [delay_s,...]
        delay_records: Dict[Tuple[str, str], List[float]] = defaultdict(list)
        source_counts: Dict[Tuple[str, str], int] = defaultdict(int)

        for source_id, source_problems in by_entity.items():
            downstream_ids = graph.get_relationships(source_id)
            if not downstream_ids:
                continue

            for sp in source_problems:
                for target_id in downstream_ids:
                    pair = (source_id, target_id)
                    source_counts[pair] += 1

                    target_problems = by_entity.get(target_id, [])
                    delay = self._find_co_occurrence_delay(
                        sp, target_problems, window_s
                    )
                    if delay is not None:
                        delay_records[pair].append(delay)

        # Merge into stored weights.
        all_pairs = set(source_counts.keys()) | set(delay_records.keys())
        now = now_utc()

        for pair in all_pairs:
            weight = self._weights.setdefault(pair, LearnedWeight())
            n_src = source_counts.get(pair, 0)
            delays = delay_records.get(pair, [])

            weight.total_source_occurrences += n_src
            weight.observed_co_occurrences += len(delays)

            # Recompute probability and delay statistics from cumulative counts.
            total = weight.total_source_occurrences
            co = weight.observed_co_occurrences
            weight.probability = co / total if total > 0 else 0.0

            if delays:
                # Running update of delay stats — simple incremental average.
                all_delays = delays  # only new delays this call
                weight.avg_delay_s = float(
                    (weight.avg_delay_s * (co - len(delays)) + sum(delays)) / co
                    if co > len(delays)
                    else np.mean(all_delays)
                )
                weight.std_delay_s = float(np.std(delays)) if len(delays) > 1 else 0.0

            # Confidence grows with sample size (logistic-like).
            weight.confidence = self._confidence(weight.total_source_occurrences)
            weight.last_updated = now

        return self._weights

    def get_weight(
        self, source_entity_id: str, target_entity_id: str
    ) -> Optional[LearnedWeight]:
        """Return the learned weight for a specific (source, target) pair."""
        return self._weights.get((source_entity_id, target_entity_id))

    def get_all_weights(self) -> Dict[Tuple[str, str], LearnedWeight]:
        """Return a snapshot of all learned weights."""
        return dict(self._weights)

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _find_co_occurrence_delay(
        source_problem: Problem,
        target_problems: List[Problem],
        window_s: float,
    ) -> Optional[float]:
        """Return seconds between *source_problem* and the earliest *target_problem*
        occurring within *window_s* after it, or ``None``."""
        source_ts = source_problem.detected_at
        for tp in target_problems:
            delay = (tp.detected_at - source_ts).total_seconds()
            if 0 <= delay <= window_s:
                return delay
        return None

    def _confidence(self, n: int) -> float:
        """Confidence as a function of sample size.

        Saturates at 1.0 when n >= min_confidence_samples.
        Uses a square-root ramp for intuitive growth.
        """
        if n <= 0:
            return 0.0
        ratio = n / self.min_confidence_samples
        return min(1.0, float(np.sqrt(ratio)))
