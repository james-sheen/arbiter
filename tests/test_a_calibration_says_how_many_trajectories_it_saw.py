"""Twelve records from one trajectory are not twelve independent tests.

A rollout files one value prediction per step per property, so a
12-step rollout of one coupled property files 12 records. They are one
trajectory: the same declared gain drives every step, the predicted values
come off one curve, and the tank either tracks it or does not. Measured on a
3600 s rollout in 300 s steps, against a mirror in which the tank never
moved: `confirmed 12, falsified 0, confirm_rate 1.0, brier 0.0025`. Against a
mirror drifting 2.0 per step: `confirmed 0, falsified 12, confirm_rate 0.0,
brier 0.9025`. All or nothing, both times, because there was only ever one
trial.

`confirm_rate` and `brier` are the figures that answer *can this engine's
projections be trusted*, and a reader given `1.0 over 12 records` reads twelve
successes. This module's own ledger is emphatic about exactly this class of
mistake -- *coverage_90 over four records and over four thousand are different
statements* -- and it already carries the field that fixes it.

`PredictionRecord.traversal_id` means THE EPISODE THIS CAME FROM.
`record_impacts` has always used it that way: one id per traversal, shared by
every impact it predicted. `_file_step` passed none, so
`record_value_prediction` minted a fresh uuid PER RECORD and 12 records from
one rollout looked like 12 unrelated episodes. The same call also let
`predicted_at` default to the moment each record happened to be written,
rather than the instant the rollout was run for.

So a rollout stamps one episode id on every prediction it files, and the
calibration reports how many distinct episodes its graded records came from.

WHAT `episodes_n` DOES NOT CLAIM. It is an upper bound on independence, not a
guarantee of it: two rollouts of the same entity over overlapping horizons are
two episodes and still correlated. What it rules out is the case that is
purely an artefact of how the engine files -- one trajectory counted as many.
"""
from __future__ import annotations

import random
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

from arbiter_engine import api
from arbiter_engine.history.observation import (
    InMemoryObservationHistory)

MODEL = """
domain:
  id: episodes
  name: A coupling whose projections can be graded
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 4h, lookback: 24h, dynamics: {model: random_walk}}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 4h, lookback: 24h}
  relationship_rules:
    - {type: feeds, source_type: Pump, target_type: Tank,
       temporal: {propagation_delay_s: 0, time_constant_s: 600,
                  response_model: exponential},
       transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                    gain_sigma: 0.002, source: datasheet}}
"""

HORIZON_S, STEP_S = 3600.0, 300.0
STEPS = int(HORIZON_S // STEP_S)


def _walk(seed=5, n=200, start=2000.0, sd=25.0):
    rng = random.Random(seed)
    value, out = start, []
    for _ in range(n):
        value += rng.gauss(0.0, sd)
        out.append(value)
    return out


def _session():
    path = Path(tempfile.mkdtemp()) / "episodes.yaml"
    path.write_text(MODEL)
    session = api.EngineSession()
    session.load_model(str(path))
    values = _walk()
    session.add_entity("pump1", "Pump", {"speed_rpm": values[-1]})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_relationship("pump1", "feeds", "tank1")
    now = api.now_utc()
    for k, value in enumerate(values):
        session.add_observations(
            "pump1", "speed_rpm",
            [(now - timedelta(seconds=60 * (len(values) - k)), value)])
    return session


def _roll(session):
    return api.rollout(session, actions=[], horizon_s=HORIZON_S,
                       step_s=STEP_S, seed_mode="projected",
                       file_predictions=True).to_dict()["simulation"]


def _records(session):
    return list(getattr(session.ledger, "_records", []))


class TestThePremise:

    def test_one_rollout_files_one_record_per_step(self):
        session = _session()
        simulation = _roll(session)
        assert simulation["checked"]["predictions_filed"] == STEPS
        assert len(_records(session)) == STEPS


class TestOneRolloutIsOneEpisode:

    def test_every_record_from_one_rollout_shares_an_episode(self):
        session = _session()
        _roll(session)
        ids = {record.traversal_id for record in _records(session)}
        assert len(ids) == 1, (
            f"{STEPS} records from ONE trajectory carry {len(ids)} episode "
            f"ids, so a calibration over them cannot tell one trajectory "
            f"from {len(ids)} independent ones")

    def test_two_rollouts_are_two_episodes(self):
        session = _session()
        _roll(session)
        _roll(session)
        ids = {record.traversal_id for record in _records(session)}
        assert len(ids) == 2

    def test_every_record_is_stamped_with_the_instant_it_was_run_for(self):
        session = _session()
        _roll(session)
        stamps = {record.predicted_at for record in _records(session)}
        assert len(stamps) == 1, (
            f"one rollout produced {len(stamps)} distinct `predicted_at` "
            f"values; they were written a few microseconds apart and the "
            f"record should say when the rollout ran, not when the row was")

    def test_the_horizons_still_differ(self):
        """The floor beside it: sharing an instant must not flatten the
        horizons, which are the whole of what distinguishes the steps."""
        session = _session()
        _roll(session)
        horizons = sorted({r.horizon_s for r in _records(session)})
        assert horizons == [STEP_S * k for k in range(1, STEPS + 1)]


def _mirror(drift, session):
    history = InMemoryObservationHistory()
    now = api.now_utc()
    for step in range(1, STEPS + 1):
        history.add("tank1", "level_pct", 50.0 + drift * step,
                    now + timedelta(seconds=STEP_S * step))
    return history


def _graded(drift, rollouts=1):
    session = _session()
    for _ in range(rollouts):
        _roll(session)
    matured = api.now_utc() + timedelta(
        seconds=HORIZON_S + session.ledger.grace_s + 1)
    session.ledger.grade_matured([], set(), now=matured,
                                 histories=[_mirror(drift, session)])
    return session.ledger.calibration()


class TestTheCalibrationSaysHowManyItSaw:

    def test_a_perfect_confirm_rate_says_it_came_from_one_trajectory(self):
        calibration = _graded(0.0)
        assert calibration["confirmed"] == STEPS
        assert calibration["confirm_rate"] == 1.0
        assert calibration["episodes_n"] == 1, (
            f"confirm_rate 1.0 over {STEPS} records reads as {STEPS} "
            f"successes; they are one trajectory")

    def test_a_total_miss_says_the_same(self):
        calibration = _graded(2.0)
        assert calibration["falsified"] == STEPS
        assert calibration["confirm_rate"] == 0.0
        assert calibration["episodes_n"] == 1

    def test_two_trajectories_count_as_two(self):
        assert _graded(0.0, rollouts=2)["episodes_n"] == 2

    def test_nothing_graded_reports_none_rather_than_zero(self):
        """The ledger's own rule for every other aggregate: a zero would read
        as a measurement."""
        calibration = _session().ledger.calibration()
        assert calibration["episodes_n"] is None
        assert calibration["confirm_rate"] is None


class TestTheExistingFiguresAreUnchanged:

    def test_the_counts_and_brier_still_report_what_they_did(self):
        calibration = _graded(0.0)
        assert calibration["recorded"] == STEPS
        assert calibration["falsified"] == 0
        assert calibration["brier"] == pytest.approx(0.0025, abs=1e-9)

    def test_a_caller_supplied_episode_is_still_honoured(self):
        """`record_value_prediction` has always taken one; the rollout simply
        never passed it, and a direct caller must keep control of it."""
        session = _session()
        session.ledger.record_value_prediction(
            entity_id="tank1", property_name="level_pct",
            predicted_value=50.0, tolerance=1.0, horizon_s=300.0,
            traversal_id="mine")
        assert _records(session)[-1].traversal_id == "mine"
