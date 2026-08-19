"""
BOUNDEDNESS Axiom Checker.

BOUNDEDNESS: System operates within limits.

Detects:
- Threshold violations (immediate)
- Trending toward limits (predictive)
- Capacity exhaustion

Mathematical formula for trend:
    slope = Σ(tᵢ - t̄)(Pᵢ - P̄) / Σ(tᵢ - t̄)²
    trend_severity = |slope| × R² / Var(P)

Parameters:
- trend_min_r2 = 0.7: Minimum R² for significant trend
- exhaustion_warning = 0.8: 80% of limit
- exhaustion_critical = 0.95: 95% of limit
"""

import logging
from datetime import timedelta
from typing import Any, List, Optional

from ...interfaces import (
    Entity,
    Problem,
    RelationshipGraph,
    ObservationHistory,
    IndicatorSpec,
    calculate_trend,
    apply_property_confidence,
    CheckOutcome,
    absent_current_value,
)
from ...types import (
    Axiom, Severity, AxiomParameters, DetectionLayer, NotEvaluatedReason,
)
# — call resolve_axiom_threshold at calibration-relevant
# read-sites so per-sample entity-property overrides win over
# global AxiomParameters fallback during v2 perturbation runs. Non-
# calibration reads (trend_min_r2, time_to_critical_hours) stay as
# global params — those are operator-tuning knobs, not per-axiom-per-
# entity calibration thresholds.
from ...axiom_thresholds import (
    resolve_axiom_threshold,
)

logger = logging.getLogger(__name__)


def _contradictory_band(
    warning: Optional[float],
    critical: Optional[float],
    lower_warning: Optional[float],
    lower_critical: Optional[float],
) -> Optional[str]:
    """describe the contradiction in a band, or return None.

    A band is contradictory when no value can satisfy it. Three ways to write
    one, and they are checked separately because the remedies differ:

    *a floor at or above its own ceiling — every reading breaches something;
    *a critical floor above the warning floor — the warning is unreachable,
      since anything low enough to warn is already critical;
    *a critical ceiling below the warning ceiling — the mirror of the above,
      and the one case that was already declarable before the floor existed.

    That third check is deliberately included even though it predates this
    change and nothing asked for it. Adding the floor's version and not the
    ceiling's would leave the engine refusing one spelling of a mistake and
    silently accepting its mirror, which is a worse contract than refusing
    neither: an author who learns that the engine validates bands would
    reasonably conclude an accepted band is coherent.

    Returns the sentence rather than a bool so the decline can say WHICH
    contradiction, with the numbers. `is not None` throughout, so a threshold
    of 0.0 is a real bound.
    """
    if lower_warning is not None and warning is not None and lower_warning >= warning:
        return (f"lower_warning ({lower_warning:g}) is at or above warning "
                f"({warning:g}), so every reading breaches one of them; a "
                f"band needs its floor below its ceiling")
    if (lower_critical is not None and critical is not None
            and lower_critical >= critical):
        return (f"lower_critical ({lower_critical:g}) is at or above critical "
                f"({critical:g}), so every reading breaches one of them; a "
                f"band needs its floor below its ceiling")
    if (lower_critical is not None and lower_warning is not None
            and lower_critical > lower_warning):
        return (f"lower_critical ({lower_critical:g}) is above lower_warning "
                f"({lower_warning:g}), so the warning floor can never be "
                f"reported — anything low enough to warn is already critical")
    if warning is not None and critical is not None and critical < warning:
        return (f"critical ({critical:g}) is below warning ({warning:g}), so "
                f"the warning can never be reported — anything high enough to "
                f"warn is already critical")
    return None


class BoundednessChecker:
    """
    Check BOUNDEDNESS axiom for entities.

    BOUNDEDNESS can work from cold start (threshold checks)
    but requires history for trend detection.
    Minimum observations for trend: 5

    optional ``overlay: RuntimeYAMLOverlay`` lets the
    checker consult approved threshold mutations (sub-
    decision (B) per-domain overlay file). When provided, the checker
    resolves the effective warning/critical thresholds via
    ``overlay.get_threshold(entity_domain, indicator.name,
    threshold_type, default=indicator.<type>_threshold)``. When None
    or no override is set, behavior is unchanged from previously.
    The entity's ``metadata['domain_id']`` is consulted for the
    domain key; if absent, the overlay is bypassed for that entity.
    """

    def __init__(
        self,
        params: Optional[AxiomParameters] = None,
        overlay: Optional[Any] = None,
    ):
        self.params = params or AxiomParameters()
        self.overlay = overlay

    def _effective_threshold(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        threshold_type: str,
        default: Optional[float],
    ) -> Optional[float]:
        """return overlay-resolved threshold or default.

        Falls back to ``default`` if (a) no overlay is wired,
        (b) entity has no ``metadata['domain_id']``, or (c) the
        overlay has no override for this (domain, indicator,
        threshold_type) triple.
        """
        if self.overlay is None:
            return default
        domain = entity.metadata.get('domain_id') if entity.metadata else None
        if not domain:
            return default
        return self.overlay.get_threshold(
            domain, indicator.name, threshold_type, default
        )

    def check(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        graph: RelationshipGraph,
        history: ObservationHistory
    ) -> List[Problem]:
        """
        Check BOUNDEDNESS for an entity/indicator.

        1. Check immediate threshold violations
        2. Check trend toward limits
        3. Estimate time to critical
        """
        problems = []

        # these three exits used to `return problems`, an empty list
        # that the envelope reports as a clean pass. Reported from outside as
        # issue #1: with no property, BOUNDEDNESS counted toward
        # `checked.invariants` and emitted neither a finding nor a decline, so
        # a vacuous pass was byte-identical to a healthy one. That is the exact
        # failure the three-part envelope exists to prevent.
        #
        # Note the ordering: the missing-property decline must come BEFORE the
        # NO_THRESHOLD decline at the foot of this method, which was
        # unreachable for a missing property precisely because of the bare
        # return here.
        if indicator.indicator_type.value != 'numeric':
            return CheckOutcome(problems).declined(
                Axiom.BOUNDEDNESS, entity, indicator.name,
                NotEvaluatedReason.WRONG_INDICATOR_TYPE,
                detail=(
                    f"BOUNDEDNESS evaluates numeric indicators; this one is "
                    f"{indicator.indicator_type.value}"),
            )

        current = entity.get_property(indicator.property_name)
        if current is None:
            # which absence, not just that there is one.
            reason, clause, seen = absent_current_value(entity, indicator, history)
            return CheckOutcome(problems).declined(
                Axiom.BOUNDEDNESS, entity, indicator.name, reason,
                detail=(
                    f"{clause}; "
                    f"BOUNDEDNESS compares a current value against a threshold"),
                observations_count=seen or None,
            )

        try:
            current = float(current)
        except (TypeError, ValueError):
            return CheckOutcome(problems).declined(
                Axiom.BOUNDEDNESS, entity, indicator.name,
                NotEvaluatedReason.WRONG_INDICATOR_TYPE,
                detail=(
                    f"property {indicator.property_name} is declared numeric "
                    f"but its value is not: {current!r}"),
            )

        #: resolve effective thresholds through the optional
        # RuntimeYAMLOverlay. When no overlay is wired or no override
        # exists, the calls return the original IndicatorSpec values.
        critical_threshold = self._effective_threshold(
            entity, indicator, 'critical', indicator.critical_threshold
        )
        warning_threshold = self._effective_threshold(
            entity, indicator, 'warning', indicator.warning_threshold
        )
        # the floor pair goes through the same overlay resolution as
        # the ceiling pair. Skipping it would give a model two thresholds an
        # operator can retune at runtime and two they cannot, with nothing
        # saying which is which.
        lower_critical = self._effective_threshold(
            entity, indicator, 'lower_critical',
            indicator.lower_critical_threshold
        )
        lower_warning = self._effective_threshold(
            entity, indicator, 'lower_warning',
            indicator.lower_warning_threshold
        )

        # a band whose floor sits at or above its ceiling admits no
        # healthy value, so EVERY reading fires. That is a model defect and the
        # engine says so once, rather than emitting a finding per cycle forever
        # and leaving the author to work out that the data is fine and the
        # declaration is not. Declined rather than raised, for the reason the
        # loader gives for every other malformed field: one bad indicator must
        # cost that indicator and not the pass.
        contradiction = _contradictory_band(
            warning_threshold, critical_threshold, lower_warning, lower_critical)
        if contradiction is not None:
            return CheckOutcome(problems).declined(
                Axiom.BOUNDEDNESS, entity, indicator.name,
                NotEvaluatedReason.MISSING_CONFIG,
                detail=contradiction,
            )

        # 1. Check immediate threshold violations
        if critical_threshold is not None:
            if current >= critical_threshold:
                problems.append(Problem.from_entity(
                    entity=entity,
                    problem_type=f'threshold_exceeded:{indicator.name}',
                    severity=Severity.CRITICAL,
                    reason=f"{indicator.name} exceeds critical threshold",
                    axiom=Axiom.BOUNDEDNESS,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'indicator': indicator.name,
                        'value': current,
                        'threshold': critical_threshold,
                        'threshold_type': 'critical',
                        'bound': 'upper',   # see the warning arm below
                    },
                    confidence=1.0,
                ))
                # early-exit short-circuits the warning_threshold +
                # trend checks (don't double-fire on same threshold breach)
                # but must STILL flow through ``apply_property_confidence``
                # so stale-property modulation applies — same return-shape
                # as the warning + trend + end-of-function paths. Pre-fix
                # this branch returned ``problems`` raw, leaving CRITICAL
                # severity un-modulated for stale properties while
                # warning/trend problems were correctly decayed. Return-
                # shape drift archetype — sibling to.
                return apply_property_confidence(
                    entity, indicator.property_name, problems
                )

        if warning_threshold is not None:
            if current >= warning_threshold:
                problems.append(Problem.from_entity(
                    entity=entity,
                    problem_type=f'threshold_warning:{indicator.name}',
                    severity=Severity.WARNING,
                    reason=f"{indicator.name} exceeds warning threshold",
                    axiom=Axiom.BOUNDEDNESS,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'indicator': indicator.name,
                        'value': current,
                        'threshold': warning_threshold,
                        'threshold_type': 'warning',
                        # stated on every finding, including the two
                        # that predate the floor. A consumer switching on
                        # `threshold_type` alone has to know which names mean
                        # which way; one field that says so directly is what
                        # lets a report layer render the sentence without a
                        # lookup table of ours.
                        'bound': 'upper',
                    },
                    confidence=1.0,
                ))

        # 1b. the same comparison, pointing down.
        #
        # Deliberately AFTER the two arms above and without their early return.
        # The upper-critical branch returns early so one breach does not
        # double-fire as warning and critical; a floor breach and a ceiling
        # breach on the same reading is not a double-fire, it is impossible —
        # `_contradictory_band` has already refused the only declaration that
        # could produce it. So the ordering here costs nothing and keeps the
        # released upper-bound path byte-identical.
        #
        # `<=` mirrors the `>=` above. A value exactly ON the floor is a breach
        # for the same reason a value exactly on the ceiling is: the threshold
        # names the edge of acceptable, not the first unacceptable value.
        if lower_critical is not None and current <= lower_critical:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'below_critical_threshold:{indicator.name}',
                severity=Severity.CRITICAL,
                reason=f"{indicator.name} is below critical threshold",
                axiom=Axiom.BOUNDEDNESS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'indicator': indicator.name,
                    'value': current,
                    'threshold': lower_critical,
                    'threshold_type': 'lower_critical',
                    'bound': 'lower',
                },
                confidence=1.0,
            ))
            return apply_property_confidence(
                entity, indicator.property_name, problems
            )

        if lower_warning is not None and current <= lower_warning:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'below_warning_threshold:{indicator.name}',
                severity=Severity.WARNING,
                reason=f"{indicator.name} is below warning threshold",
                axiom=Axiom.BOUNDEDNESS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'indicator': indicator.name,
                    'value': current,
                    'threshold': lower_warning,
                    'threshold_type': 'lower_warning',
                    'bound': 'lower',
                },
                confidence=1.0,
            ))

        # 2. Check trend toward limits (requires history)
        window = indicator.time_window or timedelta(hours=1)
        values = history.get_values(entity.id, indicator.property_name, window)

        if len(values) >= 5:
            trend = calculate_trend(values)
            slope = trend['slope']
            r2 = trend['r2']

            # Only consider significant positive trends
            # Use threshold to prevent near-zero slopes from
            # producing astronomically large time-to-critical estimates
            # Use relative slope minimum based on current value
            # so large-value domains (e.g., temperatures in Kelvin) aren't
            # over-sensitive to tiny absolute slopes.
            slope_minimum = max(1e-6, abs(current) * 1e-4) if current else 1e-6
            if slope > slope_minimum and r2 >= self.params.boundedness_trend_min_r2:
                # Estimate time to critical — uses the same
                # effective threshold the immediate-violation branch
                # consulted above, so trend-to-limit projection respects
                # overlay overrides.
                if critical_threshold and current < critical_threshold:
                    time_to_critical = (critical_threshold - current) / slope
                    threshold_hours = self.params.boundedness_time_to_critical_hours * 3600

                    if time_to_critical < threshold_hours:
                        problems.append(Problem.from_entity(
                            entity=entity,
                            problem_type=f'approaching_limit:{indicator.name}',
                            severity=Severity.HIGH,
                            reason=f"{indicator.name} trending toward critical limit",
                            axiom=Axiom.BOUNDEDNESS,
                            source_layer=DetectionLayer.ONTOLOGY,
                            evidence={
                                'indicator': indicator.name,
                                'value': current,
                                'critical_threshold': critical_threshold,
                                'slope': slope,
                                'r2': r2,
                                'time_to_critical_seconds': time_to_critical,
                                'observations': len(values),
                            },
                            confidence=r2,
                            recommended_action=f"Expected to reach critical in {time_to_critical/60:.0f} minutes",
                        ))

            # the projection arm, pointing down.
            #
            # Shipping the floor with only its threshold arm would give the two
            # directions unequal capability: a rising quantity gets warned about
            # before it arrives and a falling one only on arrival. That
            # asymmetry is invisible from any call site and would be discovered
            # the way this project keeps discovering them — by a consumer whose
            # fan died between two clean reports.
            #
            # `current > lower_critical` rather than `>=`, matching the upper
            # arm's `current < critical_threshold`: a value already at the floor
            # has fired the threshold arm above and returned, so projecting
            # toward a limit it has reached would be a second finding for one
            # breach.
            elif slope < -slope_minimum and r2 >= self.params.boundedness_trend_min_r2:
                if lower_critical is not None and current > lower_critical:
                    time_to_critical = (current - lower_critical) / (-slope)
                    threshold_hours = self.params.boundedness_time_to_critical_hours * 3600

                    if time_to_critical < threshold_hours:
                        problems.append(Problem.from_entity(
                            entity=entity,
                            problem_type=f'approaching_floor:{indicator.name}',
                            severity=Severity.HIGH,
                            reason=f"{indicator.name} trending toward critical floor",
                            axiom=Axiom.BOUNDEDNESS,
                            source_layer=DetectionLayer.ONTOLOGY,
                            evidence={
                                'indicator': indicator.name,
                                'value': current,
                                'lower_critical_threshold': lower_critical,
                                'slope': slope,
                                'r2': r2,
                                'time_to_critical_seconds': time_to_critical,
                                'observations': len(values),
                                'bound': 'lower',
                            },
                            confidence=r2,
                            recommended_action=(
                                f"Expected to reach the critical floor in "
                                f"{time_to_critical/60:.0f} minutes"),
                        ))

        # fire counting moved to the dispatch boundary
        # (reasoner._record_fires), so all eight axioms are counted
        # uniformly rather than three by hand.
        result = apply_property_confidence(
            entity, indicator.property_name, problems)

        # BOUNDEDNESS has two arms — threshold comparison and trend
        # projection — and both can be skipped, so this return can be reached
        # having evaluated nothing.
        #
        # An internal ruling removed an `and len(values) < 5` clause from this condition.
        # It read as though history were the missing ingredient, but the trend
        # arm projects toward `critical_threshold` and is guarded on it, so an
        # indicator with neither threshold is dead at EVERY history length.
        # The clause therefore silenced the decline from the fifth observation
        # onward — which is the normal operating state — and eighteen
        # declarations across the shipped domains sat in exactly that state.
        # Reported from outside as issue #6, against a fan whose real bound is
        # a floor the vocabulary cannot express.
        #
        # `required_count` is deliberately NOT passed. It would assert that
        # five observations make this evaluable, which is false, and telling a
        # caller to supply what cannot help is the defect that an internal ruling closed.
        #
        # The threshold tests are `is not None` rather than truthiness, so a
        # legitimate threshold of 0.0 is honoured; that is why this condition
        # mirrors them exactly instead of using `not critical_threshold`.
        #
        # An internal ruling widened this from two thresholds to four. It had to be
        # widened in the same change that added them: an indicator declaring
        # only a floor would otherwise have fired a finding AND been declined
        # as having no threshold in the same pass — the envelope contradicting
        # itself about the evaluation it had just performed. This is the shape
        # the project files under enumeration blindness, and it is the reason a
        # check written against a closed set has to be revisited by whoever
        # opens the set.
        if (critical_threshold is None and warning_threshold is None
                and lower_critical is None and lower_warning is None):
            return CheckOutcome(result).declined(
                Axiom.BOUNDEDNESS, entity, indicator.name,
                NotEvaluatedReason.NO_THRESHOLD,
                detail=(
                    "no threshold configured; the trend arm projects toward "
                    "the critical threshold, so more observations cannot make "
                    "this indicator evaluable — declare `warning`/`critical` "
                    "for a ceiling, `lower_warning`/`lower_critical` for a "
                    "floor, or drop BOUNDEDNESS from its `axioms:` list"),
                observations_count=len(values),
            )
        return result

    def check_capacity_ratio(
        self,
        entity: Entity,
        used_property: str,
        limit_property: str
    ) -> List[Problem]:
        """
        Check capacity ratio (used/limit).

        Useful for resources like CPU, memory, disk.
        """
        problems = []

        used = entity.get_property(used_property)
        limit = entity.get_property(limit_property)

        if used is None or limit is None:
            return problems

        try:
            used = float(used)
            limit = float(limit)
        except (TypeError, ValueError):
            return problems

        if limit <= 0:
            return problems

        ratio = used / limit

        # resolve per-entity-axiom override (sentinel key)
        # before falling back to global AxiomParameters. ``used_property``
        # serves as the indicator name in the (entity, indicator, axiom)
        # lookup tuple. When no override is present, behavior is identical
        # to previously — fallback unwrapped is the global params scalar.
        warn_ratio, critical_ratio = resolve_axiom_threshold(
            entity, used_property, "BOUNDEDNESS",
            fallback=(
                self.params.boundedness_warning_ratio,
                self.params.boundedness_critical_ratio,
            ),
            bound="both",
        )

        if ratio >= critical_ratio:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type='capacity_exhausted',
                severity=Severity.CRITICAL,
                reason=f"Capacity near exhaustion ({ratio*100:.1f}%)",
                axiom=Axiom.BOUNDEDNESS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'used': used,
                    'limit': limit,
                    'ratio': ratio,
                    'threshold': critical_ratio,
                },
                confidence=1.0,
            ))
        elif ratio >= warn_ratio:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type='capacity_warning',
                severity=Severity.WARNING,
                reason=f"Capacity at {ratio*100:.1f}%",
                axiom=Axiom.BOUNDEDNESS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'used': used,
                    'limit': limit,
                    'ratio': ratio,
                    'threshold': warn_ratio,
                },
                confidence=1.0,
            ))

        return problems
