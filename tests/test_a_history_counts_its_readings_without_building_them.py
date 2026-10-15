""" -- a history says how many readings it holds, and its first and last instants, without building them.

The Core asked `get_all_observations(datetime.min, datetime.max)` once for every problem it planned, to count a
cluster's readings and take their span, and the call builds an observation for every reading and sorts them: one
of the FAA case's problems took over two seconds of it. `reading_span()` gives the same three answers in one pass.

Readings fed out of time order, numbers and states alike, as a batch feed and a state indicator give them.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from arbiter_engine.history.observation import InMemoryObservationHistory

T0 = datetime(2021, 3, 15)


def _the_long_way(history):
    readings = history.get_all_observations(datetime.min, datetime.max)
    return len(readings), (readings[0].timestamp if readings else None), (readings[-1].timestamp if readings else None)


def _history():
    history = InMemoryObservationHistory(retention_period=timedelta(days=4000))
    history.add("u-1", "load", 7.0, T0 + timedelta(days=30))
    history.add("u-1", "load", 9.0, T0)                       # older, fed after
    history.add("u-2", "state", "declared", T0 + timedelta(days=400))
    history.add("u-2", "state", "not_declared", T0 - timedelta(days=5))
    return history


class TestAHistoryCountsItsReadingsWithoutBuildingThem:

    def test_the_same_three_answers_as_building_them(self):
        history = _history()
        assert history.reading_span() == _the_long_way(history) == (4, T0 - timedelta(days=5), T0 + timedelta(days=400))

    def test_an_empty_history(self):
        assert InMemoryObservationHistory().reading_span() == (0, None, None)
