"""Ingesting outside forecasts: what gets filed, and what every rejection says.

A FEEDER, NOT A VERB. Forecasts are an input, and every other input surface on
this session is a feeder. The verb that reports on them is `check`. A tenth
module-level verb for *here is some data* would be the first time this package
answered an input with a verb.

NOTHING RAISES, and the reason is not politeness. A producer's batch of four
hundred with three bad records must file three hundred and ninety-seven:
refusing the batch makes one producer's bug cost another producer's data, and
an engine whose thesis is *report what you could not use* must not answer
unusable input by discarding usable input beside it.

EVERY RECORD IS ACCOUNTED FOR. `filed` plus the rejections equals `received`,
which is the denominator discipline the top-level envelope applies to checks
and which an input surface needs exactly as much: a report of three rejections
means nothing without the number of records they came from.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession
from arbiter_engine.forecast import ingest_forecasts
from arbiter_engine.forecast.contract import GAUSSIAN_STAMP

NOW = datetime(2026, 9, 17, 10, 0)
ISSUED = NOW - timedelta(minutes=30)

MODEL = {"domain": {
    "id": "d", "name": "d", "entity_types": ["Acct"],
    "indicators": {"Acct": [
        {"name": "margin_balance", "type": "NUMERIC",
         "axioms": ["BOUNDEDNESS"], "window": "1h", "lower_critical": 0},
        {"name": "state", "type": "STATE", "axioms": ["STABILITY"],
         "window": "1h"}]}}}


def _session(model=MODEL):
    session = EngineSession()
    if model is not None:
        session.load_model(model)
    session.add_entity("acct_7", "Acct",
                       {"margin_balance": 1.2e6, "state": "ok"})
    return session


def _record(**overrides):
    record = {"model_id": "garch_v3", "issued_at": ISSUED, "horizon_s": 3600.0,
              "entity_id": "acct_7", "property": "margin_balance",
              "quantiles": {"q05": 1.0e6, "q50": 1.3e6, "q95": 1.6e6}}
    record.update(overrides)
    return record


def _ingest(session, records):
    return ingest_forecasts(session, records, at=NOW)


def _reasons(report):
    return [r["reason"] for r in report["rejected"]]


# --- the denominator ---------------------------------------------------------

def test_every_record_is_either_filed_or_reported():
    session = _session()
    report = _ingest(session, [
        _record(),
        _record(entity_id="nobody"),
        "not a mapping",
        _record(property="no_such_indicator"),
    ])
    assert report["received"] == 4
    assert report["filed"] + len(report["rejected"]) == report["received"]
    assert report["filed"] == 1


def test_one_bad_record_does_not_cost_the_batch():
    """The whole point of returning rather than raising."""
    session = _session()
    batch = [_record() for _ in range(9)] + ["not a mapping"]
    report = _ingest(session, batch)
    assert report["filed"] == 9
    assert len(session.ledger.records()) == 9


def test_an_empty_batch_is_not_an_error():
    report = _ingest(_session(), [])
    # `baselines` joined the tally when the engine began filing a random walk
    # beside every forecast it is SENT, not only beside its own projections.
    # Reported rather than assumed equal to `filed`: a pair with too little
    # history gets none, and *this model did not beat a random walk* must not
    # read the same as *nothing ran a random walk*.
    #
    # `raced` joined it next, for the half `baselines` could not carry. A desk
    # with six forecasts and four baselines could read the shortfall and not
    # WHICH two went unraced, nor whether the cause was a missing `lookback:`,
    # a series too short to fit, or a fit that failed -- three different things
    # to do about it. The count stays; the account sits beside it.
    #
    # THE ASSERTION IS STILL EXHAUSTIVE and that is the point of writing it
    # this way: an added key is a wire change, and it should have to be argued
    # for here rather than arriving unnoticed.
    assert report == {"received": 0, "filed": 0, "rejected": [],
                      "baselines": 0, "raced": []}


# --- what reaches the ledger -------------------------------------------------

def test_a_filed_forecast_reaches_the_ledger_with_its_model_named():
    """`model_id` is what makes `by_model` calibration possible, and a pooled
    score cannot answer the only question worth asking of a forecaster."""
    session = _session()
    _ingest(session, [_record(model_id="garch_v3"), _record(model_id="lstm_v1")])
    assert sorted(r.model_id for r in session.ledger.records()) == [
        "garch_v3", "lstm_v1"]


def test_the_issue_time_is_what_the_record_said_not_when_it_arrived():
    """A back-filled batch must be graded from when each forecast was MADE.
    Stamping arrival would move every maturity and score a producer against a
    horizon they never claimed."""
    session = _session()
    _ingest(session, [_record(issued_at=NOW - timedelta(hours=5))])
    assert session.ledger.records()[0].predicted_at == NOW - timedelta(hours=5)


def test_a_mean_and_sigma_arrive_as_quantiles():
    session = _session()
    report = _ingest(session, [_record(quantiles=None, mean=1.3e6, sigma=1.0e5)])
    assert report["filed"] == 1
    assert set(session.ledger.records()[0].quantiles) == {"q05", "q50", "q95"}


def test_the_horizon_travels_so_the_record_knows_when_to_mature():
    session = _session()
    _ingest(session, [_record(horizon_s=7200.0)])
    assert session.ledger.records()[0].horizon_s == 7200.0


# --- what the model refuses --------------------------------------------------

def test_a_forecast_for_an_entity_this_session_never_held_is_rejected():
    """Filed, it would sit pending until eviction -- counted in `pending` the
    whole time and gradeable never."""
    report = _ingest(_session(), [_record(entity_id="nobody")])
    assert _reasons(report) == ["entity_unknown"]
    assert "add it before forecasting it" in report["rejected"][0]["detail"]


def test_a_forecast_for_an_undeclared_indicator_is_rejected():
    report = _ingest(_session(), [_record(property="no_such_indicator")])
    assert _reasons(report) == ["undeclared_indicator"]
    assert "no threshold exists" in report["rejected"][0]["detail"]


def test_a_distribution_over_a_state_is_rejected():
    """There is nothing to score a quantile forecast of a label against."""
    report = _ingest(_session(), [_record(property="state")])
    assert _reasons(report) == ["wrong_indicator_type"]


def test_a_forecast_naming_the_mapped_property_is_accepted():
    """A producer speaks the model's vocabulary, and a model carrying a
    `property_mapping` has two names for one thing."""
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Acct"],
        "property_mapping": {"Acct": {"margin_balance": "bal_usd"}},
        "indicators": {"Acct": [
            {"name": "margin_balance", "type": "NUMERIC",
             "axioms": ["BOUNDEDNESS"], "window": "1h"}]}}})
    session.add_entity("acct_7", "Acct", {"bal_usd": 1.2e6})
    assert _ingest(session, [_record()])["filed"] == 1
    assert _ingest(session, [_record(property="bal_usd")])["filed"] == 1


def test_a_session_with_no_model_files_what_it_can_identify():
    """The entity check still applies -- grading needs one -- but there is no
    declaration to measure the property against, so the engine does not invent
    a refusal it has no grounds for."""
    session = EngineSession()
    session.add_entity("acct_7", "Acct", {"margin_balance": 1.0})
    report = _ingest(session, [_record(property="anything_at_all")])
    assert report["filed"] == 1


# --- the ledger's own rules, in the producer's vocabulary --------------------

def test_the_ledger_raise_becomes_a_rejection():
    """`record_distribution` raises on two keys naming one level, because from
    our own code that is a programming error. From a producer's JSON it is
    their typo, and the batch must survive it."""
    report = _ingest(_session(), [
        _record(quantiles={"q05": 1.0, "q1": 2.0, "q10": 2.0, "q95": 3.0}),
        _record(),
    ])
    assert _reasons(report) == ["malformed_forecast"]
    assert "one level" in report["rejected"][0]["detail"]
    assert report["filed"] == 1


def test_the_ledger_message_is_carried_rather_than_paraphrased():
    """Two wordings of one rule is how the two drift."""
    report = _ingest(_session(), [_record(quantiles={"q05": 1.0, "q1": 2.0,
                                                     "q10": 2.0, "q95": 3.0})])
    assert "`q1`, `q10` and `q100`" in report["rejected"][0]["detail"]


def test_nothing_in_a_malformed_batch_escapes_as_an_exception():
    """Swept deliberately: every shape that raises somewhere below has to
    surface as a row here instead."""
    session = _session()
    hostile = [
        None, 42, [], "text", {},
        _record(quantiles={}),
        _record(quantiles={"q05": float("nan"), "q95": 1.0}),
        _record(quantiles={"q05": 9.0, "q95": 1.0}),
        _record(horizon_s=-1),
        _record(issued_at="never"),
        _record(model_id=""),
        _record(samples=[1.0], quantiles=None),
        _record(mean=1.0, quantiles=None),
        _record(quantiles={"q05": 1.0, "q1": 1.0, "q10": 1.0, "q95": 2.0}),
    ]
    report = _ingest(session, hostile)
    assert report["received"] == len(hostile)
    assert report["filed"] == 0
    assert len(report["rejected"]) == len(hostile)


# --- what a rejection has to carry -------------------------------------------

def test_a_rejection_names_the_record_it_came_from():
    """A report of four hundred rows is unusable if the rows cannot be told
    apart."""
    report = _ingest(_session(), [_record(entity_id="nobody")])
    row = report["rejected"][0]
    assert row["entity_id"] == "nobody"
    assert row["indicator"] == "margin_balance"
    assert row["model_id"] == "garch_v3"


def test_a_rejection_that_could_not_read_an_identifier_omits_it():
    """Rather than filling it with a placeholder that would group four hundred
    unrelated failures under one fake id."""
    report = _ingest(_session(), ["not a mapping"])
    row = report["rejected"][0]
    assert "entity_id" not in row and "model_id" not in row


def test_the_reasons_are_distinguishable_because_the_remedies_differ():
    """An entity to add, an indicator to declare, and a type to correct are
    three different jobs; reading them as one backlog applies the wrong fix."""
    report = _ingest(_session(), [
        _record(entity_id="nobody"),
        _record(property="no_such_indicator"),
        _record(property="state"),
    ])
    assert _reasons(report) == [
        "entity_unknown", "undeclared_indicator", "wrong_indicator_type"]


# --- time --------------------------------------------------------------------

def test_the_present_moment_is_the_one_the_caller_states():
    """So a replay files the forecasts that existed then. Judging a back-fill
    against wall-clock now refuses every record in it."""
    session = _session()
    record = _record(issued_at=datetime(2026, 8, 1, 12, 0))
    assert ingest_forecasts(session, [record],
                            at=datetime(2026, 8, 1, 13, 0))["filed"] == 1
    assert ingest_forecasts(session, [record],
                            at=datetime(2026, 8, 1, 11, 0))["filed"] == 0


def test_a_forecast_from_the_future_is_rejected_by_the_batch_not_the_parser():
    """The parser owns the rule; this asserts the feeder actually consults it
    rather than passing its own clock and getting a different answer."""
    report = _ingest(_session(), [_record(issued_at=NOW + timedelta(hours=1))])
    assert _reasons(report) == ["malformed_forecast"]
    assert "after the present moment" in report["rejected"][0]["detail"]


# --- the assumption the engine adds -----------------------------------------

def test_an_expanded_forecast_is_filed_and_its_assumption_is_not_lost():
    """The stamp lives on the parsed record. Until the sub-envelope carries it
    this test is what says the expansion happened at all -- and it is the
    reason the next slice has something to publish."""
    session = _session()
    from arbiter_engine.forecast import parse_forecast
    forecast, rejected = parse_forecast(
        _record(quantiles=None, mean=1.0, sigma=1.0), at=NOW)
    assert rejected is None
    assert GAUSSIAN_STAMP in forecast.assumptions
    assert _ingest(session, [_record(quantiles=None, mean=1.0,
                                     sigma=1.0)])["filed"] == 1
