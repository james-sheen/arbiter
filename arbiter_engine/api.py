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

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .clock import as_naive_utc, now_utc
from arbiter_engine.axiom_thresholds import (
    CD508_ENTITY_PROPERTY_KEY, OVERRIDE_CONSULTED_BY,
    OVERRIDE_DECLARED_BUT_UNREACHABLE,
)
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

#: `projected` was withheld while nothing produced projected values, and
#: has been offered since 2026-08-04, when `TopologyTraverser.project_values`
#: landed. `traverse` below projects BEFORE traversing, because offering
#: the mode without running the producer would reinstate exactly the
#: inertness that landing the producer removed.
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
                         values: Sequence[Any],
                         interval_seconds: float = 60.0) -> None:
        """Feed a series. Two shapes, because real telemetry has two.

        ``[1.0, 2.0, 3.0]`` — bare readings, spaced ``interval_seconds`` apart
        and ending now. This is the synthetic shape: it is what a test or a
        demo has, and it was the only shape this method accepted.

        ``[(when, 1.0), (when, 2.0)]`` —. Timestamped samples, which is
        what a real collector produces. Snapshots arrive at the interval the
        scrape happened to take, gaps exist, and back-filling a batch is
        normal. Reconstructing that as a uniform ladder ending at *now* moves
        every reading: a window that should have contained six samples contains
        whatever the fake spacing put in it, and the axioms that read a window
        answer about a series nobody supplied.

        ``when`` may be a ``datetime`` (naive or aware) or a POSIX timestamp.
        **Aware values are converted, not stripped.** That distinction is the
        subject of this engine's clock module and is worth restating at the one
        boundary a caller actually touches: dropping the zone keeps the local
        wall-clock reading and discards the fact that explains it, which
        measured three different verdicts for one instant depending on the
        reporter's timezone. Everything stored past this line is naive UTC.

        Mixed shapes in one call raise, rather than guessing. A list whose
        first element is a pair and whose fifth is a bare float is a caller
        bug, and silently reading the pair as a value would put a tuple into
        the history for an axiom to trip over three layers down.
        """
        samples = list(values)
        if not samples:
            return

        paired = [_is_timestamped(v) for v in samples]
        if any(paired) and not all(paired):
            raise ValueError(
                "add_observations got a mix of bare readings and "
                "(timestamp, value) pairs; supply one shape or the other — "
                "the interval used to space bare readings has no meaning "
                "beside a real timestamp"
            )

        if all(paired):
            for when, value in samples:
                self.history.add(
                    entity_id, property_name, float(value), _as_timestamp(when))
            return

        now = now_utc()
        count = len(samples)
        for i, value in enumerate(samples):
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

    def set_threshold_override(self, entity_id: str, indicator: str, axiom: str,
                               warning: Any = None,
                               critical: Any = None) -> None:
        """Calibrate one axiom for one entity, instead of for its whole type.

        This is a FEEDER rather than a new capability — the engine
        has resolved per-entity overrides for a long time, and the only way to
        set one was to know an undocumented sentinel property name and stamp a
        dict keyed by tuples into ``Entity.properties``. That is a reasonable
        interface for the simulator it was built for and not one a consumer can
        find. This is the fourth feeder, for the fourth kind of input, and the
        argument is the one that added the third: the session's job is to make
        the ordinary case reachable without reading the internals.

        **This does not override a declared threshold.** An indicator's
        ``warning:`` and ``critical:`` are read straight off the model and no
        override is consulted there. What this replaces is the axiom's
        calibration parameter — see ``OVERRIDE_CONSULTED_BY`` for which
        parameter each axiom actually reads. A caller who wants per-instance
        declared bounds is asking for something the engine does not have, and
        will be told so here rather than discovering it from a check that never
        fires.

        Deliberately does not raise on an unrecognised indicator or axiom. This
        engine's answer to input it cannot use is to report it, not to refuse
        it — the same ruling that keeps ``add_observations`` accepting any
        property name. ``unread_threshold_overrides`` is where it surfaces.
        """
        entity = self.entities.get(entity_id)
        if entity is None:
            raise KeyError(
                f"no entity {entity_id!r} in this session; add_entity first. "
                f"An override is stored ON the entity, so there is nowhere to "
                f"put this one."
            )
        # The checkers look up `indicator.property_name`, which differs from
        # the declared name exactly when the model carries a `property_mapping`.
        # Translating here means the caller uses the vocabulary their own model
        # uses; keying on the declared name and silently missing was the trap.
        key = self._override_key(entity.type, indicator)
        table = entity.properties.setdefault(CD508_ENTITY_PROPERTY_KEY, {})
        table[(key, str(axiom).upper())] = (warning, critical)

    def _override_key(self, entity_type: str, indicator: str) -> str:
        """The property name the checkers will look the override up under."""
        for spec in (self.model.indicators.get(entity_type, [])
                     if self.model is not None else []):
            if spec.name == indicator:
                return spec.property_name or spec.name
        return indicator

    def unread_threshold_overrides(self) -> List[Dict[str, Any]]:
        """Overrides this session holds that no check will ever consult.

        The mirror of ``unconsumed_observations``, for the input kind that had
        no report either. An override is stored on an entity and read, if at
        all, deep inside one axiom — so a wrong axiom name, an indicator the
        model does not declare, or an axiom whose lookup sits on an unreachable
        path all fail the same way: nothing happens, and nothing says so.

        Reports the reason rather than a verdict. ``axiom_never_consults`` and
        ``axiom_unreachable`` are properties of this build and would change if
        the engine changed; ``undeclared_indicator`` is a property of the
        caller's model. They are told apart because the remedies differ.
        """
        records: List[Dict[str, Any]] = []
        for entity_id, entity in self.entities.items():
            table = entity.properties.get(CD508_ENTITY_PROPERTY_KEY) or {}
            declared = {
                (s.property_name or s.name)
                for s in ((self.model.indicators.get(entity.type, []))
                          if self.model is not None else [])
            }
            for (key, axiom), bounds in table.items():
                if axiom in OVERRIDE_DECLARED_BUT_UNREACHABLE:
                    reason = "axiom_unreachable"
                elif axiom not in OVERRIDE_CONSULTED_BY:
                    reason = "axiom_never_consults"
                elif self.model is not None and key not in declared:
                    reason = "undeclared_indicator"
                else:
                    continue
                records.append({
                    "entity_id": entity_id,
                    "entity_type": entity.type,
                    "indicator": key,
                    "axiom": axiom,
                    "bounds": list(bounds),
                    "reason": reason,
                })
        return records

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
    # the third report of input that goes nowhere, beside the other
    # two and in both tools, because that is where the observations report
    # already lives and this is the same kind of fact. An override is stored on
    # an entity and consulted, if ever, deep inside one axiom, so every way of
    # getting it wrong fails identically: nothing happens and nothing says so.
    # A feeder without this would have shipped the exact asymmetry that the
    # observations report was added to close.
    payload["unread_threshold_overrides"] = session.unread_threshold_overrides()
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
    # the third report of input that goes nowhere, beside the other
    # two and in both tools, because that is where the observations report
    # already lives and this is the same kind of fact. An override is stored on
    # an entity and consulted, if ever, deep inside one axiom, so every way of
    # getting it wrong fails identically: nothing happens and nothing says so.
    # A feeder without this would have shipped the exact asymmetry that the
    # observations report was added to close.
    payload["unread_threshold_overrides"] = session.unread_threshold_overrides()
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


def _is_timestamped(sample: Any) -> bool:
    """Is this sample a ``(when, value)`` pair rather than a bare reading?

    Shape, not type: a two-element sequence whose first element is a datetime
    or a number that could be a POSIX timestamp. Deliberately does NOT accept
    any two-element sequence — a caller feeding `[[1, 2], [3, 4]]` means two
    readings of a vector, not two timestamped samples, and guessing otherwise
    would silently reinterpret their data.

    A string is excluded explicitly. It has a length and is indexable, so a
    two-character reading like `"ok"` would otherwise unpack as a pair.
    """
    if isinstance(sample, (str, bytes)) or isinstance(sample, datetime):
        return False
    if not isinstance(sample, (tuple, list)) or len(sample) != 2:
        return False
    first = sample[0]
    if isinstance(first, datetime):
        return True
    # A POSIX timestamp. Bounded rather than "any number", because an
    # unbounded rule reads a two-element vector of small readings as a
    # timestamped sample. 10^9 seconds is 2001; anything below it is not a
    # date anyone is feeding an engine written in 2026.
    return isinstance(first, (int, float)) and not isinstance(first, bool) \
        and first >= 1_000_000_000


def _as_timestamp(when: Any) -> datetime:
    """A caller's timestamp, as the engine's naive-UTC convention.

    Both branches end in `as_naive_utc`, and the POSIX one deliberately does not
    flatten the aware datetime it builds. Doing that here would be a second
    implementation of the convention, in a module that is not the clock — which
    is the exact shape `test_no_bare_tzinfo_strip_outside_the_clock` exists to
    refuse, and it caught this one.
    """
    if isinstance(when, datetime):
        return as_naive_utc(when)
    return as_naive_utc(datetime.fromtimestamp(float(when), tz=timezone.utc))


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
