"""One declared number is one uncertainty, however many ways it reaches you.

The walk adds variances:

    contribution_variance = (gain_sigma *abs(delta_source) *fraction) **2
                            + (gain *fraction) **2 *source_variance

and the rollout adds the walks' variances across movement groups. Adding in
quadrature is the rule for INDEPENDENT contributions, and the engine says so
-- it stamps `independent_declared_spreads`. That stamp is true of two
DIFFERENT couplings each carrying their own `gain_sigma:`. It is false of ONE
coupling reached twice, and there are three ways to reach one twice:

  1. TWO MOVEMENTS OF ONE SOURCE. The rollout walks one group per movement
     instant, and the same `gain_sigma` fires in each. Measured on the pump
     and tank below, `+500` then `+100` rpm with `gain_sigma: 0.002`: the
     tank settled with a spread of 1.0198 where the one declared number says
     1.2. Two equal movements give the factor sqrt(2), 29 % narrow.
  2. TWO PATHS TO ONE TARGET. Inside a SINGLE walk: a spread on `S -> A`
     reaches `T` directly and again through `M`, so `T = A + M = 2A` and its
     spread is `2 *sigma_A`. Measured: 14.142 where the declaration says 20.
     This one is not a rollout defect -- `traverse` reports it too.
  3. A SEEDED PROPERTY THAT IS THEN PINNED. The seed's own movement and the
     action that overrides it both carry the forecast's doubt, with OPPOSITE
     signs, because the action's delta is measured FROM the seeded value.

THE SIGN IS THE WHOLE OF IT, and it is what makes `sum the absolute values`
wrong as well. The contribution of one declared spread to a target is
`sigma_g *SUM_k (delta_k *f_k)` -- the absolute value of a SIGNED sum, not
the sum of absolute values. The two agree only when every movement pushes the
same way. Move a source up by 500 and then back down by 500 and the target
returns to its baseline: it is where it started for ANY value of the gain, so
the gain's spread cannot reach it at all and the true answer is zero.
Measured before this fix: 1.4142, and summing absolute values would have
reported 2.0 -- FURTHER from the truth than the defect it replaced.

THE FIX carries a signed contribution per independent source rather than one
pooled variance: each declared `gain_sigma:` is a source, each forecast seed
is a source, contributions from one source add linearly wherever they meet,
and the squares are taken once at the end. For a tree with one movement this
is arithmetically what it replaced, which is why the floors below matter as
much as the cases above: independence is still the right rule BETWEEN
declarations, and this must not start pooling those.
"""
from __future__ import annotations

import math

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance

PUMP_TANK = """
domain:
  id: onespread
  name: One gain sigma, several movements
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump: [{name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS],
            critical: 9e9}]
    Tank: [{name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS],
            critical: 9e9}]
  action_templates:
    - name: throttle
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm,
                    candidates: [1500]}
      effect: set
      settle_s: 0
      source: runbook
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 1,
                 response_model: step}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                   gain_sigma: 0.002, source: datasheet}
"""

DIAMOND = """
domain:
  id: diamond
  name: One spread, two paths to one target
  entity_types: [S, A, M, T]
  relationship_types: [sa, at, am, mt]
  indicators:
    S: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    A: [{name: a, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    M: [{name: m, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    T: [{name: w, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  relationship_rules:
    - {type: sa, source_type: S, target_type: A,
       temporal: {propagation_delay_s: 0, time_constant_s: 1,
                  response_model: step},
       transition: {from: v, to: a, gain: 1.0, gain_sigma: 0.1,
                    source: datasheet}}
    - {type: at, source_type: A, target_type: T,
       temporal: {propagation_delay_s: 0, time_constant_s: 1,
                  response_model: step},
       transition: {from: a, to: w, gain: 1.0, source: datasheet}}
    - {type: am, source_type: A, target_type: M,
       temporal: {propagation_delay_s: 0, time_constant_s: 1,
                  response_model: step},
       transition: {from: a, to: m, gain: 1.0, source: datasheet}}
    - {type: mt, source_type: M, target_type: T,
       temporal: {propagation_delay_s: 0, time_constant_s: 1,
                  response_model: step},
       transition: {from: m, to: w, gain: 1.0, source: datasheet}}
"""

TWO_COUPLINGS = """
domain:
  id: twosources
  name: Two declarations, one target
  entity_types: [P, Q, T]
  relationship_types: [pt, qt]
  indicators:
    P: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    Q: [{name: u, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    T: [{name: w, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  relationship_rules:
    - {type: pt, source_type: P, target_type: T,
       temporal: {propagation_delay_s: 0, time_constant_s: 1,
                  response_model: step},
       transition: {from: v, to: w, gain: 1.0, gain_sigma: 0.1,
                    source: datasheet}}
    - {type: qt, source_type: Q, target_type: T,
       temporal: {propagation_delay_s: 0, time_constant_s: 1,
                  response_model: step},
       transition: {from: u, to: w, gain: 1.0, gain_sigma: 0.1,
                    source: datasheet}}
"""

BASE_SPEED, BASE_LEVEL = 1000.0, 50.0
GAIN, GAIN_SIGMA = 0.02, 0.002
HORIZON_S, STEP_S = 1200.0, 60.0
SECOND_AT = 600.0


def _pump_tank(tmp_path, name):
    path = tmp_path / f"{name}.yaml"
    path.write_text(PUMP_TANK)
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": BASE_SPEED})
    session.add_entity("tank1", "Tank", {"level_pct": BASE_LEVEL})
    session.add_relationship("pump1", "feeds", "tank1")
    return session


def _throttle(at_s, rpm):
    return ActionInstance("throttle", "pump1", {"speed_rpm": rpm}, at_s)


def _settled_sigma(session, actions):
    last = api.rollout(session, actions=actions, horizon_s=HORIZON_S,
                       step_s=STEP_S).to_dict()["simulation"]["per_step"][-1]
    return last["sigma"].get("tank1", {}).get("level_pct", 0.0)


class TestTwoMovementsOfOneSource:
    """Every edge below is `step` with a one-second constant, so every
    response fraction at the last step is 1.0 and the closed form is just the
    declared spread times the net displacement."""

    def test_two_movements_the_same_way_add_linearly(self, tmp_path):
        got = _settled_sigma(_pump_tank(tmp_path, "same"),
                             [_throttle(0.0, 1500.0),
                              _throttle(SECOND_AT, 1600.0)])
        assert got == pytest.approx(GAIN_SIGMA * 600.0, abs=1e-9), (
            f"the tank's spread is {got}; ONE declared gain_sigma over a net "
            f"movement of 600 rpm says {GAIN_SIGMA * 600.0}. Quadrature "
            f"would say {GAIN_SIGMA * math.sqrt(500 ** 2 + 100 ** 2)}.")

    def test_two_equal_movements_do_not_gain_a_root_two(self, tmp_path):
        got = _settled_sigma(_pump_tank(tmp_path, "equal"),
                             [_throttle(0.0, 1300.0),
                              _throttle(SECOND_AT, 1600.0)])
        assert got == pytest.approx(GAIN_SIGMA * 600.0, abs=1e-9)

    def test_a_source_moved_back_where_it_started_carries_no_spread(
            self, tmp_path):
        """The case that decides between a signed sum and a sum of absolute
        values. The tank returns to its baseline for ANY gain, so the gain's
        spread cannot reach it."""
        session = _pump_tank(tmp_path, "revert")
        actions = [_throttle(0.0, 1500.0), _throttle(SECOND_AT, BASE_SPEED)]
        last = api.rollout(
            session, actions=actions, horizon_s=HORIZON_S,
            step_s=STEP_S).to_dict()["simulation"]["per_step"][-1]
        assert last["values"]["tank1"]["level_pct"] == pytest.approx(
            BASE_LEVEL, abs=1e-9), "the premise: the tank is back at baseline"
        assert last["sigma"].get("tank1", {}).get("level_pct", 0.0) == (
            pytest.approx(0.0, abs=1e-9)), (
            "a target sitting exactly where it started cannot carry a spread "
            "that scales with how far its source moved")


class TestOneSpreadReachingOneTargetTwice:

    def _diamond(self, tmp_path):
        path = tmp_path / "diamond.yaml"
        path.write_text(DIAMOND)
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("s1", "S", {"v": 10.0})
        session.add_entity("a1", "A", {"a": 0.0})
        session.add_entity("m1", "M", {"m": 0.0})
        session.add_entity("t1", "T", {"w": 0.0})
        session.add_relationship("s1", "sa", "a1")
        session.add_relationship("a1", "at", "t1")
        session.add_relationship("a1", "am", "m1")
        session.add_relationship("m1", "mt", "t1")
        return session

    def test_a_spread_arriving_by_two_paths_adds_linearly(self, tmp_path):
        values = api.traverse(
            self._diamond(tmp_path), ["s1"], value_mode="hypothetical",
            overrides={"s1": {"v": 110.0}},
            horizon_s=600.0).to_dict()["simulation"]["values"]
        assert values["a1"]["a"]["value"] == pytest.approx(100.0)
        assert values["t1"]["w"]["value"] == pytest.approx(200.0), (
            "the premise: the VALUES superpose, T = A + M")
        sigma_a = values["a1"]["a"]["sigma"]
        assert sigma_a == pytest.approx(10.0)
        assert values["t1"]["w"]["sigma"] == pytest.approx(
            2 * sigma_a, abs=1e-9), (
            f"T is 2A, so its spread is twice A's. Quadrature says "
            f"{sigma_a * math.sqrt(2)}.")


LAGGED_SEED = """
domain:
  id: lagseed
  name: A forecast pinned by a setting, through a lag
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 4h, lookback: 24h, dynamics: {model: random_walk}}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 4h, lookback: 24h}
  action_templates:
    - name: throttle
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm,
                    candidates: [2500]}
      effect: set
      settle_s: 0
      source: runbook
  relationship_rules:
    - {type: feeds, source_type: Pump, target_type: Tank,
       temporal: {propagation_delay_s: 0, time_constant_s: 900,
                  response_model: exponential},
       transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                    source: datasheet}}
"""

TAU = 900.0
ACT_AT = 1800.0


def _f(elapsed):
    return 0.0 if elapsed <= 0 else 1.0 - math.exp(-elapsed / TAU)


class TestASeedPinnedByASettingLosesItsDoubtOnTheEdgesClock:
    """The sharpest case for the sign, because the two contributions cancel
    only as far as the response has developed.

    A `set` pins the property, so the forecast's doubt reaches the target
    through `f(t)` from the seed's movement and back out through
    `f(t - t_act)` from the action's -- one forecast, two movements, opposite
    signs. The band therefore RISES to the intervention and decays to nothing
    as the lag catches up, which is the physical answer: once the response
    has fully developed, the tank depends on the pinned 2500 rpm alone and
    where the forecast had the pump stops mattering.
    """

    def _session(self, tmp_path):
        import random
        from datetime import timedelta
        path = tmp_path / "lagseed.yaml"
        path.write_text(LAGGED_SEED)
        session = api.EngineSession()
        session.load_model(str(path))
        rng = random.Random(5)
        value, values = 2000.0, []
        for _ in range(200):
            value += rng.gauss(0.0, 25.0)
            values.append(value)
        session.add_entity("pump1", "Pump", {"speed_rpm": values[-1]})
        session.add_entity("tank1", "Tank", {"level_pct": 50.0})
        session.add_relationship("pump1", "feeds", "tank1")
        now = api.now_utc()
        for k, sample in enumerate(values):
            session.add_observations(
                "pump1", "speed_rpm",
                [(now - timedelta(seconds=60 * (len(values) - k)), sample)])
        return session

    def _steps(self, tmp_path):
        return api.rollout(
            self._session(tmp_path),
            actions=[ActionInstance("throttle", "pump1",
                                    {"speed_rpm": 2500.0}, ACT_AT)],
            horizon_s=7200.0, step_s=600.0,
            seed_mode="projected").to_dict()["simulation"]["per_step"]

    def test_the_band_follows_the_two_sided_closed_form(self, tmp_path):
        steps = self._steps(tmp_path)
        #: A random walk's spread grows as sqrt(t), so the value frozen at the
        #: intervention is read off an earlier step and scaled.
        before = [s for s in steps if s["at_s"] < ACT_AT]
        assert before, "the fixture must have steps before the action"
        sample = before[-1]
        frozen = sample["sigma"]["pump1"]["speed_rpm"] * math.sqrt(
            ACT_AT / sample["at_s"])
        for step in steps:
            at_s = step["at_s"]
            if at_s < ACT_AT:
                continue
            want = GAIN * abs(_f(at_s) - _f(at_s - ACT_AT)) * frozen
            got = step["sigma"].get("tank1", {}).get("level_pct", 0.0)
            assert got == pytest.approx(want, rel=1e-9), (
                f"at {at_s}s the tank's band is {got}; one forecast reaching "
                f"it through two movements of opposite sign says {want}")

    def test_the_band_decays_after_the_intervention(self, tmp_path):
        """The shape on its own, independent of the closed form."""
        after = [s["sigma"].get("tank1", {}).get("level_pct", 0.0)
                 for s in self._steps(tmp_path) if s["at_s"] > ACT_AT]
        assert after and all(b < a for a, b in zip(after, after[1:])), (
            f"the band did not decay once the property was pinned: {after}")

    def test_the_pinned_property_reports_no_band_of_its_own(self, tmp_path):
        for step in self._steps(tmp_path):
            if step["at_s"] < ACT_AT:
                continue
            assert not step["sigma"].get("pump1", {}).get("speed_rpm"), (
                "the pump was SET; a pinned value cannot carry the forecast's "
                "doubt")


class TestIndependenceIsStillTheRuleBetweenDeclarations:
    """The floor. Two different `gain_sigma:` lines are two different claims
    by the author and DO add in quadrature; a fix that pooled them would be
    the same error in the other direction."""

    def test_two_couplings_with_their_own_spreads_add_in_quadrature(
            self, tmp_path):
        path = tmp_path / "two.yaml"
        path.write_text(TWO_COUPLINGS)
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("p1", "P", {"v": 10.0})
        session.add_entity("q1", "Q", {"u": 10.0})
        session.add_entity("t1", "T", {"w": 0.0})
        session.add_relationship("p1", "pt", "t1")
        session.add_relationship("q1", "qt", "t1")
        values = api.traverse(
            session, ["p1", "q1"], value_mode="hypothetical",
            overrides={"p1": {"v": 110.0}, "q1": {"u": 110.0}},
            horizon_s=600.0).to_dict()["simulation"]["values"]
        assert values["t1"]["w"]["value"] == pytest.approx(200.0)
        assert values["t1"]["w"]["sigma"] == pytest.approx(
            10.0 * math.sqrt(2), abs=1e-9), (
            "two independent declared spreads still add in quadrature")


TWO_PUMPS = """
domain:
  id: twopumps
  name: Two pumps under one rule, one tank
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump: [{name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS],
            critical: 9e9}]
    Tank: [{name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS],
            critical: 9e9}]
  action_templates:
    - name: throttle
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm,
                    candidates: [1500]}
      effect: set
      settle_s: 0
      source: runbook
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 1,
                 response_model: step}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                   gain_sigma: 0.002, source: datasheet}
"""


class TestTwoEntitiesUnderOneRuleAreTwoCouplings:
    """The other half of the rule, and a judgement rather than an accident.

    One `gain_sigma:` line under one relationship rule instantiates a
    coupling per pair of entities it matches. Those are DIFFERENT couplings:
    the datasheet tolerance describes a population and each pump is its own
    draw from it, so their spreads are independent and add in quadrature.
    Only the same coupling reached twice adds linearly. Pinned because the
    fix above could plausibly have pooled these too, which would be the same
    error pointing the other way.
    """

    def _session(self, tmp_path):
        path = tmp_path / "twopumps.yaml"
        path.write_text(TWO_PUMPS)
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("pumpA", "Pump", {"speed_rpm": BASE_SPEED})
        session.add_entity("pumpB", "Pump", {"speed_rpm": BASE_SPEED})
        session.add_entity("tank1", "Tank", {"level_pct": BASE_LEVEL})
        session.add_relationship("pumpA", "feeds", "tank1")
        session.add_relationship("pumpB", "feeds", "tank1")
        return session

    def _last(self, tmp_path, entities):
        actions = [ActionInstance("throttle", eid, {"speed_rpm": 1500.0}, 0.0)
                   for eid in entities]
        return api.rollout(
            self._session(tmp_path), actions=actions, horizon_s=HORIZON_S,
            step_s=STEP_S).to_dict()["simulation"]["per_step"][-1]

    def test_one_pump_carries_one_spread(self, tmp_path):
        last = self._last(tmp_path, ["pumpA"])
        assert last["values"]["tank1"]["level_pct"] == pytest.approx(
            BASE_LEVEL + GAIN * 500.0)
        assert last["sigma"]["tank1"]["level_pct"] == pytest.approx(
            GAIN_SIGMA * 500.0, abs=1e-9)

    def test_two_pumps_add_in_quadrature(self, tmp_path):
        last = self._last(tmp_path, ["pumpA", "pumpB"])
        assert last["values"]["tank1"]["level_pct"] == pytest.approx(
            BASE_LEVEL + 2 * GAIN * 500.0), "the premise: both drove it"
        assert last["sigma"]["tank1"]["level_pct"] == pytest.approx(
            GAIN_SIGMA * 500.0 * math.sqrt(2), abs=1e-9), (
            "two pumps are two couplings and two gains; pooling them would "
            "be the linear rule applied where independence is right")


class TestTheSingleMovementCaseIsUnchanged:
    """The regression floor: one movement through one coupling is what the
    package already measured, and this rewrite must leave it alone."""

    def test_one_movement_reports_the_declared_spread(self, tmp_path):
        got = _settled_sigma(_pump_tank(tmp_path, "single"),
                             [_throttle(0.0, 1500.0)])
        assert got == pytest.approx(GAIN_SIGMA * 500.0, abs=1e-9)

    def test_the_stamp_still_says_what_it_assumes(self, tmp_path):
        simulation = api.rollout(
            _pump_tank(tmp_path, "stamp"), actions=[_throttle(0.0, 1500.0)],
            horizon_s=HORIZON_S, step_s=STEP_S).to_dict()["simulation"]
        assert "first_order_uncertainty" in simulation["assumptions"]
