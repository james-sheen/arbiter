"""AxiomVerdict production-readiness substrate (chain head).

Production-readiness substrate for the 8 canonical axiom checkers at
arbiter_engine/ontology/axioms/ (HOMEOSTASIS / RESPONSIVENESS / MONOTONICITY /
BOUNDEDNESS / CONSISTENCY / CONSERVATION / CAUSALITY / PREDICTION_QUALITY).

Per sibling-within-module precedent: axioms/ dir hosts 8
sibling checker modules with no single shared parent module suitable for
sibling extension. ships substrate at new standalone module
(parent = `arbiter_engine/ontology/`, sibling to `axioms/` package) rather
than mutate any individual checker. The sibling-substrate
discipline preserved (substrate sibling at axis-parent level rather than
single-module level).

Adds per-verdict production recording + 5 production-readiness public
functions + a default-off env-gate. Composes the hybrid
emit-policy decision (transition OR confidence_threshold gate) +
attestation severity floor + NaturalCategoryDispatcher
(emit_policy axis dispatch via existing 9th canonical axis added; no new axis).

A sibling substrate within an existing module, at axis-parent level rather
than single-module level — which is what distinguishes it from the variant
that extends single modules.

Domain-agnostic: axiom_name + entity_id + verdict + confidence scalars
opaque; no per-domain dispatch.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterator, List, Optional


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "1" if default else "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


DT_AXIOM_VERDICT_PRODUCTION_ENABLED: bool = _env_bool(
    "DT_AXIOM_VERDICT_PRODUCTION_ENABLED", default=False
)
DT_AXIOM_VERDICT_PRODUCTION_RING_CAP: int = int(
    os.environ.get("DT_AXIOM_VERDICT_PRODUCTION_RING_CAP", "10000")
)
DT_AXIOM_VERDICT_CONFIDENCE_THRESHOLD: float = float(
    os.environ.get("DT_AXIOM_VERDICT_CONFIDENCE_THRESHOLD", "0.5")
)

# Per hybrid emit-policy default
PRODUCTION_AXIOM_VERDICT_EMIT_POLICY_HYBRID: str = "hybrid"
PRODUCTION_AXIOM_VERDICT_EMIT_POLICY_FULL_EMIT: str = "full_emit"
PRODUCTION_AXIOM_VERDICT_EMIT_POLICY_SUPPRESSED: str = "suppressed"
KNOWN_PRODUCTION_AXIOM_VERDICT_EMIT_POLICIES = frozenset([
    PRODUCTION_AXIOM_VERDICT_EMIT_POLICY_HYBRID,
    PRODUCTION_AXIOM_VERDICT_EMIT_POLICY_FULL_EMIT,
    PRODUCTION_AXIOM_VERDICT_EMIT_POLICY_SUPPRESSED,
])
DEFAULT_PRODUCTION_AXIOM_VERDICT_EMIT_POLICY: str = (
    PRODUCTION_AXIOM_VERDICT_EMIT_POLICY_HYBRID
)

# The 8 canonical axiom names per arbiter_engine/ontology/axioms/*.py
KNOWN_CANONICAL_AXIOMS = frozenset([
    "HOMEOSTASIS",
    "RESPONSIVENESS",
    "MONOTONICITY",
    "BOUNDEDNESS",
    "CONSISTENCY",
    "CONSERVATION",
    "CAUSALITY",
    "PREDICTION_QUALITY",
])


@dataclass(frozen=True)
class ProductionAxiomVerdict:
    """ per-verdict production-readiness axiom-verdict event.

    5 opaque fields domain-agnostic invariant. Frozen for
    audit-trail provenance emit-policy decision.

    added optional ``cluster_id`` for per-axis cluster-scope filtering.
    Default None preserves previously behavior; emission callsites that
    pass cluster_id stamp the record so
    ``get_axiom_verdicts(cluster_id=X)`` can filter. Field added with
    default so existing emissions are backward-compat.
    """

    axiom_name: str
    entity_id: str
    verdict: str  # "PASS" | "FAIL" | "UNKNOWN"
    confidence: float
    emit_policy: str
    cluster_id: Optional[str] = None  # (Bucket A)


def resolve_production_axiom_verdict_emit_policy(value: Optional[str]) -> str:
    """Safe-default to hybrid."""
    if value is None or value not in KNOWN_PRODUCTION_AXIOM_VERDICT_EMIT_POLICIES:
        return DEFAULT_PRODUCTION_AXIOM_VERDICT_EMIT_POLICY
    return value


_PRODUCTION_VERDICTS: List[ProductionAxiomVerdict] = []
_PRODUCTION_LOCK = threading.RLock()
_PRODUCTION_LAST_VERDICT: Dict[tuple, str] = {}  # (entity_id, axiom_name) -> verdict


# ---------- Layer 3 ContextVar emission-scope stamping ----------
#
# `record_axiom_verdict` is called from `arbiter_engine/ontology/reasoner.py`
# inside the per-axiom check loop. That code path does NOT know cluster_id
# at the function-signature level — DetectorInterface.detect() takes
# (entities, graph, history) without cluster_id, and threading cluster_id
# through the detector interface chain is out-of-scope (would touch every
# detector implementation).
#
# Instead, callers in the full system (live loop + Monte Carlo path) wrap
# the detect-call with `cluster_scope(cluster_id)`; the ContextVar
# propagates correctly through async/await chains (asyncio.create_task
# copies the context by default). Inside `record_axiom_verdict`, if the
# explicit `cluster_id` parameter is None, we fall back to reading the
# ContextVar. This is minimal-invasive Layer-3 stamping without rewriting
# the detector contract.
#
# Per the substrate-callsite-gap discipline: the substrate-side ContextVar +
# the caller-side `with cluster_scope(cluster_id):` block together form
# the bridge between substrate-emission and cluster-aware caller context.
_CURRENT_CLUSTER_ID: ContextVar[Optional[str]] = ContextVar(
    "axiom_verdict_cluster_id", default=None,
)


@contextmanager
def cluster_scope(cluster_id: Optional[str]) -> Iterator[None]:
    """ Layer 3 helper: wrap a detect-call so emissions stamp
    cluster_id automatically.

    Usage in the full system:

        with cluster_scope(cluster_id):
            detection_result = await bridge.detect(entities, graph)

    Any `record_axiom_verdict()` calls inside the block — including those
    several frames deep in the detector chain — will pick up cluster_id
    from the ContextVar when their own `cluster_id` parameter is None.
    Explicit parameter still wins (precedence: explicit > ContextVar >
    None). Safe for nested scopes via ContextVar reset.

    cluster_id=None is also valid (no-op scope; preserves backward compat).
    """
    token = _CURRENT_CLUSTER_ID.set(cluster_id)
    try:
        yield
    finally:
        _CURRENT_CLUSTER_ID.reset(token)


def _resolve_cluster_id(explicit: Optional[str]) -> Optional[str]:
    """Resolve effective cluster_id: explicit param > ContextVar > None."""
    if explicit is not None:
        return explicit
    return _CURRENT_CLUSTER_ID.get()


def _wire_composition_for_entity(entity_id: str) -> None:
    """feed an entity's full per-axiom verdict snapshot to the
    axiom-composition wiring at the recording callsite (was callsite-less —
    the substrate-callsite gap).

    Reads the wire-up gate dynamically so it stays byte-identical when
    ``DT_AXIOM_COMPOSITION_WIRING_ENABLED`` is OFF (default): early-return, no
    snapshot build, no state change. When ON, rebuilds the entity's per-axiom
    snapshot from ``_PRODUCTION_LAST_VERDICT`` and registers it so
    ``get_axiom_composition_wired_entity_count()`` becomes nonzero (which is
    what flips ``/dt-axiom-verdicts`` from ``warming_up`` to ``ready``).
    """
    try:
        from arbiter_engine.ontology import (
            axiom_composition_wiring as _acw,
        )
    except Exception:  # noqa: BLE001 — composition wiring not deployed
        return
    if not _acw.DT_AXIOM_COMPOSITION_WIRING_ENABLED:
        return
    with _PRODUCTION_LOCK:
        snapshot = {
            ax: v
            for (eid, ax), v in _PRODUCTION_LAST_VERDICT.items()
            if eid == entity_id
        }
    if snapshot:
        _acw.wire_axiom_composition_for_entity(entity_id, snapshot)


def record_axiom_verdict(
    axiom_name: str,
    entity_id: str,
    verdict: str,
    confidence: float,
    emit_policy: Optional[str] = None,
    cluster_id: Optional[str] = None,
) -> Optional[ProductionAxiomVerdict]:
    """Record an axiom-verdict event at production-readiness shape.

    Returns the stored ProductionAxiomVerdict when gate enabled AND
    emit_policy admits the event; returns None when gate off OR
    emit_policy suppressed OR hybrid mode rejects (verdict-transition OR confidence >= threshold) gate.

    Hybrid mode gate: admits if (a) prior verdict for (entity_id,
    axiom_name) differs from current, OR (b) confidence >= threshold.

    optional ``cluster_id`` stamps the record
    so per-cluster retrieval queries can filter. Default None preserves
    previously emission behavior (callsites that don't pass cluster_id
    still record verdicts — they're then queryable via the global path
    `get_axiom_verdicts()` but excluded from filtered queries).
    """
    if not DT_AXIOM_VERDICT_PRODUCTION_ENABLED:
        return None
    policy = resolve_production_axiom_verdict_emit_policy(emit_policy)
    if policy == PRODUCTION_AXIOM_VERDICT_EMIT_POLICY_SUPPRESSED:
        return None
    key = (entity_id, axiom_name)
    if policy == PRODUCTION_AXIOM_VERDICT_EMIT_POLICY_HYBRID:
        with _PRODUCTION_LOCK:
            prior_verdict = _PRODUCTION_LAST_VERDICT.get(key)
        verdict_transition = (prior_verdict is None) or (prior_verdict != verdict)
        confidence_crosses = float(confidence) >= DT_AXIOM_VERDICT_CONFIDENCE_THRESHOLD
        if not (verdict_transition or confidence_crosses):
            return None
    # Layer 3: explicit cluster_id wins; fall back to ContextVar
    # set by `cluster_scope(cluster_id)` in the caller (typically the full system
    # detect-loop wrapper). None when neither is set (previously path).
    effective_cluster_id = _resolve_cluster_id(cluster_id)
    record = ProductionAxiomVerdict(
        axiom_name=axiom_name,
        entity_id=entity_id,
        verdict=verdict,
        confidence=float(confidence),
        emit_policy=policy,
        cluster_id=effective_cluster_id,
    )
    with _PRODUCTION_LOCK:
        _PRODUCTION_VERDICTS.append(record)
        _PRODUCTION_LAST_VERDICT[key] = verdict
        if len(_PRODUCTION_VERDICTS) > DT_AXIOM_VERDICT_PRODUCTION_RING_CAP:
            del _PRODUCTION_VERDICTS[
                : len(_PRODUCTION_VERDICTS) - DT_AXIOM_VERDICT_PRODUCTION_RING_CAP
            ]
    # land the previously-callsite-less axiom-composition wire so
    # composition_wired_count can be nonzero. Self-gated on
    # DT_AXIOM_COMPOSITION_WIRING_ENABLED (default OFF -> no-op, byte-identical).
    _wire_composition_for_entity(entity_id)
    return record


def _filter_by_cluster_id(
    verdicts: List[ProductionAxiomVerdict],
    cluster_id: Optional[str],
) -> List[ProductionAxiomVerdict]:
    """ helper: filter verdicts by cluster_id when non-None.

    cluster_id=None returns the full list (backward compat).
    cluster_id="X" returns only verdicts with v.cluster_id == "X".
    Verdicts emitted previously have cluster_id=None and are
    excluded from any non-None filter (signaling "not scoped").
    Mirror of the RCA `_filter_by_cluster_id` pattern.
    """
    if cluster_id is None:
        return verdicts
    return [v for v in verdicts if v.cluster_id == cluster_id]


def get_axiom_verdicts(
    cluster_id: Optional[str] = None,
) -> List[ProductionAxiomVerdict]:
    """All recorded production axiom-verdict records. Empty when gate off.

    optional ``cluster_id`` filter. None = all (backward compat);
    string value returns only verdicts stamped with that cluster_id.
    """
    if not DT_AXIOM_VERDICT_PRODUCTION_ENABLED:
        return []
    with _PRODUCTION_LOCK:
        all_verdicts = list(_PRODUCTION_VERDICTS)
    return _filter_by_cluster_id(all_verdicts, cluster_id)


def get_axiom_verdict_count(cluster_id: Optional[str] = None) -> int:
    """Aggregate count of recorded production axiom-verdict records.

    Dashboard-data defensive-accessor entry point. Returns 0 when gate off.

    optional ``cluster_id`` filter. None = aggregate count;
    string value returns count of verdicts stamped with that cluster_id.
    """
    if not DT_AXIOM_VERDICT_PRODUCTION_ENABLED:
        return 0
    return len(get_axiom_verdicts(cluster_id=cluster_id))


def get_latest_verdict_for_entity(
    entity_id: str, axiom_name: str,
) -> Optional[str]:
    """Last-known verdict for (entity_id, axiom_name); None when unknown
    or gate off."""
    if not DT_AXIOM_VERDICT_PRODUCTION_ENABLED:
        return None
    with _PRODUCTION_LOCK:
        return _PRODUCTION_LAST_VERDICT.get((entity_id, axiom_name))


def known_verdict_axioms() -> List[str]:
    """Diagnostic accessor — sorted unique axiom_name values."""
    if not DT_AXIOM_VERDICT_PRODUCTION_ENABLED:
        return []
    with _PRODUCTION_LOCK:
        return sorted({r.axiom_name for r in _PRODUCTION_VERDICTS})


def _reset_production_verdicts_for_tests() -> None:
    with _PRODUCTION_LOCK:
        _PRODUCTION_VERDICTS.clear()
        _PRODUCTION_LAST_VERDICT.clear()
