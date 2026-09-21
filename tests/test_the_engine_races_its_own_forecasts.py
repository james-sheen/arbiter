"""The engine's own forecasts get the yardstick it holds everyone else to.

`RandomWalk`'s docstring states why the reference
exists: *a forecaster can be beautifully calibrated and still carry no
information at all*. Three surfaces in this engine file forecasts, and until
now only two of them raced one:

    ingest_forecasts (a producer's) forecast + baseline_rw `raced` reported
    project (the engine's) forecast + baseline_rw NOTHING reported
    rollout (the engine's) forecast ONLY NOTHING reported

MEASURED, ONE SESSION, ONE SERIES, ONE HORIZON, the engine's own two verbs:

    project -> ledger {'local_level:estimated_parameters': 1, 'baseline_rw': 1}
    rollout -> ledger {'arbiter_engine:rollout': 6} <- no yardstick

So `own_projections` reported a calibration that could not tell a declared
`gain:` carrying real information from one whose `gain_sigma:` was merely
generous -- the exact failure reference was introduced to catch, on the
one population that had no reference.

THIS IS A CLASS REOPENING, NOT A NEW DEFECT. `ingest._file_baseline`'s own
docstring records the same gap in the mirror direction -- *the engine kept the
yardstick running for its OWN projections and not for anybody else's. it was
filed beside one of the two kinds*. That fix covered the two kinds that existed.
`rollout` arrived in 0.2.3 as a third and did not get one.

WHAT THIS FILE PINS
  - every filed projection appears in exactly one `raced` row (the PROPERTY,
    not the counts, which drift whenever an example gains an indicator);
  - the yardstick is NOT averaged into the score it is the yardstick for;
  - the race can be LOST as well as won -- a comparison with one possible
    outcome is not a comparison;
  - a projection that could not be raced says WHY, in the closed vocabulary
    `ingest_forecasts` already reports;
  - both calibration tables carry `by_target` in one spelling, so the two
    populations can be compared on the series they actually share.
"""
from __future__ import annotations

import datetime as dt
import random

import pytest

from arbiter_engine import api
from arbiter_engine.projection.projector import BASELINE_MODEL_ID

STEP_S, HORIZON_S = 600.0, 3600.0
STEPS = int(HORIZON_S // STEP_S)
SELF_MODEL_ID = "arbiter_engine:rollout"

#: The driven indicator declares a `window:`, which is what the reference is
#: fitted over. Without one there is no span to fit on and the race is
#: declined by name -- pinned separately below.
MODEL = """
domain:
  id: raced
  name: A rollout with something to beat
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 30m, dynamics: {model: local_level}}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 30m%(extra)s}
  relationship_rules:
    - {type: feeds, source_type: Pump, target_type: Tank,
       temporal: {propagation_delay_s: 0, time_constant_s: 1,
                  response_model: step},
       transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                    gain_sigma: 0.002, source: datasheet}}
"""

#: Readings on the DRIVEN indicator, below `MINIMUM_SAMPLES`, so the
#: reference has too little to fit on and the race is declined by name.
#:
#: NOT a model with the `window:` removed, which is the fixture this started
#: as and which silently tested nothing: `IndicatorSpec.time_window` DEFAULTS
#: to an hour, so an indicator declaring no span still reports one and the
#: baseline fitted happily. `declared_keys` knows the difference; the field
#: does not. That makes `no_lookback_or_window` effectively unreachable
#: through `time_window`, which is worth knowing and is not this file's
#: subject.
STARVED_POINTS = 2


def _session(tmp_path, name, tank_points=60):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL % {"extra": ""})
    session = api.EngineSession()
    session.load_model(str(path))
    rng = random.Random(7)
    level, series = 2500.0, []
    for _ in range(60):
        level += rng.gauss(0.0, 8.0)
        series.append(round(level + rng.gauss(0.0, 4.0), 3))
    session.add_entity("pump1", "Pump", {"speed_rpm": series[-1]})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_relationship("pump1", "feeds", "tank1")
    session.add_observations("pump1", "speed_rpm", series)
    session.add_observations("tank1", "level_pct", [50.0] * tank_points)
    return session


def _roll(session):
    return api.rollout(session, horizon_s=HORIZON_S, step_s=STEP_S,
                       seed_mode="projected", file_predictions=True
                       ).to_dict()["simulation"]


def _grade(session, t0, drift):
    """Let the world catch up, then grade at maturity."""
    for k in range(1, STEPS + 1):
        with api.as_of(t0 + dt.timedelta(seconds=STEP_S * k)):
            session.add_observations("tank1", "level_pct", [50.0 + drift * k])
    with api.as_of(t0 + dt.timedelta(seconds=HORIZON_S + 60)):
        api.check(session)
        return session.ledger.calibration()


class TestEveryFiledProjectionIsRaced:
    """The property, not the count."""

    def test_one_raced_row_per_filed_prediction(self, tmp_path):
        sim = _roll(_session(tmp_path, "pairs"))
        assert sim["checked"]["predictions_filed"] > 0
        assert len(sim["raced"]) == sim["checked"]["predictions_filed"]

    def test_a_raced_row_names_the_subject_and_the_horizon(self, tmp_path):
        sim = _roll(_session(tmp_path, "subject"))
        for row in sim["raced"]:
            assert row["entity_id"] and row["indicator"]
            assert row["horizon_s"] > 0
            assert row["model_id"] == SELF_MODEL_ID

    def test_the_yardstick_reaches_the_ledger(self, tmp_path):
        session = _session(tmp_path, "ledger")
        sim = _roll(session)
        filed = [r for r in session.ledger.records()
                 if r.model_id == BASELINE_MODEL_ID]
        assert len(filed) == sim["checked"]["baselines_filed"] > 0

    def test_a_rollout_that_does_not_file_reports_no_race(self, tmp_path):
        """`file_predictions=False` files nothing, so there is nothing to race."""
        session = _session(tmp_path, "unfiled")
        sim = api.rollout(session, horizon_s=HORIZON_S, step_s=STEP_S,
                          seed_mode="projected").to_dict()["simulation"]
        assert "raced" not in sim
        assert not [r for r in session.ledger.records()
                    if r.model_id == BASELINE_MODEL_ID]


class TestTheYardstickIsNotOneOfTheRunners:
    """Averaging the reference into the score would be worse than the gap."""

    def test_the_headline_excludes_the_baseline(self, tmp_path):
        session = _session(tmp_path, "exclude")
        t0 = api.now_utc()
        _roll(session)
        own = _grade(session, t0, 0.4)["own_projections"]
        graded_own = [r for r in session.ledger.records()
                      if r.kind == "value" and r.scores is not None
                      and r.model_id != BASELINE_MODEL_ID]
        assert own["n"] == len(graded_own) > 0

    def test_the_baseline_is_reported_under_its_own_leg(self, tmp_path):
        session = _session(tmp_path, "leg")
        t0 = api.now_utc()
        _roll(session)
        own = _grade(session, t0, 0.4)["own_projections"]
        assert own["baseline"]["n"] > 0
        assert own["baseline"]["crps_approx"] is not None

    def test_nothing_raced_is_none_and_never_false(self, tmp_path):
        """*It lost* and *no race was run* are not the same report."""
        session = _session(tmp_path, "unraced", tank_points=STARVED_POINTS)
        t0 = api.now_utc()
        _roll(session)
        own = _grade(session, t0, 0.4)["own_projections"]
        assert own["baseline"]["n"] == 0
        assert own["baseline"]["beats_baseline"] is None
        assert own["baseline"]["compared_n"] == 0


class TestTheRaceCanBeLost:
    """A comparison with one possible outcome is not a comparison."""

    @pytest.mark.parametrize("drift,expected", [(0.4, True), (0.0, False)])
    def test_the_verdict_follows_the_world(self, tmp_path, drift, expected):
        session = _session(tmp_path, f"drift{drift}")
        t0 = api.now_utc()
        _roll(session)
        own = _grade(session, t0, drift)["own_projections"]
        assert own["baseline"]["beats_baseline"] is expected

    def test_the_verdict_is_computed_over_matched_targets_only(self, tmp_path):
        session = _session(tmp_path, "matched")
        t0 = api.now_utc()
        _roll(session)
        own = _grade(session, t0, 0.4)["own_projections"]
        assert 0 < own["baseline"]["compared_n"] <= own["n"]


class TestAnUnraceableProjectionSaysWhy:
    """The silent absence is the defect; a typed one is the fix."""

    def test_a_driven_indicator_with_too_little_history_declines_by_name(self, tmp_path):
        sim = _roll(_session(tmp_path, "starved", tank_points=STARVED_POINTS))
        assert sim["raced"], "predictions were filed, so rows are owed"
        assert {row["baseline"] for row in sim["raced"]} == {
            "too_little_history"}
        assert sim["checked"]["baselines_filed"] == 0

    def test_the_reason_comes_from_the_shared_vocabulary(self, tmp_path):
        allowed = {"filed", "is_the_reference", "no_entity_or_model",
                   "no_such_indicator", "no_lookback_or_window",
                   "already_filed", "too_little_history", "fit_failed"}
        for points in (60, STARVED_POINTS):
            sim = _roll(_session(tmp_path, f"vocab{points}", tank_points=points))
            assert {row["baseline"] for row in sim["raced"]} <= allowed


class TestProjectReportsItsOwnRace:
    """`project` filed a baseline and said nothing about it."""

    def test_project_reports_a_raced_row_per_forecast(self, tmp_path):
        session = _session(tmp_path, "projraced")
        payload = api.project(session, horizon_s=HORIZON_S).to_dict()
        leg = payload["projection"]
        assert len(leg["raced"]) == leg["checked"]["forecasts_issued"] > 0

    def test_project_counts_the_baselines_it_filed(self, tmp_path):
        session = _session(tmp_path, "projcount")
        leg = api.project(session, horizon_s=HORIZON_S
                          ).to_dict()["projection"]
        assert leg["checked"]["baselines_filed"] == sum(
            1 for row in leg["raced"] if row["baseline"] == "filed")


class TestBothTablesCarryTheJoinKey:
    """One shared axis, or the two tables answer nobody."""

    def test_by_target_is_present_on_both(self, tmp_path):
        session = _session(tmp_path, "join")
        t0 = api.now_utc()
        _roll(session)
        calibration = _grade(session, t0, 0.4)
        assert "by_target" in calibration
        assert "by_target" in calibration["own_projections"]

    def test_the_key_names_entity_property_and_horizon(self, tmp_path):
        session = _session(tmp_path, "keyshape")
        t0 = api.now_utc()
        _roll(session)
        own = _grade(session, t0, 0.4)["own_projections"]
        assert own["by_target"], "graded records must land in a target"
        for key in own["by_target"]:
            entity, indicator, horizon = key.split("·")
            assert entity == "tank1" and indicator == "level_pct"
            assert horizon.endswith("s")
