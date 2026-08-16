"""
TopologyTraverser — unified BFS engine for the Digital Twin topology.

All problem solving passes through traverse(). Convenience methods
(find_root_causes, predict_impact, etc.) configure a TraversalRequest
and delegate to traverse().

Supports three directions (FORWARD, REVERSE, BIDIRECTIONAL) and three
value modes (CURRENT, PROJECTED, HYPOTHETICAL).
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Set, Tuple

from ..interfaces import Entity, Problem, ObservationHistory
from ..types import Axiom, Severity, DetectionLayer, AxiomParameters
from ..temporal.trend_projection import TrendProjection
from ..propagation.impact_estimator import DownstreamImpact, ImpactForecast
from ..propagation.root_cause import (
    RootCauseResult,
    collect_upstream_candidates,
    select_root_causes_via_set_cover,
)

from .topology import (
    TwinNode, TwinEdge, TopologyGap, DigitalTwinTopology,
    AxiomState, TraversalRequest, TraversalResult, TraversalStep,
    TopologyQuestion, ProjectedValue,
    TraversalDirection, ValueMode, EdgeDirection, FlowType,
    GapType, ResolutionStrategy,
)
from ..axiom_thresholds import (
    resolve_axiom_threshold,
)

logger = logging.getLogger(__name__)

# Severity decay per hop for impact estimation.
_SEVERITY_DECAY = {
    Severity.CRITICAL: Severity.HIGH,
    Severity.HIGH: Severity.MEDIUM,
    Severity.MEDIUM: Severity.LOW,
    Severity.LOW: Severity.WARNING,
    Severity.WARNING: Severity.INFO,
    Severity.INFO: Severity.INFO,
}


# flow-direction markers for the structural CONSERVATION path.
# Matched as underscore-delimited tokens, never as substrings.
_FLOW_IN_TOKENS: FrozenSet[str] = frozenset({'in', 'input', 'received'})
_FLOW_OUT_TOKENS: FrozenSet[str] = frozenset({'out', 'output', 'sent'})


def classify_flow_direction(prop_name: str) -> Optional[str]:
    """Classify a property name as 'in', 'out', or None (neither).

Matching is on underscore-delimited tokens. The previous form
    tested raw substring containment, which swept every property whose name
    merely contained the marker letters anywhere into the inflow total —
    in the shipped domain files that is ``material_integrity``,
    ``policy_intent``, ``root_cause_indicators``, ``seal_integrity``,
    ``wear_indicators``, ``sensor_invalid_read_rate``, ``freeze_instrument``
    and ``periodic_detection_interval``, plus ``days_outstanding`` and
    ``load_generator_outage_simulation`` on the outflow side. None of those carry
    flow, and summing them manufactures a conservation deficit from nothing.

    Token matching rather than ``endswith`` is deliberate: the unit-suffixed
    ``flow_in_m3h`` / ``flow_out_m3h`` and the suffix-form ``voltage_output``
    are genuine flow properties in the shipped domains, and a suffix test
    would silently drop all three.

    Known residual: a standalone ``in``/``input`` token inside a name that is
    not a flow quantity still matches — ``engage_human_in_loop``,
    ``bad_actor_input``, ``line_input_status``. Name-based inference cannot
    resolve those; only a declaration can. See on why this path
    consults no declaration at all.
    """
    tokens = set(prop_name.lower().split('_'))
    if tokens & _FLOW_IN_TOKENS:
        return 'in'
    if tokens & _FLOW_OUT_TOKENS:
        return 'out'
    return None


class TopologyTraverser:
    """Unified traversal engine for the Digital Twin topology."""

    def __init__(
        self,
        topology: DigitalTwinTopology,
        observation_history: Optional[ObservationHistory] = None,
        # `axiom_checkers` was accepted here, stored, and never read
        # by any code path. Removed rather than left in place: a parameter that
        # is silently ignored is worse than an absent one, because a caller can
        # pass checkers and reasonably expect them to be used. No caller passed
        # it (verified across every construction site), so removal is safe
        # despite the positional shift. Full axiom dispatch lives in
        # UnifiedAxiomReasoner.
        # `degradation_fitter` was accepted here too, and removed
        # for a *different* reason from `axiom_checkers` above. It was not
        # merely unread: it does not fit.
        #
        # `trend_projector` and `history` looked equally dead and were not —
        # they were dead only because `project_values` did not exist yet, so
        # removing them would have deleted the evidence for a missing step
        # (wired it, and they are read there now). `degradation_fitter`
        # was checked against the same test and fails it:
        #
        # - `DegradationFitter.fit(observations, failure_threshold)` needs a
        # per-indicator threshold. `project_values` walks
        # `entity.properties` and never consults the domain model, so the
        # traverser has no threshold to give it.
        # - Its output is remaining useful life — a time-to-threshold.
        # `ProjectedValue` carries value / confidence / horizon_s / model,
        # a *value at a horizon*. There is no field for a RUL and adding
        # one is a schema decision, not a wiring.
        # - The capability is already live elsewhere: an internal ruling wired it into
        # the full system, which does have thresholds.
        #
        # So this is a parameter for a capability that belongs to another
        # surface, not a producer waiting to be connected. Wiring it here
        # would need threshold plumbing plus a `ProjectedValue` field; if that
        # is ever wanted, it is a new CD, not a restored parameter.
        trend_projector: Optional[TrendProjection] = None,
        axiom_params: Optional[AxiomParameters] = None,
    ):
        self.topology = topology
        self.history = observation_history
        self.trend_projector = trend_projector
        # global fallback for the CONSERVATION flow-balance residual
        # thresholds (per-entity overrides win over these).
        self.axiom_params = axiom_params or AxiomParameters()

    # ------------------------------------------------------------------
    # Core traversal
    # ------------------------------------------------------------------

    def traverse(self, request: TraversalRequest) -> TraversalResult:
        """Core BFS traversal parameterized by TraversalRequest."""
        start_time = time.monotonic()
        result = TraversalResult()
        visited: Set[str] = set()

        # BFS queue: (entity_id, hop, cum_prob, cum_delay, path)
        queue: deque = deque()
        for start_id in request.start_nodes:
            queue.append((start_id, 0, 1.0, 0.0, [start_id]))

        while queue:
            current_id, hop, cum_prob, cum_delay, path = queue.popleft()

            if current_id in visited:
                continue
            visited.add(current_id)

            node = self.topology.get_node(current_id)

            # Node not in topology -> gap
            if node is None:
                if request.collect_gaps:
                    gap = TopologyGap(
                        gap_type=GapType.MISSING_NODE,
                        location=current_id,
                        description=(
                            f"Entity {current_id} not found in topology"
                        ),
                        discovered_during="traverse",
                    )
                    result.gaps_discovered.append(gap)
                    result.questions_generated.append(TopologyQuestion(
                        gap=gap,
                        question_text=gap.question,
                        priority=self._compute_priority(
                            gap, hop, cum_prob
                        ),
                        context_path=list(path),
                    ))
                continue

            # Get property values based on value_mode
            values = self._get_values(node, request)

            # Evaluate axiom states
            step_violations: List[Problem] = []
            if request.collect_axiom_violations:
                step_violations, attempted = self._evaluate_axioms(node, values)
                result.problems_detected.extend(step_violations)
                # Accumulated inside the `collect_axiom_violations`
                # guard on purpose: with collection off nothing is evaluated,
                # and the denominator must say zero rather than report the
                # states the builder seeded.
                result.axiom_evaluations_attempted += attempted

            # Record step
            step = TraversalStep(
                node_id=current_id,
                hop=hop,
                cumulative_probability=cum_prob,
                cumulative_delay_s=cum_delay,
                path=list(path),
                axiom_violations=step_violations,
            )
            result.steps.append(step)

            # Get edges based on direction
            if hop >= request.max_hops:
                continue

            # BIDIRECTIONAL traversal derives next_id per source
            # collection. Pre-fix the loop used ``edge.target_id`` for
            # everything except direction=REVERSE, so reverse_edges
            # contributions collapsed to next_id == current_id (because
            # reverse_edges[X] holds edges with target=X) and were
            # silently filtered by the ``in visited`` check. The
            # reverse-direction expansion was lost; only spurious self-self
            # conservation evidence fired.
            edges_with_next: List[Tuple[TwinEdge, str]] = []
            if request.direction in (
                TraversalDirection.FORWARD,
                TraversalDirection.BIDIRECTIONAL,
            ):
                for e in self.topology.edges.get(current_id, []):
                    edges_with_next.append((e, e.target_id))
            if request.direction in (
                TraversalDirection.REVERSE,
                TraversalDirection.BIDIRECTIONAL,
            ):
                for e in self.topology.reverse_edges.get(current_id, []):
                    edges_with_next.append((e, e.source_id))

            for edge, next_id in edges_with_next:
                # Edge filters
                if request.edge_filter and edge.direction not in request.edge_filter:
                    continue
                if request.flow_filter and edge.flow_type not in request.flow_filter:
                    continue

                if next_id in visited:
                    # BIDIRECTIONAL: check for FLOW cycle
                    if (request.direction == TraversalDirection.BIDIRECTIONAL
                            and edge.direction == EdgeDirection.FLOW):
                        conservation_problems = self._check_flow_balance(
                            path + [next_id]
                        )
                        result.conservation_violations.extend(
                            conservation_problems
                        )
                    continue

                new_prob = cum_prob * edge.propagation_probability
                new_delay = cum_delay + edge.propagation_delay_s

                # Pruning
                if new_prob < request.min_probability:
                    continue
                if new_delay > request.max_delay_s:
                    continue

                # Check if next node is missing
                if next_id not in self.topology.nodes:
                    if request.collect_gaps:
                        gap = TopologyGap(
                            gap_type=GapType.MISSING_NODE,
                            location=next_id,
                            description=(
                                f"Edge {current_id}->{next_id} "
                                f"points to unknown entity"
                            ),
                            discovered_during="traverse",
                        )
                        result.gaps_discovered.append(gap)
                        result.questions_generated.append(TopologyQuestion(
                            gap=gap,
                            question_text=gap.question,
                            priority=self._compute_priority(
                                gap, hop + 1, new_prob
                            ),
                            context_path=path + [next_id],
                        ))
                    continue

                queue.append((
                    next_id, hop + 1, new_prob, new_delay,
                    path + [next_id],
                ))

                # Build DownstreamImpact for forward traversals
                if request.direction in (
                    TraversalDirection.FORWARD,
                    TraversalDirection.BIDIRECTIONAL,
                ):
                    severity = self._decay_severity(Severity.HIGH, hop + 1)
                    result.impacts_predicted.append(DownstreamImpact(
                        entity_id=next_id,
                        hop_distance=hop + 1,
                        probability=new_prob,
                        expected_delay_s=new_delay,
                        severity=severity,
                        path=path + [next_id],
                    ))

        result.total_nodes_visited = len(visited)
        result.traversal_time_ms = (time.monotonic() - start_time) * 1000
        self.topology.last_traversal_at = datetime.utcnow()

        # the established pattern native 6th sub-cluster callsite-wire.
        # Defensive: substrate-unavailable / gate-off → no-op silently.
        # the established pattern bootstrap-aware preserves kernel contract.
        try:
            from arbiter_engine.twin.traverser_production import (
                record_production_traversal,
            )
            record_production_traversal(
                start_node=(
                    request.start_nodes[0] if request.start_nodes else "_empty"
                ),
                direction=(
                    request.direction.value
                    if hasattr(request.direction, "value")
                    else str(request.direction)
                ),
                value_mode=(
                    request.value_mode.value
                    if hasattr(request.value_mode, "value")
                    else str(request.value_mode)
                ),
                hop_count=int(result.total_nodes_visited),
                gap_count=int(len(result.gaps_discovered)),
            )
        except Exception:  # noqa: BLE001 — substrate not deployed
            pass

        return result

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    def find_root_causes(
        self,
        anomalous_ids: Set[str],
        max_roots: int = 10,
        min_coverage: float = 1.0,
    ) -> RootCauseResult:
        """Reverse walk + greedy set cover.

: candidate collection + set-cover assembly delegate to
        module-level helpers in ``arbiter_engine/propagation/root_cause.py`` so
        ``RootCauseIdentifier.identify`` and this method share the same
        canonical implementation. The per-candidate forward ``traverse()``
        invocation stays here because it depends on the TwinEdge graph
        abstraction (propagation_probability per edge); root_cause.py's
        equivalent uses the simpler RelationshipGraph + weights dict.
        """
        if not anomalous_ids:
            return RootCauseResult()

        anomalies = frozenset(anomalous_ids)

        candidates = collect_upstream_candidates(
            anomalies,
            lambda eid: (
                e.source_id for e in self.topology.reverse_edges.get(eid, [])
            ),
        )

        # Forward propagation footprint for each candidate via traverse().
        footprints: Dict[str, Set[str]] = {}
        footprint_probs: Dict[str, float] = {}
        footprint_hops: Dict[str, float] = {}

        for cid in candidates:
            result = self.traverse(TraversalRequest(
                start_nodes=[cid],
                direction=TraversalDirection.FORWARD,
                max_hops=4,
                min_probability=0.05,
                collect_axiom_violations=False,
                collect_gaps=False,
            ))
            covered = {
                s.node_id for s in result.steps
                if s.node_id in anomalies
            }
            if cid in anomalies:
                covered.add(cid)
            if covered:
                footprints[cid] = covered
                probs = [
                    s.cumulative_probability for s in result.steps
                    if s.node_id in covered
                ]
                hops_list = [
                    float(s.hop) for s in result.steps
                    if s.node_id in covered
                ]
                footprint_probs[cid] = (
                    sum(probs) / len(probs) if probs else 0.0
                )
                footprint_hops[cid] = (
                    sum(hops_list) / len(hops_list) if hops_list else 0.0
                )

        return select_root_causes_via_set_cover(
            footprints=footprints,
            footprint_probs=footprint_probs,
            footprint_hops=footprint_hops,
            anomalies=anomalies,
            max_roots=max_roots,
            min_coverage=min_coverage,
        )

    def predict_impact(
        self,
        problem: Problem,
        horizon_s: float = 3600.0,
    ) -> ImpactForecast:
        """Forward walk from problem source."""
        result = self.traverse(TraversalRequest(
            start_nodes=[problem.entity_id],
            direction=TraversalDirection.FORWARD,
            value_mode=ValueMode.CURRENT,
            max_hops=4,
            min_probability=0.05,
            collect_axiom_violations=False,
        ))
        sorted_impacts = sorted(
            result.impacts_predicted,
            key=lambda i: i.probability,
            reverse=True,
        )
        max_hop = max(
            (i.hop_distance for i in sorted_impacts), default=0
        )
        return ImpactForecast(
            source_problem=problem,
            downstream_impacts=sorted_impacts,
            total_affected=len(sorted_impacts),
            max_hop_distance=max_hop,
        )

    def check_conservation(self, node_id: str) -> List[Problem]:
        """Bidirectional flow-edge cycle detection and balance check."""
        cycles = self.topology.get_flow_cycles(node_id)
        problems: List[Problem] = []
        for cycle in cycles:
            cycle_ids = [cycle[0].source_id] + [e.target_id for e in cycle]
            problems.extend(self._check_flow_balance(cycle_ids))
        return problems

    def check_connectivity(
        self,
        node_id: str,
        target_type: Optional[str] = None,
        min_cardinality: int = 1,
    ) -> List[Problem]:
        """Forward reachability / adjacency check."""
        node = self.topology.get_node(node_id)
        if not node:
            return []
        outgoing = self.topology.edges.get(node_id, [])
        if target_type:
            matching = [
                e for e in outgoing
                if self.topology.get_node(e.target_id)
                and self.topology.get_node(e.target_id).entity.type.lower()
                == target_type.lower()
            ]
        else:
            matching = outgoing
        if len(matching) < min_cardinality:
            return [Problem.from_entity(
                entity=node.entity,
                problem_type='missing_connectivity',
                severity=Severity.HIGH,
                reason=(
                    f"Expected {min_cardinality} connections to "
                    f"{target_type or 'any'}, found {len(matching)}"
                ),
                axiom=Axiom.CONNECTIVITY,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'expected_min': min_cardinality,
                    'actual_count': len(matching),
                    'target_type': target_type,
                },
            )]
        return []

    def simulate_what_if(
        self,
        overrides: Dict[str, Dict[str, Any]],
        horizon_s: float = 3600.0,
    ) -> TraversalResult:
        """Perturb nodes and forward-propagate."""
        return self.traverse(TraversalRequest(
            start_nodes=list(overrides.keys()),
            direction=TraversalDirection.FORWARD,
            value_mode=ValueMode.HYPOTHETICAL,
            overrides=overrides,
            max_hops=4,
            min_probability=0.05,
        ))

    def discover_gaps(self, start_node: str) -> List[TopologyQuestion]:
        """Traverse until blocked, collect all gaps as questions."""
        result = self.traverse(TraversalRequest(
            start_nodes=[start_node],
            direction=TraversalDirection.FORWARD,
            value_mode=ValueMode.CURRENT,
            stop_on_gap=False,
            collect_gaps=True,
            collect_axiom_violations=False,
            max_hops=4,
        ))
        return sorted(
            result.questions_generated,
            key=lambda q: q.priority,
            reverse=True,
        )

    def project_values(self, horizon_s: float = 3600.0,
                       window: Optional[timedelta] = None) -> int:
        """Populate ``TwinNode.projected_values`` from observed history.

This is the producer PREDICT mode never had. ``_get_values``
        has always overlaid ``node.projected_values`` under
        ``ValueMode.PROJECTED``, but **nothing constructed a
        ``ProjectedValue``** anywhere outside a test — the source said so
        itself at ``arbiter_engine/residual/predict_vs_mirror.py``. So PROJECTED
        silently collapsed to CURRENT, and ``predict_all`` below traversed
        with present values while reporting future violations.

        It also explains two of the three dead constructor parameters
        flagged: ``trend_projector`` and ``history`` were assigned and never
        read *because* this step was missing. They are read here now, which is
        what they were accepted for.

        Returns the number of (node, property) projections written, so a
        caller can tell "projected nothing" from "projected and found
        nothing" — the same distinction drew for the checkers.
        """
        if self.history is None:
            return 0
        projector = self.trend_projector or TrendProjection()
        lookback = window or timedelta(hours=24)
        written = 0

        for node in self.topology.nodes.values():
            entity = node.entity
            for prop_name, current in entity.properties.items():
                if not isinstance(current, (int, float)) or isinstance(current, bool):
                    continue
                try:
                    values = self.history.get_values(
                        entity.id, prop_name, lookback)
                except Exception:  # noqa: BLE001 — a bad history must not
                    continue      # take down a projection pass
                if len(values) < 3:
                    # Below any sensible fit; leaving the property unprojected
                    # means PROJECTED falls back to its current value for it,
                    # which is honest — a projection was not made.
                    continue
                try:
                    trend = projector.project(values, horizon_s)
                except Exception:  # noqa: BLE001
                    trend = None
                if trend is None:
                    continue
                node.projected_values[prop_name] = ProjectedValue(
                    value=float(trend.predicted_value),
                    confidence=float(getattr(trend, "r_squared", 0.0) or 0.0),
                    horizon_s=float(horizon_s),
                    model=getattr(getattr(trend, "model", None), "value",
                                  str(getattr(trend, "model", ""))),
                )
                written += 1
        return written

    def predict_all(self, horizon_s: float = 3600.0) -> List[Problem]:
        """Project all node trends, traverse forward, find future violations.

        the projection step is now performed. Before this, the method
        traversed in PROJECTED mode over nodes whose ``projected_values`` were
        always empty, so it returned present-tense findings under a
        future-tense name.
        """
        self.project_values(horizon_s=horizon_s)
        problems: List[Problem] = []
        for node_id in self.topology.nodes:
            result = self.traverse(TraversalRequest(
                start_nodes=[node_id],
                direction=TraversalDirection.FORWARD,
                value_mode=ValueMode.PROJECTED,
                max_hops=2,
                min_probability=0.1,
                collect_axiom_violations=True,
                collect_gaps=False,
            ))
            problems.extend(result.problems_detected)
        return problems

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_values(
        self, node: TwinNode, request: TraversalRequest,
    ) -> Dict[str, Any]:
        """Get property values based on value_mode."""
        if request.value_mode == ValueMode.CURRENT:
            return dict(node.entity.properties)
        elif request.value_mode == ValueMode.PROJECTED:
            values = dict(node.entity.properties)
            for prop_name, pv in node.projected_values.items():
                values[prop_name] = pv.value
            return values
        elif request.value_mode == ValueMode.HYPOTHETICAL:
            values = dict(node.entity.properties)
            overrides = request.overrides.get(node.entity.id, {})
            values.update(overrides)
            return values
        return dict(node.entity.properties)

    def _evaluate_axioms(
        self, node: TwinNode, values: Dict[str, Any],
    ) -> Tuple[List[Problem], int]:
        """Evaluate axiom states against current/projected values.

        Returns the problems found AND the number of evaluations attempted.
        the count is returned rather than reconstructed by the caller,
        because the conditions under which an evaluation happens live in this
        body — a state is skipped when its property is absent from the values,
        when the value is not numeric, and when the axiom is not BOUNDEDNESS.
        Any caller counting `axiom_states` instead is counting declarations the
        builder seeded, which is how a walk that evaluated one invariant came
        to report four.

        **BOUNDEDNESS only.** The line this docstring used to carry — "other
        axioms delegate to registered checkers if available" — described an
        intention, not the code: the body has only ever handled BOUNDEDNESS,
        and the `axiom_checkers` constructor argument it referred to was
        stored and never read. An internal ruling removed the argument and corrected this
        sentence rather than leaving a docstring promising dispatch that does
        not happen.

        Callers wanting the full axiom set want `UnifiedAxiomReasoner`, which
        owns the dispatch table. Note that traversal separately performs a
        structural CONSERVATION check (`_check_flow_balance`) that consults no
        declaration at all —.
        """
        problems: List[Problem] = []
        attempted = 0
        for key, axiom_state in node.axiom_states.items():
            prop_name = axiom_state.indicator_name
            if not prop_name or prop_name not in values:
                continue
            value = values.get(prop_name)
            if value is None or not isinstance(value, (int, float)):
                continue

            # Check BOUNDEDNESS thresholds from evidence
            if axiom_state.axiom == Axiom.BOUNDEDNESS:
                # Counted HERE and not at the top of the loop: the two
                # `continue`s above skip states that were never evaluated, and
                # a non-BOUNDEDNESS state reaching this line is not evaluated
                # either. The denominator has to mean attempted, so it is
                # incremented at the point an attempt actually begins.
                attempted += 1
                warning = axiom_state.evidence.get('warning')
                critical = axiom_state.evidence.get('critical')
                if critical is not None and value > critical:
                    problems.append(Problem.from_entity(
                        entity=node.entity,
                        problem_type=f'twin_boundedness:{prop_name}',
                        severity=Severity.CRITICAL,
                        reason=(
                            f"{prop_name}={value} exceeds "
                            f"critical={critical}"
                        ),
                        axiom=Axiom.BOUNDEDNESS,
                        source_layer=DetectionLayer.ONTOLOGY,
                        evidence={
                            'property': prop_name,
                            'value': value,
                            'critical': critical,
                        },
                    ))
                elif warning is not None and value > warning:
                    problems.append(Problem.from_entity(
                        entity=node.entity,
                        problem_type=f'twin_boundedness:{prop_name}',
                        severity=Severity.WARNING,
                        reason=(
                            f"{prop_name}={value} exceeds "
                            f"warning={warning}"
                        ),
                        axiom=Axiom.BOUNDEDNESS,
                        source_layer=DetectionLayer.ONTOLOGY,
                        evidence={
                            'property': prop_name,
                            'value': value,
                            'warning': warning,
                        },
                    ))
        return problems, attempted

    def _compute_priority(
        self, gap: TopologyGap, hop: int, probability: float,
    ) -> float:
        """Higher = more blocking."""
        hop_factor = 1.0 / (1 + hop)
        type_weight = {
            GapType.MISSING_NODE: 1.0,
            GapType.MISSING_EDGE: 0.8,
            GapType.MISSING_PROPERTY: 0.6,
            GapType.MISSING_THRESHOLD: 0.4,
            GapType.MISSING_DYNAMICS: 0.2,
        }
        return hop_factor * probability * type_weight.get(gap.gap_type, 0.5)

    def _check_flow_balance(self, cycle_path: List[str]) -> List[Problem]:
        """Verify conservation around a flow cycle."""
        problems: List[Problem] = []
        for node_id in cycle_path[:-1]:
            node = self.topology.get_node(node_id)
            if not node:
                continue
            props = node.entity.properties
            # token-matched, not substring-matched. bool is a
            # subclass of int, so it is excluded explicitly: a flag named
            # engage_human_in_loop would otherwise contribute 1 to inflow.
            flow_in = sum(
                v for k, v in props.items()
                if classify_flow_direction(k) == 'in'
                and isinstance(v, (int, float))
                and not isinstance(v, bool)
            )
            flow_out = sum(
                v for k, v in props.items()
                if classify_flow_direction(k) == 'out'
                and isinstance(v, (int, float))
                and not isinstance(v, bool)
            )
            if flow_in > 0:
                deficit_ratio = abs(flow_in - flow_out) / flow_in
                # resolve per-entity overrides for the
                # CONSERVATION flow-balance residual; fall back to the global
                # AxiomParameters defaults (0.05 warn / 0.20 high).
                warn_threshold = resolve_axiom_threshold(
                    node.entity, "flow_balance", "CONSERVATION",
                    fallback=self.axiom_params.conservation_flow_deficit_warn,
                    bound="warn",
                )
                high_threshold = resolve_axiom_threshold(
                    node.entity, "flow_balance", "CONSERVATION",
                    fallback=self.axiom_params.conservation_flow_deficit_high,
                    bound="critical",
                )
                if deficit_ratio > warn_threshold:
                    severity = (
                        Severity.HIGH if deficit_ratio > high_threshold
                        else Severity.MEDIUM
                    )
                    problems.append(Problem.from_entity(
                        entity=node.entity,
                        problem_type='conservation_violation',
                        severity=severity,
                        reason=(
                            f"Flow imbalance: in={flow_in:.1f}, "
                            f"out={flow_out:.1f}, "
                            f"deficit={deficit_ratio:.1%}"
                        ),
                        axiom=Axiom.CONSERVATION,
                        source_layer=DetectionLayer.ONTOLOGY,
                        evidence={
                            'flow_in': flow_in,
                            'flow_out': flow_out,
                            'deficit_ratio': deficit_ratio,
                            'cycle_path': cycle_path,
                        },
                    ))
        return problems

    @staticmethod
    def _decay_severity(base: Severity, hops: int) -> Severity:
        current = base
        for _ in range(hops):
            current = _SEVERITY_DECAY.get(current, Severity.INFO)
        return current


# ---------------------------------------------------------------------------
# NL -> TraversalRequest translation
# ---------------------------------------------------------------------------

class NLTraversalTranslator:
    """Thin NL -> TraversalRequest translation layer.

    Rule-based 7-pattern primary path is the only implementation today.
    Maps common natural-language question patterns to TraversalRequest
    configurations via PATTERNS class-attribute keyword sets; unmapped
    questions return None (hard-fail at the caller's discretion).

    LLM-fallback architecture decided 2026-05-25
    (add-LLM-fallback option chosen; see decision doc
    the internal notes). Wiring follow-ups
    pending: translate() llm_fallback kwarg + shared.llm.get_llm_client()
    integration + audit-faithfulness gate + LLM-fallback pin tests.
    Until those follow-up CDs land, this class is rule-based only; LLM
    delegation is NOT yet active.

    Substrate-discovery surface for partners: GET /nl-query the established pattern
    endpoint enumerates the 7 keyword-pattern set + 3-direction +
    3-value-mode vocabularies + decision-doc cross-link.
    """

    PATTERNS = [
        ({"root cause", "why", "caused"},
         TraversalDirection.REVERSE, ValueMode.CURRENT, {}),
        ({"impact", "affect", "downstream"},
         TraversalDirection.FORWARD, ValueMode.CURRENT, {}),
        ({"predict", "forecast", "will", "future"},
         TraversalDirection.FORWARD, ValueMode.PROJECTED, {}),
        ({"what if", "simulate", "hypothetical"},
         TraversalDirection.FORWARD, ValueMode.HYPOTHETICAL, {}),
        ({"conservation", "balance", "flow"},
         TraversalDirection.BIDIRECTIONAL, ValueMode.CURRENT,
         {"edge_filter": {EdgeDirection.FLOW}}),
        ({"gap", "missing", "unknown"},
         TraversalDirection.FORWARD, ValueMode.CURRENT,
         {"stop_on_gap": False, "collect_gaps": True}),
        ({"connected", "connectivity", "reachable"},
         TraversalDirection.FORWARD, ValueMode.CURRENT, {}),
    ]

    def translate(
        self,
        question: str,
        entity_ids: Optional[List[str]] = None,
    ) -> Optional[TraversalRequest]:
        """Translate a natural-language question to a TraversalRequest.

        Returns None if the question cannot be mapped.
        """
        question_lower = question.lower()
        for keywords, direction, value_mode, extra in self.PATTERNS:
            if any(kw in question_lower for kw in keywords):
                config: Dict[str, Any] = {
                    'start_nodes': entity_ids or [],
                    'direction': direction,
                    'value_mode': value_mode,
                    'max_hops': 4,
                    'min_probability': 0.05,
                }
                config.update(extra)
                return TraversalRequest(**config)
        return None

    async def translate_with_llm_fallback(
        self,
        question: str,
        entity_ids: Optional[List[str]] = None,
        *,
        audit_entity_ids: Optional[List[str]] = None,
    ) -> Optional[TraversalRequest]:
        """ (follow-up #1/#2/#3 chain head): async wrapper around
        sync translate() that adds LLM-fallback path for unmapped questions.

        Flow decision:
            1. Try sync rule-based translate() (current 7-pattern path).
            2. If matched, return TraversalRequest (existing behavior).
            3. If unmapped + NL_LLM_FALLBACK_ENABLED env true + an LLM client
               is available → call LLM with structured prompt naming the 3
               direction enums + 3 value-mode enums + JSON output shape.
            4. Apply 3-heuristic audit-faithfulness check (adapted from
                the full system shape): substring + capitalized-token +
               coverage applied to the supplied entity_ids list.
            5. Return TraversalRequest on audit-pass OR None on audit-fail.

        Args:
            question: Natural-language question.
            entity_ids: Start nodes for the traversal (also the audit baseline).
            audit_entity_ids: Optional override for the audit-baseline list
                (defaults to entity_ids). Lets callers audit against a
                broader set than the start nodes.

        Returns None when (a) rule-based unmapped + env-gate off, OR
        (b) rule-based unmapped + LLM call fails, OR (c) audit-faithfulness
        gate fails on LLM output. an established pattern env-gate.
        """
        rule_based = self.translate(question, entity_ids=entity_ids)
        if rule_based is not None:
            return rule_based

        import os
        if os.environ.get("NL_LLM_FALLBACK_ENABLED", "false").lower() != "true":
            return None

        try:
            llm_output = await self._call_llm_for_traversal(question, entity_ids)
        except Exception:  # noqa: BLE001 — defensive LLM-call wrapper
            return None
        if llm_output is None:
            return None

        audit_pool = audit_entity_ids if audit_entity_ids is not None else (entity_ids or [])
        if not self._audit_llm_traversal_output(llm_output, audit_pool):
            return None

        return self._parse_llm_json_to_traversal_request(llm_output, entity_ids)

    async def _call_llm_for_traversal(
        self,
        question: str,
        entity_ids: Optional[List[str]],
    ) -> Optional[Dict[str, Any]]:
        """lazy-imports shared.llm.get_llm_client() + structured prompt.

        Tests mock this method directly (no real LLM call needed). Returns
        a JSON-decoded dict with keys 'direction' + 'value_mode' +
        'start_nodes' OR None on LLM failure.
        """
        try:
            # -- the root package is DERIVED, not written. This used to
            # name the originating distribution literally, and the extraction
            # deliberately leaves such a statement alone so the import fails in
            # the standalone engine. It did fail, correctly -- and shipped that
            # name into a public tree to do it, as the one string in the whole
            # artifact identifying where it came from.
            #
            # Deriving the root keeps both behaviours and neither cost: in the
            # full tree it resolves to the real client, and in the engine it
            # resolves to a sibling that was never extracted and raises below.
            import importlib
            _root = (__package__ or __name__).split(".")[0]
            get_llm_client = importlib.import_module(
                f"{_root}.shared.llm").get_llm_client
        except (ImportError, AttributeError) as exc:
            # item 5. Fails loudly rather than degrading, unlike the
            # sibling guard at propagation/root_cause.py:45 -- the caller asked
            # for a translation and there is no honest way to return one.
            raise RuntimeError(
                "natural-language traversal needs an LLM client, and none is "
                "available in this distribution. The deterministic translate() "
                "path needs no client and is unaffected. In the standalone "
                "engine the client is deliberately not shipped: it is "
                "operations, and NLTraversalTranslator is a deep path that is "
                "importable but explicitly unsupported."
            ) from exc

        client = get_llm_client()
        directions = [d.value for d in TraversalDirection]
        value_modes = [v.value for v in ValueMode]
        system_prompt = (
            "You compile natural-language questions about Digital Twin "
            "topology into TraversalRequest JSON. Output ONLY valid JSON "
            "with keys: direction (one of " + ", ".join(directions) + "), "
            "value_mode (one of " + ", ".join(value_modes) + "), "
            "start_nodes (list of entity ID strings, MUST be a subset of "
            "the supplied entity_ids). NO prose."
        )
        user_prompt = (
            "question: " + question + "\n"
            "entity_ids: " + str(entity_ids or [])
        )
        raw = await client.complete(system=system_prompt, user=user_prompt)
        import json as _json
        try:
            return _json.loads(raw)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _audit_llm_traversal_output(
        llm_output: Dict[str, Any],
        audit_entity_ids: List[str],
    ) -> bool:
        """ (follow-up #3): 3-heuristic audit-faithfulness check
        adapted from the full system shape, applied to LLM-emitted
        traversal config.

        Heuristics (all 3 must pass):
            (1) Substring: every entity_id in llm_output['start_nodes'] must
                appear as a substring of some entry in audit_entity_ids.
            (2) Capitalized-token: capitalized tokens in start_nodes must
                appear in audit_entity_ids (no novel capitalized identifiers).
            (3) Coverage: at least one audit_entity_ids entry must appear in
                start_nodes when audit_entity_ids is non-empty.

        Returns True iff all 3 pass.
        """
        start_nodes = llm_output.get("start_nodes")
        if not isinstance(start_nodes, list):
            return False

        # (1) Substring check.
        audit_blob = " ".join(audit_entity_ids)
        for node in start_nodes:
            if not isinstance(node, str):
                return False
            if audit_entity_ids and node not in audit_blob:
                return False

        # (2) Capitalized-token check.
        import re as _re
        cap_pattern = _re.compile(r"\b[A-Z][A-Za-z0-9]*\b")
        audit_caps = set()
        for eid in audit_entity_ids:
            audit_caps.update(cap_pattern.findall(eid))
        for node in start_nodes:
            for tok in cap_pattern.findall(node):
                if tok not in audit_caps:
                    return False

        # (3) Coverage check (only when audit_entity_ids is non-empty).
        if audit_entity_ids and not any(eid in start_nodes for eid in audit_entity_ids):
            return False

        return True

    @staticmethod
    def _parse_llm_json_to_traversal_request(
        llm_output: Dict[str, Any],
        entity_ids: Optional[List[str]],
    ) -> Optional[TraversalRequest]:
        """parse audit-passed LLM JSON to TraversalRequest. Returns
        None if any required field is missing or has invalid value.
        """
        direction_str = llm_output.get("direction")
        value_mode_str = llm_output.get("value_mode")
        start_nodes = llm_output.get("start_nodes")

        try:
            direction = TraversalDirection(direction_str)
            value_mode = ValueMode(value_mode_str)
        except (ValueError, TypeError):
            return None

        if not isinstance(start_nodes, list):
            return None

        try:
            return TraversalRequest(
                start_nodes=start_nodes if start_nodes else (entity_ids or []),
                direction=direction,
                value_mode=value_mode,
                max_hops=4,
                min_probability=0.05,
            )
        except (TypeError, ValueError):
            return None


# ---------------------------------------------------------------------------
#: 3-tier escalation decision
# ---------------------------------------------------------------------------

# the established pattern canonical-invariant (promotion).
# Tier 1 = rule-based or LLM-tool-use auto-translate.
# Tier 2 = LLM-ambiguity-resolution (present 2-3 candidate TraversalRequests).
# Tier 3 = operator-confirmation (cross-tenant OR HIGH+ severity OR overrides).

TRAVERSE_TOPOLOGY_TOOL_DEF: Dict[str, Any] = {
    "name": "traverse_topology",
    "description": (
        "Configure a Digital Twin TraversalRequest to answer the user's "
        "question. Returns TraversalResult with steps + problems + gaps + "
        "questions. Use FORWARD for impact/downstream, REVERSE for "
        "root-cause, BIDIRECTIONAL for conservation/cycle checks. Use "
        "CURRENT for what-is-now, PROJECTED for future-state, HYPOTHETICAL "
        "with overrides for what-if simulation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "start_nodes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Entity IDs to start traversal from. Must be a subset of supplied entity_ids context.",
            },
            "direction": {
                "type": "string",
                "enum": ["forward", "reverse", "bidirectional"],
                "description": "Traversal direction.",
            },
            "value_mode": {
                "type": "string",
                "enum": ["current", "projected", "hypothetical"],
                "description": "Property value source.",
            },
            "edge_filter": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional edge-direction filter (causal/flow/structural/temporal).",
            },
            "max_hops": {"type": "integer", "default": 4},
            "horizon_s": {"type": "number", "default": 3600.0},
            "overrides": {
                "type": "object",
                "description": "Per-node property overrides for HYPOTHETICAL mode.",
            },
        },
        "required": ["start_nodes", "direction", "value_mode"],
    },
}


@dataclass
class NLTranslationResult:
    """discriminated 3-tier outcome of NL → TraversalRequest.

    Exactly one of (tier1_traversal_request, tier2_candidates,
    tier3_pending_confirmation) is non-None. Caller dispatches on
    `tier` field (1/2/3) for routing logic.

    Per Decision Tier-3 fires when cross-tenant boundary
    detected OR HIGH+/CRITICAL severity-floor OR override-fields present.
    """

    tier: int
    nl_text: str
    tier1_traversal_request: Optional[TraversalRequest] = None
    tier2_candidates: List[TraversalRequest] = field(default_factory=list)
    tier3_pending_confirmation: Optional[TraversalRequest] = None
    tier3_reason: Optional[str] = None  # "cross_tenant" / "high_severity" / "overrides_present"
    tier2_pick_hint: Optional[str] = None
    tier3_summary: Optional[str] = None


def classify_escalation_tier_per_cd1280(
    traversal_request: TraversalRequest,
    tenant_id: Optional[str] = None,
    severity_floor: str = "MEDIUM",
    cross_tenant_start_nodes: Optional[List[str]] = None,
) -> tuple:
    """classify which tier a candidate TraversalRequest triggers.

    Returns (tier, reason) where tier is 1/2/3 and reason is None or one of:
    - "cross_tenant" (start_nodes span multiple tenants —
      tenant_context_token boundary detection)
    - "high_severity" (severity_floor >= HIGH)
    - "overrides_present" (HYPOTHETICAL mode + non-empty overrides)
    """
    # Tier 3 conditions (highest priority)
    if cross_tenant_start_nodes and len(set(cross_tenant_start_nodes)) > 1:
        return (3, "cross_tenant")
    if severity_floor.upper() in ("HIGH", "CRITICAL"):
        return (3, "high_severity")
    if (
        traversal_request.value_mode == ValueMode.HYPOTHETICAL
        and traversal_request.overrides
    ):
        return (3, "overrides_present")
    return (1, None)


class NLTraversalTranslator3Tier:
    """3-tier escalation wrapper for NLTraversalTranslator
     Decision. Companion class to existing NLTraversalTranslator
    rule-based + LLM-fallback shape; this class adds tier-classification +
    candidate presentation + operator-confirmation discriminated outcomes.

    the established pattern canonical-invariant (rule/template + LLM-fallback
    + human escape-hatch family — HTN/STRIPS/LLM + LLMClient
    fallback chain + NarrationInterface audit gate +
    LLMCounterfactual + this 5th).

    Per Lever 4: "NLTraversalTranslator is the
    AI Agent's core skill — operator NL → TraversalRequest → result → NL
    summary. Domain-agnostic by construction."
    """

    def __init__(self, base_translator: Optional[NLTraversalTranslator] = None):
        self.base = base_translator or NLTraversalTranslator()

    def translate_with_3_tier_escalation(
        self,
        nl_text: str,
        entity_ids: Optional[List[str]] = None,
        tenant_id: Optional[str] = None,
        severity_floor: str = "MEDIUM",
        cross_tenant_entity_ids: Optional[List[str]] = None,
    ) -> NLTranslationResult:
        """discriminated 3-tier translation Decision.

        Returns NLTranslationResult with discriminated tier outcome:
        - Tier 1: tier1_traversal_request populated (auto-execute)
        - Tier 2: tier2_candidates populated (operator picks)
        - Tier 3: tier3_pending_confirmation populated + tier3_reason +
          tier3_summary (operator confirms before execute)

        the established pattern canonical-invariant.
        """
        rule_based = self.base.translate(nl_text, entity_ids=entity_ids)

        if rule_based is not None:
            tier, reason = classify_escalation_tier_per_cd1280(
                rule_based,
                tenant_id=tenant_id,
                severity_floor=severity_floor,
                cross_tenant_start_nodes=cross_tenant_entity_ids,
            )
            if tier == 3:
                return NLTranslationResult(
                    tier=3,
                    nl_text=nl_text,
                    tier3_pending_confirmation=rule_based,
                    tier3_reason=reason,
                    tier3_summary=self._summarize_for_operator(rule_based, reason),
                )
            return NLTranslationResult(
                tier=1,
                nl_text=nl_text,
                tier1_traversal_request=rule_based,
            )

        # Rule-based unmapped: Tier 2 candidate presentation as fallback
        # (instead of silent LLM-only fallback) Decision Why #3.
        # Caller may bypass to LLM via translate_with_llm_fallback() if
        # desired; the 3-tier shape's default is candidate-presentation.
        return NLTranslationResult(
            tier=2,
            nl_text=nl_text,
            tier2_candidates=[],  # caller fills via LLM if NL_LLM_FALLBACK_ENABLED
            tier2_pick_hint=(
                "Rule-based 7-pattern path did not match. NL prompt is "
                "ambiguous. Operator: please rephrase with one of the "
                "vocabulary keywords (root cause / impact / predict / "
                "what if / conservation / gap / connected) OR provide a "
                "typed TraversalRequest directly."
            ),
        )

    @staticmethod
    def _summarize_for_operator(
        request: TraversalRequest, reason: str
    ) -> str:
        """5-line operator-confirmation summary Decision Tier-3."""
        direction_str = (
            request.direction.value if hasattr(request.direction, "value")
            else str(request.direction)
        )
        value_mode_str = (
            request.value_mode.value if hasattr(request.value_mode, "value")
            else str(request.value_mode)
        )
        return (
            f"Traversal: {direction_str.upper()} from {request.start_nodes} "
            f"in {value_mode_str.upper()} mode (~{request.max_hops} hops). "
            f"Escalated to Tier 3 reason={reason}. "
            f"Per + attestation, operator confirmation "
            f"required before execute. Operator: confirm Y/N + optional redirect."
        )
