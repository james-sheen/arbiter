"""`ingest_forecasts(source=)`, asserted on the engine's own side.

0.1.17 changed the producer predicate in four places -- `forecast/envelope.py`,
two sites in `forecast/shadow.py` and one in `forecast/monitor.py` -- from *is
not the engine's* to *has no source*, and gave `ingest_forecasts` the parameter
that makes the second reachable. No engine test filed a record with a source.
The only thing exercising the path was a downstream repository's CLI test,
which asserts an exit code and a membership list: a regression in any one of
the three exclusion sites would have passed this suite and been caught, if at
all, by somebody else's.

WHY A PRODUCER IS THE ONE WITH NO SOURCE. The forecasts leg answers *did the
producer send what was expected*. A caller running a reference forecaster
beside the desk's is not answering that question -- it is supplying the
yardstick the question is measured against -- so counting its rows as
submissions let a bridge's own EWMA raise the exit code of the audit it was
inside. `None` is the producer because `None` is what every caller predating
the parameter was.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, check
from arbiter_engine.clock import as_of
from arbiter_engine.forecast import (
    ingest_forecasts, model_figures,
)
from arbiter_engine.projection.projector import SOURCE_ENGINE

NOW = datetime(2026, 9, 17, 10, 0)
ISSUED = NOW - timedelta(minutes=30)

MODEL = {"domain": {
    "id": "d", "name": "d", "entity_types": ["Acct"],
    "indicators": {"Acct": [
        {"name": "margin_balance", "type": "NUMERIC",
         "axioms": ["BOUNDEDNESS"], "window": "1h", "lower_critical": 0,
         "forecast": {"expected": True}}]}}}


def _session():
    session = EngineSession()
    session.load_model(MODEL)
    session.add_entity("acct_7", "Acct", {"margin_balance": 1.2e6})
    return session


def _record(model_id):
    return {"model_id": model_id, "issued_at": ISSUED, "horizon_s": 3600.0,
            "entity_id": "acct_7", "property": "margin_balance",
            "quantiles": {"q05": 1.0e6, "q50": 1.3e6, "q95": 1.6e6}}


def _forecasts(session):
    with as_of(NOW):
        return check(session).to_dict()["forecasts"]


class TestASourcedRecordIsNotASubmission:

    def test_it_files_and_is_not_counted_as_received(self):
        session = _session()
        with as_of(NOW):
            report = ingest_forecasts(session, [_record("ewma_v1")],
                                      at=NOW, source="ewma_v1")
        assert report["filed"] == 1, "the record must still be FILED"
        leg = _forecasts(session)
        assert leg["checked"]["received"] == 0, (
            "a sourced record answered the producer's question; `received` "
            "counts submissions and there were none")
        assert leg["checked"]["reference"] == 1

    def test_the_pair_still_reads_as_unfilled(self):
        """The half that makes the exclusion worth anything. If the sourced
        record silenced `forecast_missing`, a desk that sent nothing would
        look answered by the yardstick measuring it."""
        session = _session()
        with as_of(NOW):
            ingest_forecasts(session, [_record("ewma_v1")], at=NOW,
                             source="ewma_v1")
        reasons = [d["reason"] for d in _forecasts(session)["not_checked"]]
        assert "forecast_missing" in reasons

    def test_a_producer_record_still_counts(self):
        """Non-vacuity: the same assertions with no source must go the other
        way, or the test above passes on an engine that files nothing."""
        session = _session()
        with as_of(NOW):
            ingest_forecasts(session, [_record("garch_v3")], at=NOW)
        leg = _forecasts(session)
        assert leg["checked"]["received"] == 1
        assert leg["checked"]["reference"] == 0
        assert "forecast_missing" not in [
            d["reason"] for d in leg["not_checked"]]

    def test_it_is_not_judged_by_the_shadow_axioms(self):
        session = _session()
        with as_of(NOW):
            ingest_forecasts(session, [_record("ewma_v1")], at=NOW,
                             source="ewma_v1")
            shadow = check(session).to_dict()["shadow"]
        assert shadow["checked"].get("entities", 0) == 0, (
            "a caller's reference was shadowed; the shadow pass judges what a "
            "producer claimed, and this row is not a claim")

    def test_it_produces_no_producer_figures(self):
        session = _session()
        with as_of(NOW):
            ingest_forecasts(session, [_record("ewma_v1")], at=NOW,
                             source="ewma_v1")
            figures = model_figures(session)
        assert "ewma_v1" not in {f.get("model_id") for f in figures}, (
            "the reference appeared among the producer figures it exists to "
            "be compared against")

    def test_a_model_allow_list_does_not_refuse_it(self):
        """`models:` names who may submit. A yardstick is not submitting, so
        an unlisted reference must not decline `model_unknown`."""
        model = {"domain": {
            "id": "d", "name": "d", "entity_types": ["Acct"],
            "indicators": {"Acct": [
                {"name": "margin_balance", "type": "NUMERIC",
                 "axioms": ["BOUNDEDNESS"], "window": "1h",
                 "lower_critical": 0,
                 "forecast": {"expected": True, "models": ["garch_v3"]}}]}}}
        session = EngineSession()
        session.load_model(model)
        session.add_entity("acct_7", "Acct", {"margin_balance": 1.2e6})
        with as_of(NOW):
            ingest_forecasts(session, [_record("ewma_v1")], at=NOW,
                             source="ewma_v1")
        reasons = [d["reason"] for d in _forecasts(session)["not_checked"]]
        assert "model_unknown" not in reasons


class TestAnEmptySourceIsStillASource:
    """`str(source) if source else None` folded `""` to `None`, and `None` is
    the producer predicate -- so a caller supplying an empty source was
    silently reclassified into the population the parameter exists to keep
    them out of. Reachable through any falsy value.
    """

    def test_it_does_not_become_a_producer(self):
        session = _session()
        with as_of(NOW):
            ingest_forecasts(session, [_record("ewma_v1")], at=NOW, source="")
        leg = _forecasts(session)
        assert leg["checked"]["received"] == 0, (
            "an empty source was read as no source, which made a caller's row "
            "a producer's submission")
        assert leg["checked"]["reference"] == 1


class TestTheThreeCountsPartitionTheReferences:
    """`reference` counts every sourced record; `baselines`,
    `engine_projections` and `caller_references` split it. The split shipped in
    0.1.17 matching `model_id != baseline_rw`, which had been sound while the
    engine was the only thing that could set a source -- and the same release
    let a caller set one, so a bridge's EWMA rows were counted as the engine's
    own projections. Measured then: a session in which `project` never ran
    reported `engine_projections: 1`.
    """

    def test_a_caller_reference_is_not_an_engine_projection(self):
        session = _session()
        with as_of(NOW):
            ingest_forecasts(session, [_record("ewma_v1")], at=NOW,
                             source="ewma_v1")
        checked = _forecasts(session)["checked"]
        assert checked["engine_projections"] == 0, (
            "`project` never ran in this session; nothing of the engine's was "
            "filed")
        assert checked["caller_references"] == 1

    def test_the_three_sum_to_reference(self):
        """Stated as a partition so a fourth population cannot be added
        without one of the counts moving."""
        session = _session()
        with as_of(NOW):
            ingest_forecasts(session, [_record("ewma_v1")], at=NOW,
                             source="ewma_v1")
            ingest_forecasts(session, [_record("garch_v3")], at=NOW)
        checked = _forecasts(session)["checked"]
        assert (checked["baselines"] + checked["engine_projections"]
                + checked["caller_references"]) == checked["reference"]

    def test_a_caller_may_not_be_counted_as_a_yardstick_by_naming_itself_one(self):
        """`baselines` matched on the model id alone. A caller's row named
        `baseline_rw` would have counted as a yardstick the ENGINE filed, and
        as a caller's row, both -- so the counts stopped partitioning."""
        session = _session()
        with as_of(NOW):
            ingest_forecasts(session, [_record("baseline_rw")], at=NOW,
                             source="somebody_else")
        checked = _forecasts(session)["checked"]
        assert checked["baselines"] == 0, (
            "a caller's row named itself the engine's random walk and was "
            "counted as one")
        assert checked["caller_references"] == 1
        assert (checked["baselines"] + checked["engine_projections"]
                + checked["caller_references"]) == checked["reference"]


class TestTheFeedersAreOnTheSupportedSurface:
    """`api` is a supported name; `forecast` and `clock` are not.

    An indicator declaring `forecast: {expected: true}` is waiting for a
    prediction this engine will never make, so a bridge is the only thing that
    can supply one -- and until 0.1.18 the only spellings for the call were
    `arbiter_engine.forecast` and `arbiter_engine.clock`, deep paths the README
    says may move without a major version. The first bridge built on this engine
    took both, and its `<0.2` ceiling was claiming a promise nobody had made.

    This also gives `_FEEDERS_ON_THE_SUPPORTED_SURFACE` a reader. A constant
    documenting a decision and read by nothing is the same dead-name shape as a
    decline reason with no producer -- it stops being evidence the moment it
    stops being checked.
    """

    def test_every_named_feeder_is_present_and_callable(self):
        from arbiter_engine import api

        missing = [name for name in api._FEEDERS_ON_THE_SUPPORTED_SURFACE
                   if not callable(getattr(api, name, None))]
        assert not missing, (
            f"named as re-exported onto `api` and not there: {missing}")

    def test_the_list_is_not_empty(self):
        """Non-vacuity: every assertion here is over that tuple."""
        from arbiter_engine import api

        assert api._FEEDERS_ON_THE_SUPPORTED_SURFACE

    def test_they_are_the_same_objects_as_the_deep_path(self):
        """Re-exported, NOT reimplemented. Two callables that drift apart would
        be worse than the deep path, because the two spellings would then mean
        different things while reading as synonyms."""
        from arbiter_engine import api, clock
        from arbiter_engine import forecast

        assert api.ingest_forecasts is forecast.ingest_forecasts
        assert api.feed_model_figures is forecast.feed_model_figures
        assert api.model_figures is forecast.model_figures
        assert api.as_of is clock.as_of
