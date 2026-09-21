"""A time course this engine supplied is reported, not applied in silence.

`temporal:` is optional, and an edge without it -- or with it and
short of a key -- keeps `TwinEdge`'s own 60 s dead time and 60 s time
constant. Nothing said so, and the default is not small: on the shipped
pump-and-tank model, dropping `time_constant_s` ALONE moves the first reported
level from 61.01 to 69.99 and reports the tank settled when the declared
course puts it a little past halfway. 60 s stands in for a declared 600 s.

The sibling block on the same edge has refused partial declarations since
0.2.3, because a gain nobody wrote is a guess with a decimal point. The time
course was left defaulting, and it decides every value before steady state.

RULED: PROJECT AND STAMP, NOT REFUSE. The values are unchanged on purpose --
these tests pin that -- and what is new is that the engine says whose number
the transient is. `gaps` raises a `missing_declaration` naming the absent key
AND the number used in its place, and any envelope computed across that edge
carries `time_course_not_declared`.

THE NUMBER IS IN THE QUESTION, not the description: `gaps` serialises type,
location and priority and drops everything else, which is the mistake that
An internal ruling fixed one block over.

`response_model` is deliberately exempt. A response SHAPE beside a declared
tau is a materially weaker assumption than the tau is.
"""
from __future__ import annotations

import copy
import json

import pytest
import yaml

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance
from arbiter_engine.twin.topology import TIME_COURSE_KEYS

STAMP = "time_course_not_declared"

MODEL = """
domain:
  id: time_course_pin
  name: A pump feeding a tank
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS],
         critical: 9000, window: 30m}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS],
         critical: 9000, window: 30m}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal:
        propagation_delay_s: 120
        time_constant_s: 600
        response_model: exponential
      transition:
        from: speed_rpm
        to: level_pct
        gain: 0.02
        gain_sigma: 0.002
        source: datasheet
  action_templates:
    - name: throttle_pump
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm,
                    candidates: [800, 1500, 2200, 3000]}
      effect: set
      settle_s: 0
      source: runbook
"""


def _variant(drop=None, drop_block=False):
    model = yaml.safe_load(MODEL)
    rule = model["domain"]["relationship_rules"][0]
    if drop_block:
        rule.pop("temporal")
    elif drop:
        rule["temporal"].pop(drop)
    return yaml.safe_dump(model, sort_keys=False)


def _session(text):
    s = api.EngineSession()
    s.load_model(text)
    s.add_entity("pump1", "Pump", properties={"speed_rpm": 2000})
    s.add_entity("tank1", "Tank", properties={"level_pct": 50})
    s.add_observations("pump1", "speed_rpm", [2000.0] * 40)
    s.add_observations("tank1", "level_pct", [50.0] * 40)
    s.add_relationship("pump1", "feeds", "tank1")
    return s


def _first_step(text):
    s = _session(text)
    env = api.rollout(
        s,
        actions=[ActionInstance("throttle_pump", "pump1",
                                {"speed_rpm": 3000.0}, at_s=0.0)],
        horizon_s=3600, step_s=600).to_dict()
    return s, env["simulation"]


class TestTheDefaultIsLargeEnoughToMatter:
    """The measurement that says this is worth reporting at all."""

    def test_dropping_the_time_constant_moves_the_first_value(self):
        _, declared = _first_step(MODEL)
        _, defaulted = _first_step(_variant(drop="time_constant_s"))
        a = declared["per_step"][0]["values"]["tank1"]["level_pct"]
        b = defaulted["per_step"][0]["values"]["tank1"]["level_pct"]
        assert a == pytest.approx(61.0134, abs=1e-3)
        assert b == pytest.approx(69.9933, abs=1e-3)
        # Nine points apart, and the defaulted one reads as settled.
        assert b - a > 8.0
        assert defaulted["per_step"][0]["response_fractions"][0] > 0.999

    def test_the_declared_course_is_untouched_by_this_change(self):
        """RULED NON-BREAKING. If this moves, the ruling was not kept."""
        _, declared = _first_step(MODEL)
        levels = [s["values"]["tank1"]["level_pct"]
                  for s in declared["per_step"]]
        assert levels[0] == pytest.approx(61.0134, abs=1e-3)
        assert levels[-1] == pytest.approx(69.9394, abs=1e-3)


INCOMPLETE = [
    (_variant(drop="time_constant_s"), ["time_constant_s"]),
    (_variant(drop="propagation_delay_s"), ["propagation_delay_s"]),
    (_variant(drop_block=True), list(TIME_COURSE_KEYS)),
]
INCOMPLETE_IDS = ["tau-omitted", "delay-omitted", "block-absent"]


class TestADeclaredCourseIsNotStamped:

    def test_no_stamp_and_no_question_when_the_pair_is_declared(self):
        s, sim = _first_step(MODEL)
        assert STAMP not in (sim.get("assumptions") or [])
        blob = json.dumps(api.gaps(s).to_dict())
        assert "time course" not in blob


class TestAnInventedCourseIsStampedAndAsked:

    @pytest.mark.parametrize("text,expected", INCOMPLETE, ids=INCOMPLETE_IDS)
    def test_the_envelope_is_stamped(self, text, expected):
        _, sim = _first_step(text)
        assert STAMP in (sim.get("assumptions") or [])

    @pytest.mark.parametrize("text,expected", INCOMPLETE, ids=INCOMPLETE_IDS)
    def test_the_question_names_the_key_and_the_number(self, text, expected):
        s = _session(text)
        asked = [q for q in api.gaps(s).to_dict().get("questions", [])
                 if "time course" in (q.get("question") or "")]
        assert len(asked) == 1, asked
        question = asked[0]["question"]
        for key in expected:
            assert f"`{key}`" in question
            # THE NUMBER TOO. A question naming only the key sends a reader
            # to the file without telling them what is standing in meanwhile.
            assert f"{key}=60s" in question
        assert asked[0]["gap_type"] == "missing_declaration"


class TestTheResponseModelIsExempt:

    def test_dropping_only_the_response_model_asks_nothing(self):
        """A SHAPE beside a declared tau is a weaker assumption than the tau.

        Pinned so that widening `TIME_COURSE_KEYS` to three members is a
        deliberate act and not an accident of a later edit.
        """
        assert "response_model" not in TIME_COURSE_KEYS
        s = _session(_variant(drop="response_model"))
        asked = [q for q in api.gaps(s).to_dict().get("questions", [])
                 if "time course" in (q.get("question") or "")]
        assert asked == []


class TestAnEdgeWithNoTransitionIsNotAsked:

    def test_reachability_only_edges_are_left_alone(self):
        """With nothing to project, the delay reaches no reported VALUE, and
        asking for it would be asking an author to declare a number nothing
        reads."""
        model = yaml.safe_load(MODEL)
        model["domain"]["relationship_rules"][0].pop("transition")
        model["domain"]["relationship_rules"][0].pop("temporal")
        s = _session(yaml.safe_dump(model, sort_keys=False))
        asked = [q for q in api.gaps(s).to_dict().get("questions", [])
                 if "time course" in (q.get("question") or "")]
        assert asked == []


class TestBothBuildersAskTheSameQuestion:
    """The two builders, not one of them.

    `api` reaches `build_from_relationship_graph`; `build_from_yaml` is the
    other door, and a check added to one reader and not the other is the
    shape and each closed from a different direction. This
    file carries both of their docstrings, so this is pinned rather than
    assumed.
    """

    @staticmethod
    def _topology(text):
        from arbiter_engine.interfaces import (
            Entity, RelationshipGraph)
        from arbiter_engine.twin.builder import TopologyBuilder
        entities = {
            "pump1": Entity(id="pump1", type="Pump", name="pump1",
                            properties={"speed_rpm": 2000}),
            "tank1": Entity(id="tank1", type="Tank", name="tank1",
                            properties={"level_pct": 50}),
        }
        graph = RelationshipGraph()
        graph.add_relationship("pump1", "feeds", "tank1")
        return TopologyBuilder().build_from_yaml(
            yaml.safe_load(text), entities, graph)

    def _edges(self, text):
        topology = self._topology(text)
        return [e for bucket in topology.edges.values() for e in bucket]

    def test_the_yaml_builder_records_the_absent_keys(self):
        edges = self._edges(_variant(drop="time_constant_s"))
        assert edges, "no edge was built"
        assert any(e.undeclared_time_course == ("time_constant_s",)
                   for e in edges)

    def test_the_yaml_builder_raises_the_same_gap(self):
        edges = self._edges(_variant(drop_block=True))
        asked = [g for e in edges for g in e.gaps
                 if "time course" in (g.question_override or "")]
        assert len(asked) == 1
        for key in TIME_COURSE_KEYS:
            assert f"`{key}`" in asked[0].question_override

    def test_a_fully_declared_edge_is_silent_on_this_builder_too(self):
        edges = self._edges(MODEL)
        assert edges
        assert all(e.undeclared_time_course == () for e in edges)
        assert not [g for e in edges for g in e.gaps
                    if "time course" in (g.question_override or "")]
