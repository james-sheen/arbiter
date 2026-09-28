"""`plan` says what each option reaches downstream, and what decides it.

a plan candidate carried its objective, the imagined findings pooled
over every entity, and how close its nearest call was. It could not say WHERE
an option's effect lands -- which entities downstream of the ones it acts on,
how many hops away, and what the imagined state holds there -- or which
declared number's doubt that nearest call rests on.

`reaches` lists every entity downstream of the acted-on ones along the
couplings the candidate's own rollout crossed, with its hops and each imagined
finding there and the first step it appeared at; an entity reached with nothing
found is listed, because the effect arriving and breaching nothing is an
answer. `decisive` names, at the value and step `margin_sigmas` measured, the
source carrying the largest share of that value's declared variance -- `None`
exactly when `margin_sigmas` is. Neither changes a ranking.
"""

from __future__ import annotations

import math

import pytest

from arbiter_engine import api
from arbiter_engine.twin.rollout import _spread_shares


def _model(sigma=True):
    feeds = ", gain_sigma: 0.002" if sigma else ""
    spills = ", gain_sigma: 0.1" if sigma else ""
    return f"""
domain:
  id: reach_chain
  name: reach chain
  entity_types: [Pump, Tank, Basin, Gauge]
  relationship_types: [feeds, spills, watches]
  indicators:
    Pump:
      - {{name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 4000}}
    Tank:
      - {{name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 85, critical: 95}}
    Basin:
      - {{name: basin_level, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 25, critical: 60}}
    Gauge:
      - {{name: reading, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 100}}
  relationship_rules:
    - {{type: feeds, source_type: Pump, target_type: Tank, transition: {{from: speed_rpm, to: level_pct, gain: 0.02, source: datasheet{feeds}}}}}
    - {{type: spills, source_type: Tank, target_type: Basin, transition: {{from: level_pct, to: basin_level, gain: 0.5, source: datasheet{spills}}}}}
    - {{type: watches, source_type: Pump, target_type: Gauge}}
  action_templates:
    - name: throttle_pump
      applies_to: Pump
      parameters_schema:
        speed_rpm: {{type: number, entity_property: speed_rpm, candidates: [1200, 3000]}}
      effect: set
      source: runbook
  planning: {{objective: expected_findings}}
"""


def _plan(sigma=True):
    """A pump feeding a tank spilling into a basin, and a gauge the pump is
    related to by a relation that declares no transition."""
    session = api.EngineSession()
    session.load_model(_model(sigma))
    session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_entity("basin1", "Basin", {"basin_level": 10.0})
    session.add_entity("gauge1", "Gauge", {"reading": 1.0})
    session.add_relationship("pump1", "feeds", "tank1")
    session.add_relationship("tank1", "spills", "basin1")
    session.add_relationship("pump1", "watches", "gauge1")
    plan = api.plan(session, horizon_s=1800, step_s=300).to_dict()["plan"]
    return {c["plan"].split("@0s")[0]: c for c in plan["candidates"]}


FAST = "throttle_pump@pump1(speed_rpm=3000.0)"
SLOW = "throttle_pump@pump1(speed_rpm=1200.0)"


class TestWhatAnOptionReaches:

    def test_two_hops_down_with_what_is_found_there_and_when(self):
        assert _plan()[FAST]["reaches"] == [
            {"entity": "tank1", "hops": 1, "findings": [
                {"problem_type": "imagined_threshold_warning:level_pct",
                 "first_at_s": 300}]},
            {"entity": "basin1", "hops": 2, "findings": [
                {"problem_type": "imagined_threshold_warning:basin_level",
                 "first_at_s": 300}]}]

    def test_an_entity_reached_with_nothing_found_is_listed(self):
        assert _plan()[SLOW]["reaches"] == [
            {"entity": "tank1", "hops": 1, "findings": []},
            {"entity": "basin1", "hops": 2, "findings": []}]

    def test_a_relation_with_no_transition_carries_nothing_there(self):
        """The gauge is related to the pump, and no declared transition
        crosses that relation, so no option's effect is claimed to reach it."""
        for candidate in _plan().values():
            assert "gauge1" not in {row["entity"] for row in candidate["reaches"]}

    def test_doing_nothing_reaches_nothing(self):
        assert _plan()["do_nothing"]["reaches"] == []

    def test_the_pooled_findings_are_what_the_reach_found(self):
        """The same imagined findings, now placed; none invented, none lost."""
        candidate = _plan()[FAST]
        placed = {f["problem_type"] for row in candidate["reaches"]
                  for f in row["findings"]}
        assert placed == set(candidate["findings"])


class TestWhatDecidesIt:

    def test_it_is_the_coupling_with_the_largest_share_at_the_closest_call(self):
        decisive = _plan()[FAST]["decisive"]
        assert decisive["at"] == "basin1.basin_level"
        assert decisive["source"] == "coupling"
        assert decisive["name"] == "spills:level_pct->basin_level"
        assert decisive["edge"] == "tank1->basin1"
        # 0.1 x 40 against 0.002 x 2000 x 0.5, squared: 16 of 20.
        assert decisive["share"] == pytest.approx(0.8)
        assert decisive["margin_sigmas"] == _plan()[FAST]["margin_sigmas"]

    def test_it_is_null_exactly_when_the_margin_is(self):
        for sigma in (True, False):
            for candidate in _plan(sigma).values():
                assert (candidate["decisive"] is None) == (
                    candidate["margin_sigmas"] is None), candidate["plan"]
        assert all(c["decisive"] is None for c in _plan(False).values())

    def test_neither_field_changes_a_ranking(self, monkeypatch):
        from arbiter_engine.twin import planner
        measured = [(k, c["objective"]) for k, c in _plan().items()]
        monkeypatch.setattr(planner, "_decisive", lambda envelope: None)
        monkeypatch.setattr(planner, "_reaches", lambda envelope, actions: [])
        assert [(k, c["objective"]) for k, c in _plan().items()] == measured


class TestTheSharesOfOneValue:

    def test_they_are_squares_over_their_sum_and_add_to_one(self):
        rows = _spread_shares({
            ("gain", "a", "b", "feeds", 0, "x", "y"): 3.0,
            ("seed", "b", "y"): -4.0}, 25.0)
        assert rows == [
            {"source": "seed", "name": "b.y", "share": pytest.approx(0.64)},
            {"source": "coupling", "name": "feeds:x->y", "edge": "a->b",
             "share": pytest.approx(0.36)}]
        assert math.fsum(row["share"] for row in rows) == pytest.approx(1.0)

    def test_two_keys_for_one_coupling_are_one_row(self):
        rows = _spread_shares({
            ("gain", "a", "b", "feeds", 0, "x", "y"): 3.0,
            ("gain", "a", "b", "feeds", 1, "x", "y"): 4.0}, 25.0)
        assert rows == [{"source": "coupling", "name": "feeds:x->y",
                         "edge": "a->b", "share": pytest.approx(1.0)}]

    def test_a_rollouts_own_output_does_not_carry_them(self):
        session = api.EngineSession()
        session.load_model(_model())
        session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
        session.add_entity("tank1", "Tank", {"level_pct": 50.0})
        session.add_relationship("pump1", "feeds", "tank1")
        steps = api.rollout(session, actions=[
            {"template": "throttle_pump", "entity_id": "pump1",
             "parameters": {"speed_rpm": 3000}, "at_s": 0}],
            horizon_s=600, step_s=300).to_dict()["simulation"]["per_step"]
        assert steps and all("spread_shares" not in step for step in steps)
