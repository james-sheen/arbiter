"""cross-source observation wire-up.

Composes multi-source observations (Redis Streams + InMemory + TimescaleDB
+ document pipeline) into per-entity source-lineage aggregations for the
 ProductionObservation pipeline.

separation-of-concerns: wire-up is stateless across
wire_observation_sources_for_entity() calls; tracks per-entity source-id
set for dashboard accessor entry point. Defensive: gate off →
wire-up no-op; ProductionObservation pipeline operates on raw per-source
records (hybrid emit gates per-source via record_observation).

an established pattern env-gate `DT_OBSERVATION_SOURCE_WIRING_ENABLED`.

the established pattern wire-up-as-standalone-module discipline — over-saturated reference
architecture (beyond the established pattern threshold).

Domain-agnostic: entity_id + source_id scalars opaque; no per-domain
dispatch.
"""

from __future__ import annotations

import os
import threading
from typing import Dict, List, Optional, Set


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "1" if default else "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


DT_OBSERVATION_SOURCE_WIRING_ENABLED: bool = _env_bool(
    "DT_OBSERVATION_SOURCE_WIRING_ENABLED", default=False
)


# entity_id -> Set[source_id] (per-entity source-lineage set)
_WIRED_SOURCES: Dict[str, Set[str]] = {}
_WIRING_LOCK = threading.RLock()


def wire_observation_sources_for_entity(
    entity_id: str,
    source_ids: List[str],
) -> bool:
    """Register an entity's per-source observation lineage.

    source_ids: list of source_id strings observed for this entity.

    Returns True when wired (gate enabled); False when gate off (no-op).
    Per spec: this wiring computes per-entity source-lineage set
    (union of observed source_ids); operators consume via
    get_source_lineage_for_entity for partner-facing source-attribution
    surfaces.
    """
    if not DT_OBSERVATION_SOURCE_WIRING_ENABLED:
        return False
    if not source_ids:
        return False
    with _WIRING_LOCK:
        _WIRED_SOURCES[entity_id] = set(source_ids)
    return True


def get_source_lineage_for_entity(
    entity_id: str,
) -> Optional[List[str]]:
    """Look up wired source-lineage list for an entity.

    Returns None when gate off OR entity not wired.
    Returns sorted source_ids list (deterministic ordering) when wired.
    """
    if not DT_OBSERVATION_SOURCE_WIRING_ENABLED:
        return None
    with _WIRING_LOCK:
        lineage = _WIRED_SOURCES.get(entity_id)
        if lineage is None:
            return None
        return sorted(lineage)


def get_source_count_for_entity(entity_id: str) -> Optional[int]:
    """Look up source count for an entity.

    Returns None when gate off OR entity not wired.
    """
    if not DT_OBSERVATION_SOURCE_WIRING_ENABLED:
        return None
    with _WIRING_LOCK:
        lineage = _WIRED_SOURCES.get(entity_id)
        if lineage is None:
            return None
        return len(lineage)


def get_observation_source_wired_entity_count() -> int:
    """Aggregate count of source-wired entities.

    Dashboard-data defensive-accessor entry point + Pattern
    171. Returns 0 when gate off.
    """
    if not DT_OBSERVATION_SOURCE_WIRING_ENABLED:
        return 0
    with _WIRING_LOCK:
        return len(_WIRED_SOURCES)


def known_source_wired_entities() -> List[str]:
    """Diagnostic accessor — sorted list of source-wired entity_ids."""
    if not DT_OBSERVATION_SOURCE_WIRING_ENABLED:
        return []
    with _WIRING_LOCK:
        return sorted(_WIRED_SOURCES.keys())


def _reset_wired_sources_for_tests() -> None:
    with _WIRING_LOCK:
        _WIRED_SOURCES.clear()
