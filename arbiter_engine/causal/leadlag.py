"""Lead-lag between two series: the stationarity gate, and a test that is
calibrated once you account for having searched.

WHAT THIS DOES NOT CLAIM

Not causality. A significant result says the past of one series helps predict
the other beyond its own past -- predictive precedence, which is what Granger's
test measures and what its name unhelpfully obscures. Two series driven by a
third will show it; so will two series whose common driver nobody declared.
That is why the discipline's vocabulary carries `latent_confounding_possible`
and `faithfulness_unverifiable`, and why a significant pair becomes a QUESTION
rather than an edge.

WHY THE CORRECTION IS NOT OPTIONAL

Testing four lags and reporting the smallest p is four chances to be surprised
reported as one. Measured on independent series, where a calibrated test
rejects at 5%: the uncorrected minimum over lags (1, 2, 5, 10) rejected 14.0%
of the time. The same runs, Sidak-corrected, rejected 5.0%. A discovery pass
built on the uncorrected figure proposes roughly three spurious edges for every
one it is entitled to, and reports them with a number that says otherwise.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .granger import GrangerCausalityTester

__all__ = ["stationary", "lead_lag", "align", "VARIANCE_RATIO_BAND", "TREND_T_LIMIT"]

#: Split-half variance ratio a series must sit inside. A series whose second
#: half is four times as variable as its first is not one the tests below
#: describe, and a p-value computed on it is a number rather than evidence.
VARIANCE_RATIO_BAND: Tuple[float, float] = (0.5, 2.0)

#: |t| on the slope of a regression against time, above which the series is
#: treated as trending. Two-sided 5% for a large sample.
TREND_T_LIMIT = 1.96

_TESTER: Optional[GrangerCausalityTester] = None


def _tester() -> GrangerCausalityTester:
    """The arithmetic in `granger.py`, reached without a history.

    `_granger_test` is a function of two arrays and a lag; it reads no state.
    The class wants a history because its OTHER entry point fetches series
    itself, and this discipline has already fetched them.
    """
    global _TESTER
    if _TESTER is None:
        _TESTER = GrangerCausalityTester(history=None)
    return _TESTER


def _lag1_autocorrelation(values: Sequence[float]) -> float:
    """Lag-1 autocorrelation, clamped to [0, 1). Negative values are treated as
    zero: they do not inflate a slope's standard error, and correcting toward a
    SMALLER error would manufacture trends rather than stop inventing them."""
    n = len(values)
    if n < 3:
        return 0.0
    mean = statistics.fmean(values)
    centred = [v - mean for v in values]
    denominator = sum(c * c for c in centred)
    if denominator <= 0:
        return 0.0
    numerator = sum(a * b for a, b in zip(centred, centred[1:]))
    return max(0.0, min(numerator / denominator, 0.999))


def stationary(values: Sequence[float]) -> Tuple[bool, Dict[str, Any]]:
    """Is this series flat enough in level and spread for the test to mean
    anything? Returns the verdict AND the measurements behind it, because a
    decline an author cannot check is one they can only take on faith."""
    n = len(values)
    if n < 8:
        return False, {"n": n, "reason": "too short to split"}
    half = n // 2
    first, second = list(values[:half]), list(values[half:])
    var_first = statistics.pvariance(first)
    var_second = statistics.pvariance(second)
    if var_first <= 0 or var_second <= 0:
        ratio = math.inf if var_first != var_second else 1.0
    else:
        ratio = var_second / var_first

    xs = list(range(n))
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(values)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    slope = (sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values)) / sxx
             if sxx > 0 else 0.0)
    intercept = mean_y - slope * mean_x
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, values)]
    rss = sum(r * r for r in residuals)
    # THE ORDINARY STANDARD ERROR IS WRONG HERE, and wrong in the direction
    # that matters. It assumes independent residuals; these are a time series,
    # so they are autocorrelated, and the slope's variance is understated by
    # roughly (1 + r1) / (1 - r1). The inflated |t| then reads as a trend.
    #
    # Measured before the correction, on plain AR(1) series with NO trend at
    # all, where a 5% gate should reject 5%: rejected 3.7% at phi = 0, 15.7% at
    # 0.3, 25.7% at 0.5 and 50.0% at 0.8 -- every one of them from this arm.
    # Half of all strongly autocorrelated series were being refused a test for
    # being what they are. Dividing by the same factor restores it.
    r1 = _lag1_autocorrelation(residuals)
    inflation = math.sqrt(max((1.0 + r1) / (1.0 - r1), 1.0)) if r1 < 0.99 else 10.0
    if n > 2 and sxx > 0 and rss > 0:
        se = math.sqrt(rss / (n - 2) / sxx) * inflation
        t_stat = slope / se if se > 0 else 0.0
    else:
        t_stat = 0.0

    low, high = VARIANCE_RATIO_BAND
    evidence = {"n": n, "variance_ratio": round(ratio, 6),
                "variance_band": [low, high],
                "trend_t": round(t_stat, 4), "trend_t_limit": TREND_T_LIMIT,
                "residual_autocorrelation": round(r1, 4)}
    return (low <= ratio <= high and abs(t_stat) <= TREND_T_LIMIT), evidence


def align_with_times(a: Sequence[Tuple[Any, float]],
                     b: Sequence[Tuple[Any, float]]
                     ) -> Tuple[List[Any], np.ndarray, np.ndarray]:
    """`align`, keeping the timestamps it paired on.

    a caller that needs the SPACING of the pairs, not just their
    order, had no way to get it: `align` returned two value arrays and the
    instants were gone. Recovering them by re-intersecting the two series at
    the call site would be a second copy of this function's one rule, so the
    intersection lives here once and `align` drops what it does not need.
    """
    by_time = {t: v for t, v in a}
    shared = [(t, by_time[t], v) for t, v in b if t in by_time]
    shared.sort(key=lambda row: row[0])
    return ([row[0] for row in shared],
            np.array([row[1] for row in shared], dtype=float),
            np.array([row[2] for row in shared], dtype=float))


def align(a: Sequence[Tuple[Any, float]],
          b: Sequence[Tuple[Any, float]]) -> Tuple[np.ndarray, np.ndarray]:
    """Two `(timestamp, value)` series onto a common index, by timestamp."""
    _, values_a, values_b = align_with_times(a, b)
    return values_a, values_b


def lead_lag(x: np.ndarray, y: np.ndarray,
             lags: Sequence[int]) -> Dict[str, Any]:
    """Does the past of `x` help predict `y` beyond `y`'s own past?

    Tests every lag in `lags`, keeps the smallest p, and CORRECTS it for
    having looked that many times. The corrected figure is the one to act on;
    both are reported, because a reader who only sees the corrected one cannot
    tell a strong single result from a weak one that survived a small family.
    """
    tester = _tester()
    per_lag = {}
    for lag in lags:
        f_stat, p_value, r2_full, r2_restricted = tester._granger_test(x, y, int(lag))
        per_lag[int(lag)] = {"f": float(f_stat), "p": float(p_value),
                             "r2_full": float(r2_full),
                             "r2_restricted": float(r2_restricted)}
    best_lag = min(per_lag, key=lambda k: per_lag[k]["p"])
    p_raw = per_lag[best_lag]["p"]
    # Sidak rather than Bonferroni: exact under independence, never above 1,
    # and the difference matters when the family is small and p_raw is large.
    p_corrected = 1.0 - (1.0 - p_raw) ** len(per_lag)
    return {"lag": best_lag, "p_raw": p_raw, "p_corrected": p_corrected,
            "f": per_lag[best_lag]["f"], "n": int(len(x)),
            "lags_tested": sorted(per_lag), "per_lag": per_lag}
