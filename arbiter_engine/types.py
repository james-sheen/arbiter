"""
Core type definitions for problem detection.

This module defines all enums, dataclasses, and type aliases used throughout
the detection system.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import uuid


# =============================================================================
# Enums
# =============================================================================

class Axiom(str, Enum):
    """The 8 System Health Axioms."""
    STABILITY = "STABILITY"
    BOUNDEDNESS = "BOUNDEDNESS"
    CONNECTIVITY = "CONNECTIVITY"
    CONSISTENCY = "CONSISTENCY"
    RESPONSIVENESS = "RESPONSIVENESS"
    HOMEOSTASIS = "HOMEOSTASIS"
    CONSERVATION = "CONSERVATION"
    MONOTONICITY = "MONOTONICITY"


# the canonical minimum-observation floor per axiom: how many
# observations must exist before that axiom is meaningfully evaluable.
#
# It lives here, beside the enum it keys on, because it is a property of the
# axiom set rather than of any one consumer. It previously existed as three
# separate copies — `history/readiness.py`, and twice inside
# `ontology/reasoner.py` — and **two of the eight values had drifted apart**:
# the reasoner required 10 observations for CONSERVATION and 20 for
# MONOTONICITY, against 1 and 3 in the readiness tracker. The reasoner was
# over-gating both by roughly an order of magnitude, suppressing detection
# long after the axiom could actually have been evaluated.
#
# The values below are the derived ones (amended 2026-07-29), which
# replaced earlier analogised guesses. Each non-obvious floor carries its
# derivation, because a bare number invites exactly the drift that happened.
#
# MUST cover every member of Axiom: consumers iterate `for axiom in Axiom` and
# index this table, so a missing member is a KeyError that takes down the
# readiness pass and the detection pipeline with it. That is not hypothetical —
# CONSERVATION and MONOTONICITY were absent once already.
AXIOM_MINIMUMS = {
    Axiom.STABILITY: 10,
    Axiom.BOUNDEDNESS: 5,
    Axiom.CONNECTIVITY: 1,
    Axiom.CONSISTENCY: 1,
    Axiom.RESPONSIVENESS: 20,
    Axiom.HOMEOSTASIS: 30,
    # Flow balance is INSTANTANEOUS — the check sums inflow against outflow
    # within a single observation — so "both sides sampled" is one observation,
    # not two.
    Axiom.CONSERVATION: 1,
    # The fewest points that can exhibit a reversal: up, up, down.
    Axiom.MONOTONICITY: 3,
}


class Severity(str, Enum):
    """Problem severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    WARNING = "warning"
    INFO = "info"

    @property
    def priority_score(self) -> int:
        """Numeric priority for sorting (lower = more urgent).

        Mirrors ``constants.Severity.priority_score`` so detection-layer
        consumers can sort without importing the project-root constants
        module (preserves layer isolation).

        pre-fix the local severity-order maps in
        a module held from this package and
        a module held from this package were missing ``warning``. Their fallback put WARNING items AFTER INFO,
        inverting urgency. Routing through this property keeps every
        detection-layer consumer aligned with the canonical
        constants.Severity ordering: critical=1, high=2, medium=3,
        warning=3 (same priority as medium), low=4, info=5.
        """
        return {
            Severity.CRITICAL: 1,
            Severity.HIGH: 2,
            Severity.MEDIUM: 3,
            Severity.WARNING: 3,  # Same priority as MEDIUM for sorting
            Severity.LOW: 4,
            Severity.INFO: 5,
        }[self]


class PropertyType(Enum):
    """Inferred property type."""
    UNKNOWN = "unknown"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    TIMESTAMP = "timestamp"
    REFERENCE = "reference"
    ARRAY = "array"
    OBJECT = "object"


class Cardinality(str, Enum):
    """Relationship cardinality."""
    ONE_TO_ONE = "1:1"
    ONE_TO_MANY = "1:N"
    MANY_TO_ONE = "N:1"
    MANY_TO_MANY = "N:M"


class IndicatorType(str, Enum):
    """Health indicator types."""
    NUMERIC = "numeric"
    STATE = "state"
    RELATIONSHIP = "relationship"
    TIMESTAMP = "timestamp"


class DetectionLayer(str, Enum):
    """Detection layer identifiers."""
    CONSTRAINTS = "constraints"
    ONTOLOGY = "ontology"
    STATISTICAL = "statistical"
    LLM = "llm"


class DomainStatus(str, Enum):
    """Status of a domain in the orchestrator."""
    DISCOVERED = "discovered"
    LEARNING = "learning"
    ACTIVE = "active"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class SuggestionStatus(str, Enum):
    """Status of an improvement suggestion."""
    PENDING = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


# =============================================================================
# Causal Discovery Dataclasses
# =============================================================================

@dataclass
class IORelationship:
    """Discovered input/output relationship between entities."""
    input_entity_type: str
    output_entity_type: str
    input_property: str
    output_property: str
    correlation: float = 0.0
    lag_seconds: float = 0.0
    granger_p_value: float = 1.0
    confidence: float = 0.0
    llm_validated: bool = False
    validation_reason: str = ""


# =============================================================================
# Incident & Feedback Dataclasses
# =============================================================================

@dataclass
class Incident:
    """An externally reported incident."""
    id: str
    entity_id: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    description: str = ""
    severity: Severity = Severity.MEDIUM
    reported_by: str = ""
    root_cause: Optional[str] = None


@dataclass
class Improvement:
    """A suggested improvement to detection."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    improvement_type: str = ""  # 'threshold_adjustment', 'new_indicator', 'new_constraint'
    target: str = ""
    current_value: Any = None
    suggested_value: Any = None
    rationale: str = ""
    confidence: float = 0.0
    source: str = ""  # 'false_negative_analysis', 'near_miss', 'llm_suggestion'


@dataclass
class DownstreamFailure:
    """A failure reported from downstream systems."""
    id: str
    timestamp: datetime
    failure_type: str
    affected_service: str
    description: str = ""
    user_impact: str = ""


@dataclass
class PotentialCause:
    """A potential upstream cause for a downstream failure."""
    entity_id: str
    property_name: str
    anomaly_score: float
    timestamp: datetime
    time_before_failure: float  # seconds
    was_detected: bool = False


@dataclass
class Suggestion:
    """A suggestion for improving detection."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = ""  # 'new_constraint', 'ontology_threshold', 'new_pattern'
    suggested_constraint: Optional[Dict] = None
    suggested_ontology_update: Optional[Dict] = None
    problem: Optional[Dict] = None
    timestamp: str = ""
    status: SuggestionStatus = SuggestionStatus.PENDING
    rejection_reason: Optional[str] = None


@dataclass
class NearMiss:
    """A detection that was close to a threshold."""
    entity_id: str
    property_name: str
    value: float
    threshold: float
    threshold_type: str  # 'warning', 'critical'
    ratio: float  # value / threshold
    timestamp: datetime


@dataclass
class MissedSignal:
    """A signal that was missed by detection."""
    entity_id: str
    property_name: str
    anomaly_score: float
    timestamp: datetime
    incident_id: Optional[str] = None


# =============================================================================
# Axiom Parameters
# =============================================================================

@dataclass
class AxiomParameters:
    """Parameters for axiom detection."""
    # STABILITY
    stability_window_size: int = 10
    stability_epsilon: float = 0.1
    stability_delta: float = 0.3
    stability_oscillation_threshold: float = 0.5

    # BOUNDEDNESS
    boundedness_trend_min_r2: float = 0.7
    boundedness_warning_ratio: float = 0.8
    boundedness_critical_ratio: float = 0.95
    boundedness_time_to_critical_hours: float = 1.0

    # HOMEOSTASIS
    homeostasis_z_warning: float = 2.0
    homeostasis_z_critical: float = 3.0
    homeostasis_min_samples: int = 30
    homeostasis_baseline_days: int = 7

    # RESPONSIVENESS
    responsiveness_min_correlation: float = 0.3
    responsiveness_max_lag_seconds: float = 60.0
    responsiveness_correlation_drop_threshold: float = 0.3
    responsiveness_latency_spike_factor: float = 3.0

    # CONNECTIVITY
    connectivity_grace_period_seconds: float = 60.0

    # CONSISTENCY
    # The universal rules (count >= 0, percentage 0-100, ratio 0-1) have nothing
    # to tune. The cross-signal rule does: how far two readings that are
    # DECLARED redundant may drift before their disagreement is a finding.
    # Relative, and the same 5% the conservation loss margin uses — not because
    # the two quantities are related but because a fallback nobody chose should
    # at least be the one already in the file.
    consistency_agreement_tolerance: float = 0.05

    # CONSERVATION
    conservation_loss_margin: float = 0.05      # 5% acceptable loss
    conservation_window_seconds: float = 300.0  # 5-minute accounting window
    # was 10, against a derived floor of 1. Every count gate below
    # MUST default to its AXIOM_MINIMUMS entry: readiness is reported from that
    # table but enforced here, so a stricter default silently advertises an
    # axiom as live while the checker returns before evaluating anything. That
    # is what an internal ruling removed from the reasoner and what survived, unnoticed,
    # one layer down. `test_axiom_gate_correspondence_cd1544` pins the equality.
    conservation_min_samples: int = 1
    # traverser cycle-flow-balance residual sensitivity (distinct
    # from the axiom-checker loss margin above; per-entity-overridable via
    # resolve_axiom_threshold so the A-1 retro-spike can tune the residual).
    conservation_flow_deficit_warn: float = 0.05   # deficit_ratio fire threshold
    conservation_flow_deficit_high: float = 0.20   # deficit_ratio HIGH-severity boundary

    # MONOTONICITY
    # the gate and the window are separate concerns and used to be
    # one number. `window_size` is how far back to look; `min_samples` is how
    # much must exist before looking at all, and equals the derived floor
    # (fewest points that can exhibit a reversal: up, up, down). You can look
    # at the last 20 observations while holding 5.
    monotonicity_min_samples: int = 3
    monotonicity_window_size: int = 20
    monotonicity_reversal_threshold: int = 3    # reversals before alert
    monotonicity_rate_warning: float = 0.1      # rate of change warning
    monotonicity_rate_critical: float = 0.5     # rate of change critical


@dataclass
class AxiomReadiness:
    """Readiness status for an axiom on an entity."""
    axiom: Axiom
    entity_id: str
    entity_type: str
    observations_count: int
    required_count: int
    is_ready: bool
    readiness_ratio: float
    first_observation: Optional[datetime] = None
    last_observation: Optional[datetime] = None


class NotEvaluatedReason(str, Enum):
    """Why an axiom check declined to evaluate.

    Deliberately a small, closed, domain-agnostic set: these are
    properties of the *engine's* evaluation contract, not of any domain. A
    reason that can only arise in one domain does not belong here — it belongs
    in ``detail``.
    """

    INSUFFICIENT_SAMPLES = "insufficient_samples"
    MISSING_PROPERTY = "missing_property"
    # reported from outside as issue #2. `MISSING_PROPERTY` was doing
    # duty for two states that are not the same answer: the value was never
    # supplied, and the value was supplied to the OTHER store. The engine holds
    # two, and threshold axioms read `Entity.properties` while temporal axioms
    # read observation history.
    #
    # Told apart, the second is worse than unactionable. It told a caller
    # holding sixty in-window observations of `level_pct` that there was `no
    # value for property level_pct` -- directing them to supply what they had
    # already supplied. And in the SAME session `unconsumed_observations`
    # returned empty, which is this engine positively certifying that every
    # series it holds is read by a declared indicator. Two features of one
    # release, contradicting each other about one property.
    #
    # A closed enum missing a member does not raise. It reclassifies the case
    # as the nearest member and reports it with confidence -- so the fix is the
    # vocabulary, not the wording. Third instance of that shape here.
    NO_CURRENT_VALUE = "no_current_value"
    # the referenced entity TYPE has never been observed, which is a
    # different statement from "this entity lacks a property". It says the
    # model refers to a concept the telemetry does not supply at all, and it
    # is domain-agnostic: any model with a typed relationship can hit it.
    MISSING_ENTITY_TYPE = "missing_entity_type"
    MISSING_CONFIG = "missing_config"
    NO_THRESHOLD = "no_threshold"
    WRONG_INDICATOR_TYPE = "wrong_indicator_type"
    NOT_APPLICABLE = "not_applicable"
    CHECKER_ERROR = "checker_error"


@dataclass(frozen=True)
class NotEvaluated:
    """One axiom-on-indicator evaluation that did not happen, and why.

    Before this, a checker had exactly two things it could say —
    a list of problems, or an empty list — and the empty list meant both
    *checked, nothing wrong* and *could not judge*. Those are different
    answers, and conflating them is the failure the engine's own claims
    discipline exists to prevent: a green result that measured nothing.

    Distinct from :class:`AxiomReadiness`, which is the *pre-flight* question
    (does this entity have enough observations for this axiom, computed from
    history) and is keyed on ``(axiom, entity)``. This is the *per-check*
    answer, keyed on ``(axiom, entity, indicator)``, and it covers reasons
    readiness cannot see — absent configuration, an indicator of the wrong
    type, or a checker that raised. The two share ``observations_count`` and
    ``required_count`` field names on purpose, so an insufficient-samples
    record reads the same way in both.

    Note what this does NOT change: coverage questions are still answered from
    domain declarations. A ``NotEvaluated`` records what *one run* skipped,
    which is a fact about the data and the configuration at that moment. It
    says nothing about what a domain declares, and must not be summed into a
    coverage claim.
    """

    axiom: Axiom
    entity_id: str
    entity_type: str
    indicator: str
    reason: NotEvaluatedReason
    detail: str = ""
    observations_count: Optional[int] = None
    required_count: Optional[int] = None

    # `observations_count` is counted INSIDE the evaluation window;
    # `required_count` is a global floor. Reporting them as a bare ratio
    # invites the reading "collect more data", which can be false: with a
    # 1-hour window and a floor of 3, an indicator sampled daily reports
    # `0 of 3` forever, and there may be hundreds of observations just
    # outside the window. These three make the window visible so the ratio
    # is interpretable, and `floor_unreachable_at_this_rate` states the
    # conclusion rather than leaving the reader to derive it.
    window_seconds: Optional[float] = None
    total_observations: Optional[int] = None
    sampling_interval_seconds: Optional[float] = None

    @property
    def floor_unreachable_at_this_rate(self) -> bool:
        """True when no amount of further collection can meet the floor.

        Spanning ``required_count`` samples takes ``(required_count - 1)``
        intervals; if that exceeds the window, the floor is arithmetically
        unreachable at the observed rate and more data will not help. False
        when any input is unknown — this must never assert unreachability it
        has not computed.
        """
        if not (self.window_seconds and self.required_count
                and self.sampling_interval_seconds):
            return False
        span = (self.required_count - 1) * self.sampling_interval_seconds
        return span > self.window_seconds

