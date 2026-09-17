"""`MODELING.md` promises open-time windows. Something has to deliver them.

DECLARED, PARSED, STORED, AND READ BY NOTHING. The loader put the `calendar:`
block on the model, `CalendarHistory` existed and was exported from the
package, and no line joined them -- so a `window: 1h` still meant an hour of
wall clock, and the guide's sentence "declare this and a `window: 1h` means an
hour of OPEN time" was false for every caller who did not build the wrapper
themselves. Doing that by hand needed the domain parsed a SECOND time, because
`load_model` runs after the session is constructed and the history is chosen at
construction.

AND THE REACHABILITY REPORTS COULD NOT SAY SO. `unread_fields` did not carry
it, so `model_describe` reported a model with nothing unread while one of its
declarations went nowhere. That is the fed-but-never-read shape these reports
exist to catch, sitting inside the machinery that catches it.

ORDER MATTERS AND IS ASSERTED BELOW. The calendar wraps the store; the derived
view wraps whatever answers windows. A derived series is joined from operand
series, and operands answering on a different clock from the join is a
correctness bug that would show up as an empty derived series and nothing else.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, _history_for
from arbiter_engine.clock import as_of
from arbiter_engine.derived.indicator import DerivedHistoryView
from arbiter_engine.history.calendar import CalendarHistory
from arbiter_engine.history.observation import (
    InMemoryObservationHistory)

# A Thursday, inside a 09:00-17:00 session.
T0 = datetime(2026, 9, 17, 10, 0)

CALENDAR = {"sessions": [{"days": ["mon", "tue", "wed", "thu", "fri"],
                          "open": "09:00", "close": "17:00"}]}


def _session(*, calendar=True, derived=False):
    indicators = [{"name": "balance", "type": "NUMERIC",
                   "axioms": ["STABILITY"], "window": "1h"},
                  {"name": "fees", "type": "NUMERIC", "axioms": []}]
    if derived:
        indicators.append({"name": "net", "type": "NUMERIC", "axioms": [],
                           "derived": "balance - fees"})
    domain = {"id": "book", "name": "book", "entity_types": ["Account"],
              "indicators": {"Account": indicators}}
    if calendar:
        domain["calendar"] = CALENDAR
    session = EngineSession()
    session.load_model({"domain": domain})
    session.add_entity("acct_01", "Account", {"balance": 1.0, "fees": 0.0})
    return session


class TestTheDeclarationReachesTheHistory:

    def test_a_declared_calendar_wraps_the_store(self):
        assert isinstance(_history_for(_session()), CalendarHistory)

    def test_no_calendar_leaves_the_store_alone(self):
        assert isinstance(_history_for(_session(calendar=False)),
                          InMemoryObservationHistory)

    def test_a_derived_view_sits_OUTSIDE_the_calendar(self):
        history = _history_for(_session(derived=True))
        assert isinstance(history, DerivedHistoryView)
        assert isinstance(history.inner, CalendarHistory)

    def test_without_a_calendar_the_derived_view_wraps_the_store(self):
        history = _history_for(_session(calendar=False, derived=True))
        assert isinstance(history, DerivedHistoryView)
        assert isinstance(history.inner, InMemoryObservationHistory)


class TestAWindowMeansOpenTime:

    def _fed(self, **kwargs):
        session = _session(**kwargs)
        # Wednesday 16:30 is ninety minutes of OPEN time before Thursday
        # 10:00 -- half an hour to the close, then an hour from the open. The
        # market was shut for the sixteen and a half wall-clock hours between.
        session.history.add("acct_01", "balance", 42.0,
                            timestamp=datetime(2026, 9, 16, 16, 30))
        session.history.add("acct_01", "balance", 43.0,
                            timestamp=T0 - timedelta(minutes=30))
        return session

    def test_an_hour_of_open_time_reaches_back_across_the_close(self):
        history = _history_for(self._fed())
        with as_of(T0):
            values = history.get_values("acct_01", "balance", timedelta(hours=2))
        assert [v for _ts, v in values] == [42.0, 43.0]

    def test_wall_clock_alone_would_not_have(self):
        """The control. Without the declaration the same two-hour window sees
        one reading, which is what every caller was getting."""
        history = _history_for(self._fed(calendar=False))
        with as_of(T0):
            values = history.get_values("acct_01", "balance", timedelta(hours=2))
        assert [v for _ts, v in values] == [43.0]
