"""Run the eight axioms over the forecast itself.

A FORECAST CAN BE INCOHERENT BEFORE IT IS WRONG. A forecast NAV that does not
equal the sum of the forecast holdings, a forecast bid above a forecast ask, a
forecast count below zero -- none of these needs an observation to be refuted,
and none of them is what calibration measures. A model can be beautifully
calibrated on every indicator taken alone and still predict a world that cannot
exist.

THE SAME RULES, NOT A SECOND SET. The shadow entities go through
`reasoner.detect`, so every product of Path A applies a second time: derived
indicators, cross-entity conservation, the roles, the grid and the ordering. A
separate validator would be a second copy of the model's meaning and would
drift from it the first time an axiom changed.

FORECAST PROPERTIES ONLY, and this is the decision that matters most here. A
shadow entity carries the forecast medians and nothing else -- it does NOT
inherit the entity's current readings for properties nobody forecast. Filling
the gaps from reality would let a balance close because its unforecast side
came from today, reporting that a forecast is coherent when half of it is not a
forecast at all. Where the forecast is partial the axiom declines, and the
decline names what was missing, which is the true answer.

EVERY FINDING IS PREFIXED. `forecast_` in front of the problem type, so no
reader can mistake *your system is breaking* for *your prediction of your
system is impossible*. They call for different people.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..interfaces import Entity, ObservationHistory
from ..axiom_thresholds import DECLARED_THRESHOLDS_KEY
from ..projection.projector import SOURCE_ENGINE
from ..subenvelope import Decline, SubEnvelope

#: The prefix that keeps the two questions apart. Applied to the problem type
#: rather than carried in a field, because a consumer filtering on
#: `problem_type` is the shape every existing report already uses.
SHADOW_PREFIX = "forecast_"

#: How well a breach probability is known. `exact` means the threshold fell
#: between two declared quantiles and the answer is interpolation between
#: them; the other two mean it fell outside the declared range, where the only
#: honest statement is a BOUND.
#:
#: This distinction is the whole of the arithmetic below. A producer sending
#: `q05/q50/q95` has said nothing about the shape past the 5th and 95th
#: percentiles, and turning `threshold is beyond q95` into a point probability
#: means choosing a tail -- which is the silent Gaussian assumption the
#: contract module refuses one file over.
EXACT, AT_MOST, AT_LEAST = "exact", "at_most", "at_least"


@dataclass(frozen=True)
class BreachProbability:
    """``value`` with ``bound`` saying whether it is the answer or a limit."""

    value: float
    bound: str
    #: The two declared levels the answer was interpolated between, or the one
    #: it was bounded by. Carried so a reader can see the arithmetic rather
    #: than take the number on trust.
    between: Tuple[float, ...]

    def decides(self, report_above: float) -> Optional[bool]:
        """Whether this crosses the line, or None when it cannot be told.

        NONE IS A REAL ANSWER and is the reason this returns three states. A
        bound of *at most 0.05* settles a reporting line of 0.1 -- it cannot
        be crossed -- and settles nothing at a line of 0.01, where the true
        probability might be 0.04 or 0.0001. Returning False there would read
        as *checked, and fine*.
        """
        if self.bound == EXACT:
            return self.value >= report_above
        if self.bound == AT_MOST:
            return False if self.value < report_above else None
        return True if self.value >= report_above else None


def _sorted_levels(quantiles: Dict[str, float]) -> List[Tuple[float, float]]:
    """``(level, value)`` pairs, ascending by level."""
    out = []
    for key, value in quantiles.items():
        text = str(key).strip().lower()
        if not text.startswith("q") or not text[1:].isdigit():
            continue
        out.append((float(f"0.{text[1:]}"), float(value)))
    return sorted(out)


def breach_probability(quantiles: Dict[str, float], threshold: float, *,
                       lower: bool) -> Optional[BreachProbability]:
    """P(the forecast breaches ``threshold``), or None with nothing to say.

    ``lower`` selects the side: a floor is breached from below, a ceiling from
    above. The two are not symmetric in the arithmetic and conflating them
    reports the complement of the answer, which looks entirely plausible.

    PIECEWISE LINEAR BETWEEN DECLARED LEVELS, and no shape assumed anywhere.
    The quantile function is known at the levels the producer sent and nowhere
    else; a straight line between two of them is the one interpolation that
    adds no information.
    """
    points = _sorted_levels(quantiles)
    if len(points) < 2:
        return None
    lo_level, lo_value = points[0]
    hi_level, hi_value = points[-1]

    if threshold <= lo_value:
        # Below everything declared: F(threshold) <= lo_level.
        cumulative = BreachProbability(lo_level, AT_MOST, (lo_level,))
        below = cumulative
        above = BreachProbability(1.0 - lo_level, AT_LEAST, (lo_level,))
    elif threshold >= hi_value:
        below = BreachProbability(hi_level, AT_LEAST, (hi_level,))
        above = BreachProbability(1.0 - hi_level, AT_MOST, (hi_level,))
    else:
        for (l0, v0), (l1, v1) in zip(points, points[1:]):
            if v0 <= threshold <= v1:
                span = v1 - v0
                # A flat segment means two levels share a value, so the
                # threshold sits on a step of the distribution. The upper level
                # is the conservative reading: more mass is at or below it.
                fraction = 0.0 if span == 0 else (threshold - v0) / span
                level = l0 + fraction * (l1 - l0)
                below = BreachProbability(level, EXACT, (l0, l1))
                above = BreachProbability(1.0 - level, EXACT, (l0, l1))
                break
        else:                                    # pragma: no cover - ordered
            return None
    return below if lower else above


def shadow_entities(session: Any) -> Tuple[List[Entity], List[Decline]]:
    """One entity per forecast subject, carrying the medians and nothing else.

    Returns the entities and a decline for every forecast that names something
    this session cannot place -- an entity it does not hold, a record with no
    median. Those are declines rather than silent drops because a forecast that
    went nowhere is exactly what the ingest report exists to surface, and this
    is the second place it can happen.
    """
    by_entity: Dict[str, Dict[str, float]] = {}
    declines: List[Decline] = []
    for record in getattr(session.ledger, "pending", lambda: [])():
        if record.kind != "distribution" or not record.quantiles:
            continue
        if getattr(record, "source", None) is not None:
            # THE ENGINE'S OWN PROJECTIONS ARE NOT SHADOW-CHECKED HERE. This
            # run exists to put the eight axioms over a forecast SOMEBODY ELSE
            # sent; `run_projection` already judges its own against the same
            # declared lines and reports `projected_breach` for them. Running
            # both means one prediction reported twice under two names -- and
            # the reference random walk, which nobody claimed, declining
            # `no_report_probability` beside the forecast it is the yardstick
            # for.
            continue
        median = record.quantiles.get("q50")
        if median is None:
            # THE MEDIAN IS WHAT A SHADOW ENTITY IS MADE OF. A record with q05
            # and q95 alone is scoreable -- the ledger requires only those two
            # -- and still says nothing about the central case, so it cannot
            # populate a property. Declined rather than filled from the mean of
            # the interval, which would be the engine inventing a median.
            declines.append(Decline(
                "missing_property",
                {"entity": record.entity_id, "indicator": record.indicator},
                detail=("this forecast declares no q50, so there is no value to "
                        "put on a shadow entity; a median is what the axioms "
                        "read")))
            continue
        entity = session.entities.get(record.entity_id)
        if entity is None:
            declines.append(Decline(
                "precondition_unmet",
                {"entity": record.entity_id, "indicator": record.indicator},
                detail=("this session holds no such entity, so its type is "
                        "unknown and no indicator can be looked up for it")))
            continue
        by_entity.setdefault(record.entity_id, {})[str(record.indicator)] = float(median)

    shadows = []
    for entity_id, properties in sorted(by_entity.items()):
        real = session.entities[entity_id]
        carried = dict(properties)
        resolved = _bounds_for(session, real, properties)
        if resolved:
            # THE BOUND TRAVELS, THE SOURCE PROPERTY DOES NOT.
            #
            # A `{from_property:}` bound is read off the entity, and a shadow
            # entity carries medians and nothing else -- so BOUNDEDNESS ran
            # against it, found no `margin_requirement`, and declined
            # `no_threshold` on a model that declares one. Measured: the
            # breach check beside it resolved the SAME bound correctly off the
            # real entity, so one cycle produced both an answer and a refusal
            # to answer about one declaration.
            #
            # Copying the source property across would fix the lookup and
            # introduce a worse thing: an observed present value sitting on a
            # forecast entity, judged by its own axioms and reported under the
            # `forecast_` prefix as though somebody had predicted it. So what
            # travels is the RESOLVED NUMBER, written into the per-instance
            # table the resolver already consults first. The bound is a
            # contracted fact about the account and does not change because a
            # forecast was issued.
            carried[DECLARED_THRESHOLDS_KEY] = resolved
        shadows.append(Entity(
            id=entity_id, type=real.type,
            # THE SAME NAME, so a finding about a forecast points at the thing
            # a reader already knows. The prefix on the problem type is what
            # says it is about the forecast; renaming the entity too would put
            # a subject in the report that does not exist anywhere else.
            name=getattr(real, "name", entity_id),
            properties=carried,
            metadata=dict(getattr(real, "metadata", None) or {})))
    return shadows, declines


def _bounds_for(session: Any, real: Any,
                properties: Dict[str, float]) -> Dict[Any, float]:
    """The real entity's resolved bounds, keyed the way the instance table is.

    Only for the indicators this shadow actually carries: resolving the rest
    would stamp bounds onto an entity that has no value for them, which is a
    threshold nobody can reach.
    """
    from ..axiom_thresholds import THRESHOLD_FIELDS, effective_thresholds

    if session.model is None:
        return {}
    out: Dict[Any, float] = {}
    for spec in session.model.indicators.get(real.type, []) or []:
        name = spec.property_name or spec.name
        if name not in properties:
            continue
        values, _origins, _detail = effective_thresholds(real, spec)
        for field in THRESHOLD_FIELDS:
            value = values.get(field)
            if value is not None:
                out[(name, field)] = float(value)
    return out


def run_shadow_check(session: Any) -> SubEnvelope:
    """The eight axioms, over the forecast rather than over the present."""
    shadows, declines = shadow_entities(session)
    checked = {"entities": len(shadows),
               # FORECAST VALUES ONLY. The per-instance bound table rides on a
               # shadow entity as a sentinel property so the resolver can find
               # it; counting it here would inflate the denominator by one per
               # entity and claim the axioms looked at something that is not a
               # reading.
               "properties": sum(len([k for k in e.properties
                                      if k != DECLARED_THRESHOLDS_KEY])
                                 for e in shadows),
               # NEVER SUMMED WITH `checked.invariants`. This counts forecast
               # subjects; that counts axiom evaluations on observed values.
               # Two denominators, two questions.
               "invariants": 0}
    findings: List[Any] = []
    if not shadows:
        return SubEnvelope("shadow", checked, findings, declines, [])

    reasoner = getattr(session, "reasoner", None)
    if reasoner is None:
        declines.append(Decline(
            "precondition_unmet", {},
            detail="this session has no reasoner, so no axiom can be run"))
        return SubEnvelope("shadow", checked, findings, declines, [])

    # NO HISTORY. The shadow entities exist only at the horizon, so a temporal
    # axiom has nothing to read for them and declines -- which is correct and
    # is why the history is not substituted with the REAL series. Feeding the
    # observed past under a forecast present would let STABILITY and
    # HOMEOSTASIS answer about a series that is half prediction, and the answer
    # would look exactly like a real one.
    result = reasoner.detect(shadows, session.graph, _EmptyHistory())

    findings.extend(_breach_findings(session, declines))

    for problem in getattr(result, "problems", []) or []:
        problem.problem_type = f"{SHADOW_PREFIX}{problem.problem_type}"
        findings.append(problem)
    for record in getattr(result, "not_evaluated", []) or []:
        declines.append(Decline(
            record.reason.value if hasattr(record.reason, "value") else str(record.reason),
            {"entity": record.entity_id, "indicator": record.indicator,
             "axiom": record.axiom.value if hasattr(record.axiom, "value")
                      else str(record.axiom)},
            detail=getattr(record, "detail", None)))
    return SubEnvelope("shadow", checked, findings, declines, [])


def _breach_findings(session: Any, declines: List[Decline]) -> List[Any]:
    """`forecast_breach:<indicator>` where a declared line is likely crossed.

    THE PROBABILITY IS NOT THE VERDICT. Whether 0.2 is alarming is a property
    of the engagement, so the line comes from `dynamics.report_above` -- the
    same key the engine's own projection reads, rather than a second one
    meaning the same thing. Without it the probability is computed and
    reported, and no finding is invented.
    """
    from ..axiom_thresholds import effective_thresholds
    from ..interfaces import Problem
    from ..types import Axiom, Severity

    out: List[Any] = []
    for record in session.ledger.pending():
        if record.kind != "distribution" or not record.quantiles:
            continue
        if getattr(record, "source", None) is not None:
            continue            # see `shadow_entities` for why
        entity = session.entities.get(record.entity_id)
        if entity is None or session.model is None:
            continue
        spec = next((s for s in session.model.indicators.get(entity.type, [])
                     if record.indicator in (s.name, s.property_name)), None)
        if spec is None:
            continue
        # PER-INSTANCE BOUNDS INCLUDED. The line a forecast is judged against
        # is the line the entity is judged against -- reading the spec's
        # literals here would compare a forecast for one account to a limit
        # belonging to the whole book.
        values, _origins, unresolvable = effective_thresholds(entity, spec)
        thresholds = {k: v for k, v in values.items() if v is not None}
        scope = {"entity": record.entity_id, "indicator": record.indicator}
        if unresolvable is not None or not thresholds:
            # ONE REASON, two causes. A bound declared and not arrived and a
            # bound never declared both leave nothing to compare against; the
            # detail says which, and `unresolvable` carries the resolver's own
            # sentence rather than a paraphrase of it.
            declines.append(Decline(
                "no_threshold", scope,
                detail=(unresolvable or
                        "the forecast stands, and no declared line says what "
                        "would count as breaching it")))
            continue

        report_above = ((getattr(spec, "dynamics_config", None) or {})
                        .get("report_above"))
        probabilities = {}
        for name, value in thresholds.items():
            probability = breach_probability(record.quantiles, value,
                                             lower=name.startswith("lower_"))
            if probability is not None:
                probabilities[name] = probability
        if not probabilities:
            declines.append(Decline(
                "undefined_for_values", scope,
                detail="this forecast declares fewer than two quantile levels, "
                       "so no probability can be read off it"))
            continue

        evidence = {name: round(p.value, 6) for name, p in probabilities.items()}
        bounds = {name: p.bound for name, p in probabilities.items()}
        if report_above is None:
            declines.append(Decline(
                "no_report_probability", scope,
                detail=("declare `dynamics.report_above` to say which breach "
                        "probability is worth a finding"),
                evidence={"p_breach": evidence, "bound": bounds}))
            continue

        line = float(report_above)
        verdicts = {name: p.decides(line) for name, p in probabilities.items()}
        if any(v is None for v in verdicts.values()):
            # THE CASE THAT MAKES THE BOUND WORTH CARRYING. *At most 0.05*
            # settles a line of 0.1 and settles nothing at 0.01, and reporting
            # *no breach* there would be a clean answer to a question this
            # forecast cannot answer.
            undecided = sorted(n for n, v in verdicts.items() if v is None)
            declines.append(Decline(
                "tail_not_declared", scope,
                detail=(f"the reporting line {line:g} falls in the tail this "
                        f"forecast did not declare, for {', '.join(undecided)}; "
                        f"send more quantile levels or raise `report_above`"),
                evidence={"p_breach": evidence, "bound": bounds}))
            continue
        crossed = sorted(n for n, v in verdicts.items() if v)
        if crossed:
            worst = max(crossed, key=lambda n: probabilities[n].value)
            out.append(Problem.from_entity(
                entity=entity,
                # PREFIXED AT BIRTH. The loop below prefixes what the
                # reasoner returned; these are made here, and the first
                # version reached the envelope as a bare `breach:` -- the one
                # finding in this sub-envelope that did not say it was about a
                # forecast, which is the confusion the prefix exists to stop.
                problem_type=f"{SHADOW_PREFIX}breach:{record.indicator}",
                severity=(Severity.HIGH if worst.endswith("critical")
                          else Severity.MEDIUM),
                reason=(f"{record.indicator} is forecast to breach its declared "
                        f"{worst} with probability "
                        f"{probabilities[worst].value:.2f}"),
                axiom=Axiom.BOUNDEDNESS,
                evidence={"p_breach": evidence, "bound": bounds,
                          "report_above": line, "model_id": record.model_id,
                          "horizon_s": record.horizon_s},
            ))
    return out


class _EmptyHistory(ObservationHistory):
    """A history with nothing in it, for a moment that has not arrived.

    Not `None`: the reasoner and its checkers call into whatever they are
    given, and a `None` would raise where the honest answer is *no
    observations*. A temporal axiom asked about the future should decline for
    want of samples, and that is what this produces.

    SUBCLASSES THE ABC rather than duck-typing it. The first version was a
    stub with the two methods I happened to think of, and the reasoner called
    a third on the first run -- writing methods until the exceptions stop is
    how a stub ends up silently missing the one that matters. Inheriting means
    a method added to the interface arrives here as an abstract-method error at
    construction, not as an AttributeError in the middle of a check.
    """

    def add(self, *args, **kwargs) -> None:
        raise RuntimeError(
            "the shadow history is read-only; writing an observation of a "
            "forecast would put a prediction into the record of what happened")

    def get_values(self, *args, **kwargs):
        return []

    def get_states(self, *args, **kwargs):
        return []

    def get_observations(self, *args, **kwargs):
        return []

    def get_observation_count(self, *args, **kwargs) -> int:
        return 0

    def clear_entity(self, *args, **kwargs) -> None:
        return None
