"""What the forecasts said, what arrived, and what never did.

`expected` IS THE POINT OF THIS FILE. A report of *371 forecasts received* is
not a measurement until somebody says out of how many, and the only honest
source for that number is the model: an indicator declaring `forecast:
{expected: true}` says an outside forecaster is supposed to supply one. Counting
what arrived and calling it the denominator is the shape rule 1 exists to
forbid, and it is the shape every forecasting dashboard has.

SO A MODEL THAT DECLARES NOTHING GETS A QUESTION, NOT A ZERO. `expected: 0`
beside `received: 12` would read as twelve unexpected forecasts; the truth is
that nobody has said which pairs should carry one, and `missing_declaration`
asks.

THE FINDINGS DO NOT CLIMB. This sub-envelope rides on `check`, whose top-level
findings are about the present. A forecast breach merged into those would put
*your prediction is impossible* beside *your system is breaking* in one list --
the confusion the `forecast_` prefix exists to prevent, reintroduced one level
up where the prefix cannot be seen.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..clock import now_utc
from ..subenvelope import Decline, SubEnvelope
from .shadow import run_shadow_check


def _expected_pairs(session: Any) -> Tuple[List[Tuple[str, str]], List[str]]:
    """``(pairs, undeclared_types)`` -- what should carry a forecast.

    A pair is (entity id, indicator name) for every entity whose TYPE declares
    `forecast: {expected: true}` on that indicator. Per entity rather than per
    type, because a forecast is supplied for a subject and a type with two
    hundred instances expects two hundred forecasts, not one.
    """
    if session.model is None:
        return [], []
    pairs: List[Tuple[str, str]] = []
    declaring = set()
    for entity_type, specs in session.model.indicators.items():
        for spec in specs:
            if (spec.forecast_config or {}).get("expected"):
                declaring.add(entity_type)
    for entity_id, entity in sorted(session.entities.items()):
        for spec in session.model.indicators.get(entity.type, []):
            if (spec.forecast_config or {}).get("expected"):
                pairs.append((entity_id, spec.property_name or spec.name))
    undeclared = sorted({e.type for e in session.entities.values()}
                        - declaring)
    return pairs, undeclared


def _spec_for(session: Any, entity_type: str, indicator: str) -> Any:
    for spec in session.model.indicators.get(entity_type, []):
        if indicator in (spec.name, spec.property_name):
            return spec
    return None


def run_forecasts(session: Any) -> SubEnvelope:
    """The `forecasts` leg: the denominator, the declines, and the shadow run."""
    pairs, undeclared = _expected_pairs(session)
    records = list(session.ledger.records())
    distributions = [r for r in records if r.kind == "distribution"]
    arrived = {(r.entity_id, str(r.indicator)) for r in distributions}

    declines: List[Decline] = []
    questions: List[Any] = []

    for entity_id, indicator in pairs:
        if (entity_id, indicator) not in arrived:
            declines.append(Decline(
                "forecast_missing", {"entity": entity_id, "indicator": indicator},
                detail=("this indicator declares `forecast: {expected: true}` "
                        "and no forecast for it has been filed")))

    present = now_utc()
    for record in distributions:
        scope = {"entity": record.entity_id, "indicator": str(record.indicator)}
        entity = session.entities.get(record.entity_id)
        spec = (_spec_for(session, entity.type, str(record.indicator))
                if entity is not None and session.model is not None else None)
        config = (spec.forecast_config or {}) if spec is not None else {}

        # A DECLARED LIST OR NO CHECK. Without one the engine has no way to
        # tell a new model from a typo'd one, and refusing every id it has not
        # seen would refuse the first forecast every producer ever sends.
        allowed = config.get("models")
        if allowed and record.model_id not in allowed:
            declines.append(Decline(
                "model_unknown", dict(scope, model_id=record.model_id),
                detail=(f"{record.model_id!r} is not among the models this "
                        f"indicator declares: {sorted(allowed)}")))

        # SAME RULE FOR STALENESS. How old is too old is a property of the
        # engagement -- a minute for a quote, a day for a balance -- so there
        # is no check until somebody declares the number.
        max_age = config.get("max_age")
        if max_age is not None:
            seconds = _seconds(max_age)
            if seconds is None:
                declines.append(Decline(
                    "stale_forecast", scope,
                    detail=(f"`forecast.max_age` is {max_age!r}, which is not "
                            f"a duration this engine reads")))
            elif (present - record.predicted_at).total_seconds() > seconds:
                age = (present - record.predicted_at).total_seconds()
                declines.append(Decline(
                    "stale_forecast", scope,
                    detail=(f"issued {age:.0f}s ago, past the declared "
                            f"`max_age` of {seconds:.0f}s"),
                    evidence={"age_s": round(age, 3), "max_age_s": seconds}))

        if record.verdict == "ungradeable":
            declines.append(Decline(
                "ungradeable", scope,
                detail=("this forecast matured and no observation was in the "
                        "history to score it against")))

    if not pairs:
        types = undeclared or sorted({e.type for e in session.entities.values()})
        for entity_type in types:
            questions.append({
                "kind": "missing_declaration",
                "entity_type": entity_type,
                "question": (f"Which of {entity_type}'s indicators should carry "
                             f"a forecast? Declare `forecast: {{expected: true}}` "
                             f"on each, so a missing one can be reported."),
            })

    shadow = run_shadow_check(session)
    graded = sum(1 for r in distributions if r.verdict is not None)
    checked = {
        "expected": len(pairs),
        "received": len(arrived & set(pairs)) if pairs else len(arrived),
        "graded": graded,
        "pending": len(distributions) - graded,
        # NEVER SUMMED WITH THE AXIOM DENOMINATOR, like every other discipline.
        "invariants": 0,
    }
    return SubEnvelope("forecasts", checked, list(shadow.findings),
                       declines, questions)


def _seconds(raw: Any) -> Optional[float]:
    """A duration in seconds, from a number or the short forms the model uses."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    from ..ontology.domain_loader import parse_duration
    parsed = parse_duration(str(raw))
    return parsed.total_seconds() if parsed is not None else None
