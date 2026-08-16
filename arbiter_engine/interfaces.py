"""
Abstract interfaces for the detection system.

This module defines the contracts that all detection layers must implement,
as well as core dataclasses used across the system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import (
    Any, Callable, ClassVar, Dict, List, Optional, Protocol, Set, Tuple, Union,
    runtime_checkable,
)
import uuid

from .types import (
    Axiom,
    Severity,
    DetectionLayer,
    IndicatorType,
    AxiomParameters,
    AxiomReadiness,
    NotEvaluated,
    NotEvaluatedReason,
)


# Severity ordering for confidence-based modulation
_SEVERITY_ORDER = [
    Severity.INFO, Severity.WARNING, Severity.LOW,
    Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL,
]
_SEVERITY_RANK = {s: i for i, s in enumerate(_SEVERITY_ORDER)}


# =============================================================================
# Property Metadata (Phase A —)
# =============================================================================

@dataclass
class PropertyMetadata:
    """Optional metadata for any entity property.

    All fields have defaults that preserve current behavior.
    Layer 3 adapters populate these based on domain knowledge.
    """
    confidence: float = 1.0        # 0.0-1.0, certainty of value
    staleness_seconds: float = 0   # age of reading
    source: str = "direct"         # provenance: direct, sensor, estimate,
                                   # opinion, algorithm, derived
    resolution: float = 0          # measurement granularity


def modulate_severity(base_severity: Severity, confidence: float) -> Severity:
    """Downgrade severity when property confidence is below 1.0.

    CRITICAL @ confidence 0.7 → HIGH
    CRITICAL @ confidence 0.4 → MEDIUM
    HIGH @ confidence 0.7 → MEDIUM
    etc.

    Returns the same severity when confidence >= 0.95 (near-certain).
    """
    if confidence >= 0.95:
        return base_severity
    rank = _SEVERITY_RANK.get(base_severity, 0)
    # Drop one rank per 0.3 drop in confidence
    drops = int((1.0 - confidence) / 0.3)
    new_rank = max(0, rank - drops)
    return _SEVERITY_ORDER[new_rank]


def sampling_context(history, entity_id: str, property_name: str,
                     window) -> dict:
    """The facts that make a sample-floor decline interpretable.

    Returns ``window_seconds``, ``total_observations`` (over all recorded
    history, not just the window) and ``sampling_interval_seconds`` (the
    *median* gap between consecutive observations), as kwargs for
    :meth:`CheckOutcome.declined`.

    Median rather than mean because a single long gap — a restart, a scrape
    outage — should not make a regularly-sampled series look sparse. That is
    the same reasoning applied when it replaced least squares with
    Theil-Sen: one outlier must not set the summary statistic.

    Returns only what it can compute. A caller that cannot supply history, or
    a series with fewer than two points, yields no interval rather than a
    guessed one — `floor_unreachable_at_this_rate` then stays False, which is
    the right default for a claim about impossibility.
    """
    out: dict = {}
    if window is not None:
        out["window_seconds"] = window.total_seconds()
    if history is None:
        return out
    try:
        from datetime import timedelta
        everything = history.get_values(
            entity_id, property_name, timedelta(days=3650))
    except Exception:  # noqa: BLE001 — a history that cannot answer is not an
        return out    # error here; the decline is still worth emitting.
    if everything is None:
        return out
    out["total_observations"] = len(everything)
    stamps = sorted(t for t, _ in everything)
    if len(stamps) < 2:
        return out
    gaps = sorted((b - a).total_seconds()
                  for a, b in zip(stamps, stamps[1:]))
    mid = len(gaps) // 2
    median = (gaps[mid] if len(gaps) % 2
              else (gaps[mid - 1] + gaps[mid]) / 2)
    if median > 0:
        out["sampling_interval_seconds"] = median
    return out


def apply_property_confidence(
    entity: 'Entity',
    property_name: str,
    problems: 'List[Problem]',
) -> 'List[Problem]':
    """Apply property metadata confidence to a list of problems.

    If the entity has PropertyMetadata for the given property,
    modulate each problem's severity and confidence accordingly.
    Adds staleness to evidence when > 0.

    No-op when entity has no property_metadata (backward compatible).
    """
    if not problems:
        return problems

    meta = getattr(entity, 'property_metadata', {}).get(property_name)
    if meta is None or meta.confidence >= 1.0:
        return problems

    for p in problems:
        p.severity = modulate_severity(p.severity, meta.confidence)
        p.confidence = min(p.confidence, meta.confidence)
        if meta.staleness_seconds > 0:
            p.evidence['staleness_seconds'] = meta.staleness_seconds
        if meta.source != 'direct':
            p.evidence['property_source'] = meta.source

    return problems


# =============================================================================
# Core Entity and Problem Dataclasses
# =============================================================================

@dataclass
class Entity:
    """
    An entity being monitored.

    Entities are the fundamental unit of observation. They have:
    - A unique ID
    - A type (e.g., 'Pod', 'Node', 'Service')
    - A human-readable name
    - A dictionary of properties
    """
    id: str
    type: str
    name: str
    properties: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    property_metadata: Dict[str, 'PropertyMetadata'] = field(default_factory=dict)

    # Entity lifecycle tracking
    created_at: Optional[str] = None  # ISO timestamp of first observation
    state_transitions: List[Dict[str, Any]] = field(default_factory=list)
    # [{timestamp, property, old_value, new_value}]

    def get_property(self, path: str, default: Any = None) -> Any:
        """
        Get property value, supporting dot notation.

        Args:
            path: Property path (e.g., 'status.phase', 'spec.containers[0].name')
            default: Default value if not found

        Returns:
            Property value or default
        """
        parts = path.replace('[', '.').replace(']', '').split('.')
        value = self.properties

        for part in parts:
            if value is None:
                return default
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, list):
                try:
                    idx = int(part)
                    value = value[idx] if 0 <= idx < len(value) else None
                except (ValueError, IndexError):
                    return default
            else:
                return default

        return value if value is not None else default

    def set_property(self, path: str, value: Any) -> None:
        """Set property value using dot notation."""
        parts = path.split('.')
        target = self.properties

        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]

        target[parts[-1]] = value

    def get_property_confidence(self, property_name: str) -> float:
        """Get confidence for a property (1.0 if no metadata)."""
        meta = self.property_metadata.get(property_name)
        return meta.confidence if meta else 1.0

    def get_property_meta(self, property_name: str) -> 'PropertyMetadata':
        """Get PropertyMetadata for a property (defaults if absent)."""
        return self.property_metadata.get(property_name, PropertyMetadata())

    def time_in_state(self, property_name: str, history: 'ObservationHistory') -> Optional[timedelta]:
        """
        Get duration entity has been in current state.

        Requires state history tracking.
        """
        current_value = self.get_property(property_name)
        if current_value is None:
            return None

        states = history.get_states(self.id, property_name, window=timedelta(days=7))
        if not states:
            return None

        # Find when current state started
        for i in range(len(states) - 1, -1, -1):
            ts, state = states[i]
            if state != current_value:
                # Previous state was different, current state started after this
                if i + 1 < len(states):
                    return datetime.utcnow() - states[i + 1][0]
                break

        # Been in this state for entire history
        return datetime.utcnow() - states[0][0]


@dataclass
class Problem:
    """
    A detected problem.

    Problems are the output of detection. They include:
    - The affected entity
    - Problem type and severity
    - Reason and evidence
    - Source layer and confidence
    - Recommended actions
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    entity_id: str = ""
    entity_type: str = ""
    entity_name: str = ""
    problem_type: str = ""
    severity: Severity = Severity.MEDIUM
    axiom: Optional[Axiom] = None
    reason: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    source_layer: DetectionLayer = DetectionLayer.CONSTRAINTS
    recommended_action: Optional[str] = None
    detected_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    diagnostic_sequence: Optional[List[Dict[str, Any]]] = None
    action_constraints: Optional[List[str]] = None

    def __post_init__(self):
        # normalize severity at the problem-ingest boundary.
        # previously ``severity: Severity = Severity.MEDIUM`` was a
        # type hint only — dataclasses don't enforce annotations at
        # runtime, so producer sites could (and historically did)
        # pass a bare string. Downstream serializers (``to_dict`` at
        # line 262 below, ``api/topology_api.py`` _serialize_traversal_
        # result) had to duck-type ``X.value if hasattr(X, 'value')
        # else str(X)`` to defend against both shapes — cruft that
        # masked the real bug (silent string-typed severity could
        # carry a typo like ``"hight"`` and survive through the
        # pipeline because str-Enum hash-equality lets typos look
        # OK at dict-key lookup).
        #
        # Subsequently a bare string gets coerced to ``Severity`` at
        # construction, with a ValueError on unknown values (typo
        # detection at the producer side, not silent drift). An
        # already-``Severity`` value is left alone. Reference-shape
        # drift archetype: sibling to (now
        # 12-member reference-shape arc).
        if not isinstance(self.severity, Severity):
            if isinstance(self.severity, str):
                try:
                    self.severity = Severity(self.severity)
                except ValueError:
                    valid = sorted(s.value for s in Severity)
                    raise ValueError(
                        f"Problem.severity={self.severity!r} is "
                        f"not a recognized Severity value. Valid choices: "
                        f"{valid}. previously unknown strings flowed "
                        f"through downstream as str (silent typo) — "
                        f"now coerced at construction."
                    )
            else:
                raise TypeError(
                    f"Problem.severity must be a Severity enum "
                    f"or canonical string; got "
                    f"{type(self.severity).__name__!r}={self.severity!r}."
                )

    @classmethod
    def from_entity(
        cls,
        entity: Entity,
        problem_type: str,
        severity: Severity,
        reason: str,
        **kwargs
    ) -> 'Problem':
        """Create a Problem from an Entity."""
        return cls(
            entity_id=entity.id,
            entity_type=entity.type,
            entity_name=entity.name,
            problem_type=problem_type,
            severity=severity,
            reason=reason,
            **kwargs
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'entity_id': self.entity_id,
            'entity_type': self.entity_type,
            'entity_name': self.entity_name,
            'problem_type': self.problem_type,
            # severity is guaranteed ``Severity`` post-
            # ``__post_init__`` coercion, so ``.value`` is safe
            # without the prior ``isinstance`` defensive branch.
            'severity': self.severity.value,
            'axiom': self.axiom.value if self.axiom else None,
            'reason': self.reason,
            'evidence': self.evidence,
            'confidence': self.confidence,
            'source_layer': self.source_layer.value if isinstance(self.source_layer, DetectionLayer) else self.source_layer,
            'recommended_action': self.recommended_action,
            'detected_at': self.detected_at.isoformat() if self.detected_at else None,
            'metadata': self.metadata,
            'diagnostic_sequence': self.diagnostic_sequence,
            'action_constraints': self.action_constraints,
        }


@dataclass
class RelationshipGraph:
    """
    Graph of relationships between entities.

    Stores directed edges with relationship types.

     (G4b drain from the snapshot-fidelity manifest):
    edges retain their ``(relation_type, target_id)`` tuple shape for
    backward compat with every consumer that destructures them, but a
    parallel ``_edge_metadata`` dict now carries the upstream
    ``Relationship.properties / strength / discovered_at`` data so
    consumers that want it (snapshot create_from_state, RCA explanation
    builders) can look it up via ``get_edge_metadata``. The graph
    layer no longer silently drops Relationship metadata.
    """
    # entity_id -> [(relation_type, target_id),...]
    edges: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict)
    # Reverse index: target_id -> [(relation_type, source_id),...]
    reverse_edges: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict)
    # parallel edge metadata. Keyed (source_id, relation_type,
    # target_id). Carries the ``Relationship.properties / strength /
    # discovered_at`` data that the (rel_type, target_id) tuple in
    # ``edges`` cannot encode. Always carries at least the three keys
    # so consumers can ``get_edge_metadata(...).get('strength', 1.0)``
    # without None-checks.
    _edge_metadata: Dict[Tuple[str, str, str], Dict[str, Any]] = field(
        default_factory=dict,
    )
    # Maximum edges per entity to prevent unbounded growth from
    # aggressive relationship discovery (e.g., temporal correlation mining).
    max_edges_per_entity: int = 200

    # Authoritative relationship types that should be evicted last.
    # These are structurally critical for causal chain traversal and RCA.
    AUTHORITATIVE_RELATIONS: ClassVar[Set[str]] = {
        'CONTROLLED_BY', 'OWNS', 'SELECTS', 'BOUND_TO', 'SCHEDULED_ON',
        'controlled_by', 'owns', 'selects', 'bound_to', 'scheduled_on',
    }

    # lifetime counter for `_edge_metadata` entries cleaned up
    # via eviction (`_evict_lowest_priority_edge`) + `remove_entity`.
    # previously those two paths popped from ``edges`` / ``reverse_edges``
    # without touching the parallel ``_edge_metadata`` dict added by
    # the orphaned entries leaked indefinitely AND poisoned
    # subsequent ``get_edge_metadata`` lookups (returning stale data
    # for an edge that no longer exists in the graph). Tracked here so
    # operators can verify cleanup is happening + diagnose if a future
    # refactor regresses it.
    _metadata_orphans_cleaned: int = 0

    def add_relationship(
        self,
        source_id: str,
        relation_type: str,
        target_id: str,
        properties: Optional[Dict[str, Any]] = None,
        strength: float = 1.0,
        discovered_at: Optional[datetime] = None,
        source_domain: Optional[str] = None,
        target_domain: Optional[str] = None,
    ) -> None:
        """Add a relationship to the graph.

        Dedup before appending to prevent unbounded edge list growth
        when the same entity pair is observed on consecutive cycles.

         (G4b drain): accepts optional ``properties / strength /
        discovered_at`` matching ``models.Relationship``. Defaults
        match the live dataclass: empty dict, 1.0, None. Stored in
        ``_edge_metadata`` keyed by ``(source_id, relation_type,
        target_id)``. Existing callers that pass only the three
        positional args see no behavior change — the metadata entry
        is created with defaults.

: accepts optional ``source_domain`` /
        ``target_domain`` for cross-domain edges /
        schema-extension. When both are set + differ, the edge is
        a cross-domain reference. Stored in ``_edge_metadata`` for
        ``get_cross_domain_neighbors`` lookups. Backward-compat:
        defaults preserve the existing single-domain shape.
        """
        if source_id not in self.edges:
            self.edges[source_id] = []
        edge_tuple = (relation_type, target_id)
        if edge_tuple not in self.edges[source_id]:
            # + Enforce max edges per entity to bound memory.
            # Evict non-authoritative (discovered/temporal) edges first
            # to preserve structurally critical ownership edges.
            # pass owner_id + direction so the evictor can also
            # clean up the corresponding ``_edge_metadata`` entry (was
            # silently orphaning metadata previously).
            if len(self.edges[source_id]) >= self.max_edges_per_entity:
                self._evict_lowest_priority_edge(
                    self.edges[source_id],
                    owner_id=source_id,
                    direction="outgoing",
                )
            self.edges[source_id].append(edge_tuple)

        if target_id not in self.reverse_edges:
            self.reverse_edges[target_id] = []
        reverse_tuple = (relation_type, source_id)
        if reverse_tuple not in self.reverse_edges[target_id]:
            if len(self.reverse_edges[target_id]) >= self.max_edges_per_entity:
                self._evict_lowest_priority_edge(
                    self.reverse_edges[target_id],
                    owner_id=target_id,
                    direction="incoming",
                )
            self.reverse_edges[target_id].append(reverse_tuple)

        # always populate metadata, even when called with no
        # extra kwargs. Consumers can rely on the dict having
        # properties / strength / discovered_at keys. An internal ruling adds
        # source_domain / target_domain keys for cross-domain edges.
        self._edge_metadata[(source_id, relation_type, target_id)] = {
            "properties": dict(properties) if properties else {},
            "strength": strength,
            "discovered_at": discovered_at,
            "source_domain": source_domain,
            "target_domain": target_domain,
        }

    def get_edge_metadata(
        self,
        source_id: str,
        relation_type: str,
        target_id: str,
    ) -> Optional[Dict[str, Any]]:
        """ (G4b drain): return the parallel metadata for an
        edge or ``None`` if the edge is unknown. Returned dict carries
        ``properties / strength / discovered_at`` keys; an internal ruling adds
        ``source_domain / target_domain`` for cross-domain edges.
        Callers can read each with a default. Returns a fresh dict
        each call — caller mutation does not affect storage.
        """
        meta = self._edge_metadata.get((source_id, relation_type, target_id))
        if meta is None:
            return None
        return {
            "properties": dict(meta.get("properties", {})),
            "strength": meta.get("strength", 1.0),
            "discovered_at": meta.get("discovered_at"),
            "source_domain": meta.get("source_domain"),
            "target_domain": meta.get("target_domain"),
        }

    def get_cross_domain_neighbors(
        self,
        entity_id: str,
        target_domain: str,
    ) -> List[str]:
        """return outgoing-edge target IDs whose
        ``target_domain`` matches ``target_domain``.

        Iterates ``edges[entity_id]`` + filters by the parallel
        metadata. Edges without an explicit ``target_domain`` are
        skipped (single-domain edges don't cross). Empty list when
        entity has no edges or no cross-domain matches.
        """
        results: List[str] = []
        for rel_type, target_id in self.edges.get(entity_id, []):
            meta = self._edge_metadata.get((entity_id, rel_type, target_id))
            if meta is None:
                continue
            if meta.get("target_domain") == target_domain:
                results.append(target_id)
        return results

    def get_cross_domain_edge_count(self) -> int:
        """count edges whose source_domain and
        target_domain differ. Single-domain edges (one or both None,
        or matching) are excluded.

        Used in graph stats reporting spec.
        """
        count = 0
        for meta in self._edge_metadata.values():
            src = meta.get("source_domain")
            dst = meta.get("target_domain")
            if src and dst and src != dst:
                count += 1
        return count

    def get_cross_domain_edges(self) -> List[Dict[str, Any]]:
        """return a list of cross-domain edge records for
        inspection. Each record carries source_id / source_domain /
        target_id / target_domain / relation_type / strength.

        Sibling to ``get_cross_domain_edge_count``; powers the
        graph-stats endpoint + diagnostic-API consumer."""
        rows: List[Dict[str, Any]] = []
        for (source_id, rel_type, target_id), meta in self._edge_metadata.items():
            src = meta.get("source_domain")
            dst = meta.get("target_domain")
            if not (src and dst and src != dst):
                continue
            rows.append({
                "source_id": source_id,
                "source_domain": src,
                "relation_type": rel_type,
                "target_id": target_id,
                "target_domain": dst,
                "strength": meta.get("strength", 1.0),
            })
        return rows

    def _evict_lowest_priority_edge(
        self,
        edge_list: List[Tuple[str, str]],
        owner_id: Optional[str] = None,
        direction: Optional[str] = None,
    ) -> None:
        """ + Remove the lowest-priority edge from the list
        AND clean up the corresponding ``_edge_metadata`` entry so
        metadata doesn't orphan.

        Evicts non-authoritative edges (discovered/temporal) before authoritative
        ownership edges (CONTROLLED_BY, OWNS, SELECTS, etc.).
        Within each priority tier, evicts oldest (first in list).

         (sibling of within the Detection-layer eviction
        surface): previously the popped edge was removed from
        ``edges`` / ``reverse_edges`` but the corresponding
        ``_edge_metadata[(source_id, rel_type, target_id)]`` entry was
        left behind — orphaned metadata leaked AND
        ``get_edge_metadata`` returned stale data for an edge that no
        longer existed. Now passes ``owner_id`` + ``direction`` so the
        evictor can compute the canonical metadata key:

        - ``direction='outgoing'`` → list is ``self.edges[owner_id]``;
          popped tuple is ``(rel_type, target_id)``; metadata key is
          ``(owner_id, rel_type, target_id)``.
        - ``direction='incoming'`` → list is
          ``self.reverse_edges[owner_id]``; popped tuple is
          ``(rel_type, source_id)``; metadata key is
          ``(source_id, rel_type, owner_id)``.

        The new kwargs default to ``None`` so any previously caller that
        passed only the list (test fixtures, third-party code) still
        functions — metadata cleanup is skipped + the call falls back
        to the previously behavior.
        """
        evicted_edge: Optional[Tuple[str, str]] = None
        # First try to evict a non-authoritative edge (oldest first)
        for i, (rel_type, other_id) in enumerate(edge_list):
            if rel_type not in self.AUTHORITATIVE_RELATIONS:
                evicted_edge = edge_list.pop(i)
                break
        if evicted_edge is None:
            # All edges are authoritative — evict the oldest
            evicted_edge = edge_list.pop(0)

        # clean up the parallel _edge_metadata entry.
        if owner_id is not None and direction in ("outgoing", "incoming"):
            rel_type, other_id = evicted_edge
            if direction == "outgoing":
                metadata_key = (owner_id, rel_type, other_id)
            else:  # incoming
                metadata_key = (other_id, rel_type, owner_id)
            if metadata_key in self._edge_metadata:
                del self._edge_metadata[metadata_key]
                self._metadata_orphans_cleaned += 1

    def get_relationships(
        self,
        entity_id: str,
        relation_type: Optional[str] = None
    ) -> List[str]:
        """Get related entity IDs (outgoing edges).

        Storage emits SCREAMING_SNAKE_CASE relation types via
        ``_normalize_rel_type`` in the generic builder; callers should
        pass the same form. The ``DetGraphAdapter._coerce_str``
        normalizes ``RelationshipType`` enum members to ``.name``
        (uppercase) so dynamic_layer + DetGraphAdapter callers match
        without further mangling. previously the K8s
        ``RelationshipBuilder`` projected lowercase values into
        ``det_graph``; papered over that with case-insensitive
        comparison. Stage 2.3b dropped that projection; storage is
        consistent uppercase, so strict equality is correct again.
        """
        all_rels = self.edges.get(entity_id, [])
        if relation_type:
            return [target for rel, target in all_rels if rel == relation_type]
        return [target for rel, target in all_rels]

    def get_reverse_relationships(
        self,
        entity_id: str,
        relation_type: Optional[str] = None
    ) -> List[str]:
        """Get entities that relate TO this entity (incoming edges)."""
        all_rels = self.reverse_edges.get(entity_id, [])
        if relation_type:
            return [source for rel, source in all_rels if rel == relation_type]
        return [source for rel, source in all_rels]

    def get_relationship_types(self, entity_id: str) -> Set[str]:
        """Get all outgoing relationship types for an entity."""
        return {rel for rel, target in self.edges.get(entity_id, [])}

    def has_relationship(
        self,
        source_id: str,
        relation_type: str,
        target_id: str
    ) -> bool:
        """Check if a specific relationship exists."""
        return any(
            rel == relation_type and t == target_id
            for rel, t in self.edges.get(source_id, [])
        )

    def remove_entity(self, entity_id: str) -> None:
        """Remove all edges to/from an entity (for cache eviction cleanup).

         (sibling fix to ``_evict_lowest_priority_edge`` cleanup):
        also purges the parallel ``_edge_metadata`` dict for any key
        involving ``entity_id`` (either as source or as target). previously
        every ``remove_entity`` call orphaned metadata indefinitely AND
        poisoned ``get_edge_metadata`` lookups for removed edges.
        """
        # Remove forward edges from this entity
        if entity_id in self.edges:
            for rel_type, target_id in self.edges[entity_id]:
                if target_id in self.reverse_edges:
                    self.reverse_edges[target_id] = [
                        (r, s) for r, s in self.reverse_edges[target_id]
                        if s != entity_id
                    ]
            del self.edges[entity_id]
        # Remove reverse edges pointing to this entity
        if entity_id in self.reverse_edges:
            for rel_type, source_id in self.reverse_edges[entity_id]:
                if source_id in self.edges:
                    self.edges[source_id] = [
                        (r, t) for r, t in self.edges[source_id]
                        if t != entity_id
                    ]
            del self.reverse_edges[entity_id]

        # purge metadata entries involving this entity (either
        # as source or as target). Walk a snapshot of the keys to avoid
        # mutating the dict during iteration.
        orphan_keys = [
            key for key in self._edge_metadata
            if key[0] == entity_id or key[2] == entity_id
        ]
        for key in orphan_keys:
            del self._edge_metadata[key]
        self._metadata_orphans_cleaned += len(orphan_keys)

    def get_orphans(self, entity_ids: Set[str]) -> Set[str]:
        """Find entities with no relationships (orphans)."""
        orphans = set()
        for entity_id in entity_ids:
            outgoing = self.edges.get(entity_id, [])
            incoming = self.reverse_edges.get(entity_id, [])
            if not outgoing and not incoming:
                orphans.add(entity_id)
        return orphans


@dataclass
class Constraint:
    """
    A declarative constraint for the constraint engine.

    Constraints define invariants that should never be violated.
    """
    id: str
    name: str
    description: str = ""
    entity_type: str = "*"  # "*" matches all types
    condition: Dict[str, Any] = field(default_factory=dict)
    severity: Severity = Severity.HIGH
    axiom: Optional[Axiom] = None
    message: str = ""
    tags: List[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class IndicatorSpec:
    """
    Specification for a health indicator from ontology.

    Indicators define what properties to monitor and how.
    """
    uri: str
    name: str
    property_name: str = ""  # Maps to entity property key for data access; defaults to name
    indicator_type: IndicatorType = IndicatorType.NUMERIC
    relevant_axioms: List[Axiom] = field(default_factory=list)

    # Numeric indicator fields
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None
    time_window: Optional[timedelta] = None
    # (implements decision): HOMEOSTASIS direction gate.
    # Default ``BIDIRECTIONAL`` preserves previously behavior (fire on
    # |z| > threshold). ``LOWER`` fires only on z < -threshold
    # (negative-space / drop-below-baseline). ``UPPER`` fires only on
    # z > +threshold. See the internal notes.
    direction: str = "BIDIRECTIONAL"

    # State indicator fields
    normal_states: List[str] = field(default_factory=list)
    transient_states: List[str] = field(default_factory=list)
    problematic_states: List[str] = field(default_factory=list)
    transient_timeout: Optional[timedelta] = None

    # Relationship indicator fields
    target_type: Optional[str] = None
    relation_type: Optional[str] = None
    min_cardinality: int = 0
    max_cardinality: Optional[int] = None
    violation_severity: Severity = Severity.HIGH
    # when set, the relationship cardinality check only fires on entities
    # whose property dict carries a truthy value at this key. Lets a YAML rule
    # like "Service must select ≥1 Pod" skip selector-less Services (the default
    # `kubernetes` service uses manually-managed Endpoints, no label selector).
    required_property: Optional[str] = None

    # per-axiom configuration blocks for the two axioms whose
    # parameters do not fit the flat threshold fields above.
    #
    # Both checkers have always read these via
    # ``getattr(indicator, '<axiom>_config', None)`` — but the fields did not
    # exist on this dataclass and no loader produced them, so the lookup
    # always returned ``None``. The consequence was not a crash but something
    # quieter: a domain YAML declaring ``axioms: [CONSERVATION]`` fell through
    # to a degenerate name-matching path, and ``axioms: [MONOTONICITY]``
    # silently assumed ``increasing`` / ``allow_reset=True``. Eight declarable
    # axioms were six, and the two that did not work were the two whose
    # floors had just corrected.
    #
    # Populated from nested ``conservation:`` / ``monotonicity:`` blocks on
    # the indicator. Nested rather than flat because these carry a list
    # (``output_properties``) and five rate parameters whose names would
    # collide with the flat ``warning`` / ``critical`` thresholds.
    conservation_config: Optional[Dict[str, Any]] = None
    monotonicity_config: Optional[Dict[str, Any]] = None

    # what KIND of quantity this indicator measures — one of
    # latency / count / percentage / ratio. RESPONSIVENESS and CONSISTENCY used
    # to decide whether they applied by matching the indicator's NAME against
    # English words, so `pulldown_error_c` could declare RESPONSIVENESS, be
    # accepted by the loader, be reported by `model_describe`, and never once
    # produce an evaluation. That is property-name normalisation deciding
    # whether a check runs, inside checkers the project's own rule requires to
    # be domain-agnostic.
    #
    # Optional, and unset means the old name-matching still applies — removing
    # the inference outright would silently change coverage for every model
    # relying on it. See `ontology/axioms/roles.py`, which is the one place the
    # vocabulary and the axiom mapping live.
    role: Optional[str] = None

    # reported from outside as issue #3. A sensor frozen at one value
    # for its whole window produced an envelope byte-identical to a live one:
    # two attempted, nothing found, nothing declined. STABILITY tests
    # OSCILLATION, so a series that never moves scores zero and reads as
    # maximally stable, and BOUNDEDNESS compares the dead number against its
    # threshold and correctly passes. Nothing asked whether the number was
    # still a measurement.
    #
    # DECLARED, not inferred, and that is the whole design. Whether a constant
    # series is a fault is a DOMAIN question: a CPU temperature that never
    # moves is broken, and a desired-replica count, a nominal setpoint, a
    # config value or a switched-off pump are all correctly constant. A checker
    # that decided this for itself would be carrying domain behaviour, which is
    # the one thing the axiom layer must not do. Same move made when it
    # took CONSISTENCY and RESPONSIVENESS off guessing from the indicator name.
    #
    # `None` means undeclared, and undeclared means no check — so every model
    # written before this field behaves exactly as it did.
    expect_variation: Optional[bool] = None

    def __post_init__(self):
        if not self.property_name:
            self.property_name = self.name


@dataclass
class Observation:
    """A single observation of an entity property."""
    entity_id: str
    entity_type: str
    property_name: str
    property_type: str  # 'numeric', 'state', 'relationship'
    value: Any
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DetectionResult:
    """Result from a detection run."""
    problems: List[Problem] = field(default_factory=list)
    warnings: List[Problem] = field(default_factory=list)
    layer: DetectionLayer = DetectionLayer.CONSTRAINTS
    entities_checked: int = 0
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # What this run declined to evaluate, and why. Empty is a real
    # answer here — it means every declared axiom was actually evaluated — so
    # this field distinguishes a clean pass from a pass that measured nothing.
    not_evaluated: List[NotEvaluated] = field(default_factory=list)
    # How many (axiom, entity, indicator) evaluations this pass
    # attempted, declined ones included. Without it "checked N invariants"
    # cannot be stated — only findings and declines were countable, and their
    # sum is not the total, because an evaluation that ran and found nothing
    # appears in neither. An envelope that reports a fabricated denominator is
    # the failure the envelope exists to prevent.
    evaluations_attempted: int = 0

    def merge(self, other: 'DetectionResult') -> 'DetectionResult':
        """Merge another result into this one."""
        return DetectionResult(
            problems=self.problems + other.problems,
            warnings=self.warnings + other.warnings,
            layer=self.layer,
            entities_checked=self.entities_checked + other.entities_checked,
            duration_ms=self.duration_ms + other.duration_ms,
            timestamp=min(self.timestamp, other.timestamp),
            not_evaluated=self.not_evaluated + other.not_evaluated,
            evaluations_attempted=(
                self.evaluations_attempted + other.evaluations_attempted),
        )


@dataclass
class MultiDomainDetectionResult:
    """Result from multi-domain detection."""
    results_by_domain: Dict[str, DetectionResult] = field(default_factory=dict)
    cross_domain_problems: List[Problem] = field(default_factory=list)
    total_problems: int = 0
    total_duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# Abstract Interfaces
# =============================================================================

def absent_current_value(
    entity: "Entity",
    indicator: "IndicatorSpec",
    history: Optional["ObservationHistory"] = None,
) -> Tuple[NotEvaluatedReason, str, int]:
    """Which KIND of absence this is, for a checker that found no current value.

Returns ``(reason, detail clause, in-window observation count)``.
    Four checkers decline when ``Entity.properties`` lacks the indicator's
    property, and until now all four said `missing_property` whether the value
    had never been supplied or had been supplied to the observation history
    instead. Those are different answers and only one of them is actionable as
    written.

    ONE helper rather than four call sites doing the same lookup, because the
    wording is the product here -- a decline nobody can act on is a defect in
    the thing this engine claims to be good at, so four copies drifting apart
    is four different answers to the same question.

    It returns a TRIPLE and not a `CheckOutcome`. A helper that builds the
    outcome reads better and loses the records at any caller that passes it
    through anything list-shaped, which is the seam documents and
     then hit again in RESPONSIVENESS. Handing back the pieces leaves
    the `declined(...)` call visible at the site that owns it.

    Never raises. A history that cannot answer yields the old reason, so the
    worst case is the behaviour that shipped for a year.
    """
    prop = indicator.property_name
    count = total = 0
    if history is not None and prop:
        try:
            window = getattr(indicator, "time_window", None) or timedelta(hours=1)
            count = len(history.get_values(entity.id, prop, window))
            total = history.get_observation_count(entity.id, prop)
        except Exception:  # noqa: BLE001 - a decline must not become a crash
            count = total = 0

    if count or total:
        # BOTH counts when they differ. The in-window figure is the one that
        # governs, and on its own it invites the question the comment
        # on `observations_count` already answers for the sample floors: a
        # reader who supplied sixty and is told fifty-nine has been handed a
        # discrepancy with no explanation. Sixty samples at one-minute spacing
        # span exactly the one-hour window, so the oldest sits on the boundary.
        seen = (f"{count} of {total} observations" if total != count
                else f"{count} observation(s)")
        return (
            NotEvaluatedReason.NO_CURRENT_VALUE,
            f"{seen} of {prop} in window, but no current value; threshold "
            f"axioms read the entity's properties and temporal axioms read "
            f"observation history",
            count,
        )
    return (NotEvaluatedReason.MISSING_PROPERTY,
            f"no value for property {prop}", 0)


class CheckOutcome(List["Problem"]):
    """What a checker found, plus what it declined to evaluate.

This **is** a ``list`` of :class:`Problem`, so every existing
    caller — ``problems.extend(checker.check(...))``, ``if problems:``,
    ``len(...)``, ``== []`` — keeps working untouched. That was the
    requirement: eight checkers and the running detection pass consume this
    return value, and a breaking change to the contract is not worth the
    tidier type.

    The addition is :attr:`not_evaluated`, which answers the question the old
    contract could not: *was this empty because nothing is wrong, or because
    nothing was checked?*

    **Known limitation, stated rather than hidden.** Extending a plain list
    with a ``CheckOutcome`` keeps the problems and drops the
    ``not_evaluated`` records, because that is what ``list.extend`` does. This
    is not a regression — it is exactly the information the old contract never
    carried — but it does mean the channel is opt-in per call site. In
    practice the reasoner's ``check_axiom`` is the only dispatcher, so wiring
    it there captures everything that flows through a detection pass; direct
    ``.check()`` callers get the records only if they look.

    ``CheckOutcome()`` with no arguments is an empty, clean result — the same
    thing ``[]`` used to mean, and still equal to it.
    """

    # An internal ruling adds `evaluations_attempted`. Note `__slots__` here is real, not
    # decorative: it is effective on a list subclass (verified — no __dict__,
    # and an unlisted attribute raises), so a field must be declared here
    # before it can be set anywhere.
    __slots__ = ("not_evaluated", "evaluations_attempted")

    def __init__(
        self,
        problems: Optional[List["Problem"]] = None,
        not_evaluated: Optional[List[NotEvaluated]] = None,
        evaluations_attempted: int = 0,
    ) -> None:
        super().__init__(problems or [])
        self.not_evaluated: List[NotEvaluated] = list(not_evaluated or [])
        self.evaluations_attempted: int = evaluations_attempted

    def declined(
        self,
        axiom: Axiom,
        entity: "Entity",
        indicator_name: str,
        reason: NotEvaluatedReason,
        detail: str = "",
        observations_count: Optional[int] = None,
        required_count: Optional[int] = None,
        window_seconds: Optional[float] = None,
        total_observations: Optional[int] = None,
        sampling_interval_seconds: Optional[float] = None,
    ) -> "CheckOutcome":
        """Record a declined evaluation and return self, for use in a
        checker's early-return line: ``return CheckOutcome().declined(...)``.

        the last three make a sample-floor decline interpretable.
        Pass them via :func:`sampling_context` rather than by hand."""
        self.not_evaluated.append(NotEvaluated(
            axiom=axiom,
            entity_id=entity.id,
            entity_type=entity.type,
            indicator=indicator_name,
            reason=reason,
            detail=detail,
            observations_count=observations_count,
            required_count=required_count,
            window_seconds=window_seconds,
            total_observations=total_observations,
            sampling_interval_seconds=sampling_interval_seconds,
        ))
        return self


@runtime_checkable
class AxiomChecker(Protocol):
    """The contract every axiom checker satisfies.

All eight checkers already expose exactly this method with
    exactly this signature, but nothing declared it — the contract was
    structural duck-typing held together by a dispatch dict, and a checker
    that got the signature wrong would fail at dispatch time, deep inside a
    detection pass, rather than at import.

    Declared as a ``Protocol`` rather than an ABC deliberately. The eight
    existing checkers are plain classes that inherit nothing (three of them
    mix in a telemetry helper, five do not), and an ABC would force a base
    class onto all of them for no behavioural gain. A Protocol types the
    dispatch table and supports ``isinstance`` via ``runtime_checkable``
    without touching a single checker's declaration.

    This is the public extension point of the engine package. Someone adding
    a ninth axiom should be able to read one thing to learn what they must
    implement; before this, they had to infer it from eight examples.

    Note that ``runtime_checkable`` verifies method *presence*, not signature —
    a class with a ``check`` taking the wrong arguments still passes
    ``isinstance``. Static checkers catch that; the runtime check is a guard
    against the cruder mistake of registering something with no ``check`` at
    all.
    """

    def check(
        self,
        entity: "Entity",
        indicator: "IndicatorSpec",
        graph: "RelationshipGraph",
        history: "ObservationHistory",
    ) -> List["Problem"]:
        """Evaluate one indicator on one entity; return any problems found.

        The return is a plain ``List[Problem]`` as far as every caller is
        concerned. A checker that can evaluate the indicator returns the
        problems it found, and an empty result means "checked, nothing
        wrong".

        **reverses one half of the original contract.** It used to
        read: *there is no way to say "did not check" — a checker that cannot
        evaluate an indicator returns no problems.* That conflated two
        different answers into one empty list, and the floors are real
        (HOMEOSTASIS needs 30 observations, RESPONSIVENESS 20). A checker that
        declines should now return a :class:`CheckOutcome` carrying one
        :class:`NotEvaluated` record per declined evaluation:

            return CheckOutcome().declined(Axiom.HOMEOSTASIS, entity, indicator.name,
                NotEvaluatedReason.INSUFFICIENT_SAMPLES,
                observations_count=len(values),
                required_count=self.params.homeostasis_min_samples)

        Returning a bare ``[]`` remains legal and means "checked, nothing
        wrong" — so the eight checkers can adopt this incrementally, and a
        ninth written without it still satisfies the Protocol.

        **What has NOT changed**: coverage questions are still answered from
        domain declarations, not from checker output. A ``NotEvaluated``
        describes what one run skipped given the data and configuration in
        front of it; it is not evidence about what a domain declares, and
        must not be summed into a coverage claim.
        """
        ...


class ObservationHistory(ABC):
    """Abstract interface for observation history storage."""

    @abstractmethod
    def add(
        self,
        entity_id: str,
        property_name: str,
        value: Any,
        timestamp: datetime
    ) -> None:
        """Add an observation to history."""
        pass

    @abstractmethod
    def get_values(
        self,
        entity_id: str,
        property_name: str,
        window: timedelta
    ) -> List[Tuple[datetime, float]]:
        """Get numeric values within time window."""
        pass

    @abstractmethod
    def get_states(
        self,
        entity_id: str,
        property_name: str,
        window: timedelta
    ) -> List[Tuple[datetime, str]]:
        """Get state values within time window."""
        pass

    @abstractmethod
    def get_observations(
        self,
        entity_id: str,
        start: datetime,
        end: datetime
    ) -> List[Observation]:
        """Get all observations for entity in time range."""
        pass

    @abstractmethod
    def get_observation_count(
        self,
        entity_id: str,
        property_name: str
    ) -> int:
        """Get count of observations for a property."""
        pass


class DetectorInterface(ABC):
    """Base interface for all detection layers."""

    @abstractmethod
    def detect(
        self,
        entities: List[Entity],
        graph: RelationshipGraph,
        history: ObservationHistory
    ) -> DetectionResult:
        """
        Run detection on entities.

        Args:
            entities: List of entities to check
            graph: Relationship graph
            history: Observation history

        Returns:
            DetectionResult with problems found
        """
        pass

    @abstractmethod
    def get_layer(self) -> DetectionLayer:
        """Get the detection layer this detector belongs to."""
        pass


class ConstraintEngineInterface(DetectorInterface):
    """Interface for the constraint engine (Layer 1)."""

    @abstractmethod
    def load_constraints(self, path: str) -> None:
        """Load constraints from YAML file."""
        pass

    @abstractmethod
    def add_constraint(self, constraint: Constraint) -> None:
        """Add a constraint programmatically."""
        pass

    @abstractmethod
    def get_constraints(self, entity_type: Optional[str] = None) -> List[Constraint]:
        """Get all constraints, optionally filtered by entity type."""
        pass

    @abstractmethod
    def evaluate_constraint(
        self,
        constraint: Constraint,
        entity: Entity,
        graph: RelationshipGraph
    ) -> Optional[Problem]:
        """Evaluate a single constraint against an entity."""
        pass


class OntologyReasonerInterface(DetectorInterface):
    """Interface for the ontology reasoner (Layer 2)."""

    @abstractmethod
    def load_ontology(self, meta_path: str, domain_path: str) -> None:
        """Load meta-ontology and domain ontology."""
        pass

    @abstractmethod
    def get_indicators(self, entity_type: str) -> List[IndicatorSpec]:
        """Get health indicators for an entity type."""
        pass

    @abstractmethod
    def check_axiom(
        self,
        axiom: Axiom,
        entity: Entity,
        indicator: IndicatorSpec,
        graph: RelationshipGraph,
        history: ObservationHistory
    ) -> List[Problem]:
        """Check a specific axiom for an entity/indicator."""
        pass


class StatisticalDetectorInterface(DetectorInterface):
    """Interface for statistical anomaly detection (Layer 3)."""

    @abstractmethod
    def observe(self, entity: Entity, timestamp: Optional[datetime] = None) -> None:
        """Record observation for learning."""
        pass

    @abstractmethod
    def learn(self) -> None:
        """Fit distributions to observed data."""
        pass

    @abstractmethod
    def detect_anomalies(
        self,
        entities: List[Entity]
    ) -> List[Problem]:
        """Detect statistical anomalies in current state."""
        pass

    @abstractmethod
    def get_baseline(
        self,
        entity_type: str,
        property_name: str
    ) -> Optional[Dict[str, float]]:
        """Get learned baseline statistics."""
        pass


class LLMDetectorInterface(DetectorInterface):
    """Interface for LLM-based detection (Layer 4)."""

    @abstractmethod
    async def detect_async(
        self,
        entities: List[Entity],
        graph: RelationshipGraph,
        history: ObservationHistory
    ) -> DetectionResult:
        """Async detection using LLM."""
        pass

    @abstractmethod
    async def validate_problem(
        self,
        problem: Problem,
        entities: List[Entity]
    ) -> Tuple[bool, str]:
        """Validate a problem using LLM analysis."""
        pass

    @abstractmethod
    async def generate_suggestions(
        self,
        problems: List[Problem],
        entities: List[Entity]
    ) -> List[Dict[str, Any]]:
        """Generate improvement suggestions."""
        pass


class LayeredDetectorInterface(ABC):
    """Interface for the main layered detector orchestrator."""

    @abstractmethod
    async def detect_all(
        self,
        entities: List[Entity],
        graph: RelationshipGraph,
        history: ObservationHistory
    ) -> DetectionResult:
        """Run all detection layers."""
        pass

    @abstractmethod
    def get_layer_results(self) -> Dict[DetectionLayer, DetectionResult]:
        """Get results from each layer."""
        pass

    @abstractmethod
    def get_axiom_readiness(
        self,
        entity: Entity,
        history: ObservationHistory
    ) -> Dict[Axiom, AxiomReadiness]:
        """Get axiom readiness for an entity."""
        pass



# =============================================================================
# Utility Functions
# =============================================================================

def state_distance(state_a: Any, state_b: Any) -> float:
    """
    Calculate distance between two states.

    For categorical states: 0 if same, 1 if different
    For numeric states: normalized absolute difference
    For dict states: average distance of common keys
    """
    if state_a is None or state_b is None:
        return 1.0 if state_a != state_b else 0.0

    if isinstance(state_a, (int, float)) and isinstance(state_b, (int, float)):
        # Numeric: normalized difference
        max_val = max(abs(state_a), abs(state_b), 1)
        return abs(state_a - state_b) / max_val

    if isinstance(state_a, str) and isinstance(state_b, str):
        # Categorical: binary
        return 0.0 if state_a == state_b else 1.0

    if isinstance(state_a, dict) and isinstance(state_b, dict):
        # Dict: average of common key distances
        common_keys = set(state_a.keys()) & set(state_b.keys())
        if not common_keys:
            return 1.0
        distances = [state_distance(state_a[k], state_b[k]) for k in common_keys]
        return sum(distances) / len(distances)

    # Default: binary comparison
    return 0.0 if state_a == state_b else 1.0


def calculate_trend(
    values: List[Tuple[datetime, float]]
) -> Dict[str, float]:
    """
    Calculate linear trend with R² value.

    Returns:
        {'slope': float, 'r2': float, 'intercept': float}
    """
    if len(values) < 2:
        return {'slope': 0.0, 'r2': 0.0, 'intercept': 0.0}

    import numpy as np

    # Convert to numeric
    base_time = values[0][0]
    x = np.array([(v[0] - base_time).total_seconds() for v in values])
    y = np.array([v[1] for v in values])

    # Linear regression
    n = len(x)
    x_mean = np.mean(x)
    y_mean = np.mean(y)

    numerator = np.sum((x - x_mean) * (y - y_mean))
    denominator = np.sum((x - x_mean) ** 2)

    if denominator == 0:
        return {'slope': 0.0, 'r2': 0.0, 'intercept': y_mean}

    slope = numerator / denominator
    intercept = y_mean - slope * x_mean

    # R² calculation
    y_pred = slope * x + intercept
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y_mean) ** 2)

    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return {
        'slope': float(slope),
        'r2': float(r2),
        'intercept': float(intercept)
    }
