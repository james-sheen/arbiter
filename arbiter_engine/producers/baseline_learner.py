"""A damped-trend exponential smoother, stated as quantiles.

The engine's own baseline is a random walk -- it predicts the last
value and widens with the horizon -- and every producer this engine grades is
scored against it. A random walk is the right FLOOR and a poor opponent: it is
beaten by anything that notices a series is going somewhere, so a producer that
beats it has shown almost nothing.

So this is the next thing up, and deliberately not further: Holt's linear method
with a damping factor, which is the smallest model that carries a trend and does
not extrapolate it forever. It is fitted by grid search over the three
parameters against one-step-ahead error on the series itself, which is honest
for a baseline and would not be for a claim.

WHAT IT REFUSES. A series shorter than `MINIMUM_POINTS` gets no forecast rather
than a fitted one -- three points can be fitted to perfectly and say nothing. A
series whose points are not strictly ordered in time is refused outright rather
than sorted, because re-ordering somebody's series silently is how a producer
scores well on data nobody gave it.

THE SPREAD IS THE RESIDUAL SPREAD, not a confidence interval. The quantiles come
from the one-step residuals scaled by the square root of the horizon in steps --
the random walk's own widening rule, applied to a better centre. Naming it an
interval would claim a distributional result this does not have.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: What the records say they came from. A producer names itself; the engine does
#: not name it, and `ingest_forecasts(source=)` is a separate statement about
#: who filed rather than about who computed.
BASELINE_MODEL_ID = "baseline-learner/holt-damped/1"

#: Below this a fit is arithmetic rather than evidence.
MINIMUM_POINTS = 12

#: The grid. Small on purpose: a baseline that is tuned finely is no longer a
#: baseline, it is an entry.
_ALPHAS = (0.2, 0.4, 0.6, 0.8)
_BETAS = (0.05, 0.15, 0.3)
_PHIS = (0.8, 0.9, 0.98)

#: The two the contract requires, plus the median the shadow check reads.
_Z = {"q05": -1.6448536269514722, "q50": 0.0, "q95": 1.6448536269514722}


class SeriesRefused(ValueError):
    """The series cannot be forecast, and the reason is not a number."""


def _ordered(points: Sequence[Tuple[datetime, float]]
             ) -> List[Tuple[datetime, float]]:
    rows = list(points)
    for earlier, later in zip(rows, rows[1:]):
        if later[0] <= earlier[0]:
            raise SeriesRefused(
                "the series is not strictly ordered in time; refusing rather "
                "than sorting, because re-ordering a series nobody gave you "
                "that way is how a producer scores well on data it invented")
    return rows


def _holt(values: Sequence[float], alpha: float, beta: float,
          phi: float) -> Tuple[float, float, List[float]]:
    """Level, trend and the one-step residuals, in one pass."""
    level = values[0]
    trend = values[1] - values[0]
    residuals: List[float] = []
    for actual in values[1:]:
        predicted = level + phi * trend
        residuals.append(actual - predicted)
        previous = level
        level = alpha * actual + (1.0 - alpha) * predicted
        trend = beta * (level - previous) + (1.0 - beta) * phi * trend
    return level, trend, residuals


def _fit(values: Sequence[float]) -> Tuple[float, float, float, float]:
    """`(level, trend, phi, sigma)` for the grid point with least squared error."""
    best = None
    for alpha in _ALPHAS:
        for beta in _BETAS:
            for phi in _PHIS:
                level, trend, residuals = _holt(values, alpha, beta, phi)
                sse = sum(r * r for r in residuals)
                if best is None or sse < best[0]:
                    n = max(1, len(residuals))
                    best = (sse, level, trend, phi, math.sqrt(sse / n))
    _sse, level, trend, phi, sigma = best
    return level, trend, phi, sigma


def forecast_series(points: Sequence[Tuple[datetime, float]], *,
                    entity_id: str, property_name: str,
                    horizon_s: float,
                    issued_at: Optional[datetime] = None
                    ) -> Optional[Dict[str, Any]]:
    """One forecast record, or `None` when the series cannot support one.

    Returns a plain dict in the shape `ingest_forecasts` reads. Nothing here
    constructs an engine object: a producer that had to import the contract to
    file would be a producer only this repository could write.
    """
    rows = _ordered(points)
    if len(rows) < MINIMUM_POINTS:
        return None

    values = [float(v) for _when, v in rows]
    level, trend, phi, sigma = _fit(values)

    step_s = (rows[-1][0] - rows[-2][0]).total_seconds()
    if step_s <= 0:
        raise SeriesRefused("the last two points share an instant")
    steps = max(1.0, horizon_s / step_s)

    # Damped trend summed over the horizon, which is what `phi` is for: the
    # contribution of each further step shrinks, so the forecast flattens
    # instead of running away.
    ahead = level + sum(phi ** k for k in range(1, int(steps) + 1)) * trend
    spread = sigma * math.sqrt(steps)

    return {
        "model_id": BASELINE_MODEL_ID,
        "entity_id": entity_id,
        "property": property_name,
        "issued_at": issued_at or rows[-1][0],
        "horizon_s": float(horizon_s),
        "quantiles": {name: ahead + z * spread for name, z in _Z.items()},
        "sample_count": len(rows),
    }


def forecast_session(session: Any, *, horizon_s: float,
                     issued_at: Optional[datetime] = None
                     ) -> List[Dict[str, Any]]:
    """Every numeric series this session can support a forecast for.

    Reads `reading_history()`, which is the store the engine tells every reader
    to ask -- `session.history` is what was FED, and the two differ whenever a
    calendar or a derived indicator is declared.
    """
    history = session.reading_history()
    out: List[Dict[str, Any]] = []
    for key, points in (history.get_all_numeric_series() or {}).items():
        # `entity_id.property_name`, split on the LAST dot: a property name
        # carries none in this engine and an entity id may, so splitting on the
        # first would silently forecast a property nobody named.
        entity_id, _, property_name = str(key).rpartition(".")
        if not entity_id or not property_name:
            continue
        try:
            record = forecast_series(
                points, entity_id=entity_id, property_name=property_name,
                horizon_s=horizon_s, issued_at=issued_at)
        except SeriesRefused:
            continue
        if record is not None:
            out.append(record)
    return out
