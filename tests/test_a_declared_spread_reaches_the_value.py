"""A declared spread on a gain becomes an interval on the value it drives.

THE ENGINE HAD NO VALUE-LEVEL UNCERTAINTY AT ALL. Transitions were
deterministic, `Transition.confidence` was never read, and
`clearance_probability` sampled a function returning the same constant every
time -- so the estimate was 0.0 or 1.0 and the 95 % interval collapsed to a
point. It was honestly stamped `deterministic_transitions`, and it was a
boolean wearing a decimal point.

`gain_sigma:` is the declaration that fixes it, and it is a DECLARATION: a
datasheet saying *0.02 per rpm, plus or minus 0.002* has stated one, and
nothing infers it from a correlation or from `confidence`. An edge without one
keeps the old behaviour exactly, which is the compatibility half of this file.

ABSENT IS NOT ZERO. A value nobody declared a spread for carries no `sigma`
key at all rather than `sigma: 0.0` -- because a value with no interval and a
value known to be exact are different claims, and printing 0.0 for both makes
the weaker one look like the stronger.
"""
from __future__ import annotations

import math

import pytest

from arbiter_engine import api

MODEL = """
domain:
  id: spread
  name: A chain with declared spreads
  entity_types: [P, T, D]
  relationship_types: [feeds, drains]
  indicators:
    P: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    T: [{name: w, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    D: [{name: z, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  relationship_rules:
    - {type: feeds, source_type: P, target_type: T,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: v, to: w, gain: 2.0%(s1)s, source: datasheet}}
    - {type: drains, source_type: T, target_type: D,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: w, to: z, gain: 3.0%(s2)s, source: datasheet}}
"""

BASE_V, BASE_W, BASE_Z = 10.0, 100.0, 0.0
MOVED_V = 15.0
DELTA_V = MOVED_V - BASE_V          # 5.0
GAIN_1, GAIN_2 = 2.0, 3.0
SIGMA_1, SIGMA_2 = 0.1, 0.2


def _session(tmp_path, name, s1=f", gain_sigma: {SIGMA_1}",
             s2=f", gain_sigma: {SIGMA_2}"):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL % {"s1": s1, "s2": s2})
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("p1", "P", {"v": BASE_V})
    session.add_entity("t1", "T", {"w": BASE_W})
    session.add_entity("d1", "D", {"z": BASE_Z})
    session.add_relationship("p1", "feeds", "t1")
    session.add_relationship("t1", "drains", "d1")
    return session


def _values(session):
    return api.traverse(session, ["p1"], value_mode="hypothetical",
                        overrides={"p1": {"v": MOVED_V}}
                        ).to_dict()["simulation"]["values"]


class TestTheSpreadReachesTheValue:

    def test_one_hop_carries_the_declared_spread(self, tmp_path):
        got = _values(_session(tmp_path, "hop"))["t1"]["w"]
        assert got["value"] == pytest.approx(BASE_W + GAIN_1 * DELTA_V)
        assert got["sigma"] == pytest.approx(SIGMA_1 * DELTA_V), (
            "a spread on the gain scales by how far the source moved")

    def test_the_interval_is_the_declared_band(self, tmp_path):
        got = _values(_session(tmp_path, "band"))["t1"]["w"]
        low, high = got["interval_95"]
        assert low == pytest.approx(got["value"] - 1.96 * got["sigma"])
        assert high == pytest.approx(got["value"] + 1.96 * got["sigma"])

    def test_a_chain_propagates_to_first_order(self, tmp_path):
        """The delta method, written out rather than read off the engine.

        The second edge contributes its own spread on the change it sees, and
        passes the first edge's spread through its gain. Independent
        declarations add in variance.
        """
        got = _values(_session(tmp_path, "chain"))["d1"]["z"]
        delta_w = GAIN_1 * DELTA_V
        expected = math.sqrt((SIGMA_2 * abs(delta_w)) ** 2
                             + (GAIN_2 * SIGMA_1 * DELTA_V) ** 2)
        assert got["value"] == pytest.approx(BASE_Z + GAIN_2 * delta_w)
        assert got["sigma"] == pytest.approx(expected)

    def test_the_engine_says_the_propagation_is_first_order(self, tmp_path):
        """An interval is the thing a reader most easily takes as exact."""
        assumptions = api.traverse(
            _session(tmp_path, "stamped"), ["p1"], value_mode="hypothetical",
            overrides={"p1": {"v": MOVED_V}}
        ).to_dict()["simulation"]["assumptions"]
        assert "first_order_uncertainty" in assumptions
        assert "independent_declared_spreads" in assumptions


class TestAnUndeclaredSpreadIsAbsentNotZero:

    def test_no_sigma_key_at_all(self, tmp_path):
        got = _values(_session(tmp_path, "none", s1="", s2=""))["t1"]["w"]
        assert "sigma" not in got
        assert "interval_95" not in got

    def test_the_value_is_unchanged(self, tmp_path):
        """Compatibility: a model declaring no spread behaves exactly as before."""
        got = _values(_session(tmp_path, "same", s1="", s2=""))
        assert got["t1"]["w"]["value"] == pytest.approx(
            BASE_W + GAIN_1 * DELTA_V)
        assert got["d1"]["z"]["value"] == pytest.approx(
            BASE_Z + GAIN_2 * GAIN_1 * DELTA_V)

    def test_one_declared_edge_does_not_invent_a_spread_for_the_other(
            self, tmp_path):
        """Only the declared half carries an interval; the chain still gets
        one because the declared spread propagates INTO it."""
        values = _values(_session(tmp_path, "half", s2=""))
        assert "sigma" in values["t1"]["w"]
        assert values["d1"]["z"]["sigma"] == pytest.approx(
            GAIN_2 * SIGMA_1 * DELTA_V), (
            "the second edge declares no spread of its own, so all the "
            "uncertainty at d1 is the first edge's, passed through gain 3.0")


class TestANegativeSpreadIsRefused:

    def test_it_is_reported_rather_than_made_positive(self, tmp_path):
        session = _session(tmp_path, "neg", s1=", gain_sigma: -0.1")
        refused = api.model_describe(session).to_dict()[
            "model"]["transitions"]["refused_blocks"]
        assert refused, "a negative standard deviation was accepted"
        assert any("negative" in str(entry).lower() for entry in refused)


class TestTheRolloutCarriesItToo:

    def test_each_step_reports_the_spread_it_reached(self, tmp_path):
        from arbiter_engine.twin.actions import ActionInstance
        path = tmp_path / "rollout.yaml"
        path.write_text(MODEL % {"s1": f", gain_sigma: {SIGMA_1}", "s2": ""}
                        + """  action_templates:
    - name: push
      applies_to: P
      parameters_schema:
        v: {type: number, entity_property: v}
      effect: set
      settle_s: 0
      source: runbook
""")
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("p1", "P", {"v": BASE_V})
        session.add_entity("t1", "T", {"w": BASE_W})
        session.add_entity("d1", "D", {"z": BASE_Z})
        session.add_relationship("p1", "feeds", "t1")
        session.add_relationship("t1", "drains", "d1")
        per_step = api.rollout(
            session,
            actions=[ActionInstance("push", "p1", {"v": MOVED_V}, 0.0)],
            horizon_s=180.0, step_s=60.0).to_dict()["simulation"]["per_step"]
        assert per_step
        for step in per_step:
            assert step["sigma"]["t1"]["w"] == pytest.approx(
                SIGMA_1 * DELTA_V)
