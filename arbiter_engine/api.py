"""The engine's public API: five primitives.

``model_describe`` / ``check`` / ``traverse`` / ``gaps`` / ``attest``.

These are engine-level, not transport-level. Every import below is inside the
 Option B cut, so this module ships with ``arbiter-engine`` and
depends on no protocol.

An internal ruling moved it here from ``arbiter_mcp/tools.py``, where it was filed
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

from .clock import as_naive_utc, as_of, now_utc
from arbiter_engine.axiom_thresholds import (
    AXIOM_THRESHOLD_OVERRIDES_KEY, DECLARED_THRESHOLDS_KEY,
    OVERRIDE_CONSULTED_BY, OVERRIDE_DECLARED_BUT_UNREACHABLE,
    THRESHOLD_FIELDS,
)
from arbiter_engine.envelope import (
    CheckedSummary, Envelope, build_envelope, unavailable_envelope,
)
from arbiter_engine.history.calendar import (
    CalendarHistory, SessionCalendar)
from arbiter_engine.history.observation import InMemoryObservationHistory
from arbiter_engine.interfaces import (
    Entity, RelationshipGraph,
)
from arbiter_engine.ontology.axioms.roles import (
    unreachable_axioms as _unreachable_axioms,
)
from arbiter_engine.ontology.domain_loader import load_domain
from arbiter_engine.ontology.reasoner import UnifiedAxiomReasoner
from arbiter_engine.residual.predict_vs_mirror import PredictionLedger
from arbiter_engine.forecast import run_forecasts, run_shadow_check
from arbiter_engine.projection import run_projection
from arbiter_engine.causal.discovery import (
    DEFAULT_LAGS, run_discovery,
)
from arbiter_engine.ontology.entail import entail as entail_rules
from arbiter_engine.inference import Query, run_inference
from arbiter_engine.derived.indicator import (
    DerivedHistoryView, compute_current, operands_of,
)

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

    def __init__(self, history: Optional[Any] = None) -> None:
        self.model = None
        self.reasoner: Optional[UnifiedAxiomReasoner] = None
        # An injectable history, because the default one is a seven-day ring
        # and a replay needs a decade. The default is unchanged, so every
        # existing caller gets exactly what it got before.
        self.history = history if history is not None else InMemoryObservationHistory()
        self.entities: Dict[str, Entity] = {}
        self.graph = RelationshipGraph()
        self._last_result = None
        # THE LEDGER IS PER-SESSION, not the module singleton.
        #
        # `get_prediction_ledger()` returns one ledger for the whole process,
        # gated on an environment variable that is OFF by default. That shape
        # is right for a Core hook and wrong for this API: two sessions in one
        # MCP server would grade each other's predictions, and a consumer who
        # never set the variable would find that predictions recorded through
        # a session verb went nowhere -- silently, which is the failure the
        # ledger exists to remove.
        #
        # A session-owned ledger is unconditional and isolated. The module
        # singleton is untouched and still serves the gated Core callsite.
        self.ledger = PredictionLedger()
        #: What `discover` last PROPOSED. Filled by the verb and read by
        #: `adopt_io_relationships`; nothing consumes it until a caller says so.
        self.proposed_io_relationships: List[Any] = []
        #: What `entail` last DERIVED, whether or not it was adopted.
        self.derived_facts: List[Any] = []

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

    def reading_history(self):
        """The store every reader should ask, rather than `self.history`.

        `self.history` is what was FED. This is what the model says that feed
        MEANS: windows in open time when a calendar is declared, and a series
        for a derived indicator nobody fed directly. The two differ, so a
        reader that takes the raw store answers a different question from one
        that takes this -- about the same declaration.

        FOUR READERS TOOK THE RAW STORE while `check` took the view, and the
        split was invisible because each was correct in isolation. Measured on
        a three-day series at 10:30 inside a 09:30-16:00 session: a `lookback:
        4h` reached Thu 06:31 through the store (239 readings, most of them
        overnight) and Wed 13:01 through the view (1,289 readings, four hours
        of trading). On a derived indicator the gap is total -- the store holds
        nothing under that name, so `project` declined `insufficient_samples`
        with `evidence {"n": 0}` while the view could join 200 readings. That
        evidence was not a shortfall being reported; it was a false count.

        Built per call, not held: both wrappers are views over a model, and a
        session whose model is replaced would otherwise carry a view of the old
        one.

        ORDER MATTERS: the calendar wraps the STORE, and the derived view wraps
        whatever answers windows. A derived series is joined from operand
        series, and those operands must already be answering in open time or
        the join happens on two different clocks.
        """
        store = self.history
        if self.model is None:
            return store
        calendar = getattr(self.model, "calendar", None)
        if calendar:
            store = CalendarHistory(
                store, SessionCalendar.from_declaration(calendar))
        if not any(spec.derived
                   for specs in (self.model.indicators or {}).values()
                   for spec in specs):
            return store
        return DerivedHistoryView(store, self.model)

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

    def adopt_io_relationships(self, records: Optional[Sequence[Any]] = None) -> int:
        """Turn PROPOSALS into declarations, deliberately and by a caller.

        `discover` never does this itself. A lead-lag test measures predictive
        precedence, which two series driven by an undeclared third will also
        show, so promoting its output automatically would let the engine
        conclude structure from a correlation and then check against it.

        Adopting hands the records to RESPONSIVENESS, whose `check_io_pair` arm
        has had no producer. Returns how many were adopted.
        """
        chosen = list(records if records is not None
                      else self.proposed_io_relationships)
        if self.reasoner is not None:
            self.reasoner.set_io_relationships(chosen)
        return len(chosen)

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
        table = entity.properties.setdefault(AXIOM_THRESHOLD_OVERRIDES_KEY, {})
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
            table = entity.properties.get(AXIOM_THRESHOLD_OVERRIDES_KEY) or {}
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

    def set_declared_thresholds(self, entity_id: str, indicator: str,
                                **bounds: Any) -> None:
        """Give ONE entity its own `warning:` / `critical:` band.

        THE THING THE SIBLING ABOVE SAYS THE ENGINE DOES NOT HAVE.
        ``set_threshold_override`` replaces an axiom's calibration parameter
        and states in its own docstring that a caller wanting per-instance
        declared bounds *is asking for something the engine does not have*.
        Every account has its own margin line; without this, expressing that
        means one entity type per account, and a model with one type per
        instance has stopped being a model.

        A SECOND KEY RATHER THAN A SECOND MEANING FOR THE FIRST. The override
        table is keyed by axiom and holds calibration; this is keyed by field
        and holds bounds. One table carrying both would make the two
        indistinguishable at the point a reader most needs them apart -- and
        `unread_threshold_overrides` classifies by axiom, which has no answer
        for an entry that names no axiom.

        Accepts any of the four fields as keywords. Passing `None` REMOVES a
        bound previously set here rather than storing a null, so a caller can
        put an entity back on its model's own band without knowing whether one
        was ever set.

        Does not raise on an indicator the model does not declare -- the same
        ruling the sibling records. ``unread_declared_thresholds`` is where
        that surfaces.
        """
        entity = self.entities.get(entity_id)
        if entity is None:
            raise KeyError(
                f"no entity {entity_id!r} in this session; add_entity first. "
                f"A declared threshold is stored ON the entity, so there is "
                f"nowhere to put this one."
            )
        unknown = sorted(set(bounds) - set(THRESHOLD_FIELDS))
        if unknown:
            raise ValueError(
                f"{', '.join(unknown)} is not a bound this engine reads; the "
                f"four are {', '.join(THRESHOLD_FIELDS)}. Refused rather than "
                f"reported, because a keyword argument is a typo in the "
                f"caller's own source and they are standing in front of it -- "
                f"unlike a model file, which may have come from elsewhere."
            )
        # Same translation the override feeder does: the checkers look up
        # `property_name`, which differs from the declared name exactly when
        # the model carries a `property_mapping`.
        key = self._override_key(entity.type, indicator)
        table = entity.properties.setdefault(DECLARED_THRESHOLDS_KEY, {})
        for field, value in bounds.items():
            if value is None:
                table.pop((key, field), None)
            else:
                table[(key, field)] = float(value)

    def instance_thresholds(self) -> Dict[str, Any]:
        """How much of this session's judging is against per-instance bounds.

        A SUMMARY, not a row per bound, and the difference is not cosmetic: a
        listing here grows with the session, so on a book of ten thousand
        accounts it would be ten thousand rows of ordinary configuration
        dwarfing the findings beside it. The sibling report below stays a row
        list because it carries only what is WRONG, which is small by nature.

        What a reader needs from this key is whether the numbers in the
        envelope came from the model they can read or from somewhere else, and
        which mechanism put them there. The number a finding was compared
        against already travels in that finding's own evidence.
        """
        entities, fields, by_origin = set(), set(), {"instance": 0, "property": 0}
        for entity_id, entity in self.entities.items():
            for (_key, field) in (
                    entity.properties.get(DECLARED_THRESHOLDS_KEY) or {}):
                entities.add(entity_id)
                fields.add(field)
                by_origin["instance"] += 1
            for spec in (self.model.indicators.get(entity.type, [])
                         if self.model is not None else []):
                for field, source in (spec.threshold_sources or {}).items():
                    if entity.properties.get(source) is None:
                        continue      # declared, not arrived; the decline says so
                    entities.add(entity_id)
                    fields.add(field)
                    by_origin["property"] += 1
        return {"entities": len(entities), "fields": sorted(fields),
                "by_origin": by_origin}

    def unread_declared_thresholds(self) -> List[Dict[str, Any]]:
        """Per-instance bounds no check will consult. The mirror of the
        override report above, for the key beside it.

        Two ways to be unread and they need different fixes.
        ``undeclared_indicator`` is the caller naming something the model does
        not carry; ``axiom_not_declared`` is the indicator existing without the
        axiom that reads bounds, so the number is stored against a check that
        never runs.
        """
        records: List[Dict[str, Any]] = []
        reads_bounds = {"BOUNDEDNESS", "RESPONSIVENESS"}
        for entity_id, entity in sorted(self.entities.items()):
            table = entity.properties.get(DECLARED_THRESHOLDS_KEY) or {}
            specs = ((self.model.indicators.get(entity.type, []))
                     if self.model is not None else [])
            by_key = {(s.property_name or s.name): s for s in specs}
            for (key, field) in sorted(table):
                spec = by_key.get(key)
                if self.model is not None and spec is None:
                    reason = "undeclared_indicator"
                elif spec is not None and not (
                        {a.value for a in (spec.relevant_axioms or ())}
                        & reads_bounds):
                    reason = "axiom_not_declared"
                else:
                    continue
                records.append({
                    "entity_id": entity_id,
                    "entity_type": entity.type,
                    "indicator": key,
                    "field": field,
                    "value": table[(key, field)],
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
        # THE SAME SET `unread_properties` USES. Counting only indicator names
        # here reported a `{from_property:}` bound's source, and the operands
        # of a derived indicator, as `undeclared_property` -- while the sibling
        # report on the other input surface counted them as read. One
        # declaration, two verdicts, and the only way to silence the wrong one
        # was to declare the property a second time.
        declared: Dict[str, set] = self.readable_properties()
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

    def readable_properties(self) -> Dict[str, set]:
        """Per entity type, every property name the MODEL reads.

        THREE READERS HAD THREE ANSWERS to one question. `unread_properties`
        counted an indicator's own name, a derived indicator's operands and a
        `{from_property:}` bound's source; `unconsumed_observations` counted
        only the first, so feeding a bound's source was reported
        `undeclared_property` by one report and read by another; and
        `sync_current_from_history` iterated indicator specs, so a replay never
        advanced the source of a per-instance bound at all.

        THE REPLAY CASE IS THE ONE THAT BITES. A model whose floor is
        `lower_critical: {from_property: margin_requirement}` has its floor
        advanced by nothing: the balance moves with the clock, the requirement
        stays at whatever was fed at construction, and every step after the
        first checks today's balance against the first step's floor. Nothing
        declines, because from the axiom's point of view the bound resolved.

        Derived operands are read by the join, threshold sources by the
        resolver, and both are declarations -- which is why an author had to
        declare the source a second time as an `axioms: []` indicator to stop
        the reports contradicting each other. The shipped example still carries
        one of those.
        """
        if self.model is None:
            return {}
        return {
            etype: ({spec.property_name or spec.name for spec in specs}
                    | {name for spec in specs if spec.derived
                       for name in operands_of(spec.derived)}
                    | {str(source) for spec in specs
                       for source in (getattr(spec, "threshold_sources", None)
                                      or {}).values() if source})
            for etype, specs in self.model.indicators.items()
        }

    def dropped_declarations(self) -> List[Dict[str, Any]]:
        """Declarations the loader did not recognise, so it did not apply them.

        REPORTED FROM OUTSIDE against 0.1.10. `axioms: [BOUNDEDNES]` on an
        indicator carrying a `critical:` and an entity reading past it produced
        an envelope byte-identical to declaring no axioms at all: no finding, no
        decline, `invariants: 0`. The check the author wrote never happened and
        four of the five tools could not say so. Only `model_describe` could,
        and an agent that calls `check` does not call it.

        A PAYLOAD, NOT A DECLINE, AND THE SCHEMA CHOSE THAT -- the same reason
        the report above rides this way. `not_checked[].axiom` is a closed enum
        of the eight axiom names, so a cell declined for `BOUNDEDNES` cannot be
        expressed without moving the wire contract. The finding proposed
        declining the cell; the schema does not allow it, and a payload puts the
        fact where the author reads it without changing what every tool
        satisfies.

        NARROWER THAN `unread_fields`, deliberately. That list also carries
        fields whose consuming axiom was never declared, which answers a
        question `check` was not asked -- the sibling report above refused a
        fifth key for exactly that reason. This is only the values the engine
        REJECTED: read, not understood, and dropped.
        """
        if self.model is None:
            return []
        return [dict(entry) for entry in self.model.unread_fields()
                if entry.get("reason") == "unknown_value"]

    def unread_properties(self) -> List[Dict[str, Any]]:
        """Entity properties this session holds that no declared indicator reads.

        The FOURTH report of a family rather than a new idea.
        ``unconsumed_observations`` above covers the history store and
        ``unread_threshold_overrides`` covers overrides; the engine takes three
        input surfaces and this was the one with no report. Feeding it was
        silent.

        **Filed because removing something made the gap visible.** took
        out a walk that judged every entity property by the words in its name.
        That was right -- it derived an interpretation fact from a spelling and
        its findings sat outside the denominator -- but it had been doing real
        work, and the replacement is a declaration. An author cannot declare
        what they do not know they are sending, so the honest half of that
        removal is a report saying what arrived and went unread.

        **A REPORT, NOT A FINDING, and the line matters.** It names a gap in the
        model, which is the author's to close. It does not say the value is
        wrong, because deciding that would need a rule, and picking the rule
        from the property's name is exactly what was removed.

        **Numeric values only, and that is a stated limit rather than a
        judgement about domains.** A number is something an axiom could have
        evaluated and did not. Strings are excluded because telling a state a
        STATE indicator should read from a label that is merely metadata is a
        domain question, and this engine does not answer those -- so a mistyped
        STATE property is NOT reported here, which is a real gap and is written
        down rather than papered over. Booleans are excluded explicitly: ``bool``
        subclasses ``int``, so a flag would otherwise arrive as a number nobody
        reads.

        Top-level keys only. A nested value has no declaration surface of its
        own, so naming ``status.replicas`` would report something the author
        cannot declare against.
        """
        if self.model is None:
            return []
        # AN OPERAND OF A DERIVED INDICATOR IS READ, and by something the
        # author declared. Without this, feeding `spot` and `futures` to a
        # model whose only use of them is `derived: futures - spot` reports
        # both as read by nobody -- which is the opposite of true, and would
        # send an author to delete the feed the indicator depends on.
        # A BOUND'S SOURCE IS READ TOO, by the same argument one line up. A
        # `{from_property: margin_requirement}` declaration says the engine
        # goes and reads that property at check time, and it does. Without it
        # here, an author feeding the requirement was told nobody reads it --
        # and the only way to silence that was to declare the source as its own
        # `axioms: []` indicator, which both the shipped example and the
        # margin-book bridge were doing. Declaring a thing twice to stop being
        # told it was never declared is a report training authors around
        # itself.
        declared: Dict[str, set] = self.readable_properties()
        records: List[Dict[str, Any]] = []
        for entity in self.entities.values():
            readable = declared.get(entity.type, set())
            for prop, value in (entity.properties or {}).items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                if prop in readable:
                    continue
                records.append({
                    "entity_id": entity.id,
                    "entity_type": entity.type,
                    "property": prop,
                    "reason": "undeclared_property",
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
                # The declared state vocabulary, for STATE indicators that
                # carry one. `bad:` now decides a finding; `normal:` decides
                # nothing and is reported here, because a key a model may
                # declare and no surface will show back is how `bad:` came to
                # sit unread for as long as it did. Absent entirely on
                # indicators that declare neither, rather than reported empty:
                # an empty list here would read as a vocabulary that was
                # declared and came out empty.
                **({"states": {k: v for k, v in (
                        ("normal", list(getattr(s, "normal_states", None) or ())),
                        ("problematic", list(getattr(s, "problematic_states", None) or ())),
                        ("transient", list(getattr(s, "transient_states", None) or ())),
                    ) if v}}
                   if (getattr(s, "normal_states", None)
                       or getattr(s, "problematic_states", None)
                       or getattr(s, "transient_states", None)) else {}),
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
        # the list, mounted where a MODEL fact belongs. `check` has
        # carried it since it was added; this verb, whose whole question is
        # *did my model load the way I wrote it*, did not -- so a reader
        # proofreading a generated model through the describe payload got a
        # clean answer from a key that was never there. Measured on the
        # margin-book bridge: its read-back looked for exactly this, found
        # nothing, and reported no dropped declarations for a model with a
        # misspelled axiom AND for one with an unreadable `{from_property:}`
        # mapping -- the case the changelog names.
        #
        # Through the session's own accessor, not re-derived here. The
        # predicate that says which entries count as dropped exists once; a
        # second copy of it is the shape this package has been bitten by
        # before, and it goes stale the first time the predicate moves.
        "dropped_declarations": session.dropped_declarations(),
        "note": (
            "declared_axioms is what the model declares, not what the engine "
            "evaluates; some axioms have evaluation paths that consult no "
            "declaration. unreachable_declarations lists pairs that "
            "provably cannot evaluate under any input; unread_fields "
            "lists fields whose consuming axiom is absent, so nothing will read "
            "them; dropped_declarations is the subset of those the "
            "loader REJECTED, read and not understood; "
            "unconsumed_observations lists series no declared "
            "indicator reads; unread_properties lists numeric entity "
            "properties no declared indicator reads"
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
    # the fourth report of input that goes nowhere, in both tools for
    # the reason the third one gives. An internal ruling removed a walk that judged every
    # entity property by its name; the rules it applied are declarable and now
    # declared, but an author cannot declare a property they do not know they
    # are sending. This says what arrived and was never read.
    payload["unread_properties"] = session.unread_properties()
    # B-2.7 — a bound read off an entity is invisible in the envelope, which
    # reports the number and not where it came from. Both halves ride here: what
    # is set, and what is set and will never be read.
    payload["instance_thresholds"] = session.instance_thresholds()
    payload["unread_declared_thresholds"] = session.unread_declared_thresholds()
    return _WithPayload(envelope, payload)


def _history_for(session: EngineSession):
    """The session's reading history. See `EngineSession.reading_history`.

    Kept as a module function because callers and tests import it by this
    name; the logic lives on the session so that `projection`, `causal` and
    `forecast` can reach it without importing this module.
    """
    return session.reading_history()


def _derive_current_values(session: EngineSession) -> List[Dict[str, Any]]:
    """Compute every declared derived indicator onto its entity.

    Returns the ones that could NOT be computed, naming the operands that were
    missing. A value already present under the derived name is overwritten:
    the declaration says the property IS the expression, and a fed value under
    that name is a second source for one fact.
    """
    unresolved: List[Dict[str, Any]] = []
    if session.model is None:
        return unresolved
    for entity in session.entities.values():
        for spec in session.model.indicators.get(entity.type, []) or []:
            if not spec.derived:
                continue
            name = spec.property_name or spec.name
            value, missing = compute_current(spec, entity.properties)
            if value is None:
                entity.properties.pop(name, None)
                unresolved.append({
                    "entity_id": entity.id, "entity_type": entity.type,
                    "indicator": spec.name, "property": name,
                    "derived": spec.derived,
                    "missing_operands": missing,
                    "remedy": (f"feed {missing} on {entity.id}, or correct "
                               f"`derived:` on {spec.name}") if missing else
                              (f"`derived: {spec.derived}` did not evaluate"),
                })
                continue
            entity.properties[name] = value
    return unresolved


def check(session: EngineSession) -> Envelope:
    """Evaluate the declared invariants over the supplied observations."""
    if session.reasoner is None:
        return unavailable_envelope("no domain model loaded")
    if not session.entities:
        return unavailable_envelope("no entities supplied")

    # DERIVED INDICATORS ARE COMPUTED BEFORE ANYTHING JUDGES THEM, into the
    # same `Entity.properties` the threshold axioms already read -- so no
    # checker learns that a value was computed, which is what keeps a parity
    # or spread relation from needing an axiom of its own.
    underived = _derive_current_values(session)
    result = session.reasoner.detect(
        list(session.entities.values()), session.graph,
        _history_for(session))
    session._last_result = result
    # RULE: every prediction gets graded. `check` is the cycle boundary, so it
    # is where maturity is noticed -- a prediction whose horizon passed between
    # two calls is graded on the next one rather than whenever someone
    # remembers to ask.
    #
    # This reports NOTHING in the envelope, deliberately. The payload set below
    # is closed by its own argument -- those two keys answer *did what I
    # declared actually take effect*, which is the question `check` IS -- and a
    # calibration summary is not that question. Grading is a state transition
    # on the ledger; the caller reads it at `session.ledger.calibration()`,
    # where the denominators live.
    #
    # Inert until something records a prediction: a fresh session's ledger is
    # empty and this is a no-op over an empty deque.
    session.ledger.grade_matured(
        list(result.problems) + list(result.warnings),
        set(session.entities),
        # THE SAME HISTORY THE AXIOMS JUST READ, which is the view and not the
        # bare store. Grading against the store alone meant a forecast OF a
        # derived indicator had nothing to score against -- the derived series
        # exists only through the view -- so every such record matured straight
        # to `ungradeable` and the producer looked unscoreable rather than
        # unscored.
        histories=[_history_for(session)],
    )
    envelope = build_envelope(result)
    # the one report this verb owes, and the only one carried here.
    # An internal ruling withdrew a check: a numeric property no indicator declares used to
    # be judged by the words in its name. COMPATIBILITY.md permits withdrawing a
    # check in a patch and forbids doing it QUIETLY, because a check withdrawn
    # without a word is indistinguishable from one that passed -- measured
    # against the previous release on the same model, three findings vanished,
    # one of them critical, with `not_checked` empty and the denominator
    # unmoved. The other two verbs already carried this population; `check` is
    # the surface the rule is about, and was the one of the three missing it.
    #
    # A payload rather than a `not_checked` decline, and the schema chose that:
    # a decline record REQUIRES an indicator and an axiom, and an undeclared
    # property has neither -- supplying them would mean naming the axiom from
    # the property's name, which is the move that was removed. Payloads ride
    # alongside the legs by design, which is where the other three reports of
    # input that goes nowhere already sit.
    #
    # Only this one. The observations and override reports answer a question
    # `check` was not asked; adding them here would be a wider change than the
    # rule requires and a fifth key nobody reported missing.
    #
    # An internal ruling adds the second, on the same argument and reported the same way:
    # a name the loader did not recognise drops the declaration, and a dropped
    # declaration is a check that does not run. It is not the observations or
    # override report -- those answer a question `check` was not asked. This
    # one answers *did what I declared actually take effect*, which is the
    # question `check` IS.
    payload = envelope.to_dict()
    payload["unread_properties"] = session.unread_properties()
    payload["dropped_declarations"] = session.dropped_declarations()
    # the argument, a third time, and the same one: this answers *did
    # what I declared actually take effect*, which is the question `check` IS.
    #
    # A derived indicator whose operand is missing declines on a property
    # NOBODY FEEDS. The reason is right and the name is a dead end: an author
    # told `missing_property: basis` goes looking for a `basis` feed that was
    # never supposed to exist, when what is missing is `spot`. This names the
    # operand. Empty when nothing is derived, which is every model that
    # predates the key.
    payload["underived"] = underived
    # Path B -- the forecasts leg, every cycle. Its findings stay INSIDE it:
    # the envelope's own `findings` are about the present, and a forecast
    # breach merged into them would put *your prediction is impossible* beside
    # *your system is breaking* in one list, which is the confusion the
    # `forecast_` prefix exists to prevent -- reintroduced one level up where
    # the prefix cannot be seen.
    #
    # Costs nothing when nobody forecasts: with an empty ledger the shadow run
    # returns before it builds an entity.
    #
    # TWO KEYS, BECAUSE THEY ARE TWO DISCIPLINES with two closed vocabularies.
    # `run_forecasts` composes the shadow run for its findings and used to
    # discard everything else it returned -- so through this verb a consumer
    # never saw a shadow decline at all, and the leg read as *nothing to
    # report* on a forecast the engine had refused to judge. Measured on a
    # model with no `dynamics.report_above`: `not_checked` empty here, while
    # the shadow run had declined `no_report_probability` and `no_threshold`.
    #
    # Merging them into one leg was the other option and is refused for the
    # reason `subenvelope.py` gives: a vocabulary that accepts another
    # discipline's reasons has stopped being evidence about either. Run once,
    # mounted twice, so the two cannot disagree about one cycle.
    shadow = run_shadow_check(session)
    payload["forecasts"] = run_forecasts(session, shadow=shadow).to_dict()
    payload["shadow"] = shadow.to_dict()
    return _WithPayload(envelope, payload)


def _fold(word: Any, vocabulary: Sequence[str]) -> Optional[str]:
    """Match `word` against a closed vocabulary ignoring case, returning the
    CANONICAL spelling or None.

    Returning the canonical form rather than a bool is the point: the
    caller goes on to look the value up in an enum, and handing back what the
    author typed would just move the case problem one line down.
    """
    if not isinstance(word, str):
        return None
    lowered = word.casefold()
    for candidate in vocabulary:
        if candidate.casefold() == lowered:
            return candidate
    return None


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
    # Imported here rather than at module scope for the cycle, and hoisted
    # above the topology build so both ARGUMENT checks happen before any state
    # check -- an author who mistyped a direction should be told that, not told
    # they supplied no entities.
    from arbiter_engine.twin.topology import (
        TraversalDirection, TraversalRequest, ValueMode,
    )
    from arbiter_engine.twin.traverser import TopologyTraverser

    # this function takes TWO closed vocabularies and treated them
    # differently in three ways, none of them intended.
    #
    # `direction` reached `TraversalDirection[direction.upper()]` unguarded, so
    # an unrecognised word escaped as `KeyError: 'BACKWARD'` -- an uncaught
    # exception out of a library whose product is saying what it could not do,
    # naming an UPPER-CASED token the caller never typed. `value_mode` declined
    # cleanly. That asymmetry is the defect.
    #
    # The second one is the trap: the `.upper()` meant `direction` accepted ANY
    # case, and `value_mode` accepted only lower. A guard written to match
    # `value_mode` therefore REFUSED `FORWARD`, which the published release
    # accepts -- narrowing what a caller may send, which is not something a
    # patch may do. Both now FOLD case, which widens one and keeps the other,
    # and matches the rule the loader's vocabularies already follow: fold on
    # the way in, and answer in the canonical spelling.
    #
    # `direction`'s valid set is DERIVED from the enum. `SUPPORTED_VALUE_MODES`
    # stays a literal for a reason of its own -- it names what this BUILD
    # accepts, which may be narrower than the type -- and no such reason applies
    # here, so a second copy would only be somewhere to drift.
    directions = [member.value for member in TraversalDirection]
    resolved_direction = _fold(direction, directions)
    if resolved_direction is None:
        return unavailable_envelope(
            f"direction {direction!r} is not supported; this build accepts "
            f"{', '.join(directions)}."
        )
    direction = resolved_direction

    resolved_mode = _fold(value_mode, SUPPORTED_VALUE_MODES)
    if resolved_mode is None:
        return unavailable_envelope(
            f"value_mode {value_mode!r} is not supported; this build accepts "
            f"{', '.join(SUPPORTED_VALUE_MODES)}."
        )
    value_mode = resolved_mode

    topology = _build_topology(session)
    if topology is None:
        return unavailable_envelope(
            "no topology available: supply entities before traversing")

    request = TraversalRequest(
        start_nodes=list(start_nodes),
        direction=TraversalDirection[direction.upper()],
        value_mode=ValueMode[value_mode.upper()],
        max_hops=max_hops,
        overrides=dict(overrides or {}),
    )
    traverser = TopologyTraverser(
        topology, observation_history=_history_for(session))
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
            # Ask E. This was a flat 0.5, and `gaps` documents itself as
            # priority-ranked -- so the two populations it merges were on
            # different scales and the ranking was not one. Measured on one
            # topology: seven structural gaps all at exactly 0.5, with the type
            # weights (a missing EDGE outranks a missing PROPERTY) applying to
            # none of them, and a dangling edge -- MISSING_NODE, the highest
            # weight in the table because it means the topology itself is wrong
            # -- sorting LAST at 0.03 because it was found several hops from
            # where the walk began.
            #
            # A structural gap has no hops: the builder found it AT the entity.
            # So it is scored the way a traversal gap at hop zero is scored, by
            # the same method, and the two populations become comparable --
            # `type weight` here, `type weight decayed by distance` there. One
            # source for the weights rather than a constant beside them.
            priority=traverser._compute_priority(gap, 0),
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
    # the fourth report of input that goes nowhere, in both tools for
    # the reason the third one gives. An internal ruling removed a walk that judged every
    # entity property by its name; the rules it applied are declarable and now
    # declared, but an author cannot declare a property they do not know they
    # are sending. This says what arrived and was never read.
    payload["unread_properties"] = session.unread_properties()
    # B-2.7 — a bound read off an entity is invisible in the envelope, which
    # reports the number and not where it came from. Both halves ride here: what
    # is set, and what is set and will never be read.
    payload["instance_thresholds"] = session.instance_thresholds()
    payload["unread_declared_thresholds"] = session.unread_declared_thresholds()
    return _WithPayload(envelope, payload)


def project(session: EngineSession, horizon_s: float = 3600.0) -> Envelope:
    """Forecast every declared numeric indicator, and say what could not be.

    WHICH LEGS THIS VERB CAN HONESTLY FILL

    `checked.invariants` is 0, following `attest`: this verb evaluates no
    axioms, and reporting the number of series it looked at as `invariants`
    would be the declared-versus-evaluated conflation that field was corrected
    to end. The projection's own denominator is `projection.checked`, counted in
    the units projection owns -- series, forecasts, observations assimilated --
    and the two are NEVER summed.

    `not_checked` is empty and the projection's declines are not copied into it.
    That is a shape limit rather than a decision: a top-level decline record
    REQUIRES one of eight axioms, and *this series has no declared dynamics* has
    none. Supplying one would mean naming an axiom from a field that no axiom
    reads.

    `findings` and `questions` DO carry the projection's, because both have a
    shape the leg can hold, and a consumer reading the envelope generically must
    not see an empty findings leg while a finding exists -- silence reading as
    health is the failure this envelope exists to prevent. They therefore appear
    twice: once in the generic leg, once in the discipline's own accounting. A
    test holds the two to each other, because a fact written in two places
    drifts unless something compares them.
    """
    if session.model is None:
        return unavailable_envelope("no domain model loaded")
    if not session.entities:
        return unavailable_envelope("no entities supplied")

    sub = run_projection(session, horizon_s)
    envelope = Envelope(
        checked=CheckedSummary(invariants=0, entities=len(session.entities)),
        findings=list(sub.findings),
        questions=[_q(q) for q in sub.questions],
    )
    payload = envelope.to_dict()
    payload["projection"] = sub.to_dict()
    return _WithPayload(envelope, payload)


def discover(session: EngineSession, alpha: Optional[float] = None,
             lags: Optional[Sequence[int]] = None,
             budget_pairs: int = 500) -> Envelope:
    """Test which declared series precede which, and say what went untested.

    `alpha` is the corrected p-value at which a lead-lag result counts as
    support. WITHOUT IT THERE ARE NO FINDINGS AND NO PROPOSALS: the tests run,
    their p-values are reported, and the engine declines to rule -- because how
    much a false edge costs is a fact about the engagement. Same rule as
    `project`'s `report_above`.

    The proposed `IORelationship` records are left on the envelope's payload
    and on `session.proposed_io_relationships`. They are NOT applied. Only
    `session.adopt_io_relationships()` changes what gets checked, because a
    proposal is not a declaration.
    """
    if session.model is None:
        return unavailable_envelope("no domain model loaded")
    if not session.entities:
        return unavailable_envelope("no entities supplied")

    sub, proposals = run_discovery(
        session, alpha=alpha,
        lags=tuple(lags) if lags else DEFAULT_LAGS,
        budget_pairs=budget_pairs)
    session.proposed_io_relationships = list(proposals)
    envelope = Envelope(
        checked=CheckedSummary(invariants=0, entities=len(session.entities)),
        findings=list(sub.findings),
        questions=[_q(q) for q in sub.questions],
    )
    payload = envelope.to_dict()
    payload["discovery"] = sub.to_dict()
    payload["proposed_io_relationships"] = [
        {"input_entity_type": r.input_entity_type,
         "output_entity_type": r.output_entity_type,
         "input_property": r.input_property,
         "output_property": r.output_property,
         "correlation": r.correlation, "lag_seconds": r.lag_seconds,
         "granger_p_value": r.granger_p_value, "confidence": r.confidence,
         "adopted": False}
        for r in proposals
    ]
    return _WithPayload(envelope, payload)


def entail(session: EngineSession, adopt: bool = False) -> Envelope:
    """Derive what the declared rules entail from the declared edges.

    A rule is a conjunctive query of at most three atoms whose head predicate
    is not in its own body. Those bounds are one bound: they are what keeps
    evaluation polynomial, which is the project's actual constraint, and they
    are why a body MAY quantify its join variable.

    `adopt=False` derives and reports; nothing changes. `adopt=True` writes the
    derived edges into the graph, each carrying the rule and the facts that
    produced it, so that a CONNECTIVITY check can afterwards count an edge
    nobody fed in and a finding resting on one can be traced to its author.
    Separate for the same reason `discover` proposes rather than promotes --
    except that here the derivation IS sound given its inputs, so adopting is
    a decision about what to check, not about whether to believe.
    """
    if session.model is None:
        return unavailable_envelope("no domain model loaded")

    sub, derived = entail_rules(session.model, session.graph, session.entities)
    session.derived_facts = list(derived)
    adopted = 0
    if adopt:
        for (relation, source, target), meta in derived:
            session.graph.add_relationship(
                source, relation, target,
                properties={"source": "inferred", "proof": meta})
            adopted += 1

    envelope = Envelope(
        checked=CheckedSummary(invariants=0, entities=len(session.entities)),
        findings=list(sub.findings),
        questions=[_q(q) for q in sub.questions],
    )
    payload = envelope.to_dict()
    payload["entailment"] = sub.to_dict()
    payload["derived_facts"] = [
        {"predicate": relation, "source": source, "target": target,
         "rule": meta["rule"], "from": meta["from"], "adopted": bool(adopt)}
        for (relation, source, target), meta in derived
    ]
    return _WithPayload(envelope, payload)


def infer(session: EngineSession, target: str,
          do: Optional[Dict[str, int]] = None,
          report_above: Optional[float] = None) -> Envelope:
    """How likely is `target` faulty, given what the last check could see?

    The causal edges are the ones the author declared `edge_direction: causal`
    in `relationship_rules`; the strengths are the ones they declared or a
    learner measured. A strength nobody supplied STOPS the answer -- a
    posterior is a product of edge weights, and one the engine chose would make
    the number partly a statement about the engine with no way to tell which
    part.

    `do={"node": 1}` is an INTERVENTION, not an observation: the node's
    incoming edges are cut before the query is answered. That distinction is
    the whole reason this verb exists rather than being a filter over
    `traverse`.

    Evidence is the last `check()`. An entity in its `not_checked` leg is left
    UNOBSERVED rather than assumed clean, and the count of those rides in every
    answer -- a posterior computed with six of ten nodes unseen is a different
    claim from one computed with all ten.

    Without `report_above` there is no finding, on the same rule as `project`
    and `discover`: the posterior is computed and reported, and whether it is
    alarming is not the engine's to decide.
    """
    if session.model is None:
        return unavailable_envelope("no domain model loaded")
    if not session.entities:
        return unavailable_envelope("no entities supplied")

    sub = run_inference(session, Query(target=target, do=dict(do or {})),
                        report_above=report_above)
    envelope = Envelope(
        checked=CheckedSummary(invariants=0, entities=len(session.entities)),
        findings=list(sub.findings),
        questions=[_q(q) for q in sub.questions],
        source=sub.source, reason=sub.reason,
    )
    payload = envelope.to_dict()
    payload["inference"] = sub.to_dict()
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
