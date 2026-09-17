"""Walk the declared numeric indicators, forecast what can be forecast, and
report every one that could not be.

THE DENOMINATOR IS `series_seen`, and it is counted here rather than
reconstructed by a caller: one per (entity, declared numeric indicator) pair
this routine actually looked at. Findings plus declines does not equal it -- a
series that forecast cleanly and crossed no reporting line appears in neither,
which is exactly why the count is reported separately.

THE ORDER OF THE CHECKS IS AN ARGUMENT, and it departs from the obvious one.
A missing `dynamics` block is tested BEFORE the sample floor. Both can be true
at once, and reporting the floor first tells an author to collect more data --
which will never produce a forecast, because nothing has said what model to
fit. The engine already refuses to give that advice elsewhere: the sample-floor
decline carries a remedy saying *collecting for longer will not help* when the
rate cannot span the window. Same rule, one declaration further out.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..interfaces import IndicatorSpec
from ..subenvelope import Decline, SubEnvelope
from ..types import Axiom, IndicatorType, Severity
from ..twin.topology import GapType, TopologyGap, TopologyQuestion
from .projector import (BASELINE_MODEL_ID, MINIMUM_SAMPLES, PROJECTORS,
                        RandomWalk)

__all__ = ["run_projection"]

#: Priorities come off the gap-type weight table and are scored at hop zero,
#: because that is where a declaration gap is found. Restating the weights here
#: would be a second copy of that table; they are read from it.
from ..twin.gap import GAP_CONFIDENCE_THRESHOLDS as _GAP_WEIGHT


def _scope(entity, spec) -> Dict[str, Any]:
    return {"entity_id": entity.id, "property": spec.property_name}


def _question(gap_type, location: str, description: str,
              text: str) -> TopologyQuestion:
    return TopologyQuestion(
        gap=TopologyGap(gap_type=gap_type, location=location,
                        description=description),
        question_text=text,
        priority=_GAP_WEIGHT.get(gap_type, 0.5),
        context_path=[],
    )


def _thresholds(spec: IndicatorSpec) -> Dict[str, float]:
    """The declared lines a forecast can be compared against, upper and lower.

    Read off the spec rather than off a config block: these are the same four
    numbers BOUNDEDNESS judges the current value by, and a projection that
    invented its own would be reporting a breach of a line nobody declared.
    """
    declared = {
        "critical": spec.critical_threshold,
        "warning": spec.warning_threshold,
        "lower_critical": spec.lower_critical_threshold,
        "lower_warning": spec.lower_warning_threshold,
    }
    return {k: float(v) for k, v in declared.items() if v is not None}


def _breach_probabilities(forecast, thresholds: Dict[str, float]) -> Dict[str, float]:
    out = {}
    for name, value in thresholds.items():
        if name.startswith("lower_"):
            out[name] = forecast.p_at_or_below(value)
        else:
            out[name] = forecast.p_above(value)
    return out


def run_projection(session, horizon_s: float = 3600.0) -> SubEnvelope:
    """Forecast every declared numeric indicator on every entity."""
    checked = {"series_seen": 0, "forecasts_issued": 0,
               "observations_assimilated": 0}
    findings: List[Any] = []
    declines: List[Decline] = []
    questions: List[Any] = []

    if session.model is None:
        return SubEnvelope("projection", {"series_seen": 0}, source="unavailable",
                           reason="no domain model loaded")

    for entity in session.entities.values():
        for spec in session.model.indicators.get(entity.type, []) or []:
            if spec.indicator_type is not IndicatorType.NUMERIC:
                continue
            checked["series_seen"] += 1
            scope = _scope(entity, spec)
            location = f"{entity.id}.{spec.property_name}"

            dynamics = spec.dynamics_config or {}
            if not dynamics:
                declines.append(Decline(
                    "model_missing", scope,
                    detail=("no `dynamics` declared, so there is no model to fit; "
                            "the engine will not choose one on the author's behalf"),
                ))
                questions.append(_question(
                    GapType.MISSING_DYNAMICS, location,
                    "no dynamics declared for a numeric indicator",
                    f"What model describes how {location} moves? "
                    f"Declare `dynamics: {{model: ...}}`; "
                    f"known models are {sorted(PROJECTORS)}."))
                continue

            model_name = str(dynamics.get("model") or "")
            projector = PROJECTORS.get(model_name)
            if projector is None:
                declines.append(Decline(
                    "model_missing", scope,
                    detail=(f"`dynamics.model` is {model_name!r}, which this "
                            f"engine does not implement"),
                    evidence={"declared": model_name, "known": sorted(PROJECTORS)}))
                continue

            # REACHABLE ONLY FROM A SPEC SUPPLIED PROGRAMMATICALLY. The YAML
            # loader gives every indicator a `window` when the author declares
            # none, so a loaded model always has something here -- which means
            # an author who declared no window is fitted on the LOADER's
            # default and not on one projection chose. That default is older
            # than this verb and is read by the temporal axioms too; naming it
            # here rather than adding a second one is deliberate.
            lookback = spec.lookback or spec.time_window
            if lookback is None:
                declines.append(Decline(
                    "no_lookback", scope,
                    detail=("neither `lookback` nor `window` is declared, so "
                            "there is no span of history to fit on")))
                continue

            series = session.history.get_values(
                entity.id, spec.property_name, lookback)
            if len(series) < MINIMUM_SAMPLES:
                declines.append(Decline(
                    "insufficient_samples", scope,
                    evidence={"n": len(series), "required": MINIMUM_SAMPLES,
                              "lookback_s": lookback.total_seconds()}))
                continue

            fitted = projector.fit(series, dynamics, scope)
            if isinstance(fitted, Decline):
                declines.append(fitted)
                continue

            horizon = float(
                spec.horizon.total_seconds() if spec.horizon else horizon_s)
            forecast = fitted.forecast(horizon)
            checked["forecasts_issued"] += 1
            checked["observations_assimilated"] += len(series)

            # RULE: every prediction gets graded. Filed before anything is
            # decided about it, so a forecast the author declared no reporting
            # line for is still scored against the mirror -- the calibration of
            # a model is not conditional on whether it happened to alarm.
            session.ledger.record_distribution(
                entity_id=entity.id, property_name=spec.property_name,
                quantiles=forecast.quantiles, horizon_s=horizon,
                model_id=f"{forecast.model}:{forecast.source}",
                entity_type=entity.type)

            # THE REFERENCE, ON THE SAME SERIES AND THE SAME HORIZON. Filed
            # here rather than by a separate pass, because a baseline scored on
            # a different population answers nothing: the comparison a reader
            # wants is *this forecast against what a random walk would have
            # said about exactly this*, and anything else is two numbers that
            # happen to sit in one table.
            #
            # SKIPPED when the declared model IS the reference, which would
            # otherwise file the same forecast twice under two ids and make it
            # beat itself.
            if PROJECTORS[model_name].name != RandomWalk.name:
                reference = PROJECTORS[RandomWalk.name].fit(series, {}, scope)
                if not isinstance(reference, Decline):
                    session.ledger.record_distribution(
                        entity_id=entity.id, property_name=spec.property_name,
                        quantiles=reference.forecast(horizon).quantiles,
                        horizon_s=horizon, model_id=BASELINE_MODEL_ID,
                        entity_type=entity.type)

            thresholds = _thresholds(spec)
            if not thresholds:
                declines.append(Decline(
                    "no_threshold", scope,
                    detail=("the forecast stands, and no declared line says what "
                            "would count as breaching it"),
                    evidence={"forecast": forecast.quantiles}))
                continue

            report_above = dynamics.get("report_above")
            if report_above is None:
                # A BREACH PROBABILITY IS NOT A VERDICT. Whether 0.2 is alarming
                # is a property of the engagement, not of the arithmetic, and a
                # constant here would be this engine deciding an answer from a
                # number nobody published -- the thing its own floor rule exists
                # to forbid. So the probability is computed, the author is asked
                # for the line, and no finding is invented in the meantime.
                declines.append(Decline(
                    "no_report_probability", scope,
                    detail=("declare `dynamics.report_above` to say which breach "
                            "probability is worth a finding"),
                    evidence={"p_breach": _breach_probabilities(forecast, thresholds)}))
                questions.append(_question(
                    GapType.MISSING_THRESHOLD, location,
                    "no reporting probability declared for a projected breach",
                    f"Above what probability should a projected breach of "
                    f"{location} be reported? Declare `dynamics.report_above`."))
                continue

            probabilities = _breach_probabilities(forecast, thresholds)
            crossed = {k: p for k, p in probabilities.items()
                       if p >= float(report_above)}
            if crossed:
                worst = max(crossed, key=crossed.get)
                findings.append(_finding(entity, spec, forecast, probabilities,
                                         worst, float(report_above)))

    return SubEnvelope("projection", checked, findings, declines, questions)


def _finding(entity, spec, forecast, probabilities, worst, report_above):
    from ..interfaces import Problem
    severity = (Severity.HIGH if worst in ("critical", "lower_critical")
                else Severity.MEDIUM)
    return Problem.from_entity(
        entity,
        problem_type=f"projected_breach:{spec.name}",
        severity=severity,
        reason=(f"P({worst} breach within {forecast.horizon_s:g}s) = "
                f"{probabilities[worst]:.2f}, at or above the declared "
                f"{report_above:g}"),
        axiom=Axiom.BOUNDEDNESS,
        evidence={"p_breach": probabilities, "crossed": worst,
                  "report_above": report_above,
                  "quantiles": forecast.quantiles,
                  "model": forecast.model, "source": forecast.source,
                  "horizon_s": forecast.horizon_s, **forecast.diagnostics},
    )
