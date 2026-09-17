"""The ledger belongs to the session, and `check` is where maturity is noticed.

Before this the ledger was one object for the whole process, created on first
use and gated on an environment variable that is OFF by default. That shape is
right for the hook it was written for and wrong for this API in two ways, both
of which fail quietly:

- two sessions in one long-lived server would grade each other's predictions,
  because a record is keyed by entity id and nothing says which session filed
  it;
- a consumer who never set the variable would find that predictions recorded
  through a session verb went nowhere, and the ledger's own reason for existing
  is that a prediction nobody grades is a prediction nobody made.

A session-owned ledger is unconditional and isolated. The module singleton is
untouched and still serves its gated callsite, which the last test pins --
a repair that fixes one surface by breaking another is not one.

`check` grades because it is the cycle boundary: a prediction whose horizon
passed between two calls is graded on the next one rather than whenever
somebody remembers to ask. It reports nothing new in the envelope, and the
test that matters most here is the one asserting exactly that.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from conftest import ENTITY_ID, ENTITY_TYPE, model_for, session_for

from arbiter_engine.api import EngineSession, check
from arbiter_engine.history.observation import InMemoryObservationHistory
from arbiter_engine.residual.predict_vs_mirror import (
    GRADE_CONFIRMED, PredictionLedger, get_prediction_ledger,
    reset_prediction_ledger,
)

BAND = {"q05": 100.0, "q50": 130.0, "q95": 160.0}


def test_a_session_has_a_ledger_without_being_asked():
    assert isinstance(EngineSession().ledger, PredictionLedger)


def test_two_sessions_do_not_share_a_ledger():
    one, two = EngineSession(), EngineSession()
    one.ledger.record_distribution("e", "p", dict(BAND), 60.0, "m")
    assert len(one.ledger.records()) == 1
    assert two.ledger.records() == []


def test_the_session_ledger_is_not_the_module_singleton():
    """The singleton stays gated and untouched; this one is neither."""
    reset_prediction_ledger()
    session = EngineSession()
    session.ledger.record_distribution("e", "p", dict(BAND), 60.0, "m")
    assert get_prediction_ledger().records() == []
    reset_prediction_ledger()


def test_a_history_can_be_injected():
    """The default is a seven-day ring and a replay needs a decade."""
    long_memory = InMemoryObservationHistory(
        retention_period=timedelta(days=3650), max_observations_per_key=10 ** 6)
    assert EngineSession(history=long_memory).history is long_memory


def test_the_default_history_is_unchanged():
    assert isinstance(EngineSession().history, InMemoryObservationHistory)


# --- check as the cycle boundary -------------------------------------------

def _checkable_session():
    session = session_for("BOUNDEDNESS")
    session.add_observations(ENTITY_ID, "level_pct", [10.0] * 10)
    return session


def test_check_grades_a_matured_prediction():
    """The seam, exercised end to end: a record filed before the check and
    matured by the time it runs comes back graded, with no separate call."""
    session = _checkable_session()
    at = datetime(2020, 1, 1)
    session.ledger.record_distribution(
        ENTITY_ID, "level_pct", dict(BAND), 60.0, "m", predicted_at=at)
    session.history.add(ENTITY_ID, "level_pct", 131.0,
                        timestamp=at + timedelta(seconds=60))
    assert session.ledger.records()[0].verdict is None

    check(session)

    record = session.ledger.records()[0]
    assert record.verdict == GRADE_CONFIRMED
    assert record.scores["covered_90"] is True


def test_check_reports_nothing_new_when_the_ledger_is_empty():
    """The payload set this verb carries is closed BY AN ARGUMENT, not by a
    count, and a calibration summary does not meet it: these three keys answer
    *did what I declared actually take effect*, which is the question `check`
    IS. A ledger summary answers a different one, so grading a matured
    prediction adds nothing here however many records it touched.

    `underived` joined them on the same argument rather than by growing the
    list: a derived indicator whose operand is missing declines on a property
    nobody feeds, so the envelope reported a real reason under a name that is a
    dead end. Any fourth key needs the argument too, which is why this asserts
    EQUALITY and not containment.

    `forecasts` is the fourth and the argument holds: `expected` against
    `received` is *the forecasts I declared, did they arrive*, and
    `forecast_missing` is a declaration that took no effect. That is the same
    question, asked of an input surface rather than of a property. A leg
    carrying only what a forecaster HAPPENED to send would not qualify -- it
    would be a summary, like the calibration figures above, and those stay out.
    """
    envelope = check(_checkable_session()).to_dict()
    assert set(envelope) == {
        "checked", "findings", "not_checked", "questions", "meta",
        "unread_properties", "dropped_declarations", "underived", "forecasts",
    }
    assert envelope["underived"] == []


def test_grading_does_not_move_the_denominator():
    """Two denominators are never summed. `checked.invariants` counts axiom
    evaluations attempted, and a graded prediction is not one."""
    session = _checkable_session()
    before = check(session).to_dict()["checked"]["invariants"]
    session.ledger.record_distribution(
        ENTITY_ID, "level_pct", dict(BAND), 60.0, "m",
        predicted_at=datetime(2020, 1, 1))
    after = check(session).to_dict()["checked"]["invariants"]
    assert before == after
