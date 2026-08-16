"""The engine's public API: five primitives.

``model_describe`` / ``check`` / ``traverse`` / ``gaps`` / ``attest``.

These are engine-level, not transport-level. Every import below is inside the
 Option B cut, so this module ships with ``arbiter-engine`` and
depends on no protocol.

 moved it here from ``arbiter_mcp/tools.py``, where it was filed
because MCP is where it was first needed. The misfiling was visible from
outside: an engine demo had to import from a package named for a protocol it
does not use, and the leak pin fired on exactly that. Left alone,
The extraction would have had to either ship a transport's name inside
the engine package or rename during the cut itself — the riskiest moment
available.

``arbiter_mcp/server.py`` imports these and adds a transport. That is the
whole relationship, and it points one way only.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

from arbiter_engine.envelope import (
    CheckedSummary, Envelope, build_envelope, unavailable_envelope,
)
from arbiter_engine.history.observation import InMemoryObservationHistory
from arbiter_engine.interfaces import (
    Entity, RelationshipGraph,
)
from arbiter_engine.ontology.axioms.roles import (
    unreachable_axioms as _unreachable_axioms,
)
from arbiter_engine.ontology.domain_loader import load_domain
from arbiter_engine.ontology.reasoner import UnifiedAxiomReasoner

#: An internal ruling withheld `projected` until an internal ruling fed it. An internal ruling landed
#: 2026-08-04 (`TopologyTraverser.project_values`), so the mode is now
#: offered — and `traverse` below projects before traversing, because
#: offering the mode without running the producer would reinstate the
#: exact inertness that an internal ruling removed.
SUPPORTED_VALUE_MODES = ("current", "hypothetical", "projected")


class EngineSession:
    """Holds the loaded domain and observations between tool calls.

    An MCP server is long-lived and its tools are called independently, so
    ``check`` must be able to run against a model ``model_describe`` loaded
    earlier. Keeping that state here rather than in the transport is what lets
    the tools be tested as plain functions.
    """

    def __init__(self) -> None:
        self.model = None
        self.reasoner: Optional[UnifiedAxiomReasoner] = None
        self.history = InMemoryObservationHistory()
        self.entities: Dict[str, Entity] = {}
        self.graph = RelationshipGraph()
        self._last_result = None

    # -- loading -----------------------------------------------------

    def load_model(self, source: Any) -> None:
        self.model = load_domain(source)
        reasoner = UnifiedAxiomReasoner()
        # An internal ruling removed the seam this used to work around: the loader now
        # ingests IndicatorSpec objects directly, so the typed form the engine
        # loader emits no longer round-trips through a dict to satisfy a
        # parser the caller does not need.
        reasoner.loader.set_domain_indicators(self.model.indicators)
        self.reasoner = reasoner

    def add_entity(self, entity_id: str, entity_type: str,
                   properties: Optional[Dict[str, Any]] = None,
                   name: str = "") -> None:
        self.entities[entity_id] = Entity(
            id=entity_id, type=entity_type, name=name or entity_id,
            properties=dict(properties or {}),
        )

    def add_observations(self, entity_id: str, property_name: str,
                         values: Sequence[float],
                         interval_seconds: float = 60.0) -> None:
        now = datetime.utcnow()
        count = len(values)
        for i, value in enumerate(values):
            self.history.add(
                entity_id, property_name, float(value),
                now - timedelta(seconds=(count - i) * interval_seconds),
            )

    def add_relationship(self, source_id: str, relation_type: str,
                         target_id: str) -> None:
        """The third input kind. CONNECTIVITY reads this and nothing else.

        The session held a ``RelationshipGraph`` from the beginning and
        no method put anything in it, so of the three kinds of input the engine
        consumes, two had a feeder and one did not. The capability was never
        missing — ``session.graph`` is public and ``RelationshipGraph`` is on the
        supported surface — but a reader following the front door could satisfy
        seven of the eight axioms and not the eighth.

        The argument for keeping the session to three methods was that they are
        a deliberate minimum. That argument does not survive contact with the
        asymmetry: the minimum is one feeder per input kind, and this was two.

        Deliberately narrower than ``RelationshipGraph.add_relationship``, which
        also takes properties, strength, discovery time and cross-domain tags.
        Those belong to callers building a topology directly; the session's job
        is to make the common case reachable without reading the graph's
        signature. Reach for ``session.graph`` when you need the rest.
        """
        self.graph.add_relationship(source_id, relation_type, target_id)

    def unconsumed_observations(self) -> List[Dict[str, Any]]:
        """Series this session holds that no declared indicator will ever read.

        This rules the second half of issue #1. ``add_observations``
        accepts any property name — deliberately, and it keeps doing so: it is
        a released function that cannot raise, and an engine whose thesis is
        *report what you could not use* should not answer an unrecognised input
        by refusing it. What was wrong is that the data then vanished: nothing
        in ``check``, ``gaps`` or ``model_describe`` mentioned it, so a typo'd
        property name cost thirty observations and produced no signal anywhere.

        This is the MIRROR of ``unreachable_declarations``. That answers *this
        declaration can never fire*; this answers *this data is never read*.
        Shipping only the first half was the asymmetry the report exposed.

        **Deliberately does not guess the intended name.** A nearest-match
        suggestion would be a domain-specific heuristic wearing a helpful face,
        in an engine whose foundation rule forbids exactly that. It reports what
        was fed and how much; deciding what was meant is the reader's.
        """
        if self.model is None:
            return []
        declared: Dict[str, set] = {
            etype: {spec.property_name for spec in specs}
            for etype, specs in self.model.indicators.items()
        }
        records: List[Dict[str, Any]] = []
        for entity_id, prop in self.history.series_keys():
            entity = self.entities.get(entity_id)
            if entity is None:
                reason = "unknown_entity"
            elif prop in declared.get(entity.type, set()):
                continue                      # read by a declared indicator
            else:
                reason = "undeclared_property"
            records.append({
                "entity_id": entity_id,
                "entity_type": entity.type if entity else None,
                "property": prop,
                "observations": self.history.get_observation_count(entity_id, prop),
                "reason": reason,
            })
        return records


# =====================================================================
# The five tools
# =====================================================================


def model_describe(session: EngineSession) -> Envelope:
    """What domain is loaded: entity types, indicators, declared axioms.

    This is the grounding tool. An agent calls it before reasoning so it
    learns the vocabulary and cannot invent an entity type the model does not
    contain.

    **Reports declarations, not evaluations.** ``DomainModel.declared_axioms``
    carries an explicit warning that the declared set is not the evaluated set
    — several axioms have paths that consult no declaration. The
    payload says ``declared_axioms`` for that reason, and the summary does not
    claim to answer "what does this domain check?".
    """
    if session.model is None:
        return unavailable_envelope("no domain model loaded")

    model = session.model
    per_type: Dict[str, Any] = {}
    for entity_type, specs in model.indicators.items():
        per_type[entity_type] = [
            {
                "name": s.name,
                "declared_axioms": [
                    getattr(a, "value", str(a)) for a in s.relevant_axioms],
                # DECLARED and REACHABLE are different sets, and the
                # difference used to be discoverable only by running a cycle
                # and reading a decline. `role` is what moves a pair between
                # them for the two role-gated axioms.
                "role": getattr(s, "role", None),
                "unreachable_axioms": [
                    getattr(a, "value", str(a))
                    for a in _unreachable_axioms(s)],
            }
            for s in specs
        ]

    envelope = Envelope(
        checked=CheckedSummary(
            # `model_describe` evaluates nothing, so `invariants`
            # (evaluations attempted) is 0. What it can report is what the
            # model DECLARES, and that goes in its own field: reporting a
            # declaration count as `invariants` was the conflation
            # inside the honesty leg itself.
            invariants=0,
            declared_invariants=sum(len(s.relevant_axioms)
                                    for s in model.all_indicators()),
            entities=len(model.entity_types),
        ),
    )
    # The model description rides in questions=[] / findings=[]; the payload
    # is attached so the transport can serialise one shape for every tool.
    payload = envelope.to_dict()
    payload["model"] = {
        "domain_id": model.domain_id,
        "name": model.name,
        "entity_types": list(model.entity_types),
        "relationship_types": list(model.relationship_types),
        "indicators": per_type,
        "declared_axioms": [
            getattr(a, "value", str(a)) for a in model.declared_axioms()],
        # the statically-decidable half of the gap the note below
        # describes. Not every declared axiom that fails to fire is listed here
        # (some depend on inputs), but every pair listed here CANNOT fire, and
        # that was previously knowable only by running the engine.
        "unreachable_declarations": model.unreachable_declarations(),
        # the FIELD-side twin, reported from outside as issue #5
        # against the field added the previous day. `expect_variation: true`
        # without STABILITY in the same indicator's axiom list is accepted,
        # read by nothing, and was reported nowhere -- so a frozen sensor
        # produced an envelope byte-identical to a live one, which is the exact
        # defect that field exists to end. Five fields share the shape; the
        # report named the newest.
        "unread_fields": model.unread_fields(),
        "note": (
            "declared_axioms is what the model declares, not what the engine "
            "evaluates; some axioms have evaluation paths that consult no "
            "declaration. unreachable_declarations lists pairs that "
            "provably cannot evaluate under any input; unread_fields "
            "lists fields whose consuming axiom is absent, so nothing will read "
            "them; unconsumed_observations lists series no declared "
            "indicator reads"
        ),
    }
    # the mirror of `model.unreachable_declarations`, and deliberately
    # NOT inside it. That one is a property of the MODEL: these pairs can never
    # fire whatever you feed. This is a property of the SESSION: this data was
    # fed and nothing reads it. Nesting a session fact under `model` would be
    # the same category error the envelope's own legs exist to avoid.
    payload["unconsumed_observations"] = session.unconsumed_observations()
    return _WithPayload(envelope, payload)


def check(session: EngineSession) -> Envelope:
    """Evaluate the declared invariants over the supplied observations."""
    if session.reasoner is None:
        return unavailable_envelope("no domain model loaded")
    if not session.entities:
        return unavailable_envelope("no entities supplied")

    result = session.reasoner.detect(
        list(session.entities.values()), session.graph, session.history)
    session._last_result = result
    return build_envelope(result)


def traverse(session: EngineSession, start_nodes: Sequence[str],
             direction: str = "forward", value_mode: str = "current",
             max_hops: int = 4,
             overrides: Optional[Dict[str, Dict[str, Any]]] = None) -> Envelope:
    """The kernel: subsumes root cause, impact, what-if, conservation and
    connectivity as points in one parameter space.

    ``value_mode='projected'`` is refused rather than silently downgraded —
    An internal ruling records that PREDICT is plumbed but unfed, and a tool that accepts
    a mode it cannot honour is worse than one that declines it.
    """
    if value_mode not in SUPPORTED_VALUE_MODES:
        return unavailable_envelope(
            f"value_mode {value_mode!r} is not supported; this build accepts "
            f"{', '.join(SUPPORTED_VALUE_MODES)}."
        )
    topology = _build_topology(session)
    if topology is None:
        return unavailable_envelope(
            "no topology available: supply entities before traversing")

    from arbiter_engine.twin.topology import (
        TraversalDirection, TraversalRequest, ValueMode,
    )
    from arbiter_engine.twin.traverser import TopologyTraverser

    request = TraversalRequest(
        start_nodes=list(start_nodes),
        direction=TraversalDirection[direction.upper()],
        value_mode=ValueMode[value_mode.upper()],
        max_hops=max_hops,
        overrides=dict(overrides or {}),
    )
    traverser = TopologyTraverser(topology, observation_history=session.history)
    projected_count = 0
    if value_mode == "projected":
        # the producer must run or PROJECTED silently reads present
        # values — which is what made the mode inert for its whole existence.
        projected_count = traverser.project_values()
        if projected_count == 0:
            return unavailable_envelope(
                "value_mode 'projected' needs observation history to fit a "
                "trend; none of the supplied entities had enough. Add "
                "observations or use 'current'."
            )
        # the count above is TOPOLOGY-WIDE, and the risk is
        # per-node. Found by the round-trip: one entity with 40 observations
        # made `project_values()` return 1, so a traversal starting at an
        # entity with *no* history sailed past this guard and reported
        # `source: live` while reading present values. That is exactly the
        # failure mode the guard exists to prevent — narrowed to a
        # smaller window rather than closed. Ask whether the nodes being
        # traversed projected, not whether anything did.
        unprojected = [
            node_id for node_id in start_nodes
            if not getattr(
                topology.nodes.get(node_id), "projected_values", None)
        ]
        if len(unprojected) == len(list(start_nodes)):
            return unavailable_envelope(
                "value_mode 'projected' has no fitted trend for "
                f"{', '.join(unprojected)}: those entities lack the "
                "observation history to project from. Other entities in the "
                "topology do, which is why this is not an empty-history "
                "error. Add observations for them or use 'current'."
            )
    result = traverser.traverse(request)

    # An internal ruling set this to 0 on the premise that a traversal evaluates no
    # invariants. That was true when written and stopped being true at
    # an internal ruling, which carried the declared thresholds onto the nodes so
    # `_evaluate_axioms` can fire. Reporting 0 beside a non-empty `findings`
    # list would be the same defect that an internal ruling fixed, pointing the other way:
    # an envelope that understates what it did is no more honest than one
    # that overstates it.
    #
    # and the replacement for that premise was wrong too, in the
    # other direction. This counted `axiom_states` on each walked node, which
    # is what the BUILDER SEEDED: one state per declared axiom. The evaluator
    # handles BOUNDEDNESS only and skips any state whose property is absent
    # from the values, so a walk that evaluated one invariant reported four,
    # and a walk with `collect_axiom_violations` off — evaluating nothing —
    # reported four as well. Between them, the field has now been wrong as
    # traversal steps, and as declarations, in the one place whose entire job
    # is to be an honest denominator.
    #
    # The count now comes from the traverser, which is the only thing that
    # knows what it attempted. Deriving it here was a second implementation of
    # a predicate owned elsewhere, and it disagreed with the original.
    envelope = Envelope(
        checked=CheckedSummary(
            invariants=result.axiom_evaluations_attempted,
            steps=len(result.steps),
            entities=result.total_nodes_visited,
        ),
        findings=list(result.problems_detected),
        questions=[_q(q) for q in result.questions_generated],
    )
    return envelope


def gaps(session: EngineSession,
         start_node: Optional[str] = None) -> Envelope:
    """DISCOVER mode: what the model is missing, priority-ranked.

    This is the *what it needs to know next* leg of the envelope, surfaced as
    its own tool because an agent may want the questions without running a
    traversal for findings.
    """
    topology = _build_topology(session)
    if topology is None:
        return unavailable_envelope(
            "no topology available: supply entities before discovering gaps")

    from arbiter_engine.twin.traverser import TopologyTraverser
    traverser = TopologyTraverser(topology)

    starts = [start_node] if start_node else list(topology.nodes.keys())
    seen: Dict[Any, Any] = {}
    for node_id in starts:
        for question in traverser.discover_gaps(node_id):
            gap = getattr(question, "gap", None)
            key = (getattr(getattr(gap, "gap_type", None), "value", None),
                   getattr(gap, "location", None))
            seen.setdefault(key, question)

    # the topology's STRUCTURAL gaps, which are a separate
    # population from the traversal-time ones above and were reaching no
    # consumer at all.
    #
    # `traverse` only ever generates MISSING_NODE questions, and only for a
    # start node absent from the topology or an edge pointing at an unknown
    # entity. The builder separately computes orphans and missing properties
    # into `topology.gaps`, and **nothing anywhere read that list** — so
    # `discover_gaps` could not surface them however it was called. Fixing the
    # builder alone (so the engine path computes gaps at all) was necessary
    # and not sufficient; this is the second half.
    #
    # Deduplicated on the same `(gap_type, location)` key, so a structural gap
    # that a traversal also found keeps the traversal's richer context path.
    from arbiter_engine.twin.topology import TopologyQuestion
    for gap in getattr(topology, "gaps", ()):
        key = (getattr(getattr(gap, "gap_type", None), "value", None),
               getattr(gap, "location", None))
        if key in seen:
            continue
        seen[key] = TopologyQuestion(
            gap=gap,
            question_text=gap.question,
            priority=0.5,
            context_path=[],
            suggested_resolvers=[gap.suggested_strategy],
        )

    ordered = sorted(seen.values(),
                     key=lambda q: getattr(q, "priority", 0.0) or 0.0,
                     reverse=True)
    envelope = Envelope(
        checked=CheckedSummary(invariants=0, entities=len(starts)),
        questions=[_q(q) for q in ordered],
    )
    # `gaps` is where a caller looks for what is MISSING, and data
    # fed into a void is missing from the evaluation even though it is present
    # in the session. Carried as a payload key rather than folded into
    # `questions`, because a question is something the engine wants answered
    # and this is something the CALLER already did; and rather than into
    # `not_checked`, which is the per-axiom decline channel and would blur two
    # record kinds into one leg.
    payload = envelope.to_dict()
    payload["unconsumed_observations"] = session.unconsumed_observations()
    return _WithPayload(envelope, payload)


def attest(session: EngineSession, problem_type: str,
           entity_id: Optional[str] = None) -> Envelope:
    """The evidence trail behind a finding.

    **Thin by decision, not by omission**: it reports what the engine
    itself knows — the axiom, the threshold, the observations used, the floor
    applied. The richer production-record trail needs
    the full system, which an internal ruling placed in v0.2; the tool deepens
    there rather than changing shape.
    """
    result = session._last_result
    if result is None:
        return unavailable_envelope("nothing checked yet: call check first")

    matches = [
        p for p in list(result.problems) + list(result.warnings)
        if p.problem_type == problem_type
        and (entity_id is None or p.entity_id == entity_id)
    ]
    if not matches:
        return unavailable_envelope(
            f"no finding named {problem_type!r} in the last check")

    envelope = Envelope(
        # `attest` looks up an already-computed finding. It
        # evaluates nothing, and the number of matches is already visible in
        # `findings`; reporting it as `invariants` claimed an evaluation that
        # did not happen.
        checked=CheckedSummary(invariants=0, entities=1),
        findings=matches,
    )
    payload = envelope.to_dict()
    payload["evidence"] = [
        {
            "problem_type": p.problem_type,
            "entity_id": p.entity_id,
            "axiom": getattr(p.axiom, "value", None) if p.axiom else None,
            "evidence": dict(getattr(p, "evidence", {}) or {}),
            "confidence": getattr(p, "confidence", None),
            "boundary": (
                "engine-side evidence only; production attestation records "
                "are v0.2"
            ),
        }
        for p in matches
    ]
    return _WithPayload(envelope, payload)


# =====================================================================
# helpers
# =====================================================================


class _WithPayload(Envelope):
    """An envelope carrying a tool-specific payload alongside the four legs.

    Subclassed rather than adding an ``extra`` field to :class:`Envelope`,
    because the envelope's contract is the four legs plus meta and every tool
    must satisfy it identically. Tool-specific data is additive on the wire.
    """

    def __init__(self, base: Envelope, payload: Dict[str, Any]) -> None:
        super().__init__(
            checked=base.checked, findings=base.findings,
            not_checked=base.not_checked, questions=base.questions,
            source=base.source, reason=base.reason,
        )
        object.__setattr__(self, "_payload", payload)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._payload)


def _q(question: Any) -> Dict[str, Any]:
    from arbiter_engine.envelope import _question_to_dict
    return _question_to_dict(question)


def _build_topology(session: EngineSession):
    """Build a topology from the session's entities.

    ``build_from_relationship_graph`` takes a ``Dict[str, Entity]``, not a
    list — it iterates ``.items()`` and feeds the same mapping to
    ``_build_id_alias_map``. Passing a list raises rather than degrading, so
    this is caught on first call rather than silently producing an empty
    graph, which is the better failure of the two.
    """
    if not session.entities:
        return None
    from arbiter_engine.twin.builder import TopologyBuilder
    builder = TopologyBuilder()
    # pass the declared indicators so structural gap discovery runs.
    # Without this the topology carried no gaps at all and `gaps` returned an
    # empty questions leg for every model, which is indistinguishable from
    # "this model has no gaps" and is why the demo showed none.
    indicators = getattr(session.model, "indicators", None) if session.model else None
    return builder.build_from_relationship_graph(
        dict(session.entities), session.graph, indicators)
