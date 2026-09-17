"""A store that survives a restart, a window measured in OPEN time, and a
replay that moves the data as well as the clock.

THREE FAILURES, EACH INVISIBLE IN A GREEN ENVELOPE:

- a ring buffer asked about last Tuesday answers `insufficient_samples`, which
  reads exactly like a quiet feed rather than like a store that evicted;
- a one-hour window on the first morning of a week spans the closed days, so a
  series sampled once a minute during the session looks like one sampled once
  every three days, and the sample-floor decline fires on data arriving
  perfectly well;
- a replay that moves only the clock checks TODAY's current values against last
  Tuesday's windows. Every leg of the envelope is still populated, so nothing
  about the output says the answer is about two different days at once.

The calendar's arithmetic is checked by ROUND TRIP: shift back by N open
seconds, then measure the open seconds forward again, and require N. That
catches a direction error, an off-by-one day, and a timezone applied the wrong
way, none of which a single hand-picked instant reliably does.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, time, timedelta

import pytest

from arbiter_engine.api import EngineSession
from arbiter_engine.replay import replay, sync_current_from_history
from arbiter_engine.clock import as_of
from arbiter_engine.history.calendar import (
    CalendarHistory, SessionCalendar,
)
from arbiter_engine.history.sqlite_store import SqliteObservationHistory

#: A Monday. The session below runs 09:30-16:00 in a zone five hours behind
#: UTC, so the open is 14:30 UTC.
MONDAY_OPEN = datetime(2026, 3, 2, 14, 30)

WEEKDAY_SHIFT = {"sessions": [{"days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                               "open": "09:30", "close": "16:00",
                               "tz": "America/New_York"}],
                 "holidays": ["2026-11-26"]}


@pytest.fixture
def calendar():
    return SessionCalendar.from_declaration(WEEKDAY_SHIFT)


# --- the store --------------------------------------------------------------

def test_the_five_methods_of_the_contract_answer():
    store = SqliteObservationHistory(":memory:")
    for i in range(10):
        store.add("e1", "level", 100.0 + i,
                  timestamp=MONDAY_OPEN + timedelta(minutes=i))
    store.add("e1", "state", "RUNNING", timestamp=MONDAY_OPEN)
    with as_of(MONDAY_OPEN + timedelta(minutes=9)):
        assert [v for _, v in store.get_values("e1", "level", timedelta(minutes=5))] \
            == [105.0, 106.0, 107.0, 108.0, 109.0]
        assert store.get_states("e1", "state", timedelta(days=1)) == [
            (MONDAY_OPEN, "RUNNING")]
    assert store.get_observation_count("e1", "level") == 10
    assert len(store.get_observations(
        "e1", MONDAY_OPEN, MONDAY_OPEN + timedelta(hours=1))) == 11


def test_a_window_follows_the_injected_clock():
    """The whole reason a replay needs no argument threaded through the eight
    checkers: the store reads `now_utc()` itself."""
    store = SqliteObservationHistory(":memory:")
    store.add("e1", "level", 42.0, timestamp=MONDAY_OPEN)
    assert store.get_values("e1", "level", timedelta(minutes=5)) == []
    with as_of(MONDAY_OPEN + timedelta(minutes=1)):
        assert len(store.get_values("e1", "level", timedelta(minutes=5))) == 1


def test_a_number_is_not_stored_as_text():
    """Two columns rather than one. A numeric series read back out of a TEXT
    column sorts and compares as text, which is how a threshold of 9 comes to
    exceed 10 -- and the values still all arrive, so nothing looks wrong."""
    store = SqliteObservationHistory(":memory:")
    for value in (9.0, 10.0, 100.0):
        store.add("e1", "level", value, timestamp=MONDAY_OPEN)
    with as_of(MONDAY_OPEN + timedelta(seconds=1)):
        values = [v for _, v in store.get_values("e1", "level", timedelta(minutes=1))]
    assert all(isinstance(v, float) for v in values)
    assert max(values) == 100.0


def test_a_text_value_is_not_returned_as_a_number():
    store = SqliteObservationHistory(":memory:")
    store.add("e1", "state", "DEGRADED", timestamp=MONDAY_OPEN)
    with as_of(MONDAY_OPEN + timedelta(seconds=1)):
        assert store.get_values("e1", "state", timedelta(minutes=1)) == []
        assert store.get_states("e1", "state", timedelta(minutes=1))[0][1] == "DEGRADED"


def test_the_store_outlives_the_process():
    """The property the in-memory ring cannot have, and the reason this exists."""
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    try:
        first = SqliteObservationHistory(path)
        first.add("e1", "level", 7.0, timestamp=MONDAY_OPEN)
        first.close()

        second = SqliteObservationHistory(path)
        assert second.get_observation_count("e1", "level") == 1
        with as_of(MONDAY_OPEN + timedelta(seconds=1)):
            assert [v for _, v in second.get_values(
                "e1", "level", timedelta(minutes=1))] == [7.0]
        second.close()
    finally:
        os.unlink(path)


def test_nothing_is_evicted():
    """A ring evicts because it must; a file the caller chose for durability
    dropping its oldest rows would be the surprise."""
    store = SqliteObservationHistory(":memory:")
    old = MONDAY_OPEN - timedelta(days=4000)
    store.add("e1", "level", 1.0, timestamp=old)
    assert store.get_observation_count("e1", "level") == 1
    assert store.get_observations("e1", old - timedelta(days=1),
                                  old + timedelta(days=1))


# --- the calendar -----------------------------------------------------------

def test_a_window_at_the_open_reaches_back_past_the_closed_days(calendar):
    """Five minutes into the first session of the week, an hour of OPEN time is
    mostly in the previous session -- not in the closed days, where a
    wall-clock hour would put it."""
    five_past = MONDAY_OPEN + timedelta(minutes=5)
    reached = calendar.shift_back(five_past, 3600)
    assert reached == datetime(2026, 2, 27, 20, 5)      # previous session
    assert reached < MONDAY_OPEN


def test_the_shift_and_the_measure_agree(calendar):
    """ROUND TRIP, at several spans. A direction error, an off-by-one day and
    a timezone applied backwards all survive one hand-picked instant."""
    end = MONDAY_OPEN + timedelta(minutes=5)
    for seconds in (60, 300, 3600, 25200, 100000):
        reached = calendar.shift_back(end, seconds)
        assert calendar.open_seconds_between(reached, end) == pytest.approx(seconds)


def test_closed_time_counts_for_nothing(calendar):
    """From one session's close to five past the next open is five minutes of
    open time, however many hours of wall clock it spans."""
    previous_close = datetime(2026, 2, 27, 21, 0)
    five_past = MONDAY_OPEN + timedelta(minutes=5)
    assert calendar.open_seconds_between(previous_close, five_past) == 300.0
    assert (five_past - previous_close).total_seconds() > 230000


def test_a_declared_holiday_is_closed(calendar):
    assert calendar.open_seconds_between(
        datetime(2026, 11, 26), datetime(2026, 11, 27)) == 0.0


def test_the_day_around_a_holiday_is_not(calendar):
    """The discriminator: a holiday that closed everything would pass the test
    above and be useless."""
    assert calendar.open_seconds_between(
        datetime(2026, 11, 25), datetime(2026, 11, 26)) > 0.0


def test_a_calendar_with_no_sessions_is_always_open():
    """The default, and the thing that must not change for any domain that
    declares nothing."""
    plain = SessionCalendar()
    assert plain.always_open
    assert plain.shift_back(MONDAY_OPEN, 7200) == MONDAY_OPEN - timedelta(hours=2)
    assert plain.open_seconds_between(
        MONDAY_OPEN, MONDAY_OPEN + timedelta(hours=3)) == 10800.0


def test_the_declared_zone_is_applied(calendar):
    """09:30 in a zone five hours behind UTC is 14:30 UTC. Applied the wrong
    way it is 04:30, and every session boundary moves ten hours."""
    spans = calendar._spans_on(MONDAY_OPEN.date())
    assert spans[0][0] == datetime(2026, 3, 2, 14, 30)
    assert spans[0][1] == datetime(2026, 3, 2, 21, 0)


def test_the_calendar_is_declared_in_yaml_like_everything_else():
    """A domain says when it is open in its own file. Nothing about sessions
    is in the engine, which is what lets the same package serve a domain that
    runs around the clock and one that does not."""
    from arbiter_engine.ontology.domain_loader import load_domain
    model = load_domain({"domain": {"id": "d", "name": "d",
                                    "entity_types": ["Unit"],
                                    "calendar": WEEKDAY_SHIFT, "indicators": {}}})
    declared = SessionCalendar.from_declaration(model.calendar)
    assert not declared.always_open
    assert declared.shift_back(MONDAY_OPEN + timedelta(minutes=5), 3600) \
        == datetime(2026, 2, 27, 20, 5)


def test_a_domain_that_declares_no_calendar_is_always_open():
    """The default that must not change for the domains this engine already
    serves. Declaring nothing is not declaring closed."""
    from arbiter_engine.ontology.domain_loader import load_domain
    model = load_domain({"domain": {"id": "d", "name": "d",
                                    "entity_types": ["Unit"], "indicators": {}}})
    assert SessionCalendar.from_declaration(model.calendar).always_open


# --- the wrapper ------------------------------------------------------------

def test_the_wrapper_translates_the_window(calendar):
    """A one-hour window at the open must see the previous session's readings,
    which a wall-clock hour would miss entirely."""
    store = SqliteObservationHistory(":memory:")
    store.add("e1", "level", 1.0, timestamp=datetime(2026, 2, 27, 20, 30))
    wrapped = CalendarHistory(store, calendar)
    with as_of(MONDAY_OPEN + timedelta(minutes=5)):
        assert store.get_values("e1", "level", timedelta(hours=1)) == []
        assert len(wrapped.get_values("e1", "level", timedelta(hours=1))) == 1


def test_the_wrapper_passes_explicit_instants_through(calendar):
    """`get_observations` names two instants; a caller who did that meant
    those two instants and not a translation of them."""
    store = SqliteObservationHistory(":memory:")
    store.add("e1", "level", 1.0, timestamp=datetime(2026, 2, 28, 3, 0))
    wrapped = CalendarHistory(store, calendar)
    assert len(wrapped.get_observations(
        "e1", datetime(2026, 2, 28), datetime(2026, 2, 28, 12, 0))) == 1


# --- moving the data as well as the clock -----------------------------------

#: TWO INDICATORS, and the second is the one that makes the replay test able to
#: fail. BOUNDEDNESS reads the CURRENT value, which `sync_current_from_history`
#: sets from an explicit instant -- so a replay that forgot to move the clock
#: still produces the right findings from it, and a suite with only that
#: indicator cannot tell the two apart. STABILITY reads the history WINDOW,
#: which follows the clock and nothing else: unfrozen, it finds no samples in
#: the last hour of a day six months ago and declines.
MODEL = {"domain": {"id": "d", "name": "d", "entity_types": ["Unit"],
                    "indicators": {"Unit": [
                        {"name": "level", "type": "NUMERIC",
                         "axioms": ["BOUNDEDNESS"], "window": "1h",
                         "critical": 95},
                        {"name": "rate", "type": "NUMERIC",
                         "axioms": ["STABILITY"], "window": "1h",
                         "expect_variation": True}]}}}


def _replay_session(readings=60):
    store = SqliteObservationHistory(":memory:")
    session = EngineSession(history=store)
    session.load_model(MODEL)
    session.add_entity("u1", "Unit")
    for i in range(readings):
        stamp = MONDAY_OPEN + timedelta(minutes=i)
        store.add("u1", "level", 90.0 + i * 0.2, timestamp=stamp)
        store.add("u1", "rate", 5.0 + (i % 7), timestamp=stamp)
    return session


def test_the_current_value_follows_the_clock():
    """THE FAILURE A REPLAY HIDES. Threshold axioms read `Entity.properties`,
    which follows nothing; without this the engine checks today's snapshot
    against last Tuesday's windows and every leg still looks populated."""
    session = _replay_session()
    at = MONDAY_OPEN + timedelta(minutes=20)
    synced = sync_current_from_history(session, at)
    assert synced["set"] == 2 and synced["absent"] == 0
    assert session.entities["u1"].properties["level"] == pytest.approx(94.0)


def test_a_property_with_no_reading_in_range_is_counted():
    """`absent` is the denominator that makes a replay step readable."""
    session = _replay_session(readings=0)
    synced = sync_current_from_history(session, MONDAY_OPEN)
    assert synced["set"] == 0 and synced["absent"] == 2


def test_the_span_that_was_searched_is_reported():
    """A reading older than the search and a property never fed are
    indistinguishable unless the span is stated."""
    session = _replay_session()
    synced = sync_current_from_history(session, MONDAY_OPEN,
                                       lookback=timedelta(days=2))
    assert synced["lookback_s"] == 172800.0


def test_a_replay_answers_as_of_each_step():
    """The series crosses the declared line partway through, so the finding
    must be absent early and present late -- on ONE feed, with only the clock
    and the current values moving."""
    session = _replay_session()
    steps = list(replay(session, [MONDAY_OPEN + timedelta(minutes=m)
                                  for m in (10, 30, 50)]))
    breaches = [[f for f in s["findings"]
                 if f["problem_type"] == "threshold_exceeded:level"]
                for s in steps]
    assert [len(b) for b in breaches] == [0, 1, 1]


def test_the_window_axioms_see_the_history_at_each_step():
    """THE ASSERTION THAT NEEDS THE CLOCK. A current-value check is satisfied
    by `sync` alone, so a replay that never froze the clock would pass the
    test above. A window axiom reads history and follows nothing but the
    clock: unfrozen, its window lands on an empty span six months from the
    data and it declines for want of samples."""
    session = _replay_session()
    steps = list(replay(session, [MONDAY_OPEN + timedelta(minutes=m)
                                  for m in (10, 30, 50)]))
    for step in steps:
        starved = [d for d in step["not_checked"]
                   if d["reason"] == "insufficient_samples"]
        assert starved == [], step["replay"]["at"]
        assert step["checked"]["invariants"] >= 2


def test_every_step_carries_the_instant_and_the_sync_counts():
    session = _replay_session()
    step = next(iter(replay(session, [MONDAY_OPEN + timedelta(minutes=10)])))
    assert step["replay"]["at"] == (MONDAY_OPEN + timedelta(minutes=10)).isoformat()
    assert step["replay"]["set"] == 2


def test_the_clock_is_released_after_the_replay():
    session = _replay_session()
    list(replay(session, [MONDAY_OPEN + timedelta(minutes=10)]))
    from arbiter_engine.clock import clock_is_frozen
    assert not clock_is_frozen()
