"""The projectors, and the shape they all answer in.

WHY A LOCAL LEVEL MODEL IS THE BUILT-IN ONE

It is the least a forecast can assume and still be a forecast: the quantity
wanders, and what you see is the wander plus measurement noise. It has two
parameters, both of which an author can declare from a datasheet or a contract,
and when they are not declared they can be estimated from the series itself --
with a test that says when they cannot.

The alternative already in this tree fits a curve and extrapolates it. That is
a stronger claim, and it is available here as `trend`, but it is no longer what
you get by not choosing: an extrapolated straight line reports a confident
number for a series that is not going anywhere.

WHAT A PROJECTOR MAY NOT DO

Return a number it cannot defend. Every path out of `fit` is either a `Fitted`
whose parameters have a stated `source`, or a `Decline` naming the fact that
was missing. There is no third branch, and in particular no fallback that
substitutes a plausible parameter and reports the result as a forecast.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..subenvelope import Decline

__all__ = ["Forecast", "Fitted", "Projector", "LocalLevel", "TrendCurve",
           "PROJECTORS", "SOURCE_DECLARED", "SOURCE_ESTIMATED", "SOURCE_CURVE",
           "SOURCE_BASELINE", "SOURCE_ENGINE", "RandomWalk",
           "BASELINE_MODEL_ID"]

#: Where a model's parameters came from. Carried on every forecast, because a
#: number the author declared and a number the engine inferred from the same
#: series it is now forecasting are different kinds of claim, and only the
#: second can be circular.
SOURCE_DECLARED = "declared_model"
SOURCE_ESTIMATED = "estimated_parameters"
SOURCE_CURVE = "curve_fit"
#: Says the numbers came from the yardstick rather than from a fitted model, so
#: a reader of `diagnostics` can tell a reference forecast from a real one
#: without matching on the model name.
SOURCE_BASELINE = "baseline_reference"

#: WHO ISSUED A LEDGER RECORD, which is a different question from where a
#: model's parameters came from -- the four constants above answer that, and
#: all four are the engine's own work. This one is what the `forecasts` leg
#: reads to tell its own projections from an outside producer's submission,
#: and it is deliberately ONE value rather than four: a leg that judged
#: `estimated_parameters` differently from `curve_fit` would be branching on a
#: distinction that belongs to the projector, not to the question of whether
#: anybody outside owes a forecast.
SOURCE_ENGINE = "engine"

#: The innovations test. For a correctly specified filter the normalised
#: innovation squared has mean 1 -- it is a chi-square with one degree of
#: freedom -- so a mean far from 1 says the model does not describe this series.
#:
#: The band is deliberately loose. It is not tuned to a significance level,
#: because its job is to catch a model that is wrong by an order of magnitude,
#: not to adjudicate a close call; a tight band would decline series that are
#: merely a bit non-Gaussian, and a decline the author cannot act on is noise.
#:
#: This constant decides whether the engine REFUSES, never what it asserts. A
#: default that makes the engine answer would need declaring; one that makes it
#: decline, with the measured value in the decline's evidence, leaves the
#: author strictly better informed than silence.
NIS_BAND: Tuple[float, float] = (0.5, 2.0)

#: Fewer than this and neither the filter nor the moment estimator has anything
#: to say. Five is the floor the engine already applies to its temporal axioms.
MINIMUM_SAMPLES = 5


@dataclass(frozen=True)
class Forecast:
    """A distribution over what the property will read at the horizon.

    ``sigma`` is the standard deviation of the OBSERVATION, not of the hidden
    state. The difference is the measurement noise, and it matters twice: the
    mirror this is graded against is an observation, and the thresholds a
    breach probability is computed against are declared on observed values. A
    forecast of the state would be systematically overconfident about both.
    """

    mean: float
    sigma: float
    horizon_s: float
    model: str
    source: str
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    @property
    def quantiles(self) -> Dict[str, float]:
        """The levels the ledger scores, derived from this distribution."""
        dist = statistics.NormalDist(self.mean, self.sigma)
        return {"q05": dist.inv_cdf(0.05),
                "q50": dist.inv_cdf(0.50),
                "q95": dist.inv_cdf(0.95)}

    def p_at_or_below(self, value: float) -> float:
        return statistics.NormalDist(self.mean, self.sigma).cdf(value)

    def p_above(self, value: float) -> float:
        return 1.0 - self.p_at_or_below(value)


@dataclass(frozen=True)
class Fitted:
    """A model that has assimilated a series and can be asked for a horizon."""

    level: float
    variance: float
    q: float
    r: float
    last_at: datetime
    n: int
    model: str
    source: str
    nis_mean: Optional[float] = None

    def forecast(self, horizon_s: float) -> Forecast:
        variance = self.variance + self.q * horizon_s + self.r
        return Forecast(
            mean=self.level, sigma=math.sqrt(max(variance, 1e-300)),
            horizon_s=float(horizon_s), model=self.model, source=self.source,
            diagnostics={"n": self.n, "q": self.q, "r": self.r,
                         "state_variance": self.variance,
                         "nis_mean": self.nis_mean,
                         "last_assimilated": self.last_at.isoformat()},
        )


class Projector:
    """What a projector must be. Named rather than duck-typed so that
    `PROJECTORS` is a closed set an author can be told about."""

    name: str = ""

    def fit(self, series: Sequence[Tuple[datetime, float]],
            dynamics: Dict[str, Any],
            scope: Dict[str, Any]) -> Union[Fitted, Decline]:
        raise NotImplementedError


def _moments(series: Sequence[Tuple[datetime, float]]) -> Optional[Tuple[float, float]]:
    """Estimate ``(q, r)`` from the series, or ``None`` when they do not separate.

    For a local level model the first differences carry both parameters:
    their variance is ``q*dt + 2r`` and their lag-1 autocovariance is ``-r``.
    Two equations, two unknowns -- and the system is what fails when the data
    cannot tell a wandering level from a noisy sensor.

    ``None`` when either estimate lands at or below zero. That is not a
    numerical nuisance to be clamped away: a non-positive ``r`` means the
    differences are positively autocorrelated, which this model does not
    describe, and returning a clamped value would report a fitted model for a
    series that refuted it.
    """
    values = [v for _, v in series]
    deltas = [b - a for a, b in zip(values, values[1:])]
    if len(deltas) < 2:
        return None
    spans = [(b[0] - a[0]).total_seconds() for a, b in zip(series, series[1:])]
    mean_dt = sum(spans) / len(spans)
    if mean_dt <= 0:
        return None
    var_d = statistics.pvariance(deltas)
    mean_d = statistics.fmean(deltas)
    lag1 = statistics.fmean(
        [(a - mean_d) * (b - mean_d) for a, b in zip(deltas, deltas[1:])])
    r = -lag1
    q = (var_d - 2.0 * r) / mean_dt
    if r <= 0.0 or q <= 0.0:
        return None
    return q, r


class RandomWalk(Projector):
    """The reference: tomorrow is today, and the spread is how much it moves.

    NOT A MODEL THE ENGINE OFFERS, a yardstick it holds. *Does it beat a random
    walk* is the first question asked of any forecaster, and a calibration
    table without the answer invites the reading that a well-calibrated model
    is a useful one -- a forecaster can be beautifully calibrated and still
    carry no information at all.

    PARAMETER-FREE ON PURPOSE, and that is the whole difference between this
    and `local_level` one class below, which is also a random walk. That one
    estimates `q` and `r` and declines when they do not separate; it is a
    model, and a model is what is being judged. A yardstick that could be
    tuned would let a poor comparison be explained away by tuning it.

    The forecast is the last observation. The spread is the sample standard
    deviation of the first differences, scaled by the square root of the
    horizon in steps -- which is what a random walk does and the reason the
    comparison is fair rather than generous: it is the weakest defensible
    forecast, not a strawman.

    IT DECLINES ON THE SAME FLOOR the models use rather than a lower one.
    Answering where they cannot would put a baseline score beside no model
    score and invite a comparison between a figure and an absence.
    """

    name = "random_walk"

    def fit(self, series, dynamics, scope):
        if len(series) < MINIMUM_SAMPLES:
            return Decline(
                "insufficient_samples", scope,
                detail=(f"the reference needs {MINIMUM_SAMPLES} readings to "
                        f"measure how much this series moves; {len(series)} "
                        f"were in the window"),
                evidence={"n": len(series)})
        values = [v for _, v in series]
        deltas = [b - a for a, b in zip(values, values[1:])]
        spans = [(b[0] - a[0]).total_seconds()
                 for a, b in zip(series, series[1:])]
        mean_dt = sum(spans) / len(spans)
        if mean_dt <= 0:
            return Decline(
                "undefined_for_values", scope,
                detail="the readings carry no time between them, so there is "
                       "no step for a step-size to be measured over",
                evidence={"n": len(series)})
        step_var = statistics.pvariance(deltas)
        # PER SECOND, so a horizon in seconds scales it. Storing the per-step
        # variance and scaling by the horizon would silently assume the horizon
        # is expressed in the same steps the series happened to arrive at.
        q = step_var / mean_dt
        return Fitted(level=values[-1], variance=0.0, q=q, r=0.0,
                      last_at=series[-1][0], n=len(series),
                      model=self.name, source=SOURCE_BASELINE)


class LocalLevel(Projector):
    """Random walk plus measurement noise, assimilated by a Kalman filter."""

    name = "local_level"

    def fit(self, series, dynamics, scope):
        declared_q, declared_r = dynamics.get("q"), dynamics.get("r")
        if declared_q is not None and declared_r is not None:
            q, r, source = float(declared_q), float(declared_r), SOURCE_DECLARED
            if q <= 0 or r <= 0:
                return Decline("unidentifiable_parameter", scope,
                               detail="declared q and r must both be positive",
                               evidence={"q": q, "r": r})
        else:
            estimated = _moments(series)
            if estimated is None:
                return Decline(
                    "unidentifiable_parameter", scope,
                    detail=("q and r do not separate from this series; declare "
                            "them under `dynamics` or supply a longer series"),
                    evidence={"n": len(series),
                              "declared_q": declared_q, "declared_r": declared_r})
            q, r = estimated
            source = SOURCE_ESTIMATED

        level, variance = series[0][1], r
        nis: List[float] = []
        for (t0, _), (t1, y) in zip(series, series[1:]):
            gap = (t1 - t0).total_seconds()
            variance += q * max(gap, 0.0)
            innovation = y - level
            s = variance + r
            nis.append(innovation * innovation / s)
            gain = variance / s
            level += gain * innovation
            variance *= (1.0 - gain)

        nis_mean = statistics.fmean(nis)
        low, high = NIS_BAND
        if not low < nis_mean < high:
            return Decline(
                "model_inconsistent", scope,
                detail=("the filter's innovations are not what this model "
                        "predicts; its forecasts would be mis-scaled"),
                evidence={"nis_mean": nis_mean, "band": [low, high],
                          "n": len(series), "q": q, "r": r, "source": source})

        return Fitted(level=level, variance=variance, q=q, r=r,
                      last_at=series[-1][0], n=len(series),
                      model=self.name, source=source, nis_mean=nis_mean)


class TrendCurve(Projector):
    """Least-squares straight line, with the residual spread as its width.

    The engine's older projection, kept and DEMOTED. It is reachable by
    declaring `dynamics: {model: trend}` and is no longer what an author gets
    by declaring nothing, because extrapolating a fitted line states a
    direction for a series that may have none.
    """

    name = "trend"

    def fit(self, series, dynamics, scope):
        t0 = series[0][0]
        xs = [(t - t0).total_seconds() for t, _ in series]
        ys = [v for _, v in series]
        mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
        sxx = sum((x - mean_x) ** 2 for x in xs)
        if sxx <= 0:
            return Decline("unidentifiable_parameter", scope,
                           detail="every sample carries the same timestamp",
                           evidence={"n": len(series)})
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / sxx
        intercept = mean_y - slope * mean_x
        residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
        spread = statistics.pstdev(residuals)
        if spread <= 0:
            return Decline(
                "covariance_unbounded", scope,
                detail=("the fit is exact, so this model reports no uncertainty "
                        "at all and every breach probability would be 0 or 1"),
                evidence={"n": len(series), "slope": slope})
        # Carried as a local-level `Fitted` so one shape reaches the runner:
        # the level is the line AT the last sample, the spread is the
        # measurement width, and `q` extrapolates the line across the horizon.
        return Fitted(level=intercept + slope * xs[-1],
                      variance=0.0, q=slope * slope, r=spread * spread,
                      last_at=series[-1][0], n=len(series),
                      model=self.name, source=SOURCE_CURVE)


#: The closed set of models an author may name. A `dynamics.model` outside it
#: is reported with a did-you-mean rather than silently substituted.
PROJECTORS: Dict[str, Projector] = {
    LocalLevel.name: LocalLevel(),
    RandomWalk.name: RandomWalk(),
    TrendCurve.name: TrendCurve(),
}

#: The model id the reference files under. RESERVED, and checked rather than
#: conventional: a producer naming their own model this would land in the
#: baseline's column and the table would compare it against itself.
BASELINE_MODEL_ID = "baseline_rw"
