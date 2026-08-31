"""Per-entity axiom calibration: what an override reaches, proven by running it.

An outside report asked for the threshold resolver to be "wired into the
checkers", having measured a release it did not pin. It is wired, and has been.
What measuring the current engine found instead is two facts a call site cannot
show you, and this file is the oracle for both.

FIRST, an override reaches FIVE of the eight axioms. One more calls the resolver
on a path nothing invokes, so setting one there is silent. RESPONSIVENESS was
filed as the second such axiom and is not: `check_io_pair` runs, fires and
honours the override on any session given I/O relationships. The module carries
the count as
a table; the table is documentation and THIS is what holds it true — every row
is re-derived here by running the engine with the override absent and present
and watching the verdict move or not. A table checked only by reading is a
second copy of a fact, and this project keeps finding those after they drift.

SECOND, and it is the one a consumer feels: an override never touches a
DECLARED threshold. `warning:` and `critical:` are read straight off the model
with no override lookup on that path. What the five reachable axioms override
is their calibration parameter. Pinned below, because the difference is
invisible until a check that should have moved does not.
"""

import ast
import importlib
import inspect
from pathlib import Path

import pytest

from arbiter_engine.api import (
    EngineSession, check, model_describe,
)
from arbiter_engine.axiom_thresholds import (
    OVERRIDE_CONSULTED_BY, OVERRIDE_DECLARED_BUT_UNREACHABLE,
    OVERRIDE_NOT_CONSULTED,
)
from arbiter_engine.ontology import axioms as axioms_pkg
from arbiter_engine.types import Axiom, IORelationship


ENTITY, ETYPE = "Unit/x", "Unit"
OUT_ENTITY, OUT_ETYPE = "Sink/out", "Sink"


def _session(indicators, properties, series=(), extra_entities=(),
             sink_indicators=None, sink=None, io=None):
    """Build a one-entity session, or a two-entity one when the scenario
    needs a pair.

    RESPONSIVENESS's override is read on the I/O-pair path, off
    the OUTPUT entity -- so a single-entity scenario cannot reach it, and
    for months nothing did. The declared `warning:`/`critical:` this
    axiom also carries are NOT overridable, like every declared bound, so
    a scenario that fires those looks like a fair test and exercises the
    wrong path.
    """
    session = EngineSession()
    declared = {ETYPE: indicators}
    if sink_indicators:
        declared[OUT_ETYPE] = sink_indicators
    session.load_model({"domain": {
        "id": "override", "name": "override", "entity_types": [ETYPE, "Sink"],
        "relationship_types": ["feeds"], "indicators": declared}})
    session.add_entity(ENTITY, ETYPE, properties=dict(properties))
    # CONNECTIVITY declines `missing_entity_type` rather than firing when no
    # entity of the target type exists -- correctly, since a cardinality it
    # cannot evaluate is not a cardinality it can call violated. Its scenario
    # supplies one so the check reaches a verdict and the override has
    # something to fail to move.
    for entity_id, entity_type in extra_entities:
        session.add_entity(entity_id, entity_type)
    for name, values in series:
        session.add_observations(ENTITY, name, values)
    if sink:
        session.add_entity(OUT_ENTITY, OUT_ETYPE, properties=dict(sink["properties"]))
        for name, values in sink.get("series", ()):
            session.add_observations(OUT_ENTITY, name, values)
    if io:
        session.reasoner.set_io_relationships([IORelationship(**kw) for kw in io])
    return session


def _fired(session):
    return sorted(f["problem_type"] for f in check(session).to_dict()["findings"])


#: One firing scenario per axiom, plus the override value that should silence
#: it. Authored -- a domain model is a written thing -- and pinned against the
#: Axiom enum by equality below, so a ninth axiom cannot slip through untested.
SCENARIOS = {
    "STABILITY": dict(
        indicators=[{"name": "v", "type": "NUMERIC", "axioms": ["STABILITY"],
                     "window": "30m"}],
        properties={"v": 1.0},
        series=(("v", [float(i % 2) for i in range(20)]),),
        silence=dict(warning=1.5),
    ),
    "MONOTONICITY": dict(
        indicators=[{"name": "v", "type": "NUMERIC", "axioms": ["MONOTONICITY"],
                     "window": "24h",
                     "monotonicity": {"expected_direction": "increasing",
                                      "allow_reset": True}}],
        properties={"v": 10.0},
        series=(("v", [10_000.0, 5_000.0, 10.0]),),
        silence=dict(warning=1e9, critical=1e9),
    ),
    "CONSERVATION": dict(
        indicators=[{"name": "inflow_lps", "type": "NUMERIC",
                     "axioms": ["CONSERVATION"], "window": "15m",
                     "conservation": {"input_property": "inflow_lps",
                                      "output_properties": ["outflow_lps"],
                                      "loss_margin": 0.05}},
                    {"name": "outflow_lps", "type": "NUMERIC", "axioms": []}],
        properties={"inflow_lps": 8.0, "outflow_lps": 5.0},
        series=(("inflow_lps", [8.0] * 10), ("outflow_lps", [5.0] * 10)),
        silence=dict(warning=0.99),
        indicator="inflow_lps",
    ),
    "HOMEOSTASIS": dict(
        indicators=[{"name": "v", "type": "NUMERIC", "axioms": ["HOMEOSTASIS"],
                     "window": "1h"}],
        properties={"v": 900.0},
        series=(("v", [100.0 + (i % 3) for i in range(60)]),),
        silence=dict(warning=1e9, critical=1e9),
    ),
    "BOUNDEDNESS": dict(
        indicators=[{"name": "v", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                     "warning": 85, "critical": 95, "window": "1h"}],
        properties={"v": 99.0},
        series=(),
        silence=dict(warning=1e9, critical=1e9),
    ),
    # The I/O-PAIR path, not the declared-threshold one. This axiom
    # carries both, and only the pair path consults an override: a scenario
    # firing `response_time_critical` off declared `warning:`/`critical:`
    # cannot move, because a DECLARED bound is not overridable in any axiom.
    # The pair needs two entities and an I/O relationship, which is why this
    # row is the only one carrying `sink` and `io`, and why the override goes
    # on the OUTPUT entity -- the resolver reads it off that side.
    "RESPONSIVENESS": dict(
        indicators=[{"name": "v", "type": "NUMERIC", "role": "latency",
                     "axioms": ["RESPONSIVENESS"], "window": "30m"}],
        properties={"v": 100.0},
        series=(("v", [10.0 * i for i in range(1, 15)]),),
        sink_indicators=[{"name": "v", "type": "NUMERIC", "role": "latency",
                          "axioms": ["RESPONSIVENESS"], "window": "30m"}],
        sink=dict(properties={"v": 50.0},
                  series=(("v", [50.0 + (i % 2) for i in range(14)]),)),
        io=[dict(input_entity_type=ETYPE, output_entity_type=OUT_ETYPE,
                 input_property="v", output_property="v",
                 correlation=0.95, lag_seconds=1.0)],
        override_on=OUT_ENTITY,
        silence=dict(warning=0.99),
    ),
    "CONSISTENCY": dict(
        indicators=[{"name": "v", "type": "NUMERIC", "role": "percentage",
                     "axioms": ["CONSISTENCY"], "window": "15m"}],
        properties={"v": 10_000.0},
        series=(),
        silence=dict(warning=1e9, critical=1e9),
    ),
    "CONNECTIVITY": dict(
        indicators=[{"name": "feeds_a_sink", "type": "RELATIONSHIP",
                     "axioms": ["CONNECTIVITY"], "target_type": "Sink",
                     "relation_type": "feeds", "min_cardinality": 1,
                     "max_cardinality": 2, "violation_severity": "HIGH"}],
        properties={},
        series=(),
        silence=dict(warning=1e9, critical=1e9),
        indicator="feeds_a_sink",
        extra_entities=(("Sink/one", "Sink"),),
    ),
}


def _run(axiom, with_override):
    spec = SCENARIOS[axiom]
    session = _session(spec["indicators"], spec["properties"], spec["series"],
                       spec.get("extra_entities", ()),
                       sink_indicators=spec.get("sink_indicators"),
                       sink=spec.get("sink"), io=spec.get("io"))
    if with_override:
        session.set_threshold_override(
            spec.get("override_on", ENTITY), spec.get("indicator", "v"),
            axiom, **spec["silence"])
    return _fired(session)


class TestTheTablePartitionsTheAxioms:
    """Three groups, and every axiom in exactly one.

    Equality, not containment: a ninth axiom, or one moved between groups
    without the table being updated, has to go red rather than fall through a
    gap between three lists that each look complete on their own.
    """

    def test_the_three_groups_cover_every_axiom_exactly_once(self):
        groups = (list(OVERRIDE_CONSULTED_BY)
                  + list(OVERRIDE_DECLARED_BUT_UNREACHABLE)
                  + list(OVERRIDE_NOT_CONSULTED))
        assert sorted(groups) == sorted(a.value for a in Axiom)
        assert len(groups) == len(set(groups)), "an axiom is in two groups"

    def test_every_axiom_has_a_scenario(self):
        assert set(SCENARIOS) == {a.value for a in Axiom}, (
            "an axiom with no scenario is one this file never exercises")


class TestTheTableIsTrueOfTheEngine:
    """The rows, re-derived by running it."""

    @pytest.mark.parametrize("axiom", sorted(OVERRIDE_CONSULTED_BY))
    def test_a_consulted_axiom_moves_when_overridden(self, axiom):
        without, with_ = _run(axiom, False), _run(axiom, True)
        assert without, f"{axiom} did not fire at all; the scenario is stale"
        assert with_ != without, (
            f"{axiom} is listed as consulting an override and the verdict did "
            f"not move: {without} -> {with_}")

    @pytest.mark.parametrize(
        "axiom", sorted(list(OVERRIDE_DECLARED_BUT_UNREACHABLE)
                        + list(OVERRIDE_NOT_CONSULTED)))
    def test_an_unreached_axiom_does_not_move(self, axiom):
        without, with_ = _run(axiom, False), _run(axiom, True)
        assert without, f"{axiom} did not fire at all; the scenario is stale"
        assert with_ == without, (
            f"{axiom} is listed as not reachable by an override and the "
            f"verdict moved: {without} -> {with_}. The table is now wrong, "
            f"which is better news than it sounds -- something got wired.")


class TestUnreachableIsNotTheSameAsAbsent:
    """The distinction the middle group exists to make.

    `axiom_unreachable` says the checker asks for an override on a path nothing
    runs; `axiom_never_consults` says it does not ask at all. They look
    identical from outside -- nothing happens -- and the remedies differ, so
    the source is what tells them apart.
    """

    def _calls_the_resolver(self, axiom):
        # The package is reached by a real import, not by a package path in a
        # string. A dotted name written into a literal is prose to the rewrite:
        # it would be substituted in place, and a test that names its own
        # package in prose is the defect the suite already carries a guard for.
        module = importlib.import_module(f"{axioms_pkg.__name__}.{axiom.lower()}")
        tree = ast.parse(Path(inspect.getfile(module)).read_text())
        return any(isinstance(n, ast.Call)
                   and getattr(n.func, "id", "") == "resolve_axiom_threshold"
                   for n in ast.walk(tree))

    @pytest.mark.parametrize("axiom", sorted(OVERRIDE_DECLARED_BUT_UNREACHABLE))
    def test_it_really_does_ask_for_an_override(self, axiom):
        assert self._calls_the_resolver(axiom), (
            f"{axiom} is filed as declared-but-unreachable and its checker "
            f"never calls the resolver at all; it belongs in the other group")

    @pytest.mark.parametrize("axiom", sorted(OVERRIDE_NOT_CONSULTED))
    def test_it_really_does_not_ask(self, axiom):
        assert not self._calls_the_resolver(axiom)

    @pytest.mark.parametrize("axiom", sorted(OVERRIDE_DECLARED_BUT_UNREACHABLE))
    def test_the_reason_is_recorded_and_not_a_bare_flag(self, axiom):
        assert len(OVERRIDE_DECLARED_BUT_UNREACHABLE[axiom]) > 40, (
            "an unreachable path needs its reason written down; a bare entry "
            "is a fact nobody can act on or refute")


class TestADeclaredThresholdIsNotOverridable:
    """The finding a consumer actually needs, pinned as a negative.

    BOUNDEDNESS declares `warning: 85` and `critical: 95`, and those are read
    off the spec. No override reaches them -- which is why a consumer with
    hundreds of sensors, each carrying its own vendor limits, ends up declaring
    an entity type per sensor. If this test ever goes red, that capability
    arrived and the workaround can be retired.
    """

    def test_overriding_boundedness_does_not_move_a_declared_bound(self):
        spec = SCENARIOS["BOUNDEDNESS"]
        loose = _session(spec["indicators"], spec["properties"])
        loose.set_threshold_override(ENTITY, "v", "BOUNDEDNESS",
                                     warning=1e9, critical=1e9)
        assert _fired(loose), (
            "a value of 99 against a declared critical of 95 stopped firing "
            "when a wildly loose override was set -- declared thresholds have "
            "become overridable, and this file's premise needs revisiting")


class TestTheFeeder:

    def test_it_reaches_the_engine_through_the_public_surface(self):
        assert _run("STABILITY", False) == ["stability_oscillation:v"]
        assert _run("STABILITY", True) == []

    def test_an_unknown_entity_is_refused(self):
        """An override is stored ON an entity; with no entity there is nowhere
        to put it, and silently creating one would invent topology."""
        session = _session(SCENARIOS["STABILITY"]["indicators"], {"v": 1.0})
        with pytest.raises(KeyError):
            session.set_threshold_override("Unit/absent", "v", "STABILITY",
                                           warning=1.0)

    def test_the_axiom_name_is_case_insensitive(self):
        session = _session(SCENARIOS["STABILITY"]["indicators"], {"v": 1.0},
                           SCENARIOS["STABILITY"]["series"])
        session.set_threshold_override(ENTITY, "v", "stability", warning=1.5)
        assert _fired(session) == [], (
            "a lowercase axiom name was stored under a key no checker looks up")

    def test_it_translates_a_declared_name_to_the_property_the_checker_reads(self):
        """The trap this closes: checkers look up `property_name`, which is the
        declared name only until a model carries a `property_mapping`. Keying
        on what the caller reads in their own model is the point of the feeder.
        """
        session = EngineSession()
        session.load_model({"domain": {
            "id": "mapped", "name": "mapped", "entity_types": [ETYPE],
            "relationship_types": [],
            "property_mapping": {ETYPE: {"v": "raw_v"}},
            "indicators": {ETYPE: SCENARIOS["STABILITY"]["indicators"]}}})
        session.add_entity(ENTITY, ETYPE, properties={"raw_v": 1.0})
        session.add_observations(ENTITY, "raw_v",
                                 [float(i % 2) for i in range(20)])
        session.set_threshold_override(ENTITY, "v", "STABILITY", warning=1.5)
        stored = next(iter(
            session.entities[ENTITY].properties[
                "__axiom_threshold_overrides__"]))
        assert stored[0] == "raw_v", (
            f"stored under {stored[0]!r}; the checker will look up the mapped "
            f"property name and find nothing")


class TestTheReport:
    """Every way of getting an override wrong fails identically -- nothing
    happens -- so the report is what tells them apart."""

    def _reported(self):
        session = _session(SCENARIOS["STABILITY"]["indicators"], {"v": 1.0},
                           SCENARIOS["STABILITY"]["series"])
        session.set_threshold_override(ENTITY, "v", "STABILITY", warning=1.5)
        session.set_threshold_override(ENTITY, "v", "BOUNDEDNESS", warning=0.5)
        session.set_threshold_override(ENTITY, "v", "CONNECTIVITY", warning=0.5)
        session.set_threshold_override(ENTITY, "typo", "STABILITY", warning=0.5)
        return session

    def test_a_working_override_is_not_reported(self):
        rows = self._reported().unread_threshold_overrides()
        assert not [r for r in rows
                    if r["axiom"] == "STABILITY" and r["indicator"] == "v"], (
            "the one override that works was reported as unread; a report that "
            "fires on good input is one people learn to skip")

    @pytest.mark.parametrize("axiom,indicator,reason", [
        ("BOUNDEDNESS", "v", "axiom_unreachable"),
        ("CONNECTIVITY", "v", "axiom_never_consults"),
        ("STABILITY", "typo", "undeclared_indicator"),
    ])
    def test_each_way_of_being_wrong_gets_its_own_reason(
            self, axiom, indicator, reason):
        rows = self._reported().unread_threshold_overrides()
        match = [r for r in rows
                 if r["axiom"] == axiom and r["indicator"] == indicator]
        assert match, f"{axiom}/{indicator} went unreported"
        assert match[0]["reason"] == reason

    def test_the_reasons_are_a_closed_set(self):
        rows = self._reported().unread_threshold_overrides()
        assert {r["reason"] for r in rows} <= {
            "axiom_unreachable", "axiom_never_consults", "undeclared_indicator"}

    def test_it_reaches_the_describe_payload(self):
        payload = model_describe(self._reported()).to_dict()
        assert len(payload["unread_threshold_overrides"]) == 3

    def test_a_session_with_no_overrides_reports_nothing(self):
        session = _session(SCENARIOS["STABILITY"]["indicators"], {"v": 1.0})
        assert session.unread_threshold_overrides() == []
