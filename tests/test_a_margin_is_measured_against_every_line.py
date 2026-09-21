"""The margin figures see every axiom that judged the value, not one of them.

`planner._bounds_for` read `axiom_states["BOUNDEDNESS:{prop}"]` by
name, and both figures built on it -- `margin_sigmas` through `_closest_call`,
`clearance_probability` through `_worst_margin` -- had therefore never seen a
HOMEOSTASIS band.

WHAT THAT COST, measured on the shipped pump-and-tank model, whose every plan
finding is `imagined_homeostasis_setpoint`. The `speed_rpm=1500` candidate
ties for best at objective 0.000 and settles at 40.03 against a band edge at
40: **0.03 spreads from filing a finding, reported as 45.1 spreads clear.**
Candidates already breaching the band reported comfortable positive margins,
because the only lines in view were a ceiling far above them.

So `plan` ranked on findings from every axiom and stated its confidence from
one. `margin_sigmas` exists precisely so a ranking that hinges on a tenth of a
point is visibly a coin flip, which is the one job it could not do.

`_closest_call`'s own docstring describes this bug class one layer up: it
records fixing the signed-versus-absolute half after a knife-edge candidate
read 27.6 spreads clear while sitting 0.22 spreads under its line. The
which-lines half was left, and produces the same sentence with bigger numbers.

WHICH LINES AN AXIOM DECLARES IS THE AXIOM'S OWN BUSINESS. The derivation
lives on `AxiomState.declared_lines` and the planner asks every state judging
the property, so the next axiom that declares a line cannot be added to the
reasoner and not to this figure -- the shape that an internal ruling fixed for the floor half
of BOUNDEDNESS and described as a class while fixing one instance of it.
"""
from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.twin.topology import AxiomState
from arbiter_engine.types import Axiom, Severity

MODEL = """
domain:
  id: margin_lines
  name: A tank judged by a ceiling and a band
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS],
         critical: 9000, window: 30m}
    Tank:
      - name: level_pct
        type: NUMERIC
        axioms: [BOUNDEDNESS, HOMEOSTASIS]
        warning: 85
        critical: 95
        window: 30m
        homeostasis: {setpoint: 50, tolerance: 10}
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
                    candidates: [800, 1500, 2200, 3000]}
      effect: set
      settle_s: 0
      source: runbook
  planning:
    objective: expected_findings
"""


def _plan():
    s = api.EngineSession()
    s.load_model(MODEL)
    s.add_entity("pump1", "Pump", properties={"speed_rpm": 2000})
    s.add_entity("tank1", "Tank", properties={"level_pct": 50})
    s.add_observations("pump1", "speed_rpm", [2000.0] * 40)
    s.add_observations("tank1", "level_pct", [50.0] * 40)
    s.add_relationship("pump1", "feeds", "tank1")
    return api.plan(s, horizon_s=3600, step_s=600).to_dict()["plan"]


def _by_speed(plan):
    out = {}
    for c in plan["candidates"]:
        acts = c.get("actions") or []
        key = ("do_nothing" if not acts
               else int(acts[0]["parameters"]["speed_rpm"]))
        out[key] = c
    return out


class TestTheAxiomOwnsItsLines:
    """The contract, exercised directly, so a planner change cannot hide it."""

    def test_boundedness_reports_its_four_bounds(self):
        state = AxiomState(axiom=Axiom.BOUNDEDNESS, verdict=Severity.INFO,
                           indicator_name="level_pct",
                           evidence={"warning": 85, "critical": 95,
                                     "lower_warning": 5})
        assert sorted(state.declared_lines()) == [
            (5.0, False), (85.0, True), (95.0, True)]

    def test_homeostasis_reports_a_band_as_two_lines(self):
        state = AxiomState(axiom=Axiom.HOMEOSTASIS, verdict=Severity.INFO,
                           indicator_name="level_pct",
                           evidence={"homeostasis": {"setpoint": 50,
                                                     "tolerance": 10}})
        assert sorted(state.declared_lines()) == [(40.0, False), (60.0, True)]

    def test_a_setpoint_without_a_tolerance_declares_no_line(self):
        """Refused rather than given a width, for the reason the axiom gives:
        the engine has no basis for guessing how far is too far."""
        state = AxiomState(axiom=Axiom.HOMEOSTASIS, verdict=Severity.INFO,
                           indicator_name="level_pct",
                           evidence={"homeostasis": {"setpoint": 50}})
        assert state.declared_lines() == []

    def test_an_axiom_that_declares_no_line_reports_none(self):
        state = AxiomState(axiom=Axiom.STABILITY, verdict=Severity.INFO,
                           indicator_name="level_pct",
                           evidence={"warning": 85})
        assert state.declared_lines() == []


class TestTheKnifeEdgeIsVisible:

    def test_the_tying_candidate_reports_its_real_margin(self):
        """40.03 against a band edge at 40, over a spread of 0.997.

        Before this change the same candidate reported 45.1 -- the distance to
        the BOUNDEDNESS warning at 85, which is not the line it is about to
        cross.
        """
        candidate = _by_speed(_plan())[1500]
        assert candidate["objective"] == pytest.approx(0.0)
        assert candidate["margin_sigmas"] == pytest.approx(0.0304, abs=5e-3)

    def test_the_comfortable_candidate_still_reads_comfortable(self):
        candidate = _by_speed(_plan())[2200]
        assert candidate["margin_sigmas"] == pytest.approx(15.076, abs=1e-2)

    def test_a_breaching_candidate_no_longer_reports_a_ceiling_away(self):
        """Both of these file a HOMEOSTASIS finding. A margin measured to a
        line they are nowhere near said they were clear."""
        by_speed = _by_speed(_plan())
        for speed, was in ((3000, 7.553), (800, 24.628)):
            candidate = by_speed[speed]
            assert candidate["objective"] > 0.0
            assert candidate["margin_sigmas"] < was / 2.0


class TestTheRankingIsUnchanged:
    """ corrects a FIGURE, not the objective it annotates."""

    def test_do_nothing_still_wins_and_the_objectives_hold(self):
        plan = _plan()
        assert plan["ranked"] is True
        by_speed = _by_speed(plan)
        assert by_speed["do_nothing"]["objective"] == pytest.approx(0.0)
        assert by_speed[3000]["objective"] == pytest.approx(2.0)
        assert by_speed[800]["objective"] == pytest.approx(16.0 / 3.0)
