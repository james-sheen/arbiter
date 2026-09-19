"""`rollout` and `plan` report what they ATTEMPTED, not what they found.

BOTH VERBS BUILT `checked.invariants` OUT OF THEIR OWN FINDINGS.
`api.rollout` summed the findings and the axiom-shaped declines; `planner`
summed the findings alone. `interfaces.py` carries `evaluations_attempted` for
exactly this and says in its own comment why the sum is not a substitute: an
evaluation that ran and found nothing appears in neither list.

Two things follow, and both were live. A rollout whose imagined states breach
nothing reported `checked.invariants: 0` -- indistinguishable from `no axiom
was ever evaluated`, which is the zero-denominator shape this engine exists to
prevent and which 0.2.3 had just fixed for the shadow leg. And the denominator
moved with its own numerator: every breach added one to both, so the ratio a
reader computes from them could never fall.

Measured before the fix, on the fixture below: five steps over two declared
BOUNDEDNESS indicators, nothing breached, nothing declined, and
`checked.invariants: 0`.

`check` has always reported the attempted count (`envelope.py`), and
`traverse` reports its traversal-side twin. These two verbs used neither.
"""
from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance

MODEL = """
domain:
  id: counted
  name: Two indicators, one reachable ceiling
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS],
         warning: %(warning)s, critical: 9e9}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02, source: datasheet}
  action_templates:
    - name: throttle_pump
      applies_to: Pump
      parameters_schema:
        speed_rpm:
          type: number
          entity_property: speed_rpm
          candidates: [1000, 4000]
      effect: set
      settle_s: 0
      source: runbook
  planning:
    objective: expected_findings
"""

STEPS = 5
INDICATORS = 2


def _session(tmp_path, name, warning="9e9"):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL % {"warning": warning})
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_relationship("pump1", "feeds", "tank1")
    return session


class TestACleanRolloutStillHasADenominator:

    def test_a_rollout_that_finds_nothing_counts_what_it_ran(self, tmp_path):
        envelope = api.rollout(_session(tmp_path, "clean"),
                               horizon_s=300.0, step_s=60.0).to_dict()
        assert envelope["findings"] == []
        assert envelope["simulation"]["not_checked"] == []
        assert envelope["checked"]["invariants"] > 0, (
            "five steps evaluated two declared BOUNDEDNESS states each and "
            "the denominator says nothing ran")

    def test_the_count_is_the_states_actually_evaluated(self, tmp_path):
        envelope = api.rollout(_session(tmp_path, "exact"),
                               horizon_s=300.0, step_s=60.0).to_dict()
        assert envelope["checked"]["invariants"] == STEPS * INDICATORS

    def test_every_step_carries_its_own_count(self, tmp_path):
        simulation = api.rollout(_session(tmp_path, "perstep"),
                                 horizon_s=300.0,
                                 step_s=60.0).to_dict()["simulation"]
        per_step = simulation["per_step"]
        assert len(per_step) == STEPS
        assert all(step["invariants"] == INDICATORS for step in per_step)
        assert sum(step["invariants"] for step in per_step) == STEPS * INDICATORS


class TestTheDenominatorDoesNotMoveWithTheNumerator:
    """The property that makes a denominator worth reporting."""

    def test_a_breach_changes_the_findings_and_not_the_count(self, tmp_path):
        clean = api.rollout(_session(tmp_path, "a"),
                            horizon_s=300.0, step_s=60.0).to_dict()
        # Same model, same steps, same indicators -- only the declared warning
        # line moves, so the same evaluations now produce a finding.
        breached = api.rollout(
            _session(tmp_path, "b", warning="60"),
            actions=[ActionInstance("throttle_pump", "pump1",
                                    {"speed_rpm": 4000.0}, 0.0)],
            horizon_s=300.0, step_s=60.0).to_dict()
        assert breached["findings"], "the fixture was meant to breach"
        assert clean["findings"] == []
        assert breached["checked"]["invariants"] == clean["checked"][
            "invariants"], (
            "the same states were evaluated in both runs; a denominator that "
            "grows because a finding appeared is counting the numerator")


class TestPlanCountsWhatItsRolloutsRan:

    def test_a_clean_candidate_contributes_its_evaluations(self, tmp_path):
        envelope = api.plan(_session(tmp_path, "planned"),
                            horizon_s=300.0, step_s=60.0).to_dict()
        assert envelope["plan"]["candidates"], "no candidate was evaluated"
        assert envelope["checked"]["invariants"] > 0, (
            "every candidate was rolled out and judged, and the denominator "
            "reports nothing was")
