"""An action on a property the couplings also drive reads the value that
property actually has, at the instant the action lands.

`set` and `scale` are the two effects whose delta DEPENDS on where
the property was: `set X` moves it by `X - standing` and `scale k` by
`standing *(k - 1)`. When the property is also a transition's `to:`, what it
is standing at includes whatever the couplings have delivered -- and the
rollout resolved the delta against the state written at the END OF THE
PREVIOUS STEP, while the state it then wrote used what the couplings had
delivered by THIS one.

Two clocks, one subtraction. Measured on a tank a pump fills through
`gain 0.02` under a 600 s exponential edge, the tank SET to 20 at t=600:

    step_s tank reported at t=600 declared
      300 22.3865 20.0
       60 20.3869 20.0
       20 20.1247 20.0

The error is exactly `10 *(f(600) - f(600 - step_s))` -- one step's worth of
the coupling's delivery, counted twice -- and it shrinks with the step, which
is the signature of a discretisation artefact in a module whose whole design
is that it has none: the rollout re-runs the walk at `elapsed = t - t_moved`
rather than stepping an accumulator, and that is why a single-action transient
matches the declared closed form to 0.0 at every step.

`add` is immune -- its delta does not read the standing value -- which is why
no test caught this: NO shipped test has an `action_templates:` entry whose
`applies_to` entity is a transition's target. That is the same gap that hid
the dropped-contribution defect this file's sibling covers.

THE DOUBT TRAVELS WITH THE VALUE. A `set` pins the property, so the doubt the
couplings had put into it is gone and only LATER arrivals are still in doubt.
A `scale k` multiplies what is standing, so it multiplies that doubt too. This
is the treatment the seeded-forecast band has had since (`set` leaves
none, `add` leaves all of it, `scale k` leaves k times it); a contribution that
arrived through a declared `gain_sigma:` is the same kind of quantity and gets
the same treatment.
"""
from __future__ import annotations

import math

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance

TAU = 600.0
GAIN, GAIN_SIGMA, SWING = 0.02, 0.002, 500.0
#: What the pump's swing is worth at the tank, once fully arrived.
REACH = GAIN * SWING                      # 10.0
REACH_SIGMA = GAIN_SIGMA * SWING          # 1.0

MODEL = """
domain:
  id: acted_and_coupled
  name: An action on a property a coupling also drives
  entity_types: [Pump, Tank, Sump]
  relationship_types: [feeds, drains_to]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 1e9}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 1e9}
    Sump:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 1e9}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 600,
                 response_model: exponential}
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
    - name: set_tank
      applies_to: Tank
      parameters_schema:
        level_pct: {type: number, entity_property: level_pct}
      effect: set
      source: runbook
    - name: top_up_tank
      applies_to: Tank
      parameters_schema:
        level_pct: {type: number, entity_property: level_pct}
      effect: add
      source: runbook
    - name: scale_tank
      applies_to: Tank
      parameters_schema:
        level_pct: {type: number, entity_property: level_pct}
      effect: scale
      source: runbook
"""


def _fraction(t: float) -> float:
    """The declared edge's own curve, written out once."""
    return 0.0 if t < 0 else 1.0 - math.exp(-t / TAU)


def _session(tmp_path, *, sump=False):
    path = tmp_path / "acted_and_coupled.yaml"
    path.write_text(MODEL)
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_relationship("pump1", "feeds", "tank1")
    if sump:
        session.add_entity("sump1", "Sump", {"level_pct": 10.0})
        session.add_relationship("tank1", "drains_to", "sump1")
    return session


def _run(tmp_path, actions, *, step_s=300.0, horizon_s=1800.0, sump=False):
    return api.rollout(_session(tmp_path, sump=sump), actions=actions,
                       horizon_s=horizon_s,
                       step_s=step_s).to_dict()["simulation"]


def _throttle(at_s=0.0):
    return ActionInstance("throttle_pump", "pump1", {"speed_rpm": 1500.0}, at_s)


def _at(simulation, t):
    for step in simulation["per_step"]:
        if step["at_s"] == pytest.approx(t):
            return step
    raise AssertionError(f"no step at t={t} in "
                         f"{[s['at_s'] for s in simulation['per_step']]}")


def _level(step):
    return step["values"]["tank1"]["level_pct"]


def _sigma(step):
    return step["sigma"].get("tank1", {}).get("level_pct")


class TestThePremise:
    """If the pump stops reaching the tank, every measurement below is about
    nothing and should say so rather than pass."""

    def test_the_coupling_alone_follows_the_declared_curve(self, tmp_path):
        simulation = _run(tmp_path, [_throttle()])
        for step in simulation["per_step"]:
            assert _level(step) == pytest.approx(
                50.0 + REACH * _fraction(step["at_s"]), abs=1e-6)

    def test_the_coupling_alone_carries_the_declared_doubt(self, tmp_path):
        simulation = _run(tmp_path, [_throttle()])
        assert _sigma(_at(simulation, 1800.0)) == pytest.approx(
            REACH_SIGMA * _fraction(1800.0), abs=1e-6)


class TestASetLandsOnTheValueItWasGiven:

    @pytest.mark.parametrize("step_s", [300.0, 60.0, 20.0])
    def test_at_the_instant_of_the_action_whatever_the_step(
            self, tmp_path, step_s):
        """The one number a caller can check without arithmetic: a `set 20`
        means the property reads 20. The error this pins was
        `REACH * (f(600) - f(600 - step_s))`, so it hid at a fine step and
        grew with a coarse one -- and step_s is the caller's to choose."""
        simulation = _run(tmp_path, [
            _throttle(),
            ActionInstance("set_tank", "tank1", {"level_pct": 20.0}, 600.0),
        ], step_s=step_s)
        assert _level(_at(simulation, 600.0)) == pytest.approx(20.0, abs=1e-6)

    def test_and_the_coupling_keeps_arriving_afterwards(self, tmp_path):
        """A `set` is not a freeze. The pump is still running, so what it has
        yet to deliver still arrives -- and only what it has yet to deliver."""
        simulation = _run(tmp_path, [
            _throttle(),
            ActionInstance("set_tank", "tank1", {"level_pct": 20.0}, 600.0),
        ])
        for step in simulation["per_step"]:
            t = step["at_s"]
            if t < 600.0:
                continue
            assert _level(step) == pytest.approx(
                20.0 + REACH * (_fraction(t) - _fraction(600.0)),
                abs=1e-6), f"at t={t}"

    def test_the_doubt_it_pinned_away_does_not_come_back(self, tmp_path):
        """At the instant of the `set` the tank is the number asked for, so
        nothing about it is in doubt; from there on it is in doubt only by
        what the coupling has still to deliver."""
        simulation = _run(tmp_path, [
            _throttle(),
            ActionInstance("set_tank", "tank1", {"level_pct": 20.0}, 600.0),
        ])
        assert (_sigma(_at(simulation, 600.0)) or 0.0) == pytest.approx(
            0.0, abs=1e-9)
        assert _sigma(_at(simulation, 1800.0)) == pytest.approx(
            REACH_SIGMA * (_fraction(1800.0) - _fraction(600.0)), abs=1e-6)


class TestAScaleMultipliesWhatIsStanding:

    def test_the_value_doubles_what_had_arrived_by_then(self, tmp_path):
        simulation = _run(tmp_path, [
            _throttle(),
            ActionInstance("scale_tank", "tank1", {"level_pct": 2.0}, 600.0),
        ])
        standing = 50.0 + REACH * _fraction(600.0)
        for step in simulation["per_step"]:
            t = step["at_s"]
            if t < 600.0:
                continue
            assert _level(step) == pytest.approx(
                2.0 * standing + REACH * (_fraction(t) - _fraction(600.0)),
                abs=1e-6), f"at t={t}"

    def test_and_so_does_the_doubt(self, tmp_path):
        """The declared gain drove `2 x REACH x f(600)` of this level through
        the scale, and `REACH x (f(t) - f(600))` directly. One declared
        number, so the two add rather than combining in quadrature."""
        simulation = _run(tmp_path, [
            _throttle(),
            ActionInstance("scale_tank", "tank1", {"level_pct": 2.0}, 600.0),
        ])
        step = _at(simulation, 1800.0)
        assert _sigma(step) == pytest.approx(
            REACH_SIGMA * (2.0 * _fraction(600.0)
                           + (_fraction(1800.0) - _fraction(600.0))),
            abs=1e-6)


class TestAnAddIsUnchanged:
    """The effect whose delta does not read the standing value. Pinned so the
    fix for the two that do cannot move the one that does not."""

    def test_the_value_superposes(self, tmp_path):
        simulation = _run(tmp_path, [
            _throttle(),
            ActionInstance("top_up_tank", "tank1", {"level_pct": 5.0}, 600.0),
        ])
        for step in simulation["per_step"]:
            t = step["at_s"]
            assert _level(step) == pytest.approx(
                50.0 + REACH * _fraction(t) + (5.0 if t >= 600.0 else 0.0),
                abs=1e-6), f"at t={t}"

    def test_the_doubt_is_the_couplings_alone(self, tmp_path):
        simulation = _run(tmp_path, [
            _throttle(),
            ActionInstance("top_up_tank", "tank1", {"level_pct": 5.0}, 600.0),
        ])
        assert _sigma(_at(simulation, 1800.0)) == pytest.approx(
            REACH_SIGMA * _fraction(1800.0), abs=1e-6)


class TestWhatTheActedPropertyHandsOn:
    """The acted property is also a source. Whatever the action did to its
    value, the downstream edge carries that and nothing else."""

    def test_a_set_hands_the_sump_the_level_the_tank_has(self, tmp_path):
        simulation = _run(tmp_path, [
            _throttle(),
            ActionInstance("set_tank", "tank1", {"level_pct": 20.0}, 600.0),
        ], sump=True)
        step = _at(simulation, 1800.0)
        tank = _level(step)
        sump = step["values"]["sump1"]["level_pct"]
        # unit gain, step response: the sump moved by what the tank moved,
        # and by nothing the tank did not.
        assert sump - 10.0 == pytest.approx(tank - 50.0, abs=1e-6)
