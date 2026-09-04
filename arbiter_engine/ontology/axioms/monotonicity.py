"""
MONOTONICITY Axiom Checker.

MONOTONICITY: Directional properties maintain their trend.

Detects:
- Unexpected reversals (counter decreasing when it should only increase)
- Dangerous rate of change (degradation accelerating)
- Counter reset vs genuine reversal

Mathematical formula:
    reversals(t, w) = Σ[i=1..w] 𝟙[sign(Pᵢ - Pᵢ₋₁) ≠ expected_direction]
    rate(t, w) = |median of pairwise slopes over the window| (Theil-Sen)

    the rate was |P_last - P_first| / (t_last - t_first), which
    read only the two endpoints and discarded every point between them.

Parameters:
- min_samples = 3: observations before the axiom is evaluated at all
  (the derived floor; see AXIOM_MINIMUMS)
- window_size = 20: how far back to look once it is
- reversal_threshold = 3: reversals before alert. An internal ruling made this the
  DEFAULT rather than the rule — `monotonicity: {reversal_tolerance: N}` and
  `{reset_tolerance: N}` override it per indicator. It was a global engine
  number no model could state, so a counter declared as forward-only carried a
  silent allowance of two backward moves; one rollback produced no finding and
  no decline.
- rate_warning / rate_critical: NO DEFAULT since. Undeclared, the rate
  arm declines `no_threshold` rather than judging against a number the engine
  chose; the reversal arm beside it still runs and its findings still report.
- rate_min_span_seconds: optional per-indicator floor on the time the window
  must cover before a rate is asserted; default 0, meaning off
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
    apply_property_confidence,
    CheckOutcome,
    sampling_context,
)
from ...types import (
    Axiom, Severity, AxiomParameters, DetectionLayer, NotEvaluatedReason,
)
# — call resolve_axiom_threshold at rate_warning/rate_critical
# read-sites so per-sample entity-property overrides win over global
# AxiomParameters fallback during v2 perturbation runs. Precedence chain:
# sentinel > indicator's mono_config > global params. The pre-existing
# mono_config-aware fallback is preserved as the resolver's fallback arg —
# override beats it, indicator config beats global params.
# Non-calibration reads (window_size, reversal_threshold) stay as global
# params — those are discrete-count thresholds, not per-(entity, indicator,
# axiom) calibration values.
from ...axiom_thresholds import (
    resolve_axiom_threshold,
)

logger = logging.getLogger(__name__)


#: The dataclass defaults for the two rate fields, captured once.
#:
#: a caller who constructs `AxiomParameters(monotonicity_rate_warning=
#: 100)` HAS declared a rate and is honoured; the untouched dataclass default is
#: the engine's own guess and is not. The degenerate case is a caller who passes
#: exactly the default, which reads as undeclared -- stated here rather than
#: worked around, because the model and the per-entity override are the two
#: declaring surfaces this format documents and `params=` is neither.
_RATE_PARAM_DEFAULTS = {
    "monotonicity_rate_warning": AxiomParameters().monotonicity_rate_warning,
    "monotonicity_rate_critical": AxiomParameters().monotonicity_rate_critical,
}


def _declared_param(value, field: str):
    """A params value a caller changed, or None when it is the engine's guess."""
    return None if value == _RATE_PARAM_DEFAULTS[field] else value


def _positive_int(raw, fallback: int, key: str, indicator) -> int:
    """A declared tolerance, or the default if it is unusable.

    Reported and dropped rather than coerced, the convention `_resolve_role`
    and `_resolve_expect_variation` already use in the loader. `int("2")` would
    quietly accept a string; `int(0.5)` would quietly accept a float and floor
    it to a tolerance of 0, turning every backward move into a finding on a
    model whose author wrote something they thought meant *half*.

    Zero and negatives are refused for the same reason: `reversal_tolerance: 0`
    reads as *no reversals allowed*, which is what `1` means here, and a
    counter that fires on `reversal_count >= 0` fires on every clean series
    forever. An author writing 0 has made a fencepost error, and the safe
    answer is the default plus a warning, not the reading that makes the axiom
    scream.
    """
    if raw is None:
        return fallback
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        logger.warning(
            "unusable %s %r on indicator %r — ignored, using %d; write a "
            "whole number of 1 or more",
            key, raw, getattr(indicator, "name", "?"), fallback)
        return fallback
    return raw


def _robust_slope(samples) -> Optional[float]:
    """Theil-Sen slope in units per second: the median of pairwise slopes.

    Returns ``None`` when no slope can be determined — never ``0.0``,
    because zero is a real answer meaning "flat" and would be read as one.

    WHY NOT LEAST SQUARES, which was the first attempt. A least-squares fit
    does use the interior points, but in a linear fit the *endpoints carry the
    highest leverage*, so the very outlier this is meant to survive is the one
    it weights most. Measured on nineteen flat readings followed by one
    corrupted spike: the endpoint difference gives 2.58/s and the least-squares
    fit 0.70/s — a real improvement, and still over a 0.5 critical threshold.
    It would still have fired.

    The median of pairwise slopes has a breakdown point near 29 percent: on
    that same series 171 of the 190 pairs are flat, so the median is flat and
    the spike is ignored outright. On a clean ramp every pair carries the same
    slope, so the answer is identical to both older forms — which is what keeps
    well-behaved data unaffected.

    O(n^2) in the window, which is 190 pairs at the default window of 20.
    """
    n = len(samples)
    if n < 2:
        return None
    base = samples[0][0]
    pts = [((ts - base).total_seconds(), float(val)) for ts, val in samples]

    slopes = []
    for i in range(n):
        xi, yi = pts[i]
        for j in range(i + 1, n):
            xj, yj = pts[j]
            dx = xj - xi
            if dx != 0:
                slopes.append((yj - yi) / dx)
    if not slopes:  # every sample carries the same timestamp
        return None

    slopes.sort()
    mid = len(slopes) // 2
    if len(slopes) % 2:
        return slopes[mid]
    return (slopes[mid - 1] + slopes[mid]) / 2.0


class MonotonicityChecker:
    """
    Check MONOTONICITY axiom for entities.

    MONOTONICITY requires historical data to detect trend violations.
    Minimum observations: 3 (was stated as 20, which was the
    lookback window being mistaken for the evaluation floor).
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
        Check MONOTONICITY for an entity/indicator.

        Uses indicator config for direction:
          - expected_direction: 'increasing' or 'decreasing'
          - allow_reset: whether counter resets are legitimate
          - rate_warning: rate threshold for warning
          - rate_critical: rate threshold for critical
          - reversal_tolerance: backward moves allowed before firing (default 3). Declare 1 to fire on a single rollback.
          - reset_tolerance: excused resets allowed before the storm arm fires
            (default 3)
        """
        problems = []

        # this was a bare `return problems`. An empty list, no finding
        # and no decline, from a checker the reasoner had already DISPATCHED: the
        # cell counts toward `checked.invariants` and produces nothing, so the
        # envelope reports coverage the run did not have. The outside method
        # document named this state RETIRED and ranked it above misattribution,
        # correctly — silence costs a detection and misattribution spends trust,
        # but retirement produces ASSURANCE, and assurance is the only one of the
        # three that stops somebody looking.
        #
        # Found by answering that document's own open question, *which sites can
        # retire a check*. Measured across all eight axioms declared on an
        # indicator whose type they cannot reason about: seven report something —
        # four `wrong_indicator_type`, two `missing_role`, one
        # `insufficient_samples` — and this one answered with silence. The fix is
        # the sibling form, verbatim, because the asymmetry was the whole defect.
        if indicator.indicator_type.value != 'numeric':
            return CheckOutcome(problems).declined(
                Axiom.MONOTONICITY, entity, indicator.name,
                NotEvaluatedReason.WRONG_INDICATOR_TYPE,
                detail=(
                    f"MONOTONICITY evaluates numeric indicators; this one is "
                    f"{indicator.indicator_type.value}"),
            )

        window = indicator.time_window or timedelta(hours=1)
        values = history.get_values(entity.id, indicator.property_name, window)

        # `monotonicity_window_size` was serving two roles at once:
        # how far back to look, and how much history must exist before looking
        # at all. Only the first is what a window means. Conflating them
        # re-imposed the exact over-gate that an internal ruling removed from the reasoner:
        # readiness reported this axiom evaluable at the derived floor (3,
        # being the fewest points that can exhibit a reversal — up, up, down)
        # while the checker silently returned until 20, so the axiom was
        # advertised live and emitted nothing. The two roles are now separate
        # params; the window slice below is unchanged, because you can look at
        # the last 20 observations while holding 5.
        if len(values) < self.params.monotonicity_min_samples:
            # corrected this floor from 20 to 3 precisely
            # because the axiom was advertised live while emitting nothing.
            # Reporting the decline is what makes that class of gap visible
            # from the outside rather than only from a source audit.
            # say which window the count is from. Measured on the
            # the reference VPS disk demo: 12 daily observations produce `0 of 3` here,
            # because the default window is one hour. Every number was true
            # and the composite told the operator to collect more data, which
            # would never have helped.
            ctx = sampling_context(
                history, entity.id, indicator.property_name, window)
            return CheckOutcome(problems).declined(
                Axiom.MONOTONICITY, entity, indicator.name,
                NotEvaluatedReason.INSUFFICIENT_SAMPLES,
                detail="fewer points than can exhibit a reversal",
                observations_count=len(values),
                required_count=self.params.monotonicity_min_samples,
                **ctx,
            )

        recent = values[-self.params.monotonicity_window_size:]

        mono_config = getattr(indicator, 'monotonicity_config', None)
        expected_dir = 'increasing'
        allow_reset = True
        # the rate arm no longer answers from a number nobody
        # declared. `None` means undeclared and is not compared; the pair being
        # BOTH undeclared is a decline, below.
        rate_warning_fallback = _declared_param(
            self.params.monotonicity_rate_warning, "monotonicity_rate_warning")
        rate_critical_fallback = _declared_param(
            self.params.monotonicity_rate_critical, "monotonicity_rate_critical")

        # how many reversals, and how many resets, this counter is
        # allowed before the axiom says anything. Declarable since 0.1.8;
        # `self.params` is the default and is unchanged at 3, so no model
        # written before this behaves differently.
        #
        # WHY IT HAD TO BECOME DECLARABLE. It was a global engine default of 3,
        # so an indicator declaring `expected_direction: increasing` had a
        # silent allowance of TWO backward moves — and unlike every other
        # tolerance in this format (`warning`, `critical`, `tolerance`,
        # `loss_margin`, the floor pair) no model could state it, no document
        # named it, and no envelope mentioned it. BOUNDEDNESS is correctly
        # quiet at 84 against a declared 85; the difference is that somebody
        # declared the 85.
        #
        # A single rollback of a cumulative counter produced no finding AND no
        # decline. Measured on 0.1.7 before this landed: one reversal 0/0, two
        # reversals 0/0, three reversals 1/0, identical under both `allow_reset`
        # settings.
        reversal_tolerance = self.params.monotonicity_reversal_threshold
        reset_tolerance = self.params.monotonicity_reversal_threshold

        if mono_config:
            expected_dir = mono_config.get('expected_direction', 'increasing')
            allow_reset = mono_config.get('allow_reset', True)
            # a declared key wins; an absent one stays undeclared
            # rather than falling back to the engine's own number. Declaring
            # only `rate_critical` is legal and leaves the warning arm silent,
            # which is how `critical:` without `warning:` already behaves under
            # BOUNDEDNESS and RESPONSIVENESS.
            rate_warning_fallback = mono_config.get(
                'rate_warning', rate_warning_fallback)
            rate_critical_fallback = mono_config.get(
                'rate_critical', rate_critical_fallback)
            # Two keys rather than one, because they count different events and
            # sharing a number is what hid the second. A reset is a drop to
            # near zero that `allow_reset` excuses individually; a reversal is
            # any other backward move. An internal ruling added the reset-storm arm on the
            # SAME global default, so it carried the identical defect one arm
            # over — fixing only the reversal side would have been fixing the
            # instance and leaving the class.
            reversal_tolerance = _positive_int(
                mono_config.get('reversal_tolerance'), reversal_tolerance,
                'reversal_tolerance', indicator)
            reset_tolerance = _positive_int(
                mono_config.get('reset_tolerance'), reset_tolerance,
                'reset_tolerance', indicator)

        # resolve per-entity override before falling back to
        # the existing mono_config-aware default. Precedence:
        # sentinel key > indicator.monotonicity_config > global params
        # The `(rate_warning_fallback, rate_critical_fallback)` tuple already
        # encodes the indicator-config + global-params precedence; the resolver
        # adds override on top.
        rate_warning, rate_critical = resolve_axiom_threshold(
            entity, indicator.property_name, "MONOTONICITY",
            fallback=(rate_warning_fallback, rate_critical_fallback),
            bound="both",
        )

        problems.extend(self._check_reversals(
            entity, indicator, recent, expected_dir, allow_reset,
            reversal_tolerance, reset_tolerance,
        ))

        # THE RATE ARM DECLINES RATHER THAN ANSWERING FROM A DEFAULT.
        #
        # Measured against the published 0.1.10 artifact, by a bridge written
        # to the downstream guide without reading this source -- which is what
        # made it visible, and is the whole of the claim. The bridge is this
        # engine's author's, so it is not independent evidence: with nothing
        # declared, this arm fired `warning` at 0.1/s and `critical` at 0.5/s.
        # Every PLC heartbeat crosses that. Every fast production counter
        # crosses it. The finding named an entity whose model never asked the
        # question, against a number nobody in the domain chose.
        #
        # It was the only arm in the format that did this. The reversal
        # tolerance beside it became declarable in 0.1.8 for the same argument
        # and by the same route, and the rate arm was left on the old footing --
        # the instance fixed and the class left, one arm over, again.
        #
        # Allowed as a patch release by COMPATIBILITY.md: *make a check DECLINE
        # where it previously answered from a guess, when the guess was
        # unsound.* The cost is stated rather than argued away -- a model
        # relying on the default loses the rate arm until it declares a rate,
        # and the decline names the declaration to write.
        #
        # THE REVERSAL ARM STILL RUNS AND ITS FINDINGS SURVIVE. `CheckOutcome`
        # is a list of problems PLUS declines, so this reports both: what the
        # reversal arm found, and that the rate arm was never asked. Returning
        # early without the problems would have withdrawn a working check to
        # report a missing one.
        if rate_warning is None and rate_critical is None:
            return CheckOutcome(
                apply_property_confidence(
                    entity, indicator.property_name, problems)
            ).declined(
                Axiom.MONOTONICITY, entity, indicator.name,
                NotEvaluatedReason.NO_THRESHOLD,
                detail=(
                    f"{indicator.name} declares MONOTONICITY and no rate to "
                    f"judge against; declare `monotonicity: {{rate_warning, "
                    f"rate_critical}}` with a basis, or accept that only the "
                    f"reversal arm is being checked. The reversal arm ran"),
            )

        problems.extend(self._check_rate(
            entity, indicator, recent, expected_dir, rate_warning, rate_critical
        ))

        return apply_property_confidence(entity, indicator.property_name, problems)

    def _check_reversals(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        values: list,
        expected_direction: str,
        allow_reset: bool,
        reversal_tolerance: Optional[int] = None,
        reset_tolerance: Optional[int] = None,
    ) -> List[Problem]:
        """Check for unexpected direction reversals.

        the two tolerances arrive as arguments so the DECLARED value
        reaches the comparison. They default to the global params for callers
        that predate the field; `check` above always passes both.
        """
        if reversal_tolerance is None:
            reversal_tolerance = self.params.monotonicity_reversal_threshold
        if reset_tolerance is None:
            reset_tolerance = self.params.monotonicity_reversal_threshold
        problems = []
        reversal_count = 0
        # count the drops `allow_reset` excuses, rather than only
        # dropping them on the floor. One reset is legitimate: a pod restarts
        # and zeroes its error counter. Five inside one window is not five
        # legitimate resets, it is a flapping system, and that is exactly the
        # signal a "transfer storm" consists of.
        reset_count = 0

        for i in range(1, len(values)):
            prev_val = values[i - 1][1]
            curr_val = values[i][1]

            if prev_val is None or curr_val is None:
                continue

            delta = curr_val - prev_val

            if expected_direction == 'increasing':
                if delta < 0:
                    if allow_reset and self._is_counter_reset(prev_val, curr_val):
                        reset_count += 1
                        continue
                    reversal_count += 1
            elif expected_direction == 'decreasing':
                if delta > 0:
                    if allow_reset and self._is_counter_reset(prev_val, curr_val):
                        reset_count += 1
                        continue
                    reversal_count += 1

        if reversal_count >= reversal_tolerance:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'monotonicity_reversal:{indicator.name}',
                severity=Severity.HIGH,
                reason=(
                    f"{indicator.name}: {reversal_count} unexpected reversals "
                    f"(expected {expected_direction})"
                ),
                axiom=Axiom.MONOTONICITY,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'indicator': indicator.name,
                    'expected_direction': expected_direction,
                    'reversal_count': reversal_count,
                    'threshold': reversal_tolerance,
                    'window_size': len(values),
                    'recent_values': [v[1] for v in values[-5:]],
                },
                confidence=min(
                    1.0,
                    reversal_count / reversal_tolerance
                ),
            ))

        # repeated resets are their own finding.
        #
        # `_is_counter_reset` returns True for any drop of more than 90% to
        # near zero, so an oscillation between a high value and zero is
        # indistinguishable from a reset pair by pair. That is a reasonable
        # per-pair judgement and a bad per-window one: the excuse had no
        # bound, so a counter resetting on every other sample produced
        # silence. Measured on a synthetic UPS transfer storm — 50/0/50/0,
        # five clean reversals, **zero problems and zero declines**.
        #
        # Deliberately a distinct problem type rather than folding into
        # `monotonicity_reversal`: the two mean different things to an
        # operator. One says the metric went the wrong way; this says the
        # metric keeps restarting, which is a liveness symptom.
        if reset_count >= reset_tolerance:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'monotonicity_reset_storm:{indicator.name}',
                severity=Severity.HIGH,
                reason=(
                    f"{indicator.name}: {reset_count} counter resets in the "
                    f"window; a single reset is legitimate, this many is a "
                    f"flapping source"
                ),
                axiom=Axiom.MONOTONICITY,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'indicator': indicator.name,
                    'expected_direction': expected_direction,
                    'reset_count': reset_count,
                    'threshold': reset_tolerance,
                    'window_size': len(values),
                    'recent_values': [v[1] for v in values[-5:]],
                },
                confidence=min(
                    1.0,
                    reset_count / reset_tolerance
                ),
            ))

        return problems

    def _check_rate(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        values: list,
        expected_direction: str,
        rate_warning: float,
        rate_critical: float,
    ) -> List[Problem]:
        """Check if rate of monotonic change is dangerously fast.

        the rate is a least-squares fit over the whole window, not
        the difference between its endpoints. The endpoint form discarded every
        interior point, so one bad reading at either end set the verdict
        outright and a longer window bought nothing but a longer lever for that
        outlier. It became load-bearing when an internal ruling lowered the gate from 20
        observations to 3: fewer points, same total reliance on two of them.

        For a clean ramp the two agree exactly — the fit through evenly spaced
        collinear points *is* the endpoint slope — so this changes nothing on
        well-behaved data and only damps the noisy case it was written for.
        """
        problems = []

        if len(values) < 2:
            return problems

        usable = [(ts, val) for ts, val in values if val is not None]
        if len(usable) < 2:
            return problems

        first_ts, first_val = usable[0]
        last_ts, last_val = usable[-1]

        time_delta = (last_ts - first_ts).total_seconds()
        if time_delta <= 0:
            return problems

        # Optional per-indicator floor on how much time the window must cover
        # before a rate is asserted at all. Default 0 (off): the right span is
        # a property of the indicator's sampling cadence — a counter read every
        # 15s and one read hourly do not share a number — so it is configured
        # per indicator rather than guessed here.
        mono_config = getattr(indicator, 'monotonicity_config', None) or {}
        min_span = mono_config.get('rate_min_span_seconds', 0)
        if min_span and time_delta < min_span:
            return problems

        slope = _robust_slope(usable)
        if slope is None:
            return problems
        rate = abs(slope)

        # an undeclared half is not compared. Both undeclared never
        # reaches here; `check` declines instead.
        if rate_critical is not None and rate >= rate_critical:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'monotonicity_rate:{indicator.name}',
                severity=Severity.CRITICAL,
                reason=(
                    f"{indicator.name}: rate of change {rate:.4f}/s "
                    f"exceeds critical threshold"
                ),
                axiom=Axiom.MONOTONICITY,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'indicator': indicator.name,
                    'rate_per_second': rate,
                    'threshold': rate_critical,
                    'threshold_type': 'critical',
                    'first_value': first_val,
                    'last_value': last_val,
                    'time_span_seconds': time_delta,
                    # a rate is uninterpretable without knowing how
                    # many points produced it, and this is what distinguishes
                    # a fitted trend from a two-point difference.
                    'sample_count': len(usable),
                    'rate_method': 'theil_sen',
                },
                confidence=min(1.0, rate / rate_critical),
            ))
        elif rate_warning is not None and rate >= rate_warning:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'monotonicity_rate:{indicator.name}',
                severity=Severity.WARNING,
                reason=(
                    f"{indicator.name}: rate of change {rate:.4f}/s "
                    f"exceeds warning threshold"
                ),
                axiom=Axiom.MONOTONICITY,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'indicator': indicator.name,
                    'rate_per_second': rate,
                    'threshold': rate_warning,
                    'threshold_type': 'warning',
                    'first_value': first_val,
                    'last_value': last_val,
                    'time_span_seconds': time_delta,
                    # a rate is uninterpretable without knowing how
                    # many points produced it, and this is what distinguishes
                    # a fitted trend from a two-point difference.
                    'sample_count': len(usable),
                    'rate_method': 'theil_sen',
                },
                confidence=min(1.0, rate / rate_warning),
            ))

        return problems

    @staticmethod
    def _is_counter_reset(prev_val: float, curr_val: float) -> bool:
        """
        Detect counter reset (e.g., pod restart resets error count to 0).

        A reset is characterized by a large drop to near zero.
        """
        if curr_val > prev_val:
            return False
        if prev_val <= 0:
            return False
        drop_ratio = (prev_val - curr_val) / prev_val
        return drop_ratio > 0.9 and curr_val < prev_val * 0.1
