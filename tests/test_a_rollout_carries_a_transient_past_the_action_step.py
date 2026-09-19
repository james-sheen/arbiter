"""A declared response keeps developing after the step its action fired in.

THE ROLLOUT APPLIED EVERY TRANSITION ONCE, WITH ONE STEP'S WORTH OF
ELAPSED TIME, AND NEVER AGAIN. Whatever fraction of the response `step_s`
reached was the fraction that stood for the whole horizon.

That is not a corner case, because the number it produces on the engine's own
defaults is zero. `TwinEdge` defaults to `propagation_delay_s = 60` and
`time_constant_s = 60`; `api.rollout` defaults to `step_s = 60`; and
`response_fraction(60)` on a delay of 60 is exactly `0.0`. Measured before the
fix, on the fixture below with the delay declared at 120 s: the tank sat at
50.0 for all sixty steps of an hour-long rollout while the declared response
said 109.8, `transitions_applied` reported 1, and the envelope declined
nothing. An effect accepted and silently never applied is the failure this
module already fixed once for actions at `at_s = 0`.

`plan` inherited it whole. Every candidate's downstream effect was zero, so
candidates tied on everything but the acted entity's own bounds and the
tie-break handed back `do_nothing`. Measured on a tank at 92 % against a
declared `warning: 85`, with throttling the pump among the declared
candidates: all four scored 10.0 and the recommendation was to do nothing.

WHY THE SUITE COULD NOT SEE IT. Every `temporal:` block in the rollout and
plan fixtures is `{0, 1, step}` -- a step response, which reaches steady state
inside the first step and is the one regime where applying a transition once
is correct. The two fixtures that declare a real time course exercise
`traverse`, which passes a full horizon and was never wrong. A defect that
only appears when a fixture declares dynamics slower than its own step is
invisible to a suite whose fixtures are all instantaneous, so this file
declares MODELING.md's own example and asserts against the closed form.
"""
from __future__ import annotations

import math

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance

#: MODELING.md's own `transition:` example, whose prose says `rollout` steps
#: it forward under actions.
LAGGED = ("temporal: {propagation_delay_s: 120, time_constant_s: 600, "
          "response_model: exponential}")
#: What an author gets by declaring `transition:` and no `temporal:` block.
ENGINE_DEFAULTS = ""

MODEL = """
domain:
  id: transient
  name: Pump and tank with a declared time course
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
      %(temporal)s
      transition: {from: speed_rpm, to: level_pct, gain: 0.02, source: datasheet}
  action_templates:
    - name: throttle_pump
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm}
      effect: set
      settle_s: 0
      source: runbook
"""

BASE_LEVEL = 50.0
BASE_SPEED = 1000.0
TARGET_SPEED = 4000.0
GAIN = 0.02
#: gain x the change the action makes: 0.02 x 3000 = 60.0
STEADY_DELTA = GAIN * (TARGET_SPEED - BASE_SPEED)


def _session(tmp_path, temporal, name):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL % {"temporal": temporal})
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": BASE_SPEED})
    session.add_entity("tank1", "Tank", {"level_pct": BASE_LEVEL})
    session.add_relationship("pump1", "feeds", "tank1")
    return session


def _throttle(at_s=0.0):
    return ActionInstance("throttle_pump", "pump1",
                          {"speed_rpm": TARGET_SPEED}, at_s)


def _sim(session, **kw):
    kw.setdefault("horizon_s", 3600.0)
    kw.setdefault("step_s", 60.0)
    kw.setdefault("actions", [_throttle()])
    return api.rollout(session, **kw).to_dict()["simulation"]


def _declared(at_s, delay=120.0, tau=600.0):
    """The closed form of what the model declares, independent of the engine.

    Deliberately NOT computed by calling `TwinEdge.response_fraction`: a test
    that asks the code under test what the answer should be cannot falsify it.
    """
    if at_s < delay:
        return BASE_LEVEL
    return BASE_LEVEL + STEADY_DELTA * (
        1.0 - math.exp(-(at_s - delay) / tau))


class TestTheTrajectoryFollowsTheDeclaredResponse:

    def test_every_step_matches_the_declared_curve(self, tmp_path):
        simulation = _sim(_session(tmp_path, LAGGED, "lagged"))
        for step in simulation["per_step"]:
            got = step["values"]["tank1"]["level_pct"]
            assert got == pytest.approx(_declared(step["at_s"]), abs=1e-6), (
                f"at {step['at_s']}s the tank reads {got} and the declared "
                f"response says {_declared(step['at_s'])}")

    def test_the_value_is_still_moving_late_in_the_horizon(self, tmp_path):
        """The specific symptom: frozen at step one, whatever the horizon."""
        per_step = _sim(_session(tmp_path, LAGGED, "lagged2"))["per_step"]
        early = per_step[4]["values"]["tank1"]["level_pct"]
        late = per_step[-1]["values"]["tank1"]["level_pct"]
        assert late > early + 40.0, (
            f"the tank moved from {early} to {late} across the horizon; a "
            f"first-order response with a 600s time constant covers most of "
            f"its range in an hour")

    def test_nothing_moves_before_the_declared_delay(self, tmp_path):
        """The floor half. A response that starts early is as wrong as one
        that never starts, and would pass a test that only checks the end."""
        per_step = _sim(_session(tmp_path, LAGGED, "lagged3"))["per_step"]
        for step in per_step:
            if step["at_s"] < 120.0:
                assert step["values"]["tank1"]["level_pct"] == pytest.approx(
                    BASE_LEVEL), "the declared delay was not waited out"

    def test_the_engine_defaults_also_develop(self, tmp_path):
        """`transition:` with no `temporal:` is the likeliest declaration an
        author writes, and it is the case that produced a fraction of exactly
        zero -- delay 60 against a step of 60."""
        per_step = _sim(_session(tmp_path, ENGINE_DEFAULTS, "defaults"),
                        horizon_s=1800.0)["per_step"]
        assert per_step[-1]["values"]["tank1"]["level_pct"] == pytest.approx(
            BASE_LEVEL + STEADY_DELTA, abs=1e-3), (
            "on the engine's own edge defaults the tank never left its "
            "starting value")


class TestAStepResponseStillJumpsOnce:
    """Guard. The fix must not turn an instantaneous coupling into a ramp."""

    STEP = ("temporal: {propagation_delay_s: 0, time_constant_s: 1, "
            "response_model: step}")

    def test_a_step_edge_reaches_steady_state_in_the_first_step(self, tmp_path):
        per_step = _sim(_session(tmp_path, self.STEP, "stepwise"))["per_step"]
        for step in per_step:
            assert step["values"]["tank1"]["level_pct"] == pytest.approx(
                BASE_LEVEL + STEADY_DELTA), (
                "a step response is fully realised in the step the action "
                "fired in and stays there")


class TestTheFractionReachedIsVisible:
    """A reader must be able to tell `not yet` from `never asked`.

    The envelope reported `transitions_applied: 1` beside a flat trajectory
    and nothing else, which reads as a transition that ran and had no effect.
    """

    def test_per_step_carries_the_response_fractions(self, tmp_path):
        per_step = _sim(_session(tmp_path, LAGGED, "fractions"))["per_step"]
        assert all("response_fractions" in step for step in per_step)
        inside_delay = [s for s in per_step if s["at_s"] < 120.0]
        assert all(f == 0.0 for s in inside_delay
                   for f in s["response_fractions"]), (
            "inside the declared delay the fraction reached is zero, and the "
            "envelope should say so rather than only showing a flat value")
        assert per_step[-1]["response_fractions"], "no fraction was reported"
        assert max(per_step[-1]["response_fractions"]) > 0.9


class TestAPlanCanTellItsCandidatesApart:
    """The consequence that reaches a caller as advice.

    `plan` rolls every candidate through this path. With the transient frozen,
    every candidate's downstream effect was identical and the tie-break
    returned `do_nothing` -- on a tank already above its declared warning.
    """

    PLAN_MODEL = """
domain:
  id: planning
  name: Plan under a declared time course
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS],
         warning: 85, critical: 95}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 120, time_constant_s: 600,
                 response_model: exponential}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02, source: datasheet}
  action_templates:
    - name: throttle_pump
      applies_to: Pump
      parameters_schema:
        speed_rpm:
          type: number
          entity_property: speed_rpm
          candidates: [500, 1000, 4000]
      effect: set
      settle_s: 0
      source: runbook
  planning:
    objective: expected_findings
"""

    @pytest.fixture
    def loaded(self, tmp_path):
        path = tmp_path / "plan.yaml"
        path.write_text(self.PLAN_MODEL)
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("pump1", "Pump", {"speed_rpm": 4000.0})
        session.add_entity("tank1", "Tank", {"level_pct": 92.0})
        session.add_relationship("pump1", "feeds", "tank1")
        return session

    def test_the_candidates_do_not_all_tie(self, loaded):
        plan = api.plan(loaded, horizon_s=1800.0, step_s=60.0).to_dict()["plan"]
        scores = {c["objective"] for c in plan["candidates"]}
        assert len(scores) > 1, (
            f"every candidate scored {scores}; a plan that cannot tell "
            f"throttling a pump from leaving it alone is reporting the "
            f"dynamics it never ran")

    def test_acting_beats_doing_nothing_when_acting_helps(self, loaded):
        plan = api.plan(loaded, horizon_s=1800.0, step_s=60.0).to_dict()["plan"]
        assert plan["ranked"] is True
        assert plan["best"] != "do_nothing", (
            "the tank sits above its declared warning and a declared "
            "candidate throttles the pump that feeds it; recommending "
            "inaction here is the frozen transient, not a judgement")
