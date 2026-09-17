"""The contract an outside forecaster speaks, and nothing that forecasts.

A forecasting model IS domain knowledge. Putting a GARCH or a gradient-boosted
tree in here would put *which indicators matter* in here, which is the one
thing this engine is built not to carry. What it adds instead is what
forecasters conspicuously lack: a denominator, declines, and calibration
stratified by something other than the whole population.

Models change monthly. The contract for what a forecast looks like and how it
is scored can stand for a decade, and that asymmetry is the whole argument for
the split.
"""

from .contract import (
    Forecast,
    ForecastRejected,
    REQUIRED_QUANTILES,
    parse_forecast,
)
from .envelope import run_forecasts
from .ingest import ingest_forecasts
from .monitor import feed_model_figures, model_figures
from .shadow import SHADOW_PREFIX, run_shadow_check, shadow_entities

__all__ = ["Forecast", "ForecastRejected", "REQUIRED_QUANTILES",
           "SHADOW_PREFIX", "ingest_forecasts", "parse_forecast",
           "feed_model_figures", "model_figures", "run_forecasts", "run_shadow_check",
           "shadow_entities"]
