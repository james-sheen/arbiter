"""The statistics discovery rests on: the F distribution, the multiplicity
correction, and the gate that decides a series is testable at all.

EVERY ONE OF THESE WAS WRONG BEFORE IT WAS MEASURED, and none of the three
failures was visible by reading:

- the F survival function was the exact formula for ``df1 == 2`` applied at
  every ``df1``. It returned 0.145 where 0.05 was correct at one degree of
  freedom and 0.0001 at ten;
- taking the smallest p across a family of lags and reporting it as if one test
  had been run rejected independent series 14% of the time;
- the trend arm of the stationarity gate used an ordinary standard error on
  autocorrelated residuals and refused HALF of all strongly autocorrelated
  series for having a trend they did not have.

So the assertions here are CALIBRATION assertions, not smoke tests. They ask
whether a number that claims to be a 5% false-positive rate is one, which is
the only property that makes a discovery pass worth running: a proposal is
only as good as the rate of spurious proposals beside it.

The reference values are `scipy.stats.f.sf`. scipy is NOT a dependency of this
package -- it was used to produce the constants below, which are then checked
against an implementation that uses the standard library alone.
"""

from __future__ import annotations

import math
import random
import statistics

import numpy as np
import pytest

from arbiter_engine.causal.granger import (
    GrangerCausalityTester, betainc, f_sf,
)
from arbiter_engine.causal.leadlag import (
    TREND_T_LIMIT, VARIANCE_RATIO_BAND, lead_lag, stationary,
)

#: (df1, df2, x, P(F > x)) from scipy.stats.f.sf.
REFERENCE = [
    (1, 50, 3.5, 0.067226875993),
    (1, 250, 3.879, 0.049997770552),
    (2, 100, 2.0, 0.140712615333),
    (2, 250, 3.032, 0.049996017758),
    (5, 100, 2.305, 0.050027982744),
    (5, 250, 2.25, 0.050012491582),
    (10, 250, 1.869, 0.049956228247),
    (10, 1000, 1.6, 0.101458965870),
    (20, 30, 2.0, 0.041760112265),
    (3, 17, 4.0, 0.025230226435),
]

LAGS = (1, 2, 5, 10)


def _ar1(seed, n=400, phi=0.5, trend=0.0, sigma=1.0):
    rng = random.Random(seed)
    out, level = [], 0.0
    for i in range(n):
        level = phi * level + rng.gauss(0, sigma)
        out.append(level + trend * i)
    return out


def _independent_pair(seed, n=300):
    rng = random.Random(seed)
    x = [0.0] * n
    y = [0.0] * n
    for i in range(1, n):
        x[i] = 0.5 * x[i - 1] + rng.gauss(0, 1)
        y[i] = 0.4 * y[i - 1] + rng.gauss(0, 1)
    return np.array(x), np.array(y)


def _coupled_pair(seed, n=300, strength=0.9, lag=2):
    rng = random.Random(seed)
    x = [0.0] * n
    y = [0.0] * n
    for i in range(1, n):
        x[i] = 0.5 * x[i - 1] + rng.gauss(0, 1)
        driven = strength * x[i - lag] if i >= lag else 0.0
        y[i] = 0.4 * y[i - 1] + driven + rng.gauss(0, 1)
    return np.array(x), np.array(y)


# --- the F distribution -----------------------------------------------------

@pytest.mark.parametrize("df1,df2,x,expected", REFERENCE)
def test_the_survival_function_is_the_f_distribution(df1, df2, x, expected):
    assert f_sf(x, df1, df2) == pytest.approx(expected, abs=1e-10)


def test_the_shape_that_was_wrong_before_is_right_now():
    """The single most diagnostic case. The replaced formula was exact at
    ``df1 == 2`` and wrong everywhere else, so a check that happened to use two
    degrees of freedom would have passed against it."""
    for df1, expected_at_five_percent in ((1, 3.879), (2, 3.032),
                                          (5, 2.250), (10, 1.869)):
        assert f_sf(expected_at_five_percent, df1, 250) == pytest.approx(0.05, abs=2e-4)


def test_the_survival_function_is_monotone_and_bounded():
    previous = 1.0
    for x in (0.1, 0.5, 1.0, 2.0, 5.0, 20.0, 100.0):
        p = f_sf(x, 5, 100)
        assert 0.0 <= p <= 1.0
        assert p < previous
        previous = p
    assert f_sf(0.0, 5, 100) == 1.0


def test_the_incomplete_beta_satisfies_its_own_symmetry():
    """I_x(a,b) = 1 - I_{1-x}(b,a). Independent of the reference values above,
    so it still holds if every one of them were transcribed wrongly."""
    for a, b, x in ((2.0, 3.0, 0.3), (0.5, 7.5, 0.8), (12.5, 1.0, 0.05)):
        assert betainc(a, b, x) == pytest.approx(1.0 - betainc(b, a, 1.0 - x), abs=1e-12)


def test_the_normal_survival_function_is_the_real_one():
    tester = GrangerCausalityTester(history=None)
    for x, expected in ((0.0, 0.5), (1.0, 0.158655253931),
                        (1.959963985, 0.025), (-1.0, 0.841344746069)):
        assert tester._normal_sf(x) == pytest.approx(expected, abs=1e-9)


# --- calibration ------------------------------------------------------------

def test_the_corrected_test_rejects_independent_series_at_about_its_level():
    """THE ASSERTION THE WHOLE DISCIPLINE RESTS ON. On series with no relation,
    a test claiming 5% must reject near 5%. Measured before the two fixes: 14%."""
    rejects = sum(1 for s in range(300)
                  if lead_lag(*_independent_pair(7000 + s), LAGS)["p_corrected"] < 0.05)
    rate = rejects / 300
    assert 0.02 <= rate <= 0.09, f"false-positive rate {rate:.3f} against a nominal 0.05"


def test_the_uncorrected_minimum_would_reject_far_more():
    """The discriminator. Without it the test above could pass because the
    whole thing is inert rather than because the correction works."""
    raw = sum(1 for s in range(300)
              if lead_lag(*_independent_pair(7000 + s), LAGS)["p_raw"] < 0.05)
    corrected = sum(1 for s in range(300)
                    if lead_lag(*_independent_pair(7000 + s), LAGS)["p_corrected"] < 0.05)
    assert raw > corrected * 1.5, (raw, corrected)


def test_the_correction_never_makes_a_result_look_stronger():
    for s in range(20):
        result = lead_lag(*_independent_pair(9000 + s), LAGS)
        assert result["p_corrected"] >= result["p_raw"]


def test_one_lag_needs_no_correction():
    result = lead_lag(*_independent_pair(9100), (3,))
    assert result["p_corrected"] == pytest.approx(result["p_raw"])


def test_a_real_lead_is_found_at_the_lag_it_was_planted_at():
    result = lead_lag(*_coupled_pair(11), LAGS)
    assert result["lag"] == 2
    assert result["p_corrected"] < 1e-10


def test_the_reverse_direction_is_not_significant():
    """Power without orientation is useless: a test that fires both ways on a
    one-way relation cannot tell a cause from an effect."""
    x, y = _coupled_pair(11)
    assert lead_lag(y, x, LAGS)["p_corrected"] > 0.05


def test_every_lag_tested_is_reported():
    result = lead_lag(*_coupled_pair(12), LAGS)
    assert result["lags_tested"] == sorted(LAGS)
    assert set(result["per_lag"]) == set(LAGS)


# --- the stationarity gate --------------------------------------------------

def test_a_plain_autocorrelated_series_is_testable():
    """It was not, before the trend arm was corrected. Half of all AR(0.8)
    series were refused for a trend that was an artefact of the standard
    error, and a refused pair is a pair nobody looks at again."""
    for phi in (0.0, 0.3, 0.5, 0.8):
        rejected = sum(1 for s in range(120)
                       if not stationary(_ar1(1000 + s, phi=phi))[0])
        assert rejected / 120 <= 0.15, f"phi={phi} rejected {rejected/120:.3f}"


def test_a_real_trend_is_still_caught_at_every_autocorrelation():
    """The other half. A correction that restored the false-rejection rate by
    blinding the arm would pass the test above and be worthless."""
    for phi in (0.0, 0.5, 0.8):
        caught = sum(1 for s in range(40)
                     if not stationary(_ar1(5000 + s, phi=phi, trend=0.05))[0])
        assert caught == 40, f"phi={phi} caught only {caught}/40"


def test_a_widening_spread_is_caught():
    rng = random.Random(3)
    series = [rng.gauss(0, 1.0 + 3.0 * i / 400) for i in range(400)]
    ok, evidence = stationary(series)
    assert not ok
    assert evidence["variance_ratio"] > VARIANCE_RATIO_BAND[1]


def test_the_gate_reports_what_it_measured():
    """A decline an author cannot check is one they can only take on faith."""
    _, evidence = stationary(_ar1(7))
    assert set(evidence) >= {"n", "variance_ratio", "variance_band", "trend_t",
                             "trend_t_limit", "residual_autocorrelation"}
    assert evidence["trend_t_limit"] == TREND_T_LIMIT


def test_a_series_too_short_to_split_is_not_called_stationary():
    ok, evidence = stationary([1.0, 2.0, 3.0])
    assert not ok
    assert evidence["n"] == 3
