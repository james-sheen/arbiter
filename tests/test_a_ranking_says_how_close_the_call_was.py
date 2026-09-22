"""`expected_findings` is the median trajectory's count, and the engine says so.

The objective sums severity weights over the findings a rollout
produced. Those findings come from comparing imagined values against declared
lines, so the objective is a STEP FUNCTION of a quantity the engine frequently
knows only to within a declared spread -- and it is evaluated at the median
trajectory alone, with no part of that spread reaching the figure the ranking
uses.

Measured on the shipped example, throttling to 800 rpm (which moves the tank
by `gain 0.02 *-200 rpm` = -4.0) against a `warning: 85`:

    starts at settles at objective
      88.8 84.812 14.000
      88.9 84.912 14.333
      89.0 85.012 16.000

A tenth of a point of level moves the ranking by 12 %, while the engine's own
declared spread on that very value at that very step is 0.3988 -- four times
the distance that flipped it. The candidate's `interval` was `None`
throughout: the doubt was computed, carried, reported per step, and then not
carried into the number the plan is ranked on.

WHAT THIS FILE DOES AND DOES NOT CHANGE. It does not make the objective an
expectation. Doing that honestly needs the probability of each of eight
axioms firing over a trajectory, not just a threshold crossing, and inventing
that would be the engine answering a question nobody declared. It does not
change any ranking. What it adds is the two things the engine was in a
position to say and did not:

  - `objective_evaluated_at_median`, stamped whenever a plan is ranked, so a
    reader of the ENVELOPE -- not just of the guide -- knows the figure is the
    median trajectory's count and not an average over the declared spread;
  - `margin_sigmas` on each candidate: the closest any imagined value came to
    a line it was judged against, in units of that value's own declared
    spread. A MEASUREMENT, not a decision. It is the number that tells a
    reader whether a 14.333-against-16.000 ranking turned on a real
    difference or on a coin flip, and the engine already computed both halves
    of it for `clearance_probability`.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance


def _examples_dir() -> pathlib.Path:
    """Whichever copy this tree has; never an absolute path -- one names a
    directory that exists only where this file was written, and this file ships."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "docs" / "publication"
                      / "engine-example"):
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    raise AssertionError("no examples directory found in this tree")


EXAMPLE = _examples_dir() / "pump_tank_dynamics.yaml"
SOURCE = EXAMPLE.read_text()
HORIZON_S, STEP_S = 3600.0, 300.0
WARNING = 85.0

#: The same model with every declared spread removed, which is how a reader
#: gets the deterministic case.
NO_SPREAD = SOURCE.replace("gain_sigma: 0.002", "source: datasheet")


def _session(level, model_text=None):
    session = api.EngineSession()
    if model_text is None:
        session.load_model(str(EXAMPLE))
    else:
        path = pathlib.Path(tempfile.mkdtemp()) / "model.yaml"
        path.write_text(model_text)
        session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("tank1", "Tank", {"level_pct": level})
    session.add_relationship("pump1", "feeds", "tank1")
    return session


def _plan(level, model_text=None):
    return api.plan(_session(level, model_text), horizon_s=HORIZON_S,
                    step_s=STEP_S).to_dict()["plan"]


def _throttled(plan):
    return [c for c in plan["candidates"] if "800" in c["plan"]][0]


def _settled(level):
    action = [ActionInstance("throttle_pump", "pump1",
                             {"speed_rpm": 800.0}, 0.0)]
    last = api.rollout(_session(level), actions=action, horizon_s=HORIZON_S,
                       step_s=STEP_S).to_dict()["simulation"]["per_step"][-1]
    return (last["values"]["tank1"]["level_pct"],
            last["sigma"]["tank1"]["level_pct"])


class TestThePremise:
    """If throttling stops landing the tank either side of its warning line,
    this file stops being about anything and should say so."""

    def test_a_tenth_of_a_point_straddles_the_line(self):
        below, _ = _settled(88.9)
        above, _ = _settled(89.0)
        assert below < WARNING < above, (below, WARNING, above)

    def test_the_declared_spread_is_wider_than_that_gap(self):
        below, spread = _settled(88.9)
        above, _ = _settled(89.0)
        assert spread > (above - below), (
            f"the spread {spread} must exceed the {above - below} gap that "
            f"flips the objective, or this is not a knife edge")

    def test_the_objective_really_does_step(self):
        assert _throttled(_plan(88.9))["objective"] != _throttled(
            _plan(89.0))["objective"]


class TestTheEnvelopeSaysWhereTheFigureWasTaken:

    def test_a_ranked_plan_stamps_that_it_used_the_median(self):
        assert "objective_evaluated_at_median" in _plan(89.0)["assumptions"]

    def test_an_unranked_plan_does_not(self):
        """No objective declared, nothing ranked, nothing to qualify."""
        unranked = SOURCE.replace("  planning:\n    objective: "
                                  "expected_findings", "  planning:\n"
                                  "    max_depth: 1")
        plan = _plan(89.0, unranked)
        assert not plan["ranked"]
        assert "objective_evaluated_at_median" not in plan["assumptions"]


class TestEachCandidateSaysHowCloseItsCallWas:

    def test_a_knife_edge_candidate_reports_a_small_margin(self):
        candidate = _throttled(_plan(88.9))
        assert candidate["margin_sigmas"] is not None, (
            "a declared spread reached this trajectory, so the distance to "
            "the line it was judged against is measurable")
        assert candidate["margin_sigmas"] < 1.0, (
            f"the tank settles {candidate['margin_sigmas']} spreads from its "
            f"warning line; under one sigma is what makes the ranking a coin "
            f"flip")

    def test_a_candidate_far_from_any_line_reports_a_large_margin(self):
        far = _throttled(_plan(60.0))
        near = _throttled(_plan(88.9))
        assert far["margin_sigmas"] > near["margin_sigmas"]

    def test_it_is_none_when_no_spread_was_declared(self):
        """The engine reports no margin rather than a zero one: a distance in
        units of a spread nobody declared is not a measurement."""
        candidate = _throttled(_plan(88.9, NO_SPREAD))
        assert candidate["margin_sigmas"] is None

    def test_the_premise_of_that_case(self):
        assert "gain_sigma" not in NO_SPREAD


class TestNothingAboutTheRankingMoves:
    """The floors. This round reports; it decides nothing."""

    def test_the_objectives_are_unchanged(self):
        assert _throttled(_plan(88.9))["objective"] == pytest.approx(
            14.333333333333334)
        assert _throttled(_plan(89.0))["objective"] == 16.0

    def test_the_winner_is_unchanged(self):
        assert _plan(92.0)["candidates"][0]["plan"] == "do_nothing"

    def test_the_tie_break_stamp_is_still_there(self):
        assert "ties_break_toward_fewer_actions" in _plan(89.0)["assumptions"]
