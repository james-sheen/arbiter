"""
CONNECTIVITY Axiom Checker.

CONNECTIVITY: System maintains relationships.

Detects:
- Missing required relationships
- Orphaned entities
- Relationship loss over time
- Broken reference chains

Works from cold start (no history required for basic checks).
"""

import logging
import re
from datetime import timedelta
from typing import List, Mapping, Optional, Set

from ...interfaces import (
    Entity,
    Problem,
    RelationshipGraph,
    ObservationHistory,
    IndicatorSpec,
    apply_property_confidence,
    CheckOutcome,
)
from ...types import (
    Axiom, Severity, AxiomParameters, DetectionLayer, NotEvaluatedReason,
)

logger = logging.getLogger(__name__)


class ConnectivityChecker:
    """
    Check CONNECTIVITY axiom for entities.

    CONNECTIVITY works from cold start - it only requires
    the current relationship graph.

    fires are counted at the reasoner's dispatch boundary, so
    this checker carries no instrumentation of its own.
    """

    def __init__(self, params: Optional[AxiomParameters] = None):
        self.params = params or AxiomParameters()

    # declared capability, read by the reasoner's dispatch boundary.
    # A flag rather than an isinstance check there: the seven other checkers
    # take four positional arguments and would break on a fifth, and a
    # capability the checker announces about itself extends to the next one
    # that needs entity state without touching the dispatch again.
    wants_entities = True

    def check(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        graph: RelationshipGraph,
        history: ObservationHistory,
        *,
        entities: Optional[Mapping[str, Entity]] = None,
    ) -> List[Problem]:
        """
        Check CONNECTIVITY for an entity/indicator.

        For relationship indicators: Check cardinality constraints
        """
        problems = []

        # Only check relationship indicators
        if indicator.indicator_type.value != 'relationship':
            # the commonest way a declared CONNECTIVITY produces
            # nothing: the indicator is numeric. Declaring the axiom on a
            # non-relationship indicator is a modelling mistake, and saying so
            # is more useful than an empty list.
            return CheckOutcome(problems).declined(
                Axiom.CONNECTIVITY, entity, indicator.name,
                NotEvaluatedReason.WRONG_INDICATOR_TYPE,
                detail=(
                    f"CONNECTIVITY evaluates relationship indicators; this one "
                    f"is {indicator.indicator_type.value}"),
            )

        # indicator may declare a property the entity must carry for the
        # cardinality check to apply. Selector-less Services (default `kubernetes`
        # service) legitimately have no SELECTS edges — skip those rather than
        # alarm.
        if indicator.required_property:
            value = entity.properties.get(indicator.required_property)
            if not value:
                return problems

        # Get relationships of the specified type
        # Normalize camelCase → SCREAMING_SNAKE_CASE to match graph storage
        # (domain YAML uses "scheduledOn" but graph stores "SCHEDULED_ON")
        raw_relation_type = indicator.relation_type or indicator.name
        relation_type = re.sub(r'(?<=[a-z])(?=[A-Z])', '_', raw_relation_type).upper()

        # Skip check if target entity type doesn't exist in graph.
        # E.g., don't flag pods for missing scheduledOn→Node when no
        # Node entities have been observed yet (cold start / limited scope).
        # resolve the target type against the ENTITY REGISTRY when
        # the caller supplies one. The scan below asked whether any id
        # appearing as an edge endpoint began with `<type>/`, which is a
        # different question and answers it wrongly in both directions. A
        # declared `Hub/h1` with no edge was declined as "no entity of type
        # 'Hub' has been observed", in a session holding exactly one. An edge
        # to `Hub/ghost`, with no Hub declared anywhere, passed clean.
        #
        # (Written as prose deliberately: an aligned two-column layout does not
        # survive into the published artifact, where runs of spaces inside a
        # comment are collapsed. Continuation lines then read as fragments.)
        #
        # The second is the dangerous one. A decline is reported and a reader
        # can see the coverage they did not get; a pass on a fabricated
        # topology is indistinguishable from a real one. Any inventory that
        # lags its edges — which is every discovery pipeline mid-sync — emits
        # exactly that shape.
        #
        # It also enforced an id convention (`<lowercased type>/<name>`) that
        # appears in no schema, no README and no example, while the shipped
        # `water_tank.yaml` satisfies it by accident. That is a hardcoded
        # domain pattern inside a domain-agnostic checker.
        typed_ids: Optional[set] = None
        if entities is not None and indicator.target_type:
            wanted = indicator.target_type.strip().lower()
            typed_ids = {
                eid for eid, ent in entities.items()
                if (getattr(ent, "type", "") or "").strip().lower() == wanted
            }

        if indicator.target_type:
            if typed_ids is not None:
                has_target_type = bool(typed_ids)
            else:
                # Degraded path: no registry supplied, so the type question is
                # genuinely unanswerable here and this approximates it. Kept
                # only for callers that construct the checker directly; the
                # reasoner always supplies the registry, and a test pins that
                # so production cannot quietly fall back to this.
                target_prefix = indicator.target_type.lower() + "/"
                has_target_type = any(
                    eid.lower().startswith(target_prefix)
                    for eid in graph.edges
                ) or any(
                    eid.lower().startswith(target_prefix)
                    for eid in graph.reverse_edges
                )
            if not has_target_type:
                # this was a bare `return problems`, and it is the
                # highest-value silence in the engine. The model declares that
                # this entity must relate to a `target_type`; not one entity of
                # that type has ever been observed. Cold start and "the concept
                # is missing from your telemetry entirely" are indistinguishable
                # from the outside, and staying quiet reports the second as the
                # first.
                #
                # Found by building the reference VPS disk demo: the model said every
                # Filesystem must have >= 1 DiskConsumer, no DiskConsumer was
                # ever observed, and the engine said nothing at all — about the
                # single fact that explains the outage. Whether this should
                # also raise a finding or a discovery question is; that
                # it must not be silent is not in question.
                return CheckOutcome(problems).declined(
                    Axiom.CONNECTIVITY, entity, indicator.name,
                    NotEvaluatedReason.MISSING_ENTITY_TYPE,
                    detail=(
                        f"no entity of type {indicator.target_type!r} has been "
                        f"observed, so the required {relation_type} "
                        f"relationship could not be evaluated"),
                )

        # Try normalized case first, then original case (graph may store either)
        related = graph.get_relationships(entity.id, relation_type)
        if not related:
            related = graph.get_relationships(entity.id, raw_relation_type)

        # count edges that RESOLVE. `len(related)` counted every
        # edge of the right relation type regardless of what sat on the far
        # end, so an edge to an id no entity ever claimed satisfied
        # `min_cardinality` and the invariant reported as held. Crediting a
        # dangling reference toward a cardinality floor is how a phantom
        # topology passes.
        dangling: List[str] = []
        if typed_ids is not None and entities is not None:
            resolved = [t for t in related if t in typed_ids]
            dangling = [t for t in related if t not in entities]
            actual_count = len(resolved)
        else:
            actual_count = len(related)

        # Check minimum cardinality
        if indicator.min_cardinality and actual_count < indicator.min_cardinality:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'missing_relationship:{indicator.name}',
                severity=indicator.violation_severity,
                reason=f"Missing required {relation_type} relationship",
                axiom=Axiom.CONNECTIVITY,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'relationship': relation_type,
                    'expected_min': indicator.min_cardinality,
                    'actual': actual_count,
                    'target_type': indicator.target_type,
                    # say why the count is what it is when edges
                    # exist but do not resolve. Without this the finding reads
                    # `actual: 0` beside a graph that plainly has an edge.
                    'edges_of_type': len(related),
                    'unresolved_targets': dangling,
                },
                confidence=1.0,
            ))

        # a dangling reference is a topology defect in its own
        # right, and reporting it is what stops it from being silently
        # credited. Raised even when cardinality is otherwise satisfied,
        # because "the edge exists and its target does not" is true either
        # way. MEDIUM matches `excess_relationships` below: a structural
        # complaint about the model, not an outage.
        if dangling:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'dangling_relationship:{indicator.name}',
                severity=Severity.MEDIUM,
                reason=(
                    f"{relation_type} points at "
                    f"{len(dangling)} entity id(s) that were never declared"),
                axiom=Axiom.CONNECTIVITY,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'relationship': relation_type,
                    'target_type': indicator.target_type,
                    'unresolved_targets': dangling,
                },
                confidence=1.0,
            ))

        # Check maximum cardinality (if specified)
        if indicator.max_cardinality and actual_count > indicator.max_cardinality:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'excess_relationships:{indicator.name}',
                severity=Severity.MEDIUM,
                reason=f"Too many {relation_type} relationships",
                axiom=Axiom.CONNECTIVITY,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'relationship': relation_type,
                    'expected_max': indicator.max_cardinality,
                    'actual': actual_count,
                },
                confidence=1.0,
            ))

        # fire counting moved to the dispatch boundary
        # (reasoner._record_fires), so all eight axioms are counted
        # uniformly rather than three by hand.
        result = apply_property_confidence(
            entity, indicator.property_name, problems)

        # both cardinality arms are truthiness-gated, and the
        # defaults are falsy — `min_cardinality` is 0 and `max_cardinality`
        # is None. An indicator declaring CONNECTIVITY without cardinality
        # config therefore evaluated nothing and returned clean. Worth noting
        # the 0 is doubly invisible: a deliberate `min_cardinality: 0` is
        # indistinguishable from an absent one.
        if not indicator.min_cardinality and not indicator.max_cardinality:
            return CheckOutcome(result).declined(
                Axiom.CONNECTIVITY, entity, indicator.name,
                NotEvaluatedReason.MISSING_CONFIG,
                detail=(
                    "neither min_cardinality nor max_cardinality is set, so "
                    "no cardinality invariant was evaluated"),
            )
        return result

    def check_orphans(
        self,
        entities: List[Entity],
        graph: RelationshipGraph,
        required_connections: Set[str] = None,
        min_entities_for_connectivity: int = 3,
    ) -> List[Problem]:
        """
        Find orphaned entities with no relationships.

        Args:
            entities: List of entities to check
            graph: Relationship graph
            required_connections: Entity types that should have connections
            min_entities_for_connectivity: Minimum entities of a type
                before flagging orphans. Prevents false alerts for new types
                whose relationship partners haven't arrived yet.
        """
        problems = []

        entity_ids = {e.id for e in entities}

        # Don't flag orphans when graph is still being populated
        total_edges = sum(len(rels) for rels in graph.edges.values()) if hasattr(graph, 'edges') else 0
        if total_edges < len(entity_ids) // 2:
            return []  # Graph not yet populated

        # Count entities per type to defer orphan checks for new types
        from collections import Counter
        type_counts = Counter(e.type for e in entities)

        orphans = graph.get_orphans(entity_ids)

        for entity in entities:
            if entity.id in orphans:
                # Skip if entity type doesn't require connections
                if required_connections and entity.type not in required_connections:
                    continue

                # Skip orphan check for entity types with too few entities.
                # New types may not have relationship partners yet.
                if type_counts.get(entity.type, 0) < min_entities_for_connectivity:
                    logger.debug(
                        f"Deferring orphan check for {entity.type} "
                        f"({type_counts[entity.type]}/{min_entities_for_connectivity} entities)"
                    )
                    continue

                problems.append(Problem.from_entity(
                    entity=entity,
                    problem_type='orphaned_entity',
                    severity=Severity.WARNING,
                    reason=f"Entity has no relationships",
                    axiom=Axiom.CONNECTIVITY,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'entity_type': entity.type,
                    },
                    confidence=0.8,
                ))

        return problems

    def check_relationship_loss(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        graph: RelationshipGraph,
        history: ObservationHistory,
        window: timedelta = None
    ) -> List[Problem]:
        """
        Check for relationship loss over time.

        This detects when relationships that existed are now missing.
        Requires relationship history tracking.
        """
        problems = []

        # This would require relationship history in ObservationHistory
        # For now, we rely on the basic cardinality checks
        # TODO: Implement relationship history tracking

        return problems

    def check_broken_references(
        self,
        entity: Entity,
        graph: RelationshipGraph,
        all_entity_ids: Set[str]
    ) -> List[Problem]:
        """
        Check for broken references (references to non-existent entities).
        """
        problems = []

        # Get all relationships from this entity
        all_rels = graph.edges.get(entity.id, [])

        for rel_type, target_id in all_rels:
            if target_id not in all_entity_ids:
                problems.append(Problem.from_entity(
                    entity=entity,
                    problem_type='broken_reference',
                    severity=Severity.HIGH,
                    reason=f"Reference to non-existent entity via {rel_type}",
                    axiom=Axiom.CONNECTIVITY,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'relationship': rel_type,
                        'target_id': target_id,
                    },
                    confidence=1.0,
                ))

        return problems
