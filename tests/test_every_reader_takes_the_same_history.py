"""`check` read the model's history. Four other verbs read the raw feed.

A calendar and a derived indicator both say the same kind of thing: *the series
you should read is not the series you were handed.* `check` went through
`_history_for` and honoured both. `project`, `discover`, `traverse` and the
random walk filed beside an ingested forecast took `session.history` directly,
so one declaration produced two different series depending on which verb asked.

THE DERIVED CASE IS THE ONE THAT LIES. The raw store holds nothing under a
derived indicator's name, so `project` declined `insufficient_samples` with
`evidence {"n": 0}` -- not a shortfall being reported, a false count, about a
series the engine could have joined from 200 readings it was holding.

THE CALENDAR CASE IS QUIETER AND WORSE TO DEBUG: both numbers are plausible.
Measured at 10:30 inside a 09:30-16:00 session, a `lookback: 4h` reached back to
06:31 through the store and to the previous afternoon through the view. The
first is four hours of wall clock, most of it a closed market. Nothing declines;
the model is simply fitted on the wrong series.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, project
from arbiter_engine.clock import as_of
from arbiter_engine.forecast import ingest_forecasts

T0 = datetime(2026, 9, 17, 10, 30)          # Thursday, an hour after the open
CALENDAR = {"sessions": [{"days": ["mon", "tue", "wed", "thu", "fri"],
                          "open": "09:30", "close": "16:00"}]}


def _minutely(entity: str, prop: str, minutes: int):
    return [(T0 - timedelta(minutes=i), 100.0 + (i % 7))
            for i in range(minutes, 0, -1)]


def _calendar_session(*, declared: bool) -> EngineSession:
    domain = {"id": "mkt", "name": "mkt", "entity_types": ["Account"],
              "indicators": {"Account": [
                  {"name": "px", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                   "window": "1h", "lookback": "4h", "horizon": "1h",
                   "critical": 100000.0,
                   "dynamics": {"model": "random_walk", "report_above": 0.25}}]}}
    if declared:
        domain["calendar"] = CALENDAR
    session = EngineSession()
    session.load_model({"domain": domain})
    session.add_entity("a1", "Account", {"px": 100.0})
    session.add_observations("a1", "px", _minutely("a1", "px", 3 * 1440))
    return session


def _derived_session() -> EngineSession:
    session = EngineSession()
    session.load_model({"domain": {
        "id": "basis", "name": "basis", "entity_types": ["Pair"],
        "indicators": {"Pair": [
            {"name": "futures", "type": "NUMERIC", "axioms": []},
            {"name": "spot", "type": "NUMERIC", "axioms": []},
            {"name": "basis", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
             "derived": "futures - spot", "critical": 50.0,
             "window": "6h", "lookback": "2d", "horizon": "1h",
             "dynamics": {"model": "random_walk", "report_above": 0.25}}]}}})
    session.add_entity("p1", "Pair", {"futures": 101.0, "spot": 100.0})
    base = T0 - timedelta(days=1)
    for name, level in (("futures", 101.0), ("spot", 100.0)):
        session.add_observations("p1", name, [
            (base + timedelta(minutes=7 * i), level + (i % 5) * 0.1)
            for i in range(200)])
    return session


def _projection(session):
    with as_of(T0):
        payload = project(session, horizon_s=3600.0).to_dict()
    return payload.get("projection", payload)


class TestProjectReadsTheDeclaredSeries:

    def test_a_derived_indicator_is_not_reported_as_an_empty_series(self):
        declines = _projection(_derived_session())["not_checked"]
        empty = [d for d in declines
                 if d["reason"] == "insufficient_samples"
                 and (d.get("evidence") or {}).get("n") == 0]
        assert empty == [], (
            "`project` reported a derived indicator as having no observations. "
            "The operands are in the store and the model says how to join "
            "them, so `n: 0` is not a measurement -- it is the wrong reader.")

    def test_the_lookback_is_measured_in_open_time_when_a_calendar_says_so(self):
        without = _projection(_calendar_session(declared=False))
        with_cal = _projection(_calendar_session(declared=True))
        assert with_cal["checked"]["observations_assimilated"] > \
            without["checked"]["observations_assimilated"], (
            "declaring a calendar did not change what `project` assimilated, "
            "so the lookback is still being measured on the wall clock")


class TestTheOtherVerbsTakeItToo:
    """Not a restatement: each verb resolves the history independently, and
    three of the four were fixed by separate edits. A test per verb is what
    stops one of them regressing alone."""

    def test_discover_runs_against_a_calendar_model(self):
        """The assertion is that it RUNS and reports, not what it finds. A
        correlation over a market calendar is a domain question; the engine's
        promise is only that both legs were read on one clock."""
        from arbiter_engine import api

        session = _calendar_session(declared=True)
        session.add_entity("a2", "Account", {"px": 100.0})
        session.add_observations("a2", "px", _minutely("a2", "px", 3 * 1440))
        with as_of(T0):
            payload = api.discover(session).to_dict()
        assert isinstance(payload, dict) and payload

    def test_traverse_is_given_the_view_and_not_the_raw_store(self):
        """`traverse` takes start nodes, so the cheap assertion is structural:
        the traverser must be handed whatever `reading_history` returns. Under
        a declared calendar those are different objects, and handing it the
        store is the defect this file is about."""
        from arbiter_engine import api
        from arbiter_engine.history.calendar import CalendarHistory
        from arbiter_engine.twin import traverser as traverser_mod

        session = _calendar_session(declared=True)
        seen = {}
        original = traverser_mod.TopologyTraverser

        class _Spy(original):
            def __init__(self, *args, **kwargs):
                seen["history"] = kwargs.get("observation_history")
                super().__init__(*args, **kwargs)

        # `api.traverse` imports the class inside the function, so the patch
        # goes on the module it imports FROM.
        traverser_mod.TopologyTraverser = _Spy
        try:
            with as_of(T0):
                api.traverse(session, ["a1"])
        finally:
            traverser_mod.TopologyTraverser = original
        assert isinstance(seen.get("history"), CalendarHistory), (
            "traverse was handed the raw store; a declared calendar means its "
            f"windows are wall clock, not open time (got {seen.get('history')!r})")

    def test_an_ingested_forecast_gets_its_yardstick_on_the_derived_series(self):
        """The random walk filed beside an outside forecast was fitted on the
        raw store, so a derived indicator could be GRADED and never raced --
        the comparison silently had one entrant."""
        session = _derived_session()
        with as_of(T0):
            report = ingest_forecasts(session, [{
                "model_id": "desk_v1", "entity_id": "p1",
                "property": "basis", "horizon_s": 3600.0,
                "issued_at": T0 - timedelta(minutes=5),
                "quantiles": {"q05": 0.5, "q50": 1.0, "q95": 1.5}}], at=T0)
        assert report["filed"] == 1
        assert report["baselines"] == 1, (
            f"the forecast was filed and got no yardstick: {report['raced']}")
