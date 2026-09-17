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

    for raw in records:
        received += 1
        forecast, rejection = parse_forecast(raw, at=present)
        if rejection is not None:
            rejected.append(rejection.to_dict())
            continue

        outcome = _file(session, forecast)
        if outcome is None:
            filed += 1
        else:
            rejected.append(outcome.to_dict())

    return {"received": received, "filed": filed, "rejected": rejected}


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
