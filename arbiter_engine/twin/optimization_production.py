"""ProductionOptimization substrate sibling: the 4th native
landing of the callsite-wire shape.

The fourth axis built ground-up with this shape rather than backfilled
into it.

Substrate sibling alongside `arbiter_engine/twin/topology_optimizer.py`
(TopologyOptimizer). Independent ring; optimizer preserved
unchanged.

Records ProductionOptimization events on each `TopologyOptimizer.emit()`
invocation. Each record captures: (request_id, pareto_front_size,
max_objective_value, max_constraint_satisfaction, tenant_id,
observed_at).

Three-level cascade safety is preserved along the same chain as its
siblings.

Default-off env-gates decision shape.

The sibling-within-existing-module discipline.

Domain-agnostic: request_id + tenant_id opaque scalars; no per-domain
dispatch. Composes with Lever 1 (kernel
parameter-space extension) — substrate-callsite-wire IS the per-
optimization-emit hook for the 6th DT-mode OPTIMIZE.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime
from ..clock import as_naive_utc, now_utc

from typing import Dict, List, Optional


# ---------- default-off env-gates ----------

def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "1" if default else "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


DT_PRODUCTION_OPTIMIZATION_ENABLED: bool = _env_bool(
    "DT_PRODUCTION_OPTIMIZATION_ENABLED", default=False
)
DT_PRODUCTION_OPTIMIZATION_RING_CAP: int = int(
    os.environ.get("DT_PRODUCTION_OPTIMIZATION_RING_CAP", "512")
)


PRODUCTION_OPTIMIZATION_SEVERITY_LOW: str = "LOW"
PRODUCTION_OPTIMIZATION_SEVERITY_MEDIUM: str = "MEDIUM"
PRODUCTION_OPTIMIZATION_SEVERITY_HIGH: str = "HIGH"
PRODUCTION_OPTIMIZATION_SEVERITY_CRITICAL: str = "CRITICAL"
KNOWN_PRODUCTION_OPTIMIZATION_SEVERITY_FLOORS = frozenset([
    PRODUCTION_OPTIMIZATION_SEVERITY_LOW,
    PRODUCTION_OPTIMIZATION_SEVERITY_MEDIUM,
    PRODUCTION_OPTIMIZATION_SEVERITY_HIGH,
    PRODUCTION_OPTIMIZATION_SEVERITY_CRITICAL,
])
DEFAULT_PRODUCTION_OPTIMIZATION_SEVERITY_FLOOR: str = (
    PRODUCTION_OPTIMIZATION_SEVERITY_LOW
)

_SEVERITY_RANK: Dict[str, int] = {
    PRODUCTION_OPTIMIZATION_SEVERITY_LOW: 1,
    PRODUCTION_OPTIMIZATION_SEVERITY_MEDIUM: 2,
    PRODUCTION_OPTIMIZATION_SEVERITY_HIGH: 3,
    PRODUCTION_OPTIMIZATION_SEVERITY_CRITICAL: 4,
}

DT_PRODUCTION_OPTIMIZATION_SEVERITY_FLOOR: str = os.environ.get(
    "DT_PRODUCTION_OPTIMIZATION_SEVERITY_FLOOR",
    DEFAULT_PRODUCTION_OPTIMIZATION_SEVERITY_FLOOR,
).upper()
if DT_PRODUCTION_OPTIMIZATION_SEVERITY_FLOOR not in KNOWN_PRODUCTION_OPTIMIZATION_SEVERITY_FLOORS:
    DT_PRODUCTION_OPTIMIZATION_SEVERITY_FLOOR = DEFAULT_PRODUCTION_OPTIMIZATION_SEVERITY_FLOOR


# ---------- optimization_severity derivation ----------

def severity_tier_for_pareto(
    pareto_front_size: int,
    max_constraint_satisfaction: float,
) -> str:
    """Severity-tier mapping.

    Severity proxies "optimization-traffic intensity":
    - pareto_front_size > 16 OR max_constraint_satisfaction < 0.25 -> CRITICAL
    - pareto_front_size > 8 OR max_constraint_satisfaction < 0.5 -> HIGH
    - pareto_front_size > 4 OR max_constraint_satisfaction < 0.75 -> MEDIUM
    - else -> LOW
    """
    if pareto_front_size > 16 or max_constraint_satisfaction < 0.25:
        return PRODUCTION_OPTIMIZATION_SEVERITY_CRITICAL
    if pareto_front_size > 8 or max_constraint_satisfaction < 0.5:
        return PRODUCTION_OPTIMIZATION_SEVERITY_HIGH
    if pareto_front_size > 4 or max_constraint_satisfaction < 0.75:
        return PRODUCTION_OPTIMIZATION_SEVERITY_MEDIUM
    return PRODUCTION_OPTIMIZATION_SEVERITY_LOW


# ---------- ProductionOptimization dataclass ----------

@dataclass(frozen=True)
class ProductionOptimization:
    """ per-optimization-invocation production-readiness record.

    7 opaque fields frozen-typed schema subset + derived severity.

    KEY: (request_id, observed_at) implicit;
    METRICS: pareto_front_size + max_objective_value + max_constraint_satisfaction + severity;
    PROVENANCE: tenant_id.
    """

    request_id: str
    pareto_front_size: int
    max_objective_value: float
    max_constraint_satisfaction: float
    severity: str
    tenant_id: str
    observed_at: datetime


def _resolve_severity_floor(value):  # noqa: ANN001
    if value is None:
        return DEFAULT_PRODUCTION_OPTIMIZATION_SEVERITY_FLOOR
    v = value.upper()
    if v not in KNOWN_PRODUCTION_OPTIMIZATION_SEVERITY_FLOORS:
        return DEFAULT_PRODUCTION_OPTIMIZATION_SEVERITY_FLOOR
    return v


def _severity_at_or_above_floor(severity: str, floor: str) -> bool:
    s = _resolve_severity_floor(severity)
    f = _resolve_severity_floor(floor)
    return _SEVERITY_RANK[s] >= _SEVERITY_RANK[f]


# ---------- ring buffer + lock ----------

_PRODUCTION_OPTIMIZATIONS: List["ProductionOptimization"] = []
_PRODUCTION_OPTIMIZATION_LOCK = threading.RLock()


# ---------- 5 public functions ----------

def record_production_optimization(
    request_id: str,
    pareto_front_size: int,
    max_objective_value: float,
    max_constraint_satisfaction: float,
    tenant_id: str = "default",
    severity: Optional[str] = None,
    observed_at: Optional[datetime] = None,
):
    """Record an optimization-invocation event at production-readiness shape.

    Returns the stored ProductionOptimization when gate enabled AND
    severity-floor admits; returns None when gate off OR severity below
    floor.

    severity-tier derived (pareto_front_size,
    max_constraint_satisfaction) when caller omits.
    """
    if not DT_PRODUCTION_OPTIMIZATION_ENABLED:
        return None
    derived_severity = severity_tier_for_pareto(
        pareto_front_size, max_constraint_satisfaction
    )
    effective_severity = severity or derived_severity
    if not _severity_at_or_above_floor(
        effective_severity, DT_PRODUCTION_OPTIMIZATION_SEVERITY_FLOOR
    ):
        return None
    ts = as_naive_utc(observed_at) if observed_at else now_utc()
    record = ProductionOptimization(
        request_id=request_id,
        pareto_front_size=int(pareto_front_size),
        max_objective_value=float(max_objective_value),
        max_constraint_satisfaction=float(max_constraint_satisfaction),
        severity=effective_severity,
        tenant_id=tenant_id,
        observed_at=ts,
    )
    with _PRODUCTION_OPTIMIZATION_LOCK:
        _PRODUCTION_OPTIMIZATIONS.append(record)
        if len(_PRODUCTION_OPTIMIZATIONS) > DT_PRODUCTION_OPTIMIZATION_RING_CAP:
            del _PRODUCTION_OPTIMIZATIONS[
                : len(_PRODUCTION_OPTIMIZATIONS) - DT_PRODUCTION_OPTIMIZATION_RING_CAP
            ]
    return record


def get_production_optimizations():
    """All recorded production optimization records. Empty when gate off."""
    if not DT_PRODUCTION_OPTIMIZATION_ENABLED:
        return []
    with _PRODUCTION_OPTIMIZATION_LOCK:
        return list(_PRODUCTION_OPTIMIZATIONS)


def get_production_optimization_count() -> int:
    """Aggregate count for dashboard-data defensive-accessor
    (Round-57 P2). Returns 0 when gate off."""
    if not DT_PRODUCTION_OPTIMIZATION_ENABLED:
        return 0
    with _PRODUCTION_OPTIMIZATION_LOCK:
        return len(_PRODUCTION_OPTIMIZATIONS)


def get_severity_for_optimization(request_id: str):
    """Last-known severity for request_id; None when unknown."""
    if not DT_PRODUCTION_OPTIMIZATION_ENABLED:
        return None
    with _PRODUCTION_OPTIMIZATION_LOCK:
        for r in reversed(_PRODUCTION_OPTIMIZATIONS):
            if r.request_id == request_id:
                return r.severity
        return None


def known_production_optimizations():
    """Diagnostic accessor — sorted unique (severity, tenant_id) pairs."""
    if not DT_PRODUCTION_OPTIMIZATION_ENABLED:
        return []
    with _PRODUCTION_OPTIMIZATION_LOCK:
        return sorted({(r.severity, r.tenant_id) for r in _PRODUCTION_OPTIMIZATIONS})
