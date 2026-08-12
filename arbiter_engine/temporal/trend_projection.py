"""
Trend Projection — Phase 2.1.2.

Multi-model trend projection extending BOUNDEDNESS with:
- Linear: y(t) = slope × t + intercept
- Exponential: y(t) = a × e^(bt) + c (capacity exhaustion curves)
- Seasonal: y(t) = trend(t) + seasonal(t, period) + residual(t)
- Plateau: y(t) = L / (1 + e^(-k(t-t0))) (logistic saturation)

Auto-selects best model by R² / AIC.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class TrendModel(Enum):
    """Available trend projection models."""
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    SEASONAL = "seasonal"
    PLATEAU = "plateau"


@dataclass
class TrendResult:
    """Result of trend projection."""
    model: TrendModel
    predicted_value: float
    confidence_lower: float
    confidence_upper: float
    r_squared: float
    time_to_threshold: Optional[float] = None  # seconds until threshold
    parameters: Dict[str, float] = field(default_factory=dict)
    residual_std: float = 0.0

    @property
    def confidence_interval(self) -> float:
        return self.confidence_upper - self.confidence_lower


@dataclass
class SeasonalComponents:
    """Decomposed seasonal components."""
    trend: np.ndarray
    seasonal: np.ndarray
    residual: np.ndarray
    period: int


class TrendProjection:
    """Project entity state forward in time using observed trends.

    Given observation history and a projection horizon, predicts future
    values using the best-fit model among linear, exponential, seasonal,
    and plateau (logistic).
    """

    def __init__(
        self,
        min_observations: int = 5,
        min_r2: float = 0.5,
        seasonal_periods: Optional[List[int]] = None,
    ):
        self.min_observations = min_observations
        self.min_r2 = min_r2
        self.seasonal_periods = seasonal_periods or [24, 168]  # hours

    def project(
        self,
        values: List[Tuple[datetime, float]],
        horizon_seconds: float,
        threshold: Optional[float] = None,
    ) -> Optional[TrendResult]:
        """Project entity state forward using the best-fit model.

        Args:
            values: Historical (timestamp, value) pairs
            horizon_seconds: How far forward to predict
            threshold: Optional threshold to compute time-to-threshold

        Returns:
            TrendResult with prediction and confidence interval, or None
        """
        if len(values) < self.min_observations:
            return None

        base_time = values[0][0]
        t = np.array([(v[0] - base_time).total_seconds() for v in values])
        y = np.array([v[1] for v in values])

        # Fit all models and pick best
        results = []

        linear = self._fit_linear(t, y, horizon_seconds, threshold)
        if linear:
            results.append(linear)

        exponential = self._fit_exponential(t, y, horizon_seconds, threshold)
        if exponential:
            results.append(exponential)

        plateau = self._fit_plateau(t, y, horizon_seconds, threshold)
        if plateau:
            results.append(plateau)

        # Seasonal requires more data
        if len(values) >= 20:
            seasonal = self._fit_seasonal(t, y, horizon_seconds, threshold)
            if seasonal:
                results.append(seasonal)

        if not results:
            return None

        # Pick model with best R², with deterministic tiebreaker
        # on equal r_squared. previously ``max(results, key=lambda r:
        # r.r_squared)`` returned the FIRST result with the max score
        # (list-order dependent: linear inserted first, then
        # exponential, plateau, seasonal). Operators saw equal-fit
        # picks vary by which models the projector evaluated, with no
        # signal that ties existed. Same tied-result-no-tiebreaker
        # archetype as — surface the tie via
        # tuple key.
        # Tiebreak order:
        # 1. r_squared (primary — best fit).
        # 2. -confidence_interval (tighter forecast = better; negate
        # so max() picks the smaller interval).
        # 3. r.model.value (alphabetical for full determinism on
        # all-tied).
        best_r2 = max(r.r_squared for r in results)
        tied = [r for r in results if r.r_squared == best_r2]
        if len(tied) > 1:
            logger.warning(
                "TrendProjector: %d models tied at r_squared=%.4f "
                "(%s) — picking by smallest confidence_interval then "
                "model-name alphabetical. Operator: if this ties "
                "repeatedly, the data may not discriminate between "
                "model families.",
                len(tied),
                best_r2,
                [r.model.value for r in tied],
            )
        best = max(
            results,
            key=lambda r: (r.r_squared, -r.confidence_interval, r.model.value),
        )
        if best.r_squared < self.min_r2:
            # Still return but with low confidence.
            best = results[0]  # fall back to linear

        return best

    def project_multiple(
        self,
        values: List[Tuple[datetime, float]],
        horizons_seconds: List[float],
        threshold: Optional[float] = None,
    ) -> List[Optional[TrendResult]]:
        """Project at multiple horizons using the same best-fit model."""
        return [self.project(values, h, threshold) for h in horizons_seconds]

    def _fit_linear(
        self,
        t: np.ndarray,
        y: np.ndarray,
        horizon_s: float,
        threshold: Optional[float],
    ) -> Optional[TrendResult]:
        """Linear: y = slope *t + intercept."""
        if len(t) < 2:
            return None

        t_mean = np.mean(t)
        y_mean = np.mean(y)
        denom = np.sum((t - t_mean) ** 2)
        if denom == 0:
            return None

        slope = np.sum((t - t_mean) * (y - y_mean)) / denom
        intercept = y_mean - slope * t_mean

        y_pred = slope * t + intercept
        r2 = self._r_squared(y, y_pred)
        residual_std = np.std(y - y_pred)

        t_future = t[-1] + horizon_s
        predicted = slope * t_future + intercept

        time_to_threshold = None
        if threshold is not None and slope != 0:
            t_thresh = (threshold - intercept) / slope
            remaining = t_thresh - t[-1]
            if remaining > 0:
                time_to_threshold = remaining

        return TrendResult(
            model=TrendModel.LINEAR,
            predicted_value=predicted,
            confidence_lower=predicted - 2 * residual_std,
            confidence_upper=predicted + 2 * residual_std,
            r_squared=r2,
            time_to_threshold=time_to_threshold,
            parameters={'slope': float(slope), 'intercept': float(intercept)},
            residual_std=float(residual_std),
        )

    def _fit_exponential(
        self,
        t: np.ndarray,
        y: np.ndarray,
        horizon_s: float,
        threshold: Optional[float],
    ) -> Optional[TrendResult]:
        """Exponential: y = a *exp(b *t) + c."""
        if len(t) < 3:
            return None

        # Shift to avoid log(0): use y - min(y) + 1
        y_min = np.min(y)
        y_shifted = y - y_min + 1.0

        if np.any(y_shifted <= 0):
            return None

        try:
            log_y = np.log(y_shifted)
            # Linear fit on log(y) to get initial b estimate
            t_mean = np.mean(t)
            log_mean = np.mean(log_y)
            denom = np.sum((t - t_mean) ** 2)
            if denom == 0:
                return None

            b = np.sum((t - t_mean) * (log_y - log_mean)) / denom
            log_a = log_mean - b * t_mean
            a = math.exp(log_a)
            c = y_min - 1.0

            y_pred = a * np.exp(b * t) + c
            r2 = self._r_squared(y, y_pred)
            residual_std = np.std(y - y_pred)

            # Safeguard: don't predict explosive growth (overflow)
            t_future = t[-1] + horizon_s
            exponent = b * t_future
            if abs(exponent) > 50:
                return None

            predicted = a * math.exp(exponent) + c

            time_to_threshold = None
            if threshold is not None and b != 0 and a > 0:
                target = threshold - c
                if target > 0 and a > 0:
                    t_thresh = math.log(target / a) / b
                    remaining = t_thresh - t[-1]
                    if remaining > 0:
                        time_to_threshold = remaining

            return TrendResult(
                model=TrendModel.EXPONENTIAL,
                predicted_value=predicted,
                confidence_lower=predicted - 2 * residual_std,
                confidence_upper=predicted + 2 * residual_std,
                r_squared=r2,
                time_to_threshold=time_to_threshold,
                parameters={'a': float(a), 'b': float(b), 'c': float(c)},
                residual_std=float(residual_std),
            )
        except (ValueError, OverflowError, FloatingPointError):
            return None

    def _fit_plateau(
        self,
        t: np.ndarray,
        y: np.ndarray,
        horizon_s: float,
        threshold: Optional[float],
    ) -> Optional[TrendResult]:
        """Plateau (logistic): y = L / (1 + exp(-k*(t - t0)))."""
        if len(t) < 4:
            return None

        try:
            L = np.max(y) * 1.1  # estimated upper bound
            if L == 0:
                return None

            # Normalize y to [0, 1] for logistic fit
            y_norm = y / L
            y_norm = np.clip(y_norm, 0.01, 0.99)

            # logit transform: ln(y/(1-y)) = k*t - k*t0
            logit_y = np.log(y_norm / (1.0 - y_norm))
            t_mean = np.mean(t)
            logit_mean = np.mean(logit_y)
            denom = np.sum((t - t_mean) ** 2)
            if denom == 0:
                return None

            k = np.sum((t - t_mean) * (logit_y - logit_mean)) / denom
            t0 = t_mean - logit_mean / k if k != 0 else t_mean

            y_pred = L / (1.0 + np.exp(-k * (t - t0)))
            r2 = self._r_squared(y, y_pred)
            residual_std = np.std(y - y_pred)

            t_future = t[-1] + horizon_s
            exponent = -k * (t_future - t0)
            if abs(exponent) > 50:
                predicted = L if exponent < 0 else 0.0
            else:
                predicted = L / (1.0 + math.exp(exponent))

            time_to_threshold = None
            if threshold is not None and k != 0 and 0 < threshold < L:
                t_thresh = t0 - math.log(L / threshold - 1) / k
                remaining = t_thresh - t[-1]
                if remaining > 0:
                    time_to_threshold = remaining

            return TrendResult(
                model=TrendModel.PLATEAU,
                predicted_value=predicted,
                confidence_lower=predicted - 2 * residual_std,
                confidence_upper=predicted + 2 * residual_std,
                r_squared=r2,
                time_to_threshold=time_to_threshold,
                parameters={'L': float(L), 'k': float(k), 't0': float(t0)},
                residual_std=float(residual_std),
            )
        except (ValueError, OverflowError, ZeroDivisionError):
            return None

    def _fit_seasonal(
        self,
        t: np.ndarray,
        y: np.ndarray,
        horizon_s: float,
        threshold: Optional[float],
    ) -> Optional[TrendResult]:
        """Seasonal: y = trend(t) + seasonal(t, period) + residual."""
        if len(t) < 20:
            return None

        try:
            best_r2 = -1.0
            best_result = None

            for period_hours in self.seasonal_periods:
                period_s = period_hours * 3600
                duration = t[-1] - t[0]
                if duration < period_s * 1.5:
                    continue  # not enough data for this period

                n_bins = max(4, min(int(duration / period_s * 4), 48))
                bin_size = period_s / n_bins * (duration / period_s)

                # Decompose: compute moving average for trend
                window = max(3, len(t) // 4)
                trend = np.convolve(y, np.ones(window) / window, mode='same')

                detrended = y - trend

                # Compute seasonal component by phase binning
                phases = (t % period_s) / period_s * n_bins
                phase_bins = phases.astype(int) % n_bins
                seasonal = np.zeros_like(y)
                for b in range(n_bins):
                    mask = phase_bins == b
                    if np.sum(mask) > 0:
                        seasonal[mask] = np.mean(detrended[mask])

                y_pred = trend + seasonal
                r2 = self._r_squared(y, y_pred)
                residual_std = np.std(y - y_pred)

                if r2 > best_r2:
                    # Predict at horizon
                    t_future = t[-1] + horizon_s
                    # Extrapolate linear trend
                    trend_slope = (trend[-1] - trend[0]) / (t[-1] - t[0]) if t[-1] != t[0] else 0
                    trend_future = trend[-1] + trend_slope * horizon_s
                    # Phase for future
                    future_phase = int((t_future % period_s) / period_s * n_bins) % n_bins
                    mask = phase_bins == future_phase
                    seasonal_future = np.mean(detrended[mask]) if np.sum(mask) > 0 else 0.0
                    predicted = trend_future + seasonal_future

                    time_to_threshold = None
                    if threshold is not None and trend_slope > 0:
                        t_thresh = (threshold - trend[-1]) / trend_slope
                        if t_thresh > 0:
                            time_to_threshold = t_thresh

                    best_result = TrendResult(
                        model=TrendModel.SEASONAL,
                        predicted_value=predicted,
                        confidence_lower=predicted - 2 * residual_std,
                        confidence_upper=predicted + 2 * residual_std,
                        r_squared=r2,
                        time_to_threshold=time_to_threshold,
                        parameters={
                            'trend_slope': float(trend_slope),
                            'period_hours': float(period_hours),
                        },
                        residual_std=float(residual_std),
                    )
                    best_r2 = r2

            return best_result
        except (ValueError, ZeroDivisionError):
            return None

    @staticmethod
    def _r_squared(y_actual: np.ndarray, y_predicted: np.ndarray) -> float:
        ss_res = np.sum((y_actual - y_predicted) ** 2)
        ss_tot = np.sum((y_actual - np.mean(y_actual)) ** 2)
        if ss_tot == 0:
            return 0.0
        return max(0.0, 1.0 - ss_res / ss_tot)
