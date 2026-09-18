"""Predictions and their grades survive the process that made them.

`README.md` names this as a boundary rather than an oversight and
says what it costs: `grade_matured` scores a record when its horizon has
passed AND the record is still in the live session's ledger, so *did it beat a
random walk* is answerable only by a process that outlives the horizon. A
one-shot command that loads a model, ingests forecasts and exits can never
learn whether any of them were right, and the next process starts with a
calibration rate of null -- which reads as *no data* rather than as *this tool
cannot answer that question*.

WHAT IS PINNED IS THE CONTRACT, NOT THE STORAGE. The durable ledger subclasses
the in-memory one and changes exactly one thing: where records live between
processes. Every grading rule is the base class's, so the tests that matter
are the ones asserting the two ledgers AGREE -- a second implementation of
what CONFIRMED means is how two ledgers come to disagree about it.

THE RING CAP STILL APPLIES, deliberately. A durable store could keep
everything, and then `records()` would return a different population before
and after a restart, making the calibration denominator depend on when the
process happened to start.
"""
from __future__ import annotations

import os
from datetime import timedelta

import pytest

from arbiter_engine.clock import now_utc
from arbiter_engine.history.observation import (
    InMemoryObservationHistory)
from arbiter_engine.residual.predict_vs_mirror import (
    PredictionLedger)
from arbiter_engine.residual.sqlite_ledger import (
    SqlitePredictionLedger)


@pytest.fixture(autouse=True)
def _gate_on(monkeypatch):
    monkeypatch.setenv("DT_PREDICT_VS_MIRROR_ENABLED", "1")


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "predictions.db")


def _file(ledger, at, value=50.0, tolerance=2.0):
    return ledger.record_value_prediction(
        "e1", "v", predicted_value=value, tolerance=tolerance,
        horizon_s=60.0, predicted_at=at)


def _history(value, at):
    history = InMemoryObservationHistory()
    history.add("e1", "v", value, at)
    return history


class TestARecordSurvivesTheProcess:

    def test_a_new_ledger_on_the_same_file_sees_the_prediction(self, db):
        now = now_utc()
        first = SqlitePredictionLedger(db)
        prediction_id = _file(first, now - timedelta(seconds=120))
        first.close()

        second = SqlitePredictionLedger(db)
        assert [r.prediction_id for r in second.records()] == [prediction_id]
        assert len(second.pending()) == 1
        second.close()

    def test_the_in_memory_ledger_does_not(self):
        """The control. Without this, the test above proves nothing about
        persistence -- only that a ledger can hold a record."""
        now = now_utc()
        _file(PredictionLedger(), now - timedelta(seconds=120))
        assert PredictionLedger().records() == []

    def test_a_verdict_written_by_one_process_is_read_by_the_next(self, db):
        now = now_utc()
        first = SqlitePredictionLedger(db)
        prediction_id = _file(first, now - timedelta(seconds=120))
        first.close()

        second = SqlitePredictionLedger(db)
        second.grade_matured([], {"e1"}, now=now,
                             histories=[_history(50.5,
                                                 now - timedelta(seconds=30))])
        second.close()

        third = SqlitePredictionLedger(db)
        record = next(r for r in third.records()
                      if r.prediction_id == prediction_id)
        assert record.verdict == "confirmed"
        third.close()

    def test_calibration_is_answerable_across_a_restart(self, db):
        """The number the README says is out of reach."""
        now = now_utc()
        first = SqlitePredictionLedger(db)
        _file(first, now - timedelta(seconds=120))
        first.close()
        second = SqlitePredictionLedger(db)
        second.grade_matured([], {"e1"}, now=now,
                             histories=[_history(50.5,
                                                 now - timedelta(seconds=30))])
        second.close()
        third = SqlitePredictionLedger(db)
        assert third.calibration()["confirm_rate"] == 1.0
        third.close()


class TestTheTwoLedgersAgree:
    """The durable one must not be a second answer to what CONFIRMED means."""

    @pytest.mark.parametrize("observed,expected", [
        (50.5, "confirmed"),
        (70.0, "falsified"),
        (None, "ungradeable"),
    ])
    def test_the_verdict_is_the_same_in_both(self, db, observed, expected):
        now = now_utc()
        histories = ([_history(observed, now - timedelta(seconds=30))]
                     if observed is not None else [InMemoryObservationHistory()])

        durable = SqlitePredictionLedger(db)
        durable_id = _file(durable, now - timedelta(seconds=120))
        durable.grade_matured([], {"e1"}, now=now, histories=histories)
        durable_verdict = next(r.verdict for r in durable.records()
                               if r.prediction_id == durable_id)
        durable.close()

        memory = PredictionLedger()
        memory_id = _file(memory, now - timedelta(seconds=120))
        memory.grade_matured([], {"e1"}, now=now, histories=histories)
        memory_verdict = next(r.verdict for r in memory.records()
                              if r.prediction_id == memory_id)

        assert durable_verdict == memory_verdict == expected

    def test_an_immature_prediction_is_graded_by_neither(self, db):
        """At maturity AND NOT BEFORE. A ledger that graded early would score
        a prediction against a reading from before its horizon."""
        now = now_utc()
        durable = SqlitePredictionLedger(db)
        _file(durable, now)          # horizon 60s, filed now: not yet mature
        durable.grade_matured([], {"e1"}, now=now,
                              histories=[_history(50.5, now)])
        assert len(durable.pending()) == 1
        assert all(r.verdict is None for r in durable.records())
        durable.close()


class TestTheFileHoldsWhatTheRingHolds:

    def test_the_cap_applies_to_the_file_too(self, db):
        now = now_utc()
        ledger = SqlitePredictionLedger(db, ring_cap=3)
        for k in range(6):
            _file(ledger, now - timedelta(seconds=120 + k))
        ledger.close()
        reopened = SqlitePredictionLedger(db, ring_cap=3)
        assert len(reopened.records()) == 3, (
            "the file kept more than the ring, so the calibration denominator "
            "would depend on when the process started")
        reopened.close()

    def test_the_evicted_pending_count_survives(self, db):
        """The one number that says how much the ledger is NOT telling you."""
        now = now_utc()
        ledger = SqlitePredictionLedger(db, ring_cap=2)
        for k in range(5):
            _file(ledger, now - timedelta(seconds=120 + k))
        evicted = ledger.evicted_pending
        ledger.close()
        assert evicted > 0, "guard: no eviction here makes this vacuous"
        reopened = SqlitePredictionLedger(db, ring_cap=2)
        assert reopened.evicted_pending == evicted
        reopened.close()


class TestAnUnreadableRowIsCountedNotFatal:

    def test_a_corrupt_row_is_skipped_and_reported(self, db, tmp_path):
        import sqlite3
        now = now_utc()
        ledger = SqlitePredictionLedger(db)
        _file(ledger, now - timedelta(seconds=120))
        ledger.close()

        connection = sqlite3.connect(db)
        connection.execute(
            "INSERT INTO predictions (prediction_id, filed_at, payload) "
            "VALUES ('bogus', 1.0, 'not json')")
        connection.commit()
        connection.close()

        reopened = SqlitePredictionLedger(db)
        assert reopened.unreadable_rows == 1, (
            "a ledger that will not open because one row came from a "
            "neighbouring build is worse than one that opens and says how "
            "many rows it could not read")
        assert len(reopened.records()) == 1
        reopened.close()
