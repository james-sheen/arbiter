"""Every history this engine ships can be described, gapped and rolled from.

`SqliteObservationHistory` and `CalendarHistory` have been supported names since
0.2.3. `model_describe` and `gaps` both asked the session's history for
`series_keys()` -- a method the in-memory store has and the ABC does not
require -- and so both RAISED AttributeError for any session built over either
of the other two. `rollout` checked for the method and, finding none, ran with
no imagined past, declining `precondition_unmet`.

NOTHING DOWNSTREAM HAD EVER CONSTRUCTED ONE, which is how it survived. The first
caller was a vertical keeping its readings across separate runs -- the one use
the durable store exists for -- and its first `detect` died in the describe
call. Every test of the durable store here fed it and read it back through
`get_values`, which is the half that worked.

So this is asked of EVERY history the engine ships, through the verbs a caller
actually uses, rather than of one method on one class.
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timedelta

import pytest

from arbiter_engine import api
from arbiter_engine.history.calendar import (CalendarHistory,
                                                          SessionCalendar)
from arbiter_engine.history.observation import \
    InMemoryObservationHistory
from arbiter_engine.history.sqlite_store import \
    SqliteObservationHistory
from arbiter_engine.interfaces import ObservationHistory

MODEL = """
domain:
  id: histories
  name: every shipped history
  entity_types: [Tank]
  indicators:
    Tank:
      - name: level
        type: NUMERIC
        axioms: [BOUNDEDNESS]
        warning: 80
        critical: 90
"""

AT = datetime(2026, 9, 25, 12, 0)


def _always_open():
    """A calendar with no sessions, which counts every instant -- the history
    underneath is what is under test, not the calendar."""
    return SessionCalendar()


HISTORIES = {
    "in_memory": lambda: InMemoryObservationHistory(),
    "sqlite": lambda: SqliteObservationHistory(":memory:"),
    "calendar_over_memory": lambda: CalendarHistory(
        InMemoryObservationHistory(), _always_open()),
    "calendar_over_sqlite": lambda: CalendarHistory(
        SqliteObservationHistory(":memory:"), _always_open()),
}


def _session(history, tmp_path):
    path = tmp_path / "model.yaml"
    path.write_text(MODEL)
    session = api.EngineSession(history=history)
    session.load_model(str(path))
    session.add_entity("tank-1", "Tank", {"level": 50.0})
    with api.as_of(AT):
        session.add_observations("tank-1", "level",
                                 [(AT - timedelta(minutes=5 - i), 50.0 + i)
                                  for i in range(5)])
        # A series no indicator reads -- the report this breaks exists for it.
        session.add_observations("tank-1", "levle",
                                 [(AT - timedelta(minutes=1), 1.0)])
    return session


@pytest.fixture(params=sorted(HISTORIES))
def shipped(request, tmp_path):
    return request.param, _session(HISTORIES[request.param](), tmp_path)


class TestTheVerbsThatEnumerateAHistory:

    def test_model_describe_answers(self, shipped):
        name, session = shipped
        with api.as_of(AT):
            payload = api.model_describe(session).to_dict()
        assert "unconsumed_observations" in payload, name

    def test_gaps_answers(self, shipped):
        name, session = shipped
        with api.as_of(AT):
            api.check(session)
            api.gaps(session).to_dict()

    def test_the_unread_series_is_reported_the_same_way_by_all_of_them(
            self, shipped):
        """Same feed, same report, whichever store holds it -- the store is a
        durability choice and must not change what the engine says."""
        name, session = shipped
        records = session.unconsumed_observations()
        assert [(r["entity_id"], r["property"], r["reason"]) for r in records] == [
            ("tank-1", "levle", "undeclared_property")], name

    def test_a_rollout_is_seeded_from_it(self, shipped):
        """`precondition_unmet` is what a rollout says when it could not read
        the past; on a store the engine ships, it must never say it."""
        name, session = shipped
        with api.as_of(AT):
            payload = api.rollout(session, horizon_s=120.0,
                                  step_s=60.0).to_dict()["simulation"]
        reasons = {d["reason"] for d in payload.get("not_checked", [])}
        assert "precondition_unmet" not in reasons, (name, reasons)


class TestTheDurableStoreListsItsSeries:

    def test_distinct_and_ordered(self):
        store = SqliteObservationHistory(":memory:")
        for entity, prop in (("b", "x"), ("a", "y"), ("a", "x"), ("a", "x")):
            store.add(entity, prop, 1.0, AT)
        assert store.series_keys() == [("a", "x"), ("a", "y"), ("b", "x")]

    def test_it_survives_the_process(self, tmp_path):
        path = str(tmp_path / "h.sqlite")
        SqliteObservationHistory(path).add("tank-1", "level", 1.0, AT)
        assert SqliteObservationHistory(path).series_keys() == [("tank-1", "level")]


class _OnlyTheAbc(ObservationHistory):
    """A caller's own history, implementing exactly the five methods required."""

    def __init__(self):
        self._inner = InMemoryObservationHistory()

    def add(self, *args, **kwargs):
        return self._inner.add(*args, **kwargs)

    def get_values(self, *args, **kwargs):
        return self._inner.get_values(*args, **kwargs)

    def get_states(self, *args, **kwargs):
        return self._inner.get_states(*args, **kwargs)

    def get_observations(self, *args, **kwargs):
        return self._inner.get_observations(*args, **kwargs)

    def get_observation_count(self, *args, **kwargs):
        return self._inner.get_observation_count(*args, **kwargs)


class TestAHistoryThatCannotListItsSeriesSaysSo:
    """The ABC does not require `series_keys`, so a caller's history may lack it.
    The report it feeds cannot be made then -- and `[]` would say it was made
    and found nothing."""

    def test_the_report_is_none_not_empty(self, tmp_path):
        session = _session(_OnlyTheAbc(), tmp_path)
        assert session.unconsumed_observations() is None

    def test_describe_still_answers(self, tmp_path):
        session = _session(_OnlyTheAbc(), tmp_path)
        with api.as_of(AT):
            payload = api.model_describe(session).to_dict()
        assert payload["unconsumed_observations"] is None


FORECAST_MODEL = """
domain:
  id: graded
  name: a forecast graded through every view
  entity_types: [Tank]
  indicators:
    Tank:
      - name: level
        type: NUMERIC
        axioms: [BOUNDEDNESS]
        warning: 1000
        critical: 2000
        window: 1h
        dynamics: {model: random_walk}
"""

#: A calendar open around the clock is still a declared calendar, so the view
#: `check` hands the ledger is the calendar wrapper -- which is the point.
CALENDAR = ("  calendar:\n    sessions:\n      - {days: [mon, tue, wed, thu, fri, "
            "sat, sun], open: '00:00', close: '23:59'}\n")

#: One derived indicator anywhere in the model wraps the whole reading history.
DERIVED = ("      - name: double\n        type: NUMERIC\n        axioms: [BOUNDEDNESS]\n"
           "        warning: 1000\n        critical: 2000\n"
           "        derived: {expression: \"level + level\"}\n")

VIEWS = {
    "in_memory": (FORECAST_MODEL, InMemoryObservationHistory),
    "sqlite": (FORECAST_MODEL, lambda: SqliteObservationHistory(":memory:")),
    "calendar": (FORECAST_MODEL.replace("  entity_types:", CALENDAR + "  entity_types:"),
                 InMemoryObservationHistory),
    "derived": (FORECAST_MODEL + DERIVED, InMemoryObservationHistory),
}


def _graded(model_text, history, tmp_path):
    """Twenty minutes of one tank, a forecast filed each minute from the
    seventh, one fresh session per minute over the same two stores."""
    import random

    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "m.yaml"
    path.write_text(model_text)
    rng, level, ledger = random.Random(1), 100.0, None
    for minute in range(20):
        at = AT + timedelta(minutes=minute)
        level += rng.gauss(0.0, 1.0)
        with api.as_of(at):
            session = api.EngineSession(history=history, ledger=ledger)
            session.load_model(str(path))
            session.add_entity("t1", "Tank", {"level": level})
            session.add_observations("t1", "level", [(at, level)])
            ledger = session.ledger
            api.check(session)
            if minute >= 6:
                api.project(session, horizon_s=60.0)
    return ledger.calibration(), type(session.reading_history()).__name__


class TestAForecastIsGradedThroughEveryView:
    """The ledger read the in-memory store's private dict and skipped anything
    else, so the durable store, a declared calendar and one derived indicator
    each graded NONE of twelve forecasts -- every one `ungradeable`."""

    @pytest.mark.parametrize("view", sorted(VIEWS))
    def test_it_grades_what_the_plain_store_grades(self, view, tmp_path):
        text, make = VIEWS[view]
        cal, name = _graded(text, make(), tmp_path / view)
        plain_text, plain_store = VIEWS["in_memory"]
        control, _ = _graded(plain_text, plain_store(), tmp_path / "control")
        assert control["confirmed"] + control["falsified"] > 0, (
            "the control graded nothing, so parity with it would be free")
        assert cal["ungradeable"] == 0, (view, name, cal["ungradeable"])
        assert (cal["confirmed"], cal["falsified"]) == (
            control["confirmed"], control["falsified"]), (view, name)

    def test_the_views_are_really_different_objects(self, tmp_path):
        """Non-vacuity: if every case were the plain store underneath, the
        parity above would be free."""
        names = {view: _graded(text, make(), tmp_path / view)[1]
                 for view, (text, make) in VIEWS.items()}
        assert names == {"in_memory": "InMemoryObservationHistory",
                         "sqlite": "SqliteObservationHistory",
                         "calendar": "CalendarHistory",
                         "derived": "DerivedHistoryView"}, names
