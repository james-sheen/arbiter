"""Forecasting a declared indicator forward, and saying what could not be forecast.

The engine judges what it has observed. This package answers the neighbouring
question -- what the series is about to do -- and it is a separate package
because the answer has a different shape: a distribution rather than a value, a
model that can fail to fit rather than a threshold that cannot, and a
denominator counted in series rather than in axiom evaluations.

Nothing here judges. A projection produces a forecast and, where the author has
declared what probability is worth reporting, a finding that says so. Every
other outcome is a decline naming the fact the author must supply.
"""

from .projector import (
    Fitted, Forecast, LocalLevel, PROJECTORS, Projector, TrendCurve,
)
from .runner import run_projection

__all__ = ["Fitted", "Forecast", "LocalLevel", "PROJECTORS", "Projector",
           "TrendCurve", "run_projection"]
