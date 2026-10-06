"""A producer is late when its newest forecast is, not when an older one is.

The forecasts leg asks whether a producer is current, and it judged
every record in the ledger against `max_age`. A ledger keeps every forecast a
producer ever filed -- grading needs it to outlive the horizon -- so a producer
that sent a forecast five minutes ago was declined `stale_forecast` for the one
it sent forty minutes ago, and a ledger kept on a file declined every record an
earlier run had filed. Measured through margin-book-audit: a clean book audited
again 75 minutes later, every producer re-sending, exited 1 on four stale
forecasts, and a third run on eight. Staleness is judged on each producer's
newest forecast for the pair, and the decline names the producer.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from arbiter_engine.api import EngineSession
from arbiter_engine.clock import as_of
from arbiter_engine.forecast import ingest_forecasts, run_forecasts
from arbiter_engine.residual.sqlite_ledger import SqlitePredictionLedger

T0 = datetime(2026, 9, 17, 10, 0)


def _session(max_age="15m", ledger=None):
    session = EngineSession(ledger=ledger)
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Acct"],
        "indicators": {"Acct": [{
            "name": "balance", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
            "window": "1h", "critical": 100.0,
            "forecast": {"expected": True, "max_age": max_age}}]}}})
    session.add_entity("a1", "Acct", {"balance": 50.0})
    return session


def _feed(session, minutes_ago, model="garch_v3", at=T0):
    ingest_forecasts(session, [{
        "model_id": model, "entity_id": "a1", "property": "balance",
        "horizon_s": 3600.0, "issued_at": at - timedelta(minutes=minutes_ago),
        "quantiles": {"q05": 80.0, "q50": 95.0, "q95": 110.0}}], at=at)


def _stale(session, at=T0):
    with as_of(at):
        leg = run_forecasts(session)
    return [d for d in leg.not_checked if d.reason == "stale_forecast"]


def test_a_producer_that_sent_a_newer_forecast_is_current():
    session = _session()
    _feed(session, minutes_ago=40)
    _feed(session, minutes_ago=5)
    assert _stale(session) == []


def test_a_producer_whose_newest_forecast_is_old_is_stale_once():
    session = _session()
    _feed(session, minutes_ago=100)
    _feed(session, minutes_ago=40)
    [decline] = _stale(session)
    assert decline.evidence["age_s"] == 2400.0          # the newest, not the oldest
    assert decline.scope == {"entity": "a1", "indicator": "balance", "model_id": "garch_v3"}


def test_each_producer_is_judged_on_its_own_newest():
    session = _session()
    _feed(session, minutes_ago=5, model="garch_v3")
    _feed(session, minutes_ago=40, model="lstm_v1")
    assert [d.scope["model_id"] for d in _stale(session)] == ["lstm_v1"]


def test_a_forecast_issued_after_the_instant_supersedes_nothing_at_it():
    """A ledger read at an earlier instant: what came later is not yet there."""
    session = _session()
    _feed(session, minutes_ago=40)
    _feed(session, minutes_ago=0, at=T0 + timedelta(minutes=30))
    [decline] = _stale(session)
    assert decline.evidence["age_s"] == 2400.0


def test_an_unreadable_max_age_is_reported_once_per_producer_and_pair():
    session = _session(max_age="soon")
    _feed(session, minutes_ago=40)
    _feed(session, minutes_ago=5)
    [decline] = _stale(session)
    assert "not a duration this engine reads" in decline.detail


def test_a_ledger_kept_for_grading_holds_no_stale_forecast_for_a_current_producer(tmp_path):
    """Two runs of one book on one ledger file, the second 75 minutes on."""
    path = str(tmp_path / "book.sqlite")
    first = _session(ledger=SqlitePredictionLedger(path))
    _feed(first, minutes_ago=0)
    assert _stale(first) == []
    first.ledger.close()

    later = T0 + timedelta(minutes=75)
    second = _session(ledger=SqlitePredictionLedger(path))
    _feed(second, minutes_ago=0, at=later)
    assert len(second.ledger.records()) == 2            # the first run's forecast is still there
    assert _stale(second, at=later) == []
    second.ledger.close()
