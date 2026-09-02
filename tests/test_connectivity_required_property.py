"""A mistyped `required_property` retired the check, and the denominator agreed.

A topology statement may gate its cardinality check on a property the entity
must carry. The gate read `if not entity.properties.get(prop)`, which folds two
facts: the entity does not carry this property, and it carries it with a falsy
value. The second is the case the gate was added for -- a selector-less Service
legitimately has no edges and should not alarm. The first is a property name the
model got wrong.

Folding them meant a typo RETIRED the check. The cardinality violation this cell
exists to find became an empty list, which the envelope reports as a clean pass
while `checked.invariants` counts the cell as attempted. That is worse than a
silent miss: the denominator that exists to make missed coverage visible agrees
the cell was covered.

The two cannot be separated on one entity, so the remedy asks the POPULATION. A
name the model supplies resolves on somebody -- a cluster running selector-less
Services also runs Services with selectors. A typo resolves nowhere.

THE CONTROLS ARE THE POINT. A fix that suppresses the legitimate skip replaces
this defect with the false positives the gate was added to remove, so the skip is
pinned in three shapes here alongside the decline.
"""
from __future__ import annotations

import pathlib
import tempfile
import textwrap

import pytest

from arbiter_engine.api import EngineSession, check
from arbiter_engine.interfaces import Entity, RelationshipGraph
from arbiter_engine.ontology.axioms.connectivity import (
    ConnectivityChecker,
)
from arbiter_engine.history.observation import (
    InMemoryObservationHistory,
)

HEAD = ("domain:\n  id: t\n  name: T\n  entity_types: [Unit]\n"
        "  relationship_types: [feeds]\n  indicators:\n")

MODEL = """
    Unit:
      - name: feeds
        type: relationship
        axioms: [CONNECTIVITY]
        relation_type: feeds
        target_type: Unit
        min_cardinality: 1
        required_property: {prop}
    """


def _envelope(prop, population, edges=()):
    """Through the front door. `population` is {entity_id: properties}."""
    path = pathlib.Path(tempfile.mktemp(suffix=".yaml"))
    path.write_text(HEAD + textwrap.indent(
        textwrap.dedent(MODEL.format(prop=prop)), "    "))
    session = EngineSession()
    session.load_model(str(path))
    for entity_id, props in population.items():
        session.add_entity(entity_id, "Unit", props)
    for source, target in edges:
        session.add_relationship(source, "feeds", target)
    return check(session).to_dict()


def _declines(envelope):
    return [d for d in envelope["not_checked"] if d["axiom"] == "CONNECTIVITY"]


def _findings(envelope):
    return [f for f in envelope["findings"]
            if f["problem_type"].startswith("missing_relationship")]


class TestTheNameResolvesNowhere:
    """The defect. No entity of the type carries the gate property."""

    def test_it_declines_instead_of_retiring_the_check(self):
        env = _envelope("enabld", {"u1": {"enabled": True},
                                   "u2": {"enabled": True}})
        declines = _declines(env)
        assert declines, (
            "a gate property nothing carries retired the check silently; "
            f"envelope reported {env['findings']} and {env['not_checked']}")
        assert declines[0]["reason"] == "missing_property"

    def test_it_quotes_the_token_the_author_would_change(self):
        env = _envelope("enabld", {"u1": {"enabled": True}})
        assert "enabld" in _declines(env)[0]["detail"]

    def test_it_names_both_readings_rather_than_accusing_the_model(self):
        # The population is the only oracle available, and it cannot tell a
        # typo from a property nothing has reported yet. Saying so is the
        # difference between a decline and a misattribution.
        detail = _declines(env := _envelope("enabld", {"u1": {"enabled": 1}}))[0]["detail"]
        assert "observed" in detail and "name" in detail
        assert not _findings(env)

    def test_the_check_is_not_reported_as_a_clean_pass(self):
        # The original defect in one assertion: findings empty AND nothing in
        # not_checked, while checked.invariants counts the cell as attempted.
        env = _envelope("enabld", {"u1": {"enabled": True}})
        assert env["checked"]["invariants"] >= 1
        assert not (not env["findings"] and not env["not_checked"])


class TestTheLegitimateSkipSurvives:
    """The controls. The gate exists so a legitimately ungated entity is quiet.

    RE-DERIVED UPWARD BY, not relaxed. These asserted `not _declines`,
    which read *the skip is silent* -- and silence was the defect that CD closed:
    a gated cell counted in the denominator and appearing in no row is
    byte-identical to a cell that evaluated and found nothing.

    The claim these controls were written to protect is that a legitimately
    gated entity does not ALARM, and that its gate is not mistaken for the typo
     reports. Both survive. What changed is that the skip now says so.
    """

    def _gate_reasons(self, env, entity_id):
        return {d["reason"] for d in _declines(env) if d["entity_id"] == entity_id}

    def test_a_carried_but_falsy_value_declines_without_alarming(self):
        # u2 carries `enabled`, so the NAME resolves; u1 carries it falsy and
        # is the entity the gate was written for.
        env = _envelope("enabled", {"u1": {"enabled": False},
                                    "u2": {"enabled": True}},
                        edges=[("u2", "u1")])
        assert self._gate_reasons(env, "u1") == {"precondition_unmet"}, (
            "the entity the gate was added for is not reported as gated")
        assert not [f for f in _findings(env) if f["entity_id"] == "u1"], (
            "the gate alarmed for an entity it was added to exempt")

    def test_presence_is_what_resolves_a_name_not_truthiness(self):
        # Every entity carries the property and every value is falsy. The name
        # resolves; a truthiness test would read this as unresolved and decline
        # MISSING_PROPERTY across the whole population, which is the
        # failure direction and the one that costs findings.
        env = _envelope("selector", {"s1": {"selector": {}},
                                     "s2": {"selector": {}}})
        reasons = {d["reason"] for d in _declines(env)}
        assert reasons == {"precondition_unmet"}, (
            f"the name resolved on the population and was reported as "
            f"unresolved anyway: {reasons}")
        assert not _findings(env)

    def test_a_missing_key_on_one_entity_is_still_the_quiet_skip(self):
        env = _envelope("selector", {"s1": {},
                                     "s2": {"selector": {"app": "x"}}},
                        edges=[("s2", "s1")])
        assert self._gate_reasons(env, "s1") == {"precondition_unmet"}
        assert "missing_property" not in self._gate_reasons(env, "s1")


class TestTheRealViolationStillFires:
    """A fix that buys quiet by suppressing findings is the worse defect."""

    def test_a_resolving_gate_with_no_edges_still_reports(self):
        env = _envelope("enabled", {"u1": {"enabled": True},
                                    "u2": {"enabled": True}})
        findings = _findings(env)
        assert findings, "the cardinality violation stopped being reported"
        assert findings[0]["severity"] == "high"

    def test_it_still_reports_for_the_gated_entity_only(self):
        # u1 is gated off, u2 is not and has no edges.
        env = _envelope("enabled", {"u1": {"enabled": False},
                                    "u2": {"enabled": True}})
        assert {f["entity_id"] for f in _findings(env)} == {"u2"}


class TestTheDegradedPath:
    """No registry, no population question. Pinned so production cannot use it."""

    def test_the_front_door_always_supplies_the_population(self):
        seen = {}
        original = ConnectivityChecker.check

        def spy(self, entity, indicator, graph, history, *, entities=None):
            seen[entity.id] = entities is not None
            return original(self, entity, indicator, graph, history,
                            entities=entities)

        ConnectivityChecker.check = spy
        try:
            _envelope("enabled", {"u1": {"enabled": True}})
        finally:
            ConnectivityChecker.check = original
        assert seen and all(seen.values()), (
            "a checker reached the population-free path through the front door; "
            "the silent-retire behaviour is reachable in production")

    def test_a_direct_caller_without_a_registry_says_it_did_not_ask(self):
        """The degraded path used to skip in silence; it now declines
        like every other gate, and the DETAIL is what differs.

        Without a registry the population question was never put, so the engine
        cannot say the name resolves. It says so. The first draft of that
        sentence claimed resolution on both paths -- the engine asserting a fact
        it does not hold, inside the change made to stop it doing that."""
        path = pathlib.Path(tempfile.mktemp(suffix=".yaml"))
        path.write_text(HEAD + textwrap.indent(
            textwrap.dedent(MODEL.format(prop="enabld")), "    "))
        session = EngineSession()
        session.load_model(str(path))
        indicator = session.model.indicators["Unit"][0]
        outcome = ConnectivityChecker().check(
            Entity(id="u1", type="Unit", name="u1", properties={"enabled": True}),
            indicator, RelationshipGraph(), InMemoryObservationHistory(),
        )
        declines = list(getattr(outcome, "not_evaluated", ()))
        assert len(declines) == 1
        assert declines[0].reason.value == "precondition_unmet"
        assert "was not checked on this path" in declines[0].detail, (
            "the degraded path claimed the name resolves, which it never asked")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
