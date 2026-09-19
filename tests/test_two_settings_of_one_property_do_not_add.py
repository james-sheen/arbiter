"""`set` is not additive, and neither is `scale`. Summing them invents a value.

An action is converted to a DELTA so it composes with the transitions
arriving at the same property in the same step, and that is right: one
superposition rule, one arithmetic. What it is not right for is composing two
ACTIONS with each other, because only one of the three declared effects is
additive.

Measured, pump at 1000, both actions at `t=0`:

  - `set 1500` then `set 2000` put the pump at **2500** -- neither value, and
    a number no action asked for. The rule is `A + B - base`, so three
    settings reached 3300. It is order-INDEPENDENT, which is what makes it a
    systematic artifact rather than a race: each `set` measures its delta from
    the same pre-step reading and the deltas are then added.
  - `scale 2` then `scale 3` put it at **4000**, where composing the two
    scalings gives 6000.
  - `add 100` then `add 200` gave 300, which is correct and stays correct.

Nothing was refused and nothing declined in any of those.

`plan` REACHES IT. With `max_depth: 2` the planner offers every declared
candidate as a second action, all at `at_s = 0`, so on the engine's own worked
example three of its eight candidates set `pump1.speed_rpm` twice at one
instant and were ranked on a set-point the pump could never be given.

THE TWO CASES ARE NOT THE SAME and are not treated the same. Two `scale`
factors compose by multiplication, which is commutative -- there is one answer
and no ordering is needed to find it, so the engine computes it. Two DIFFERENT
`set` values at one instant have no answer: `at_s` is the only ordering this
engine has, the two share it, and list position is an accident of how a caller
built the sequence. So it is refused by name, with both values in the refusal,
and the property is left alone. Picking the later one would be the engine
choosing which instruction the author meant.

Same value twice is not a conflict. It is redundant, and applying it once is
what it asks for.
"""
from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance

MODEL = """
domain:
  id: effects
  name: effects
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump: [{name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    Tank: [{name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02, source: datasheet}
  action_templates:
    - name: put
      applies_to: Pump
      parameters_schema: {speed_rpm: {type: number, entity_property: speed_rpm}}
      effect: %(effect)s
      settle_s: 0
      source: runbook
"""

BASE = 1000.0


def _session(tmp_path, effect, name):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL % {"effect": effect})
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": BASE})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_relationship("pump1", "feeds", "tank1")
    return session


def _run(session, values, at=None):
    at = at or [0.0] * len(values)
    actions = [ActionInstance("put", "pump1", {"speed_rpm": v}, t)
               for v, t in zip(values, at)]
    return api.rollout(session, actions=actions,
                       horizon_s=600.0, step_s=60.0).to_dict()["simulation"]


def _pump(simulation):
    return simulation["per_step"][-1]["values"]["pump1"]["speed_rpm"]


class TestTwoSettingsAtOneInstantAreRefused:

    def test_the_pump_is_not_put_where_neither_action_asked(self, tmp_path):
        simulation = _run(_session(tmp_path, "set", "conflict"), [1500.0, 2000.0])
        assert _pump(simulation) != pytest.approx(2500.0), (
            "the two settings were added: 1500 + 2000 - 1000")
        assert _pump(simulation) == pytest.approx(BASE), (
            "a refused pair leaves the property alone")

    def test_the_refusal_names_both_values(self, tmp_path):
        simulation = _run(_session(tmp_path, "set", "named"), [1500.0, 2000.0])
        assert simulation["checked"]["actions_refused"] >= 1
        refusals = [row for row in simulation["not_checked"]
                    if row["reason"] == "contradictory_actions"]
        assert refusals, simulation["not_checked"]
        detail = refusals[0]["detail"]
        assert "1500" in detail and "2000" in detail, detail
        assert "speed_rpm" in detail, detail

    def test_three_settings_do_not_reach_3300(self, tmp_path):
        simulation = _run(_session(tmp_path, "set", "three"),
                          [1500.0, 2000.0, 1800.0])
        assert _pump(simulation) == pytest.approx(BASE)

    def test_the_target_is_not_driven_by_a_value_nobody_set(self, tmp_path):
        """The downstream half: the tank was reading a gain applied to an
        invented set-point."""
        simulation = _run(_session(tmp_path, "set", "down"), [1500.0, 2000.0])
        assert simulation["per_step"][-1]["values"]["tank1"][
            "level_pct"] == pytest.approx(50.0)


class TestTheSameSettingTwiceIsNotAConflict:

    def test_a_repeated_setting_is_applied_once(self, tmp_path):
        simulation = _run(_session(tmp_path, "set", "same"), [1500.0, 1500.0])
        assert _pump(simulation) == pytest.approx(1500.0)
        assert simulation["checked"]["actions_refused"] == 0


class TestScalesCompose:

    def test_two_scalings_multiply(self, tmp_path):
        simulation = _run(_session(tmp_path, "scale", "scales"), [2.0, 3.0])
        assert _pump(simulation) == pytest.approx(6000.0), (
            "2x then 3x is 6x; summing the deltas gives 4x")

    def test_one_scaling_is_unchanged(self, tmp_path):
        assert _pump(_run(_session(tmp_path, "scale", "one"),
                          [2.0])) == pytest.approx(2000.0)


class TestAdditionIsUntouched:

    def test_two_additions_still_add(self, tmp_path):
        """The floor. `add` is the one effect for which summing deltas was
        always right, and this fix must not reach it."""
        assert _pump(_run(_session(tmp_path, "add", "adds"),
                          [100.0, 200.0])) == pytest.approx(BASE + 300.0)


MIXED = """
domain:
  id: mixed
  name: mixed
  entity_types: [Pump]
  indicators:
    Pump: [{name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  action_templates:
    - {name: put,  applies_to: Pump, effect: set,   settle_s: 0, source: runbook,
       parameters_schema: {speed_rpm: {type: number, entity_property: speed_rpm}}}
    - {name: bump, applies_to: Pump, effect: add,   settle_s: 0, source: runbook,
       parameters_schema: {speed_rpm: {type: number, entity_property: speed_rpm}}}
    - {name: mul,  applies_to: Pump, effect: scale, settle_s: 0, source: runbook,
       parameters_schema: {speed_rpm: {type: number, entity_property: speed_rpm}}}
"""


class TestEffectsThatComposeDifferentlyDoNotMix:
    """The hole the first version of this fix left, found by reading the diff
    rather than by a test. Holding back only the NON-additive effects meant an
    `add` was summed into the bucket on its way past, so it still composed by
    addition with whatever was resolved afterwards: `add 100` beside
    `set 1500` on a pump at 1000 came out at **1600**, which is neither value
    and was not refused. `add 100` beside `scale 2` came out at 2100, where
    the two orderings give 2100 and 2200 -- an answer that depends on an
    ordering this engine does not have.

    The rule is about the SET of effects meeting at one instant, so the set
    has to be complete before anything is decided."""

    def _run(self, tmp_path, pairs, name):
        path = tmp_path / f"{name}.yaml"
        path.write_text(MIXED)
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("pump1", "Pump", {"speed_rpm": BASE})
        actions = [ActionInstance(t, "pump1", {"speed_rpm": v}, 0.0)
                   for t, v in pairs]
        return api.rollout(session, actions=actions, horizon_s=300.0,
                           step_s=60.0).to_dict()["simulation"]

    @pytest.mark.parametrize("pairs,name", [
        ([("bump", 100.0), ("put", 1500.0)], "add_set"),
        ([("mul", 2.0), ("put", 1500.0)], "scale_set"),
        ([("bump", 100.0), ("mul", 2.0)], "add_scale"),
    ])
    def test_two_kinds_at_one_instant_are_refused(self, tmp_path, pairs, name):
        simulation = self._run(tmp_path, pairs, name)
        assert simulation["per_step"][-1]["values"]["pump1"][
            "speed_rpm"] == pytest.approx(BASE), (
            "a mixture that has no single answer moved the property anyway")
        assert "contradictory_actions" in {
            row["reason"] for row in simulation["not_checked"]}

    def test_one_kind_alone_still_applies(self, tmp_path):
        """The floor: this must refuse MIXTURES, not any two actions."""
        simulation = self._run(
            tmp_path, [("bump", 100.0), ("bump", 200.0)], "adds_only")
        assert simulation["per_step"][-1]["values"]["pump1"][
            "speed_rpm"] == pytest.approx(BASE + 300.0)
        assert simulation["checked"]["actions_refused"] == 0


class TestPlanSaysWhyACandidateDidNothing:
    """`plan` at `max_depth: 2` offers every declared candidate as a second
    action, all at `at_s = 0`, so on a model with one action template every
    depth-2 plan sets one property twice at one instant. Those are refused
    now, which is right; what was missing is that the candidate came back
    tied with `do_nothing` and an EMPTY `declines`, so a reader comparing
    rows had no way to tell a plan that did nothing from one that was
    refused. The refusals were reported at plan level, so the fact was never
    lost -- it was unattributed."""

    def test_a_refused_candidate_names_its_refusal(self, tmp_path):
        path = tmp_path / "planned.yaml"
        path.write_text(MODEL % {"effect": "set"} + """
  planning:
    objective: expected_findings
    max_depth: 2
""")
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("pump1", "Pump", {"speed_rpm": BASE})
        session.add_entity("tank1", "Tank", {"level_pct": 50.0})
        session.add_relationship("pump1", "feeds", "tank1")
        out = api.plan(
            session,
            candidates=[ActionInstance("put", "pump1", {"speed_rpm": v}, 0.0)
                        for v in (1500.0, 2000.0)],
            horizon_s=600.0, step_s=60.0).to_dict()
        plan = (out.get("payload") or out).get("plan") or out.get("plan")
        staged = [c for c in plan["candidates"] if len(c["actions"]) > 1]
        assert staged, "max_depth 2 produced no two-action candidate"
        for candidate in staged:
            assert "contradictory_actions" in candidate["declines"], candidate


class TestDifferentInstantsAreNotAConflict:

    def test_a_later_setting_supersedes_an_earlier_one(self, tmp_path):
        """`at_s` IS an ordering, so two settings at different instants are a
        sequence rather than a contradiction, and both apply."""
        simulation = _run(_session(tmp_path, "set", "seq"),
                          [1500.0, 2000.0], at=[0.0, 300.0])
        assert _pump(simulation) == pytest.approx(2000.0)
        assert simulation["checked"]["actions_refused"] == 0
