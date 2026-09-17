"""The projectors: what they recover, what they refuse, and what a horizon costs.

A forecast is the first thing this engine produces that is not a reading of
something that already happened, so it is the first that can be confidently
wrong. These tests pin the three properties that make it answerable:

- **it widens.** Uncertainty at two hours must exceed uncertainty at one. A
  forecast whose interval does not grow with the horizon is reporting the
  precision of its last observation as the precision of its prediction.
- **it says where its parameters came from.** A number the author declared and
  a number estimated from the very series being forecast are different claims,
  and only the second can be circular.
- **it refuses.** Every path out of `fit` is a fitted model or a named decline.
  No branch substitutes a plausible parameter and reports the result anyway.

The data below is GENERATED FROM THE MODEL under test, which is normally the
weakest kind of fixture -- it cannot falsify the model. It is used for exactly
one thing it can do honestly: the innovations test has a known expected value
of 1 on correctly specified data, so a filter that mis-scales its own
uncertainty fails it. Every refusal test feeds data the model does NOT describe.
"""

from __future__ import annotations

import math
import random
import statistics
from datetime import datetime, timedelta

import pytest

from arbiter_engine.projection.projector import (
    LocalLevel, NIS_BAND, PROJECTORS, SOURCE_CURVE, SOURCE_DECLARED,
    SOURCE_ESTIMATED, TrendCurve,
)
from arbiter_engine.subenvelope import Decline

T0 = datetime(2026, 5, 1)
SCOPE = {"entity_id": "u1", "property": "level_pct"}


#: `q` is a variance RATE, per second, and `r` is a variance. That is the whole
#: reason the filter multiplies `q` by the gap between two samples: real
#: telemetry arrives irregularly, and a `q` meaning *per sample* would make the
#: same process look different at a different scrape interval. The generator
#: below therefore scales by `step` exactly as the filter does -- an earlier
#: version of it did not, declared the same numbers, and produced innovations
#: sixty times too large.
Q_PER_SECOND = 0.001
R_VARIANCE = 0.09


def _walk(n=80, q=Q_PER_SECOND, r=R_VARIANCE, step=60, seed=5, drift=0.0):
    """A local level process: a wandering level, seen through noise."""
    rng = random.Random(seed)
    level, out = 100.0, []
    for i in range(n):
        level += rng.gauss(drift, math.sqrt(q * step))
        out.append((T0 + timedelta(seconds=step * i), level + rng.gauss(0, math.sqrt(r))))
    return out


def _flat(n=80, step=60, value=100.0):
    return [(T0 + timedelta(seconds=step * i), value) for i in range(n)]


# --- what it recovers -------------------------------------------------------

def test_the_filter_scales_its_own_uncertainty_correctly():
    """ACROSS MANY SERIES, not one.

    The innovations test has an expected value of 1 on data the model
    describes, but a single run is an average of 79 chi-square draws whose
    standard error is 0.16 -- so one series landing at 1.36 says nothing, and a
    threshold loose enough to admit it is loose enough to admit a filter that
    is genuinely 30% wrong. The first version of this test asserted one seed
    and had to choose between those two failures.

    Averaging over 40 series separates them. The standard error of the mean
    below is about 0.025, so the band here would catch a filter mis-scaled by
    10% -- and the SECOND assertion is the stronger one: the spread of the
    per-run means must itself match the theory. A filter can centre correctly
    and still report the wrong width, and only the spread can see that.
    """
    means = [LocalLevel().fit(_walk(seed=s), {"q": Q_PER_SECOND, "r": R_VARIANCE},
                              SCOPE).nis_mean for s in range(40)]
    assert statistics.fmean(means) == pytest.approx(1.0, abs=0.12)
    assert statistics.pstdev(means) == pytest.approx(math.sqrt(2.0 / 79), rel=0.35)


def test_one_series_can_sit_well_away_from_the_expected_value():
    """The reason the test above averages. This seed lands near 1.36 with the
    TRUE parameters declared, which is an ordinary draw and not a defect -- and
    it is inside the band the projector declines on, so it still fits."""
    fitted = LocalLevel().fit(_walk(seed=5), {"q": Q_PER_SECOND, "r": R_VARIANCE},
                              SCOPE)
    low, high = NIS_BAND
    assert low < fitted.nis_mean < high
    assert fitted.nis_mean > 1.2


def test_declared_parameters_are_used_and_labelled():
    fitted = LocalLevel().fit(_walk(), {"q": Q_PER_SECOND, "r": R_VARIANCE}, SCOPE)
    assert fitted.source == SOURCE_DECLARED
    assert (fitted.q, fitted.r) == (Q_PER_SECOND, R_VARIANCE)


def test_estimated_parameters_are_labelled_differently():
    """Rule: a default that decides an answer appears in the evidence. An
    estimate is not a declaration and the forecast says which it had."""
    fitted = LocalLevel().fit(_walk(), {}, SCOPE)
    assert fitted.source == SOURCE_ESTIMATED
    assert fitted.forecast(60).source == SOURCE_ESTIMATED


# --- what a horizon costs ---------------------------------------------------

def test_a_forecast_widens_with_its_horizon():
    fitted = LocalLevel().fit(_walk(), {"q": Q_PER_SECOND, "r": R_VARIANCE}, SCOPE)
    near, far = fitted.forecast(3600), fitted.forecast(7200)
    assert far.sigma > near.sigma


def test_the_width_is_the_observation_and_not_the_hidden_state():
    """The mirror a forecast is graded against is an OBSERVATION, and the
    thresholds a breach probability is computed against are declared on
    observed values. A forecast of the state omits the measurement noise and is
    systematically overconfident about both."""
    fitted = LocalLevel().fit(_walk(), {"q": Q_PER_SECOND, "r": R_VARIANCE}, SCOPE)
    forecast = fitted.forecast(3600)
    state_only = math.sqrt(fitted.variance + fitted.q * 3600)
    assert forecast.sigma > state_only
    assert forecast.sigma == pytest.approx(math.sqrt(state_only ** 2 + fitted.r))


def test_the_quantiles_bracket_the_mean_in_order():
    forecast = LocalLevel().fit(_walk(), {"q": Q_PER_SECOND, "r": R_VARIANCE}, SCOPE).forecast(600)
    q = forecast.quantiles
    assert q["q05"] < q["q50"] < q["q95"]
    assert q["q50"] == pytest.approx(forecast.mean)


def test_the_breach_probabilities_are_complements():
    forecast = LocalLevel().fit(_walk(), {"q": Q_PER_SECOND, "r": R_VARIANCE}, SCOPE).forecast(600)
    assert forecast.p_above(105) == pytest.approx(1 - forecast.p_at_or_below(105))


# --- what it refuses --------------------------------------------------------

def test_a_series_with_no_wander_cannot_separate_the_two_parameters():
    """Pure measurement noise around a fixed level. There is no wander to
    attribute, so `q` cannot be told from zero -- and a clamped estimate would
    report a fitted model for a series that refutes it."""
    rng = random.Random(2)
    series = [(T0 + timedelta(seconds=60 * i), 100.0 + rng.gauss(0, 0.5))
              for i in range(80)]
    declined = LocalLevel().fit(series, {}, SCOPE)
    assert isinstance(declined, Decline)
    assert declined.reason == "unidentifiable_parameter"


def test_a_declared_parameter_at_or_below_zero_is_refused():
    for dynamics in ({"q": 0.0, "r": R_VARIANCE}, {"q": Q_PER_SECOND, "r": -1.0}):
        declined = LocalLevel().fit(_walk(), dynamics, SCOPE)
        assert isinstance(declined, Decline)
        assert declined.reason == "unidentifiable_parameter"


def test_parameters_that_do_not_describe_the_series_are_refused():
    """Declared parameters a thousand times too small: the filter's own
    innovations say so, and the measured value rides in the decline."""
    declined = LocalLevel().fit(_walk(), {"q": 1e-7, "r": 1e-5}, SCOPE)
    assert isinstance(declined, Decline)
    assert declined.reason == "model_inconsistent"
    assert declined.evidence["nis_mean"] > NIS_BAND[1]


def test_the_decline_carries_the_scope_it_was_asked_about():
    declined = LocalLevel().fit(_flat(), {}, SCOPE)
    assert isinstance(declined, Decline)
    assert declined.scope == SCOPE


# --- the demoted curve ------------------------------------------------------

def test_the_trend_projector_is_reachable_by_name():
    # `random_walk` joined as the REFERENCE every forecaster is measured
    # against. It is in the same registry because an author may declare it --
    # a model that cannot be beaten by a random walk should be able to say so
    # -- and the registry is what the did-you-mean list is derived from.
    assert set(PROJECTORS) == {"local_level", "random_walk", "trend"}
    assert PROJECTORS["trend"].name == TrendCurve.name


def test_a_curve_fit_says_it_is_one():
    fitted = TrendCurve().fit(_walk(drift=0.2), {}, SCOPE)
    assert fitted.source == SOURCE_CURVE
    assert fitted.forecast(600).source == SOURCE_CURVE


def test_an_exact_fit_reports_no_uncertainty_and_is_refused():
    """A straight line through points that lie on it has zero residual spread,
    so every breach probability it could produce is 0 or 1 -- a certainty this
    engine has no basis for."""
    series = [(T0 + timedelta(seconds=60 * i), 100.0 + i) for i in range(20)]
    declined = TrendCurve().fit(series, {}, SCOPE)
    assert isinstance(declined, Decline)
    assert declined.reason == "covariance_unbounded"


def test_q_is_a_rate_so_a_wider_gap_costs_more():
    """Two samples an hour apart carry more drift than two a minute apart. A
    `q` read as per-sample would make the same process look identical at both
    scrape intervals, and every interval it produced would be wrong at one."""
    fitted = LocalLevel().fit(_walk(), {"q": Q_PER_SECOND, "r": R_VARIANCE}, SCOPE)
    minute, hour = fitted.forecast(60), fitted.forecast(3600)
    assert (hour.sigma ** 2 - minute.sigma ** 2) == pytest.approx(
        Q_PER_SECOND * (3600 - 60))
