"""ProductionPipeline substrate sibling: the 5th native
landing of the callsite-wire shape.

Sequel to (load-bearing →
 reference architecture).

Default-off env-gates, on the sibling-within-existing-module discipline.

Domain-agnostic: pipeline_id + tenant_id opaque scalars. Per
 Lever 1+4 cross-cut — substrate-callsite-wire
is the per-pipeline-emit hook for the 4th kernel-amplification axis.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime
from ..clock import as_naive_utc, now_utc

from typing import Dict, List, Optional


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "1" if default else "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


DT_PRODUCTION_PIPELINE_ENABLED: bool = _env_bool(
    "DT_PRODUCTION_PIPELINE_ENABLED", default=False
)
DT_PRODUCTION_PIPELINE_RING_CAP: int = int(
    os.environ.get("DT_PRODUCTION_PIPELINE_RING_CAP", "512")
)


PRODUCTION_PIPELINE_SEVERITY_LOW: str = "LOW"
PRODUCTION_PIPELINE_SEVERITY_MEDIUM: str = "MEDIUM"
PRODUCTION_PIPELINE_SEVERITY_HIGH: str = "HIGH"
PRODUCTION_PIPELINE_SEVERITY_CRITICAL: str = "CRITICAL"
KNOWN_PRODUCTION_PIPELINE_SEVERITY_FLOORS = frozenset([
    PRODUCTION_PIPELINE_SEVERITY_LOW,
    PRODUCTION_PIPELINE_SEVERITY_MEDIUM,
    PRODUCTION_PIPELINE_SEVERITY_HIGH,
    PRODUCTION_PIPELINE_SEVERITY_CRITICAL,
])
DEFAULT_PRODUCTION_PIPELINE_SEVERITY_FLOOR: str = PRODUCTION_PIPELINE_SEVERITY_LOW

_SEVERITY_RANK: Dict[str, int] = {
    PRODUCTION_PIPELINE_SEVERITY_LOW: 1,
    PRODUCTION_PIPELINE_SEVERITY_MEDIUM: 2,
    PRODUCTION_PIPELINE_SEVERITY_HIGH: 3,
    PRODUCTION_PIPELINE_SEVERITY_CRITICAL: 4,
}

DT_PRODUCTION_PIPELINE_SEVERITY_FLOOR: str = os.environ.get(
    "DT_PRODUCTION_PIPELINE_SEVERITY_FLOOR",
    DEFAULT_PRODUCTION_PIPELINE_SEVERITY_FLOOR,
).upper()
if DT_PRODUCTION_PIPELINE_SEVERITY_FLOOR not in KNOWN_PRODUCTION_PIPELINE_SEVERITY_FLOORS:
    DT_PRODUCTION_PIPELINE_SEVERITY_FLOOR = DEFAULT_PRODUCTION_PIPELINE_SEVERITY_FLOOR


def severity_tier_for_pipeline(
    total_steps: int,
    failed_steps: int,
) -> str:
    """4-tier severity: failure-rate + step-count proxies."""
    fail_rate = (failed_steps / total_steps) if total_steps > 0 else 0.0
    if fail_rate >= 0.5 or total_steps > 16:
        return PRODUCTION_PIPELINE_SEVERITY_CRITICAL
    if fail_rate >= 0.25 or total_steps > 8:
        return PRODUCTION_PIPELINE_SEVERITY_HIGH
    if fail_rate > 0.0 or total_steps > 4:
        return PRODUCTION_PIPELINE_SEVERITY_MEDIUM
    return PRODUCTION_PIPELINE_SEVERITY_LOW


@dataclass(frozen=True)
class ProductionPipeline:
    """ per-pipeline-execution production-readiness record."""

    pipeline_id: str
    total_steps: int
    succeeded_steps: int
    failed_steps: int
    severity: str
    tenant_id: str
    observed_at: datetime


def _resolve_severity_floor(value):  # noqa: ANN001
    if value is None:
        return DEFAULT_PRODUCTION_PIPELINE_SEVERITY_FLOOR
    v = value.upper()
    if v not in KNOWN_PRODUCTION_PIPELINE_SEVERITY_FLOORS:
        return DEFAULT_PRODUCTION_PIPELINE_SEVERITY_FLOOR
    return v


def _severity_at_or_above_floor(severity: str, floor: str) -> bool:
    s = _resolve_severity_floor(severity)
    f = _resolve_severity_floor(floor)
    return _SEVERITY_RANK[s] >= _SEVERITY_RANK[f]


_PRODUCTION_PIPELINES: List["ProductionPipeline"] = []
_PRODUCTION_PIPELINE_LOCK = threading.RLock()


def record_production_pipeline(
    pipeline_id: str,
    total_steps: int,
    succeeded_steps: int,
    failed_steps: int,
    tenant_id: str = "default",
    severity: Optional[str] = None,
    observed_at: Optional[datetime] = None,
):
    """On the sibling-within-existing-module discipline."""
    if not DT_PRODUCTION_PIPELINE_ENABLED:
        return None
    derived_severity = severity_tier_for_pipeline(total_steps, failed_steps)
    effective_severity = severity or derived_severity
    if not _severity_at_or_above_floor(
        effective_severity, DT_PRODUCTION_PIPELINE_SEVERITY_FLOOR
    ):
        return None
    ts = as_naive_utc(observed_at) if observed_at else now_utc()
    record = ProductionPipeline(
        pipeline_id=pipeline_id,
        total_steps=int(total_steps),
        succeeded_steps=int(succeeded_steps),
        failed_steps=int(failed_steps),
        severity=effective_severity,
        tenant_id=tenant_id,
        observed_at=ts,
    )
    with _PRODUCTION_PIPELINE_LOCK:
        _PRODUCTION_PIPELINES.append(record)
        if len(_PRODUCTION_PIPELINES) > DT_PRODUCTION_PIPELINE_RING_CAP:
            del _PRODUCTION_PIPELINES[
                : len(_PRODUCTION_PIPELINES) - DT_PRODUCTION_PIPELINE_RING_CAP
            ]
    return record


def get_production_pipelines():
    if not DT_PRODUCTION_PIPELINE_ENABLED:
        return []
    with _PRODUCTION_PIPELINE_LOCK:
        return list(_PRODUCTION_PIPELINES)


def get_production_pipeline_count() -> int:
    """Dashboard-data accessor."""
    if not DT_PRODUCTION_PIPELINE_ENABLED:
        return 0
    with _PRODUCTION_PIPELINE_LOCK:
        return len(_PRODUCTION_PIPELINES)


def get_severity_for_pipeline(pipeline_id: str):
    if not DT_PRODUCTION_PIPELINE_ENABLED:
        return None
    with _PRODUCTION_PIPELINE_LOCK:
        for r in reversed(_PRODUCTION_PIPELINES):
            if r.pipeline_id == pipeline_id:
                return r.severity
        return None


def known_production_pipelines():
    if not DT_PRODUCTION_PIPELINE_ENABLED:
        return []
    with _PRODUCTION_PIPELINE_LOCK:
        return sorted({(r.severity, r.tenant_id) for r in _PRODUCTION_PIPELINES})
