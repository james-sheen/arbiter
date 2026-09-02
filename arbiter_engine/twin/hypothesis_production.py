"""ProductionHypothesis substrate sibling: the 3rd native
landing of the callsite-wire shape.

The third axis built ground-up with this shape rather than backfilled
into it.

Substrate sibling alongside `arbiter_engine/twin/hypothesis_generator.py`
(HypothesisGenerator + TopologyHypothesis). Independent ring;
generator preserved unchanged.

Records ProductionHypothesis events on each `HypothesisGenerator.emit()`
invocation (callsite-wire at `hypothesis_generator.py` defensive-import).
Each record captures: (hypothesis_id, hypothesis_type, confidence,
evidence_traversal_id, tenant_id, observed_at).

hypothesis_severity is the confidence scalar itself (no log-normalize —
confidence IS in [0,1] frozen schema). Severity-tier mapping
(computed not stored): confidence < 0.25 -> LOW; 0.25-0.5 -> MEDIUM;
0.5-0.75 -> HIGH; >= 0.75 -> CRITICAL.

Three-level cascade safety is preserved: tenant, then privacy, then
evidence-pack, then traversal, compounded at the MEDIUM floor and extended
to hypothesis at kernel-amplification level.

Default-off env-gates decision shape
(DT_PRODUCTION_HYPOTHESIS_ENABLED + DT_PRODUCTION_HYPOTHESIS_SEVERITY_FLOOR).

The sibling-within-existing-module discipline.

Domain-agnostic: hypothesis_id + hypothesis_type opaque scalars; no
per-domain dispatch. Composes with Lever 2
(Topology-Hypothesis Generator) — substrate-callsite-wire IS the
per-hypothesis-emit hook for the 5th DT-mode HYPOTHESIZE.
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


DT_PRODUCTION_HYPOTHESIS_ENABLED: bool = _env_bool(
    "DT_PRODUCTION_HYPOTHESIS_ENABLED", default=False
)
DT_PRODUCTION_HYPOTHESIS_RING_CAP: int = int(
    os.environ.get("DT_PRODUCTION_HYPOTHESIS_RING_CAP", "512")
)


PRODUCTION_HYPOTHESIS_SEVERITY_LOW: str = "LOW"
PRODUCTION_HYPOTHESIS_SEVERITY_MEDIUM: str = "MEDIUM"
PRODUCTION_HYPOTHESIS_SEVERITY_HIGH: str = "HIGH"
PRODUCTION_HYPOTHESIS_SEVERITY_CRITICAL: str = "CRITICAL"
KNOWN_PRODUCTION_HYPOTHESIS_SEVERITY_FLOORS = frozenset([
    PRODUCTION_HYPOTHESIS_SEVERITY_LOW,
    PRODUCTION_HYPOTHESIS_SEVERITY_MEDIUM,
    PRODUCTION_HYPOTHESIS_SEVERITY_HIGH,
    PRODUCTION_HYPOTHESIS_SEVERITY_CRITICAL,
])
DEFAULT_PRODUCTION_HYPOTHESIS_SEVERITY_FLOOR: str = (
    PRODUCTION_HYPOTHESIS_SEVERITY_LOW
)

_SEVERITY_RANK: Dict[str, int] = {
    PRODUCTION_HYPOTHESIS_SEVERITY_LOW: 1,
    PRODUCTION_HYPOTHESIS_SEVERITY_MEDIUM: 2,
    PRODUCTION_HYPOTHESIS_SEVERITY_HIGH: 3,
    PRODUCTION_HYPOTHESIS_SEVERITY_CRITICAL: 4,
}

DT_PRODUCTION_HYPOTHESIS_SEVERITY_FLOOR: str = os.environ.get(
    "DT_PRODUCTION_HYPOTHESIS_SEVERITY_FLOOR",
    DEFAULT_PRODUCTION_HYPOTHESIS_SEVERITY_FLOOR,
).upper()
if DT_PRODUCTION_HYPOTHESIS_SEVERITY_FLOOR not in KNOWN_PRODUCTION_HYPOTHESIS_SEVERITY_FLOORS:
    DT_PRODUCTION_HYPOTHESIS_SEVERITY_FLOOR = DEFAULT_PRODUCTION_HYPOTHESIS_SEVERITY_FLOOR


# ---------- hypothesis_severity derivation ----------

def severity_tier_for_confidence(confidence: float) -> str:
    """Severity-tier mapping + precedent.

    < 0.25 -> LOW; 0.25-0.5 -> MEDIUM; 0.5-0.75 -> HIGH; >= 0.75 -> CRITICAL.
    Confidence IS the severity scalar (no log-normalize needed since
     frozen schema already constrains confidence to [0, 1]).
    """
    c = max(0.0, min(1.0, float(confidence)))
    if c < 0.25:
        return PRODUCTION_HYPOTHESIS_SEVERITY_LOW
    if c < 0.5:
        return PRODUCTION_HYPOTHESIS_SEVERITY_MEDIUM
    if c < 0.75:
        return PRODUCTION_HYPOTHESIS_SEVERITY_HIGH
    return PRODUCTION_HYPOTHESIS_SEVERITY_CRITICAL


# ---------- ProductionHypothesis dataclass ----------

@dataclass(frozen=True)
class ProductionHypothesis:
    """ per-hypothesis-emission production-readiness record.

    6 opaque fields frozen-typed schema (subset of the full 9
     fields — production substrate doesn't carry precondition/effect
    patterns or nl_text; those live in the TopologyHypothesis identity).

    KEY: (hypothesis_id, observed_at) implicit;
    METRICS: hypothesis_type + confidence + severity tier;
    PROVENANCE: evidence_traversal_id + tenant_id.
    """

    hypothesis_id: str
    hypothesis_type: str
    confidence: float
    severity: str
    evidence_traversal_id: Optional[str]
    tenant_id: str
    observed_at: datetime


def _resolve_severity_floor(value):  # noqa: ANN001
    if value is None:
        return DEFAULT_PRODUCTION_HYPOTHESIS_SEVERITY_FLOOR
    v = value.upper()
    if v not in KNOWN_PRODUCTION_HYPOTHESIS_SEVERITY_FLOORS:
        return DEFAULT_PRODUCTION_HYPOTHESIS_SEVERITY_FLOOR
    return v


def _severity_at_or_above_floor(severity: str, floor: str) -> bool:
    s = _resolve_severity_floor(severity)
    f = _resolve_severity_floor(floor)
    return _SEVERITY_RANK[s] >= _SEVERITY_RANK[f]


# ---------- ring buffer + lock ----------

_PRODUCTION_HYPOTHESES: List["ProductionHypothesis"] = []
_PRODUCTION_HYPOTHESIS_LOCK = threading.RLock()


# ---------- 5 public functions ----------

def record_production_hypothesis(
    hypothesis_id: str,
    hypothesis_type: str,
    confidence: float,
    evidence_traversal_id: Optional[str] = None,
    tenant_id: str = "default",
    severity: Optional[str] = None,
    observed_at: Optional[datetime] = None,
):
    """Record a hypothesis-emission event at production-readiness shape.

    Returns the stored ProductionHypothesis when gate enabled AND
    severity-floor admits; returns None when gate off OR severity below
    floor.

    severity-tier derived from confidence scalar when caller
    omits.
    """
    if not DT_PRODUCTION_HYPOTHESIS_ENABLED:
        return None
    derived_severity = severity_tier_for_confidence(confidence)
    effective_severity = severity or derived_severity
    if not _severity_at_or_above_floor(
        effective_severity, DT_PRODUCTION_HYPOTHESIS_SEVERITY_FLOOR
    ):
        return None
    ts = as_naive_utc(observed_at) if observed_at else now_utc()
    record = ProductionHypothesis(
        hypothesis_id=hypothesis_id,
        hypothesis_type=hypothesis_type,
        confidence=float(confidence),
        severity=effective_severity,
        evidence_traversal_id=evidence_traversal_id,
        tenant_id=tenant_id,
        observed_at=ts,
    )
    with _PRODUCTION_HYPOTHESIS_LOCK:
        _PRODUCTION_HYPOTHESES.append(record)
        if len(_PRODUCTION_HYPOTHESES) > DT_PRODUCTION_HYPOTHESIS_RING_CAP:
            del _PRODUCTION_HYPOTHESES[
                : len(_PRODUCTION_HYPOTHESES) - DT_PRODUCTION_HYPOTHESIS_RING_CAP
            ]
    return record


def get_production_hypotheses():
    """All recorded production hypothesis records. Empty when gate off."""
    if not DT_PRODUCTION_HYPOTHESIS_ENABLED:
        return []
    with _PRODUCTION_HYPOTHESIS_LOCK:
        return list(_PRODUCTION_HYPOTHESES)


def get_production_hypothesis_count() -> int:
    """Aggregate count for dashboard-data defensive-accessor
    (Round-56 P2). Returns 0 when gate off."""
    if not DT_PRODUCTION_HYPOTHESIS_ENABLED:
        return 0
    with _PRODUCTION_HYPOTHESIS_LOCK:
        return len(_PRODUCTION_HYPOTHESES)


def get_severity_for_hypothesis(hypothesis_id: str):
    """Last-known severity for hypothesis_id; None when unknown."""
    if not DT_PRODUCTION_HYPOTHESIS_ENABLED:
        return None
    with _PRODUCTION_HYPOTHESIS_LOCK:
        for r in reversed(_PRODUCTION_HYPOTHESES):
            if r.hypothesis_id == hypothesis_id:
                return r.severity
        return None


def known_production_hypotheses():
    """Diagnostic accessor — sorted unique (hypothesis_type, severity) pairs."""
    if not DT_PRODUCTION_HYPOTHESIS_ENABLED:
        return []
    with _PRODUCTION_HYPOTHESIS_LOCK:
        return sorted({(r.hypothesis_type, r.severity) for r in _PRODUCTION_HYPOTHESES})
