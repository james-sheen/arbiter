"""A plan none of whose actions ran does not report a cost for running them.

With `max_depth: 2` the planner offers a second setting of a property
already set at the same instant. The rollout refuses the pair -- correctly:
two settings at one instant have no answer, and `at_s` is the only ordering
this engine has -- so NOTHING is applied and the trajectory is the do-nothing
one. Measured on the shipped example at a 92 % tank, three such candidates
came back with `transitions_applied: 0` and `objective: 16.0`, which is
exactly `do_nothing`'s score, under a label naming two actions.

An earlier pass put `contradictory_actions` into those rows' `declines`, which
made the fact ATTRIBUTABLE. It left the number. A reader comparing rows still
saw *throttling to 800 and then to 1500 costs 16.0, the same as doing
nothing* -- a plan that reads as merely pointless rather than one that was
never tried. Those are different claims, and only the second is true.

So a candidate none of whose actions ran carries no objective, is not ranked,
and sorts to the end with its refusal beside it.

WHAT DOES NOT CHANGE. A candidate whose actions DID run keeps its score even
if something else about it declined. `do_nothing` keeps its score: it proposed
nothing, so *nothing ran* is not a complaint about it but the whole of what it
is. And the recommendation on the shipped example is identical before and
after -- the refused rows never won, because ties already broke toward fewer
actions. What changes is what the report claims to have measured.

A NOTE ON WHAT THIS FILE DOES NOT CLAIM. An action scheduled outside the
rollout's window ALREADY refuses, by name, with the window and the remedy in
the message -- `TestTheHorizonWindowAlreadyRefuses` below pins it. It is
recorded here because the probe that went looking for it reported silence:
it read `refused_actions` and `declines` off the simulation payload, where
neither key exists, got `None` from both, and called that *nothing declined*.
The refusals live in `not_checked`. A check that asks the wrong surface
returns a confident answer about nothing, which is the failure this whole
module is otherwise about.
"""
from __future__ import annotations

import pathlib
import tempfile
from pathlib import Path

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance


def _examples_dir() -> pathlib.Path:
    """Whichever copy this tree has: the built package ships `examples/` at its
    root, the source tree keeps them under the publication docs. Never an
    absolute path -- one names a directory that exists only where this file was
    written, and this file ships."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "docs" / "publication"
                      / "engine-example"):
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    raise AssertionError("no examples directory found in this tree")


EXAMPLE = _examples_dir() / "pump_tank_dynamics.yaml"
HORIZON_S, STEP_S = 3600.0, 300.0
BASE_LEVEL = 92.0

DEEP = EXAMPLE.read_text().replace(
    "  planning:\n    objective: expected_findings",
    "  planning:\n    objective: expected_findings\n    max_depth: 2")


def _session(model_text=None):
    session = api.EngineSession()
    if model_text is None:
        session.load_model(str(EXAMPLE))
    else:
        path = Path(tempfile.mkdtemp()) / "model.yaml"
        path.write_text(model_text)
        session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("tank1", "Tank", {"level_pct": BASE_LEVEL})
    session.add_relationship("pump1", "feeds", "tank1")
    return session


def _plan():
    return api.plan(_session(DEEP), horizon_s=HORIZON_S,
                    step_s=STEP_S).to_dict()["plan"]


class TestThePremise:

    def test_the_planner_still_offers_colliding_pairs(self):
        collided = [c for c in _plan()["candidates"]
                    if "contradictory_actions" in c["declines"]]
        assert collided, (
            "this fixture exists to exercise refused candidates; the planner "
            "no longer produces any, so the cases below are about nothing")
        for candidate in collided:
            assert candidate["checked"]["transitions_applied"] == 0, (
                "a refused candidate must have applied nothing")


class TestAPlanThatNeverRanCarriesNoScore:

    def test_a_refused_candidate_reports_no_objective(self):
        for candidate in _plan()["candidates"]:
            if "contradictory_actions" not in candidate["declines"]:
                continue
            assert candidate["objective"] is None, (
                f"{candidate['plan']} reports {candidate['objective']!r}; "
                f"none of its actions ran, so that number is do_nothing's "
                f"cost under a label naming {len(candidate['actions'])} "
                f"actions")

    def test_a_refused_candidate_still_says_why(self):
        """Unranked must not become unexplained."""
        for candidate in _plan()["candidates"]:
            if candidate["objective"] is None and candidate["actions"]:
                assert candidate["declines"], (
                    f"{candidate['plan']} is unranked and silent about it")

    def test_a_refused_candidate_sorts_behind_every_scored_one(self):
        objectives = [c["objective"] for c in _plan()["candidates"]]
        seen_none = False
        for value in objectives:
            if value is None:
                seen_none = True
            elif seen_none:
                pytest.fail(f"a scored candidate sorts after an unscored one: "
                            f"{objectives}")


class TestARefusedActionIsNotReportedAsApplied:
    """The reason the planner fix above could not be written as *did anything
    run*: the step said something ran.

    `actions_applied` holds `template@entity`, which carries neither the
    parameters nor `at_s`, so two instances of one template on one entity
    share a label. The loop appends once PER INSTANCE -- twice -- and the
    refusal removed once per DISTINCT label, over a set. One occurrence
    survived, so a step in which the pump never moved reported
    `throttle_pump@pump1` as applied.
    """

    def _refused_pair(self):
        return api.rollout(
            _session(),
            actions=[ActionInstance("throttle_pump", "pump1",
                                    {"speed_rpm": 800.0}, 0.0),
                     ActionInstance("throttle_pump", "pump1",
                                    {"speed_rpm": 1500.0}, 0.0)],
            horizon_s=HORIZON_S, step_s=STEP_S).to_dict()["simulation"]

    def test_the_premise_nothing_moved(self):
        simulation = self._refused_pair()
        assert simulation["checked"]["actions_refused"] == 1
        assert simulation["per_step"][0]["values"]["pump1"][
            "speed_rpm"] == pytest.approx(1000.0)

    def test_no_step_claims_the_refused_action_applied(self):
        simulation = self._refused_pair()
        claimed = [s["at_s"] for s in simulation["per_step"]
                   if s["actions_applied"]]
        assert not claimed, (
            f"steps at {claimed} report an action applied; the pair was "
            f"refused and the pump never moved")

    def test_one_action_is_still_reported_as_applied(self):
        """The floor, at the granularity the bug lived in: a single action
        must still show up."""
        simulation = api.rollout(
            _session(),
            actions=[ActionInstance("throttle_pump", "pump1",
                                    {"speed_rpm": 1500.0}, 0.0)],
            horizon_s=HORIZON_S, step_s=STEP_S).to_dict()["simulation"]
        assert ["throttle_pump@pump1"] == simulation["per_step"][0][
            "actions_applied"]

    def test_the_same_setting_twice_is_applied_once_and_reported(self):
        """Redundant rather than contradictory: two identical settings are
        applied once, so the step DID act and must say so."""
        simulation = api.rollout(
            _session(),
            actions=[ActionInstance("throttle_pump", "pump1",
                                    {"speed_rpm": 1500.0}, 0.0),
                     ActionInstance("throttle_pump", "pump1",
                                    {"speed_rpm": 1500.0}, 0.0)],
            horizon_s=HORIZON_S, step_s=STEP_S).to_dict()["simulation"]
        assert simulation["per_step"][0]["actions_applied"], (
            "two identical settings compose to one setting, which happened")
        assert simulation["per_step"][0]["values"]["pump1"][
            "speed_rpm"] == pytest.approx(1500.0)


class TestWhatKeepsItsScore:

    def test_the_candidates_that_did_run_keep_theirs(self):
        scored = [c for c in _plan()["candidates"]
                  if c["checked"]["transitions_applied"] > 0]
        assert scored, "the fixture must still score real plans"
        assert all(c["objective"] is not None for c in scored)

    def test_do_nothing_still_scores(self):
        do_nothing = [c for c in _plan()["candidates"]
                      if c["plan"] == "do_nothing"]
        assert do_nothing and do_nothing[0]["objective"] == 16.0

    def test_the_recommendation_is_unchanged(self):
        assert _plan()["candidates"][0]["plan"] == "do_nothing", (
            "the tank is above its warning line and no candidate clears it, "
            "so the ranked winner is unchanged by this fix")

    def test_the_plan_still_counts_every_rollout_it_ran(self):
        """Not scoring a candidate is not the same as not running it, and the
        denominator must keep saying what the engine actually did."""
        checked = _plan()["checked"]
        assert checked["rollouts_run"] == 8
        assert checked["candidates_evaluated"] == 8


CLEARANCE = EXAMPLE.read_text().replace(
    "  planning:\n    objective: expected_findings",
    "  planning:\n    objective: clearance_probability\n"
    "    min_severity: warning")


class TestEachCandidateCarriesItsOwnAssumptions:
    """A stamp on the plan cannot say WHICH candidate it is about.

    `score` already returns its assumptions per candidate -- whether that
    candidate's clearance figure was sampled from a declared spread or came
    from a trajectory with none. They were merged into the plan-level list and
    the per-candidate fact was dropped, so a reader saw both
    `deterministic_transitions` and `declared_gain_spread_sampled` on one plan
    with no way to attribute either. That is the same unattributed shape the
    refused-candidate `declines` had, and `interval` does not disambiguate it:
    `[0.0, 0.0]` is what a deterministic candidate reports AND what a sampled
    one reports when no sample cleared.
    """

    def _plan(self, level=86.0):
        session = api.EngineSession()
        path = Path(tempfile.mkdtemp()) / "clearance.yaml"
        path.write_text(CLEARANCE)
        session.load_model(str(path))
        session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
        session.add_entity("tank1", "Tank", {"level_pct": level})
        session.add_relationship("pump1", "feeds", "tank1")
        return api.plan(session, horizon_s=HORIZON_S,
                        step_s=STEP_S).to_dict()["plan"]

    def test_the_premise_the_plan_carries_both_stamps(self):
        plan = self._plan()
        stamps = set(plan["assumptions"])
        assert {"deterministic_transitions",
                "declared_gain_spread_sampled"} <= stamps, (
            f"this fixture exists because one plan carries both: {stamps}")

    def test_every_candidate_reports_its_own(self):
        for candidate in self._plan()["candidates"]:
            assert "assumptions" in candidate, (
                "a candidate must say which assumptions its own number rests "
                "on")

    def test_a_candidate_that_moved_nothing_is_not_called_sampled(self):
        do_nothing = [c for c in self._plan()["candidates"]
                      if c["plan"] == "do_nothing"][0]
        assert "declared_gain_spread_sampled" not in do_nothing["assumptions"]
        assert "deterministic_transitions" in do_nothing["assumptions"], (
            "doing nothing moves nothing, so there is no declared spread to "
            "sample and the engine should say which case it is in")

    def test_a_candidate_that_moved_something_says_it_sampled(self):
        moved = [c for c in self._plan()["candidates"]
                 if c["checked"]["transitions_applied"] > 0]
        assert moved, "the fixture must still move something"
        assert any("declared_gain_spread_sampled" in c["assumptions"]
                   for c in moved)

    def test_the_plan_level_list_still_carries_the_union(self):
        """Per-candidate stamps are an addition, not a move."""
        plan = self._plan()
        union = set()
        for candidate in plan["candidates"]:
            union |= set(candidate["assumptions"])
        assert union <= set(plan["assumptions"])


class TestTheHorizonWindowAlreadyRefuses:
    """Not a fix -- a floor under behaviour that is already right, written
    because a probe claimed otherwise by reading a surface that does not
    exist. See this module's docstring."""

    def _outside(self, at_s):
        simulation = api.rollout(
            _session(),
            actions=[ActionInstance("throttle_pump", "pump1",
                                    {"speed_rpm": 2200.0}, at_s)],
            horizon_s=HORIZON_S, step_s=STEP_S).to_dict()["simulation"]
        return simulation, {d["reason"] for d in simulation["not_checked"]}

    def test_past_the_horizon_is_refused_by_name(self):
        simulation, reasons = self._outside(99999.0)
        assert "malformed_action" in reasons
        assert simulation["checked"]["actions_refused"] == 1
        assert simulation["per_step"][-1]["values"]["tank1"][
            "level_pct"] == pytest.approx(BASE_LEVEL)

    def test_the_refusal_names_the_action_the_window_and_the_remedy(self):
        simulation, _ = self._outside(99999.0)
        detail = [d["detail"] for d in simulation["not_checked"]
                  if d["reason"] == "malformed_action"][0]
        assert "99999" in detail and "3600" in detail
        assert "horizon_s" in detail

    def test_before_the_start_is_refused_too(self):
        _, reasons = self._outside(-99999.0)
        assert "malformed_action" in reasons

    def test_inside_the_window_is_not_refused(self):
        for at_s in (0.0, STEP_S, HORIZON_S):
            simulation, reasons = self._outside(at_s)
            assert "malformed_action" not in reasons, (
                f"an action at {at_s}s is inside a {HORIZON_S}s horizon")
            assert simulation["checked"]["actions_refused"] == 0
