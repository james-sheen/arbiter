"""An exact tie is broken by the declared spread, not by YAML order.

The ranking sorted on `(objective, len(actions))`, so two candidates
with the same objective AND the same action count fell to insertion order --
which is the order the author happened to list them in `candidates:`.

MEASURED on the shipped pump-and-tank model. Two candidates tie at
`expected_findings` 0.000: `speed_rpm=1500` settles 0.03 declared spreads from
the HOMEOSTASIS edge that decides whether it files a finding, and
`speed_rpm=2200` settles 15.08 spreads clear of it. Scored by the engine's own
sampler under `clearance_probability` on the same rollouts, those are 0.43 and
1.00. Swapping the two entries in the YAML swapped their rank, so a candidate
that breaches more than half the time outranked one that never does, on the
strength of where it was written down.

THIS IS THE EXISTING COMMENT'S OWN ARGUMENT, ONE STEP FURTHER. The block that
added `len(actions)` says sorting on the objective alone left the tie to
insertion order, so the right answer came out for the wrong reason and would
change the first time the evaluation order did. That was true between
`do_nothing` and an action. It stayed true between two actions.

NOT AN INVENTED PREFERENCE. `gain_sigma:` is the author's, `margin_sigmas` is
the distance to the nearest line in units of it, and further from a decision is
the direction `clearance_probability` already optimises. A candidate carrying
no measured margin sorts LAST among its ties, so a model that declares no
spread keeps the order it has today -- pinned below, because a tie-break that
quietly reorders an undeclared model would be the engine deciding a domain
question.
"""
from __future__ import annotations

import copy

import pytest
import yaml

from arbiter_engine import api

STAMP = "ties_break_toward_the_wider_margin"
SIBLING = "ties_break_toward_fewer_actions"

MODEL = """
domain:
  id: margin_tiebreak
  name: A pump feeding a tank
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


def _plan(order=None, drop_sigma=False, objective="expected_findings",
          min_severity=None):
    model = yaml.safe_load(MODEL)
    domain = model["domain"]
    domain["planning"] = {"objective": objective}
    if min_severity:
        domain["planning"]["min_severity"] = min_severity
    if order is not None:
        domain["action_templates"][0]["parameters_schema"][
            "speed_rpm"]["candidates"] = order
    if drop_sigma:
        domain["relationship_rules"][0]["transition"].pop("gain_sigma")
    session = api.EngineSession()
    session.load_model(yaml.safe_dump(model, sort_keys=False))
    session.add_entity("pump1", "Pump", properties={"speed_rpm": 2000})
    session.add_entity("tank1", "Tank", properties={"level_pct": 50})
    session.add_observations("pump1", "speed_rpm", [2000.0] * 40)
    session.add_observations("tank1", "level_pct", [50.0] * 40)
    session.add_relationship("pump1", "feeds", "tank1")
    return api.plan(session, horizon_s=3600, step_s=600).to_dict()["plan"]


def _order(plan):
    out = []
    for candidate in plan["candidates"]:
        actions = candidate.get("actions") or []
        out.append("do_nothing" if not actions
                   else int(actions[0]["parameters"]["speed_rpm"]))
    return out


class TestTheTieWasRealAndArbitrary:
    """The measurement that makes this worth changing at all."""

    def test_the_two_candidates_do_tie_on_the_objective(self):
        by_speed = {s: c for s, c in zip(_order(_plan()),
                                         _plan()["candidates"])}
        assert by_speed[1500]["objective"] == pytest.approx(0.0)
        assert by_speed[2200]["objective"] == pytest.approx(0.0)
        assert len(by_speed[1500]["actions"]) == len(by_speed[2200]["actions"])

    def test_and_the_engine_had_already_measured_the_difference(self):
        by_speed = {s: c for s, c in zip(_order(_plan()),
                                         _plan()["candidates"])}
        assert by_speed[1500]["margin_sigmas"] == pytest.approx(0.030, abs=5e-3)
        assert by_speed[2200]["margin_sigmas"] == pytest.approx(15.076, abs=1e-2)

    def test_the_engines_own_sampler_agrees_they_are_not_alike(self):
        """`clearance_probability` on the same rollouts and the same declared
        spread: a coin flip beside a certainty."""
        plan = _plan(objective="clearance_probability", min_severity="warning")
        by_speed = {s: c for s, c in zip(_order(plan), plan["candidates"])}
        assert by_speed[1500]["objective"] < 0.75
        assert by_speed[2200]["objective"] == pytest.approx(1.0)


class TestTheRankIsNoLongerTheYamlOrder:

    @pytest.mark.parametrize("order", [
        [800, 1500, 2200, 3000],
        [800, 2200, 1500, 3000],
        [3000, 2200, 1500, 800],
    ])
    def test_the_wider_margin_wins_however_they_are_listed(self, order):
        ranked = _order(_plan(order))
        assert ranked.index(2200) < ranked.index(1500)

    def test_do_nothing_still_wins_before_any_margin_is_consulted(self):
        """Action count is read first, and `do_nothing` carries no margin at
        all -- so a rule that sorted an absent margin last must not reach it."""
        plan = _plan()
        assert plan["best"] == "do_nothing"
        assert _order(plan)[0] == "do_nothing"
        by_speed = {s: c for s, c in zip(_order(plan), plan["candidates"])}
        assert by_speed["do_nothing"]["margin_sigmas"] is None


class TestAModelWithNoDeclaredSpreadIsUNCHANGED:
    """The non-breaking guarantee, pinned rather than asserted."""

    def test_the_order_falls_back_to_the_declaration(self):
        assert _order(_plan(drop_sigma=True)) == [
            "do_nothing", 1500, 2200, 3000, 800]

    def test_and_the_stamp_does_not_claim_a_rule_that_cannot_fire(self):
        assert STAMP not in _plan(drop_sigma=True)["assumptions"]
        assert SIBLING in _plan(drop_sigma=True)["assumptions"]


class TestTheStampIsPresentWhenTheRuleCanFire:

    def test_both_tie_break_rules_are_named(self):
        assumptions = _plan()["assumptions"]
        assert STAMP in assumptions
        assert SIBLING in assumptions


class TestNoReportedNumberMoved:
    """ reorders exact ties. It must not change an objective."""

    def test_the_objectives_are_what_they_were(self):
        by_speed = {s: c for s, c in zip(_order(_plan()),
                                         _plan()["candidates"])}
        assert by_speed["do_nothing"]["objective"] == pytest.approx(0.0)
        assert by_speed[1500]["objective"] == pytest.approx(0.0)
        assert by_speed[2200]["objective"] == pytest.approx(0.0)
        assert by_speed[3000]["objective"] == pytest.approx(2.0)
        assert by_speed[800]["objective"] == pytest.approx(16.0 / 3.0)
