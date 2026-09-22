"""A value prediction is graded against a reading taken AT its horizon.

`_grade_value_record` selects, from the observations inside
`[predicted_at, predicted_at + horizon + grace]`, the one closest to the
horizon instant -- and there was no bound on how far away that closest one
was allowed to be. A single reading anywhere in the window therefore graded
every horizon the window contains.

Measured: twelve value predictions filed for t = 300. 3600 s, then one
tank reading 60 s after the rollout and silence for the rest of the hour.

    confirmed 12, falsified 0, ungradeable 0,
    confirm_rate 1.0, brier 0.0025
    coupling report: graded 12, confirmed 12

The hour-ahead forecast was confirmed by a reading fifty-nine minutes stale.
`confirm_rate` is the one number in this package that says whether its
projections can be trusted, and the quietest possible mirror produced a
perfect one.

THE LEDGER'S OWN DOCSTRING ALREADY SAYS THE RULE: *no observations in-window
= the channel was silent = UNGRADEABLE (not-looking is not evidence)*. What
was missing is that a reading far from the horizon is the channel being
silent AT THE HORIZON, which is the instant the record is about.

WHAT BOUNDS IT, AND WHY IT IS NOT A NEW NUMBER. A reading grades the record
whose horizon it is NEAREST to, and the records themselves say where the
other horizons are: a rollout files one per step, so they come spaced by the
caller's own `step_s`. Nothing was chosen. The guarantee is that ONE reading
grades AT MOST ONE record, which is the whole of the harm above.

`grace_s` was tried first and is wrong, which is worth recording because it
looks right. It is already the ledger's statement of how long past the
horizon it will wait, so reading it symmetrically seemed to introduce
nothing -- but a ledger may declare `grace_s=0`, and one in this tree's own
suite does. That means *I will not wait past the horizon*, not *a reading
must land on it to the second*, and the symmetric reading turned five
seconds of ordinary sampling jitter into `ungradeable`. Ten shipped tests
said so.
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta

import numpy as np
import pytest

from arbiter_engine import api
from arbiter_engine.clock import as_of

T0 = datetime(2026, 9, 10, 12, 0, 0)
HORIZON_S, STEP_S = 3600.0, 300.0
#: Long enough after the window closes that every record has matured.
LATER = T0 + timedelta(seconds=10000)


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


EXAMPLE = str(_examples_dir() / "pump_tank_dynamics.yaml")


def _filed_session():
    """Twelve filed value predictions for the tank, at 300 s intervals."""
    session = api.EngineSession()
    session.load_model(EXAMPLE)
    rng = np.random.default_rng(3)
    speeds = 1000 + np.cumsum(rng.normal(0, 5, 200))
    for index, speed in enumerate(speeds):
        session.add_observations("pump1", "speed_rpm", [
            (T0 - timedelta(seconds=(199 - index) * 60), float(speed))])
    session.add_entity("pump1", "Pump", {"speed_rpm": float(speeds[-1])})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_relationship("pump1", "feeds", "tank1")
    with as_of(T0):
        simulation = api.rollout(
            session, actions=None, horizon_s=HORIZON_S, step_s=STEP_S,
            seed_mode="projected",
            file_predictions=True).to_dict()["simulation"]
    assert simulation["checked"]["predictions_filed"] == 12, (
        "the premise: twelve horizons were filed")
    return session


def _graded(session):
    with as_of(LATER):
        session.ledger.grade_matured([], set(), now=LATER,
                                     histories=[session.history])
        return session.ledger.calibration()


def _mirror(session, *offsets_s, value=50.0):
    for offset in offsets_s:
        session.add_observations("tank1", "level_pct", [
            (T0 + timedelta(seconds=offset), value)])


class TestOneStaleReadingGradesOnlyItsOwnHorizon:

    def test_a_reading_a_minute_in_does_not_confirm_the_hour(self):
        session = _filed_session()
        _mirror(session, 60.0)
        calibration = _graded(session)
        assert calibration["confirmed"] <= 1, (
            f"one reading 60 s after the rollout confirmed "
            f"{calibration['confirmed']} of 12 horizons; the furthest of them "
            f"is an hour away from it")
        assert calibration["ungradeable"] >= 11

    def test_and_the_confirm_rate_says_so(self):
        """`confirm_rate` is over what was GRADED, so a ledger that graded
        almost nothing must not read like one that got almost everything
        right. Either it is None, or it is over at most the one record that
        had a reading near its horizon."""
        session = _filed_session()
        _mirror(session, 60.0)
        calibration = _graded(session)
        graded = calibration["confirmed"] + calibration["falsified"]
        assert graded <= 1, (
            f"{graded} records graded from one reading")


class TestAReadingAtTheHorizonStillGrades:
    """The floor. A bound that made the well-behaved mirror ungradeable would
    be worse than the defect: a ledger that never grades says nothing at all."""

    def test_a_mirror_that_reports_at_every_horizon_grades_every_record(self):
        session = _filed_session()
        _mirror(session, *[step * STEP_S for step in range(1, 13)])
        calibration = _graded(session)
        assert calibration["ungradeable"] == 0
        assert calibration["confirmed"] + calibration["falsified"] == 12

    def test_a_mirror_on_its_own_schedule_still_grades(self):
        """Sampling jitter is the ordinary case, not the exception: a reading
        a few seconds early is still a reading at that horizon. An earlier
        version of this bound made every one of these `ungradeable` and ten
        shipped tests said so."""
        session = _filed_session()
        _mirror(session, *[step * STEP_S - 5.0 for step in range(1, 13)])
        calibration = _graded(session)
        assert calibration["ungradeable"] == 0

    def test_no_reading_grades_more_than_one_record(self):
        """The guarantee, stated directly. Three readings cannot produce
        twelve grades however the mirror happens to be timed."""
        session = _filed_session()
        _mirror(session, 300.0, 1500.0, 3600.0)
        calibration = _graded(session)
        graded = calibration["confirmed"] + calibration["falsified"]
        assert graded <= 3, (
            f"three readings graded {graded} of twelve horizons")
        assert calibration["ungradeable"] == 12 - graded


class TestNothingElseMoves:

    def test_a_silent_channel_is_still_ungradeable(self):
        session = _filed_session()
        calibration = _graded(session)
        assert calibration["ungradeable"] == 12
        assert calibration["confirm_rate"] is None

    def test_a_reading_that_misses_at_its_horizon_still_falsifies(self):
        session = _filed_session()
        _mirror(session, *[step * STEP_S for step in range(1, 13)],
                value=500.0)
        calibration = _graded(session)
        assert calibration["falsified"] == 12
        assert calibration["confirm_rate"] == pytest.approx(0.0)
