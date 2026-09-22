"""Two actions scheduled at different times are two movements, not a collision.

`rollout` collected every action falling inside a step into ONE bucket
keyed by `(entity, property)`, which threw away `at_s`. Two `set` effects
scheduled nine hundred seconds apart then met the rule written for two effects
at ONE instant, and the whole pair was refused.

WHAT THAT COSTS, MEASURED. Same model, same two actions, step size alone
changed:

    step_s=900 refused; the pump never moves, the tank it feeds reads 50.0
    step_s=450 applied; the tank peaks at 88.0 and files a warning breach

**`step_s` is how finely a caller asks to see the trajectory. It is not a fact
about the model**, and it decided here whether a declared action happened at
all. That is the shape that an internal ruling closed one surface over, where a tie-break
reversed with the step size; this one does not reverse a ranking, it discards
the trajectory.

THE REFUSAL'S OWN MESSAGE WAS THE TELL. It reads *effects at the same instant
`at_s` is the only ordering this engine has and they share it*, and then
prescribes *schedule them at different times* -- which is exactly what the
caller had done. A refusal whose remedy is the input it just rejected is
reporting its own bucketing, not the model.

ONLY `set` AND MIXED KINDS WERE AFFECTED, and that is the argument for where
the fix goes rather than a reason it is small: `add` superposes and `scale`
composes by multiplication, so both are order-free and were correct at every
step size. The rule is about effects that need an ordering, and `at_s` is one.
"""
from __future__ import annotations

import pytest

from arbiter_engine.api import EngineSession, rollout

MODEL = """
domain:
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - name: speed_rpm
        axioms: [BOUNDEDNESS]
        warning: 3600
        critical: 4000
    Tank:
      - name: level_pct
        axioms: [BOUNDEDNESS]
        warning: 85
        critical: 95
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 300, response_model: exponential}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02, source: datasheet, gain_sigma: 0.002}
  action_templates:
    - name: throttle
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm, candidates: [1000, 2000, 3000]}
      effect: set
      settle_s: 1
"""

#: Up, then down again nine hundred seconds later.
TWO = [{"template": "throttle", "entity_id": "p",
        "parameters": {"speed_rpm": 3000.0}, "at_s": 0.0},
       {"template": "throttle", "entity_id": "p",
        "parameters": {"speed_rpm": 2000.0}, "at_s": 900.0}]


def _session(model: str = MODEL) -> EngineSession:
    session = EngineSession()
    session.load_model(model)
    session.add_entity("p", "Pump", properties={"speed_rpm": 1000.0})
    session.add_entity("t", "Tank", properties={"level_pct": 50.0})
    session.add_relationship("p", "feeds", "t")
    return session


def _roll(actions, step_s: float, model: str = MODEL) -> dict:
    return rollout(_session(model), actions=actions,
                   horizon_s=1800.0, step_s=step_s).to_dict()["simulation"]


def _reasons(simulation: dict) -> set:
    return {row.get("reason") for row in simulation.get("not_checked", [])}


class TestTheStepSizeDoesNotDecideWhetherAnActionHappened:
    """The claim, stated as the thing a caller can check."""

    @pytest.mark.parametrize("step_s", [1800.0, 900.0, 450.0, 300.0, 100.0])
    def test_both_actions_are_applied_at_every_step_size(self, step_s):
        simulation = _roll(TWO, step_s)
        assert simulation["checked"]["actions_refused"] == 0, (
            f"step_s={step_s} refused an action scheduled at a different "
            f"instant from the other: {_reasons(simulation)}")

    @pytest.mark.parametrize("step_s", [1800.0, 900.0, 450.0, 300.0, 100.0])
    def test_the_last_setting_is_what_the_property_holds(self, step_s):
        """A `set` pins the property. The LAST one scheduled is the one that
        stands at the end of the horizon, whatever the sampling grid was."""
        final = _roll(TWO, step_s)["per_step"][-1]["values"]["p"]["speed_rpm"]
        assert final == pytest.approx(2000.0), (
            f"step_s={step_s} ended at {final}, not the last setting asked for")

    def test_the_trajectory_does_not_depend_on_the_grid_at_the_horizon(self):
        """Every grid must agree about where the model ENDS.

        Not about every intermediate reading -- a coarse grid genuinely sees
        fewer points, and that is the caller's choice. The end state is not a
        matter of taste.
        """
        ends = {step: _roll(TWO, step)["per_step"][-1]["values"]["t"]["level_pct"]
                for step in (900.0, 450.0, 300.0, 100.0)}
        assert max(ends.values()) - min(ends.values()) < 0.5, (
            f"the horizon reading depends on the sampling grid: {ends}")


class TestTheRefusalStillFiresWhereItMeansSomething:
    """Two-sided. The rule exists because two effects at ONE instant have no
    ordering, and removing that would be a worse defect than the one fixed."""

    def test_two_settings_at_the_same_instant_are_still_refused(self):
        same = [{"template": "throttle", "entity_id": "p",
                 "parameters": {"speed_rpm": 3000.0}, "at_s": 0.0},
                {"template": "throttle", "entity_id": "p",
                 "parameters": {"speed_rpm": 2000.0}, "at_s": 0.0}]
        simulation = _roll(same, 300.0)
        assert simulation["checked"]["actions_refused"] >= 1
        assert "contradictory_actions" in _reasons(simulation)

    def test_one_setting_asked_for_twice_at_one_instant_is_not_a_collision(self):
        """Redundant, not contradictory -- the existing rule, kept."""
        twice = [{"template": "throttle", "entity_id": "p",
                  "parameters": {"speed_rpm": 3000.0}, "at_s": 0.0},
                 {"template": "throttle", "entity_id": "p",
                  "parameters": {"speed_rpm": 3000.0}, "at_s": 0.0}]
        simulation = _roll(twice, 300.0)
        assert simulation["checked"]["actions_refused"] == 0
        assert simulation["per_step"][-1]["values"]["p"]["speed_rpm"] == pytest.approx(3000.0)


class TestTheOrderFreeKindsWereNeverAffected:
    """Measured before the fix and pinned after it: `add` and `scale` gave the
    same answer at every step size throughout, which is why the repair belongs
    to the ordering rule and not to the stepping loop at large."""

    @pytest.mark.parametrize("effect,expected", [("add", 2000.0), ("scale", 4000.0)])
    @pytest.mark.parametrize("step_s", [1800.0, 300.0])
    def test_they_agree_across_the_grid(self, effect, expected, step_s):
        model = MODEL.replace("effect: set", f"effect: {effect}")
        values = [{"add": 500.0, "scale": 2.0}[effect]] * 2
        actions = [{"template": "throttle", "entity_id": "p",
                    "parameters": {"speed_rpm": values[i]}, "at_s": at}
                   for i, at in enumerate((0.0, 900.0))]
        simulation = _roll(actions, step_s, model)
        assert simulation["checked"]["actions_refused"] == 0
        final = simulation["per_step"][-1]["values"]["p"]["speed_rpm"]
        assert final == pytest.approx(expected)


class TestTheEngineSaysWhichInstantsItJudged:
    """The axioms run at the steps and nowhere between them.

    Found while proving, from the other direction: once two movements
    on one property could coexist, the trajectory could TURN, and a turn
    between two sampled instants is a turn nothing judged.

    MEASURED, with the true peak at 88.314 at `t=950` and the line at 88.1:

        step_s=950 samples t=950 BREACH
        step_s=475 samples t=950 BREACH
        step_s=300 does not clean
        step_s=200 does not clean
        step_s=100 does not clean

    **Refining the grid does not fix it.** 100 s reports clean and 950 s
    reports the breach, because what decides is whether the turning instant is
    ON the grid, not how fine the grid is. A caller who halves `step_s` to be
    safer has done nothing of the kind.

    NOT FIXED BY JUDGING MORE INSTANTS, and that is a choice. Evaluating at
    instants the caller did not ask for would put rows in `per_step` nobody
    requested, and choosing those instants would be the engine picking the
    resolution of a trajectory the caller asked to see at `step_s`. The engine's
    product is *did you look*; the honest form is to say where it looked.
    """

    #: The true peak is 88.314 at t=950; the line sits between that and the
    #: 88.009 a 300 s grid can see.
    TUNED = MODEL.replace("warning: 85", "warning: 88.1").replace(
        "critical: 95", "critical: 99")
    TURN = [{"template": "throttle", "entity_id": "p",
             "parameters": {"speed_rpm": 3000.0}, "at_s": 0.0},
            {"template": "throttle", "entity_id": "p",
             "parameters": {"speed_rpm": 1000.0}, "at_s": 950.0}]
    STAMP = "movement_between_sampled_steps"

    @pytest.mark.parametrize("step_s", [300.0, 200.0, 100.0])
    def test_a_turn_off_the_grid_is_disclosed(self, step_s):
        simulation = rollout(_session(self.TUNED), actions=self.TURN,
                             horizon_s=1900.0, step_s=step_s
                             ).to_dict()["simulation"]
        assert self.STAMP in simulation["assumptions"], (
            f"step_s={step_s} never judged t=950, where the trajectory turns, "
            f"and said nothing about it")

    @pytest.mark.parametrize("step_s", [950.0, 475.0])
    def test_a_turn_ON_the_grid_is_not_disclosed(self, step_s):
        """Two-sided. A stamp that fires whatever happened is not a
        disclosure, it is decoration."""
        simulation = rollout(_session(self.TUNED), actions=self.TURN,
                             horizon_s=1900.0, step_s=step_s
                             ).to_dict()["simulation"]
        assert self.STAMP not in simulation["assumptions"]
        assert simulation["per_step"], "the grid judged nothing at all"

    def test_one_movement_cannot_hide_a_turn_and_is_not_stamped(self):
        """A first-order response from a SINGLE movement is monotonic, so its
        extremum is an endpoint and every endpoint is sampled. The shipped
        example is this case, and stamping it would be false."""
        one = [{"template": "throttle", "entity_id": "p",
                "parameters": {"speed_rpm": 3000.0}, "at_s": 0.0}]
        simulation = _roll(one, 300.0, self.TUNED)
        assert self.STAMP not in simulation["assumptions"]

    def test_the_stamp_is_in_the_published_vocabulary(self):
        from arbiter_engine.assumptions import is_known_stamp
        assert is_known_stamp(self.STAMP)
