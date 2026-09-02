"""ProductionTraversal substrate sibling: the sixth native landing of the
sub-cluster callsite-wire shape.

The second axis built ground-up with this shape rather than backfilled
into it.

Substrate sibling alongside `arbiter_engine/twin/traverser.py` foundation
(TopologyTraverser kernel + NLTraversalTranslator). Independent ring;
foundation TopologyTraverser preserved unchanged.

Records ProductionTraversal events on each `TopologyTraverser.traverse()`
invocation (callsite-wire at line 231-232 of traverser.py). Each record
captures: (start_node, direction, value_mode, hop_count, gap_count,
traversal_severity, observed_at, tenant_id, emit_policy).

traversal_severity log-normalized scalar from `hop_count *gap_count`
clamped to [0, 1] — single-node-zero-gap = LOW; deep-multi-gap = CRITICAL.
Severity-tier mapping (computed not stored): severity < 0.25 → LOW;
0.25-0.5 → MEDIUM; 0.5-0.75 → HIGH; >= 0.75 → CRITICAL.

Three-level cascade safety is preserved: tenant, then privacy, then
evidence-pack, compounded at the MEDIUM floor and extended to traversal at
kernel level.

Default-off env-gates.

The NaturalCategoryDispatcher, via 4-value
severity-floor enum.

The sibling-within-existing-module discipline.

Domain-agnostic: start_node + direction + value_mode opaque scalars; no
per-domain dispatch. Composes with the kernel-as-atom design centre — substrate-callsite-wire IS the per-traversal-emit hook.
"""

from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from ..clock import as_naive_utc, now_utc

from typing import Dict, List, Optional


# ---------- default-off env-gates ----------

def _env_bool_cd1282(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "1" if default else "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


DT_PRODUCTION_TRAVERSAL_ENABLED: bool = _env_bool_cd1282(
    "DT_PRODUCTION_TRAVERSAL_ENABLED", default=False
)
DT_PRODUCTION_TRAVERSAL_RING_CAP: int = int(
    os.environ.get("DT_PRODUCTION_TRAVERSAL_RING_CAP", "10000")
)


PRODUCTION_TRAVERSAL_SEVERITY_LOW: str = "LOW"
PRODUCTION_TRAVERSAL_SEVERITY_MEDIUM: str = "MEDIUM"
PRODUCTION_TRAVERSAL_SEVERITY_HIGH: str = "HIGH"
PRODUCTION_TRAVERSAL_SEVERITY_CRITICAL: str = "CRITICAL"
KNOWN_PRODUCTION_TRAVERSAL_SEVERITY_FLOORS = frozenset([
    PRODUCTION_TRAVERSAL_SEVERITY_LOW,
    PRODUCTION_TRAVERSAL_SEVERITY_MEDIUM,
    PRODUCTION_TRAVERSAL_SEVERITY_HIGH,
    PRODUCTION_TRAVERSAL_SEVERITY_CRITICAL,
])
DEFAULT_PRODUCTION_TRAVERSAL_SEVERITY_FLOOR: str = (
    PRODUCTION_TRAVERSAL_SEVERITY_MEDIUM
)

_SEVERITY_RANK_CD1282: Dict[str, int] = {
    PRODUCTION_TRAVERSAL_SEVERITY_LOW: 1,
    PRODUCTION_TRAVERSAL_SEVERITY_MEDIUM: 2,
    PRODUCTION_TRAVERSAL_SEVERITY_HIGH: 3,
    PRODUCTION_TRAVERSAL_SEVERITY_CRITICAL: 4,
}

DT_PRODUCTION_TRAVERSAL_SEVERITY_FLOOR: str = os.environ.get(
    "DT_PRODUCTION_TRAVERSAL_SEVERITY_FLOOR",
    DEFAULT_PRODUCTION_TRAVERSAL_SEVERITY_FLOOR,
).upper()
if DT_PRODUCTION_TRAVERSAL_SEVERITY_FLOOR not in KNOWN_PRODUCTION_TRAVERSAL_SEVERITY_FLOORS:
    DT_PRODUCTION_TRAVERSAL_SEVERITY_FLOOR = DEFAULT_PRODUCTION_TRAVERSAL_SEVERITY_FLOOR


# ---------- traversal_severity derivation ----------

# Normalization basis: 16 axes *10000 ring records (same shape as
# tenant_severity + pack_severity).
_TRAVERSAL_SEVERITY_NORM_BASE: float = math.log(16 * 10000 + 1)


def compute_traversal_severity_per_cd1282(
    hop_count: int, gap_count: int,
) -> float:
    """Log-normalized traversal_severity scalar in [0, 1].

    Maps (hop_count *gap_count) product into severity via log-normalize
    so a 1-hop 0-gap traversal stays at LOW while a 16-hop 100-gap
    traversal saturates at CRITICAL.
    """
    hop_count = max(0, int(hop_count))
    gap_count = max(0, int(gap_count))
    raw = math.log(hop_count * gap_count + 1) / _TRAVERSAL_SEVERITY_NORM_BASE
    return min(1.0, max(0.0, raw))


def severity_tier_for_traversal_severity_per_cd1282(
    traversal_severity: float,
) -> str:
    """Severity-tier mapping Decision section.

    < 0.25 -> LOW; 0.25-0.5 -> MEDIUM; 0.5-0.75 -> HIGH; >= 0.75 -> CRITICAL.
    """
    if traversal_severity < 0.25:
        return PRODUCTION_TRAVERSAL_SEVERITY_LOW
    if traversal_severity < 0.5:
        return PRODUCTION_TRAVERSAL_SEVERITY_MEDIUM
    if traversal_severity < 0.75:
        return PRODUCTION_TRAVERSAL_SEVERITY_HIGH
    return PRODUCTION_TRAVERSAL_SEVERITY_CRITICAL


# ---------- ProductionTraversal dataclass ----------


@dataclass(frozen=True)
class ProductionTraversal:
    """ per-traversal-invocation production-readiness record.

    8 opaque fields (extended from canonical 7 with tenant_id for
    composition) domain-agnostic invariant. Frozen for audit-
    trail provenance emit-policy decision.

    KEY: (start_node, direction, value_mode, observed_at) implicit;
    METRICS: hop_count + gap_count + traversal_severity scalar +
    severity tier; PROVENANCE: emit_policy + tenant_id.
    """

    start_node: str
    direction: str
    value_mode: str
    hop_count: int
    gap_count: int
    traversal_severity: float
    severity: str
    observed_at: datetime
    tenant_id: str
    emit_policy: str


def _resolve_severity_floor_cd1282(value):  # noqa: ANN001
    if value is None:
        return DEFAULT_PRODUCTION_TRAVERSAL_SEVERITY_FLOOR
    v = value.upper()
    if v not in KNOWN_PRODUCTION_TRAVERSAL_SEVERITY_FLOORS:
        return DEFAULT_PRODUCTION_TRAVERSAL_SEVERITY_FLOOR
    return v


def _severity_at_or_above_floor_cd1282(severity: str, floor: str) -> bool:
    s = _resolve_severity_floor_cd1282(severity)
    f = _resolve_severity_floor_cd1282(floor)
    return _SEVERITY_RANK_CD1282[s] >= _SEVERITY_RANK_CD1282[f]


# ---------- ring buffer + lock ----------


_PRODUCTION_TRAVERSALS: List["ProductionTraversal"] = []
_PRODUCTION_TRAVERSAL_LOCK = threading.RLock()


# ---------- 5 public functions ----------


def record_production_traversal(
    start_node: str,
    direction: str,
    value_mode: str,
    hop_count: int,
    gap_count: int,
    tenant_id: str = "default",
    traversal_severity: Optional[float] = None,
    severity: Optional[str] = None,
    observed_at: Optional[datetime] = None,
    emit_policy: str = "hybrid",
):
    """Record a traversal-invocation event at production-readiness shape.

    Returns the stored ProductionTraversal when gate enabled AND severity-
    floor admits; returns None when gate off OR severity below floor.

    traversal_severity derivation: when caller omits, derive
    log-normalized scalar from hop_count *gap_count.

    severity-tier (LOW/MEDIUM/HIGH/CRITICAL) derived from
    traversal_severity scalar when caller omits.
    """
    if not DT_PRODUCTION_TRAVERSAL_ENABLED:
        return None
    if traversal_severity is None:
        traversal_severity = compute_traversal_severity_per_cd1282(
            hop_count, gap_count
        )
    derived_severity = severity_tier_for_traversal_severity_per_cd1282(
        float(traversal_severity)
    )
    effective_severity = severity or derived_severity
    if not _severity_at_or_above_floor_cd1282(
        effective_severity, DT_PRODUCTION_TRAVERSAL_SEVERITY_FLOOR
    ):
        return None
    ts = as_naive_utc(observed_at) if observed_at else now_utc()
    record = ProductionTraversal(
        start_node=start_node,
        direction=direction,
        value_mode=value_mode,
        hop_count=int(hop_count),
        gap_count=int(gap_count),
        traversal_severity=float(traversal_severity),
        severity=effective_severity,
        observed_at=ts,
        tenant_id=tenant_id,
        emit_policy=emit_policy,
    )
    with _PRODUCTION_TRAVERSAL_LOCK:
        _PRODUCTION_TRAVERSALS.append(record)
        if len(_PRODUCTION_TRAVERSALS) > DT_PRODUCTION_TRAVERSAL_RING_CAP:
            del _PRODUCTION_TRAVERSALS[
                : len(_PRODUCTION_TRAVERSALS) - DT_PRODUCTION_TRAVERSAL_RING_CAP
            ]
    return record


def get_production_traversals():
    """All recorded production traversal records. Empty when gate off."""
    if not DT_PRODUCTION_TRAVERSAL_ENABLED:
        return []
    with _PRODUCTION_TRAVERSAL_LOCK:
        return list(_PRODUCTION_TRAVERSALS)


def get_production_traversal_count() -> int:
    """Aggregate count for dashboard-data defensive-accessor
    (Round-55 P2). Returns 0 when gate off."""
    if not DT_PRODUCTION_TRAVERSAL_ENABLED:
        return 0
    with _PRODUCTION_TRAVERSAL_LOCK:
        return len(_PRODUCTION_TRAVERSALS)


def get_severity_for_traversal(start_node: str):
    """Last-known traversal_severity for start_node; None when unknown."""
    if not DT_PRODUCTION_TRAVERSAL_ENABLED:
        return None
    with _PRODUCTION_TRAVERSAL_LOCK:
        for r in reversed(_PRODUCTION_TRAVERSALS):
            if r.start_node == start_node:
                return r.traversal_severity
        return None


def known_production_traversals():
    """Diagnostic accessor — sorted unique (start_node, direction) pairs."""
    if not DT_PRODUCTION_TRAVERSAL_ENABLED:
        return []
    with _PRODUCTION_TRAVERSAL_LOCK:
        return sorted({(r.start_node, r.direction) for r in _PRODUCTION_TRAVERSALS})


def _reset_production_traversal_for_tests() -> None:
    with _PRODUCTION_TRAVERSAL_LOCK:
        _PRODUCTION_TRAVERSALS.clear()
