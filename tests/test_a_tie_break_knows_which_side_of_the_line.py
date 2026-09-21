"""The tie-break reads a SIGNED headroom, not the absolute closest approach.

correcting. That one broke an exact tie toward the wider
`margin_sigmas` — and `margin_sigmas` is the minimum ABSOLUTE distance to any
line over the horizon, which is the right figure for the question it answers
and the wrong one to rank on.

WHY, MEASURED. Among candidates that BREACH, the absolute closest approach is
not a measure of the breach: it is wherever a discrete step happened to fall as
the trajectory crossed the line. Two candidates on the shipped model tie at
objective 1.667, one settling about 4 points past the band edge and one about 8
points past — the deeper one is worse — and they reported 1.443 and 0.089. At
`step_s=450` the reported margins swapped and **the engine preferred the deeper
breach**. The ranking moved with the step size rather than with the risk.

`margin_sigmas` also carries its own contract in its docstring: *it changes no
ranking*. An internal ruling contradicted that line. `clearance_sigmas` carries the job
instead, signed — positive is headroom, negative is how far the worst excursion
went past a line — so a larger value is further from a decision whether or not
the trajectory ever crossed one.

It is reported as well as ranked on, because it answers a question
`margin_sigmas` cannot: on the shipped model a candidate reports a margin of
0.920 while sitting 4.985 spreads PAST a line, and an absolute distance cannot
say which of those two a reader is looking at.
"""
from __future__ import annotations

import copy

import pytest
import yaml

from arbiter_engine import api

STAMP = "ties_break_toward_the_wider_margin"

MODEL = """
domain:
  id: signed_clearance
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


def _plan(candidates=None, step_s=600, drop_sigma=False):
    model = yaml.safe_load(MODEL)
    domain = model["domain"]
    if candidates is not None:
        domain["action_templates"][0]["parameters_schema"][
            "speed_rpm"]["candidates"] = candidates
    if drop_sigma:
        domain["relationship_rules"][0]["transition"].pop("gain_sigma")
    session = api.EngineSession()
    session.load_model(yaml.safe_dump(model, sort_keys=False))
    session.add_entity("pump1", "Pump", properties={"speed_rpm": 2000})
    session.add_entity("tank1", "Tank", properties={"level_pct": 50})
    session.add_observations("pump1", "speed_rpm", [2000.0] * 40)
    session.add_observations("tank1", "level_pct", [50.0] * 40)
    session.add_relationship("pump1", "feeds", "tank1")
    return api.plan(session, horizon_s=3600, step_s=step_s).to_dict()["plan"]


def _rows(plan):
    out = {}
    for candidate in plan["candidates"]:
        actions = candidate.get("actions") or []
        key = ("do_nothing" if not actions
               else int(actions[0]["parameters"]["speed_rpm"]))
        out[key] = candidate
    return out


def _order(plan):
    order = []
    for candidate in plan["candidates"]:
        actions = candidate.get("actions") or []
        order.append("do_nothing" if not actions
                     else int(actions[0]["parameters"]["speed_rpm"]))
    return order


class TestTheRankNoLongerMovesWithTheStepSize:
    """The defect that an internal ruling shipped, pinned so it cannot come back."""

    @pytest.mark.parametrize("step_s", [600, 450, 300, 200, 120])
    def test_the_shallower_breach_wins_at_every_step_size(self, step_s):
        # 1100 settles about twice as far past the band edge as 1300.
        order = _order(_plan([1300, 1100], step_s=step_s))
        assert order.index(1300) < order.index(1100)

    def test_and_the_two_really_do_tie_on_the_objective(self):
        """Without the tie there is nothing for a tie-break to get wrong."""
        rows = _rows(_plan([1300, 1100]))
        assert rows[1300]["objective"] == pytest.approx(
            rows[1100]["objective"])

    def test_the_absolute_figure_still_swings_and_no_longer_decides(self):
        """`margin_sigmas` is unchanged — it is the absolute closest approach
        and it does move with the step size. What changed is that nothing
        ranks on it."""
        wide = _rows(_plan([1300, 1100], step_s=600))[1300]["margin_sigmas"]
        tight = _rows(_plan([1300, 1100], step_s=300))[1300]["margin_sigmas"]
        assert wide != pytest.approx(tight)


class TestTheSignedFigureSaysWhichSide:

    def test_a_clear_candidate_is_positive_and_equals_its_margin(self):
        rows = _rows(_plan())
        for speed in (1500, 2200):
            assert rows[speed]["clearance_sigmas"] > 0
            assert rows[speed]["clearance_sigmas"] == pytest.approx(
                rows[speed]["margin_sigmas"], abs=1e-6)

    def test_a_breaching_candidate_is_negative_and_its_margin_is_not(self):
        """The case an absolute distance cannot express: a reassuring 0.92
        that is really five spreads the wrong side of a line."""
        row = _rows(_plan())[3000]
        assert row["margin_sigmas"] == pytest.approx(0.920, abs=1e-2)
        assert row["clearance_sigmas"] == pytest.approx(-4.985, abs=1e-2)

    def test_do_nothing_declares_no_headroom_at_all(self):
        assert _rows(_plan())["do_nothing"]["clearance_sigmas"] is None


class TestTheOrderIsStillIndependentOfTheYaml:

    @pytest.mark.parametrize("candidates", [
        [800, 1500, 2200, 3000],
        [800, 2200, 1500, 3000],
        [3000, 2200, 1500, 800],
    ])
    def test_the_clearer_of_two_tied_candidates_wins(self, candidates):
        order = _order(_plan(candidates))
        assert order.index(2200) < order.index(1500)


class TestAModelWithNoDeclaredSpreadIsStillUNCHANGED:

    def test_no_signed_headroom_and_no_stamp(self):
        plan = _plan(drop_sigma=True)
        assert all(c.get("clearance_sigmas") is None
                   for c in plan["candidates"])
        assert STAMP not in plan["assumptions"]
        assert _order(plan) == ["do_nothing", 1500, 2200, 3000, 800]
