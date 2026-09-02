"""The production-prediction substrate: a record per prediction, and the gate.

Moved out of `reasoner.py` 2026-09-02. It was appended to the end of that module
and every import it needed was aliased with a suffix -- `import os as _os`
and six more -- because the module above already imports those names. The suffix
was doing the work a module boundary does, so the boundary is here now and the
aliases are gone.

`reasoner` re-exports every public name, because two callers address this
substrate through that module by dotted path rather than by import.

Default-off behind `DT_PRODUCTION_PREDICTION_ENABLED`, ring-capped, and filtered
by cluster on the way out. Domain-agnostic: entity id, axiom engine and severity
are opaque scalars here and no branch reads them.

Provenance, carried over from the banner this docstring replaces: the gate is
the established pattern (default-off env-var), the substrate is the established pattern (the production
sibling), and the prior siblings of that shape are and the rest of the run. Kept because the tests pin it
and because a module extracted from another loses its history at exactly the
moment somebody needs it -- settled the emit policy, built this,
An internal ruling added cluster stamping.

**The one thing the banner claimed that is no longer true**: it described a
sibling-within-an-existing-module shape, preserving the foundation class in the
same file. That was the decision and reversed it. The foundation
`UnifiedAxiomReasoner` stays in `reasoner`, and this is a module of its own,
because the suffix-aliased imports the old shape required were an internal ticket
number visible in shipped code.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Taken from the host module's namespace while this block lived at the end of
# `reasoner.py`, and invisible until the block moved: an appended block reads
# whatever its file already imported, and nothing says which names those are.
from ..clock import as_naive_utc, now_utc


import os as os
import threading as threading
from dataclasses import dataclass as dataclass
from datetime import datetime as datetime
from typing import Dict as Dict, List as List, Tuple as Tuple


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "1" if default else "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


DT_PRODUCTION_PREDICTION_ENABLED: bool = _env_bool(
    "DT_PRODUCTION_PREDICTION_ENABLED", default=False
)
DT_PRODUCTION_PREDICTION_RING_CAP: int = int(
    os.environ.get("DT_PRODUCTION_PREDICTION_RING_CAP", "10000")
)

# Per decision — a default-off env-gate (3-value enum)
PRODUCTION_PREDICTION_EMIT_POLICY_HYBRID: str = "hybrid"
PRODUCTION_PREDICTION_EMIT_POLICY_FULL_EMIT: str = "full_emit"
PRODUCTION_PREDICTION_EMIT_POLICY_SUPPRESSED: str = "suppressed"
KNOWN_PRODUCTION_PREDICTION_EMIT_POLICIES = frozenset([
    PRODUCTION_PREDICTION_EMIT_POLICY_HYBRID,
    PRODUCTION_PREDICTION_EMIT_POLICY_FULL_EMIT,
    PRODUCTION_PREDICTION_EMIT_POLICY_SUPPRESSED,
])
DEFAULT_PRODUCTION_PREDICTION_EMIT_POLICY: str = (
    PRODUCTION_PREDICTION_EMIT_POLICY_HYBRID
)

# Per decision — a default-off env-gate
# (CENTENARY MILESTONE — 4-value enum)
PRODUCTION_PREDICTION_SEVERITY_LOW: str = "LOW"
PRODUCTION_PREDICTION_SEVERITY_MEDIUM: str = "MEDIUM"
PRODUCTION_PREDICTION_SEVERITY_HIGH: str = "HIGH"
PRODUCTION_PREDICTION_SEVERITY_CRITICAL: str = "CRITICAL"
KNOWN_PRODUCTION_PREDICTION_SEVERITY_FLOORS = frozenset([
    PRODUCTION_PREDICTION_SEVERITY_LOW,
    PRODUCTION_PREDICTION_SEVERITY_MEDIUM,
    PRODUCTION_PREDICTION_SEVERITY_HIGH,
    PRODUCTION_PREDICTION_SEVERITY_CRITICAL,
])
DEFAULT_PRODUCTION_PREDICTION_SEVERITY_FLOOR: str = (
    PRODUCTION_PREDICTION_SEVERITY_MEDIUM
)

_SEVERITY_RANK: Dict[str, int] = {
    PRODUCTION_PREDICTION_SEVERITY_LOW: 1,
    PRODUCTION_PREDICTION_SEVERITY_MEDIUM: 2,
    PRODUCTION_PREDICTION_SEVERITY_HIGH: 3,
    PRODUCTION_PREDICTION_SEVERITY_CRITICAL: 4,
}

DT_PRODUCTION_PREDICTION_SEVERITY_FLOOR: str = os.environ.get(
    "DT_PRODUCTION_PREDICTION_SEVERITY_FLOOR",
    DEFAULT_PRODUCTION_PREDICTION_SEVERITY_FLOOR,
).upper()
if DT_PRODUCTION_PREDICTION_SEVERITY_FLOOR not in KNOWN_PRODUCTION_PREDICTION_SEVERITY_FLOORS:
    DT_PRODUCTION_PREDICTION_SEVERITY_FLOOR = DEFAULT_PRODUCTION_PREDICTION_SEVERITY_FLOOR


@dataclass(frozen=True)
class ProductionPrediction:
    """ per-(entity, axiom_engine) production-readiness prediction event.

    5 opaque fields domain-agnostic invariant. Frozen for
    audit-trail provenance emit-policy decision.

    Mirrors ProductionFeedback 5-field shape: KEY (entity_id +
    axiom_engine composite key) + METRIC (prediction_severity) + TIMESTAMP
    (observed_at) + PROVENANCE (emit_policy).
    """

    entity_id: str
    axiom_engine: str
    prediction_severity: float
    observed_at: datetime
    emit_policy: str
    cluster_id: Optional[str] = None  # (Bucket A) per-axis cluster-scope


def resolve_production_prediction_emit_policy(value):  # noqa: ANN001
    """Safe-default to hybrid."""
    if value is None or value not in KNOWN_PRODUCTION_PREDICTION_EMIT_POLICIES:
        return DEFAULT_PRODUCTION_PREDICTION_EMIT_POLICY
    return value


def resolve_production_prediction_severity_floor(value):  # noqa: ANN001
    """Safe-default to MEDIUM."""
    if value is None:
        return DEFAULT_PRODUCTION_PREDICTION_SEVERITY_FLOOR
    v = value.upper()
    if v not in KNOWN_PRODUCTION_PREDICTION_SEVERITY_FLOORS:
        return DEFAULT_PRODUCTION_PREDICTION_SEVERITY_FLOOR
    return v


def _severity_at_or_above_floor(severity: str, floor: str) -> bool:
    s = resolve_production_prediction_severity_floor(severity)
    f = resolve_production_prediction_severity_floor(floor)
    return _SEVERITY_RANK[s] >= _SEVERITY_RANK[f]


_PRODUCTION_PREDICTIONS: List["ProductionPrediction"] = []
_PRODUCTION_PREDICTION_LOCK = threading.RLock()
_PRODUCTION_PREDICTION_LAST_SEVERITY: Dict[Tuple[str, str], float] = {}


def record_production_prediction(
    entity_id: str,
    axiom_engine: str,
    prediction_severity: float,
    severity: str = PRODUCTION_PREDICTION_SEVERITY_MEDIUM,
    observed_at=None,
    emit_policy=None,
    cluster_id: Optional[str] = None,
):
    """Record a prediction event at production-readiness shape.

    optional ``cluster_id`` stamps the record
    for per-axis cluster-scope filtering. Additive, None default; the
    emission callsites have no cluster in scope and pass None (the param
    exists for any cluster-aware caller).

    Returns the stored ProductionPrediction when gate enabled AND
    emit_policy admits the event; returns None when gate off OR
    emit_policy suppressed OR hybrid mode rejects per severity-floor
    gate (severity < DT_PRODUCTION_PREDICTION_SEVERITY_FLOOR).

    Hybrid mode gate (decision): admits if severity is
    at-or-above the configured severity-floor.
    """
    if not DT_PRODUCTION_PREDICTION_ENABLED:
        return None
    policy = resolve_production_prediction_emit_policy(emit_policy)
    if policy == PRODUCTION_PREDICTION_EMIT_POLICY_SUPPRESSED:
        return None
    ts = as_naive_utc(observed_at) if observed_at else now_utc()
    if policy == PRODUCTION_PREDICTION_EMIT_POLICY_HYBRID:
        if not _severity_at_or_above_floor(
            severity, DT_PRODUCTION_PREDICTION_SEVERITY_FLOOR
        ):
            return None
    record = ProductionPrediction(
        entity_id=entity_id,
        axiom_engine=axiom_engine,
        prediction_severity=float(prediction_severity),
        observed_at=ts,
        emit_policy=policy,
        cluster_id=cluster_id,  # (Bucket A)
    )
    with _PRODUCTION_PREDICTION_LOCK:
        _PRODUCTION_PREDICTIONS.append(record)
        _PRODUCTION_PREDICTION_LAST_SEVERITY[(entity_id, axiom_engine)] = (
            float(prediction_severity)
        )
        if len(_PRODUCTION_PREDICTIONS) > DT_PRODUCTION_PREDICTION_RING_CAP:
            del _PRODUCTION_PREDICTIONS[
                : len(_PRODUCTION_PREDICTIONS) - DT_PRODUCTION_PREDICTION_RING_CAP
            ]
    return record


def _filter_by_cluster_id(predictions, cluster_id: Optional[str]):
    """ helper: filter predictions by cluster_id when non-None.

    cluster_id=None returns the full list (backward compat). cluster_id="X"
    returns only predictions with ``p.cluster_id == "X"``. Records emitted
    previously carry cluster_id=None and are excluded from a specific-
    cluster query. Mirror of the RCA / axiom_verdicts
    pattern.
    """
    if cluster_id is None:
        return list(predictions)
    return [p for p in predictions if p.cluster_id == cluster_id]


def get_production_predictions(cluster_id: Optional[str] = None):
    """All recorded production prediction records. Empty when gate off.

    optional ``cluster_id`` filter. None = all (backward compat);
    string value returns only predictions stamped with that cluster_id.
    """
    if not DT_PRODUCTION_PREDICTION_ENABLED:
        return []
    with _PRODUCTION_PREDICTION_LOCK:
        return _filter_by_cluster_id(_PRODUCTION_PREDICTIONS, cluster_id)


def get_production_prediction_count(cluster_id: Optional[str] = None) -> int:
    """Aggregate count of recorded production prediction records.

    Dashboard-data defensive-accessor entry point. Returns 0 when gate off.

    optional ``cluster_id`` filter. None = aggregate count;
    string value returns count of predictions stamped with that cluster_id.
    """
    if not DT_PRODUCTION_PREDICTION_ENABLED:
        return 0
    with _PRODUCTION_PREDICTION_LOCK:
        return len(_filter_by_cluster_id(_PRODUCTION_PREDICTIONS, cluster_id))


def get_severity_for_entity_prediction(entity_id: str, axiom_engine: str):
    """Last-known prediction_severity for (entity, axiom_engine); None when unknown or gate off."""
    if not DT_PRODUCTION_PREDICTION_ENABLED:
        return None
    with _PRODUCTION_PREDICTION_LOCK:
        return _PRODUCTION_PREDICTION_LAST_SEVERITY.get((entity_id, axiom_engine))


def known_production_predictions():
    """Diagnostic accessor — sorted unique (entity_id, axiom_engine) pairs."""
    if not DT_PRODUCTION_PREDICTION_ENABLED:
        return []
    with _PRODUCTION_PREDICTION_LOCK:
        return sorted({(r.entity_id, r.axiom_engine) for r in _PRODUCTION_PREDICTIONS})


def _reset_production_prediction_for_tests() -> None:
    with _PRODUCTION_PREDICTION_LOCK:
        _PRODUCTION_PREDICTIONS.clear()
        _PRODUCTION_PREDICTION_LAST_SEVERITY.clear()
