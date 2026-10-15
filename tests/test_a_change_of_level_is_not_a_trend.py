"""A change of level is not a trend toward a limit.

BOUNDEDNESS projects a fitted line toward the critical line, and a line through two flat
levels has a steep slope and a high R-squared: a pump held at 2,000 rpm, then set to 3,000 and held,
read as `approaching_limit` against a 9,000 line nothing was moving toward, and a step down to 800
as `approaching_floor`. A live `check` always did this after a set-point change; since a
rollout judges its steps the same way, so `plan` charged a set-point option for it.

The arm now asks what explains the window better: one line, or one step. When a step explains it
as well, by the R-squared a trend must reach, the readings since the step are judged on their own:
still moving, they project; level, or fewer than five, they do not. A ramp still projects, and so
does a level that jumped and kept climbing.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

import pytest

from arbiter_engine import api
from arbiter_engine.history.observation import InMemoryObservationHistory
from arbiter_engine.interfaces import calculate_trend, level_shift_at

T0 = datetime(2026, 1, 1, 12, 0)
MODEL = """
domain:
  id: change-of-level
  name: a pump's speed against its lines
  entity_types: [Pump]
  relationship_types: []
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9000, lower_critical: 500, window: 30m}
"""


def _at(i):
    return T0 - timedelta(minutes=39 - i)


def _found(series):
    session = api.EngineSession(history=InMemoryObservationHistory(retention_period=timedelta(days=30)))
    session.load_model(MODEL)
    session.add_entity("p1", "Pump", {"speed_rpm": series[-1][1]})
    session.add_observations("p1", "speed_rpm", series)
    with api.as_of(T0):
        return sorted(f["problem_type"] for f in api.check(session).to_dict()["findings"])


def _series(level):
    return [(_at(i), float(level(i))) for i in range(40)]


class TestAChangeOfLevel:

    @pytest.mark.parametrize("after", [3000, 800])
    def test_a_step_that_held_projects_toward_nothing(self, after):
        assert _found(_series(lambda i: 2000 if i < 30 else after)) == []

    def test_a_step_with_fewer_than_five_readings_since_is_not_yet_a_trend(self):
        assert _found(_series(lambda i: 2000 if i < 37 else 3000 + 300 * (i - 37))) == []


class TestATrend:

    def test_a_ramp_up_projects_toward_the_ceiling(self):
        assert _found(_series(lambda i: 2000 + 100 * i)) == ["approaching_limit:speed_rpm"]

    def test_a_ramp_down_projects_toward_the_floor(self):
        assert _found(_series(lambda i: 4000 - 75 * i)) == ["approaching_floor:speed_rpm"]

    def test_a_noisy_ramp_still_does(self):
        assert _found(_series(lambda i: 2000 + 100 * i + (37 * i % 11 - 5) * 40)) == ["approaching_limit:speed_rpm"]

    def test_a_level_that_jumped_and_kept_climbing_does(self):
        assert _found(_series(lambda i: 2000 if i < 30 else 3000 + 150 * (i - 30))) == ["approaching_limit:speed_rpm"]

    def test_so_does_one_whose_line_alone_would_not_have(self):
        """A big jump then a slow climb: the whole window's line falls short of the R-squared a
        trend needs, and only the readings since the jump show where it is going."""
        series = _series(lambda i: 2000 if i < 30 else 6000 + 60 * (i - 30))
        assert calculate_trend(series)["r2"] < 0.7
        assert _found(series) == ["approaching_limit:speed_rpm"]


class TestTheStepIsFoundWhereItIs:

    def test_the_first_reading_at_the_new_level(self):
        series = _series(lambda i: 2000 if i < 30 else 3000)
        assert level_shift_at(series, calculate_trend(series)["r2"], 0.7) == 30

    def test_a_ramp_has_none(self):
        series = _series(lambda i: 2000 + 100 * i)
        assert level_shift_at(series, calculate_trend(series)["r2"], 0.7) is None

    def test_a_noisy_ramp_near_the_bar_is_not_read_as_a_step(self):
        """Read as a step, each half of it falls short of the R-squared a trend needs and the trend
        is lost; the line explains it better, so it stands."""
        rng = random.Random(5)
        series = [(_at(i), 2000 + 120 * i + rng.gauss(0, 800)) for i in range(10, 40)]   # the window's
        r2 = calculate_trend(series)["r2"]
        assert 0.72 <= r2 <= 0.8
        assert level_shift_at(series, r2, 0.7) is None
        assert _found(series) == ["approaching_limit:speed_rpm"]

    def test_noise_has_none_and_never_reads_as_a_trend(self):
        rng = random.Random(2250)
        for _ in range(200):
            series = _series(lambda i: 5000 + rng.gauss(0, 200))
            assert level_shift_at(series, calculate_trend(series)["r2"], 0.7) is None
            assert _found(series) == []


PUMP = """
domain:
  id: change-of-level-plan
  name: a pump a plan can set
  entity_types: [Pump]
  relationship_types: []
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9000, lower_critical: 500, window: 30m}
  action_templates:
    - name: set_speed
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm, candidates: [3000, 800]}
      effect: set
      settle_s: 0
      source: runbook
"""


def test_a_rollout_no_longer_charges_a_set_point_for_its_own_step():
    session = api.EngineSession(history=InMemoryObservationHistory(retention_period=timedelta(days=30)))
    session.load_model(PUMP)
    session.add_entity("p1", "Pump", {"speed_rpm": 2000.0})
    session.add_observations("p1", "speed_rpm", _series(lambda i: 2000))
    for speed in (3000, 800):
        with api.as_of(T0):
            steps = api.rollout(session, actions=[{"template": "set_speed", "entity_id": "p1",
                                                   "parameters": {"speed_rpm": speed}, "at_s": 0}],
                                horizon_s=1800, step_s=60).to_dict()["simulation"]["per_step"]
        named = {f if isinstance(f, str) else f.get("problem_type") for step in steps for f in step.get("findings") or []}
        assert not {"imagined_approaching_limit:speed_rpm", "imagined_approaching_floor:speed_rpm"} & named, speed
