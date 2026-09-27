"""The learn floor can be reached at every cadence, and the decline says when.

The learn stage fits a declared coupling's gain once it holds 120
paired changes, and it read the series through a ten-year window. At a
calendar-monthly cadence that window holds 120 readings, so 119 paired
changes: the floor was never met however long the series ran, and the decline
counted 119 for ever. Measured on the operating-health vertical's model at 240
monthly captures, twenty years of them. A feeder on a 30-day ladder never saw
it, because 121 readings thirty days apart span 3,600 days -- which is why the
loop test there passed while the claim beside it, *ten years of monthly
captures*, was true only on that ladder.

The fit reads the whole series now, and so do the two other readers that
spelled "all of it" as ten years: the rollout's seed and the decline
diagnostic. A calendar passes the whole series through rather than walking
open time back to its ten-year stop.

The decline carries the arithmetic: the median spacing of the readings and the
instant the floor is reached at that spacing, or that it cannot be. The keys
are the ones the axioms' own sample floors use, plus
`floor_reached_at`.

The floor itself stays 120 by ruling. What changed is that it can be met.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine import api
from arbiter_engine.history.calendar import (CalendarHistory,
                                                         SessionCalendar)
from arbiter_engine.history.observation import (
    InMemoryObservationHistory)
from arbiter_engine.interfaces import (WHOLE_SERIES,
                                                   sampling_context)
from arbiter_engine.twin import rollout as rollout_module
from arbiter_engine.twin import transition_learner
from arbiter_engine.twin.transition_learner import (
    MINIMUM_PAIRED_SAMPLES)

#: The window every reader here used before this change.
TEN_YEARS = timedelta(days=3650)
#: The instant every series ends at, and the one the clock is frozen at.
END = datetime(2026, 9, 1)

MODEL = """
domain:
  id: monthly
  name: One coupling fed once a month
  entity_types: [Unit, Group]
  relationship_types: [reports_to]
  indicators:
    Unit: [{name: size, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    Group: [{name: total, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  relationship_rules:
    - type: reports_to
      source_type: Unit
      target_type: Group
      temporal:
        propagation_delay_s: 0
        time_constant_s: 1
        response_model: step
      transition:
        from: size
        to: total
        gain: estimate
        source: estimated
"""


def _month(k: int) -> datetime:
    """The first of the month `k` months after January 2000."""
    year, month = divmod(k, 12)
    return datetime(2000 + year, month + 1, 1)


def _calendar_months(count: int) -> list:
    """`count` instants on the first of consecutive months, ending at END."""
    last = (END.year - 2000) * 12 + END.month - 1
    return [_month(k) for k in range(last - count + 1, last + 1)]


def _ladder(count: int, spacing: timedelta) -> list:
    return [END - spacing * (count - 1 - k) for k in range(count)]


def _session(tmp_path, stamps, name="m"):
    """A unit whose size moves every reading and a group that moves with it."""
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL)
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("u", "Unit", {"size": 10.0})
    session.add_entity("g", "Group", {"total": 100.0})
    session.add_relationship("u", "reports_to", "g")
    size, total = 10.0, 100.0
    for k, when in enumerate(stamps):
        step = (2.0, -2.0, 1.0, 1.0, -1.0, -1.0)[k % 6]
        size, total = size + step, total + step
        session.add_observations("u", "size", [(when, size)])
        session.add_observations("g", "total", [(when, total)])
    return session


def _proposed(session):
    with api.as_of(END):
        return api.model_describe(session).to_dict()[
            "model"]["proposed_transitions"]


class TestAMonthlySeriesReachesTheFloor:

    def test_121_calendar_months_fit(self, tmp_path):
        payload = _proposed(_session(tmp_path, _calendar_months(121)))
        assert payload["not_fitted"] == []
        assert [f["n"] for f in payload["fitted"]] == [MINIMUM_PAIRED_SAMPLES]
        assert payload["fitted"][0]["gain"] == pytest.approx(1.0)

    def test_the_ten_year_window_is_what_stopped_it(self, tmp_path,
                                                    monkeypatch):
        """The control: put the old window back and the same series declines
        at 119, and so does one twice as long."""
        monkeypatch.setattr(transition_learner, "_LOOKBACK", TEN_YEARS)
        for count in (121, 240):
            entry = _proposed(_session(tmp_path, _calendar_months(count),
                                       name=f"old{count}"))["not_fitted"][0]
            assert entry["reason"] == "insufficient_samples"
            assert entry["observations"] == MINIMUM_PAIRED_SAMPLES - 1, count

    def test_a_30_day_ladder_fitted_under_either_window(self, tmp_path,
                                                        monkeypatch):
        """Why a feeder on a fixed thirty-day ladder never saw it."""
        stamps = _ladder(121, timedelta(days=30))
        assert _proposed(_session(tmp_path, stamps, name="new"))["fitted"]
        monkeypatch.setattr(transition_learner, "_LOOKBACK", TEN_YEARS)
        assert _proposed(_session(tmp_path, stamps, name="old"))["fitted"]

    def test_the_floor_itself_did_not_move(self, tmp_path):
        payload = _proposed(_session(tmp_path, _calendar_months(121)))
        assert payload["checked"]["sample_floor"] == MINIMUM_PAIRED_SAMPLES == 120


class TestTheDeclineSaysWhen:

    def test_a_monthly_series_is_dated(self, tmp_path):
        stamps = _calendar_months(30)
        entry = _proposed(_session(tmp_path, stamps))["not_fitted"][0]
        assert entry["reason"] == "insufficient_samples"
        assert (entry["observations"], entry["required"]) == (29, 120)
        # Calendar months: seven of every twelve gaps are 31 days.
        assert entry["sampling_interval_seconds"] == 31 * 86400
        reached = stamps[-1] + timedelta(days=31) * (120 - 29)
        assert entry["floor_reached_at"] == reached.isoformat()
        assert "floor_unreachable_at_this_rate" not in entry
        assert "31 days" in entry["detail"]
        assert reached.date().isoformat() in entry["detail"]

    def test_one_short_of_the_floor_is_one_reading_away(self, tmp_path):
        stamps = _calendar_months(120)
        entry = _proposed(_session(tmp_path, stamps))["not_fitted"][0]
        assert entry["observations"] == 119
        assert entry["floor_reached_at"] == (
            stamps[-1] + timedelta(days=31)).isoformat()

    def test_a_series_sampled_by_the_minute_is_dated_to_the_minute(
            self, tmp_path):
        stamps = _ladder(30, timedelta(seconds=60))
        entry = _proposed(_session(tmp_path, stamps))["not_fitted"][0]
        reached = stamps[-1] + timedelta(minutes=91)
        assert entry["floor_reached_at"] == reached.isoformat()
        assert reached.isoformat(timespec="minutes") in entry["detail"]
        assert "60 s" in entry["detail"]

    def test_an_annual_series_is_told_waiting_will_not_help(self, tmp_path):
        """120 paired changes a year apart need 120 years, and the fit reads a
        century. Saying *collect more* there is the false remedy that an internal ruling
        took out of the axioms' declines."""
        stamps = [datetime(1997 + k, 9, 1) for k in range(30)]
        entry = _proposed(_session(tmp_path, stamps))["not_fitted"][0]
        assert entry["reason"] == "insufficient_samples"
        assert entry["floor_unreachable_at_this_rate"] is True
        assert "Collecting for longer will not help" in entry["remedy"]
        assert "floor_reached_at" not in entry
        assert "sample more often" in entry["detail"]

    def test_the_floor_is_said_to_be_borrowed(self, tmp_path):
        """It told the author the floor was discovery's *for the same reason*.
        Discovery's reason is a stationarity split and a regression at lag
        10, and this fit runs neither."""
        detail = _proposed(_session(tmp_path, _calendar_months(30)))[
            "not_fitted"][0]["detail"]
        assert "same reason" not in detail
        assert "used here unchanged" in detail

    def test_every_published_key_is_a_sample_floor_key(self, tmp_path):
        entry = _proposed(_session(tmp_path, _calendar_months(30)))[
            "not_fitted"][0]
        assert set(entry) == {"edge", "reason", "detail", "observations",
                              "required", "window_seconds",
                              "sampling_interval_seconds", "floor_reached_at"}


def _monthly_store(count):
    store = InMemoryObservationHistory()
    for k, when in enumerate(_calendar_months(count)):
        store.add("u", "size", float(k), when)
    return store


class TestTheOtherReadersSeeTheWholeSeries:

    def test_the_rollout_seeds_every_reading(self, tmp_path, monkeypatch):
        """Its own comment: a declared window is the thing being honoured. At
        ten years a declared `window:` longer than that was checked on less
        inside `plan` than outside it."""
        stamps = _calendar_months(240)

        def seeded(name):
            session = _session(tmp_path, stamps, name=name)
            with api.as_of(END):
                envelope = api.rollout(session, horizon_s=120.0, step_s=60.0)
            return envelope.to_dict()["simulation"]["checked"]["history_seeded"]

        assert seeded("whole") == 2 * 240
        monkeypatch.setattr(rollout_module, "_CLONE_WINDOW", TEN_YEARS)
        assert seeded("decade") < 2 * 240

    def test_the_diagnostic_counts_all_recorded_history(self):
        """`total_observations` is documented as over all recorded history,
        not just the window."""
        with api.as_of(END):
            figures = sampling_context(_monthly_store(240), "u", "size",
                                       timedelta(days=365))
        assert figures["total_observations"] == 240
        assert figures["sampling_interval_seconds"] == 31 * 86400

    def test_a_calendar_passes_the_whole_series_through(self):
        """Translating *everything* into open time walked back the calendar's
        ten-year stop and returned there."""
        calendar = SessionCalendar.from_declaration({"sessions": [
            {"days": ["mon", "tue", "wed", "thu", "fri"],
             "open": "09:30", "close": "16:00"}]})
        assert not calendar.always_open
        view = CalendarHistory(_monthly_store(240), calendar)
        with api.as_of(END):
            assert len(view.get_values("u", "size", WHOLE_SERIES)) == 240
            assert len(view.get_values("u", "size", TEN_YEARS)) < 240
