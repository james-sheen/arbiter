"""Greedy set cover for root cause identification.

Extracted from arbiter_engine/propagation/root_cause.py and arbiter_engine/twin/traverser.py
which both implemented identical greedy set cover logic.
"""
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple


@dataclass
class SetCoverResult:
    """Result of greedy set cover."""
    selected: List[Tuple[str, FrozenSet[str], float]] = field(default_factory=list)
    # (candidate_id, covered_set, score)
    uncovered: FrozenSet[str] = field(default_factory=frozenset)
    coverage_ratio: float = 0.0


def greedy_set_cover(
    candidates: Dict[str, Set[str]],
    universe: Set[str],
    scores: Optional[Dict[str, float]] = None,
    max_selected: int = 10,
    min_coverage: float = 1.0,
) -> SetCoverResult:
    """Standard greedy set cover with score-based tiebreaking.

    Args:
        candidates: Mapping candidate_id -> set of elements it covers.
        universe: The full set of elements to cover.
        scores: Optional tiebreaker scores per candidate (higher = preferred).
        max_selected: Maximum candidates to select.
        min_coverage: Stop when coverage ratio >= this value.

    Returns:
        SetCoverResult with selected candidates and coverage info.
    """
    if not universe:
        return SetCoverResult(
            selected=[],
            uncovered=frozenset(),
            coverage_ratio=1.0,
        )

    scores = scores or {}
    uncovered = set(universe)
    selected: List[Tuple[str, FrozenSet[str], float]] = []

    while uncovered and len(selected) < max_selected:
        best_id: Optional[str] = None
        best_coverage: FrozenSet[str] = frozenset()
        best_count = 0
        best_score = -1.0

        for cid, cover_set in candidates.items():
            if any(s[0] == cid for s in selected):
                continue  # already selected
            new_coverage = cover_set & uncovered
            count = len(new_coverage)
            score = scores.get(cid, 0.0)
            if count > best_count or (
                count == best_count and count > 0 and score > best_score
            ):
                best_id = cid
                best_coverage = frozenset(new_coverage)
                best_count = count
                best_score = score

        if best_id is None or best_count == 0:
            break

        selected.append((best_id, best_coverage, best_score))
        uncovered -= best_coverage

        coverage_ratio = 1.0 - (len(uncovered) / len(universe))
        if coverage_ratio >= min_coverage:
            break

    final_ratio = 1.0 - (len(uncovered) / len(universe))
    return SetCoverResult(
        selected=selected,
        uncovered=frozenset(uncovered),
        coverage_ratio=final_ratio,
    )


# ============================================================
# — RootCauseIdentifier production-readiness substrate
# ============================================================
# Re-activates RCA axis-25 substrate (RootCauseIdentifier
# foundation; greedy_set_cover above + the analyzer, causal_graph,
# evidence_collector and report_generator foundation modules) at
# production-readiness shape hybrid
# emit-policy decision. Adds per-candidate production recording + 5
# production-readiness public methods + a default-off env-gate. Composes attestation severity floor +
# NaturalCategoryDispatcher (emit_policy axis dispatch via existing 9th
# canonical axis added) + emit-policy.

import os
import threading


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "1" if default else "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


DT_RCA_PRODUCTION_ENABLED: bool = _env_bool(
    "DT_RCA_PRODUCTION_ENABLED", default=False
)
DT_RCA_PRODUCTION_RING_CAP: int = int(
    os.environ.get("DT_RCA_PRODUCTION_RING_CAP", "10000")
)
DT_RCA_TOP_N: int = int(os.environ.get("DT_RCA_TOP_N", "10"))
DT_RCA_CONFIDENCE_THRESHOLD: float = float(
    os.environ.get("DT_RCA_CONFIDENCE_THRESHOLD", "0.5")
)

# Per hybrid emit-policy default
PRODUCTION_RCA_EMIT_POLICY_HYBRID: str = "hybrid"
PRODUCTION_RCA_EMIT_POLICY_FULL_RANKING: str = "full_ranking"
PRODUCTION_RCA_EMIT_POLICY_SUPPRESSED: str = "suppressed"
KNOWN_PRODUCTION_RCA_EMIT_POLICIES = frozenset([
    PRODUCTION_RCA_EMIT_POLICY_HYBRID,
    PRODUCTION_RCA_EMIT_POLICY_FULL_RANKING,
    PRODUCTION_RCA_EMIT_POLICY_SUPPRESSED,
])
DEFAULT_PRODUCTION_RCA_EMIT_POLICY: str = PRODUCTION_RCA_EMIT_POLICY_HYBRID


@dataclass(frozen=True)
class ProductionRCACandidate:
    """ per-candidate production-readiness RCA record.

    5 opaque fields domain-agnostic invariant. Frozen for
    audit-trail provenance emit-policy decision.

    added optional ``cluster_id`` for per-axis
    cluster-scope filtering. Default None preserves previously behavior;
    emission callsites that pass cluster_id stamp the record so
    ``get_rca_candidates(cluster_id=X)`` can filter. Field added with
    default so existing emissions are backward-compat.
    """

    candidate_id: str
    target_entity: str
    confidence_score: float
    supporting_evidence_count: int
    emit_policy: str
    cluster_id: Optional[str] = None  #


def resolve_production_rca_emit_policy(value: Optional[str]) -> str:
    """Safe-default to hybrid."""
    if value is None or value not in KNOWN_PRODUCTION_RCA_EMIT_POLICIES:
        return DEFAULT_PRODUCTION_RCA_EMIT_POLICY
    return value


_PRODUCTION_CANDIDATES: List[ProductionRCACandidate] = []
_PRODUCTION_LOCK = threading.Lock()


def record_rca_candidate(
    candidate_id: str,
    target_entity: str,
    confidence_score: float,
    supporting_evidence_count: int = 0,
    emit_policy: Optional[str] = None,
    cluster_id: Optional[str] = None,
) -> Optional[ProductionRCACandidate]:
    """Record an RCA candidate at production-readiness shape.

    Returns the stored ProductionRCACandidate when gate enabled AND
    emit_policy admits the candidate; returns None when gate off OR
    emit_policy suppressed OR hybrid mode rejects per confidence-threshold
    gate (top-N enforced at get_top_n_candidates retrieval time).

    optional ``cluster_id`` stamps the candidate
    so per-cluster retrieval queries can filter. Default None preserves
    previously emission behavior (callsites that don't pass cluster_id
    still record candidates — they're then queryable via the global path
    `get_rca_candidates()` but excluded from filtered queries).
    """
    if not DT_RCA_PRODUCTION_ENABLED:
        return None
    policy = resolve_production_rca_emit_policy(emit_policy)
    if policy == PRODUCTION_RCA_EMIT_POLICY_SUPPRESSED:
        return None
    if policy == PRODUCTION_RCA_EMIT_POLICY_HYBRID:
        if confidence_score < DT_RCA_CONFIDENCE_THRESHOLD:
            return None
    candidate = ProductionRCACandidate(
        candidate_id=candidate_id,
        target_entity=target_entity,
        confidence_score=float(confidence_score),
        supporting_evidence_count=int(supporting_evidence_count),
        emit_policy=policy,
        cluster_id=cluster_id,
    )
    with _PRODUCTION_LOCK:
        _PRODUCTION_CANDIDATES.append(candidate)
        if len(_PRODUCTION_CANDIDATES) > DT_RCA_PRODUCTION_RING_CAP:
            del _PRODUCTION_CANDIDATES[
                : len(_PRODUCTION_CANDIDATES) - DT_RCA_PRODUCTION_RING_CAP
            ]
    return candidate


def _filter_by_cluster_id(
    candidates: List[ProductionRCACandidate],
    cluster_id: Optional[str],
) -> List[ProductionRCACandidate]:
    """ helper: filter candidates by cluster_id when non-None.

    cluster_id=None returns the full list (backward compat).
    cluster_id="X" returns only candidates with c.cluster_id == "X".
    Candidates emitted previously have cluster_id=None and are
    excluded from any non-None filter (signaling "not scoped").
    """
    if cluster_id is None:
        return candidates
    return [c for c in candidates if c.cluster_id == cluster_id]


def get_rca_candidates(
    cluster_id: Optional[str] = None,
) -> List[ProductionRCACandidate]:
    """All recorded RCA candidates. Empty when gate off.

    optional ``cluster_id`` filter. None = all (backward compat);
    string value returns only candidates stamped with that cluster_id.
    """
    if not DT_RCA_PRODUCTION_ENABLED:
        return []
    with _PRODUCTION_LOCK:
        all_candidates = list(_PRODUCTION_CANDIDATES)
    return _filter_by_cluster_id(all_candidates, cluster_id)


def get_rca_candidate_count(cluster_id: Optional[str] = None) -> int:
    """Aggregate count of recorded production RCA candidates.

    Dashboard-data defensive-accessor entry point. Returns 0 when gate off.

    optional ``cluster_id`` filter. None = aggregate count;
    string value returns count of candidates stamped with that cluster_id.
    """
    if not DT_RCA_PRODUCTION_ENABLED:
        return 0
    return len(get_rca_candidates(cluster_id=cluster_id))


def get_top_n_candidates(
    n: int = None,
    cluster_id: Optional[str] = None,
) -> List[ProductionRCACandidate]:
    """Top-N candidates by confidence_score descending.

    Defaults to DT_RCA_TOP_N (10). Returns empty when gate off.

    optional ``cluster_id`` filter applied BEFORE top-N truncation;
    so top-N is per-cluster when scoped. None = global top-N (backward compat).
    """
    if not DT_RCA_PRODUCTION_ENABLED:
        return []
    if n is None:
        n = DT_RCA_TOP_N
    with _PRODUCTION_LOCK:
        pool = _filter_by_cluster_id(list(_PRODUCTION_CANDIDATES), cluster_id)
        sorted_candidates = sorted(
            pool,
            key=lambda c: c.confidence_score,
            reverse=True,
        )
        return sorted_candidates[:n]


def known_rca_targets() -> List[str]:
    """Diagnostic accessor — sorted unique target_entity values."""
    if not DT_RCA_PRODUCTION_ENABLED:
        return []
    with _PRODUCTION_LOCK:
        return sorted({c.target_entity for c in _PRODUCTION_CANDIDATES})


def _reset_production_candidates_for_tests() -> None:
    with _PRODUCTION_LOCK:
        _PRODUCTION_CANDIDATES.clear()
