"""The engine grades producers and shipped none, so nothing had ever raced it.

Phase B3. `STANCE.md` says what a producer is and what this engine owes
one, and `ingest_forecasts(source=)` is the door. Nothing in this repository
walked through it, so the whole producer path was exercised by fixtures -- and a
consumer asking *what does a reasonable forecaster score here* had nothing to
compare against.

WHY A RANDOM WALK IS THE WRONG OPPONENT TO STOP AT. The engine's own baseline
predicts the last value and widens with the horizon. That is the right FLOOR and
a poor opponent: anything that notices a series is going somewhere beats it, so
`beats_baseline: true` against a random walk alone says almost nothing. A shipped
producer one step up gives the comparison a second point.

WHAT MAKES THIS A PRODUCER AND NOT AN ENGINE FEATURE, which is the part worth
guarding: it reads the session through `reading_history()` -- the accessor the
engine tells every reader to use -- and files ordinary records through
`ingest_forecasts`. It imports no checker and is handed no privilege an outside
forecaster would be refused. A baseline with access the competition lacks is not
a baseline, and the test below asserts the import surface as well as the score.
"""

from __future__ import annotations

import datetime as dt

import pytest

from arbiter_engine import api
from arbiter_engine.producers import (
    BASELINE_MODEL_ID, MINIMUM_POINTS, SeriesRefused, forecast_series,
    forecast_session)

STEP_S = 60.0
HORIZON_S = 600.0
SLOPE = 2.0
START = 100.0

MODEL = {"domain": {
    "id": "raced", "name": "A series going somewhere",
    "entity_types": ["T"], "relationship_types": [],
    "indicators": {"T": [{"name": "v", "type": "NUMERIC",
                          "axioms": ["BOUNDEDNESS"], "critical": 9e9}]}}}


def _session(points=40):
    session = api.EngineSession()
    session.load_model(MODEL)
    session.add_entity("e1", "T", {"v": START})
    now = api.now_utc()
    for k in range(points):
        when = now - dt.timedelta(seconds=STEP_S * (points - k))
        session.add_observations("e1", "v", [(when, START + SLOPE * k)])
    return session


def _last_value(points=40):
    return START + SLOPE * (points - 1)


class TestItIsAProducerAndNotAPrivilegedOne:
    """The claim that makes the comparison mean anything."""

    def test_it_imports_no_checker_or_envelope(self):
        import pathlib
        src = (pathlib.Path(forecast_series.__code__.co_filename)
               .read_text())
        for forbidden in ("from ..api", "from ..ontology", "from ..subenvelope",
                          "import check", "Envelope"):
            assert forbidden not in src, (
                f"the producer reaches for `{forbidden}`; a baseline with "
                f"access the competition lacks is not a baseline")

    def test_it_reads_the_store_the_engine_tells_readers_to_ask(self):
        """Asked of the PARSE TREE. The first draft grepped the source for
        `session.history` -- and failed, because the docstring explaining why
        that store is the wrong one contains the phrase. A pattern tested
        against a body that includes the pattern, for the fourth time in this
        codebase; an AST walk sees attribute access and cannot see prose."""
        import ast
        import pathlib
        tree = ast.parse(
            pathlib.Path(forecast_session.__code__.co_filename).read_text())
        calls = {n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)}
        assert "reading_history" in calls, (
            "the producer does not ask the store the engine tells readers "
            "to ask")
        raw = [n for n in ast.walk(tree)
               if isinstance(n, ast.Attribute) and n.attr == "history"
               and isinstance(n.value, ast.Name) and n.value.id == "session"]
        assert not raw, (
            "`session.history` is what was FED; `reading_history()` is what "
            "the model says that feed MEANS, and the two differ whenever a "
            "calendar or a derived indicator is declared")

    def test_it_files_through_the_public_door(self):
        session = _session()
        records = forecast_session(session, horizon_s=HORIZON_S)
        report = api.ingest_forecasts(session, records,
                                      source="baseline-learner")
        assert report["received"] == len(records) >= 1
        assert report["filed"] == report["received"]


class TestItRefusesRatherThanGuessing:

    def test_a_short_series_gets_no_forecast(self):
        session = _session(points=MINIMUM_POINTS - 1)
        assert forecast_session(session, horizon_s=HORIZON_S) == [], (
            "a series too short to fit was fitted anyway")

    def test_an_unordered_series_is_refused_and_not_sorted(self):
        now = api.now_utc()
        points = [(now, 1.0), (now - dt.timedelta(seconds=60), 2.0)]
        with pytest.raises(SeriesRefused):
            forecast_series(points, entity_id="e1", property_name="v",
                            horizon_s=HORIZON_S)

    def test_the_record_names_itself(self):
        session = _session()
        record = forecast_session(session, horizon_s=HORIZON_S)[0]
        assert record["model_id"] == BASELINE_MODEL_ID
        assert record["sample_count"] == 40, (
            "a q05 from twenty samples and one from twenty thousand are "
            "different claims; the count is what distinguishes them")


class TestItIsWorthBeating:
    """The measurement the phase item exists for."""

    def test_it_lands_nearer_than_the_random_walk(self):
        """MEASURED, on a series with a real trend: the walk predicts the last
        value it saw, and the truth has moved on since."""
        session = _session()
        record = forecast_session(session, horizon_s=HORIZON_S)[0]
        walk = _last_value()
        truth = walk + SLOPE * (HORIZON_S / STEP_S)
        mine = abs(record["quantiles"]["q50"] - truth)
        theirs = abs(walk - truth)
        assert mine < theirs, (
            f"the producer is {mine:.3f} from the truth and the random walk "
            f"{theirs:.3f}; an opponent that loses to the floor is not one")

    def test_the_interval_carries_the_residual_spread(self):
        """Not a confidence interval, and the test says so: the quantiles are
        the one-step residuals widened by the horizon, which is the walk's own
        rule applied to a better centre."""
        record = forecast_session(_session(), horizon_s=HORIZON_S)[0]
        q = record["quantiles"]
        assert q["q05"] < q["q50"] < q["q95"]

    def test_a_flat_series_does_not_invent_a_trend(self):
        """The damping is what stops a baseline extrapolating noise. A series
        that goes nowhere must forecast roughly where it is."""
        session = api.EngineSession()
        session.load_model(MODEL)
        session.add_entity("e1", "T", {"v": 50.0})
        now = api.now_utc()
        for k in range(40):
            session.add_observations(
                "e1", "v", [(now - dt.timedelta(seconds=STEP_S * (40 - k)),
                             50.0)])
        record = forecast_session(session, horizon_s=HORIZON_S)[0]
        assert record["quantiles"]["q50"] == pytest.approx(50.0, abs=1e-6)
