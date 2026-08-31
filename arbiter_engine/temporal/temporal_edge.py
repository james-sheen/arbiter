"""
Temporal Relationship Annotations — Phase 2.1.1.

Extends relationship edges with time constants, propagation delays,
coupling strength, and response models to enable quantitative prediction
of downstream impact timing.

Example YAML:
  relationship_rules:
    - type: cools
      source_type: CRAC
      target_type: Rack
      temporal:
        propagation_delay_s: 300
        time_constant_s: 1800
        coupling_strength: 0.85
        response_model: exponential
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ..clock import as_naive_utc, now_utc
from ..interfaces import (
    Entity,
    Problem,
    RelationshipGraph,
    ObservationHistory,
)
from ..types import Axiom, Severity, DetectionLayer

logger = logging.getLogger(__name__)


class ResponseModel(Enum):
    """How downstream entities respond to upstream changes."""
    EXPONENTIAL = "exponential"   # y(t) = y_final × (1 - e^(-t/τ))
    LINEAR = "linear"            # y(t) = y_final × min(t/τ, 1)
    STEP = "step"                # y(t) = y_final if t > delay else 0
    LOGARITHMIC = "logarithmic"  # y(t) = y_final × ln(1+t/τ) / ln(2)


@dataclass
class TemporalEdge:
    """Time-annotated relationship edge."""
    source_type: str
    target_type: str
    relation_type: str
    propagation_delay_s: float = 0.0
    time_constant_s: float = 60.0
    coupling_strength: float = 1.0
    response_model: ResponseModel = ResponseModel.EXPONENTIAL

    def response_fraction(self, elapsed_s: float) -> float:
        """Fraction of final impact realized at time t after the triggering event.

        Returns a value in [0, 1] representing how much of the final impact
        has been realized after elapsed_s seconds since the cause.
        """
        effective_t = elapsed_s - self.propagation_delay_s
        if effective_t < 0:
            return 0.0

        tau = max(self.time_constant_s, 1e-6)

        if self.response_model == ResponseModel.EXPONENTIAL:
            return 1.0 - math.exp(-effective_t / tau)
        elif self.response_model == ResponseModel.LINEAR:
            return min(effective_t / tau, 1.0)
        elif self.response_model == ResponseModel.STEP:
            return 1.0 if effective_t >= 0 else 0.0
        elif self.response_model == ResponseModel.LOGARITHMIC:
            return min(math.log1p(effective_t / tau) / math.log(2), 1.0)
        return 0.0

    def time_to_fraction(self, fraction: float) -> float:
        """Seconds from cause until impact reaches the given fraction of final value.

        Inverse of response_fraction. Returns seconds including propagation delay.
        """
        if fraction <= 0:
            return self.propagation_delay_s
        if fraction >= 1.0:
            fraction = 0.999  # asymptotic

        tau = max(self.time_constant_s, 1e-6)

        if self.response_model == ResponseModel.EXPONENTIAL:
            t = -tau * math.log(1.0 - fraction)
        elif self.response_model == ResponseModel.LINEAR:
            t = tau * fraction
        elif self.response_model == ResponseModel.STEP:
            t = 0.001  # effectively instant after delay
        elif self.response_model == ResponseModel.LOGARITHMIC:
            t = tau * (2 ** fraction - 1)
        else:
            t = tau * fraction

        return t + self.propagation_delay_s

    def effective_impact(self, elapsed_s: float) -> float:
        """Combined impact = coupling_strength × response_fraction(t)."""
        return self.coupling_strength * self.response_fraction(elapsed_s)


@dataclass
class TemporalAnnotationStore:
    """Store for temporal edge annotations, keyed (source_type, target_type, relation)."""

    _edges: Dict[Tuple[str, str, str], TemporalEdge] = field(default_factory=dict)

    def add(self, edge: TemporalEdge) -> None:
        key = (edge.source_type, edge.target_type, edge.relation_type)
        self._edges[key] = edge

    def get(self, source_type: str, target_type: str, relation_type: str) -> Optional[TemporalEdge]:
        return self._edges.get((source_type, target_type, relation_type))

    def get_for_source(self, source_type: str) -> List[TemporalEdge]:
        return [e for k, e in self._edges.items() if k[0] == source_type]

    def get_all(self) -> List[TemporalEdge]:
        return list(self._edges.values())

    @classmethod
    def from_yaml(cls, relationship_rules: List[Dict[str, Any]]) -> 'TemporalAnnotationStore':
        """Parse temporal annotations from domain YAML relationship_rules."""
        store = cls()
        for rule in relationship_rules:
            temporal = rule.get('temporal')
            if not temporal:
                continue
            model_str = temporal.get('response_model', 'exponential')
            try:
                model = ResponseModel(model_str)
            except ValueError:
                model = ResponseModel.EXPONENTIAL

            edge = TemporalEdge(
                source_type=rule.get('source_type', ''),
                target_type=rule.get('target_type', ''),
                relation_type=rule.get('type', ''),
                propagation_delay_s=float(temporal.get('propagation_delay_s', 0)),
                time_constant_s=float(temporal.get('time_constant_s', 60)),
                coupling_strength=float(temporal.get('coupling_strength', 1.0)),
                response_model=model,
            )
            store.add(edge)
        return store


@dataclass
class ImpactPrediction:
    """Predicted downstream impact from a source problem."""
    target_entity_id: str
    target_entity_type: str
    source_entity_id: str
    source_entity_type: str
    relation_type: str
    time_to_warning_s: float
    time_to_critical_s: float
    current_impact_fraction: float
    coupling_strength: float
    propagation_path: List[str]


class TemporalPropagationChecker:
    """Check temporal propagation and predict downstream impact timing.

    Uses TemporalEdge annotations to estimate when a problem on entity A
    will impact downstream entity B, and how severe the impact will be.
    """

    def __init__(self, temporal_store: TemporalAnnotationStore):
        self.temporal_store = temporal_store

    def predict_downstream_impact(
        self,
        source_entity: Entity,
        source_problem: Problem,
        graph: RelationshipGraph,
        entities_by_id: Dict[str, Entity],
        max_hops: int = 3,
    ) -> List[ImpactPrediction]:
        """Predict impact on downstream entities from a source problem.

        Walks the relationship graph, using temporal annotations to estimate
        time-to-impact at each hop.
        """
        predictions = []
        visited = {source_entity.id}
        queue: List[Tuple[str, float, List[str]]] = [
            (source_entity.id, 0.0, [source_entity.id])
        ]

        while queue:
            current_id, cumulative_delay, path = queue.pop(0)
            if len(path) - 1 >= max_hops:
                continue

            current_entity = entities_by_id.get(current_id)
            if not current_entity:
                continue

            outgoing = graph.edges.get(current_id, [])
            for rel_type, target_id in outgoing:
                if target_id in visited:
                    continue
                visited.add(target_id)

                target_entity = entities_by_id.get(target_id)
                if not target_entity:
                    continue

                temporal_edge = self.temporal_store.get(
                    current_entity.type, target_entity.type, rel_type
                )
                if not temporal_edge:
                    # No temporal annotation — use default (instant, full coupling)
                    temporal_edge = TemporalEdge(
                        source_type=current_entity.type,
                        target_type=target_entity.type,
                        relation_type=rel_type,
                    )

                hop_delay = temporal_edge.propagation_delay_s
                total_delay = cumulative_delay + hop_delay

                # Coupling attenuates through hops
                hop_coupling = temporal_edge.coupling_strength
                path_coupling = hop_coupling
                for i in range(len(path) - 1):
                    path_coupling *= 0.8  # attenuation per hop

                # Warning at 30% impact, critical at 70%
                t_warning = total_delay + temporal_edge.time_to_fraction(0.3)
                t_critical = total_delay + temporal_edge.time_to_fraction(0.7)

                predictions.append(ImpactPrediction(
                    target_entity_id=target_id,
                    target_entity_type=target_entity.type,
                    source_entity_id=source_entity.id,
                    source_entity_type=source_entity.type,
                    relation_type=rel_type,
                    time_to_warning_s=t_warning,
                    time_to_critical_s=t_critical,
                    current_impact_fraction=temporal_edge.response_fraction(0),
                    coupling_strength=path_coupling,
                    propagation_path=path + [target_id],
                ))

                # (callsite) — emit per-edge temporal record at
                # production-readiness shape. Severity derived from
                # path_coupling (attenuated coupling strength along the
                # propagation path): coupling >= 0.7 → HIGH; >= 0.4 →
                # MEDIUM; else LOW. `record_production_temporal_edge` gate
                # internally checked; hybrid emit-policy + severity-floor
                # (default MEDIUM) suppresses LOW.
                try:
                    if path_coupling >= 0.7:
                        _severity = "HIGH"
                    elif path_coupling >= 0.4:
                        _severity = "MEDIUM"
                    else:
                        _severity = "LOW"
                    record_production_temporal_edge(
                        src_entity_id=source_entity.id,
                        dst_entity_id=target_id,
                        time_lag_seconds=float(total_delay),
                        severity=_severity,
                    )
                except Exception:  # noqa: BLE001 — defensive
                    pass

                new_path = path + [target_id]
                queue.append((target_id, total_delay + temporal_edge.time_constant_s, new_path))

        return predictions

    def check_temporal_violations(
        self,
        source_entity: Entity,
        source_problem: Problem,
        problem_age_s: float,
        graph: RelationshipGraph,
        entities_by_id: Dict[str, Entity],
    ) -> List[Problem]:
        """Generate problems for downstream entities that should be affected by now.

        If a problem has existed for T seconds and a temporal edge says
        the downstream entity should be 70%+ affected by now, fire a
        predictive warning.
        """
        problems = []
        predictions = self.predict_downstream_impact(
            source_entity, source_problem, graph, entities_by_id
        )

        for pred in predictions:
            if pred.coupling_strength < 0.1:
                continue  # too weak to matter

            target_entity = entities_by_id.get(pred.target_entity_id)
            if not target_entity:
                continue

            temporal_edge = self.temporal_store.get(
                source_entity.type, target_entity.type, pred.relation_type
            )
            if not temporal_edge:
                continue

            impact = temporal_edge.effective_impact(problem_age_s)
            if impact < 0.3:
                continue

            severity = Severity.HIGH if impact >= 0.7 else Severity.MEDIUM

            problems.append(Problem.from_entity(
                entity=target_entity,
                problem_type=f'temporal_propagation:{source_problem.problem_type}',
                severity=severity,
                reason=(
                    f"Predicted impact from {source_entity.type} "
                    f"({source_problem.problem_type}) — "
                    f"{impact*100:.0f}% impact after {problem_age_s:.0f}s"
                ),
                axiom=Axiom.BOUNDEDNESS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'source_entity': source_entity.id,
                    'source_problem': source_problem.problem_type,
                    'impact_fraction': impact,
                    'coupling_strength': pred.coupling_strength,
                    'time_since_cause_s': problem_age_s,
                    'propagation_path': pred.propagation_path,
                    'temporal_model': temporal_edge.response_model.value,
                },
                confidence=min(0.95, pred.coupling_strength * impact),
            ))

        return problems


# ============================================================
# ProductionTemporalEdge production-readiness substrate.
#
# The sibling-within-existing-module shape, after five prior in-place
# production-readiness extensions. Adds per-temporal-edge production
# recording + 5 production-readiness public functions + default-off
# env-gates hybrid emit-policy decision
# (severity-floor gating + 3-value enum emit-policy).
#
# Domain-agnostic: src_entity_id + dst_entity_id + time_lag_seconds scalars
# opaque; no per-domain dispatch. Composes emit-policy decision +
# attestation severity floor + NaturalCategoryDispatcher
# (severity axis = 1 of 8 canonical axes; no new axis).
# ============================================================

import os as _os_cd1121
import threading as _threading_cd1121


def _env_bool_cd1121(name: str, default: bool = False) -> bool:
    raw = _os_cd1121.environ.get(name, "1" if default else "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


DT_PRODUCTION_TEMPORAL_ENABLED: bool = _env_bool_cd1121(
    "DT_PRODUCTION_TEMPORAL_ENABLED", default=False
)
DT_PRODUCTION_TEMPORAL_RING_CAP: int = int(
    _os_cd1121.environ.get("DT_PRODUCTION_TEMPORAL_RING_CAP", "10000")
)

# Per decision — a default-off env-gate (3-value enum)
PRODUCTION_TEMPORAL_EMIT_POLICY_HYBRID: str = "hybrid"
PRODUCTION_TEMPORAL_EMIT_POLICY_FULL_EMIT: str = "full_emit"
PRODUCTION_TEMPORAL_EMIT_POLICY_SUPPRESSED: str = "suppressed"
KNOWN_PRODUCTION_TEMPORAL_EMIT_POLICIES = frozenset([
    PRODUCTION_TEMPORAL_EMIT_POLICY_HYBRID,
    PRODUCTION_TEMPORAL_EMIT_POLICY_FULL_EMIT,
    PRODUCTION_TEMPORAL_EMIT_POLICY_SUPPRESSED,
])
DEFAULT_PRODUCTION_TEMPORAL_EMIT_POLICY: str = PRODUCTION_TEMPORAL_EMIT_POLICY_HYBRID

# Per decision — a default-off env-gate (4-value enum)
PRODUCTION_TEMPORAL_SEVERITY_LOW: str = "LOW"
PRODUCTION_TEMPORAL_SEVERITY_MEDIUM: str = "MEDIUM"
PRODUCTION_TEMPORAL_SEVERITY_HIGH: str = "HIGH"
PRODUCTION_TEMPORAL_SEVERITY_CRITICAL: str = "CRITICAL"
KNOWN_PRODUCTION_TEMPORAL_SEVERITY_FLOORS = frozenset([
    PRODUCTION_TEMPORAL_SEVERITY_LOW,
    PRODUCTION_TEMPORAL_SEVERITY_MEDIUM,
    PRODUCTION_TEMPORAL_SEVERITY_HIGH,
    PRODUCTION_TEMPORAL_SEVERITY_CRITICAL,
])
DEFAULT_PRODUCTION_TEMPORAL_SEVERITY_FLOOR: str = PRODUCTION_TEMPORAL_SEVERITY_MEDIUM

# Higher integer = more severe (matches Severity enum ordering used by
# downstream gates). Numeric mapping is a substrate-local concern; we do
# NOT depend on detection.types.Severity here to keep this module
# domain-opaque.
_SEVERITY_RANK_CD1121: Dict[str, int] = {
    PRODUCTION_TEMPORAL_SEVERITY_LOW: 1,
    PRODUCTION_TEMPORAL_SEVERITY_MEDIUM: 2,
    PRODUCTION_TEMPORAL_SEVERITY_HIGH: 3,
    PRODUCTION_TEMPORAL_SEVERITY_CRITICAL: 4,
}

DT_PRODUCTION_TEMPORAL_SEVERITY_FLOOR: str = _os_cd1121.environ.get(
    "DT_PRODUCTION_TEMPORAL_SEVERITY_FLOOR",
    DEFAULT_PRODUCTION_TEMPORAL_SEVERITY_FLOOR,
).upper()
if DT_PRODUCTION_TEMPORAL_SEVERITY_FLOOR not in KNOWN_PRODUCTION_TEMPORAL_SEVERITY_FLOORS:
    DT_PRODUCTION_TEMPORAL_SEVERITY_FLOOR = DEFAULT_PRODUCTION_TEMPORAL_SEVERITY_FLOOR


@dataclass(frozen=True)
class ProductionTemporalEdge:
    """ per-edge production-readiness temporal propagation event.

    5 opaque fields domain-agnostic invariant. Frozen for
    audit-trail provenance emit-policy decision.

    Mirrors ProductionEntityLifecycleRecord 5-field shape:
    KEY (src_entity_id + dst_entity_id composite) + METRIC
    (time_lag_seconds) + TIMESTAMP (observed_at) + PROVENANCE
    (emit_policy_per_cd1120).
    """

    src_entity_id: str
    dst_entity_id: str
    time_lag_seconds: float
    observed_at: datetime
    emit_policy_per_cd1120: str
    cluster_id: Optional[str] = None  # (Bucket A) per-axis cluster-scope


def resolve_production_temporal_emit_policy(value: Optional[str]) -> str:
    """Safe-default to hybrid."""
    if value is None or value not in KNOWN_PRODUCTION_TEMPORAL_EMIT_POLICIES:
        return DEFAULT_PRODUCTION_TEMPORAL_EMIT_POLICY
    return value


def resolve_production_temporal_severity_floor(value: Optional[str]) -> str:
    """Safe-default to MEDIUM."""
    if value is None:
        return DEFAULT_PRODUCTION_TEMPORAL_SEVERITY_FLOOR
    v = value.upper()
    if v not in KNOWN_PRODUCTION_TEMPORAL_SEVERITY_FLOORS:
        return DEFAULT_PRODUCTION_TEMPORAL_SEVERITY_FLOOR
    return v


def _severity_at_or_above_floor(severity: str, floor: str) -> bool:
    s = resolve_production_temporal_severity_floor(severity)
    f = resolve_production_temporal_severity_floor(floor)
    return _SEVERITY_RANK_CD1121[s] >= _SEVERITY_RANK_CD1121[f]


_PRODUCTION_TEMPORAL_EDGES: List[ProductionTemporalEdge] = []
_PRODUCTION_TEMPORAL_LOCK = _threading_cd1121.RLock()
_PRODUCTION_TEMPORAL_LAST_SEVERITY: Dict[Tuple[str, str], str] = {}


def record_production_temporal_edge(
    src_entity_id: str,
    dst_entity_id: str,
    time_lag_seconds: float,
    severity: str = PRODUCTION_TEMPORAL_SEVERITY_MEDIUM,
    observed_at: Optional[datetime] = None,
    emit_policy: Optional[str] = None,
    cluster_id: Optional[str] = None,
) -> Optional[ProductionTemporalEdge]:
    """Record a temporal-edge propagation event at production-readiness shape.

    Returns the stored ProductionTemporalEdge when gate enabled AND
    emit_policy admits the event; returns None when gate off OR
    emit_policy suppressed OR hybrid mode rejects per severity-floor
    gate (severity < DT_PRODUCTION_TEMPORAL_SEVERITY_FLOOR).

    Hybrid mode gate (decision): admits if severity is
    at-or-above the configured severity-floor.
    """
    if not DT_PRODUCTION_TEMPORAL_ENABLED:
        return None
    policy = resolve_production_temporal_emit_policy(emit_policy)
    if policy == PRODUCTION_TEMPORAL_EMIT_POLICY_SUPPRESSED:
        return None
    ts = as_naive_utc(observed_at) if observed_at else now_utc()
    if policy == PRODUCTION_TEMPORAL_EMIT_POLICY_HYBRID:
        if not _severity_at_or_above_floor(severity, DT_PRODUCTION_TEMPORAL_SEVERITY_FLOOR):
            return None
    record = ProductionTemporalEdge(
        src_entity_id=src_entity_id,
        dst_entity_id=dst_entity_id,
        time_lag_seconds=float(time_lag_seconds),
        observed_at=ts,
        emit_policy_per_cd1120=policy,
        cluster_id=cluster_id,  # (Bucket A)
    )
    with _PRODUCTION_TEMPORAL_LOCK:
        _PRODUCTION_TEMPORAL_EDGES.append(record)
        _PRODUCTION_TEMPORAL_LAST_SEVERITY[(src_entity_id, dst_entity_id)] = (
            resolve_production_temporal_severity_floor(severity)
        )
        if len(_PRODUCTION_TEMPORAL_EDGES) > DT_PRODUCTION_TEMPORAL_RING_CAP:
            del _PRODUCTION_TEMPORAL_EDGES[
                : len(_PRODUCTION_TEMPORAL_EDGES) - DT_PRODUCTION_TEMPORAL_RING_CAP
            ]
    return record


def _filter_by_cluster_id_cd1436(edges, cluster_id: Optional[str]):
    """ helper: filter temporal edges by cluster_id when non-None.

    cluster_id=None returns the full list (backward compat). cluster_id="X"
    returns only edges with ``e.cluster_id == "X"``. Records emitted
    previously carry cluster_id=None and are excluded from a specific-
    cluster query. Mirror of the RCA / axiom_verdicts
    pattern.
    """
    if cluster_id is None:
        return list(edges)
    return [e for e in edges if e.cluster_id == cluster_id]


def get_production_temporal_edges(
    cluster_id: Optional[str] = None,
) -> List[ProductionTemporalEdge]:
    """All recorded production temporal-edge records. Empty when gate off.

    optional ``cluster_id`` filter. None = all (backward compat);
    string value returns only edges stamped with that cluster_id.
    """
    if not DT_PRODUCTION_TEMPORAL_ENABLED:
        return []
    with _PRODUCTION_TEMPORAL_LOCK:
        return _filter_by_cluster_id_cd1436(_PRODUCTION_TEMPORAL_EDGES, cluster_id)


def get_production_temporal_edge_count(cluster_id: Optional[str] = None) -> int:
    """Aggregate count of recorded production temporal-edge records.

    Dashboard-data defensive-accessor entry point. Returns 0 when gate off.

    optional ``cluster_id`` filter. None = aggregate count;
    string value returns count of edges stamped with that cluster_id.
    """
    if not DT_PRODUCTION_TEMPORAL_ENABLED:
        return 0
    with _PRODUCTION_TEMPORAL_LOCK:
        return len(_filter_by_cluster_id_cd1436(_PRODUCTION_TEMPORAL_EDGES, cluster_id))


def get_severity_for_edge(
    src_entity_id: str, dst_entity_id: str
) -> Optional[str]:
    """Last-known severity for (src, dst) edge; None when unknown or gate off."""
    if not DT_PRODUCTION_TEMPORAL_ENABLED:
        return None
    with _PRODUCTION_TEMPORAL_LOCK:
        return _PRODUCTION_TEMPORAL_LAST_SEVERITY.get((src_entity_id, dst_entity_id))


def known_production_temporal_edges() -> List[Tuple[str, str]]:
    """Diagnostic accessor — sorted unique (src_entity_id, dst_entity_id) pairs."""
    if not DT_PRODUCTION_TEMPORAL_ENABLED:
        return []
    with _PRODUCTION_TEMPORAL_LOCK:
        return sorted({(r.src_entity_id, r.dst_entity_id) for r in _PRODUCTION_TEMPORAL_EDGES})


def _reset_production_temporal_for_tests() -> None:
    with _PRODUCTION_TEMPORAL_LOCK:
        _PRODUCTION_TEMPORAL_EDGES.clear()
        _PRODUCTION_TEMPORAL_LAST_SEVERITY.clear()
