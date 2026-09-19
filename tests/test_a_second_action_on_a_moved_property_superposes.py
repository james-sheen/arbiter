"""Two movements of one property develop along their own clocks.

`moved_at` held ONE instant per `(entity, property)` -- the latest
action's -- while `state` held the cumulative delta. So a property that moved
at t1 and again at t2 was walked once, as though the whole `d1 + d2` had
arrived at t2:

    (d1 + d2) *f(t - t2) instead of d1 *f(t - t1) + d2 *f(t - t2)

The engine stamps `linear_superposition` on every simulating walk. This is the
one place it did not hold, and the direction it fails in is the loud one: the
progress the first movement had already made is thrown away and the trajectory
DROPS BACK TO ITS BASELINE the moment the second action fires.

Measured on the shipped `pump_tank_dynamics` shape (120 s dead time, 600 s
time constant), +500 rpm at t=0 and +100 rpm at t=1800: the tank reached 59.33
and fell to exactly 50.00 at t=1800, worst error -9.50 at t=1920, rejoining
the declared curve only as both responses saturated. The steady state was
always right, which is why a test that checks the end could not see it.

A HOMEOSTASIS or STABILITY axiom reading that trajectory reports a finding
about a collapse the simulator invented, and `plan` scores any staged
candidate -- two adjustments of one set-point, the ordinary shape of a ramp --
against it.

THE OFFSET IS WHY THIS IS NOT A ONE-LINE CHANGE. `delta_target` is
`(gain *delta + offset) *fraction`, so an edge applied in two movement
groups charges its offset TWICE and the steady state, the one thing that was
right before, becomes `g*(d1+d2) + 2c`. The offset is a one-time constant
belonging to the coupling, not to each movement, so it is charged in the
FIRST group a source moves in suppressed thereafter: the result is
`g*(d1*f1 + d2*f2) + c*f1`, which is what superposition through a first-order
lag with a constant term actually says.

WHY THE SUITE COULD NOT SEE IT. Every rollout and plan fixture in the package
schedules exactly one action per property, so `moved_at` was never overwritten
in any test that existed.
"""
from __future__ import annotations

import math

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance

MODEL = """
domain:
  id: superposition
  name: Two movements of one property
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 120, time_constant_s: 600,
                 response_model: exponential}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                   source: datasheet%(offset)s}
  action_templates:
    - name: throttle_pump
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm}
      effect: set
      settle_s: 0
      source: runbook
"""

DELAY, TAU, GAIN = 120.0, 600.0, 0.02
BASE_LEVEL, BASE_SPEED = 50.0, 1000.0
FIRST_SPEED, SECOND_SPEED = 1500.0, 1600.0
SECOND_AT = 1800.0
HORIZON_S, STEP_S = 3600.0, 60.0


def _f(t):
    """The declared response, written out rather than asked of the engine."""
    return 0.0 if t < DELAY else 1.0 - math.exp(-(t - DELAY) / TAU)


def _session(tmp_path, name, offset=""):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL % {"offset": offset})
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": BASE_SPEED})
    session.add_entity("tank1", "Tank", {"level_pct": BASE_LEVEL})
    session.add_relationship("pump1", "feeds", "tank1")
    return session


def _throttle(at_s, speed):
    return ActionInstance("throttle_pump", "pump1", {"speed_rpm": speed}, at_s)


def _staged(session, **kw):
    kw.setdefault("horizon_s", HORIZON_S)
    kw.setdefault("step_s", STEP_S)
    kw.setdefault("actions", [_throttle(0.0, FIRST_SPEED),
                              _throttle(SECOND_AT, SECOND_SPEED)])
    return api.rollout(session, **kw).to_dict()["simulation"]


def _superposed(at_s, offset=0.0):
    d1 = GAIN * (FIRST_SPEED - BASE_SPEED)
    d2 = GAIN * (SECOND_SPEED - FIRST_SPEED)
    return (BASE_LEVEL + d1 * _f(at_s) + d2 * _f(at_s - SECOND_AT)
            + offset * _f(at_s))


class TestEachMovementDevelopsOnItsOwnClock:

    def test_the_second_movement_does_not_reset_the_first(self, tmp_path):
        for step in _staged(_session(tmp_path, "stage"))["per_step"]:
            at_s = step["at_s"]
            got = step["values"]["tank1"]["level_pct"]
            assert got == pytest.approx(_superposed(at_s), abs=1e-6), (
                f"at {at_s}s the tank sits at {got}; superposition says "
                f"{_superposed(at_s)}")

    def test_the_trajectory_never_falls_back(self, tmp_path):
        """The symptom on its own, independent of the closed form: a rising
        response to two rises cannot go down."""
        levels = [s["values"]["tank1"]["level_pct"]
                  for s in _staged(_session(tmp_path, "mono"))["per_step"]]
        drops = [(a, b) for a, b in zip(levels, levels[1:]) if b < a - 1e-9]
        assert not drops, f"the trajectory fell back at {drops}"

    def test_the_source_still_carries_the_cumulative_setting(self, tmp_path):
        """Superposing the RESPONSE must not split the acted property itself:
        the pump was set to 1600 and reads 1600."""
        last = _staged(_session(tmp_path, "cumulative"))["per_step"][-1]
        assert last["values"]["pump1"]["speed_rpm"] == pytest.approx(
            SECOND_SPEED)


class TestTheOffsetIsChargedOnce:

    def test_a_declared_offset_is_not_doubled_by_a_second_movement(
            self, tmp_path):
        offset = 7.0
        steps = _staged(_session(tmp_path, "offset",
                                 offset=f", offset: {offset}"))["per_step"]
        for step in steps:
            at_s = step["at_s"]
            got = step["values"]["tank1"]["level_pct"]
            assert got == pytest.approx(
                _superposed(at_s, offset), abs=1e-6), (
                f"at {at_s}s the tank sits at {got}; one offset developing "
                f"from the first movement says {_superposed(at_s, offset)}")

    def test_the_steady_state_carries_exactly_one_offset(self, tmp_path):
        offset = 7.0
        last = _staged(_session(tmp_path, "steady",
                                offset=f", offset: {offset}"),
                       horizon_s=36000.0, step_s=600.0)["per_step"][-1]
        settled = (BASE_LEVEL + GAIN * (SECOND_SPEED - BASE_SPEED) + offset)
        assert last["values"]["tank1"]["level_pct"] == pytest.approx(
            settled, abs=1e-3), "the offset was charged once per movement"


class TestOneActionIsUnchanged:

    def test_a_single_movement_still_follows_the_declared_curve(
            self, tmp_path):
        """The regression floor: the fix must not disturb the case the
        package already measured."""
        simulation = _staged(_session(tmp_path, "single"),
                             actions=[_throttle(0.0, FIRST_SPEED)])
        d1 = GAIN * (FIRST_SPEED - BASE_SPEED)
        for step in simulation["per_step"]:
            expected = BASE_LEVEL + d1 * _f(step["at_s"])
            assert step["values"]["tank1"]["level_pct"] == pytest.approx(
                expected, abs=1e-6)
