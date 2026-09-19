"""An edge with no declared dynamics projects no value, and says which edge.

The whole point of putting a transition model in this engine rather than in a
library that will answer anything is that the engine reports its own coverage.
A learned world model produces a number for every input and cannot say *I did
not model this*; this one declines by edge, by name, with the question whose
answer would fix it.

`GapType.MISSING_DYNAMICS` already existed with the question template *"How
fast does a change propagate through '{location}'?"* and exactly one producer
in the whole package -- `projection/runner.py`, for a numeric indicator with
no `dynamics:` block. The traversal never emitted it, because the traversal
never asked for a value.

WHAT IS PINNED HERE IS THE REFUSAL, NOT THE NUMBER. A partial `transition:`
block is the case an author most needs told about, because it looks declared
in the file: it has a `from` and a `to` and reads like dynamics. Completing it
with a default gain would be the single most damaging silent default in this
design -- a number a reader would act on, invented by the engine.
"""
from __future__ import annotations

import pytest

from arbiter_engine import api

NO_DYNAMICS = """
domain:
  id: no-dynamics
  name: Declared edge, undeclared dynamics
  entity_types: [Pump, Tank, Sink]
  relationship_types: [feeds, drains]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9000}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 95}
    Sink:
      - {name: flow_lps, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 50}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step}
      transition: {from: speed_rpm, to: level_pct, gain: 0.01, source: datasheet}
    - type: drains
      source_type: Tank
      target_type: Sink
      temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step}
"""

PARTIAL = """
domain:
  id: partial
  name: A block that looks declared
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9000}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 95}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step}
      transition: {from: speed_rpm, to: level_pct, source: datasheet}
"""


def _write(tmp_path, text, name):
    path = tmp_path / f"{name}.yaml"
    path.write_text(text)
    return str(path)


def _undeclared(tmp_path):
    session = api.EngineSession()
    session.load_model(_write(tmp_path, NO_DYNAMICS, "no_dynamics"))
    session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("tank1", "Tank", {"level_pct": 40.0})
    session.add_entity("sink", "Sink", {"flow_lps": 5.0})
    session.add_relationship("pump1", "feeds", "tank1")
    session.add_relationship("tank1", "drains", "sink")
    return session


def _walk(session):
    return api.traverse(session, ["pump1"], value_mode="hypothetical",
                        overrides={"pump1": {"speed_rpm": 2000.0}}).to_dict()


class TestAnEdgeWithoutDynamicsIsRefusedByName:

    def test_the_undeclared_edge_produces_a_missing_dynamics_decline(
            self, tmp_path):
        declines = _walk(_undeclared(tmp_path))["simulation"]["not_checked"]
        missing = [d for d in declines if d["reason"] == "missing_dynamics"]
        assert len(missing) == 1
        assert missing[0]["location"] == "tank1->sink"

    def test_the_declared_edge_is_not_declined(self, tmp_path):
        declines = _walk(_undeclared(tmp_path))["simulation"]["not_checked"]
        assert all(d["location"] != "pump1->tank1" for d in declines)

    def test_the_downstream_value_is_not_invented(self, tmp_path):
        values = _walk(_undeclared(tmp_path))["simulation"]["values"]
        assert "tank1" in values, "the declared edge should project"
        assert "sink" not in values, (
            "a value crossed an edge with no declared dynamics")

    def test_the_gap_carries_a_question_an_author_can_answer(self, tmp_path):
        questions = _walk(_undeclared(tmp_path))["questions"]
        dynamics = [q for q in questions
                    if q.get("gap_type") == "missing_dynamics"]
        assert dynamics, "a refusal with no question is a dead end"
        assert dynamics[0]["location"] == "tank1->sink"

    def test_a_current_walk_asks_no_such_question(self, tmp_path):
        """CURRENT asks for no values, so nothing is missing."""
        payload = api.traverse(_undeclared(tmp_path), ["pump1"],
                               value_mode="current").to_dict()
        assert [q for q in payload["questions"]
                if q.get("gap_type") == "missing_dynamics"] == []


class TestAPartialBlockIsRefusedNotCompleted:

    def _partial(self, tmp_path):
        session = api.EngineSession()
        session.load_model(_write(tmp_path, PARTIAL, "partial"))
        session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
        session.add_entity("tank1", "Tank", {"level_pct": 40.0})
        session.add_relationship("pump1", "feeds", "tank1")
        return session

    def test_a_block_without_a_gain_gets_no_gain(self, tmp_path):
        assert _walk(self._partial(tmp_path))["simulation"]["values"] == {}

    def test_the_refusal_names_the_missing_key(self, tmp_path):
        declines = _walk(self._partial(tmp_path))["simulation"]["not_checked"]
        refused = [d for d in declines
                   if d["reason"] in ("missing_declaration",
                                      "missing_dynamics")]
        assert refused, "a partial block was silently dropped"
        assert any("gain" in d["detail"] for d in refused), (
            "the author must be told WHICH key is missing")

    def test_model_describe_reports_the_refusal_without_running_anything(
            self, tmp_path):
        session = api.EngineSession()
        session.load_model(_write(tmp_path, PARTIAL, "partial"))
        coverage = api.model_describe(session).to_dict()["model"]["transitions"]
        assert coverage["refused_blocks"], (
            "a block the engine will refuse at traversal time is knowable "
            "from the model alone, and an author should not have to run a "
            "traversal to find it")
        assert "gain" in coverage["refused_blocks"][0]


class TestModelDescribeReportsDynamicsCoverage:

    def test_rules_without_dynamics_are_listed(self, tmp_path):
        session = api.EngineSession()
        session.load_model(_write(tmp_path, NO_DYNAMICS, "no_dynamics"))
        coverage = api.model_describe(session).to_dict()["model"]["transitions"]
        without = [r["rule"] for r in coverage["rules_without_dynamics"]]
        assert without == ["Tank-drains->Sink"]

    def test_a_rule_with_temporal_but_no_transition_is_still_listed(
            self, tmp_path):
        """The distinction the whole stage rests on.

        A `temporal:` block says how FAST and how LIKELY. Only `transition:`
        says how MUCH. A rule carrying the first and not the second looks
        modelled and cannot project a value.
        """
        session = api.EngineSession()
        session.load_model(_write(tmp_path, NO_DYNAMICS, "no_dynamics"))
        coverage = api.model_describe(session).to_dict()["model"]["transitions"]
        entry = coverage["rules_without_dynamics"][0]
        assert entry["has_temporal"] is True

    def test_the_declared_side_names_its_properties_and_provenance(
            self, tmp_path):
        session = api.EngineSession()
        session.load_model(_write(tmp_path, NO_DYNAMICS, "no_dynamics"))
        coverage = api.model_describe(session).to_dict()["model"]["transitions"]
        assert len(coverage["declared"]) == 1
        entry = coverage["declared"][0]
        # SUBSET, not equality. This asserted the whole dict, which made it
        # fail the first time the entry grew a key -- and COMPATIBILITY.md
        # says in as many words that a PATCH may add one. A test that breaks
        # on every legal addition is pinning a contract the project does not
        # have, and the fix is to assert what this test is named for: that the
        # entry NAMES its properties and their provenance.
        for key, value in {
                "rule": "Pump-feeds->Tank", "from": "speed_rpm",
                "to": "level_pct", "gain": 0.01,
                "source": "datasheet"}.items():
            assert entry[key] == value, key

    def test_the_coverage_counts_add_up(self, tmp_path):
        session = api.EngineSession()
        session.load_model(_write(tmp_path, NO_DYNAMICS, "no_dynamics"))
        checked = api.model_describe(session).to_dict()[
            "model"]["transitions"]["checked"]
        assert checked["with_transition"] + checked["without_transition"] == (
            checked["relationship_rules"])


class TestADeclaredCouplingIsNotPrunedByAnUndeclaredProbability:
    """`propagation_probability` is P(target fails | source fails) and
    defaults to 0.3 when nothing has been learned. A transition is a declared
    coupling between two VALUES. Multiplying them silenced a declared gain
    three hops out: 0.3^3 = 0.027 against `min_probability` 0.05."""

    def test_a_declared_transition_survives_three_hops(self, tmp_path):
        text = """
domain:
  id: deep
  name: Deep chain
  entity_types: [A, B, C, D]
  relationship_types: [feeds]
  indicators:
    A: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9000}]
    B: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9000}]
    C: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9000}]
    D: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9000}]
  relationship_rules:
    - {type: feeds, source_type: A, target_type: B,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: v, to: v, gain: 1.0, source: datasheet}}
    - {type: feeds, source_type: B, target_type: C,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: v, to: v, gain: 1.0, source: datasheet}}
    - {type: feeds, source_type: C, target_type: D,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: v, to: v, gain: 1.0, source: datasheet}}
"""
        session = api.EngineSession()
        session.load_model(_write(tmp_path, text, "deep"))
        for name in "abcd":
            session.add_entity(name, name.upper(), {"v": 0.0})
        session.add_relationship("a", "feeds", "b")
        session.add_relationship("b", "feeds", "c")
        session.add_relationship("c", "feeds", "d")
        values = api.traverse(
            session, ["a"], value_mode="hypothetical",
            overrides={"a": {"v": 10.0}}).to_dict()["simulation"]["values"]
        assert "d" in values, (
            "the third hop was dropped by a reachability probability nobody "
            "declared, and nothing was said about it")
        assert values["d"]["v"]["value"] == pytest.approx(10.0)

    def test_the_bypass_is_stamped(self, tmp_path):
        session = api.EngineSession()
        session.load_model(_write(tmp_path, NO_DYNAMICS, "no_dynamics"))
        session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
        session.add_entity("tank1", "Tank", {"level_pct": 40.0})
        session.add_relationship("pump1", "feeds", "tank1")
        assert "declared_coupling_not_probability_pruned" in _walk(
            session)["simulation"]["assumptions"]
