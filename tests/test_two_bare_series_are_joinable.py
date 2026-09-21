"""Two series fed one after the other can be joined.

`add_observations` in its bare shape spaces readings
`interval_seconds` apart ENDING NOW, and read the wall clock once per call.
Two calls therefore ended microseconds apart and their uniform ladders shared
not one timestamp -- measured, `0 of 5` in common with the two grids 0.003146
seconds apart.

WHAT THAT BROKE. Everything downstream that joins two series on time. The
gain fitter intersects on exact timestamps, so it paired nothing and reported
`delay_off_grid` for EVERY declared delay including zero, offering a remedy
about the delay -- which was never the cause. `gain: estimate` fitting and the
`disagreements` report for a declared gain were unreachable through the shape
the README, the examples and every demo use.

WHY 2114 GREEN TESTS DID NOT SEE IT. Every test that exercises the fitter
builds its series with the timestamped tuple shape and explicitly shared
stamps. The fixtures avoided the broken path by construction, which is the
one thing a fixture must not do.

THE REUSE WINDOW IS THE CALLER'S OWN `interval_seconds`, not a constant
chosen here. Two calls less than one sampling interval apart are the same
sample instant by the caller's own declaration, and a session that feeds again
later re-pins rather than stamping new readings into a receding past. Inside
`as_of` the clock is already pinned and this returns it unchanged; that path
was always joinable.
"""
from __future__ import annotations

import datetime as dt
import math

import pytest

from arbiter_engine import api
from arbiter_engine.clock import as_of

WINDOW = dt.timedelta(days=3650)

MODEL = """
domain:
  id: joinable_series
  name: A pump feeding a tank
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS],
         critical: 9000, window: 30m}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS],
         critical: 9000, window: 30m}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: %(delay)d, time_constant_s: 600,
                 response_model: exponential}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                   source: datasheet}
"""


def _session(delay=120):
    s = api.EngineSession()
    s.load_model(MODEL % {"delay": delay})
    s.add_entity("pump1", "Pump", properties={"speed_rpm": 2000})
    s.add_entity("tank1", "Tank", properties={"level_pct": 50})
    s.add_relationship("pump1", "feeds", "tank1")
    return s


def _grids(s):
    a = [t for t, _ in s.history.get_values("pump1", "speed_rpm", WINDOW)]
    b = [t for t, _ in s.history.get_values("tank1", "level_pct", WINDOW)]
    return a, b


def _coupled(delay, n=200, interval=60.0):
    """A pump step and the tank response the declared coupling implies."""
    speeds = [2000.0 + (400.0 if i >= 60 else 0.0) for i in range(n)]
    levels = []
    for i in range(n):
        elapsed = (i - 60) * interval
        fraction = (0.0 if elapsed <= delay
                    else 1.0 - math.exp(-(elapsed - delay) / 600.0))
        levels.append(50.0 + 400.0 * 0.02 * fraction)
    return speeds, levels


class TestTheGridsCoincide:

    def test_two_bare_calls_share_every_timestamp(self):
        s = _session()
        s.add_observations("pump1", "speed_rpm", [2000.0] * 5)
        s.add_observations("tank1", "level_pct", [50.0] * 5)
        a, b = _grids(s)
        assert len(a) == len(b) == 5
        assert set(a) == set(b)

    def test_the_pinned_instant_is_not_used_inside_as_of(self):
        """That path pinned the clock already; this must not fight it."""
        when = dt.datetime(2026, 9, 1, 12, 0, 0)
        s = _session()
        with as_of(when):
            s.add_observations("pump1", "speed_rpm", [2000.0] * 5)
            s.add_observations("tank1", "level_pct", [50.0] * 5)
        a, b = _grids(s)
        assert set(a) == set(b)
        # The ladder ends one interval before the pinned instant, which is
        # what `now - (count - i) * interval` has always meant. The claim
        # here is that it derives from the FROZEN clock and not the wall one.
        assert max(a) == when - dt.timedelta(seconds=60)

    def test_a_feed_a_full_interval_later_re_pins(self):
        """The window is the caller's declared interval, so a later feed does
        NOT stamp into a receding past."""
        s = _session()
        s.add_observations("pump1", "speed_rpm", [2000.0] * 3,
                           interval_seconds=0.0)
        first = max(_grids(s)[0])
        s.add_observations("pump1", "speed_rpm", [2000.0] * 3,
                           interval_seconds=0.0)
        assert max(_grids(s)[0]) >= first


class TestTheFitterIsReachableFromTheBareShape:

    @pytest.mark.parametrize("delay", [0, 60, 120, 600])
    def test_a_declared_gain_is_fitted_at_any_delay(self, delay):
        s = _session(delay)
        speeds, levels = _coupled(delay)
        s.add_observations("pump1", "speed_rpm", speeds)
        s.add_observations("tank1", "level_pct", levels)
        proposed = api.model_describe(s).to_dict()["model"][
            "proposed_transitions"]
        assert proposed["not_fitted"] == [], proposed["not_fitted"]
        fitted = proposed["fitted"]
        assert len(fitted) == 1
        assert fitted[0]["gain"] == pytest.approx(0.02, abs=5e-4)


class TestTheDeclineNamesTheRightCause:

    def test_a_delay_that_misses_a_shared_grid_is_still_named(self):
        """90 s against a 60 s grid genuinely IS the delay's fault."""
        s = _session(90)
        speeds, levels = _coupled(90)
        s.add_observations("pump1", "speed_rpm", speeds)
        s.add_observations("tank1", "level_pct", levels)
        refused = api.model_describe(s).to_dict()["model"][
            "proposed_transitions"]["not_fitted"]
        assert [r["reason"] for r in refused] == ["delay_off_grid"]
        assert "share a sampling grid" in refused[0]["detail"]

    def test_series_on_different_clocks_are_named_as_such(self):
        """The case that used to be reported as the delay's fault. Its remedy
        is a different one, which is the whole point of splitting them."""
        s = _session(0)
        t0 = dt.datetime(2026, 9, 1, 0, 0, 0)
        s.add_observations("pump1", "speed_rpm", [
            (t0 + dt.timedelta(seconds=60 * i), 2000.0 + (i % 9) * 40)
            for i in range(200)])
        s.add_observations("tank1", "level_pct", [
            (t0 + dt.timedelta(seconds=60 * i + 7), 50.0 + (i % 7) * 0.4)
            for i in range(200)])
        refused = api.model_describe(s).to_dict()["model"][
            "proposed_transitions"]["not_fitted"]
        assert [r["reason"] for r in refused] == ["series_not_co_sampled"]
        assert "share no timestamp at all" in refused[0]["detail"]
