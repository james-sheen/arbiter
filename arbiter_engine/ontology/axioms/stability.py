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

from ...clock import now_utc
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

        # a series that never moves, where the model said it should.
        # Reported from outside as issue #3: a frozen sensor and a live one
        # returned byte-identical envelopes, because OSCILLATION is what this
        # axiom measures and a flat line oscillates least of all. The check
        # that reads the series was the one place a reader would look for
        # this, which is why it lives here rather than in a ninth axiom.
        frozen = self._check_frozen_series(
            entity, indicator, history, window, window_size)
        problems.extend(frozen)
        declines.extend(getattr(frozen, "not_evaluated", ()))

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

    def _check_frozen_series(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        history: ObservationHistory,
        window: timedelta,
        window_size: int,
    ) -> CheckOutcome:
        """A live measurement that has stopped moving.

        Runs ONLY where the model declared `expect_variation: true`. Whether a
        constant series is a fault is a domain question and the checker is not
        entitled to an opinion: a CPU temperature that never moves is broken,
        and a setpoint, a replica count or a switched-off pump are correctly
        flat. Undeclared means no check, so nothing that worked before changes.

        The AXIOMS READING THE VALUE ARE NOT SUPPRESSED, deliberately. It is
        tempting to decline BOUNDEDNESS here on the grounds that judging a dead
        number is meaningless, and it costs more than it buys: a sensor frozen
        ABOVE its critical threshold still deserves the finding it currently
        produces, and suppressing it would trade a vacuous pass for a missing
        alarm. The frozen finding tells the operator the input is dead; they
        can discount the other verdicts themselves, which is the division of
        labour the envelope exists for.
        """
        problems: List[Problem] = []
        if indicator.expect_variation is not True:
            return CheckOutcome(problems)
        if indicator.indicator_type.value != 'numeric':
            return CheckOutcome(problems)

        values = [v for _, v in history.get_values(
            entity.id, indicator.property_name, window)]

        if len(values) < window_size:
            # Two identical readings are a coincidence, so there IS a floor,
            # and it is the same one the oscillation arm uses -- a second,
            # quieter threshold for the same axiom is how a number ends up true
            # in one arm and wrong in the other.
            #
            # It returns rather than declining, and that is the correction.
            # Declining here emitted a SECOND not_evaluated record for one
            # (axiom, entity, indicator) evaluation, because the oscillation arm
            # has already declined INSUFFICIENT_SAMPLES on the same starved
            # input. Two records for one evaluation breaks the accounting the
            # envelope rests on -- declines exceeded `evaluations_attempted`,
            # and the denominator is the whole reason that leg exists. Caught by
            # a test asserting exactly that invariant on the shipped
            # example, not by this arm's own tests.
            return CheckOutcome(problems)

        if len(set(values)) > 1:
            return CheckOutcome(problems)

        # BOTH counts when they differ, following the convention that an internal ruling set
        # for the same reason: sixty samples at one-minute spacing span exactly
        # a one-hour window, so the oldest sits on the boundary and a reader who
        # supplied sixty is otherwise told fifty-nine with no explanation.
        total = history.get_observation_count(entity.id, indicator.property_name)
        seen = (f"{len(values)} of {total} observations" if total != len(values)
                else f"{len(values)} observations")

        problems.append(Problem.from_entity(
            entity=entity,
            problem_type=f'frozen_series:{indicator.name}',
            severity=Severity.HIGH,
            reason=(f"{indicator.name} has not changed across {seen} in "
                    f"window; the model declares it should vary, so the "
                    f"reading is no longer a measurement"),
            axiom=Axiom.STABILITY,
            source_layer=DetectionLayer.ONTOLOGY,
            evidence={
                'indicator': indicator.name,
                'value': values[0],
                'observations': len(values),
                'total_observations': total,
                'window_seconds': window.total_seconds(),
            },
            confidence=1.0,
        ))
        return CheckOutcome(problems)

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

        # the FULL window, not `recent_values`.
        #
        # The period-2 arm above deliberately truncates to `window_size`
        # samples, because its question is about the last few readings. A
        # slow-period detector handed the same ten samples sees at most one
        # cycle of a period-8 signal, counts two or three crossings, and stays
        # silent on exactly the series it exists to catch. Measured that way
        # first: the arm ran, on the right data shape, and could not have fired
        # for any input, which is the failure mode a check that never refuses
        # anything produces.
        problems.extend(self._check_slow_oscillation(
            entity, indicator, values))

        return problems

    def _check_slow_oscillation(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        recent_values: list,
    ) -> List[Problem]:
        """hunting on a period the arm above cannot see.

        The detector above is period-2 BY CONSTRUCTION: it asks whether each
        value is close to the one two back and far from the one before. A
        controller hunting on a four-, six- or eight-sample period scores
        exactly zero there, so the series reads as maximally stable. That is a
        detector correctly answering the question it was built to answer, and
        the project's own analysis says so while calling slow hunting genuinely
        pathological.

        **Zero-crossings about the mean rather than an FFT.** numpy is already a
        dependency so the transform was available, and the count is the better
        instrument here for a reason that is not about accuracy: this engine's
        product is evidence a reader can check. `crossed its mean six times in
        forty samples, so the period is about thirteen` is a sentence an
        operator can verify against their own graph. A dominant bin in a
        periodogram is not, and it brings windowing and leakage questions that
        would need their own parameters to answer.

        **Opt-in.** Whether a slow cycle is a fault is a domain question — a
        day/night thermal swing, a duty-cycled compressor and a batch process
        are all correctly periodic — so this runs only where the model declares
        it, the same ruling `expect_variation` got.
        """
        problems: List[Problem] = []
        config = getattr(indicator, "stability_config", None)
        if not isinstance(config, dict) or not config.get("detect_slow_oscillation"):
            return problems

        values = [float(v) for _, v in recent_values]
        if len(values) < 6:
            # A period this arm can report needs at least a couple of cycles;
            # below six samples any crossing count is as consistent with noise
            # as with a cycle. Returns rather than declining, for the reason
            # `_check_frozen_series` records: the oscillation arm above has
            # already declined on a starved input, and two records for one
            # evaluation breaks the denominator the envelope rests on.
            return problems

        mean = sum(values) / len(values)
        scale = max(abs(v) for v in values) or 1.0
        # Relative, so the same declaration works for a temperature in Kelvin
        # and a ratio in [0, 1] -- the reasoning that put a relative
        # slope minimum in BOUNDEDNESS.
        min_amplitude = float(config.get("min_amplitude", 0.05))
        # Half the amplitude gate, so a swing that qualifies cannot be split
        # into crossings that individually do not. A separate parameter here
        # would be a second number meaning the same thing.
        dead_band = (min_amplitude / 2) * scale

        amplitude = (max(values) - min(values)) / scale
        if amplitude < min_amplitude:
            return problems

        crossings = 0
        side = 0
        for value in values:
            offset = value - mean
            if abs(offset) < dead_band:
                continue          # inside the noise band; not a crossing
            now = 1 if offset > 0 else -1
            if side and now != side:
                crossings += 1
            side = now

        min_crossings = int(config.get("min_crossings", 4))
        if crossings < min_crossings:
            return problems

        # Two crossings per cycle, so the period in samples is 2n/crossings.
        period_samples = 2 * len(values) / crossings

        # The arm above owns period 2. Reporting here as well would give one
        # signal two findings, and the boundary is the honest one rather than a
        # suppression: below three samples per period this IS the fast case.
        if period_samples < 3:
            return problems

        problems.append(Problem.from_entity(
            entity=entity,
            problem_type=f'slow_oscillation:{indicator.name}',
            severity=Severity.MEDIUM,
            reason=(f"{indicator.name} is cycling on a period of about "
                    f"{period_samples:.0f} samples, which the period-2 "
                    f"oscillation check cannot see"),
            axiom=Axiom.STABILITY,
            source_layer=DetectionLayer.ONTOLOGY,
            evidence={
                'indicator': indicator.name,
                'mean_crossings': crossings,
                'estimated_period_samples': period_samples,
                'relative_amplitude': amplitude,
                'min_amplitude': min_amplitude,
                'min_crossings': min_crossings,
                'observations': len(values),
                'mean': mean,
            },
            confidence=1.0,
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
            duration = now_utc() - state_start
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
