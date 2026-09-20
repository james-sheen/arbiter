"""An offset belongs to a COUPLING. Two couplings from one source carry two.

 stopped a declared `offset:` being charged once per movement
of its source, which was right: a rollout walks one group per distinct
movement instant so that two movements superpose, and a constant term added
in every group would settle at `g*(d1+d2) + 2c`. The mechanism it introduced
marks the offset spent in a set the rollout hands to every walk.

THE KEY WAS THE SOURCE PROPERTY:

    charge_key = (source_id, transition.from_property)

which is the right granularity for *the same coupling firing twice* and the
wrong one for *two couplings leaving the same property*. A source property
with two outgoing transitions that both declare an `offset:` is walked in one
pass: the first edge charges its offset and marks the property spent, and the
second edge reads it as spent and charges nothing -- in that step and in every
later one, because the set is rebuilt per step and the edge order recurs.

Measured on the fixture below, `s1.v` moving 1.0 -> 2.0 with `offset: 5.0` to
`t1.w` and `offset: 7.0` to `t2.z`:

  - `traverse` reported `t1.w = 16.0` and `t2.z = 28.0` -- both offsets, no
    `offsets_charged` attribute outside a rollout;
  - the rollout reported `t1.w = 16.0` and `t2.z = 21.0`.

So the two verbs disagreed about `t2.z` by exactly the second offset, and the
rollout was the one that was wrong. The same happened for two `transition:`
blocks on ONE rule that share `from:`, which is the shape a model uses when
one reading drives two properties of the same neighbour.

The fix keys the charge by the coupling -- source, target, relation type, the
transition's position on the edge, and its endpoints -- so `once per coupling`
means what the CHANGELOG already said it meant. The index is in the key
because nothing stops a model declaring two transitions with the same
endpoints on one edge, and two of those are two couplings.

WHAT MUST NOT MOVE: a single coupling walked across two movement instants
still charges one offset. That is the case and
`test_a_second_action_on_a_moved_property_superposes.py` owns it; the floor
below restates it here so this file cannot be satisfied by reverting that one.
"""
from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance

TWO_EDGES = """
domain:
  id: fanout
  name: One source, two offset-bearing couplings
  entity_types: [S, T1, T2]
  relationship_types: [drives_w, drives_z]
  indicators:
    S: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    T1: [{name: w, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    T2: [{name: z, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  action_templates:
    - name: bump
      applies_to: S
      parameters_schema:
        v: {type: number, entity_property: v, candidates: [2.0]}
      effect: set
      settle_s: 0
      source: runbook
  relationship_rules:
    - type: drives_w
      source_type: S
      target_type: T1
      temporal: {propagation_delay_s: 0, time_constant_s: 1,
                 response_model: step}
      transition: {from: v, to: w, gain: 1.0, offset: 5.0, source: datasheet}
    - type: drives_z
      source_type: S
      target_type: T2
      temporal: {propagation_delay_s: 0, time_constant_s: 1,
                 response_model: step}
      transition: {from: v, to: z, gain: 1.0, offset: 7.0, source: datasheet}
"""

ONE_EDGE_TWO_BLOCKS = """
domain:
  id: twoblocks
  name: One rule, two transitions sharing a source property
  entity_types: [S, T]
  relationship_types: [drives]
  indicators:
    S: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    T: [{name: w, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9},
        {name: z, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  action_templates:
    - name: bump
      applies_to: S
      parameters_schema:
        v: {type: number, entity_property: v, candidates: [2.0]}
      effect: set
      settle_s: 0
      source: runbook
  relationship_rules:
    - type: drives
      source_type: S
      target_type: T
      temporal: {propagation_delay_s: 0, time_constant_s: 1,
                 response_model: step}
      transition:
        - {from: v, to: w, gain: 1.0, offset: 5.0, source: datasheet}
        - {from: v, to: z, gain: 1.0, offset: 7.0, source: datasheet}
"""

BASE_V, MOVED_V = 1.0, 2.0
BASE_W, BASE_Z = 10.0, 20.0
OFFSET_W, OFFSET_Z = 5.0, 7.0
GAIN = 1.0
HORIZON_S, STEP_S = 600.0, 60.0

#: Both edges are `step` with a zero delay and a one-second time constant, so
#: every fraction below is 1.0 and the settled value is the whole arithmetic.
SETTLED_W = BASE_W + GAIN * (MOVED_V - BASE_V) + OFFSET_W
SETTLED_Z = BASE_Z + GAIN * (MOVED_V - BASE_V) + OFFSET_Z


def _fanout(tmp_path, name):
    path = tmp_path / f"{name}.yaml"
    path.write_text(TWO_EDGES)
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("s1", "S", {"v": BASE_V})
    session.add_entity("t1", "T1", {"w": BASE_W})
    session.add_entity("t2", "T2", {"z": BASE_Z})
    session.add_relationship("s1", "drives_w", "t1")
    session.add_relationship("s1", "drives_z", "t2")
    return session


def _one_edge(tmp_path, name):
    path = tmp_path / f"{name}.yaml"
    path.write_text(ONE_EDGE_TWO_BLOCKS)
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("s1", "S", {"v": BASE_V})
    session.add_entity("t1", "T", {"w": BASE_W, "z": BASE_Z})
    session.add_relationship("s1", "drives", "t1")
    return session


def _bump(at_s=0.0, value=MOVED_V):
    return ActionInstance("bump", "s1", {"v": value}, at_s)


def _rollout(session, actions=None):
    return api.rollout(
        session, actions=actions if actions is not None else [_bump()],
        horizon_s=HORIZON_S, step_s=STEP_S).to_dict()["simulation"]


def _walk(session):
    return api.traverse(
        session, ["s1"], value_mode="hypothetical",
        overrides={"s1": {"v": MOVED_V}},
        horizon_s=HORIZON_S).to_dict()["simulation"]["values"]


class TestEachCouplingCarriesItsOwnOffset:

    def test_two_edges_from_one_property_both_charge(self, tmp_path):
        last = _rollout(_fanout(tmp_path, "fanout"))["per_step"][-1]["values"]
        assert last["t1"]["w"] == pytest.approx(SETTLED_W), (
            "the first coupling's offset is missing")
        assert last["t2"]["z"] == pytest.approx(SETTLED_Z), (
            f"t2.z settled at {last['t2']['z']}; its own declared offset of "
            f"{OFFSET_Z} says {SETTLED_Z}. An offset marked spent by a "
            f"different coupling is never charged at all.")

    def test_two_transition_blocks_on_one_rule_both_charge(self, tmp_path):
        last = _rollout(_one_edge(tmp_path, "blocks"))["per_step"][-1]["values"]
        assert last["t1"]["w"] == pytest.approx(SETTLED_W)
        assert last["t1"]["z"] == pytest.approx(SETTLED_Z), (
            f"t1.z settled at {last['t1']['z']}; two transitions sharing "
            f"`from: v` are two couplings and carry two offsets")


class TestTheTwoVerbsAgree:
    """`traverse` never had this defect -- it sets no `offsets_charged` -- so
    the two verbs disagreeing is the sharpest statement of the bug, and the
    shape this repository already uses for `check` against `traverse`."""

    def test_rollout_settles_where_traverse_says(self, tmp_path):
        session = _fanout(tmp_path, "agree")
        walked = _walk(session)
        last = _rollout(session)["per_step"][-1]["values"]
        for entity, prop in (("t1", "w"), ("t2", "z")):
            assert last[entity][prop] == pytest.approx(
                walked[entity][prop]["value"]), (
                f"rollout says {last[entity][prop]} for {entity}.{prop} and "
                f"traverse says {walked[entity][prop]['value']}")


class TestTheCaseThatDroveTheOriginalRule:
    """The floor. The case must not come back while this one is fixed:
    ONE coupling, TWO movements, ONE offset."""

    def test_one_coupling_across_two_movements_charges_one_offset(
            self, tmp_path):
        session = _fanout(tmp_path, "floor")
        last = _rollout(session, actions=[
            _bump(0.0, 2.0), _bump(300.0, 3.0)])["per_step"][-1]["values"]
        assert last["t1"]["w"] == pytest.approx(
            BASE_W + GAIN * (3.0 - BASE_V) + OFFSET_W), (
            "a second movement charged the offset again")
        assert last["t2"]["z"] == pytest.approx(
            BASE_Z + GAIN * (3.0 - BASE_V) + OFFSET_Z)
