"""The yardstick: what a random walk would have said about exactly this.

*DOES IT BEAT A RANDOM WALK* is the first question asked of any forecaster, and
a calibration table without the answer invites the reading that a
well-calibrated model is a useful one. It is not: a forecaster can be
beautifully calibrated and carry no information at all, which is precisely what
a random walk is.

NOT `local_level`, which is also a random walk plus noise. That one estimates
its parameters and declines when they do not separate -- it is a MODEL, and a
model is what is being judged. A yardstick that could be tuned would let a poor
comparison be explained away by tuning it, so this one has nothing to tune.

THE SAME SERIES AND THE SAME HORIZON, filed in the same loop. A baseline scored
over a different population answers nothing; two numbers that happen to sit in
one table are not a comparison.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession
from arbiter_engine.clock import as_of
from arbiter_engine.projection.projector import (
    BASELINE_MODEL_ID, MINIMUM_SAMPLES, PROJECTORS, RandomWalk,
    SOURCE_BASELINE, Decline)

T0 = datetime(2026, 9, 17, 9, 0)


def _series(values, step=60):
    return [(T0 + timedelta(seconds=i * step), float(v))
            for i, v in enumerate(values)]


def _fit(values, step=60):
    return RandomWalk().fit(_series(values, step), {}, {"entity": "e"})


# --- the yardstick itself ----------------------------------------------------

def test_the_forecast_is_the_last_reading():
    """A random walk says tomorrow is today. Not the mean -- a mean is a model
    of a level, which is a claim this makes no part of."""
    fitted = _fit([10.0, 12.0, 11.0, 13.0, 17.0])
    assert fitted.forecast(60.0).mean == 17.0


def test_the_spread_is_how_much_the_series_moves():
    deltas = [2.0, -1.0, 2.0, 4.0]
    fitted = _fit([10.0, 12.0, 11.0, 13.0, 17.0])
    expected_q = statistics.pvariance(deltas) / 60.0
    assert fitted.q == pytest.approx(expected_q)


def test_a_still_series_forecasts_itself_with_no_spread():
    fitted = _fit([7.0] * 8)
    forecast = fitted.forecast(60.0)
    assert forecast.mean == 7.0
    assert forecast.sigma < 1e-100


def test_the_spread_grows_with_the_square_root_of_the_horizon():
    """What a random walk does, and the reason this is a fair reference rather
    than a generous one."""
    fitted = _fit([10.0, 12.0, 11.0, 13.0, 17.0])
    one, four = fitted.forecast(60.0).sigma, fitted.forecast(240.0).sigma
    assert four == pytest.approx(one * 2.0, rel=1e-9)


def test_the_step_is_measured_per_second_not_per_sample():
    """Storing a per-step variance would silently assume the horizon is
    expressed in whatever steps the series happened to arrive at -- so a series
    sampled every ten seconds and one sampled every hour would be handed the
    same spread for a one-hour forecast."""
    fast = _fit([0.0, 1.0, 0.0, 1.0, 0.0], step=10)
    slow = _fit([0.0, 1.0, 0.0, 1.0, 0.0], step=600)
    assert fast.forecast(3600.0).sigma > slow.forecast(3600.0).sigma


def test_it_has_nothing_to_tune():
    """The whole difference from `local_level`. Declared parameters are ignored
    because a yardstick a caller can set is a yardstick a poor comparison can
    be explained away with."""
    plain = _fit([10.0, 12.0, 11.0, 13.0, 17.0])
    tuned = RandomWalk().fit(_series([10.0, 12.0, 11.0, 13.0, 17.0]),
                             {"q": 999.0, "r": 999.0}, {"entity": "e"})
    assert tuned.q == plain.q
    assert tuned.r == plain.r == 0.0


def test_it_says_the_numbers_came_from_the_yardstick():
    """So a reader of a record can tell a reference from a real forecast
    without matching on a model name."""
    assert _fit([10.0, 12.0, 11.0, 13.0, 17.0]).source == SOURCE_BASELINE


# --- where it refuses --------------------------------------------------------

def test_it_declines_on_the_same_floor_the_models_use():
    """A lower floor would answer where the models cannot, putting a baseline
    score beside no model score and inviting a comparison between a figure and
    an absence."""
    short = _fit([1.0] * (MINIMUM_SAMPLES - 1))
    assert isinstance(short, Decline)
    assert short.reason == "insufficient_samples"
    assert not isinstance(_fit([1.0] * MINIMUM_SAMPLES), Decline)


def test_readings_with_no_time_between_them_decline_rather_than_divide():
    stacked = [(T0, 1.0), (T0, 2.0), (T0, 3.0), (T0, 4.0), (T0, 5.0)]
    outcome = RandomWalk().fit(stacked, {}, {"entity": "e"})
    assert isinstance(outcome, Decline)
    assert outcome.reason == "undefined_for_values"


def test_it_is_in_the_registry_an_author_can_be_told_about():
    assert PROJECTORS[RandomWalk.name] is not None
    assert RandomWalk.name == "random_walk"


# --- filed beside the forecast it judges -------------------------------------

def _projecting_session(model="local_level"):
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Acct"],
        "indicators": {"Acct": [
            {"name": "balance", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
             "window": "2h", "critical": 1e9, "horizon": "1h",
             "dynamics": {"model": model}}]}}})
    session.add_entity("acct_7", "Acct", {"balance": 100.0})
    for index in range(40):
        session.history.add("acct_7", "balance", 100.0 + (index % 5),
                            timestamp=T0 + timedelta(minutes=index))
    return session


#: The instant every projection in this file is taken at. NAMED ONCE, because
#: a recomputation that reads the history at a DIFFERENT instant is comparing
#: two fits of two different series and says so only by the numbers.
PROJECTED_AT = T0 + timedelta(minutes=41)


def _project(session):
    from arbiter_engine.api import project
    with as_of(PROJECTED_AT):
        return project(session)


def test_a_reference_is_filed_beside_every_forecast():
    session = _projecting_session()
    _project(session)
    ids = [r.model_id for r in session.ledger.records()]
    assert BASELINE_MODEL_ID in ids
    assert any(i != BASELINE_MODEL_ID for i in ids)


def test_the_reference_is_filed_on_the_same_horizon():
    """A baseline at a different horizon is a different question, and the
    comparison would quietly be between two of them.

    ASSERTED ON THE NUMBERS, not on `horizon_s`. Reading the stored field
    cannot see the failure that matters: a reference whose QUANTILES were
    computed for one horizon and filed under another keeps a correct
    `horizon_s` and a spread belonging to a different question. So the
    reference is recomputed here at the horizon it was filed under, and the
    filed quantiles have to match it.
    """
    session = _projecting_session()
    _project(session)
    records = {r.model_id: r for r in session.ledger.records()}
    reference = records[BASELINE_MODEL_ID]
    # INSIDE THE SAME FROZEN INSTANT, and this line is why the constant exists.
    # A lookback window is measured from NOW, so reading the history on the wall
    # clock fits a series the projection never saw -- and only once enough real
    # time has passed for the window to start dropping samples. This assertion
    # passed for the two hours after its own fixture time and then began
    # failing, on a tree nobody had touched: 41 samples frozen against 33 live.
    # A test whose verdict depends on the hour it is run is not a check.
    with as_of(PROJECTED_AT):
        series = session.history.get_values("acct_7", "balance", timedelta(hours=2))
        expected = RandomWalk().fit(series, {}, {}).forecast(
            reference.horizon_s).quantiles
    assert reference.quantiles == pytest.approx(expected)
    assert reference.horizon_s == records[
        [k for k in records if k != BASELINE_MODEL_ID][0]].horizon_s


def test_the_reference_carries_the_entity_type_too():
    """Otherwise the baseline sits outside the stratum it is meant to be
    compared within."""
    session = _projecting_session()
    _project(session)
    for record in session.ledger.records():
        assert record.entity_type == "Acct"


def test_the_reference_is_not_filed_against_itself():
    """Declaring the yardstick as the model would otherwise file one forecast
    twice under two ids and let it beat itself."""
    session = _projecting_session(model="random_walk")
    _project(session)
    ids = [r.model_id for r in session.ledger.records()]
    assert BASELINE_MODEL_ID not in ids
    assert len(ids) == 1


def test_the_reference_files_under_its_reserved_id():
    """Checked rather than conventional: a producer naming their own model this
    would land in the baseline's column and be compared against itself."""
    assert BASELINE_MODEL_ID == "baseline_rw"
    assert BASELINE_MODEL_ID not in PROJECTORS


def test_the_decline_arm_is_defence_and_not_a_live_path():
    """NO TEST CLAIMS TO EXERCISE IT, and that is the honest report.

    `run_projection` guards the reference against returning a `Decline`. That
    arm cannot be reached through the verb: the reference's preconditions are
    strictly weaker than every model's -- it needs samples above the floor the
    runner already enforces, and a positive mean step, which every model also
    needs. Measured: a series with all readings at one instant declines for
    the reference AND for `local_level` with declared parameters, so the
    runner never gets past the model to the reference at all.

    The guard stays, because a future projector with weaker preconditions
    would reach it and `Decline.forecast` does not exist. What does not stay
    is a test pretending to cover it: the version here asserted a count that
    was true either way, and a mutation deleting the guard passed it.
    """
    from arbiter_engine.projection import runner
    import inspect
    assert "if not isinstance(reference, Decline):" in inspect.getsource(runner)
    stacked = [(T0, 100.0 + n) for n in range(MINIMUM_SAMPLES + 3)]
    assert isinstance(RandomWalk().fit(stacked, {}, {"entity": "e"}), Decline)
    assert isinstance(
        PROJECTORS["local_level"].fit(stacked, {"q": 1.0, "r": 1.0},
                                      {"entity": "e"}), Decline)
