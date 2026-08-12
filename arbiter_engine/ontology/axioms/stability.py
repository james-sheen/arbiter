"""
STABILITY Axiom Checker.

STABILITY: System tends toward equilibrium.

Detects:
- Oscillation (state bouncing back and forth)
- State instability (rapid changes)
- Failure to converge

Mathematical formula:
    oscillation(t, w) = (1/(w-2)) *Σ[i=t-w+2 to t] 𝟙[d(Sᵢ, Sᵢ₋₂) < ε ∧ d(Sᵢ, Sᵢ₋₁) > δ]

Parameters:
- w (window_size) = 10: Number of observations
- ε (epsilon) = 0.1: States 2 apart must be similar (<10% different)
- δ (delta) = 0.3: Consecutive states must be different (>30% different)
"""

import logging
from datetime import timedelta
from typing import List, Optional

from ...interfaces import (
    Entity,
    Problem,
    RelationshipGraph,
    ObservationHistory,
    IndicatorSpec,
    state_distance,
    apply_property_confidence,
    CheckOutcome,
)
from ...types import (
    Axiom, Severity, AxiomParameters, DetectionLayer, NotEvaluatedReason,
)
# — call resolve_axiom_threshold at oscillation_threshold
# read-sites (the firing gate). Per sentinel override > global params
# fallback. epsilon/delta/window_size kept as global — they are
# distance-metric / sample-count parameters, not the per-axiom firing
# threshold. Same carve-out shape as MONOTONICITY's reversal_threshold.
from ...axiom_thresholds import (
    resolve_axiom_threshold,
)

logger = logging.getLogger(__name__)


class StabilityChecker:
    """
    Check STABILITY axiom for entities.

    STABILITY requires historical data to detect oscillation patterns.
    Minimum observations: 10

    fires are counted at the reasoner's dispatch boundary, so
    this checker carries no instrumentation of its own.
    """

    def __init__(self, params: Optional[AxiomParameters] = None):
        self.params = params or AxiomParameters()

    def check(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        graph: RelationshipGraph,
        history: ObservationHistory
    ) -> List[Problem]:
        """
        Check STABILITY for an entity/indicator.

        For state indicators: Check oscillation between states
        For numeric indicators: Check oscillation around a value
        """
        problems = []

        # Only check state or numeric indicators
        if indicator.indicator_type.value not in ('state', 'numeric'):
            return CheckOutcome(problems).declined(
                Axiom.STABILITY, entity, indicator.name,
                NotEvaluatedReason.WRONG_INDICATOR_TYPE,
                detail=(
                    f"STABILITY evaluates state or numeric indicators; this "
                    f"one is {indicator.indicator_type.value}"),
            )

        # the helper seam. Both branches below decline internally
        # when there is too little history, and `extend` keeps their problems
        # while discarding the records. Collected explicitly here, the same
        # way the reasoner collects from `check_axiom`.
        declines = []

        # Get historical states/values
        window = indicator.time_window or timedelta(hours=1)
        window_size = self.params.stability_window_size

        if indicator.indicator_type.value == 'state':
            outcome = self._check_state_stability(
                entity, indicator, history, window, window_size)
        else:
            outcome = self._check_numeric_stability(
                entity, indicator, history, window, window_size)
        problems.extend(outcome)
        declines.extend(getattr(outcome, "not_evaluated", ()))

        # Check transient state timeout
        if indicator.indicator_type.value == 'state' and indicator.transient_states:
            problems.extend(self._check_transient_timeout(
                entity, indicator, history
            ))

        # fire counting moved to the dispatch boundary
        # (reasoner._record_fires), so all eight axioms are counted
        # uniformly rather than three by hand.
        confirmed = apply_property_confidence(
            entity, indicator.property_name, problems)
        # carry the helper's declines out. `apply_property_confidence`
        # returns a plain list, so rebuilding the outcome here is what stops the
        # records dying at the last step.
        return CheckOutcome(confirmed, declines)

    def _check_state_stability(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        history: ObservationHistory,
        window: timedelta,
        window_size: int
    ) -> List[Problem]:
        """Check for state oscillation."""
        problems = []

        # Get state history
        states = history.get_states(entity.id, indicator.property_name, window)
        if len(states) < window_size:
            return CheckOutcome(problems).declined(
                Axiom.STABILITY, entity, indicator.name,
                NotEvaluatedReason.INSUFFICIENT_SAMPLES,
                detail="too few state observations to detect oscillation",
                observations_count=len(states),
                required_count=window_size,
            )

        # Take the most recent window_size observations
        recent_states = states[-window_size:]

        # Calculate oscillation score
        oscillation_count = 0
        epsilon = self.params.stability_epsilon
        delta = self.params.stability_delta

        for i in range(2, len(recent_states)):
            state_current = recent_states[i][1]
            state_prev = recent_states[i-1][1]
            state_skip = recent_states[i-2][1]

            # Distance from 2 ago (should be small for oscillation)
            d_skip = state_distance(state_current, state_skip)
            # Distance from 1 ago (should be large for oscillation)
            d_consecutive = state_distance(state_current, state_prev)

            if d_skip < epsilon and d_consecutive > delta:
                oscillation_count += 1

        oscillation_score = oscillation_count / (len(recent_states) - 2)

        # resolve per-entity override for the firing-gate
        # threshold before falling back to global params. Single-bound shape
        # via bound="warn" (oscillation_threshold is a single scalar; not a
        # warn/critical pair).
        oscillation_threshold = resolve_axiom_threshold(
            entity, indicator.property_name, "STABILITY",
            fallback=self.params.stability_oscillation_threshold,
            bound="warn",
        )

        if oscillation_score > oscillation_threshold:
            # Get the oscillating states
            unique_states = list(set(s[1] for s in recent_states))

            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'stability_oscillation:{indicator.name}',
                severity=Severity.HIGH,
                reason=f"{indicator.name} oscillating between states",
                axiom=Axiom.STABILITY,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'indicator': indicator.name,
                    'oscillation_score': oscillation_score,
                    'threshold': oscillation_threshold,
                    'recent_states': [s[1] for s in recent_states[-5:]],
                    'unique_states': unique_states,
                    'observations': len(recent_states),
                },
                confidence=min(1.0, oscillation_score),
            ))

        return problems

    def _check_numeric_stability(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        history: ObservationHistory,
        window: timedelta,
        window_size: int
    ) -> List[Problem]:
        """Check for numeric oscillation."""
        problems = []

        # Get value history
        values = history.get_values(entity.id, indicator.property_name, window)
        if len(values) < window_size:
            return CheckOutcome(problems).declined(
                Axiom.STABILITY, entity, indicator.name,
                NotEvaluatedReason.INSUFFICIENT_SAMPLES,
                detail="too few observations to detect oscillation",
                observations_count=len(values),
                required_count=window_size,
            )

        # Take recent values
        recent_values = values[-window_size:]

        # Calculate oscillation (value bouncing)
        oscillation_count = 0
        epsilon = self.params.stability_epsilon
        delta = self.params.stability_delta

        for i in range(2, len(recent_values)):
            v_current = recent_values[i][1]
            v_prev = recent_values[i-1][1]
            v_skip = recent_values[i-2][1]

            # Normalize distances
            max_val = max(abs(v_current), abs(v_prev), abs(v_skip), 1)
            d_skip = abs(v_current - v_skip) / max_val
            d_consecutive = abs(v_current - v_prev) / max_val

            if d_skip < epsilon and d_consecutive > delta:
                oscillation_count += 1

        oscillation_score = oscillation_count / (len(recent_values) - 2)

        # same single-bound override-precedence as state stability.
        oscillation_threshold = resolve_axiom_threshold(
            entity, indicator.property_name, "STABILITY",
            fallback=self.params.stability_oscillation_threshold,
            bound="warn",
        )

        if oscillation_score > oscillation_threshold:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'stability_oscillation:{indicator.name}',
                severity=Severity.MEDIUM,
                reason=f"{indicator.name} oscillating",
                axiom=Axiom.STABILITY,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'indicator': indicator.name,
                    'oscillation_score': oscillation_score,
                    'threshold': oscillation_threshold,
                    'recent_values': [v[1] for v in recent_values[-5:]],
                    'observations': len(recent_values),
                },
                confidence=min(1.0, oscillation_score),
            ))

        return problems

    def _check_transient_timeout(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        history: ObservationHistory
    ) -> List[Problem]:
        """Check if entity has been in transient state too long."""
        problems = []

        current_value = entity.get_property(indicator.property_name)
        if current_value is None:
            return problems

        # Check if current state is transient
        if str(current_value) not in indicator.transient_states:
            return problems

        # Get time in state
        timeout = indicator.transient_timeout or timedelta(minutes=5)

        # Get states to find when we entered this state
        states = history.get_states(entity.id, indicator.property_name, timeout * 2)
        if not states:
            return problems

        # Find when current state started
        state_start = None
        for ts, state in reversed(states):
            if str(state) != str(current_value):
                break
            state_start = ts

        if state_start:
            from datetime import datetime
            duration = datetime.utcnow() - state_start
            if duration > timeout:
                problems.append(Problem.from_entity(
                    entity=entity,
                    problem_type=f'transient_state_timeout:{indicator.name}',
                    severity=Severity.HIGH,
                    reason=f"{indicator.name} stuck in transient state '{current_value}'",
                    axiom=Axiom.STABILITY,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'indicator': indicator.name,
                        'state': current_value,
                        'duration_seconds': duration.total_seconds(),
                        'timeout_seconds': timeout.total_seconds(),
                        'transient_states': indicator.transient_states,
                    },
                    confidence=1.0,
                ))

        return problems
