"""
Granger Causality Testing.

Tests whether one time series helps predict another,
establishing causal direction for I/O relationships.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..interfaces import ObservationHistory

logger = logging.getLogger(__name__)


@dataclass
class GrangerTestResult:
    """Result of a Granger causality test."""
    cause_property: str
    effect_property: str
    entity_id: str
    is_causal: bool
    f_statistic: float
    p_value: float
    optimal_lag: int
    r_squared_full: float
    r_squared_restricted: float
    confidence: float
    sample_size: int


@dataclass
class BidirectionalTestResult:
    """Result of bidirectional Granger test."""
    property_a: str
    property_b: str
    entity_id: str
    a_causes_b: bool
    b_causes_a: bool
    a_to_b_strength: float
    b_to_a_strength: float
    relationship: str  # 'a->b', 'b->a', 'bidirectional', 'none'


def _betacf(a: float, b: float, x: float,
            itmax: int = 300, eps: float = 3e-16) -> float:
    """Continued fraction for the incomplete beta, by the modified Lentz method."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta, I_x(a, b). Standard library only."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                 + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(log_front) * _betacf(a, b, x) / a
    return 1.0 - math.exp(log_front) * _betacf(b, a, 1.0 - x) / b


def f_sf(x: float, df1: int, df2: int) -> float:
    """P(F > x) for an F distribution with ``(df1, df2)`` degrees of freedom.

    THE PREVIOUS VERSION OF THIS WAS NOT THE F DISTRIBUTION. It computed
    ``exp(-x*df1/(2*df2)) * (1 + x*df1/df2) ** (-df2/2)``, which is the exact
    survival function for ``df1 == 2`` multiplied by a factor that vanishes for
    large ``df2`` -- and was applied at every ``df1``. Measured against the true
    distribution at the 5% critical value with ``df2 = 250``: it returned 0.145
    at ``df1 = 1``, 0.049 at ``df1 = 2``, 0.004 at ``df1 = 5`` and 0.0001 at
    ``df1 = 10``. Correct at 2, three times too conservative at 1, and five
    hundred times too liberal at 10.

    What that did to a Granger test is the part worth stating, because a
    p-value that is wrong in a known direction is worse than no p-value: on
    INDEPENDENT series, where a correct test rejects 5% of the time, the
    measured false-positive rate was 0.3% at lag 1, 6% at lag 2 and 25% at
    lag 5. The test was not slightly miscalibrated -- it was a different
    function of the lag.

    This is the real thing, via the identity
    ``P(F > x) = I_{df2/(df2 + df1*x)}(df2/2, df1/2)``, and it agrees with
    ``scipy.stats.f.sf`` to within 3e-13 across a grid of 1,120 points. scipy
    is NOT a dependency of this package; it was used to check, not to compute.
    """
    if x <= 0:
        return 1.0
    return betainc(df2 / 2.0, df1 / 2.0, df2 / (df2 + df1 * x))


class GrangerCausalityTester:
    """
    Test Granger causality between time series.

    Uses vector autoregression (VAR) to test whether
    past values of X help predict Y beyond Y's own past.
    """

    def __init__(
        self,
        history: ObservationHistory,
        max_lag: int = 10,
        significance_level: float = 0.05,
        min_samples: int = 30
    ):
        self.history = history
        self.max_lag = max_lag
        self.significance_level = significance_level
        self.min_samples = min_samples

    def test_causality(
        self,
        entity_id: str,
        cause_property: str,
        effect_property: str,
        time_window: timedelta = timedelta(hours=1)
    ) -> Optional[GrangerTestResult]:
        """
        Test if cause_property Granger-causes effect_property.

        Args:
            entity_id: Entity to analyze
            cause_property: Potential causal property
            effect_property: Potential effect property
            time_window: Time window for analysis

        Returns:
            GrangerTestResult or None if insufficient data
        """
        # Get time series
        cause_series = self.history.get_values(
            entity_id, cause_property, time_window
        )
        effect_series = self.history.get_values(
            entity_id, effect_property, time_window
        )

        if len(cause_series) < self.min_samples or len(effect_series) < self.min_samples:
            return None

        # Align series
        cause_arr, effect_arr = self._align_series(cause_series, effect_series)

        if len(cause_arr) < self.min_samples:
            return None

        # Find optimal lag
        optimal_lag = self._find_optimal_lag(cause_arr, effect_arr)

        # Perform Granger test
        f_stat, p_value, r2_full, r2_restricted = self._granger_test(
            cause_arr, effect_arr, optimal_lag
        )

        is_causal = p_value < self.significance_level
        confidence = 1 - p_value if is_causal else p_value

        return GrangerTestResult(
            cause_property=cause_property,
            effect_property=effect_property,
            entity_id=entity_id,
            is_causal=is_causal,
            f_statistic=f_stat,
            p_value=p_value,
            optimal_lag=optimal_lag,
            r_squared_full=r2_full,
            r_squared_restricted=r2_restricted,
            confidence=confidence,
            sample_size=len(cause_arr)
        )

    def test_bidirectional(
        self,
        entity_id: str,
        property_a: str,
        property_b: str,
        time_window: timedelta = timedelta(hours=1)
    ) -> Optional[BidirectionalTestResult]:
        """
        Test bidirectional Granger causality.

        Args:
            entity_id: Entity to analyze
            property_a: First property
            property_b: Second property
            time_window: Time window for analysis

        Returns:
            BidirectionalTestResult or None if insufficient data
        """
        # Test A -> B
        result_ab = self.test_causality(
            entity_id, property_a, property_b, time_window
        )

        # Test B -> A
        result_ba = self.test_causality(
            entity_id, property_b, property_a, time_window
        )

        if result_ab is None or result_ba is None:
            return None

        a_causes_b = result_ab.is_causal
        b_causes_a = result_ba.is_causal

        # Determine relationship type
        if a_causes_b and b_causes_a:
            relationship = 'bidirectional'
        elif a_causes_b:
            relationship = 'a->b'
        elif b_causes_a:
            relationship = 'b->a'
        else:
            relationship = 'none'

        return BidirectionalTestResult(
            property_a=property_a,
            property_b=property_b,
            entity_id=entity_id,
            a_causes_b=a_causes_b,
            b_causes_a=b_causes_a,
            a_to_b_strength=result_ab.confidence if a_causes_b else 0,
            b_to_a_strength=result_ba.confidence if b_causes_a else 0,
            relationship=relationship
        )

    def _align_series(
        self,
        series1: List[Tuple[datetime, float]],
        series2: List[Tuple[datetime, float]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Align two time series by timestamp."""
        # Convert to dictionaries
        dict1 = {ts: val for ts, val in series1}
        dict2 = {ts: val for ts, val in series2}

        # Find common timestamps
        common = sorted(set(dict1.keys()) & set(dict2.keys()))

        if not common:
            # Try nearest neighbor matching
            return self._align_by_nearest(series1, series2)

        arr1 = np.array([dict1[ts] for ts in common])
        arr2 = np.array([dict2[ts] for ts in common])

        return arr1, arr2

    def _align_by_nearest(
        self,
        series1: List[Tuple[datetime, float]],
        series2: List[Tuple[datetime, float]],
        tolerance_seconds: float = 60
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Align series by nearest timestamp within tolerance."""
        arr1 = []
        arr2 = []

        times2 = sorted([ts for ts, _ in series2])
        dict2 = {ts: val for ts, val in series2}

        for ts1, val1 in sorted(series1):
            # Find nearest in series2
            nearest = min(times2, key=lambda t: abs((t - ts1).total_seconds()))
            if abs((nearest - ts1).total_seconds()) <= tolerance_seconds:
                arr1.append(val1)
                arr2.append(dict2[nearest])

        return np.array(arr1), np.array(arr2)

    def _find_optimal_lag(
        self,
        cause: np.ndarray,
        effect: np.ndarray
    ) -> int:
        """Find optimal lag using AIC criterion."""
        best_aic = float('inf')
        best_lag = 1

        for lag in range(1, min(self.max_lag + 1, len(cause) // 4)):
            aic = self._calculate_aic(cause, effect, lag)
            if aic < best_aic:
                best_aic = aic
                best_lag = lag

        return best_lag

    def _calculate_aic(
        self,
        cause: np.ndarray,
        effect: np.ndarray,
        lag: int
    ) -> float:
        """Calculate Akaike Information Criterion for given lag."""
        n = len(effect) - lag

        if n < 10:
            return float('inf')

        # Build design matrix for full model
        X_full = np.column_stack([
            self._create_lagged(effect, lag),
            self._create_lagged(cause, lag)
        ])
        y = effect[lag:]

        if X_full.shape[0] != len(y):
            return float('inf')

        # Fit full model
        # narrow the bare ``except:`` to the legitimate numerical-
        # failure types (LinAlgError on singular matrix, ValueError on
        # numpy shape mismatch, ZeroDivisionError defensive). Programming
        # errors (AttributeError, KeyError, etc.) now propagate so
        # operators see real bugs instead of silent float('inf')
        # returns. Same structured-classification archetype as
        # /
        # family.
        try:
            coeffs = np.linalg.lstsq(X_full, y, rcond=None)[0]
            residuals = y - X_full @ coeffs
            rss = np.sum(residuals ** 2)
        except (np.linalg.LinAlgError, ValueError, ZeroDivisionError) as e:
            logger.warning(
                "Granger _calculate_aic numerical failure: %s: %s "
                "(returning inf — model fit failed). Likely cause: "
                "singular matrix / collinear input / insufficient data.",
                type(e).__qualname__,
                e,
            )
            return float('inf')

        # Calculate AIC
        k = X_full.shape[1]
        aic = n * np.log(rss / n) + 2 * k

        return aic

    def _create_lagged(
        self,
        series: np.ndarray,
        lag: int
    ) -> np.ndarray:
        """Create lagged matrix for regression."""
        n = len(series) - lag
        lagged = np.zeros((n, lag))

        for i in range(lag):
            lagged[:, i] = series[lag - 1 - i:n + lag - 1 - i]

        return lagged

    def _granger_test(
        self,
        cause: np.ndarray,
        effect: np.ndarray,
        lag: int
    ) -> Tuple[float, float, float, float]:
        """
        Perform Granger causality test.

        Returns:
            (f_statistic, p_value, r2_full, r2_restricted)
        """
        n = len(effect) - lag

        if n < 10:
            return 0.0, 1.0, 0.0, 0.0

        y = effect[lag:]

        # Restricted model: only effect's own lags
        X_restricted = self._create_lagged(effect, lag)

        # Full model: effect's lags + cause's lags
        X_full = np.column_stack([
            X_restricted,
            self._create_lagged(cause, lag)
        ])

        # Fit restricted model. same structured-classification
        # treatment as ``_compute_aic`` — narrow except to numerical
        # failure types; let programming errors propagate.
        try:
            coeffs_r = np.linalg.lstsq(X_restricted, y, rcond=None)[0]
            residuals_r = y - X_restricted @ coeffs_r
            rss_r = np.sum(residuals_r ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r2_r = 1 - rss_r / ss_tot if ss_tot > 0 else 0
        except (np.linalg.LinAlgError, ValueError, ZeroDivisionError) as e:
            logger.warning(
                "Granger _granger_test restricted-model fit failed: "
                "%s: %s (returning neutral statistics; full-model fit "
                "skipped). Likely cause: singular matrix / collinear "
                "input / insufficient data.",
                type(e).__qualname__,
                e,
            )
            return 0.0, 1.0, 0.0, 0.0

        # Fit full model. narrow except; on failure preserve
        # the restricted r2 (pre-fix behavior).
        try:
            coeffs_f = np.linalg.lstsq(X_full, y, rcond=None)[0]
            residuals_f = y - X_full @ coeffs_f
            rss_f = np.sum(residuals_f ** 2)
            r2_f = 1 - rss_f / ss_tot if ss_tot > 0 else 0
        except (np.linalg.LinAlgError, ValueError, ZeroDivisionError) as e:
            logger.warning(
                "Granger _granger_test full-model fit failed: "
                "%s: %s (returning restricted r2=%.3f only). Likely "
                "cause: cause-series collinear with effect's lags.",
                type(e).__qualname__,
                e,
                r2_r,
            )
            return 0.0, 1.0, 0.0, r2_r

        # F-test
        df1 = lag  # Number of restrictions
        df2 = n - 2 * lag  # Degrees of freedom in full model

        if df2 <= 0 or rss_f <= 0:
            return 0.0, 1.0, r2_f, r2_r

        f_stat = ((rss_r - rss_f) / df1) / (rss_f / df2)

        # Calculate p-value using F distribution
        p_value = self._f_distribution_sf(f_stat, df1, df2)

        return f_stat, p_value, r2_f, r2_r

    def _f_distribution_sf(self, x: float, df1: int, df2: int) -> float:
        """Survival function for the F distribution. Delegates to :func:`f_sf`.

        Kept as a method because callers and tests reach it here; the
        mathematics moved to module scope so it can be tested on its own,
        which is what found that the previous one was wrong.
        """
        return f_sf(x, df1, df2)

    def _normal_sf(self, x: float) -> float:
        """Standard normal survival function, via the error function."""
        return 0.5 * math.erfc(x / math.sqrt(2.0))

    def test_multiple_pairs(
        self,
        entity_id: str,
        properties: List[str],
        time_window: timedelta = timedelta(hours=1)
    ) -> List[GrangerTestResult]:
        """
        Test all pairs of properties for Granger causality.

        Args:
            entity_id: Entity to analyze
            properties: List of property names
            time_window: Time window for analysis

        Returns:
            List of significant GrangerTestResults
        """
        results = []

        for i, prop_a in enumerate(properties):
            for prop_b in properties[i + 1:]:
                # Test A -> B
                result_ab = self.test_causality(
                    entity_id, prop_a, prop_b, time_window
                )
                if result_ab and result_ab.is_causal:
                    results.append(result_ab)

                # Test B -> A
                result_ba = self.test_causality(
                    entity_id, prop_b, prop_a, time_window
                )
                if result_ba and result_ba.is_causal:
                    results.append(result_ba)

        return results
