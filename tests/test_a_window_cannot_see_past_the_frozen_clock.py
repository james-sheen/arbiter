"""A window ends NOW, and under a frozen clock NOW is the frozen instant.

THE REPLAY RECIPE LEAKED ITS OWN FUTURE. The changelog says: feed the history
once with real timestamps, then step the clock. Every store computed its cutoff
as `now_utc() - window` and applied only that ONE end, so a step evaluated at
09:35 was handed every reading stamped after 09:35 as well. Measured on four
readings either side of the instant: both stores returned all four.

WHAT THAT PRODUCED is worse than a wrong number, because it is a plausible one.
`sync_current_from_history` bounds the CURRENT value correctly, so the
threshold axioms answered as-of the step while STABILITY, HOMEOSTASIS's
baseline, MONOTONICITY, CONSERVATION over a series and every `project` lookback
saw the whole run. A backtest step built that way looks exactly like an honest
one, and the model it endorses is one that had the answer in front of it.

THE TESTS THAT EXISTED asserted the LOWER cutoff follows the clock -- four of
them, all passing, none placing a reading after the frozen instant. A bound
tested at one end is a bound nobody has checked.

Both stores, because `CalendarHistory` delegates and would inherit whichever
half was wrong.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta

import pytest

from arbiter_engine.clock import as_of
from arbiter_engine.history.calendar import (
    CalendarHistory, SessionCalendar)
from arbiter_engine.history.observation import (
    InMemoryObservationHistory)
from arbiter_engine.history.sqlite_store import (
    SqliteObservationHistory)

T0 = datetime(2026, 9, 17, 9, 35)

BEFORE = [(T0 - timedelta(minutes=30), 10.0), (T0 - timedelta(minutes=10), 11.0)]
AFTER = [(T0 + timedelta(minutes=10), 999.0), (T0 + timedelta(minutes=30), 998.0)]


def _stores():
    memory = InMemoryObservationHistory()
    sqlite = SqliteObservationHistory(
        os.path.join(tempfile.mkdtemp(), "history.db"))
    calendar = CalendarHistory(InMemoryObservationHistory(),
                               SessionCalendar.from_declaration(None))
    for store in (memory, sqlite, calendar):
        for when, value in BEFORE + AFTER:
            store.add("e1", "balance", value, timestamp=when)
        for when, value in BEFORE + AFTER:
            store.add("e1", "state", "up" if value < 500 else "down",
                      timestamp=when)
    return {"in-memory": memory, "sqlite": sqlite, "calendar": calendar}


@pytest.fixture(params=["in-memory", "sqlite", "calendar"])
def store(request):
    return _stores()[request.param]


class TestNothingAfterTheInstantComesBack:

    def test_get_values_stops_at_the_frozen_now(self, store):
        with as_of(T0):
            values = store.get_values("e1", "balance", timedelta(hours=2))
        assert [v for _ts, v in values] == [10.0, 11.0]

    def test_get_states_stops_at_the_frozen_now(self, store):
        with as_of(T0):
            states = store.get_states("e1", "state", timedelta(hours=2))
        assert [s for _ts, s in states] == ["up", "up"]

    def test_the_lower_cutoff_still_applies(self, store):
        """The half that already worked, kept honest: a one-ended fix in the
        other direction would pass every assertion above."""
        with as_of(T0):
            values = store.get_values("e1", "balance", timedelta(minutes=20))
        assert [v for _ts, v in values] == [11.0]

    def test_stepping_the_clock_forward_reveals_them_one_at_a_time(self, store):
        """What a replay is FOR. Each step sees one more reading, and never
        more than one more."""
        seen = []
        for step in (T0, T0 + timedelta(minutes=20), T0 + timedelta(minutes=40)):
            with as_of(step):
                seen.append(len(store.get_values("e1", "balance",
                                                 timedelta(hours=4))))
        assert seen == [2, 3, 4]

    def test_at_the_wall_clock_everything_is_visible(self, store):
        """Not frozen, and these timestamps are in the past by the time any
        suite runs -- so the bound must not quietly drop real data."""
        values = store.get_values("e1", "balance", timedelta(days=3650))
        assert len(values) == 4
