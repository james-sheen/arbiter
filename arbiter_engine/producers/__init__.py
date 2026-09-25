"""Reference producers. They have no special status and that is the point.

Phase B3. `STANCE.md` says what a producer is and what this engine owes
one: a record naming a `source` is filed, fitted a baseline, and graded, and the
only thing the source changes is whether the eight shadow axioms run over it.
Until now nothing in this repository walked through that door, so the whole
producer path was exercised by fixtures and a consumer asking *what does a
reasonable forecaster score here* had nothing to compare against.

WHAT MAKES THIS A PRODUCER AND NOT AN ENGINE FEATURE. Everything here reads the
session through `reading_history()` -- the accessor the engine tells every
reader to use -- and emits ordinary forecast records through
`ingest_forecasts`. It imports no checker, touches no envelope, and is handed no
privilege the engine would refuse an outside forecaster. If any of that stopped
being true the comparison it exists to support would stop meaning anything: a
baseline with access the competition lacks is not a baseline.
"""

from .baseline_learner import (
    BASELINE_MODEL_ID, MINIMUM_POINTS, SeriesRefused, forecast_series,
    forecast_session,
)

__all__ = ["BASELINE_MODEL_ID", "MINIMUM_POINTS", "SeriesRefused",
           "forecast_series", "forecast_session"]
