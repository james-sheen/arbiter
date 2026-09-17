"""The `forecasts` leg asks what somebody ELSE owed. Two records are not that.

`project` files its forecast under `<model>:<source>` and its reference under
`baseline_rw`, and `run_forecasts` read every distribution record in the ledger
as a producer's submission. That did two wrong things at once, and the second
is the one nobody would have found by reading.

FIRST, the visible one: a model declaring `models: [garch_v3, lstm_v1]` -- as
`examples/margin_book.yaml` does -- declined `model_unknown` for the engine's
OWN projection and for its OWN random walk, and once older than `max_age` they
declined `stale_forecast` too. The changelog says the reference is tagged "so a
reader can tell a reference from a real forecast without matching on a name";
the tag lived on the `Forecast` object and never reached the ledger, so the
leg matched on nothing.

SECOND, the one that matters: those records also counted as ARRIVED. A pair
whose outside forecaster sent nothing reported `expected: 1, received: 1` and
no `forecast_missing`, because the engine's own projection had filled the slot.
An expectation nobody met read as met -- which is the one shape this leg exists
to refuse, produced by the leg itself.

THE SPLIT IS BY A FIELD THE FILER SET, never by the shape of the id. An id
containing a colon is a naming convention, and reading a convention as a fact
is the name-heuristic class removed from three axioms.

THE TESTS THAT EXISTED declared `models:` and never called `project`; the test
that called `project` never declared `models:`. Each half was covered and the
crossing was not, which is where the defect was.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, check, project
from arbiter_engine.clock import as_of
from arbiter_engine.forecast import ingest_forecasts
from arbiter_engine.projection.projector import (
    BASELINE_MODEL_ID, SOURCE_ENGINE)

T0 = datetime(2026, 9, 17, 9, 35)


def _session(*, models=("garch_v3",), max_age="15m"):
    forecast = {"expected": True, "max_age": max_age}
    if models:
        forecast["models"] = list(models)
    session = EngineSession()
    session.load_model({"domain": {
        "id": "margin-book", "name": "book", "entity_types": ["Account"],
        "indicators": {"Account": [{
            "name": "margin_balance", "type": "NUMERIC",
            "axioms": ["BOUNDEDNESS"], "lower_critical": 900.0,
            "window": "1h", "lookback": "7d", "horizon": "1h",
            "forecast": forecast,
            "dynamics": {"model": "local_level", "report_above": 0.25},
        }]}}})
    session.add_entity("acct_01", "Account", {"margin_balance": 1000.0})
    base = T0 - timedelta(days=1)
    session.add_observations("acct_01", "margin_balance", [
        (base + timedelta(minutes=7 * i), 1000.0 + (i % 11) * 3.0)
        for i in range(200)])
    return session


def _leg(session):
    with as_of(T0):
        return check(session).to_dict()["forecasts"]


class TestTheLedgerRemembersWhoIssuedIt:

    def test_project_marks_its_own_records(self):
        session = _session()
        with as_of(T0):
            project(session, horizon_s=3600.0)
        sources = {r.model_id: r.source for r in session.ledger.records()}
        assert set(sources.values()) == {SOURCE_ENGINE}
        assert BASELINE_MODEL_ID in sources

    def test_an_ingested_forecast_is_not_marked_as_the_engines(self):
        session = _session()
        with as_of(T0):
            ingest_forecasts(session, [{
                "model_id": "garch_v3", "entity_id": "acct_01",
                "property": "margin_balance", "horizon_s": 3600.0,
                "issued_at": T0 - timedelta(minutes=5),
                "quantiles": {"q05": 850.0, "q50": 1000.0,
                              "q95": 1120.0}}], at=T0)
        producer = [r for r in session.ledger.records()
                    if r.model_id == "garch_v3"]
        assert [r.source for r in producer] == [None]


class TestProjectingDoesNotAnswerForAProducer:

    def test_a_missing_forecast_is_still_missing_after_project(self):
        """The defect that masked a coverage hole."""
        session = _session()
        with as_of(T0):
            project(session, horizon_s=3600.0)
        leg = _leg(session)
        assert leg["checked"]["expected"] == 1
        assert leg["checked"]["received"] == 0
        assert [d["reason"] for d in leg["not_checked"]] == ["forecast_missing"]

    def test_the_engines_records_are_counted_and_not_hidden(self):
        """Excluded from `received`, reported under their own name. Silence
        would leave *no reference was filed* and *references were filed and
        hidden* reading identically."""
        session = _session()
        with as_of(T0):
            project(session, horizon_s=3600.0)
        assert _leg(session)["checked"]["reference"] == 2

    def test_no_model_unknown_for_a_record_the_engine_filed(self):
        session = _session(models=("garch_v3", "lstm_v1"))
        with as_of(T0):
            project(session, horizon_s=3600.0)
        assert not [d for d in _leg(session)["not_checked"]
                    if d["reason"] == "model_unknown"]

    def test_no_stale_forecast_for_a_record_the_engine_filed(self):
        session = _session(max_age="1s")
        with as_of(T0 - timedelta(hours=2)):
            project(session, horizon_s=3600.0)
        assert not [d for d in _leg(session)["not_checked"]
                    if d["reason"] == "stale_forecast"]


class TestAProducerIsStillJudged:
    """The other side of the split. A fix that simply stopped judging records
    would pass every assertion above and remove the checks entirely."""

    def _fed(self, model_id, minutes_ago=5, **kwargs):
        session = _session(**kwargs)
        with as_of(T0):
            ingest_forecasts(session, [{
                "model_id": model_id, "entity_id": "acct_01",
                "property": "margin_balance", "horizon_s": 3600.0,
                "issued_at": T0 - timedelta(minutes=minutes_ago),
                "quantiles": {"q05": 850.0, "q50": 1000.0,
                              "q95": 1120.0}}], at=T0)
        return session

    def test_an_undeclared_producer_still_declines_model_unknown(self):
        leg = _leg(self._fed("typo_v9"))
        assert [d["reason"] for d in leg["not_checked"]] == ["model_unknown"]

    def test_an_old_producer_record_still_declines_stale_forecast(self):
        leg = _leg(self._fed("garch_v3", minutes_ago=60))
        assert "stale_forecast" in [d["reason"] for d in leg["not_checked"]]

    def test_a_producers_forecast_still_counts_as_received(self):
        leg = _leg(self._fed("garch_v3"))
        assert leg["checked"]["received"] == 1
        assert not [d for d in leg["not_checked"]
                    if d["reason"] == "forecast_missing"]
