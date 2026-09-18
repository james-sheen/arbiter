"""*Does it beat a random walk* can only be asked if something runs one.

THE REFERENCE WAS KEPT FOR ONE OF THE TWO KINDS OF FORECAST. `project` fitted a
random walk on the same series and horizon and filed it beside its own
projection; `ingest_forecasts` -- the surface a desk's feed actually arrives on
-- filed the producer's record and nothing else. So the changelog's "the
reference every forecaster is measured against ... filed on the same series and
the same horizon as the forecast it judges" held for the forecasts the engine
made and not for the ones it was sent, which is the opposite of where the
question is interesting: nobody needs to be told the engine's own local-level
model beat a random walk.

AS OF WHEN THE FORECAST WAS ISSUED, not as of now. The yardstick is fitted
under the producer's own instant, so it sees what the producer could have seen
and not one reading more. Fitting on everything up to the present would hand
the reference a look at the outcome it is being compared on -- and it would
win, which is worse than losing, because the number would look like a result.

REPORTED, NOT ASSUMED. `ingest_forecasts` returns how many yardsticks it filed,
because a pair with too little history gets none -- and *this model did not
beat a random walk* must not read the same as *nothing ran a random walk*.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession
from arbiter_engine.clock import as_of
from arbiter_engine.forecast import ingest_forecasts
from arbiter_engine.projection.projector import (
    BASELINE_MODEL_ID, SOURCE_ENGINE)

T0 = datetime(2026, 9, 17, 9, 35)


def _session(samples=200):
    session = EngineSession()
    session.load_model({"domain": {
        "id": "margin-book", "name": "book", "entity_types": ["Account"],
        "indicators": {"Account": [{
            "name": "margin_balance", "type": "NUMERIC",
            "axioms": ["BOUNDEDNESS"], "lower_critical": 900.0,
            "window": "1h", "lookback": "7d",
            "forecast": {"expected": True},
        }]}}})
    session.add_entity("acct_01", "Account", {"margin_balance": 1000.0})
    if samples:
        base = T0 - timedelta(days=1)
        session.add_observations("acct_01", "margin_balance", [
            (base + timedelta(minutes=7 * i), 1000.0 + (i % 11) * 3.0)
            for i in range(samples)])
    return session


def _feed(session, *, model_id="garch_v3", minutes_ago=5, horizon=3600.0):
    with as_of(T0):
        return ingest_forecasts(session, [{
            "model_id": model_id, "entity_id": "acct_01",
            "property": "margin_balance", "horizon_s": horizon,
            "issued_at": T0 - timedelta(minutes=minutes_ago),
            "quantiles": {"q05": 850.0, "q50": 1000.0, "q95": 1120.0}}], at=T0)


def _baselines(session):
    return [r for r in session.ledger.records()
            if r.model_id == BASELINE_MODEL_ID]


class TestAnOutsideForecastIsMeasuredAgainstSomething:

    def test_a_baseline_is_filed_beside_it(self):
        session = _session()
        assert _feed(session)["baselines"] == 1
        assert len(_baselines(session)) == 1

    def test_on_the_same_horizon_and_the_same_instant(self):
        """A reference scored on a different population answers nothing."""
        session = _session()
        _feed(session, horizon=7200.0, minutes_ago=5)
        reference = _baselines(session)[0]
        producer = [r for r in session.ledger.records()
                    if r.model_id == "garch_v3"][0]
        assert reference.horizon_s == producer.horizon_s
        assert reference.predicted_at == producer.predicted_at

    def test_it_is_tagged_as_the_engines_own(self):
        session = _session()
        _feed(session)
        assert _baselines(session)[0].source == SOURCE_ENGINE

    def test_the_reference_is_fitted_as_of_the_issuing_instant(self):
        """Not as of now. Readings after the forecast was issued must not
        reach the yardstick -- a reference that saw the outcome wins, and the
        number would look like a result."""
        session = _session()
        # A cliff AFTER the issuing instant. If the fit saw it the median
        # would be dragged toward it; the series before the instant sits
        # around 1000.
        session.add_observations("acct_01", "margin_balance", [
            (T0 - timedelta(minutes=4), 5000.0),
            (T0 - timedelta(minutes=3), 5000.0),
            (T0 - timedelta(minutes=2), 5000.0)])
        _feed(session, minutes_ago=5)
        median = _baselines(session)[0].quantiles["q50"]
        assert median < 2000.0, (
            f"the yardstick was fitted on data issued after it: q50={median}")


class TestTheReferenceDoesNotMultiply:

    def test_two_producers_on_one_pair_share_one_yardstick(self):
        session = _session()
        _feed(session, model_id="garch_v3")
        second = _feed(session, model_id="lstm_v1")
        assert second["baselines"] == 0
        assert len(_baselines(session)) == 1

    def test_the_reference_does_not_race_itself(self):
        session = _session()
        assert _feed(session, model_id=BASELINE_MODEL_ID)["baselines"] == 0


class TestWhenThereIsNoYardstickItSaysSo:

    def test_too_little_history_files_none_and_reports_none(self):
        session = _session(samples=3)
        assert _feed(session)["baselines"] == 0
        assert _baselines(session) == []

    def test_the_producers_record_is_filed_anyway(self):
        """A reference that could not be fitted must not cost the batch."""
        session = _session(samples=3)
        assert _feed(session)["filed"] == 1


class TestTheAccountSaysWHICHOneWentUnraced:
    """`baselines: 4` out of six forecasts is a shortfall a desk can read and
    cannot act on. Which two? And was the cause a missing `lookback:`, a series
    too short to fit, or a fit that failed -- three different things to do.

    The count stays, because a reader who only wants the headline should not
    have to walk a list. The account sits beside it.
    """

    def _report(self):
        from datetime import datetime, timedelta

        from arbiter_engine.api import EngineSession
        from arbiter_engine.clock import as_of
        from arbiter_engine.forecast import ingest_forecasts

        t0 = datetime(2026, 9, 17, 9, 35)
        session = EngineSession()
        session.load_model({"domain": {
            "id": "b", "name": "b", "entity_types": ["A"],
            "indicators": {"A": [
                {"name": "fed", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                 "critical": 5000.0, "window": "1h", "lookback": "7d",
                 "horizon": "1h"},
                {"name": "unfed", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                 "critical": 5000.0, "window": "1h", "lookback": "7d",
                 "horizon": "1h"},
            ]}}})
        session.add_entity("a1", "A", {"fed": 1000.0, "unfed": 1.0})
        base = t0 - timedelta(days=1)
        session.add_observations("a1", "fed", [
            (base + timedelta(minutes=7 * i), 1000.0 + (i % 11))
            for i in range(50)])
        rows = [{"model_id": "m1", "entity_id": "a1", "property": name,
                 "horizon_s": 3600.0, "issued_at": t0 - timedelta(minutes=5),
                 "quantiles": {"q05": 0.5, "q50": 1.0, "q95": 1.5}}
                for name in ("fed", "unfed")]
        with as_of(t0):
            return ingest_forecasts(session, rows, at=t0)

    def test_the_count_and_the_account_agree(self):
        report = self._report()
        filed = [r for r in report["raced"] if r["baseline"] == "filed"]
        assert len(filed) == report["baselines"]

    def test_the_unraced_one_carries_a_reason_and_not_just_a_gap(self):
        raced = {r["indicator"]: r["baseline"] for r in self._report()["raced"]}
        assert raced["fed"] == "filed"
        assert raced["unfed"] not in (None, "filed", ""), (
            "a forecast with no yardstick must say why; silence here is the "
            "shortfall repeated in a second place")
