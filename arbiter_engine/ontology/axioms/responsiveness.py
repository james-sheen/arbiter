"""
RESPONSIVENESS Axiom Checker.

RESPONSIVENESS: System responds to inputs.

Detects:
- Unresponsive systems (no output despite input)
- Increasing latency
- Degraded correlation between input/output
- Missing responses
- Queue buildup (growing queue depth)
- Degraded throughput (requests/sec dropping)
- Slow startup (container slow to ready)
- Health check timeout (probe failures)

Requires I/O relationship discovery (Phase 3.5).
For indicators marked as response/latency, basic checks apply.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import numpy as np

from ...clock import as_naive_utc, now_utc
from ...interfaces import (
    Entity,
    Problem,
    RelationshipGraph,
    ObservationHistory,
    IndicatorSpec,
    apply_property_confidence,
    CheckOutcome,
    absent_current_value,
)
from ...types import (
    Axiom,
    Severity,
    AxiomParameters,
    DetectionLayer,
    NotEvaluatedReason,
    IORelationship,
)
# — resolve_axiom_threshold at the primary firing-gate
# read-site (correlation_drop_threshold). The other 2 calibration scalars
# (latency_spike_factor + max_lag_seconds) stay as global params —
# sentinel key only has 1 override slot (indicator, axiom) tuple, so
# only the primary threshold gets the per-entity override. Same carve-out
# rationale as MONOTONICITY's reversal_threshold + STABILITY's epsilon/delta.
# The override is read off ``output_entity.properties`` (the entity carrying
# the responsiveness Problem); operator-supplied perturbed_thresholds inject
# via the output-side entity.
from ...axiom_thresholds import (
    resolve_axiom_threshold,
)

from . import roles

logger = logging.getLogger(__name__)


class ResponsivenessChecker:
    """
    Check RESPONSIVENESS axiom for entities.

    RESPONSIVENESS requires I/O relationship discovery for full functionality.
    For indicators with 'response' or 'latency' in name, basic threshold checks apply.
    """

    def __init__(
        self,
        params: Optional[AxiomParameters] = None,
        io_relationships: Optional[List[IORelationship]] = None
    ):
        self.params = params or AxiomParameters()
        self.io_relationships = io_relationships or []
        self._io_index = {}
        self._build_io_index()

    def _build_io_index(self):
        """Build index of I/O relationships for fast lookup."""
        self._io_index = {}
        for io_rel in self.io_relationships:
            key = (io_rel.input_entity_type, io_rel.output_entity_type)
            if key not in self._io_index:
                self._io_index[key] = []
            self._io_index[key].append(io_rel)

    def set_io_relationships(self, io_relationships: List[IORelationship]):
        """Update I/O relationships (from discovery)."""
        self.io_relationships = io_relationships
        self._build_io_index()

    def check(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        graph: RelationshipGraph,
        history: ObservationHistory
    ) -> List[Problem]:
        """
        Check RESPONSIVENESS for an entity/indicator.

        For response/latency indicators: Check threshold
        For I/O pairs: Check correlation and latency
        """
        problems = []

        # applicability is now a DECLARED role, with the old
        # name-substring rule kept as the fallback for models written before
        # the field existed. `role: latency` makes this evaluate an indicator
        # called `pulldown_error_c`; before, only English decided.
        name_matches, _matched, _role_source = roles.applies(
            Axiom.RESPONSIVENESS, indicator)
        if name_matches:
            # the decline has to be raised HERE, not inside the
            # helper. `_check_latency_threshold` returns a plain list and this
            # is an `extend`, which keeps the problems and drops any
            # `not_evaluated` records (the helper-seam limitation). A
            # decline written in the helper would vanish at exactly this line.
            #
            # Reported from outside as issue #1: with `role: latency` declared
            # and no property fed, the NOT_APPLICABLE decline below is skipped
            # (the role DOES apply), the helper finds nothing, and `check()`
            # returns a clean pass. RESPONSIVENESS is the fifth silent axiom
            # and the one the report did not name — `Controller` is the only
            # entity type in the shipped example that declares it.
            if entity.get_property(indicator.property_name) is None:
                # which absence, not just that there is one.
                reason, clause, seen = absent_current_value(
                    entity, indicator, history)
                return CheckOutcome(problems).declined(
                    Axiom.RESPONSIVENESS, entity, indicator.name, reason,
                    detail=(
                        f"{clause}; "
                        f"RESPONSIVENESS compares a latency against its "
                        f"threshold"),
                    observations_count=seen or None,
                )
            # the case the previous three rounds left inside the
            # helper. The role applies and the value is present, so neither
            # decline above fires; if no threshold is declared,
            # `_check_latency_threshold` compares against nothing and returns
            # an empty list, which `extend` cannot distinguish from a clean
            # pass. `checked.invariants` then counts the cell as attempted, so
            # the envelope reports a question as covered that it could not ask.
            #
            # Raised here for the same reason the decline above is: a
            # `not_evaluated` record written in the helper is dropped by this
            # `extend`. Measured from outside on 0.1.10 by an independent
            # bridge, against a latency of ten million: no finding, no decline,
            # `invariants: 1`. BOUNDEDNESS in the same position already
            # declines NO_THRESHOLD, which is the shape this restores.
            if (indicator.critical_threshold is None
                    and indicator.warning_threshold is None):
                return CheckOutcome(problems).declined(
                    Axiom.RESPONSIVENESS, entity, indicator.name,
                    NotEvaluatedReason.NO_THRESHOLD,
                    detail=(
                        f"{indicator.name} declares RESPONSIVENESS and a "
                        f"latency role, and no `critical:` or `warning:` to "
                        f"compare against; RESPONSIVENESS judges a latency "
                        f"against a declared threshold"),
                )
            problems.extend(self._check_latency_threshold(
                entity, indicator
            ))

        result = apply_property_confidence(
            entity, indicator.property_name, problems)

        # the largest silent decline in the engine. `check()` has
        # exactly ONE arm, and it is gated on the indicator's NAME containing
        # 'response' or 'latency'. Every other indicator declaring
        # RESPONSIVENESS reached this return having evaluated nothing at all,
        # and returned an empty list indistinguishable from a clean pass.
        #
        # A declared axiom that silently evaluates nothing is worse than an
        # undeclared one: the domain model says the invariant is being
        # checked. Note the matching itself is a hidden domain assumption —
        # an indicator named `queue_depth` or `p99` is plainly a
        # responsiveness measure and is skipped anyway. Reporting it is this
        # CD's scope; replacing name-matching with a declared property is not.
        if not name_matches:
            # the decline now names the REMEDY rather than the rule.
            # The sentence this replaces was true and unhelpful: it described
            # the engine's name test, leaving the reader to conclude that
            # renaming their domain concept was the fix. Renaming a concept to
            # satisfy a checker is the wrong remedy; saying what the concept is
            # is the right one.
            return CheckOutcome(result).declined(
                Axiom.RESPONSIVENESS, entity, indicator.name,
                NotEvaluatedReason.MISSING_ROLE,
                detail=roles.explain_absence(Axiom.RESPONSIVENESS, indicator),
            )
        # a branch keyed on a third role source was removed here: the
        # role module returns two, so it could never fire and nothing could go red.
        return result

    def _check_latency_threshold(
        self,
        entity: Entity,
        indicator: IndicatorSpec
    ) -> List[Problem]:
        """Check response time against threshold."""
        problems = []

        value = entity.get_property(indicator.property_name)
        if value is None:
            return problems

        try:
            value = float(value)
        except (TypeError, ValueError):
            return problems

        # Check threshold.
        #
        # `is not None`, not truthiness. A declared `critical: 0` is
        # falsy, and the previous test skipped it silently: a threshold the
        # model states and the checker does not apply. Zero is a legitimate
        # bound for a latency that must be immediate, and the caller now
        # declines NO_THRESHOLD when neither is declared, so an undeclared
        # threshold no longer reaches here at all.
        if (indicator.critical_threshold is not None
                and value > indicator.critical_threshold):
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'response_time_critical:{indicator.name}',
                severity=Severity.CRITICAL,
                reason=f"Response time {indicator.name} exceeds critical threshold",
                axiom=Axiom.RESPONSIVENESS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'property': indicator.name,
                    'value': value,
                    'threshold': indicator.critical_threshold,
                },
                confidence=1.0,
            ))
        elif (indicator.warning_threshold is not None
                and value > indicator.warning_threshold):
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'response_time_warning:{indicator.name}',
                severity=Severity.WARNING,
                reason=f"Response time {indicator.name} exceeds warning threshold",
                axiom=Axiom.RESPONSIVENESS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'property': indicator.name,
                    'value': value,
                    'threshold': indicator.warning_threshold,
                },
                confidence=1.0,
            ))

        return problems

    def check_io_pair(
        self,
        input_entity: Entity,
        output_entity: Entity,
        io_rel: IORelationship,
        history: ObservationHistory
    ) -> List[Problem]:
        """
        Check responsiveness between an I/O pair.

        Detects:
        - Correlation breakdown
        - Latency spike
        - Missing response
        """
        problems = []

        # Get recent time series
        window = timedelta(hours=1)
        input_series = history.get_values(
            input_entity.id, io_rel.input_property, window
        )
        output_series = history.get_values(
            output_entity.id, io_rel.output_property, window
        )

        if len(input_series) < 10 or len(output_series) < 10:
            return problems  # Not enough data

        # 1. Check correlation
        current_corr = self._compute_correlation(input_series, output_series)

        # an indeterminate correlation is NOT a correlation of zero.
        # `_compute_correlation` returned 0.0 for "cannot compute", and the
        # subtraction below turned that into a full-baseline drop: a steady
        # output series (zero variance, so `np.corrcoef` gives NaN) fired
        # CRITICAL for a breakdown that never happened. Skipping the arm is
        # the correct behaviour — the other two checks below still run, so a
        # genuine latency or missing-response problem is unaffected.
        if current_corr is None:
            logger.debug(
                "correlation indeterminate for %s -> %s (%s/%s); "
                "skipping the correlation arm rather than reading it as zero",
                input_entity.id, output_entity.id,
                io_rel.input_property, io_rel.output_property,
            )
            correlation_drop = None
        else:
            correlation_drop = io_rel.correlation - current_corr

        # resolve per-entity override (off output_entity) for
        # the correlation_drop_threshold firing gate. Single-bound shape.
        correlation_drop_threshold = resolve_axiom_threshold(
            output_entity, io_rel.output_property, "RESPONSIVENESS",
            fallback=self.params.responsiveness_correlation_drop_threshold,
            bound="warn",
        )
        if correlation_drop is not None and correlation_drop > correlation_drop_threshold:
            severity = Severity.CRITICAL if correlation_drop > 0.5 else Severity.WARNING
            problems.append(Problem.from_entity(
                entity=output_entity,
                problem_type='correlation_breakdown',
                severity=severity,
                reason=f"I/O correlation dropped from {io_rel.correlation:.2f} to {current_corr:.2f}",
                axiom=Axiom.RESPONSIVENESS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'input_entity': input_entity.id,
                    'output_entity': output_entity.id,
                    'input_property': io_rel.input_property,
                    'output_property': io_rel.output_property,
                    'expected_correlation': io_rel.correlation,
                    'observed_correlation': current_corr,
                },
                confidence=0.8,
            ))

        # 2. Check latency
        current_lag = self._compute_lag(input_series, output_series)
        if current_lag > io_rel.lag_seconds * self.params.responsiveness_latency_spike_factor:
            severity = Severity.CRITICAL if current_lag > io_rel.lag_seconds * 5 else Severity.WARNING
            problems.append(Problem.from_entity(
                entity=output_entity,
                problem_type='latency_spike',
                severity=severity,
                reason=f"Response latency {current_lag:.1f}s vs expected {io_rel.lag_seconds:.1f}s",
                axiom=Axiom.RESPONSIVENESS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'input_entity': input_entity.id,
                    'output_entity': output_entity.id,
                    'expected_lag': io_rel.lag_seconds,
                    'observed_lag': current_lag,
                },
                confidence=0.7,
            ))

        # 3. Check for missing responses
        if input_series and output_series:
            latest_input_time = input_series[-1][0]
            latest_output_time = output_series[-1][0]
            time_since_output = (latest_input_time - latest_output_time).total_seconds()

            timeout = io_rel.lag_seconds + self.params.responsiveness_max_lag_seconds
            if time_since_output > timeout:
                problems.append(Problem.from_entity(
                    entity=output_entity,
                    problem_type='missing_response',
                    severity=Severity.CRITICAL,
                    reason=f"No response for {time_since_output:.0f}s after input",
                    axiom=Axiom.RESPONSIVENESS,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'input_entity': input_entity.id,
                        'output_entity': output_entity.id,
                        'time_since_output': time_since_output,
                        'expected_timeout': timeout,
                    },
                    confidence=0.9,
                ))

        return problems

    def _compute_correlation(
        self,
        series_a: List,
        series_b: List
    ) -> Optional[float]:
        """Pearson correlation between two series, or None if indeterminate.

        Every one of these paths used to return ``0.0``, and the
        caller computes ``correlation_drop = baseline - current``. So an
        indeterminate correlation was read as *total correlation loss* and
        produced ``Severity.CRITICAL`` for a breakdown that did not happen.

        The reachable trigger is **zero variance**, not insufficient samples —
        ``check_io_pair`` already guards both series at 10 upstream, so the
        length branches here are unreachable from it. ``np.corrcoef`` divides
        by the standard deviation, so a perfectly steady series yields NaN.
        A flat output is the *normal* shape of a healthy steady-state metric
        or an idle counter, which is what made this fire on well-behaved
        systems: baseline 0.9 minus a coerced 0.0 clears the 0.5 critical
        threshold outright. Verified: ``np.corrcoef(range(12), [5.0]*12)`` is
        ``nan``.

        Returning ``None`` rather than ``0.0`` is the same correction that an internal ruling
        made to ``_robust_slope`` in the MONOTONICITY checker, for the same
        reason: **zero is a real answer** — it means uncorrelated — and a
        sentinel that collides with a legitimate value cannot be distinguished
        from one downstream.
        """
        import numpy as np

        # Require minimum 10 samples for meaningful correlation
        if len(series_a) < 10 or len(series_b) < 10:
            return None  # insufficient data — not "uncorrelated"

        # Align series (simple: use values only)
        values_a = [v for _, v in series_a]
        values_b = [v for _, v in series_b]

        # Use shorter length
        min_len = min(len(values_a), len(values_b))
        values_a = values_a[-min_len:]
        values_b = values_b[-min_len:]

        if len(values_a) < 10:
            return None

        try:
            corr = np.corrcoef(values_a, values_b)[0, 1]
            return float(corr) if not np.isnan(corr) else None
        except Exception:  # noqa: BLE001 — indeterminate, not zero
            return None

    def _compute_lag(
        self,
        input_series: List,
        output_series: List
    ) -> float:
        """Compute average lag between input and output."""
        if not input_series or not output_series:
            return 0.0

        # Simple: compare latest timestamps
        latest_input = input_series[-1][0]
        latest_output = output_series[-1][0]

        return abs((latest_output - latest_input).total_seconds())

    # =========================================================================
    # Domain-specific RESPONSIVENESS Checks (loaded via extensions)
    # =========================================================================

    def run_domain_checks(
        self,
        entity: Entity,
        history: ObservationHistory,
        domain_id: str = "",
    ) -> List[Problem]:
        """Run all registered domain-specific responsiveness checks.

        Accept domain_id to filter extension checks to the correct
        domain. Without this, multi-domain deployments run ALL registered
        extensions on every entity.

        **A check that cannot run is reported, not dropped (2026-09-07).** This
        swallowed every exception into a debug line, which is the one log level
        nobody reads in production. Measured, that hid a declared check which
        could never run at all: the domain file names it, the binder calls it
        with the wrong arity because its second parameter is not the one the
        binder looks for, and the TypeError landed here and vanished. It had
        been declared and unrunnable for as long as both existed, and no
        surface said so.

        `warning`, not `raise`. One extension raising must not take out the
        others in the same pass -- that is why the try is here. But *ran and
        found nothing* and *could not be called* are different answers, and a
        log level is the only place this function can currently tell them
        apart: it returns a plain list and has no decline channel to put the
        distinction in. That is the narrower gap, and it is recorded rather
        than closed here.
        """
        from .extensions import extension_registry
        outcome = CheckOutcome()
        for check_fn in extension_registry.get_responsiveness_checks(domain_id=domain_id):
            try:
                result = check_fn(entity, history)
                # `if result:` used to guard this, and a CheckOutcome
                # carrying only declines is falsy -- zero problems in a list
                # subclass -- so a check that declined had its record dropped
                # here. Extending with an empty list is a no-op, so the guard
                # bought nothing and cost the records. `not_evaluated` is not
                # list contents, so it is carried across explicitly or not at
                # all.
                outcome.extend(result)
                outcome.not_evaluated.extend(
                    getattr(result, "not_evaluated", ()))
            except Exception as e:
                # Named, so the record and the message identify WHICH check
                # failed. The callables arrive from an extension and are often
                # lambdas, so `__name__` is frequently `<lambda>`; the qualname
                # of what it closes over is the useful half when it is there.
                _named = getattr(check_fn, "__qualname__", None) or repr(check_fn)
                # `checker_error` was in the closed decline vocabulary from the
                # start and had never once been emitted -- a reason this engine
                # advertises it can return, that no path produced. It is the
                # exact name for this case, so the case now uses it.
                outcome.declined(
                    Axiom.RESPONSIVENESS, entity, _named,
                    NotEvaluatedReason.CHECKER_ERROR,
                    detail=f"the registered check raised and produced nothing: {e}")
                logger.warning(
                    "domain responsiveness check %s could not run and produced "
                    "nothing: %s. A declared check that cannot be called is "
                    "not a check that found nothing.", _named, e)
        return outcome

    # =========================================================================
    # Built-in checks: domain-agnostic, plus Kubernetes-shaped ones the
    # Kubernetes domain file names under `domain_checks` and reaches by
    # declaration through the extension registry -- never by a branch here.
    # =========================================================================

    def check_queue_buildup(
        self,
        entity: Entity,
        history: ObservationHistory,
        queue_property: str = 'queueDepth',
        threshold: int = 100,
        growth_rate_threshold: float = 0.1
    ) -> List[Problem]:
        """
        Check for queue buildup (growing queue depth).

        Detects:
        - Queue depth exceeding threshold
        - Queue growth rate indicating backpressure
        """
        problems = []

        # Get queue depth history
        window = timedelta(minutes=10)
        values = history.get_values(entity.id, queue_property, window)

        if len(values) < 5:
            return problems

        current_depth = values[-1][1] if values else 0

        # Check absolute threshold
        if current_depth > threshold:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type='queue_buildup',
                severity=Severity.HIGH,
                reason=f"Queue depth {current_depth:.0f} exceeds threshold {threshold}",
                axiom=Axiom.RESPONSIVENESS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'property': queue_property,
                    'current_depth': current_depth,
                    'threshold': threshold,
                },
                confidence=0.9,
            ))

        # Check growth rate
        if len(values) >= 5:
            recent_values = [v for _, v in values[-5:]]
            older_values = [v for _, v in values[:-5]] if len(values) > 5 else [values[0][1]]

            recent_avg = np.mean(recent_values)
            older_avg = np.mean(older_values)

            if older_avg > 0:
                growth_rate = (recent_avg - older_avg) / older_avg
                if growth_rate > growth_rate_threshold:
                    problems.append(Problem.from_entity(
                        entity=entity,
                        problem_type='queue_growth',
                        severity=Severity.WARNING,
                        reason=f"Queue growing at {growth_rate*100:.1f}% rate",
                        axiom=Axiom.RESPONSIVENESS,
                        source_layer=DetectionLayer.ONTOLOGY,
                        evidence={
                            'property': queue_property,
                            'growth_rate': growth_rate,
                            'recent_avg': recent_avg,
                            'older_avg': older_avg,
                        },
                        confidence=0.7,
                    ))

        return problems

    def check_throughput_degradation(
        self,
        entity: Entity,
        history: ObservationHistory,
        throughput_property: str = 'requestsPerSecond',
        degradation_threshold: float = 0.5
    ) -> List[Problem]:
        """
        Check for throughput degradation.

        Detects:
        - Throughput dropping significantly from baseline
        """
        problems = []

        # Get throughput history (1 hour baseline, 5 min recent)
        baseline_window = timedelta(hours=1)
        baseline_values = history.get_values(entity.id, throughput_property, baseline_window)

        if len(baseline_values) < 20:
            return problems  # Not enough baseline data

        # Calculate baseline (first half) vs recent (last 5 min)
        cutoff = len(baseline_values) // 2
        baseline_avg = np.mean([v for _, v in baseline_values[:cutoff]])
        recent_values = [v for _, v in baseline_values[-10:]]
        recent_avg = np.mean(recent_values) if recent_values else 0

        if baseline_avg > 0:
            degradation = (baseline_avg - recent_avg) / baseline_avg
            if degradation > degradation_threshold:
                problems.append(Problem.from_entity(
                    entity=entity,
                    problem_type='throughput_degradation',
                    severity=Severity.HIGH,
                    reason=f"Throughput degraded by {degradation*100:.1f}%",
                    axiom=Axiom.RESPONSIVENESS,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'property': throughput_property,
                        'baseline_avg': baseline_avg,
                        'recent_avg': recent_avg,
                        'degradation_pct': degradation * 100,
                    },
                    confidence=0.8,
                ))

        return problems

    def check_slow_startup(
        self,
        entity: Entity,
        startup_timeout_seconds: float = 120.0
    ) -> List[Problem]:
        """
        Check for slow container startup.

        Detects:
        - Container taking too long to become ready
        """
        problems = []

        # The entity types this check applies to are DECLARED, in the domain
        # file's `domain_checks` entry, and enforced by the wrapper the platform
        # builds from it. A literal list here was a second copy of that scope:
        # a domain naming a type this list omitted was accepted, bound, called,
        # and silently returned nothing. Removed. Four of the eight
        # checks k8s.yaml declares never carried one.

        phase = entity.get_property('phase')
        if phase not in ('Pending', 'ContainerCreating'):
            return problems

        # Get creation time
        created_at = entity.get_property('createdAt')
        if not created_at:
            return problems

        try:
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            elif isinstance(created_at, (int, float)):
                created_at = datetime.fromtimestamp(created_at, timezone.utc)

            age_seconds = (now_utc() - as_naive_utc(created_at)).total_seconds()

            if age_seconds > startup_timeout_seconds:
                problems.append(Problem.from_entity(
                    entity=entity,
                    problem_type='slow_startup',
                    severity=Severity.HIGH if age_seconds > startup_timeout_seconds * 2 else Severity.WARNING,
                    reason=f"Container startup taking {age_seconds:.0f}s (threshold: {startup_timeout_seconds}s)",
                    axiom=Axiom.RESPONSIVENESS,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'phase': phase,
                        'age_seconds': age_seconds,
                        'threshold': startup_timeout_seconds,
                    },
                    confidence=0.9,
                ))
        except (ValueError, TypeError) as e:
            logger.debug(f"Could not parse createdAt for {entity.id}: {e}")

        return problems

    def check_health_probe_failures(
        self,
        entity: Entity,
        history: ObservationHistory,
        failure_threshold: int = 3
    ) -> List[Problem]:
        """
        Check for health probe failures.

        Detects:
        - Liveness/readiness probe failures
        """
        problems = []

        # The entity types this check applies to are DECLARED, in the domain
        # file's `domain_checks` entry, and enforced by the wrapper the platform
        # builds from it. A literal list here was a second copy of that scope:
        # a domain naming a type this list omitted was accepted, bound, called,
        # and silently returned nothing. Removed. Four of the eight
        # checks k8s.yaml declares never carried one.

        # Check liveness probe failures
        liveness_failures = entity.get_property('livenessProbeFailures', 0)
        if liveness_failures and liveness_failures >= failure_threshold:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type='liveness_probe_failing',
                severity=Severity.CRITICAL,
                reason=f"Liveness probe failed {liveness_failures} times",
                axiom=Axiom.RESPONSIVENESS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'probe_type': 'liveness',
                    'failure_count': liveness_failures,
                    'threshold': failure_threshold,
                },
                confidence=1.0,
            ))

        # Check readiness probe failures
        readiness_failures = entity.get_property('readinessProbeFailures', 0)
        if readiness_failures and readiness_failures >= failure_threshold:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type='readiness_probe_failing',
                severity=Severity.HIGH,
                reason=f"Readiness probe failed {readiness_failures} times",
                axiom=Axiom.RESPONSIVENESS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'probe_type': 'readiness',
                    'failure_count': readiness_failures,
                    'threshold': failure_threshold,
                },
                confidence=1.0,
            ))

        return problems

    def check_request_timeout(
        self,
        entity: Entity,
        history: ObservationHistory,
        timeout_property: str = 'timeoutCount',
        window_minutes: int = 5,
        threshold: int = 1
    ) -> List[Problem]:
        """
        Check for request timeouts.

        Detects:
        - Request timeouts exceeding threshold
        """
        problems = []

        window = timedelta(minutes=window_minutes)
        timeout_values = history.get_values(entity.id, timeout_property, window)

        if not timeout_values:
            return problems

        total_timeouts = sum(v for _, v in timeout_values)

        if total_timeouts >= threshold:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type='request_timeout',
                severity=Severity.CRITICAL if total_timeouts >= threshold * 3 else Severity.HIGH,
                reason=f"{total_timeouts} request timeouts in last {window_minutes} minutes",
                axiom=Axiom.RESPONSIVENESS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'timeout_count': total_timeouts,
                    'window_minutes': window_minutes,
                    'threshold': threshold,
                },
                confidence=0.95,
            ))

        return problems

    def check_all(
        self,
        entity: Entity,
        history: ObservationHistory
    ) -> List[Problem]:
        """
        Run all RESPONSIVENESS checks on an entity.

        Two domain-agnostic checks always run. Everything domain-specific
        arrives through the extension registry, scoped by the entity's declared
        domain. This method decides nothing by asking which domain it is in.
        """
        # Domain-agnostic checks always run.
        #
        # Each `extend` keeps the problems and drops any declines the callee
        # recorded -- the known seam. The declines are collected
        # alongside so this method can return them, which is why the results
        # are bound before being extended rather than extended inline.
        problems = []
        declines = []
        for outcome in (self.check_queue_buildup(entity, history),
                        self.check_throughput_degradation(entity, history)):
            problems.extend(outcome)
            declines.extend(getattr(outcome, "not_evaluated", ()))

        # Run domain-specific checks via extension registry
        # check per-entity results instead of global registry
        # Extract domain_id from entity metadata to scope extension checks.
        _domain_id = getattr(entity, 'metadata', {}).get('domain_id', '') if hasattr(entity, 'metadata') else ''
        domain_problems = self.run_domain_checks(entity, history, domain_id=_domain_id)
        problems.extend(domain_problems)
        declines.extend(getattr(domain_problems, "not_evaluated", ()))

        # Option C, 2026-09-07. The hardcoded fallback that ran the
        # three Kubernetes-shaped checks below is gone. It was gated on
        # `_domain_id` matching one literal and on a flat entity-type set, and
        # it fired whenever the declared path above returned nothing -- so one
        # behaviour had two implementations, and this was the weaker of them:
        # the declaration scopes each check to its own entity types, this could
        # not. The twin in homeostasis.py went in the same change, and so did
        # the two records that pinned them.
        return CheckOutcome(problems, not_evaluated=declines)
