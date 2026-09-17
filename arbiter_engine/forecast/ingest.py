"""File a batch of outside forecasts, and report every one that went nowhere.

A FEEDER, NOT A VERB. Forecasts are an INPUT, and every other input surface on
this session is a feeder: `add_entity`, `add_observations`,
`set_threshold_override`, `set_declared_thresholds`. The verb that reports on
them is `check`, which is where the `forecasts` sub-envelope will ride. Adding
a tenth module-level verb for an input would be the first time this package
answered *here is some data* with a verb, and the governance bar for the verb
surface exists precisely to stop that happening by accident.

NOTHING RAISES. A producer's batch of four hundred with three bad records files
three hundred and ninety-seven and reports the three -- the ruling that keeps
`add_observations` accepting any property name, for the same reason: refusing
the batch makes one producer's bug cost another producer's data, and an engine
whose thesis is *report what you could not use* must not answer unusable input
by discarding usable input beside it.

THE LEDGER IS STRICTER THAN THE CONTRACT, deliberately. `record_distribution`
raises on a duplicate quantile level and a malformed key, because by the time a
caller reaches it those are programming errors. Reached from here they are a
producer's JSON, so the raise is caught and becomes a rejection with the
producer's own record named. Two readers, two audiences, one rule each.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..clock import as_naive_utc, now_utc
from .contract import Forecast, ForecastRejected, parse_forecast


def _indicator_for(session: Any, entity: Any, property_name: str) -> Any:
    """The declared indicator a forecast names, by declared name or by the
    property it maps to. Both, because a producer speaks the model's vocabulary
    and a model with a `property_mapping` has two."""
    if getattr(session, "model", None) is None:
        return None
    for spec in session.model.indicators.get(entity.type, []):
        if property_name in (spec.name, spec.property_name):
            return spec
    return None


def ingest_forecasts(session: Any, records: Iterable[Any], *,
                     at: Optional[datetime] = None) -> Dict[str, Any]:
    """Parse, check against the model, file into the ledger, report the rest.

    Returns ``{received, filed, rejected: [...]}``. ``filed`` and the length of
    ``rejected`` sum to ``received`` -- every record is accounted for, which is
    the denominator discipline the top-level envelope applies to checks and
    which an input surface has exactly as much need of.
    """
    present = as_naive_utc(at) if at is not None else now_utc()
    rejected: List[Dict[str, Any]] = []
    filed = 0
    received = 0
    baselines = 0

    for raw in records:
        received += 1
        forecast, rejection = parse_forecast(raw, at=present)
        if rejection is not None:
            rejected.append(rejection.to_dict())
            continue

        outcome = _file(session, forecast)
        if outcome is None:
            filed += 1
            baselines += _file_baseline(session, forecast)
        else:
            rejected.append(outcome.to_dict())

    return {"received": received, "filed": filed, "rejected": rejected,
            # HOW MANY GOT A YARDSTICK. Reported rather than assumed equal to
            # `filed`: a reference needs a series to fit on, and a producer
            # forecasting a pair this session has little history for gets no
            # baseline. Silence there would leave *this model did not beat a
            # random walk* indistinguishable from *nothing ran a random walk*.
            "baselines": baselines}


def _file(session: Any, forecast: Forecast) -> Optional[ForecastRejected]:
    """File one parsed forecast, or say why it cannot be."""
    identity = {"entity_id": forecast.entity_id,
                "property_name": forecast.property_name,
                "model_id": forecast.model_id}

    entity = getattr(session, "entities", {}).get(forecast.entity_id)
    if entity is None:
        # NOT filed against an entity that will turn up later. A forecast is
        # graded against an observation of a specific entity, and a record
        # filed against an id the session has never held would sit pending
        # until it was evicted, counted in `pending` the whole time and
        # gradeable never.
        return ForecastRejected(
            "entity_unknown",
            f"this session holds no entity {forecast.entity_id!r}; add it "
            f"before forecasting it, or the record waits for a grading that "
            f"cannot happen", **identity)

    spec = _indicator_for(session, entity, forecast.property_name)
    if spec is None and getattr(session, "model", None) is not None:
        return ForecastRejected(
            "undeclared_indicator",
            f"{entity.type} declares no indicator {forecast.property_name!r}, "
            f"so nothing will ever read this forecast and no threshold exists "
            f"to compare it against", **identity)

    if spec is not None:
        kind = getattr(getattr(spec, "indicator_type", None), "value", None)
        if kind is not None and str(kind).upper() != "NUMERIC":
            return ForecastRejected(
                "wrong_indicator_type",
                f"{forecast.property_name!r} is declared {kind}; a quantile "
                f"forecast describes a number and there is nothing to score a "
                f"distribution over a state against", **identity)

    try:
        session.ledger.record_distribution(
            entity_id=forecast.entity_id,
            property_name=forecast.property_name,
            quantiles=forecast.quantiles,
            horizon_s=forecast.horizon_s,
            model_id=forecast.model_id,
            predicted_at=forecast.issued_at,
            # Free here and unrecoverable later: this function resolved the
            # entity two statements ago to check the forecast against the model.
            entity_type=entity.type,
        )
    except ValueError as exc:
        # The ledger's own rules, reached from a producer's JSON rather than
        # from our own code. Its message names the defect precisely and is
        # carried rather than paraphrased -- a second wording of one rule is
        # how the two drift.
        return ForecastRejected("malformed_forecast", str(exc), **identity)
    return None


def _file_baseline(session: Any, forecast: Forecast) -> int:
    """Fit the reference on the same series and horizon, and file it. 1 or 0.

    WHY THIS IS HERE AND NOT ONLY IN `project`. "Does it beat a random walk" is
    the question a forecast is judged by, and the engine kept the yardstick
    running for its OWN projections and not for anybody else's -- so a desk
    whose feed arrives through this function could never be told. The changelog
    said the reference is filed beside every forecast it judges; it was filed
    beside one of the two kinds.

    AS OF WHEN THE FORECAST WAS ISSUED. The series is read under the forecast's
    own instant, so the reference sees what the producer could have seen and
    not one reading more. Fitting on everything up to now would hand the
    yardstick a look at the outcome it is being compared on.

    NOTHING RAISES, like everything else on this path. A producer's batch must
    not fail because a reference could not be fitted.
    """
    from ..clock import as_of
    from ..projection.projector import (BASELINE_MODEL_ID, PROJECTORS,
                                        SOURCE_ENGINE, RandomWalk)
    from ..subenvelope import Decline

    if forecast.model_id == BASELINE_MODEL_ID:
        return 0                      # it IS the reference; do not race itself
    entity = getattr(session, "entities", {}).get(forecast.entity_id)
    if entity is None or getattr(session, "model", None) is None:
        return 0
    spec = _indicator_for(session, entity, forecast.property_name)
    if spec is None:
        return 0
    lookback = getattr(spec, "lookback", None) or getattr(spec, "time_window", None)
    if lookback is None:
        return 0

    # ONE REFERENCE PER SUBJECT AND INSTANT. Two producers forecasting one pair
    # at one moment are measured against one yardstick; filing a second
    # identical record would double its weight in every calibration figure that
    # strata by model.
    for record in session.ledger.records():
        if (record.kind == "distribution"
                and record.model_id == BASELINE_MODEL_ID
                and record.entity_id == forecast.entity_id
                and str(record.indicator) == forecast.property_name
                and record.predicted_at == forecast.issued_at
                and float(record.horizon_s) == float(forecast.horizon_s)):
            return 0

    try:
        with as_of(forecast.issued_at):
            series = session.history.get_values(
                forecast.entity_id, forecast.property_name, lookback)
        scope = {"entity_id": forecast.entity_id,
                 "property": forecast.property_name}
        fitted = PROJECTORS[RandomWalk.name].fit(series, {}, scope)
        if isinstance(fitted, Decline):
            return 0
        session.ledger.record_distribution(
            entity_id=forecast.entity_id,
            property_name=forecast.property_name,
            quantiles=fitted.forecast(float(forecast.horizon_s)).quantiles,
            horizon_s=float(forecast.horizon_s),
            model_id=BASELINE_MODEL_ID,
            predicted_at=forecast.issued_at,
            entity_type=entity.type,
            source=SOURCE_ENGINE)
    except (ValueError, KeyError, ArithmeticError, TypeError):
        return 0
    return 1
