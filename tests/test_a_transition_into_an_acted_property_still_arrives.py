"""A transition into a property an action also moved still arrives.

MODELING.md says an action is converted to a DELTA so that it composes with
the transitions arriving at the same property, through the one superposition
rule the walk already applies. The rollout does not do that for a property
that is BOTH a transition target and an action target: `rollout.py` skips
every transition contribution into a property that appears in `movements`,
and the drift reconciliation then folds whatever had already arrived into the
property's latest movement -- which propagates it downstream a second time.

Measured on the tree this file was written against (0.2.5.dev0):

  pump SET 1500 @0s + tank ADD +5 @0s, step response, gain 0.02
      expected 65.0, reported 55.0, `transitions_applied: 5`, nothing declined
  pump SET 1500 @0s, tank ADD +5 @600s, 120 s / 600 s exponential
      tank froze at 60.03 from t=600 on; declared 64.97 at t=3600
      the declared `gain_sigma:` stopped reaching the tank from t=600 on
  chain pump -> tank -> sump, same actions
      sump 30.00 at t=3600 against 24.97: the 5.03 the tank had received
      before the action was carried downstream twice

Every case reports the transition as applied and declines nothing, which is
the accepted-and-silently-not-applied shape this module's own comments name
as worse than a refusal. `plan` reaches it whenever an `action_templates:`
entry writes a property that is also a transition's `to:`.
"""
from __future__ import annotations

import math

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance

MODEL = """
domain:
  id: acted_target
  name: A transition into a property an action also moves
  entity_types: [Pump, Tank, Sump]
  relationship_types: [feeds, drains_to]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS],
         lower_critical: 100, critical: 4000}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS],
         warning: 85, critical: 95}
    Sump:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS],
         warning: 85, critical: 95}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: %(delay)s, time_constant_s: %(tau)s,
                 response_model: %(model)s}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                   source: datasheet, gain_sigma: 0.002}
    - type: drains_to
      source_type: Tank
      target_type: Sump
      temporal: {propagation_delay_s: 0, time_constant_s: 1,
                 response_model: step}
      transition: {from: level_pct, to: level_pct, gain: 1.0,
                   source: datasheet}
  action_templates:
    - name: throttle_pump
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm}
      effect: set
      source: runbook
    - name: top_up_tank
      applies_to: Tank
      parameters_schema:
        level_pct: {type: number, entity_property: level_pct}
      effect: add
      source: runbook
"""


def _session(tmp_path, *, delay=0, tau=1, model="step", sump=False):
    path = tmp_path / "acted_target.yaml"
    path.write_text(MODEL % {"delay": delay, "tau": tau, "model": model})
    s = api.EngineSession()
    s.load_model(str(path))
    s.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
    s.add_entity("tank1", "Tank", {"level_pct": 50.0})
    s.add_relationship("pump1", "feeds", "tank1")
    if sump:
        s.add_entity("sump1", "Sump", {"level_pct": 10.0})
        s.add_relationship("tank1", "drains_to", "sump1")
    return s


def _throttle(rpm, at_s=0.0):
    return ActionInstance("throttle_pump", "pump1", {"speed_rpm": rpm}, at_s)


def _top_up(delta, at_s=0.0):
    return ActionInstance("top_up_tank", "tank1", {"level_pct": delta}, at_s)


def _fraction(t, delay=120.0, tau=600.0):
    return 0.0 if t < delay else 1.0 - math.exp(-(t - delay) / tau)


class TestTheTwoContributionsSuperpose:

    @pytest.mark.parametrize("actions", [
        [_throttle(1500.0, 0.0), _top_up(5.0, 0.0)],
        [_top_up(5.0, 0.0), _throttle(1500.0, 120.0)],
    ], ids=["same instant", "tank first, pump later"])
    def test_a_step_transition_and_an_add_both_reach_the_tank(
            self, tmp_path, actions):
        simulation = api.rollout(
            _session(tmp_path), actions=actions,
            horizon_s=300.0, step_s=60.0).to_dict()["simulation"]
        final = simulation["per_step"][-1]["values"]["tank1"]["level_pct"]
        # 50 + 0.02 * 500 + 5
        assert final == pytest.approx(65.0)

    def test_the_transient_keeps_developing_after_the_action(self, tmp_path):
        simulation = api.rollout(
            _session(tmp_path, delay=120, tau=600, model="exponential"),
            actions=[_throttle(1500.0, 0.0), _top_up(5.0, 600.0)],
            horizon_s=3600.0, step_s=60.0).to_dict()["simulation"]
        for step in simulation["per_step"]:
            t = step["at_s"]
            expected = 50.0 + 10.0 * _fraction(t) + (5.0 if t >= 600 else 0.0)
            assert step["values"]["tank1"]["level_pct"] == pytest.approx(
                expected, abs=1e-6), f"at t={t}"

    def test_the_declared_spread_still_reaches_the_tank_after_the_action(
            self, tmp_path):
        simulation = api.rollout(
            _session(tmp_path, delay=120, tau=600, model="exponential"),
            actions=[_throttle(1500.0, 0.0), _top_up(5.0, 600.0)],
            horizon_s=3600.0, step_s=60.0).to_dict()["simulation"]
        last = simulation["per_step"][-1]
        # gain_sigma * delta * fraction: an `add` neither depends on the gain
        # nor removes the gain's doubt from the value the coupling drives.
        assert last["sigma"]["tank1"]["level_pct"] == pytest.approx(
            0.002 * 500.0 * _fraction(3600.0), abs=1e-6)


class TestNothingIsCountedTwiceDownstream:

    def test_the_sump_carries_the_tank_exactly_once(self, tmp_path):
        simulation = api.rollout(
            _session(tmp_path, delay=120, tau=600, model="exponential",
                     sump=True),
            actions=[_throttle(1500.0, 0.0), _top_up(5.0, 600.0)],
            horizon_s=3600.0, step_s=60.0).to_dict()["simulation"]
        last = simulation["per_step"][-1]
        tank = last["values"]["tank1"]["level_pct"]
        sump = last["values"]["sump1"]["level_pct"]
        # unit gain, step response: the sump moves by exactly what the tank
        # moved, and by nothing the tank did not.
        assert sump - 10.0 == pytest.approx(tank - 50.0, abs=1e-6)
        assert sump == pytest.approx(10.0 + 10.0 * _fraction(3600.0) + 5.0,
                                     abs=1e-6)


class TestOrAtLeastSaySo:
    """If the engine cannot superpose the two, the accepted-and-dropped
    shape is the one thing it must not do: the transition into the acted
    property must be refused by name rather than reported as applied."""

    def test_an_unapplied_transition_is_not_reported_as_applied(
            self, tmp_path):
        simulation = api.rollout(
            _session(tmp_path),
            actions=[_throttle(1500.0, 0.0), _top_up(5.0, 0.0)],
            horizon_s=300.0, step_s=60.0).to_dict()["simulation"]
        final = simulation["per_step"][-1]["values"]["tank1"]["level_pct"]
        applied = simulation["checked"]["transitions_applied"]
        declined = {d["reason"] for d in simulation["not_checked"]}
        arrived = final == pytest.approx(65.0)
        assert arrived or (applied == 0 and declined), (
            f"tank at {final}, transitions_applied={applied}, "
            f"declines={sorted(declined)}: the coupling was reported as "
            f"applied, its contribution never arrived, and nothing said so")
