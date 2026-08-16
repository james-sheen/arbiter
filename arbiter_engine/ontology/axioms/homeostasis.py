"""
HOMEOSTASIS Axiom Checker.

HOMEOSTASIS: System maintains properties in normal range.

Detects:
- Z-score anomalies (values far from learned mean)
- Drift from baseline
- Sudden changes
- Failed self-healing (auto-recovery not working)
- Config drift (config differs from desired)
- Replica mismatch (actual != desired replicas)
- Oscillating recovery (repeated fail/recover cycles)
- Recovery timeout (recovery taking too long)

Mathematical formula:
    z_P(t) = (P(t) - μ_P) / σ_P

Parameters:
- z_warning = 2.0: ~5% false positive rate (2σ)
- z_critical = 3.0: ~0.3% false positive rate (3σ)
- min_samples = 30: Minimum observations for reliable baseline
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ...interfaces import (
    Entity,
    Problem,
    RelationshipGraph,
    ObservationHistory,
    IndicatorSpec,
    apply_property_confidence,
    CheckOutcome,
    sampling_context,
    absent_current_value,
)
from ...types import (
    Axiom, Severity, AxiomParameters, DetectionLayer, NotEvaluatedReason,
)
# — call resolve_axiom_threshold at z_warning/z_critical
# read-sites so per-sample entity-property overrides win over global
# AxiomParameters fallback during v2 perturbation runs. Non-calibration
# reads (baseline_days, min_samples) stay as global params — those are
# sample-window / sample-count parameters, not per-(entity, indicator,
# axiom) calibration values.
from ...axiom_thresholds import (
    resolve_axiom_threshold,
)

logger = logging.getLogger(__name__)


class HomeostasisChecker:
    """
    Check HOMEOSTASIS axiom for entities.

    HOMEOSTASIS requires historical data for baseline calculation.
    Minimum observations: 30
    """

    def __init__(self, params: Optional[AxiomParameters] = None):
        self.params = params or AxiomParameters()
        # Cache for learned baselines
        self._baseline_cache = {}
        # Max cache size to prevent unbounded growth from entity churn
        self._max_baseline_cache_size: int = 10000

    def clear_entity_baseline(self, entity_id: str) -> int:
        """Remove all baseline cache entries for a specific entity.

        Called from entity eviction path alongside history.clear_entity()
        and graph.remove_entity().

        Returns:
            Number of entries removed
        """
        keys_to_remove = [k for k in self._baseline_cache if k[0] == entity_id]
        for k in keys_to_remove:
            del self._baseline_cache[k]
        return len(keys_to_remove)

    def check(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        graph: RelationshipGraph,
        history: ObservationHistory
    ) -> List[Problem]:
        """
        Check HOMEOSTASIS for an entity/indicator.

        For numeric indicators: Calculate Z-score and detect anomalies
        """
        problems = []

        # three bare early returns replaced by declines. The
        # INSUFFICIENT_SAMPLES decline further down was already correct and was
        # unreachable whenever the property was absent, because this exit fired
        # first and returned an empty list that reads as a clean pass.
        if indicator.indicator_type.value != 'numeric':
            return CheckOutcome(problems).declined(
                Axiom.HOMEOSTASIS, entity, indicator.name,
                NotEvaluatedReason.WRONG_INDICATOR_TYPE,
                detail=(
                    f"HOMEOSTASIS evaluates numeric indicators; this one is "
                    f"{indicator.indicator_type.value}"),
            )

        current = entity.get_property(indicator.property_name)
        if current is None:
            # which absence, not just that there is one.
            reason, clause, seen = absent_current_value(entity, indicator, history)
            return CheckOutcome(problems).declined(
                Axiom.HOMEOSTASIS, entity, indicator.name, reason,
                detail=(
                    f"{clause}; "
                    f"HOMEOSTASIS compares a current value against a baseline"),
                observations_count=seen or None,
            )

        try:
            current = float(current)
        except (TypeError, ValueError):
            return CheckOutcome(problems).declined(
                Axiom.HOMEOSTASIS, entity, indicator.name,
                NotEvaluatedReason.WRONG_INDICATOR_TYPE,
                detail=(
                    f"property {indicator.property_name} is declared numeric "
                    f"but its value is not: {current!r}"),
            )

        # Get historical values for baseline
        baseline_window = timedelta(days=self.params.homeostasis_baseline_days)
        value_history = history.get_values(
            entity.id, indicator.property_name, baseline_window
        )

        if len(value_history) < self.params.homeostasis_min_samples:
            # this is the widest floor of the eight axioms, so it is
            # the one most often responsible for an empty result that looks
            # clean. Say so rather than returning a bare list.
            # carry the baseline window and the observed sampling
            # rate. This is the widest floor (30) against a 7-day window, so
            # anything sampled less often than every 5.6 hours can never reach
            # it; `6 of 30` on a daily series reads as "keep collecting" and
            # is permanently wrong.
            ctx = sampling_context(
                history, entity.id, indicator.property_name, baseline_window)
            return CheckOutcome(problems).declined(
                Axiom.HOMEOSTASIS, entity, indicator.name,
                NotEvaluatedReason.INSUFFICIENT_SAMPLES,
                detail="not enough history to establish a baseline",
                observations_count=len(value_history),
                required_count=self.params.homeostasis_min_samples,
                **ctx,
            )

        # Calculate baseline statistics
        historical_values = [v for _, v in value_history]
        mean = np.mean(historical_values)
        std = np.std(historical_values)

        if std == 0:
            return problems  # No variance, can't detect anomaly

        # Z-score anomaly detection
        z_score = (current - mean) / std

        # resolve per-entity override for z_warning/z_critical
        # before falling back to global params. Canonical bound="both" shape.
        z_warning, z_critical = resolve_axiom_threshold(
            entity, indicator.property_name, "HOMEOSTASIS",
            fallback=(
                self.params.homeostasis_z_warning,
                self.params.homeostasis_z_critical,
            ),
            bound="both",
        )

        # (implements): direction gate.
        # BIDIRECTIONAL (default) preserves previously behavior: fire on
        # |z| > threshold. LOWER fires only on z < -threshold (negative-space,
        # e.g. silent moderation failure when rejected_input rate drops to
        # zero). UPPER fires only on z > +threshold. The empirical direction
        # is computed below for the reason-string regardless of gate choice.
        direction_param = getattr(indicator, "direction", "BIDIRECTIONAL") or "BIDIRECTIONAL"
        if direction_param == "UPPER":
            fires_critical = z_score > z_critical
            fires_warning = z_score > z_warning
        elif direction_param == "LOWER":
            fires_critical = z_score < -z_critical
            fires_warning = z_score < -z_warning
        else:  # BIDIRECTIONAL — previously behavior
            fires_critical = abs(z_score) > z_critical
            fires_warning = abs(z_score) > z_warning

        if fires_critical:
            direction = "above" if z_score > 0 else "below"
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'homeostasis_anomaly:{indicator.name}',
                severity=Severity.CRITICAL,
                reason=f"{indicator.name} is {abs(z_score):.1f}σ {direction} normal",
                axiom=Axiom.HOMEOSTASIS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'indicator': indicator.name,
                    'value': current,
                    'mean': mean,
                    'std': std,
                    'z_score': z_score,
                    'threshold': z_critical,
                    'observations': len(value_history),
                },
                confidence=min(1.0, abs(z_score) / 5),
            ))
        elif fires_warning:
            direction = "above" if z_score > 0 else "below"
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'homeostasis_warning:{indicator.name}',
                severity=Severity.WARNING,
                reason=f"{indicator.name} is {abs(z_score):.1f}σ {direction} normal",
                axiom=Axiom.HOMEOSTASIS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'indicator': indicator.name,
                    'value': current,
                    'mean': mean,
                    'std': std,
                    'z_score': z_score,
                    'threshold': z_warning,
                    'observations': len(value_history),
                },
                confidence=min(1.0, abs(z_score) / 3),
            ))

        return apply_property_confidence(entity, indicator.property_name, problems)

    def check_drift(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        history: ObservationHistory,
        drift_window: timedelta = None
    ) -> List[Problem]:
        """
        Check for baseline drift (gradual change in normal range).

        Compares recent mean to historical mean.
        """
        problems = []

        if indicator.indicator_type.value != 'numeric':
            return problems

        drift_window = drift_window or timedelta(days=1)
        baseline_window = timedelta(days=self.params.homeostasis_baseline_days)

        # Get recent values
        recent_values = history.get_values(
            entity.id, indicator.property_name, drift_window
        )
        if len(recent_values) < 10:
            return problems

        # Get historical values
        historical_values = history.get_values(
            entity.id, indicator.property_name, baseline_window
        )
        if len(historical_values) < self.params.homeostasis_min_samples:
            return problems

        # Compare means
        recent_mean = np.mean([v for _, v in recent_values])
        historical_mean = np.mean([v for _, v in historical_values])
        historical_std = np.std([v for _, v in historical_values])

        if historical_std == 0:
            return problems

        # Drift is significant if recent mean is far from historical mean
        drift_z = (recent_mean - historical_mean) / historical_std

        # same override-precedence as check(); drift uses only the
        # warning bound (no separate critical for drift detection).
        drift_z_warning = resolve_axiom_threshold(
            entity, indicator.property_name, "HOMEOSTASIS",
            fallback=self.params.homeostasis_z_warning,
            bound="warn",
        )

        if abs(drift_z) > drift_z_warning:
            direction = "increased" if drift_z > 0 else "decreased"
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'baseline_drift:{indicator.name}',
                severity=Severity.WARNING,
                reason=f"{indicator.name} baseline has {direction}",
                axiom=Axiom.HOMEOSTASIS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'indicator': indicator.name,
                    'recent_mean': recent_mean,
                    'historical_mean': historical_mean,
                    'historical_std': historical_std,
                    'drift_z': drift_z,
                    'recent_observations': len(recent_values),
                    'historical_observations': len(historical_values),
                },
                confidence=0.7,
            ))

        return problems

    def check_sudden_change(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        history: ObservationHistory
    ) -> List[Problem]:
        """
        Check for sudden changes (step changes in value).
        """
        problems = []

        if indicator.indicator_type.value != 'numeric':
            return problems

        # Get recent values
        window = timedelta(hours=1)
        values = history.get_values(entity.id, indicator.property_name, window)

        if len(values) < 5:
            return problems

        # Calculate rolling statistics
        recent_values = [v for _, v in values[-5:]]
        older_values = [v for _, v in values[:-5]] if len(values) > 5 else []

        if not older_values:
            return problems

        recent_mean = np.mean(recent_values)
        older_mean = np.mean(older_values)
        older_std = np.std(older_values) if len(older_values) > 1 else 0

        if older_std == 0:
            older_std = abs(older_mean) * 0.1 or 1  # Use 10% as proxy

        change_z = (recent_mean - older_mean) / older_std

        if abs(change_z) > 3:
            direction = "spike" if change_z > 0 else "drop"
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'sudden_change:{indicator.name}',
                severity=Severity.HIGH,
                reason=f"{indicator.name} sudden {direction} detected",
                axiom=Axiom.HOMEOSTASIS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'indicator': indicator.name,
                    'recent_mean': recent_mean,
                    'older_mean': older_mean,
                    'change_magnitude': abs(recent_mean - older_mean),
                    'change_z': change_z,
                },
                confidence=min(1.0, abs(change_z) / 5),
            ))

        return problems

    def get_baseline(
        self,
        entity_id: str,
        indicator_name: str,
        history: ObservationHistory
    ) -> Optional[dict]:
        """
        Get or calculate baseline statistics for an entity/indicator.

        Baseline invalidation via version counter. Baselines are
        recalculated when observation count grows by 50%+ since last cache.
        """
        cache_key = (entity_id, indicator_name)

        if cache_key in self._baseline_cache:
            cached = self._baseline_cache[cache_key]
            # Invalidate if observation count grew significantly
            window = timedelta(days=self.params.homeostasis_baseline_days)
            current_count = len(history.get_values(entity_id, indicator_name, window))
            cached_count = cached.get('observations', 0)
            if cached_count > 0 and current_count < cached_count * 1.5:
                return cached
            # Stale — recalculate below

        # Calculate baseline
        window = timedelta(days=self.params.homeostasis_baseline_days)
        values = history.get_values(entity_id, indicator_name, window)

        if len(values) < self.params.homeostasis_min_samples:
            return None

        historical_values = [v for _, v in values]
        baseline = {
            'mean': float(np.mean(historical_values)),
            'std': float(np.std(historical_values)),
            'min': float(np.min(historical_values)),
            'max': float(np.max(historical_values)),
            'observations': len(historical_values),
        }

        self._baseline_cache[cache_key] = baseline
        return baseline

    def clear_baseline_cache(self):
        """Clear the baseline cache."""
        self._baseline_cache.clear()

    # =========================================================================
    # Domain-specific HOMEOSTASIS Checks (loaded via extensions)
    # =========================================================================

    def run_domain_checks(
        self,
        entity: Entity,
        history: ObservationHistory,
        domain_id: str = "",
    ) -> List[Problem]:
        """Run all registered domain-specific homeostasis checks.

        Accept domain_id to filter extension checks to the correct
        domain. Without this, multi-domain deployments run ALL registered
        extensions on every entity, causing K8s checks on BMC entities.
        """
        from .extensions import extension_registry
        problems = []
        for check_fn in extension_registry.get_homeostasis_checks(domain_id=domain_id):
            try:
                result = check_fn(entity, history)
                if result:
                    problems.extend(result)
            except Exception as e:
                logger.debug(f"Domain homeostasis check error: {e}")
        return problems

    # =========================================================================
    # K8s-specific HOMEOSTASIS Checks (kept for backward compatibility,
    # also registered via K8sHomeostasisExtension)
    # =========================================================================

    def check_replica_mismatch(
        self,
        entity: Entity,
        tolerance_seconds: float = 60.0
    ) -> List[Problem]:
        """
        Check for replica count mismatch.

        Detects:
        - Desired replicas != ready replicas (after grace period)
        """
        problems = []

        if entity.type not in ('Deployment', 'ReplicaSet', 'StatefulSet'):
            return problems

        desired = entity.get_property('replicas', 0)
        ready = entity.get_property('readyReplicas', 0)
        available = entity.get_property('availableReplicas', 0)

        # Allow for scaling operations - check last update time
        last_update = entity.get_property('lastUpdateTime')
        if last_update:
            try:
                if isinstance(last_update, str):
                    last_update = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                age = (datetime.utcnow() - last_update.replace(tzinfo=None)).total_seconds()
                if age < tolerance_seconds:
                    return problems  # Still in grace period
            except (ValueError, TypeError):
                pass

        if desired > 0 and ready < desired:
            missing = desired - ready
            severity = Severity.CRITICAL if ready == 0 else Severity.HIGH
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type='replica_mismatch',
                severity=severity,
                reason=f"Only {ready}/{desired} replicas ready ({missing} missing)",
                axiom=Axiom.HOMEOSTASIS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'desired': desired,
                    'ready': ready,
                    'available': available,
                    'missing': missing,
                },
                confidence=0.95,
            ))

        return problems

    def check_config_drift(
        self,
        entity: Entity,
        desired_config: Dict[str, Any]
    ) -> List[Problem]:
        """
        Check for configuration drift from desired state.

        Detects:
        - Config values that differ from desired specification
        """
        problems = []

        current_config = entity.properties
        drifts = []

        for key, desired_value in desired_config.items():
            current_value = current_config.get(key)
            if current_value != desired_value:
                drifts.append({
                    'key': key,
                    'desired': desired_value,
                    'current': current_value,
                })

        if drifts:
            severity = Severity.HIGH if len(drifts) > 3 else Severity.WARNING
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type='config_drift',
                severity=severity,
                reason=f"Configuration drift detected: {len(drifts)} values differ from desired",
                axiom=Axiom.HOMEOSTASIS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'drift_count': len(drifts),
                    'drifts': drifts[:10],  # Limit to first 10
                },
                confidence=0.9,
            ))

        return problems

    def check_self_healing(
        self,
        entity: Entity,
        history: ObservationHistory,
        recovery_timeout_seconds: float = 300.0
    ) -> List[Problem]:
        """
        Check if self-healing is working.

        Detects:
        - Problems that are not being auto-resolved
        """
        problems = []

        # Get problem detection history
        window = timedelta(hours=1)
        problem_states = history.get_states(entity.id, 'problemDetected', window)

        if not problem_states:
            return problems

        # Look for problems that haven't been resolved
        unresolved = []
        for ts, state in problem_states:
            if isinstance(state, dict):
                detected = state.get('detected', False)
                resolved = state.get('resolved', False)
            else:
                detected = state == 'detected'
                resolved = False

            if detected and not resolved:
                age = (datetime.utcnow() - ts).total_seconds()
                if age > recovery_timeout_seconds:
                    unresolved.append({
                        'timestamp': ts.isoformat(),
                        'age_seconds': age,
                    })

        if unresolved:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type='failed_self_healing',
                severity=Severity.CRITICAL,
                reason=f"{len(unresolved)} problems not auto-resolved after {recovery_timeout_seconds}s",
                axiom=Axiom.HOMEOSTASIS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'unresolved_count': len(unresolved),
                    'timeout_seconds': recovery_timeout_seconds,
                    'oldest_unresolved': unresolved[0] if unresolved else None,
                },
                confidence=0.85,
            ))

        return problems

    def check_oscillating_recovery(
        self,
        entity: Entity,
        history: ObservationHistory,
        max_recovery_attempts: int = 5,
        window_hours: int = 1
    ) -> List[Problem]:
        """
        Check for oscillating recovery (repeated fail/recover cycles).

        Detects:
        - Entity repeatedly failing and recovering (thrashing)
        """
        problems = []

        window = timedelta(hours=window_hours)

        # Check recovery attempts
        recovery_events = history.get_states(entity.id, 'recoveryAttempt', window)

        if len(recovery_events) >= max_recovery_attempts:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type='oscillating_recovery',
                severity=Severity.CRITICAL,
                reason=f"{len(recovery_events)} recovery attempts in {window_hours} hour(s)",
                axiom=Axiom.HOMEOSTASIS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'recovery_attempts': len(recovery_events),
                    'threshold': max_recovery_attempts,
                    'window_hours': window_hours,
                },
                confidence=0.9,
            ))

        # Also check restart count for pods
        if entity.type == 'Pod':
            restart_count = entity.get_property('restartCount', 0)
            if restart_count >= max_recovery_attempts:
                # Check if restarts happened recently
                restart_history = history.get_values(entity.id, 'restartCount', window)
                if restart_history:
                    first_count = restart_history[0][1] if restart_history else 0
                    recent_restarts = restart_count - first_count

                    if recent_restarts >= max_recovery_attempts:
                        problems.append(Problem.from_entity(
                            entity=entity,
                            problem_type='excessive_restarts',
                            severity=Severity.CRITICAL,
                            reason=f"{int(recent_restarts)} restarts in {window_hours} hour(s)",
                            axiom=Axiom.HOMEOSTASIS,
                            source_layer=DetectionLayer.ONTOLOGY,
                            evidence={
                                'recent_restarts': recent_restarts,
                                'total_restarts': restart_count,
                                'threshold': max_recovery_attempts,
                            },
                            confidence=0.95,
                        ))

        return problems

    def check_persistent_degradation(
        self,
        entity: Entity,
        history: ObservationHistory,
        degradation_threshold_seconds: float = 600.0
    ) -> List[Problem]:
        """
        Check for persistent degraded state.

        Detects:
        - Entity stuck in degraded state for too long
        """
        problems = []

        # Get phase/status history
        window = timedelta(seconds=degradation_threshold_seconds * 2)
        phase_states = history.get_states(entity.id, 'phase', window)

        if not phase_states:
            # Check current phase
            current_phase = entity.get_property('phase')
            degraded_phases = {'Degraded', 'Warning', 'Unknown', 'Failed'}

            if current_phase in degraded_phases:
                # Check how long we've been in this state
                created_at = entity.get_property('lastTransitionTime')
                if created_at:
                    try:
                        if isinstance(created_at, str):
                            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        age = (datetime.utcnow() - created_at.replace(tzinfo=None)).total_seconds()

                        if age > degradation_threshold_seconds:
                            problems.append(Problem.from_entity(
                                entity=entity,
                                problem_type='persistent_degradation',
                                severity=Severity.HIGH,
                                reason=f"Stuck in {current_phase} state for {age:.0f}s",
                                axiom=Axiom.HOMEOSTASIS,
                                source_layer=DetectionLayer.ONTOLOGY,
                                evidence={
                                    'phase': current_phase,
                                    'duration_seconds': age,
                                    'threshold_seconds': degradation_threshold_seconds,
                                },
                                confidence=0.8,
                            ))
                    except (ValueError, TypeError):
                        pass
            return problems

        # Analyze phase history for persistent degradation
        degraded_phases = {'Degraded', 'Warning', 'Unknown', 'Failed'}
        degraded_duration = 0
        last_degraded_start = None

        for ts, phase in phase_states:
            if phase in degraded_phases:
                if last_degraded_start is None:
                    last_degraded_start = ts
            else:
                if last_degraded_start:
                    degraded_duration += (ts - last_degraded_start).total_seconds()
                    last_degraded_start = None

        # If still degraded, add time until now
        if last_degraded_start:
            degraded_duration += (datetime.utcnow() - last_degraded_start).total_seconds()

        if degraded_duration > degradation_threshold_seconds:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type='persistent_degradation',
                severity=Severity.HIGH,
                reason=f"Degraded for {degraded_duration:.0f}s total",
                axiom=Axiom.HOMEOSTASIS,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'degraded_duration_seconds': degraded_duration,
                    'threshold_seconds': degradation_threshold_seconds,
                },
                confidence=0.8,
            ))

        return problems

    def check_all(
        self,
        entity: Entity,
        history: ObservationHistory,
        desired_config: Optional[Dict[str, Any]] = None
    ) -> List[Problem]:
        """
        Run all HOMEOSTASIS checks on an entity.

        Runs domain extension checks first, then K8s defaults as fallback.
        """
        # Run domain-specific checks via extension registry
        # Extract domain_id from entity metadata to scope extension checks.
        _domain_id = getattr(entity, 'metadata', {}).get('domain_id', '') if hasattr(entity, 'metadata') else ''
        domain_problems = self.run_domain_checks(entity, history, domain_id=_domain_id)
        problems = list(domain_problems)

        # Fall back to built-in K8s checks if domain checks returned
        # nothing for THIS entity. Previously checked global extension_registry.domains
        # which broke multi-domain deployments (K8s checks skipped when any domain registered).
        # Only run K8s fallback checks for actual K8s entity types.
        # Non-K8s entities (BMC sensors, network devices) should NOT trigger K8s-specific
        # checks like replica_mismatch or config_drift — those produce false positives.
        _K8S_HOMEOSTASIS_TYPES = {
            'Deployment', 'ReplicaSet', 'StatefulSet', 'Pod',
            'DaemonSet', 'Job', 'CronJob', 'Node',
        }
        entity_type_str = getattr(entity.type, 'value', str(entity.type))
        # Gate K8s fallback behind domain_id to prevent false positives
        # for non-K8s domains that happen to have matching type names.
        #
        # see the twin of this comment in responsiveness.py. The
        # `not _domain_id` clause treated an unstamped entity as Kubernetes,
        # so a `Deployment` or `Node` in any other domain silently received
        # replica-mismatch and config-drift checks. It compensated for the
        # stamping gap that an internal ruling fixed; absent now means absent.
        _is_k8s_domain = _domain_id == 'kubernetes'
        if not domain_problems and _is_k8s_domain and entity_type_str in _K8S_HOMEOSTASIS_TYPES:
            problems.extend(self.check_replica_mismatch(entity))
            if desired_config:
                problems.extend(self.check_config_drift(entity, desired_config))
            problems.extend(self.check_self_healing(entity, history))
            problems.extend(self.check_oscillating_recovery(entity, history))
            problems.extend(self.check_persistent_degradation(entity, history))

        return problems
