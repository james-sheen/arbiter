"""The `forecasts` leg: a denominator nobody can fake, and where it does not climb.

*371 FORECASTS RECEIVED* IS NOT A MEASUREMENT until somebody says out of how
many. The only honest source is the model -- an indicator declaring
`forecast: {expected: true}` says an outside forecaster is supposed to supply
one -- and counting what arrived and calling that the denominator is the shape
rule 1 exists to forbid. It is also the shape every forecasting dashboard has.

SO A MODEL THAT DECLARES NOTHING GETS A QUESTION, NOT A ZERO. `expected: 0`
beside `received: 12` reads as twelve unexpected forecasts. The truth is that
nobody has said which pairs should carry one.

AND THE FINDINGS DO NOT CLIMB. This leg rides on `check`, whose top-level
findings are about the present. A forecast breach merged into those would put
*your prediction is impossible* beside *your system is breaking* in one list --
the confusion the `forecast_` prefix exists to prevent, reintroduced one level
up where the prefix cannot be seen.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, check
from arbiter_engine.clock import as_of
from arbiter_engine.forecast import ingest_forecasts, run_forecasts

T0 = datetime(2026, 9, 17, 10, 0)


def _session(forecast=None, entities=("a1",), critical=100.0):
    indicator = {"name": "balance", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                 "window": "1h", "critical": critical,
                 "dynamics": {"model": "local_level", "report_above": 0.1}}
    if forecast is not None:
        indicator["forecast"] = forecast
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Acct"],
        "indicators": {"Acct": [indicator]}}})
    for entity_id in entities:
        session.add_entity(entity_id, "Acct", {"balance": 50.0})
    return session


def _feed(session, entity_id="a1", model="garch_v3", minutes_ago=5,
          q=(80.0, 95.0, 110.0)):
    return ingest_forecasts(session, [{
        "model_id": model, "entity_id": entity_id, "property": "balance",
        "horizon_s": 3600.0, "issued_at": T0 - timedelta(minutes=minutes_ago),
        "quantiles": {"q05": q[0], "q50": q[1], "q95": q[2]}}], at=T0)


def _leg(session):
    with as_of(T0):
        return run_forecasts(session)


def _reasons(sub):
    return sorted(d.reason for d in sub.not_checked)


EXPECTED = {"expected": True}


# --- the denominator ---------------------------------------------------------

def test_expected_comes_from_the_model_not_from_what_arrived():
    session = _session(EXPECTED, entities=("a1", "a2", "a3"))
    _feed(session, "a1")
    checked = _leg(session).checked
    assert checked["expected"] == 3
    assert checked["received"] == 1


def test_a_declared_pair_with_nothing_filed_is_reported():
    """The case that is invisible without a declaration: a forecaster that
    stopped sending looks exactly like one that was never expected."""
    session = _session(EXPECTED, entities=("a1", "a2"))
    _feed(session, "a1")
    sub = _leg(session)
    assert _reasons(sub) == ["forecast_missing"]
    missing = sub.not_checked[0]
    assert missing.scope["entity"] == "a2"


def test_expected_is_counted_per_entity_not_per_type():
    """A type with two hundred instances expects two hundred forecasts, and
    counting the declaration once would report a denominator of one."""
    session = _session(EXPECTED, entities=tuple(f"a{n}" for n in range(200)))
    assert _leg(session).checked["expected"] == 200


def test_a_model_declaring_nothing_asks_rather_than_answering_zero():
    """`expected: 0` beside `received: 12` reads as twelve unexpected
    forecasts. The truth is that nobody has said which pairs should carry
    one."""
    session = _session(None)
    _feed(session)
    sub = _leg(session)
    assert sub.checked["expected"] == 0
    assert [q["kind"] for q in sub.questions] == ["missing_declaration"]
    assert "Acct" in sub.questions[0]["question"]


def test_a_declaring_model_asks_no_question():
    """The discriminator: a question on every run is a question nobody reads."""
    session = _session(EXPECTED)
    _feed(session)
    assert _leg(session).questions == []


def test_graded_and_pending_split_the_records_filed():
    """WITH SOMETHING GRADED, which the first version of this test lacked.
    All-pending satisfies `graded + pending == total` even when `pending` is
    just the total, so a mutation dropping the subtraction passed."""
    session = _session(EXPECTED, entities=("a1", "a2"))
    _feed(session, "a1", minutes_ago=120)
    _feed(session, "a2", minutes_ago=5)
    session.history.add("a1", "balance", 95.0, timestamp=T0 - timedelta(minutes=60))
    with as_of(T0):
        session.ledger.grade_matured(problems=[], observed_entity_ids={"a1"},
                                     histories=[session.history])
    checked = _leg(session).checked
    assert checked["graded"] == 1
    assert checked["pending"] == 1
    assert checked["graded"] + checked["pending"] == 2


def test_the_denominator_is_never_summed_with_the_axiom_one():
    session = _session(EXPECTED)
    _feed(session)
    assert _leg(session).checked["invariants"] == 0


# --- the declines ------------------------------------------------------------

def test_a_model_the_declaration_does_not_list_is_reported():
    session = _session({"expected": True, "models": ["garch_v3"]})
    _feed(session, model="rogue_v9")
    sub = _leg(session)
    assert "model_unknown" in _reasons(sub)
    decline = next(d for d in sub.not_checked if d.reason == "model_unknown")
    assert decline.scope["model_id"] == "rogue_v9"


def test_without_a_declared_list_no_model_is_unknown():
    """Refusing every id the engine has not seen would refuse the first
    forecast every producer ever sends."""
    session = _session(EXPECTED)
    _feed(session, model="brand_new_v1")
    assert "model_unknown" not in _reasons(_leg(session))


def test_a_listed_model_passes():
    session = _session({"expected": True, "models": ["garch_v3", "lstm_v1"]})
    _feed(session, model="lstm_v1")
    assert "model_unknown" not in _reasons(_leg(session))


def test_a_forecast_past_its_declared_age_is_stale():
    session = _session({"expected": True, "max_age": "15m"})
    _feed(session, minutes_ago=40)
    sub = _leg(session)
    assert "stale_forecast" in _reasons(sub)
    decline = next(d for d in sub.not_checked if d.reason == "stale_forecast")
    assert decline.evidence["max_age_s"] == 900.0
    assert decline.evidence["age_s"] == pytest.approx(2400.0)


def test_a_fresh_forecast_is_not_stale():
    session = _session({"expected": True, "max_age": "15m"})
    _feed(session, minutes_ago=5)
    assert "stale_forecast" not in _reasons(_leg(session))


def test_without_a_declared_age_nothing_is_stale():
    """How old is too old is a minute for a quote and a day for a balance.
    There is no check until somebody declares the number."""
    session = _session(EXPECTED)
    _feed(session, minutes_ago=100000)
    assert "stale_forecast" not in _reasons(_leg(session))


def test_an_unreadable_max_age_is_reported_rather_than_ignored():
    session = _session({"expected": True, "max_age": "soon"})
    _feed(session)
    decline = next(d for d in _leg(session).not_checked
                   if d.reason == "stale_forecast")
    assert "not a duration this engine reads" in decline.detail


def test_a_matured_forecast_with_no_mirror_is_ungradeable():
    session = _session(EXPECTED)
    _feed(session, minutes_ago=120)
    with as_of(T0):
        session.ledger.grade_matured(problems=[], observed_entity_ids=set(),
                                     histories=[session.history])
    assert "ungradeable" in _reasons(_leg(session))


# --- where the findings go ---------------------------------------------------

def test_a_forecast_breach_rides_in_the_leg():
    session = _session(EXPECTED)
    _feed(session)
    assert [f.problem_type for f in _leg(session).findings] == [
        "forecast_breach:balance"]


def test_a_forecast_finding_does_not_climb_into_the_envelope():
    """THE SHAPE THIS LEG IS ABOUT. The top-level findings answer *is the
    system breaking*; this forecast is impossible and the system is fine."""
    session = _session(EXPECTED)
    _feed(session)
    with as_of(T0):
        payload = check(session).to_dict()
    assert payload["forecasts"]["findings"]
    assert payload["findings"] == []


def test_the_leg_is_present_even_when_nobody_forecasts():
    """An absent key reads as *no forecasting here*; a present one with a zero
    denominator and a question says which."""
    with as_of(T0):
        payload = check(_session(None)).to_dict()
    assert "forecasts" in payload
    assert payload["forecasts"]["checked"]["expected"] == 0


def test_an_empty_ledger_costs_the_check_nothing_it_can_report():
    session = _session(EXPECTED)
    sub = _leg(session)
    assert sub.findings == []
    assert sub.checked["received"] == 0
    assert _reasons(sub) == ["forecast_missing"]
