"""
Root Cause Identifier — greedy set cover for multi-entity anomaly correlation.

Given a set of simultaneously observed anomalies across multiple entities,
identifies the minimum set of root entities whose forward propagation
explains all observed anomalies. Uses greedy set cover with O(ln n)
approximation guarantee (provably optimal under P != NP).

This is complementary to:
  - :class:`ImpactEstimator` — forward propagation from a *known* source
  - the full system — ownership chain / metric
    correlation analysis

The ``RootCauseIdentifier`` operates at the arbiter_engine/propagation layer
and answers: *"Which entities most likely caused these N anomalies?"*
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from ..interfaces import Problem, RelationshipGraph
from .weight_learner import LearnedWeight
from arbiter_engine.rca import greedy_set_cover

logger = logging.getLogger(__name__)


def _wire_mcts_reranker_for_candidate(
    candidate_id: str,
    target_entity: str,
    mcts_iterations: int,
    reranker_score: float,
) -> None:
    """register MCTS + reranker results for a root-cause candidate at
    the production emit callsite (was the established pattern callsite-less — the 2nd
    callsite-less Pattern-360 wiring module, sibling of).

    Self-gated on ``DT_RCA_MCTS_RERANKER_WIRING_ENABLED`` (default OFF -> no-op,
    byte-identical). Called only when the MCTS strategy actually ran, so the
    registered iteration budget + confidence score reflect real MCTS activity.
    """
    try:
        from arbiter_engine.rca import mcts_reranker_wiring as _mrw
    except Exception:  # noqa: BLE001 — wiring module not deployed
        return
    if not _mrw.DT_RCA_MCTS_RERANKER_WIRING_ENABLED:
        return
    _mrw.wire_mcts_reranker_into_rca(
        candidate_id, target_entity, mcts_iterations, reranker_score,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RootCauseCandidate:
    """A candidate root cause entity with its coverage.

    Attributes
    ----------
    entity_id: The candidate root entity.
    coverage: Set of anomalous entity IDs explained by this root.
    probability: Joint propagation probability to reach covered entities.
    avg_path_length: Average hop distance to covered entities.
    """
    entity_id: str
    coverage: FrozenSet[str] = field(default_factory=frozenset)
    probability: float = 0.0
    avg_path_length: float = 0.0
    confidence: float = 0.0


@dataclass
class RootCauseResult:
    """Result of root cause identification.

    Attributes
    ----------
    root_causes: Ordered list of identified root causes (most impactful first).
    anomaly_count: Total number of input anomalies.
    explained_count: Number of anomalies explained by the identified roots.
    coverage_ratio: explained_count / anomaly_count.
    generated_at: UTC timestamp.
    """
    root_causes: List[RootCauseCandidate] = field(default_factory=list)
    anomaly_count: int = 0
    explained_count: int = 0
    coverage_ratio: float = 0.0
    generated_at: datetime = field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers (/) — used by both RootCauseIdentifier and
# TopologyTraverser.find_root_causes. Extracted to consolidate the
# upstream-candidate walk and the greedy-set-cover assembly that both
# components previously duplicated. Behavior is identical to the previously
# inline code; abstraction differences (RelationshipGraph vs TwinEdge) live
# in the call sites via the predecessor callable.
# ─────────────────────────────────────────────────────────────────────────────


def collect_upstream_candidates(
    anomalies: FrozenSet[str],
    get_predecessors: Callable[[str], Iterable[str]],
    max_upstream_hops: int = 2,
) -> Set[str]:
    """Collect candidate root entities by walking N hops upstream from anomalies.

    Anomalies themselves are always candidates (self-root case). Then walk
    upstream `max_upstream_hops` times; deduped per frontier so identical
    upstream nodes reachable from multiple anomalies are walked once.

    Args:
        anomalies: Anomalous entity IDs.
        get_predecessors: Callable returning upstream node IDs for a node ID.
        max_upstream_hops: How many hops upstream to walk (default 2 matches
            previously behavior in both RootCauseIdentifier and
            TopologyTraverser.find_root_causes).

    Returns:
        Set of candidate entity IDs (includes anomalies themselves).
    """
    candidates: Set[str] = set(anomalies)
    if max_upstream_hops <= 0:
        return candidates

    frontier: Set[str] = set(anomalies)
    for _ in range(max_upstream_hops):
        next_frontier: Set[str] = set()
        for eid in frontier:
            for upstream in get_predecessors(eid):
                if upstream not in candidates:
                    candidates.add(upstream)
                    next_frontier.add(upstream)
        if not next_frontier:
            break
        frontier = next_frontier
    return candidates


def collect_cross_domain_upstream_candidates(
    anomalies: FrozenSet[str],
    get_predecessors: Callable[[str], Iterable[str]],
    get_cross_domain_predecessors: Optional[
        Callable[[str], Iterable[tuple]]
    ] = None,
    anomaly_domains: Optional[Dict[str, str]] = None,
    max_upstream_hops: int = 2,
) -> Dict[str, Set[str]]:
    """walk upstream RCA candidates ACROSS domain boundaries.

    Per sub-decision (single Coordination Core) +
    (cross-domain edges), RCA chains may span domains:
    Department-missed-deadline (consulting) → k8s outage (k8s) → blocked
    deployment (k8s). This function extends ``collect_upstream_candidates``
    with per-candidate domain attribution.

    Args:
        anomalies: Anomalous entity IDs.
        get_predecessors: Callable returning same-domain upstream node
            IDs for a node ID (the existing interface).
        get_cross_domain_predecessors: Optional callable returning
            ``(upstream_entity_id, source_domain_id)`` tuples for
            cross-domain predecessors. When None, behaves identically
            to ``collect_upstream_candidates`` (returns Dict shape
            instead of Set).
        anomaly_domains: Optional ``{entity_id: domain_id}`` for each
            anomaly. When provided, the returned attribution dict
            seeds anomalies with their declared domain; otherwise
            anomalies are seeded with ``"unknown"``.
        max_upstream_hops: How many hops upstream to walk (default 2
            matches behavior).

    Returns:
        ``Dict[entity_id, Set[domain_id]]`` — each candidate maps to
        the set of domains it was discovered in. Same-domain walks
        preserve the upstream node's inherited domain; cross-domain
        walks add the foreign domain to the set.

    Per read-only-by-design contract — never mutates inputs.
    """
    candidates: Dict[str, Set[str]] = {}
    anomaly_domains = anomaly_domains or {}
    for eid in anomalies:
        candidates[eid] = {anomaly_domains.get(eid, "unknown")}
    if max_upstream_hops <= 0:
        return candidates

    # Frontier carries (entity_id, domain_at_this_hop) tuples so the
    # domain attribution propagates correctly across walks.
    frontier: Set[tuple] = {
        (eid, anomaly_domains.get(eid, "unknown")) for eid in anomalies
    }
    for _ in range(max_upstream_hops):
        next_frontier: Set[tuple] = set()
        for eid, current_domain in frontier:
            # Same-domain predecessors inherit the current domain.
            for upstream in get_predecessors(eid):
                prev = candidates.get(upstream)
                if prev is None:
                    candidates[upstream] = {current_domain}
                    next_frontier.add((upstream, current_domain))
                elif current_domain not in prev:
                    prev.add(current_domain)
                    next_frontier.add((upstream, current_domain))
            # Cross-domain predecessors carry the foreign domain.
            if get_cross_domain_predecessors is not None:
                try:
                    cross_preds = get_cross_domain_predecessors(eid)
                except Exception:
                    cross_preds = []
                for upstream, foreign_domain in cross_preds:
                    prev = candidates.get(upstream)
                    if prev is None:
                        candidates[upstream] = {foreign_domain}
                        next_frontier.add((upstream, foreign_domain))
                    elif foreign_domain not in prev:
                        prev.add(foreign_domain)
                        next_frontier.add((upstream, foreign_domain))
        if not next_frontier:
            break
        frontier = next_frontier
    return candidates


def select_root_causes_via_set_cover(
    footprints: Dict[str, Set[str]],
    footprint_probs: Dict[str, float],
    footprint_hops: Dict[str, float],
    anomalies: FrozenSet[str],
    max_roots: int = 10,
    min_coverage: float = 1.0,
) -> RootCauseResult:
    """Run greedy set cover over precomputed footprints + assemble RootCauseResult.

    Both call sites (RootCauseIdentifier.identify greedy branch +
    TopologyTraverser.find_root_causes) compute their own footprints under
    their own graph abstraction, then delegate to this assembly helper.

    Args:
        footprints: candidate_id -> covered-anomaly set.
        footprint_probs: candidate_id -> average propagation probability over
            covered anomalies (used as tiebreaker score).
        footprint_hops: candidate_id -> average hop distance to covered
            anomalies (carried into the RootCauseCandidate).
        anomalies: All anomalous entity IDs (the universe for set cover).
        max_roots: Maximum candidates the greedy selection returns.
        min_coverage: Stop when coverage ratio reaches this threshold.

    Returns:
        :class:`RootCauseResult` with ordered selected candidates +
        coverage statistics. Empty `footprints` early-returns a result with
        `anomaly_count=len(anomalies)` and zero coverage (matches previously
        guard in RootCauseIdentifier.identify).
    """
    if not footprints:
        return RootCauseResult(anomaly_count=len(anomalies))

    cover_result = greedy_set_cover(
        candidates=footprints,
        universe=set(anomalies),
        scores=footprint_probs,
        max_selected=max_roots,
        min_coverage=min_coverage,
    )

    selected: List[RootCauseCandidate] = []
    for sel_id, _, _ in cover_result.selected:
        covered_all = footprints[sel_id] & anomalies
        selected.append(RootCauseCandidate(
            entity_id=sel_id,
            coverage=frozenset(covered_all),
            probability=footprint_probs.get(sel_id, 0.0),
            avg_path_length=footprint_hops.get(sel_id, 0.0),
        ))

    uncovered = set(cover_result.uncovered)
    explained = len(anomalies) - len(uncovered)
    ratio = explained / len(anomalies) if anomalies else 0.0

    return RootCauseResult(
        root_causes=selected,
        anomaly_count=len(anomalies),
        explained_count=explained,
        coverage_ratio=ratio,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Identifier
# ─────────────────────────────────────────────────────────────────────────────

class RootCauseIdentifier:
    """Identify root causes for a set of simultaneous anomalies.

    Uses greedy set cover: iteratively select the candidate root whose
    forward propagation footprint covers the most unexplained anomalies.

    Parameters
    ----------
    max_hops: Maximum BFS depth for computing propagation footprint.
    min_probability: Minimum cumulative probability for a propagation path
                         to count as "covering" an anomaly.
    min_coverage: Stop when coverage ratio reaches this threshold.
    max_roots: Maximum number of root causes to identify.
    """

    def __init__(
        self,
        max_hops: int = 4,
        min_probability: float = 0.05,
        min_coverage: float = 1.0,
        max_roots: int = 10,
        use_lp_confidence: bool = False,
        use_mcts: bool = False,
        mcts_iterations: int = 1000,
        mcts_time_ms: float = 500.0,
        reranker: Optional[Any] = None,
        candidate_pruner: Optional[Any] = None,
    ) -> None:
        self.max_hops = max_hops
        self.min_probability = min_probability
        self.min_coverage = min_coverage
        self.max_roots = max_roots
        self._use_lp_confidence = use_lp_confidence
        self._use_mcts = use_mcts
        self._mcts_iterations = mcts_iterations
        self._mcts_time_ms = mcts_time_ms
        self._reranker = reranker
        self._candidate_pruner = candidate_pruner

    def identify(
        self,
        anomalous_entities: Set[str],
        graph: RelationshipGraph,
        learned_weights: Optional[Dict[Tuple[str, str], LearnedWeight]] = None,
        candidate_roots: Optional[Set[str]] = None,
    ) -> RootCauseResult:
        """Identify root causes for the given set of anomalous entities.

        Parameters
        ----------
        anomalous_entities:
            Entity IDs currently exhibiting anomalies.
        graph:
            Relationship graph for topology traversal.
        learned_weights:
            Propagation weights from :class:`PropagationWeightLearner`.
        candidate_roots:
            Optional restricted set of candidate root entities. If ``None``,
            all entities with outgoing edges are considered.

        Returns
        -------
        :class:`RootCauseResult` with ordered root causes.
        """
        if not anomalous_entities:
            return RootCauseResult()

        weights = learned_weights or {}
        anomalies = frozenset(anomalous_entities)

        # Determine candidate roots: entities with outgoing relationships.
        #: delegate to collect_upstream_candidates module helper
        # so TopologyTraverser.find_root_causes can use the same canonical
        # upstream walk under its own graph abstraction.
        if candidate_roots is not None:
            candidates = candidate_roots
        else:
            candidates = collect_upstream_candidates(
                anomalies, graph.get_reverse_relationships,
            )

        if not candidates:
            return RootCauseResult(anomaly_count=len(anomalies))

        # Precompute forward propagation footprint for each candidate.
        footprints: Dict[str, Tuple[Set[str], float, float]] = {}
        for cid in candidates:
            covered, avg_prob, avg_hops = self._propagation_footprint(
                cid, anomalies, graph, weights
            )
            if covered:
                footprints[cid] = (covered, avg_prob, avg_hops)

        # Save full footprints (greedy loop mutates the dict).
        all_footprints = dict(footprints)

        # ── Select root causes ────────────────────────────────────────
        uncovered = set(anomalies)
        selected: List[RootCauseCandidate] = []

        if self._use_mcts and footprints:
            # Strategy 5: MCTS search (beyond-greedy exploration).
            from .mcts_root_cause import MCTSRootCause

            fp_sets = {cid: cov for cid, (cov, _, _) in footprints.items()}
            mcts = MCTSRootCause(
                max_iterations=self._mcts_iterations,
                max_time_ms=self._mcts_time_ms,
            )
            mcts_ids = mcts.search(anomalies, fp_sets, self.max_roots)
            for eid in mcts_ids:
                if eid in footprints:
                    cov, prob, hops = footprints[eid]
                    selected.append(RootCauseCandidate(
                        entity_id=eid,
                        coverage=frozenset(cov & anomalies),
                        probability=prob,
                        avg_path_length=hops,
                    ))
                    uncovered -= cov

            explained = len(anomalies) - len(uncovered)
            ratio = explained / len(anomalies) if anomalies else 0.0
            result = RootCauseResult(
                root_causes=selected,
                anomaly_count=len(anomalies),
                explained_count=explained,
                coverage_ratio=ratio,
            )
        else:
            # Default: greedy set cover with O(ln n) guarantee.
            #: delegate to select_root_causes_via_set_cover
            # module helper, shared with TopologyTraverser.find_root_causes.
            result = select_root_causes_via_set_cover(
                footprints={cid: cov for cid, (cov, _, _) in footprints.items()},
                footprint_probs={cid: prob for cid, (_, prob, _) in footprints.items()},
                footprint_hops={cid: hops for cid, (_, _, hops) in footprints.items()},
                anomalies=anomalies,
                max_roots=self.max_roots,
                min_coverage=self.min_coverage,
            )

        # ── LP confidence scores (Strategy 3) ────────────────────────
        if self._use_lp_confidence and result.root_causes:
            try:
                from .lp_confidence import compute_lp_confidence

                fp_sets = {cid: cov for cid, (cov, _, _) in all_footprints.items()}
                probs = {cid: prob for cid, (_, prob, _) in all_footprints.items()}
                confidences = compute_lp_confidence(
                    [rc.entity_id for rc in result.root_causes],
                    anomalies,
                    fp_sets,
                    self.max_roots,
                    propagation_probs=probs,
                )
                for rc in result.root_causes:
                    rc.confidence = confidences.get(rc.entity_id, 0.0)
            except Exception as e:
                logger.warning("LP confidence computation failed: %s", e)

        # (callsite) — emit per-candidate RCA record at
        # production-readiness shape. One record per RootCauseCandidate
        # (not per covered anomaly) — per-candidate is the substrate intent
        # ProductionRCACandidate dataclass shape. target_entity
        # uses first sorted covered anomaly as stable representative.
        # `record_rca_candidate` gate is internally checked
        # (DT_RCA_PRODUCTION_ENABLED); no-op when production substrate off.
        # Hybrid emit-policy enforces confidence-threshold gate at substrate side.
        if result.root_causes:
            try:
                from arbiter_engine.rca.greedy_set_cover import (
                    record_rca_candidate,
                )
                for rc in result.root_causes:
                    target = sorted(rc.coverage)[0] if rc.coverage else ""
                    confidence = rc.confidence if rc.confidence > 0 else rc.probability
                    record_rca_candidate(
                        candidate_id=rc.entity_id,
                        target_entity=target,
                        confidence_score=float(confidence),
                        supporting_evidence_count=len(rc.coverage),
                    )
                    # register MCTS+reranker results when the MCTS
                    # strategy ran (the established pattern sibling of). Self-gated
                    # on DT_RCA_MCTS_RERANKER_WIRING_ENABLED -> byte-identical off.
                    if self._use_mcts:
                        _wire_mcts_reranker_for_candidate(
                            rc.entity_id, target,
                            self._mcts_iterations, float(confidence),
                        )
            except Exception as e:  # noqa: BLE001 — defensive; gate-off / unavailable
                logger.warning("record_rca_candidate callsite failed: %s", e)

        return result

    # ── Private helpers ──────────────────────────────────────────────────

    def _propagation_footprint(
        self,
        source_id: str,
        anomalies: FrozenSet[str],
        graph: RelationshipGraph,
        weights: Dict[Tuple[str, str], LearnedWeight],
    ) -> Tuple[Set[str], float, float]:
        """Compute which anomalous entities this source can reach via forward BFS.

        Returns
        -------
        (covered_anomalies, average_probability, average_hop_distance)
        """
        covered: Set[str] = set()
        probs: List[float] = []
        hops: List[float] = []

        # The source itself counts if it's anomalous.
        if source_id in anomalies:
            covered.add(source_id)
            probs.append(1.0)
            hops.append(0.0)

        # BFS forward: (entity_id, hop, cumulative_probability)
        queue: deque = deque()
        queue.append((source_id, 0, 1.0))
        visited = {source_id}

        while queue:
            current_id, hop, cum_prob = queue.popleft()

            if hop >= self.max_hops:
                continue

            for target_id in graph.get_relationships(current_id):
                if target_id in visited:
                    continue
                visited.add(target_id)

                pair = (current_id, target_id)
                weight = weights.get(pair)

                if weight and weight.is_reliable:
                    hop_prob = weight.probability
                else:
                    hop_prob = 0.3  # default

                new_prob = cum_prob * hop_prob
                if new_prob < self.min_probability:
                    continue

                new_hop = hop + 1

                if target_id in anomalies:
                    covered.add(target_id)
                    probs.append(new_prob)
                    hops.append(float(new_hop))

                queue.append((target_id, new_hop, new_prob))

        avg_prob = sum(probs) / len(probs) if probs else 0.0
        avg_hops = sum(hops) / len(hops) if hops else 0.0

        return covered, avg_prob, avg_hops
