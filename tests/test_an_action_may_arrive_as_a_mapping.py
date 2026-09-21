"""A caller's wrong type is a caller's bug, not a gap in the model's coverage.

`rollout` and `plan` took `ActionInstance` dataclasses, and a plain
mapping -- the shape every JSON consumer has -- reached the walk and raised
`AttributeError` inside it. The discipline caught that and reported
`not_checked[].reason: internal_error` with `meta.source: unavailable`, which
says THE ENGINE BROKE over a cell nobody could answer. Nothing was wrong with
the model and nothing was unanswerable: the caller passed a dict.

Filing it under coverage is the specific harm. `not_checked` is the leg that
distinguishes a clean pass from an unevaluated one, and a caller bug parked
there reads as something the author failed to declare.

WHY A MAPPING IS ACCEPTED RATHER THAN REFUSED. Two transports were already
converting one by hand on the way in, in two copies of the same six lines, so
the shape was supported in practice and unsupported in name. The conversion
now has one home at the API boundary -- which is also why the defect was
invisible from the MCP direction: every consumer reaching the verb over the
transport was converted, and every consumer calling it directly was not.

THE COERCION SITS OUTSIDE THE BOUNDARY on purpose, so a type that is
neither raises instead of being swallowed into the envelope.
"""
from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import (
    ActionInstance, as_action_instance)

MODEL = """
domain:
  id: mapping_actions
  name: A pump feeding a tank
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS],
         critical: 9000, window: 30m}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS],
         critical: 9000, window: 30m}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 120, time_constant_s: 600,
                 response_model: exponential}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                   gain_sigma: 0.002, source: datasheet}
  action_templates:
    - name: throttle_pump
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm,
                    candidates: [1500, 3000]}
      effect: set
      settle_s: 0
      source: runbook
  planning:
    objective: expected_findings
"""

AS_MAPPING = {"template": "throttle_pump", "entity_id": "pump1",
              "parameters": {"speed_rpm": 3000.0}, "at_s": 0.0}
AS_INSTANCE = ActionInstance("throttle_pump", "pump1",
                             {"speed_rpm": 3000.0}, at_s=0.0)


def _session():
    s = api.EngineSession()
    s.load_model(MODEL)
    s.add_entity("pump1", "Pump", properties={"speed_rpm": 2000})
    s.add_entity("tank1", "Tank", properties={"level_pct": 50})
    s.add_observations("pump1", "speed_rpm", [2000.0] * 40)
    s.add_observations("tank1", "level_pct", [50.0] * 40)
    s.add_relationship("pump1", "feeds", "tank1")
    return s


class TestTheCoercionItself:

    def test_an_instance_passes_through_unchanged(self):
        assert as_action_instance(AS_INSTANCE, where="x") is AS_INSTANCE

    def test_a_mapping_becomes_the_same_instance(self):
        assert as_action_instance(AS_MAPPING, where="x") == AS_INSTANCE

    def test_a_partial_mapping_is_not_completed_with_a_guess(self):
        """Empty strings and zero are what the dataclass itself declares; the
        rollout's own refusal vocabulary then names the problem, rather than
        this function inventing a second one."""
        built = as_action_instance({}, where="x")
        assert built.template == "" and built.entity_id == ""
        assert built.parameters == {} and built.at_s == 0.0

    @pytest.mark.parametrize("bad", ["throttle_pump", 3, None, ["a"]])
    def test_anything_else_raises_at_the_boundary(self, bad):
        with pytest.raises(TypeError) as caught:
            as_action_instance(bad, where="rollout(actions=...)")
        assert "rollout(actions=...)" in str(caught.value)
        assert type(bad).__name__ in str(caught.value)


class TestTheVerbsAcceptBothShapes:

    def test_a_mapping_rolls_out_identically_to_an_instance(self):
        a = api.rollout(_session(), actions=[AS_MAPPING],
                        horizon_s=3600, step_s=600).to_dict()["simulation"]
        b = api.rollout(_session(), actions=[AS_INSTANCE],
                        horizon_s=3600, step_s=600).to_dict()["simulation"]
        assert a["meta"]["source"] == "live"
        assert a["tier"] == 3
        assert [s["values"] for s in a["per_step"]] == [
            s["values"] for s in b["per_step"]]

    def test_the_old_failure_is_gone(self):
        env = api.rollout(_session(), actions=[AS_MAPPING],
                          horizon_s=3600, step_s=600).to_dict()["simulation"]
        assert env["meta"].get("reason") is None
        reasons = [d.get("reason") for d in (env.get("not_checked") or [])]
        assert "internal_error" not in reasons

    def test_plan_accepts_mapping_candidates(self):
        plan = api.plan(_session(), candidates=[AS_MAPPING],
                        horizon_s=3600, step_s=600).to_dict()["plan"]
        assert plan["checked"]["candidates_evaluated"] >= 1

    def test_a_wrong_type_raises_rather_than_filing_a_decline(self):
        with pytest.raises(TypeError):
            api.rollout(_session(), actions=["throttle_pump"],
                        horizon_s=600, step_s=600)
