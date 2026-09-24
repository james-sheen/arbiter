"""Every surface that reports findings reports a WARNING-severity one.

`DetectionResult` carries findings in two legs, `problems` and
`warnings`. `check` has summed them since it was written and `envelope.py`
does too. Three other readers in the published cut took the first leg only,
and each of them is a surface whose whole claim is *the eight axioms, applied
to something*:

- `forecast/shadow.py` — the axioms over a forecast. Measured on a model
  declaring `warning: 80` and `critical: 95`, a forecast of 98 produced
  `forecast_threshold_exceeded` and a forecast of 85 produced NOTHING, with no
  decline saying why. The coherence check generative models are said to lack
  was itself checking one severity.
- `twin/monte_carlo_predictor.py` — an outcome probability computed from
  `problems` alone answers a narrower question than the one asked.
- `twin/rollout.py` — a node at 88% against a declared `warning: 80` produced
  two findings through `check` and none through a rollout over the identical
  values, which made a planner rank *causes a warning* level with *causes
  nothing*.

WHY THIS FILE IS BEHAVIOURAL AND NOT A GREP. A structural test for
`.warnings` beside every `.problems` would flag a platform detector that
reads `problems` to count them in a debug log and collects warnings separately
and correctly. The property worth pinning is not the spelling; it is that a
declared warning threshold, crossed, is reported. So each surface is driven
across a warning line and asked.
"""
from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.twin.traverser import IMAGINED_PREFIX

MODEL = """
domain:
  id: warnings
  name: A band with a warning and a critical
  entity_types: [Node]
  relationship_types: [hosts]
  indicators:
    Node:
      - name: memory_used_pct
        type: NUMERIC
        role: percentage
        axioms: [BOUNDEDNESS]
        warning: 80
        critical: 95
        forecast:
          expected: true
          models: [m1]
          expected_from: [m1]
          max_age: 15m
"""

INSIDE, OVER_WARNING, OVER_CRITICAL = 50.0, 85.0, 98.0


@pytest.fixture
def model_path(tmp_path):
    path = tmp_path / "warnings.yaml"
    path.write_text(MODEL)
    return str(path)


def _session(model_path, value):
    session = api.EngineSession()
    session.load_model(model_path)
    session.add_entity("node1", "Node", {"memory_used_pct": value})
    return session


def _types(payload):
    return {f["problem_type"] for f in payload.get("findings", [])}


class TestCheckIsTheReference:
    """The surface that was always right. If this stops firing, the rest of
    the file is comparing against nothing."""

    @pytest.mark.parametrize("value,expected", [
        (INSIDE, False), (OVER_WARNING, True), (OVER_CRITICAL, True)])
    def test_check_reports_across_the_whole_band(self, model_path, value,
                                                 expected):
        found = _types(api.check(_session(model_path, value)).to_dict())
        assert bool(found) is expected

    def test_the_warning_case_is_a_warning_and_not_a_critical(self,
                                                              model_path):
        payload = api.check(_session(model_path, OVER_WARNING)).to_dict()
        assert [f["severity"] for f in payload["findings"]] == ["warning"]


class TestTheShadowPassSeesAWarning:

    def _shadow(self, model_path, forecast_value):
        session = _session(model_path, INSIDE)
        api.ingest_forecasts(session, [{
            "entity_id": "node1", "property": "memory_used_pct",
            "model_id": "m1", "horizon_s": 900, "issued_at": api.now_utc(),
            "quantiles": {"q05": forecast_value - 2,
                          "q50": forecast_value,
                          "q95": forecast_value + 2}}])
        return _types(api.run_shadow_check(session).to_dict())

    def test_a_forecast_over_the_warning_line_is_reported(self, model_path):
        assert self._shadow(model_path, OVER_WARNING) == {
            "forecast_threshold_warning:memory_used_pct"}

    def test_a_forecast_over_the_critical_line_is_still_reported(
            self, model_path):
        assert self._shadow(model_path, OVER_CRITICAL) == {
            "forecast_threshold_exceeded:memory_used_pct"}

    def test_a_forecast_inside_the_band_reports_nothing(self, model_path):
        """Guard: a surface that fires on everything is no better."""
        assert self._shadow(model_path, INSIDE) == set()


class TestARolloutSeesAWarning:

    def test_a_rollout_agrees_with_check_across_the_band(self, model_path):
        for value in (INSIDE, OVER_WARNING, OVER_CRITICAL):
            checked = _types(api.check(_session(model_path, value)).to_dict())
            rolled = _types(api.rollout(
                _session(model_path, value),
                horizon_s=120.0, step_s=60.0).to_dict())
            assert bool(checked) is bool(rolled), (
                f"at {value}, check says {checked} and rollout says {rolled}")

    def test_the_rollout_finding_is_the_prefixed_twin_of_the_live_one(
            self, model_path):
        checked = _types(api.check(_session(model_path, OVER_WARNING)).to_dict())
        rolled = _types(api.rollout(
            _session(model_path, OVER_WARNING),
            horizon_s=120.0, step_s=60.0).to_dict())
        assert rolled == {IMAGINED_PREFIX + t for t in checked}


class TestAPlanCanTellTheTwoApart:
    """The consequence. A planner blind to warnings ranks a plan that causes
    one level with a plan that causes nothing, and recommends either."""

    PLANNING = """
domain:
  id: plan-warnings
  name: Two remedies, one of which causes a warning
  entity_types: [Node]
  relationship_types: [hosts]
  indicators:
    Node:
      - name: memory_used_pct
        type: NUMERIC
        role: percentage
        axioms: [BOUNDEDNESS]
        warning: 80
        critical: 95
  action_templates:
    - name: set_memory
      applies_to: Node
      parameters_schema:
        memory_used_pct:
          type: number
          entity_property: memory_used_pct
          candidates: [50, 85]
      effect: set
  planning:
    objective: expected_findings
"""

    def test_the_plan_causing_a_warning_scores_worse(self, tmp_path):
        path = tmp_path / "planwarn.yaml"
        path.write_text(self.PLANNING)
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("node1", "Node", {"memory_used_pct": 50.0})
        payload = api.plan(session, horizon_s=120.0,
                           step_s=60.0).to_dict()["plan"]
        by_plan = {c["plan"]: c["objective"] for c in payload["candidates"]}
        quiet = next(v for k, v in by_plan.items() if "50" in k)
        noisy = next(v for k, v in by_plan.items() if "85" in k)
        assert noisy > quiet, (
            "setting memory to 85 crosses a declared warning line and setting "
            "it to 50 does not; a planner that scores them equally is blind "
            "to the severity it was asked to minimise")
