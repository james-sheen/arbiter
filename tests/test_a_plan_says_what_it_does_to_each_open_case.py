"""A plan says what each candidate does to each open case, and ranks on none of it.

`plan` knew nothing of a case's outcome. Measured on engine
0.2.35 with the planning example and a case open on the tank's level: with no
`planning:` it ranked none of 9 candidates and its reply never mentioned the case;
`expected_findings` ranked first a plan that ends with the case open (it overshoots
under the setpoint band), the second ending clear; and `clearance_probability` at
the case's severity scored every candidate 0.0, since a case open now never stays
clear from the first step. The case's own declaration does not say what *solved*
means over a rollout -- *resolves first* and *clear at the end* pick different
plans -- so it is not an objective.

Each simulated candidate now reports, per open case, `first_clear_s` and
`clear_to_end_from_s` from its own rollout, by the predicate the case book records
a check `found` by. No ranking moves.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from arbiter_engine import api
from arbiter_engine.twin import planner
from arbiter_engine.twin.topology import SimulationDecline
from arbiter_engine.types import Severity


def _examples() -> Path:
    """The shipped examples, in whichever tree this file runs in."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples", here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / "pump_tank_planning.yaml").is_file():
            return candidate
    raise AssertionError("no examples directory in this tree carries them")


def _session(*, severity="warning", planning=True, case=True, unreached=False):
    model = yaml.safe_load((_examples() / "pump_tank_planning.yaml").read_text())
    model["domain"]["cases"] = {"severity": severity, "consecutive_checks": 2}
    if not planning:
        model["domain"].pop("planning")
    session = api.EngineSession()
    session.load_model(model)
    for entity_id, entity_type, properties in (
            ("pump1", "Pump", {"speed_rpm": 3000.0}),
            ("tank1", "Tank", {"level_pct": 97.0}),
            ("valve1", "Valve", {"open_pct": 0.0})):
        session.add_entity(entity_id, entity_type, properties)
    session.add_relationship("pump1", "feeds", "tank1")
    session.add_relationship("valve1", "drains", "tank1")
    if unreached:
        # A second tank, over its bound too, that no action and no edge reaches.
        session.add_entity("tank2", "Tank", {"level_pct": 97.0})
    api.check(session)
    opened = {}
    if case:
        opened["tank1"] = api.open_case(session, "tank1", "level_pct").to_dict()["case"]["case_id"]
    if unreached:
        opened["tank2"] = api.open_case(session, "tank2", "level_pct").to_dict()["case"]["case_id"]
    return session, opened


PAIR = "throttle_pump@pump1(speed_rpm=800.0)@0s + set_valve@valve1(open_pct={})@0s"


def _rows(leg, case_id):
    return {c["plan"]: next(((r["first_clear_s"], r["clear_to_end_from_s"])
                             for r in c["cases"] if r["case_id"] == case_id), "no row")
            for c in leg["candidates"]}


class TestTheMeasuredTable:

    def test_each_candidate_reports_both_instants(self):
        session, opened = _session()
        rows = _rows(api.plan(session).to_dict()["plan"], opened["tank1"])
        assert rows[PAIR.format("50.0")] == (600.0, None)       # clear, then under the band
        assert rows[PAIR.format("25.0")] == (780.0, 780.0)      # clear to the end
        assert rows[PAIR.format("75.0")] == (480.0, None)       # first clear, ends breached
        assert rows["throttle_pump@pump1(speed_rpm=800.0)@0s"] == (1260.0, 1260.0)
        assert rows["do_nothing"] == (None, None)

    def test_the_case_is_held_to_its_own_severity(self):
        """At `critical` a warning does not keep the case open: the plan that
        ends under the band, a warning, is clear to the end."""
        session, opened = _session(severity="critical")
        rows = _rows(api.plan(session).to_dict()["plan"], opened["tank1"])
        assert rows[PAIR.format("50.0")] == (420.0, 420.0)
        assert rows[PAIR.format("75.0")] == (360.0, None)      # under by more than 20

    def test_a_case_nothing_reaches_is_never_clear(self):
        session, opened = _session(unreached=True)
        leg = api.plan(session).to_dict()["plan"]
        assert set(_rows(leg, opened["tank2"]).values()) <= {(None, None), "no row"}
        assert _rows(leg, opened["tank1"])[PAIR.format("25.0")] == (780.0, 780.0)


class TestNoRankingMoves:

    def test_the_first_place_and_every_objective_are_what_they_were(self):
        with_case = api.plan(_session()[0]).to_dict()["plan"]
        without = api.plan(_session(case=False)[0]).to_dict()["plan"]
        assert with_case["best"] == without["best"] == PAIR.format("50.0")
        assert ({c["plan"]: c["objective"] for c in with_case["candidates"]}
                == {c["plan"]: c["objective"] for c in without["candidates"]})

    def test_with_no_objective_the_rows_are_there_and_nothing_is_ranked(self):
        """Ruling 3's own case: a model with `cases:` and no `planning:`."""
        session, opened = _session(planning=False)
        leg = api.plan(session).to_dict()["plan"]
        assert leg["ranked"] is False and "best" not in leg
        assert _rows(leg, opened["tank1"])["throttle_pump@pump1(speed_rpm=800.0)@0s"] == (1260.0, 1260.0)


class TestWhatIsNotMeasured:

    def test_no_open_case_no_rows(self):
        leg = api.plan(_session(case=False)[0]).to_dict()["plan"]
        assert {len(c["cases"]) for c in leg["candidates"]} == {0}

    def test_a_plan_whose_actions_were_refused_is_not_measured(self):
        """As it is not scored: it ran the do-nothing trajectory under a label
        naming two actions."""
        leg = api.plan(_session()[0]).to_dict()["plan"]
        refused = [c for c in leg["candidates"] if "contradictory_actions" in c["declines"]]
        assert refused and {len(c["cases"]) for c in refused} == {0}

    def test_a_step_that_declined_the_indicator_is_not_clear(self):
        """Silence is not health, as the case book's `not_looked` says."""
        quiet = SimpleNamespace(at_s=60.0, findings=[], declines=[
            SimulationDecline("insufficient_samples", "tank1.level_pct")])
        looked = SimpleNamespace(at_s=120.0, findings=[], declines=[])
        envelope = SimpleNamespace(steps=[quiet, looked])
        case = {"case_id": "c", "entity_id": "tank1", "indicator": "level_pct",
                "severity": "warning"}
        assert planner._case_outcomes(envelope, [case]) == [
            {"case_id": "c", "first_clear_s": 120.0, "clear_to_end_from_s": 120.0}]


def _step(at_s, *severities):
    return SimpleNamespace(at_s=at_s, declines=[], findings=[
        SimpleNamespace(entity_id="tank1", problem_type="imagined_threshold_warning:level_pct",
                        severity=severity, evidence={"indicator": "level_pct"})
        for severity in severities])


class TestTheTwoInstantsAreTwoQuestions:

    CASE = {"case_id": "c", "entity_id": "tank1", "indicator": "level_pct",
            "severity": "warning"}

    def test_clear_breached_again_then_clear_is_two_different_instants(self):
        envelope = SimpleNamespace(steps=[_step(60.0, Severity.CRITICAL), _step(120.0),
                                          _step(180.0, Severity.WARNING), _step(240.0),
                                          _step(300.0)])
        assert planner._case_outcomes(envelope, [self.CASE]) == [
            {"case_id": "c", "first_clear_s": 120.0, "clear_to_end_from_s": 240.0}]

    def test_a_finding_below_the_cases_severity_does_not_keep_it_open(self):
        envelope = SimpleNamespace(steps=[_step(60.0, Severity.LOW), _step(120.0, Severity.INFO)])
        assert planner._case_outcomes(envelope, [self.CASE]) == [
            {"case_id": "c", "first_clear_s": 60.0, "clear_to_end_from_s": 60.0}]


class TestTheCaseKeepsIt:

    def test_the_plan_attachment_keeps_the_chosen_plans_rows(self):
        session, opened = _session()
        planned = api.plan(session)
        api.attach_stage(session, opened["tank1"], "plan", planned)
        [case] = [c for c in api.case_book(session).to_dict()["cases"]["cases"]
                  if c["case_id"] == opened["tank1"]]
        assert case["stages"]["plan"][-1]["reference"]["cases"] == [
            {"case_id": opened["tank1"], "first_clear_s": 600.0, "clear_to_end_from_s": None}]

    def test_an_unranked_plan_chooses_nothing_to_keep(self):
        session, opened = _session(planning=False)
        api.attach_stage(session, opened["tank1"], "plan", api.plan(session))
        [case] = [c for c in api.case_book(session).to_dict()["cases"]["cases"]
                  if c["case_id"] == opened["tank1"]]
        assert case["stages"]["plan"][-1]["reference"]["cases"] == []
