"""ProductionObservation production-readiness substrate (chain head).

Production-readiness substrate for the observation foundation modules at
a module held from this package (Redis Streams consumer) +
arbiter_engine/history/observation.py (InMemoryObservationHistory).

sibling-within-package precedent:
history/ dir hosts observation.py + readiness.py sibling modules with no
single shared parent module suitable for sibling extension. ships
substrate at new standalone module sibling-within-package (parent =
`arbiter_engine/history/`, sibling to `observation.py` + `readiness.py`) rather
than mutate any individual foundation module. an established pattern
sibling-substrate-at-axis-parent-level variant.

Adds per-observation production recording + 5 production-readiness public
functions + an established pattern env-gate. Composes hybrid
emit-policy decision (source-health-transition OR freshness_age >
threshold gate) + attestation severity floor +
NaturalCategoryDispatcher (emit_policy axis dispatch via existing 9th
canonical axis added; no new axis).

Domain-agnostic: observation_id + source_id + freshness_age_seconds
scalars opaque; no per-domain dispatch.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime
from ..clock import as_naive_utc, now_utc

from typing import Dict, List, Optional


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "1" if default else "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


DT_OBSERVATION_PRODUCTION_ENABLED: bool = _env_bool(
    "DT_OBSERVATION_PRODUCTION_ENABLED", default=False
)
DT_OBSERVATION_PRODUCTION_RING_CAP: int = int(
    os.environ.get("DT_OBSERVATION_PRODUCTION_RING_CAP", "10000")
)
DT_OBSERVATION_FRESHNESS_THRESHOLD_SECONDS: float = float(
    os.environ.get("DT_OBSERVATION_FRESHNESS_THRESHOLD_SECONDS", "60")
)

# Per hybrid emit-policy default
PRODUCTION_OBSERVATION_EMIT_POLICY_HYBRID: str = "hybrid"
PRODUCTION_OBSERVATION_EMIT_POLICY_FULL_EMIT: str = "full_emit"
PRODUCTION_OBSERVATION_EMIT_POLICY_SUPPRESSED: str = "suppressed"
KNOWN_PRODUCTION_OBSERVATION_EMIT_POLICIES = frozenset([
    PRODUCTION_OBSERVATION_EMIT_POLICY_HYBRID,
    PRODUCTION_OBSERVATION_EMIT_POLICY_FULL_EMIT,
    PRODUCTION_OBSERVATION_EMIT_POLICY_SUPPRESSED,
])
DEFAULT_PRODUCTION_OBSERVATION_EMIT_POLICY: str = (
    PRODUCTION_OBSERVATION_EMIT_POLICY_HYBRID
)

# Per-source health-state vocabulary
SOURCE_HEALTH_HEALTHY: str = "healthy"
SOURCE_HEALTH_STALE: str = "stale"


@dataclass(frozen=True)
class ProductionObservation:
    """ per-observation production-readiness event.

    5 opaque fields domain-agnostic invariant. Frozen for
    audit-trail provenance emit-policy decision.
    """

    observation_id: str
    source_id: str
    freshness_age_seconds: float
    observed_at: datetime
    emit_policy_per_cd1109: str
    cluster_id: Optional[str] = None  # (Bucket A) per-axis cluster-scope


def resolve_production_observation_emit_policy(value: Optional[str]) -> str:
    """Safe-default to hybrid."""
    if value is None or value not in KNOWN_PRODUCTION_OBSERVATION_EMIT_POLICIES:
        return DEFAULT_PRODUCTION_OBSERVATION_EMIT_POLICY
    return value


# ---------------------------------------------------------------------------
# the ingest heartbeat.
#
# Separate from the ring ON PURPOSE. The ring answers "what was notable" and,
# under the default `hybrid` policy, records only health-state TRANSITIONS — so
# a healthy steady feed writes nothing and any liveness threshold on it produces
# false STALE. Measured on the reference VPS 2026-08-04 with the scraper running normally:
# observation_count=4, seconds_since_last_observation=208.
#
# This counter answers the ordinary question instead: "is anything arriving at
# all". It is bumped UPSTREAM of the emit-policy gate, because that gate is
# precisely what makes the ring unusable here — a heartbeat downstream of it
# would inherit the same silence.
# ---------------------------------------------------------------------------
_INGEST_COUNT_TOTAL: int = 0
_LAST_INGEST_AT: Optional[datetime] = None


# ---------------------------------------------------------------------------
# WHO is ingesting?
#
# With the scraper stopped, `ingest_count_total` stayed flat for 57-90s and then
# jumped in one batch (+24, then +48 — the size scaling with the wait). So a
# second producer, or a buffered path, reaches observation history. The call
# graph does not answer it: `record_observation` has exactly ONE production
# caller (`InMemoryObservationHistory.add`), and that is not the answer, it is
# the funnel everything passes through.
#
# So: tag the real caller at runtime and count. Default OFF (the established pattern) —
# frame inspection on every ingest is not something to leave on by accident.
# ---------------------------------------------------------------------------
DT_INGEST_CALLER_TAG_ENABLED: bool = (
    os.environ.get("DT_INGEST_CALLER_TAG_ENABLED", "0") not in ("0", "false", "False")
)

# Frames inside the ingest funnel itself; the interesting caller is above these.
_FUNNEL_MODULES = (
    "detection.history.observation_production",
    "detection.history.observation",
)

_INGEST_CALLER_TAGS: Dict[str, int] = {}


def _classify_ingest_caller() -> str:
    """Walk up until we leave the funnel; return `module:qualname` of the caller.

    Returns a sentinel rather than raising: an instrumentation failure must not
    break ingest, and must be VISIBLE in the distribution rather than silently
    attributed to some other bucket.
    """
    try:
        import sys as _sys
        frame = _sys._getframe(1)
        depth = 0
        while frame is not None and depth < 30:
            mod = frame.f_globals.get("__name__", "")
            if not any(f in mod for f in _FUNNEL_MODULES):
                fn = frame.f_code.co_name
                return "%s:%s" % (mod, fn)
            frame = frame.f_back
            depth += 1
        return "<funnel-only:no-external-caller>"
    except Exception:  # noqa: BLE001
        return "<classify-failed>"


def get_ingest_caller_tags() -> Dict[str, int]:
    """Ingest counts by calling site. Empty when the gate is off."""
    with _PRODUCTION_LOCK:
        return dict(_INGEST_CALLER_TAGS)


def reset_ingest_caller_tags_for_test() -> None:
    global _INGEST_CALLER_TAGS
    with _PRODUCTION_LOCK:
        _INGEST_CALLER_TAGS = {}


def _bump_ingest_heartbeat(now: Optional[datetime] = None) -> None:
    """Record that an ingest reached the substrate. Unconditional by design."""
    global _INGEST_COUNT_TOTAL, _LAST_INGEST_AT
    tag = _classify_ingest_caller() if DT_INGEST_CALLER_TAG_ENABLED else None
    with _PRODUCTION_LOCK:
        _INGEST_COUNT_TOTAL += 1
        _LAST_INGEST_AT = as_naive_utc(now) if now else now_utc()
        if tag is not None:  #
            _INGEST_CALLER_TAGS[tag] = _INGEST_CALLER_TAGS.get(tag, 0) + 1


def get_ingest_count_total() -> int:
    """Total ingests seen since process start, regardless of emit policy."""
    return _INGEST_COUNT_TOTAL


def get_seconds_since_last_ingest() -> Optional[float]:
    """Seconds since the last ingest, or None if none has ever arrived.

    None must be read as "nothing yet", NOT as "stale" — a consumer that
    conflates them reports a cold start as an outage.
    """
    if _LAST_INGEST_AT is None:
        return None
    return max(0.0, (now_utc() - _LAST_INGEST_AT).total_seconds())


def reset_ingest_heartbeat_for_test() -> None:
    """Test-only. Module-level state that nothing resets is what made the
     ordering bug possible; this exists so pins cannot poison each other."""
    global _INGEST_COUNT_TOTAL, _LAST_INGEST_AT
    with _PRODUCTION_LOCK:
        _INGEST_COUNT_TOTAL = 0
        _LAST_INGEST_AT = None


def _derive_source_health(freshness_age_seconds: float) -> str:
    """Source is healthy when fresh, stale when over threshold."""
    if freshness_age_seconds > DT_OBSERVATION_FRESHNESS_THRESHOLD_SECONDS:
        return SOURCE_HEALTH_STALE
    return SOURCE_HEALTH_HEALTHY


_PRODUCTION_OBSERVATIONS: List[ProductionObservation] = []
_PRODUCTION_LOCK = threading.RLock()
_PRODUCTION_LAST_HEALTH: Dict[str, str] = {}  # source_id -> health_state


def record_observation(
    observation_id: str,
    source_id: str,
    freshness_age_seconds: float,
    observed_at: Optional[datetime] = None,
    emit_policy: Optional[str] = None,
    cluster_id: Optional[str] = None,
) -> Optional[ProductionObservation]:
    """Record an observation event at production-readiness shape.

    Returns the stored ProductionObservation when gate enabled AND
    emit_policy admits the event; returns None when gate off OR
    emit_policy suppressed OR hybrid mode rejects (source-health-transition OR freshness_age > threshold) gate.

    Hybrid mode gate: admits if (a) prior health-state for source_id
    differs from current (derived from freshness_age vs threshold), OR
    (b) freshness_age > threshold (stale).
    """
    if not DT_OBSERVATION_PRODUCTION_ENABLED:
        return None
    # heartbeat FIRST. Every ingest that reaches a live substrate counts,
    # whatever the policy then decides to store. Moving this below the policy
    # check would reproduce the exact silence it exists to detect.
    _bump_ingest_heartbeat(observed_at)
    policy = resolve_production_observation_emit_policy(emit_policy)
    if policy == PRODUCTION_OBSERVATION_EMIT_POLICY_SUPPRESSED:
        return None
    ts = as_naive_utc(observed_at) if observed_at else now_utc()
    current_health = _derive_source_health(freshness_age_seconds)
    if policy == PRODUCTION_OBSERVATION_EMIT_POLICY_HYBRID:
        with _PRODUCTION_LOCK:
            prior_health = _PRODUCTION_LAST_HEALTH.get(source_id)
        health_transition = (prior_health is None) or (prior_health != current_health)
        freshness_stale = current_health == SOURCE_HEALTH_STALE
        if not (health_transition or freshness_stale):
            return None
    record = ProductionObservation(
        observation_id=observation_id,
        source_id=source_id,
        freshness_age_seconds=float(freshness_age_seconds),
        observed_at=ts,
        emit_policy_per_cd1109=policy,
        cluster_id=cluster_id,  # (Bucket A)
    )
    with _PRODUCTION_LOCK:
        _PRODUCTION_OBSERVATIONS.append(record)
        _PRODUCTION_LAST_HEALTH[source_id] = current_health
        if len(_PRODUCTION_OBSERVATIONS) > DT_OBSERVATION_PRODUCTION_RING_CAP:
            del _PRODUCTION_OBSERVATIONS[
                : len(_PRODUCTION_OBSERVATIONS) - DT_OBSERVATION_PRODUCTION_RING_CAP
            ]
    return record


def _filter_by_cluster_id_cd1436(
    observations: List[ProductionObservation],
    cluster_id: Optional[str],
) -> List[ProductionObservation]:
    """ helper: filter observations by cluster_id when non-None.

    cluster_id=None returns the full list (backward compat). cluster_id="X"
    returns only observations with ``o.cluster_id == "X"``. Records emitted
    previously (or from cross-cluster merge / transient histories) carry
    cluster_id=None and are excluded from a specific-cluster query. Mirror
    of the RCA / axiom_verdicts pattern.
    """
    if cluster_id is None:
        return list(observations)
    return [o for o in observations if o.cluster_id == cluster_id]


def get_observations(cluster_id: Optional[str] = None) -> List[ProductionObservation]:
    """All recorded production observation records. Empty when gate off.

    optional ``cluster_id`` filter. None = all (backward compat);
    string value returns only observations stamped with that cluster_id.
    """
    if not DT_OBSERVATION_PRODUCTION_ENABLED:
        return []
    with _PRODUCTION_LOCK:
        return _filter_by_cluster_id_cd1436(_PRODUCTION_OBSERVATIONS, cluster_id)


def get_observation_count(cluster_id: Optional[str] = None) -> int:
    """Aggregate count of recorded production observation records.

    Dashboard-data defensive-accessor entry point + Pattern
    171. Returns 0 when gate off.

    optional ``cluster_id`` filter. None = aggregate count;
    string value returns count of observations stamped with that cluster_id.
    """
    if not DT_OBSERVATION_PRODUCTION_ENABLED:
        return 0
    with _PRODUCTION_LOCK:
        return len(_filter_by_cluster_id_cd1436(_PRODUCTION_OBSERVATIONS, cluster_id))


def get_freshness_for_source(source_id: str) -> Optional[str]:
    """Last-known health-state for source_id; None when unknown or gate off."""
    if not DT_OBSERVATION_PRODUCTION_ENABLED:
        return None
    with _PRODUCTION_LOCK:
        return _PRODUCTION_LAST_HEALTH.get(source_id)


def known_observation_sources() -> List[str]:
    """Diagnostic accessor — sorted unique source_id values."""
    if not DT_OBSERVATION_PRODUCTION_ENABLED:
        return []
    with _PRODUCTION_LOCK:
        return sorted({r.source_id for r in _PRODUCTION_OBSERVATIONS})


def _reset_production_observations_for_tests() -> None:
    with _PRODUCTION_LOCK:
        _PRODUCTION_OBSERVATIONS.clear()
        _PRODUCTION_LAST_HEALTH.clear()
