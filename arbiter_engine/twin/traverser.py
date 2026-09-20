"""
TopologyTraverser — unified BFS engine for the Digital Twin topology.

All problem solving passes through traverse(). Convenience methods
(find_root_causes, predict_impact, etc.) configure a TraversalRequest
and delegate to traverse().

Supports three directions (FORWARD, REVERSE, BIDIRECTIONAL) and three
value modes (CURRENT, PROJECTED, HYPOTHETICAL).
"""

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Set, Tuple

from ..clock import now_utc
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
    TransitionApplied, SimulationDecline,
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


# flow-direction markers. demoted them: they no longer decide
# anything, they only propose. Matched as underscore-delimited tokens, never as
# substrings.
_FLOW_IN_TOKENS: FrozenSet[str] = frozenset({'in', 'input', 'received'})
_FLOW_OUT_TOKENS: FrozenSet[str] = frozenset({'out', 'output', 'sent'})


def suggest_flow_direction(prop_name: str) -> Optional[str]:
    """PROPOSE 'in', 'out', or None for a property name. Never assert on it.

    An internal ruling renamed this from ``classify_flow_direction`` and took its output
    off the assertion path. The rename is the change: *classify* reads as a
    verdict, and the verdict was wrong often enough to manufacture conservation
    deficits out of nothing. Its only caller now writes candidates into a
    :class:`TopologyGap` for a human to confirm or reject — the ``gaps()``
    posture, reported and asserted by nobody. The balance itself is computed
    from ``TwinNode.flow_directions``, which the builder seeds from the model's
    declared ``flow:`` field.

    Matching is on underscore-delimited tokens. The previous form
    tested raw substring containment, which swept every property whose name
    merely contained the marker letters anywhere into the inflow total —
    in the shipped domain files that is ``material_integrity``,
    ``policy_intent``, ``root_cause_indicators``, ``seal_integrity``,
    ``wear_indicators``, ``sensor_invalid_read_rate``, ``freeze_instrument``
    and ``periodic_detection_interval``, plus ``days_outstanding`` and
    ``load_generator_outage_simulation`` on the outflow side.

    Token matching rather than ``endswith`` is deliberate: the unit-suffixed
    ``flow_in_m3h`` / ``flow_out_m3h`` and the suffix-form ``voltage_output``
    are genuine flow properties in the shipped domains, and a suffix test
    would silently drop all three.

    THE RESIDUAL IS WHY THIS IS ONLY A SUGGESTION. A standalone ``in``/
    ``input`` token inside a name that is not a flow quantity still matches —
    ``engage_human_in_loop``, ``bad_actor_input``, ``line_input_status``. Two
    rounds of narrowing did not reach them and a third would not either: the
    information is not in the name. Only a declaration can resolve it, so a
    declaration is what the balance now reads.
    """
    tokens = set(prop_name.lower().split('_'))
    if tokens & _FLOW_IN_TOKENS:
        return 'in'
    if tokens & _FLOW_OUT_TOKENS:
        return 'out'
    return None


#: the prefix on a finding drawn from a value that is not a reading.
#:
#: `forecast/shadow.py` already prefixes `forecast_` for findings about a
#: forecast a PRODUCER supplied, and this is deliberately not that. The engine
#: separates its own output from a producer's everywhere else -- the
#: `project` verb's result is never counted as a bridge's forecast -- and a
#: what-if is the engine imagining, not a producer predicting. One prefix for
#: both would make `forecast_boundedness:x` mean two different things
#: depending on which verb produced it, which is the collision the prefix
#: exists to prevent.
#:
#: The rule is per-VALUE, not per-verb: a HYPOTHETICAL walk reads most of the
#: topology at its current reading, and a finding drawn from a real reading is
#: a real finding whichever walk found it.
IMAGINED_PREFIX = "imagined_"


def _declared_dynamics(model: Any) -> Optional[Set[Tuple[str, str]]]:
    """(entity_type, property) pairs whose indicator declares `dynamics:`.

    `None` when no model was supplied, which reproduces the old
    behaviour exactly for the callers that never had one to give -- a kernel
    used directly with a hand-built topology and no domain file. Those callers
    are asking a narrower question than the published verbs do, and silently
    refusing them would be a second wrong answer rather than a fix.

    The pairs come from `IndicatorSpec.dynamics_config`, which is the same
    field `projection/runner.py` reads to decide whether it may fit anything.
    Read from the one place rather than re-derived, because two readings of
    one declaration are how the two paths came to disagree in the first place.
    """
    if model is None:
        return None
    indicators = getattr(model, "indicators", None)
    if not isinstance(indicators, dict):
        return None
    pairs: Dict[Tuple[str, str], Any] = {}
    for entity_type, specs in indicators.items():
        for spec in specs or ():
            if getattr(spec, "dynamics_config", None):
                pairs[(str(entity_type),
                       str(getattr(spec, "property_name", "")
                           or getattr(spec, "name", "")))] = spec
    return pairs


def _sigma_from_quantiles(quantiles: Dict[str, Any]) -> float:
    """A standard deviation from a declared 90% interval, or 0.0.

    `forecast/contract.py` already stamps `gaussian_from_mean_sigma` when it
    widens a mean and sigma into quantiles; this is that conversion run the
    other way, and it rests on the same assumption -- which is why the caller
    stamps it rather than leaving a reader to infer it from an interval that
    looks exact.
    """
    low, high = quantiles.get("q05"), quantiles.get("q95")
    if not isinstance(low, (int, float)) or isinstance(low, bool):
        return 0.0
    if not isinstance(high, (int, float)) or isinstance(high, bool):
        return 0.0
    return max(0.0, (float(high) - float(low)) / (2.0 * 1.645))


def _curve(fitted):
    """A `(value, sigma)` reader over the fitted model, at any horizon.

    One fit, many instants. Re-fitting per step would read the same
    history a dozen times to reach the same parameters; re-forecasting is the
    part that actually depends on the horizon, and it is the cheap part.
    """
    def at(horizon_s: float):
        try:
            forecast = fitted.forecast(float(horizon_s))
        except Exception:  # noqa: BLE001 - a refusal is not a crash
            return None
        quantiles = dict(getattr(forecast, "quantiles", None) or {})
        median = quantiles.get("q50")
        if not isinstance(median, (int, float)) or isinstance(median, bool):
            return None
        return float(median), _sigma_from_quantiles(quantiles)
    return at


def _project_declared(values, spec, horizon_s: float):
    """Fit and forecast through the model the indicator declares.

    Returns `(projection, refusal)`, exactly one of which is set.

    THE REFUSAL IS RETURNED, NOT SWALLOWED. The first version of this dropped
    it and left the property unprojected, which turned `local_level`'s
    `unidentifiable_parameter` -- *q and r do not separate from this series* --
    into silence, and the caller then reported `model_missing` about a
    DIFFERENT indicator that happened to be undeclared. A declared model whose
    fit refused and an undeclared model are not the same fact, and the remedies
    point in opposite directions: declare the parameters, versus declare a
    model at all.

    The MEDIAN is taken as the projected value because a `ProjectedValue`
    carries one number and a forecast carries a distribution; q50 is the one
    that means *the middle of what this model expects*. The spread is not
    discarded so much as not representable here -- `project` reports the whole
    distribution, and this is the seed for a rollout, not a replacement for it.
    """
    from ..projection.projector import PROJECTORS
    dynamics = dict(getattr(spec, "dynamics_config", None) or {})
    name = str(dynamics.get("model") or "")
    projector = PROJECTORS.get(name)
    if projector is None:
        return None, ("model_missing",
                      f"`dynamics.model` is {name!r}, which this engine does "
                      f"not implement; known models are {sorted(PROJECTORS)}"), None
    scope = {"entity_id": "", "property": str(
        getattr(spec, "property_name", "") or getattr(spec, "name", ""))}
    try:
        fitted = projector.fit(values, dynamics, scope)
    except Exception as exc:  # noqa: BLE001 - a refusal is not a crash
        return None, ("internal_error",
                      f"the {name} projector raised {type(exc).__name__}"), None
    if fitted is None or not hasattr(fitted, "forecast"):
        reason = str(getattr(fitted, "reason", "") or "insufficient_samples")
        detail = str(getattr(fitted, "detail", "") or
                     f"the declared {name} model could not be fitted")
        return None, (reason, detail), None
    horizon = float(spec.horizon.total_seconds()
                    if getattr(spec, "horizon", None) else horizon_s)
    try:
        forecast = fitted.forecast(horizon)
    except Exception as exc:  # noqa: BLE001
        return None, ("internal_error",
                      f"the {name} forecast raised {type(exc).__name__}"), None
    quantiles = dict(getattr(forecast, "quantiles", None) or {})
    median = quantiles.get("q50")
    if not isinstance(median, (int, float)) or isinstance(median, bool):
        return None, ("insufficient_samples",
                      f"the {name} forecast carried no median to seed from"), None
    return ProjectedValue(
        value=float(median),
        confidence=0.0,
        horizon_s=horizon,
        # the band, converted to one number. `q05`/`q95` bound a 90%
        # interval, so the half-width over 1.645 is the standard deviation
        # under the normal the projector's own quantiles already assume. Zero
        # when the forecast reported no band, which keeps *nobody said* apart
        # from *said zero*, the same rule `gain_sigma` follows.
        sigma=_sigma_from_quantiles(quantiles),
        model=f"{getattr(forecast, 'model', '')}:"
              f"{getattr(forecast, 'source', '')}",
    ), None, _curve(fitted)


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
        #   - `DegradationFitter.fit(observations, failure_threshold)` needs a
        #     per-indicator threshold. `project_values` walks
        #     `entity.properties` and never consults the domain model, so the
        #     traverser has no threshold to give it.
        #   - Its output is remaining useful life — a time-to-threshold.
        #     `ProjectedValue` carries value / confidence / horizon_s / model,
        #     a *value at a horizon*. There is no field for a RUL and adding
        #     one is a schema decision, not a wiring.
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

        # value propagation. `imagined` holds per-node DELTAS away
        # from the node's current reading, accumulated as in-edges are walked;
        # `_get_values` overlays them. Only PROJECTED and HYPOTHETICAL ask for
        # values at all, so a CURRENT walk builds none of this and behaves
        # exactly as it did.
        simulating = request.value_mode in (
            ValueMode.PROJECTED, ValueMode.HYPOTHETICAL)
        imagined: Dict[str, Dict[str, float]] = {}
        #: the VARIANCE of each accumulated delta, propagated beside
        #: it. Held as variance rather than as a standard deviation because
        #: independent contributions add in variance and a walk sums many:
        #: keeping sigmas here would mean squaring and rooting at every edge.
        # SEEDED, not started empty, when the caller supplied a
        # spread for the values it overrode. A rollout seeded from a forecast
        # hands its band in here so a transition carries it downstream through
        # its own gain, exactly as it carries a declared `gain_sigma:`.
        #
        # AND IT IS KEYED BY THE SOURCE OF THE DOUBT, not pooled
        # into one variance per property. Each entry is
        # `{uncertainty source -> that source's SIGNED contribution to this
        # property, in the property's own units}`; the variance is the sum of
        # their squares, taken once at the end. One declared number reaching
        # a property by two routes lands in ONE bucket and adds linearly,
        # which is what being the same number means; two different
        # declarations land in two and add in quadrature, which is what
        # `independent_declared_spreads` has always claimed.
        imagined_spread: Dict[str, Dict[str, Dict[Any, float]]] = {
            eid: {prop: dict(contributions)
                  for prop, contributions in props.items()}
            for eid, props in (getattr(self, "seed_spread", None) or {}).items()}
        for eid, props in (getattr(self, "seed_variance", None) or {}).items():
            for prop, variance in props.items():
                bucket = imagined_spread.setdefault(eid, {}).setdefault(prop, {})
                bucket.setdefault(("seed", eid, prop), math.sqrt(variance))
        imagined_via: Dict[str, Dict[str, str]] = {}
        edges_without_dynamics: Set[str] = set()
        #:. (node, sink) pairs whose axioms are evaluated after
        #: the walk, once every contribution has landed. Simulating
        #: walks only; a reachability walk derives no values, so its
        #: per-node evaluation is already final when the node is popped.
        deferred_evaluations: List[Tuple[TwinNode, List[Problem]]] = []
        #:. Every declared transition the walk reached, held until the
        #: whole reachable subgraph is known. Applied in DEPENDENCY order
        #: afterwards, so a node's value is complete before anything reads it.
        pending_transitions: List[Tuple[Any, str, str, float, TwinNode]] = []
        budget_left = max(0, int(request.max_transitions))

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
                        priority=self._compute_priority(gap, hop),
                        context_path=list(path),
                    ))
                continue

            # Get property values based on value_mode
            values = self._get_values(node, request, imagined)
            imagined_properties: Set[str] = set()
            if simulating:
                for prop_name, value in values.items():
                    current = node.entity.properties.get(prop_name)
                    if isinstance(value, (int, float)) and value != current:
                        imagined_properties.add(prop_name)

            # Evaluate axiom states
            step_violations: List[Problem] = []
            if request.collect_axiom_violations:
                if simulating:
                    # DEFERRED, because on a simulating walk a
                    # node's value is not final when the node is popped. A
                    # target reachable by two acyclic paths of unequal length
                    # is popped at the shorter hop and the longer path's
                    # contribution arrives later; evaluating here drew
                    # findings from a partial value and then reported a
                    # different, complete one. The list object is handed to
                    # the step now and filled in place after the walk, so the
                    # step still carries its own violations.
                    deferred_evaluations.append((node, step_violations))
                else:
                    step_violations, attempted = self._evaluate_axioms(
                        node, values, imagined_properties)
                    result.problems_detected.extend(step_violations)
                    # Accumulated inside the
                    # `collect_axiom_violations` guard on purpose: with
                    # collection off nothing is evaluated, and the denominator
                    # must say zero rather than report the states the builder
                    # seeded.
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
                    # a declared transition on an edge that closes a
                    # LOOP. This `continue` predates value propagation and was
                    # right for reachability: a node already visited needs no
                    # second visit. For a VALUE it is not right, and it was
                    # silent: A->B->A dropped B's contribution back into A and
                    # reported A's number as though nothing were missing.
                    #
                    # Resolving it needs iteration to a fixpoint, which leaves
                    # first-order. So the loop is reported and the value is
                    # not adjusted -- the same choice every other refusal here
                    # makes. `cycle_unsupported` was in the vocabulary from
                    # the start and NOTHING COULD REACH IT, because this
                    # branch returns before the transition code runs: a dead
                    # member found by constructing the input for each reason
                    # rather than by grepping for the literal.
                    if simulating and edge.transitions:
                        # RECORDED, NOT JUDGED HERE. Whether this
                        # edge closes a loop is a property of the whole
                        # reachable subgraph, and the BFS only knows the one
                        # path it walked. `a->d` beside `a->b->c->d` looks
                        # identical from here to `a->b->a`; the difference is
                        # only visible once every edge is in hand. The
                        # ordering pass below decides, and it decides by
                        # whether the target has already been resolved.
                        pending_transitions.append(
                            (edge, current_id, next_id, cum_delay, node))
                    continue

                new_prob = cum_prob * edge.propagation_probability
                new_delay = cum_delay + edge.propagation_delay_s

                # a DECLARED transition is applied before the
                # reachability prune, and the prune does not discard the edge
                # that carries one.
                #
                # `propagation_probability` is P(target has a problem | source
                # has a problem) -- the co-occurrence `weight_learner` fits,
                # and 0.3 when nothing has been learned. A transition is a
                # different quantity entirely: a declared coupling between two
                # VALUES, with no probability attached. Multiplying the two
                # meant a declared gain three hops out was silenced by an
                # undeclared default: measured on a four-entity chain, hop 3
                # fell to 0.027 against `min_probability` 0.05 and the value
                # was never projected, with nothing said.
                #
                # Undeclared edges prune exactly as before, so a topology that
                # declares no transitions is unaffected.
                simulated_here = False
                if simulating:
                    if edge.transitions:
                        # deferred to the ordering pass, so the
                        # source's value is final before it is read. An edge
                        # applied when its source is popped carries whatever
                        # that source had accumulated SO FAR, which is not the
                        # same number on a graph where anything re-converges.
                        pending_transitions.append(
                            (edge, current_id, next_id, cum_delay, node))
                        simulated_here = True
                    else:
                        # No transitions: this only files `missing_dynamics`
                        # or `missing_declaration`, touches no value, and so
                        # does not care what order it runs in. Left inline so
                        # an edge inside a cycle still reports the gap even
                        # though the ordering pass will never reach it.
                        budget_left = self._apply_transitions(
                            edge=edge, source_id=current_id,
                            target_id=next_id,
                            source_values=values, node=node,
                            cum_delay_at_source=cum_delay,
                            request=request, result=result,
                            imagined=imagined, imagined_via=imagined_via,
                            imagined_spread=imagined_spread,
                            budget_left=budget_left,
                            edges_without_dynamics=edges_without_dynamics,
                        )

                # Pruning
                if new_prob < request.min_probability and not simulated_here:
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
                            priority=self._compute_priority(gap, hop + 1),
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
        if simulating and pending_transitions:
            budget_left = self._apply_in_dependency_order(
                pending_transitions, request=request, result=result,
                imagined=imagined, imagined_via=imagined_via,
                imagined_spread=imagined_spread,
                budget_left=budget_left,
                edges_without_dynamics=edges_without_dynamics)
        # Every contribution has landed, so the values these axioms
        # read are the ones the envelope reports. Drained in visit order so
        # `problems_detected` keeps the sequence a caller already relied on.
        for pending_node, sink in deferred_evaluations:
            final_values = self._get_values(pending_node, request, imagined)
            moved = {
                prop for prop, value in final_values.items()
                if isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value != pending_node.entity.properties.get(prop)
            }
            violations, attempted = self._evaluate_axioms(
                pending_node, final_values, moved)
            sink.extend(violations)
            result.problems_detected.extend(violations)
            result.axiom_evaluations_attempted += attempted
        if simulating:
            self._finalise_simulation(
                result, request, imagined, imagined_via, imagined_spread,
                visited,
                edges_without_dynamics)
        result.traversal_time_ms = (time.monotonic() - start_time) * 1000
        self.topology.last_traversal_at = now_utc()

        # The callsite-wire. Defensive: substrate-unavailable or gate-off
        # means a silent no-op, so the bootstrap-aware contract preserves the
        # kernel contract.
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

        candidate collection + set-cover assembly delegate to
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
        """Perturb nodes and forward-propagate.

        `horizon_s` was accepted and never passed on, so every
        caller got the `TraversalRequest` default of one hour whatever it
        asked for. A parameter a method takes and ignores is worse than one it
        does not offer: asking for ten minutes returned the one-hour answer
        with nothing to say it had.
        """
        return self.traverse(TraversalRequest(
            start_nodes=list(overrides.keys()),
            direction=TraversalDirection.FORWARD,
            value_mode=ValueMode.HYPOTHETICAL,
            overrides=overrides,
            max_hops=4,
            min_probability=0.05,
            horizon_s=horizon_s,
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
                       window: Optional[timedelta] = None,
                       model: Any = None) -> int:
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

        IT WILL NOT CHOOSE A MODEL ON THE AUTHOR'S BEHALF, and it
        used to. This method fitted a curve and extrapolated it for any series
        with three readings, whatever the model said, while the `project` verb
        looked at the same indicator and DECLINED `model_missing` with the
        sentence *no `dynamics` declared, so there is no model to fit; the
        engine will not choose one on the author's behalf*. Two paths, the
        same question, opposite answers -- and only one of them was the rule
        this package states about itself.

        Measured on a 120-sample random walk with no `dynamics:` declared:
        `project` declined, and this returned 2683.89 against a last reading
        of 2522.40 -- a confident extrapolation of +161 on a series going
        nowhere, which is the exact failure `projection/projector.py` names in
        its own opening as the reason a curve fit is not the default. Once
        `rollout(seed_mode="projected")` began FILING those values as
        predictions, the engine was scoring itself on numbers nobody declared
        a model for.

        The declaration is now read the same way `run_projection` reads it, so
        an undeclared indicator is left unprojected and the location is
        recorded for the caller to decline.
        """
        if self.history is None:
            return 0
        projector = self.trend_projector or TrendProjection()
        lookback = window or timedelta(hours=24)
        written = 0
        self.undeclared_dynamics = []
        #: (location, reason, detail) for every DECLARED model whose fit
        #: refused. Kept apart from `undeclared_dynamics` because the two
        #: send an author in opposite directions.
        self.projection_refusals = []
        #:. (entity, property) -> a callable taking a horizon in
        #: seconds and returning `(value, sigma)`. Kept because a ROLLOUT does
        #: not want one forecast, it wants the CURVE: every step of it is a
        #: different instant, and holding one horizon's answer across all of
        #: them says the source finished moving before the first step.
        self.projection_curves = {}
        declared = _declared_dynamics(model)

        for node in self.topology.nodes.values():
            entity = node.entity
            for prop_name, current in entity.properties.items():
                if not isinstance(current, (int, float)) or isinstance(current, bool):
                    continue
                if declared is not None and (
                        entity.type, prop_name) not in declared:
                    # No `dynamics:` on this indicator. Recorded, not fitted.
                    self.undeclared_dynamics.append(
                        f"{entity.id}.{prop_name}")
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
                spec = (declared or {}).get(
                    (entity.type, prop_name)) if declared else None
                if spec is not None:
                    # THE MODEL THE AUTHOR DECLARED, fitted by the
                    # same projector `run_projection` would use. Gating the
                    # old curve fit on a declaration was only half the
                    # unification: an author who declared `local_level` and
                    # got a trend extrapolation still had two paths answering
                    # one question two ways, with nothing saying which they
                    # had.
                    projected, refusal, curve = _project_declared(
                        values, spec, horizon_s)
                    if projected is None:
                        if refusal is not None:
                            self.projection_refusals.append(
                                (f"{entity.id}.{prop_name}", *refusal))
                        continue
                    node.projected_values[prop_name] = projected
                    if curve is not None:
                        self.projection_curves[
                            (entity.id, prop_name)] = curve
                    written += 1
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
        imagined: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Dict[str, Any]:
        """Get property values based on value_mode.

        ``imagined`` carries the DELTAS this traversal derived from
        declared transitions, and is overlaid last. Before it existed this
        method overlaid and never derived: a HYPOTHETICAL walk moved the
        properties the caller named on the nodes the caller named, and every
        other node in the topology was read at its present value. So a
        what-if on a pump reported which tank was reachable and reported the
        tank's level unchanged.

        ``None`` reproduces exactly the old behaviour, which is what a
        CURRENT-mode walk wants: it asks for no values, so it derives none.
        """
        if request.value_mode == ValueMode.CURRENT:
            return dict(node.entity.properties)
        values = dict(node.entity.properties)
        if request.value_mode == ValueMode.PROJECTED:
            for prop_name, pv in node.projected_values.items():
                values[prop_name] = pv.value
        elif request.value_mode == ValueMode.HYPOTHETICAL:
            values.update(request.overrides.get(node.entity.id, {}))
        deltas = (imagined or {}).get(node.entity.id) or {}
        for prop_name, delta in deltas.items():
            base = values.get(prop_name)
            if isinstance(base, (int, float)) and not isinstance(base, bool):
                values[prop_name] = base + delta
        return values

    def _apply_in_dependency_order(
        self, pending, *, request, result,
        imagined, imagined_via, imagined_spread,
        budget_left: int, edges_without_dynamics) -> int:
        """Apply every recorded transition with its source already resolved.

        THE WALK ORDER AND THE DEPENDENCY ORDER ARE NOT THE SAME
        ORDER, and applying a transition when the BFS happened to pop its
        source meant reading a value that was not finished. On any graph where
        two paths of unequal length meet, the shorter one arrives first, the
        node is carried onward at that partial value, and the longer path's
        contribution lands afterwards on a node whose own targets have already
        been written. Measured on `a->d` beside `a->b->c->d` with `d->e`: `d`
        ended correct at 3.0 and `e` sat at 2.0, short by the whole second
        path, with a decline that could only name the edge and not the damage.

        Kahn's algorithm over the recorded edges fixes the order rather than
        reporting the consequence. A node is resolved only once every edge
        into it has contributed, so `_get_values` reads a finished number and
        the downstream walk carries it.

        A CYCLE IS WHAT THIS CANNOT ORDER, which is the honest definition and
        a narrower one than the walk could give. Two cases produce it and both
        decline `cycle_unsupported`: an edge into a node already resolved, and
        an edge whose source never resolves because it sits inside the loop.
        An acyclic re-convergence is neither, and no longer reports anything --
        there is nothing left to report, because the value is now right.
        """
        from collections import deque

        out_edges: Dict[str, List[Any]] = {}
        indegree: Dict[str, int] = {}
        nodes: Set[str] = set()
        for record in pending:
            _, source_id, target_id, _, _ = record
            nodes.add(source_id)
            nodes.add(target_id)
            out_edges.setdefault(source_id, []).append(record)
            indegree[target_id] = indegree.get(target_id, 0) + 1
        for node_id in nodes:
            indegree.setdefault(node_id, 0)

        # The start nodes are ROOTS whatever points at them: their values were
        # supplied by the caller, not derived. Seeding them is what makes an
        # edge back into one read as the loop it is, rather than deadlocking
        # the whole pass.
        queue = deque(n for n in nodes if indegree[n] == 0)
        for start in request.start_nodes:
            if start in nodes and start not in queue:
                queue.append(start)

        resolved: Set[str] = set()
        while queue:
            current_id = queue.popleft()
            if current_id in resolved:
                continue
            resolved.add(current_id)
            source_node = None
            for record in out_edges.get(current_id, []):
                edge, source_id, target_id, cum_delay, source_node = record
                if target_id in resolved:
                    self._decline_cycle(result, source_id, target_id,
                                        closes=True)
                    continue
                budget_left = self._apply_transitions(
                    edge=edge, source_id=source_id, target_id=target_id,
                    # Read HERE, not when the edge was recorded: everything
                    # into this node has contributed by now, and that is the
                    # whole point of the ordering.
                    source_values=self._get_values(
                        source_node, request, imagined),
                    node=source_node, cum_delay_at_source=cum_delay,
                    request=request, result=result,
                    imagined=imagined, imagined_via=imagined_via,
                    imagined_spread=imagined_spread,
                    budget_left=budget_left,
                    edges_without_dynamics=edges_without_dynamics)
                indegree[target_id] -= 1
                if indegree[target_id] <= 0:
                    queue.append(target_id)

        for record in pending:
            _, source_id, target_id, _, _ = record
            if source_id not in resolved:
                # Its source never became orderable, so it sits INSIDE a loop
                # rather than closing one -- a different sentence, because an
                # author sent to look for the edge that closes the loop will
                # not find it here.
                self._decline_cycle(result, source_id, target_id,
                                    closes=False)
        return budget_left

    @staticmethod
    def _decline_cycle(result, source_id: str, target_id: str,
                       *, closes: bool) -> None:
        """One `cycle_unsupported`, de-duplicated by edge.

        TWO SENTENCES FOR TWO SITUATIONS. An edge into an already-resolved
        node CLOSES a loop and is the edge an author should look at. An edge
        whose source never resolved is INSIDE one -- it closes nothing, and
        telling its author to go and find the edge that closes the loop is
        advice that can fail: in `a->b->c->b` neither loop member ever
        resolves, so BOTH of its edges take this branch and no edge takes the
        other one. Measured, which is why the sentence says what is true of
        the value instead of pointing at a decline that may not be there.
        Both are `cycle_unsupported` because both are the same refusal.
        """
        if closes:
            detail = (f"this edge closes a loop back to {target_id}; its "
                      f"contribution is NOT in the reported value, because "
                      f"resolving a feedback path needs iteration to a "
                      f"fixpoint and that is not first-order")
        else:
            detail = (f"{source_id} sits inside a feedback loop, so its own "
                      f"value never settles and nothing it drives can be "
                      f"projected from it; this edge contributed nothing. "
                      f"Any value reported for {source_id} carries only the "
                      f"contributions from outside the loop. Declare the "
                      f"coupling in one direction, or accept that this "
                      f"first-order pass will not resolve it")
        decline = SimulationDecline(
            reason="cycle_unsupported", location=f"{source_id}->{target_id}",
            detail=detail)
        if decline not in result.simulation_declines:
            result.simulation_declines.append(decline)

    def _apply_transitions(
        self, *, edge, source_id: str, target_id: str,
        source_values: Dict[str, Any], node: TwinNode,
        cum_delay_at_source: float, request: TraversalRequest,
        result: TraversalResult,
        imagined: Dict[str, Dict[str, float]],
        imagined_via: Dict[str, Dict[str, str]],
        imagined_spread: Dict[str, Dict[str, Dict[Any, float]]],
        budget_left: int,
        edges_without_dynamics: Set[str],
    ) -> int:
        """Push one edge's declared transitions onto the target's deltas.

        Returns the remaining budget. Every refusal is recorded; none of them
        is a default.
        """
        label = f"{source_id}->{target_id}"

        refused = [g for g in edge.gaps
                   if g.gap_type is GapType.MISSING_DECLARATION]

        if not edge.transitions:
            if label in edges_without_dynamics:
                return budget_left
            edges_without_dynamics.add(label)
            if refused:
                # The author DID declare dynamics here and the block did not
                # load. Reporting `missing_dynamics` -- *no transition
                # declared* -- would be false, and false in the direction that
                # wastes the reader's time: they would go looking for a block
                # that is sitting in the file in front of them. Say which key
                # is missing instead.
                for gap in refused:
                    result.simulation_declines.append(SimulationDecline(
                        reason="missing_declaration", location=label,
                        detail=gap.description))
                return budget_left
            # The edge says how fast and how likely, and not how much. That is
            # a gap in the MODEL, and it already has a name.
            if True:
                result.simulation_declines.append(SimulationDecline(
                    reason="missing_dynamics", location=label,
                    detail=(f"no transition declared on "
                            f"{edge.relation_type!r}; the value the caller "
                            f"asked for is not projected across this edge")))
                if request.collect_gaps:
                    gap = TopologyGap(
                        gap_type=GapType.MISSING_DYNAMICS,
                        location=label,
                        description=(
                            f"edge {label} ({edge.relation_type}) declares no "
                            f"transition, so no downstream value follows "
                            f"from it"),
                        discovered_during="traverse",
                    )
                    result.gaps_discovered.append(gap)
                    result.questions_generated.append(TopologyQuestion(
                        gap=gap, question_text=gap.question,
                        priority=self._compute_priority(gap, 1),
                        context_path=[source_id, target_id],
                    ))
            return budget_left

        # A partial block beside valid ones: the valid transitions apply and
        # the refused one is still reported, because an author who declared
        # two couplings and got one is exactly who needs telling.
        for gap in refused:
            decline = SimulationDecline(
                reason="missing_declaration", location=label,
                detail=gap.description)
            if decline not in result.simulation_declines:
                result.simulation_declines.append(decline)

        # Time available for the response to develop, measured from when the
        # SOURCE moved. `response_fraction` subtracts this edge's own
        # propagation delay internally, so subtracting it here too would
        # charge it twice -- which reports zero response for the whole window
        # between one delay and two.
        elapsed = float(request.horizon_s) - float(cum_delay_at_source)

        for position, transition in enumerate(edge.transitions):
            result.transitions_attempted += 1
            if transition.estimated:
                # the pair is declared and the magnitude is not, so
                # nothing is projected across it. Reported rather than treated
                # as a zero gain: a zero gain is a claim that the coupling has
                # no effect, and this says nobody has supplied one yet.
                result.simulation_declines.append(SimulationDecline(
                    reason="gain_not_adopted", location=label,
                    detail=(f"{transition.from_property} -> "
                            f"{transition.to_property} declares "
                            f"`gain: estimate`; a fitted gain is a proposal "
                            f"and projects nothing until it is adopted")))
                continue
            if budget_left <= 0:
                # ONE decline carrying the count, filed in
                # `_finalise_simulation`. `causal/discovery.py` reports
                # `pairs_untested` as a single number for the same reason: a
                # decline per skipped item makes an exhausted budget look like
                # many different refusals, and buries the one fact the caller
                # needs, which is how much was left.
                result.transitions_unapplied += 1
                continue
            budget_left -= 1

            base = node.entity.properties.get(transition.from_property)
            now = source_values.get(transition.from_property)
            if not isinstance(now, (int, float)) or isinstance(now, bool):
                result.simulation_declines.append(SimulationDecline(
                    reason="missing_property", location=label,
                    detail=(f"{source_id}.{transition.from_property} is not a "
                            f"number, so no change can be measured from it")))
                continue
            if not isinstance(base, (int, float)) or isinstance(base, bool):
                base = now
            delta_source = float(now) - float(base)
            # A SOURCE THAT STANDS STILL CAN STILL BE UNCERTAIN,
            # and this returned before the variance term below ever ran.
            # `(gain * fraction)**2 * source_variance` does not depend on the
            # median at all, so a forecast whose median happens to equal the
            # reading lost its whole band on the way downstream.
            #
            # That is not a corner case. A `random_walk` forecast's median IS
            # the last observation -- the model's entire content is *what you
            # saw last is the best guess for what comes next* -- so any entity
            # whose property was set from its last reading, which is what a
            # collector writes, produces a delta of exactly zero at every
            # step. Measured: a source carrying +/- 62.75 rpm reached the tank
            # as no interval at all instead of +/- 1.25 points.
            source_spread = imagined_spread.get(source_id, {}).get(
                transition.from_property, {})
            if delta_source == 0.0 and not source_spread:
                continue

            # the `already_final` refusal that sat here is gone.
            # It could never fire: the visited branch returned before this
            # function was reached, so the flag was always False. Its premise
            # is also no longer true — axiom evaluation on a simulating walk
            # is deferred until every contribution has landed, so no target is
            # `already evaluated` while the walk is still running.

            fraction = edge.response_fraction(elapsed)
            # THE OFFSET IS PART OF THE PROPAGATION, so it is
            # charged the same response fraction as the gain term. It used to
            # be added in full the moment the source moved, which put a value
            # on the far end of an edge whose declared delay had not elapsed:
            # measured on a 120s delay with `offset: 7.0`, a walk at a 60s
            # horizon reported the target 7 units away from its reading while
            # `fraction` was 0.0. A declared dead time that a constant term
            # walks straight through is not a dead time.
            #
            # At `fraction == 1.0` this is arithmetically identical to what it
            # replaced, so a steady-state answer is unchanged.
            # THE OFFSET IS CHARGED ONCE PER COUPLING, not once
            # per movement of its source. A rollout walks one group per
            # distinct movement instant so that two movements of one property
            # superpose; the gain term is linear in the delta and superposes
            # correctly, but a constant term added in every group would be
            # charged as many times as the source moved and the steady state
            # would drift to `g*(d1+d2) + 2c`. It belongs to the edge, so it
            # develops from the FIRST instant the source moved and the caller
            # names the couplings whose offsets it has already taken.
            #
            # KEYED BY THE COUPLING, NOT BY THE SOURCE PROPERTY.
            # The first version of this key was `(source_id,
            # from_property)`, which is the right granularity for the same
            # coupling firing twice and the wrong one for TWO COUPLINGS
            # LEAVING ONE PROPERTY. Both are walked in a single pass, so the
            # first edge charged its offset and marked the property spent and
            # the second read it as spent and charged nothing -- in that step
            # and in every later one. Measured: a source moving 1.0 -> 2.0
            # with `offset: 5.0` to one neighbour and `offset: 7.0` to
            # another settled the second at 21.0 while `traverse`, which sets
            # no `offsets_charged` at all, said 28.0.
            #
            # The relation type and the transition's POSITION on the edge are
            # in the key because neither is implied by the endpoints: two
            # rules can join one pair of entities, and nothing stops one rule
            # declaring two transitions with the same `from:` and `to:`. Two
            # of those are two couplings and carry two offsets.
            charged = getattr(self, "offsets_charged", None)
            charge_key = (source_id, target_id, edge.relation_type, position,
                          transition.from_property, transition.to_property)
            spent = charged is not None and charge_key in charged
            offset = 0.0 if spent else transition.offset
            if delta_source == 0.0:
                # A STANDING SOURCE MOVES NOTHING. The offset is part of a
                # CHANGE, not a standing term, so a zero delta propagates a
                # zero value -- and, since, still propagates its
                # doubt, which is the whole reason this line is reachable.
                #
                # IT ALSO SPENDS NOTHING. Marking the offset charged here
                # would retire a constant term that was never applied, so a
                # later movement of the same source would silently lose it --
                # the mirror of the double-charge this mechanism exists to
                # prevent, and the more dangerous direction because the
                # steady state would come out LOW rather than high.
                delta_target = 0.0
            else:
                delta_target = (transition.gain * delta_source
                                + offset) * fraction
                if offset and charged is not None:
                    charged.add(charge_key)
            imagined.setdefault(target_id, {}).setdefault(
                transition.to_property, 0.0)
            imagined[target_id][transition.to_property] += delta_target

            # UNCERTAINTY PROPAGATED BESIDE THE VALUE, first order.
            # The contribution is `g * d * f`, so a declared spread on `g`
            # scales it by `d * f`, and any spread already on `d` -- an
            # upstream edge's -- scales by `g * f`. That is the same
            # superposition rule the value itself follows one line above.
            #
            # FIRST ORDER, and stamped as such: the product of two uncertain
            # gains along a chain is not Gaussian, and this is the delta
            # method, exact for one hop and an approximation beyond it. The
            # engine already tells a reader its response is first order; this
            # is the same statement about the spread.
            #
            # CARRIED SIGNED AND PER SOURCE. Squaring here and
            # summing pooled the contributions, which is the rule for
            # INDEPENDENT ones and silently applied it to a single declared
            # number arriving twice: once per movement group in a rollout,
            # and once per path in a walk where two routes meet again. The
            # sign matters as much as the pooling -- a source moved out and
            # back leaves its target where it started FOR ANY GAIN, so the
            # contributions must be able to cancel. Squares are taken in
            # `_finalise_simulation`, once, after everything has landed.
            bucket = imagined_spread.setdefault(target_id, {}).setdefault(
                transition.to_property, {})
            if transition.gain_sigma:
                own = ("gain",) + charge_key
                bucket[own] = bucket.get(own, 0.0) + (
                    transition.gain_sigma * delta_source * fraction)
            carried = transition.gain * fraction
            if carried:
                for source_key, contribution in source_spread.items():
                    bucket[source_key] = bucket.get(source_key, 0.0) + (
                        carried * contribution)
            imagined_via.setdefault(target_id, {})[
                transition.to_property] = transition.source
            result.transitions_applied.append(TransitionApplied(
                edge=label, relation_type=edge.relation_type,
                from_property=transition.from_property,
                to_property=transition.to_property,
                delta_source=delta_source, gain=transition.gain,
                fraction=fraction, delta_target=delta_target,
                source=transition.source, elapsed_s=elapsed,
            ))
        return budget_left

    def _finalise_simulation(
        self, result: TraversalResult, request: TraversalRequest,
        imagined: Dict[str, Dict[str, float]],
        imagined_via: Dict[str, Dict[str, str]],
        imagined_spread: Dict[str, Dict[str, Dict[Any, float]]],
        visited: Set[str], edges_without_dynamics: Set[str],
    ) -> None:
        """Turn the delta map into absolute values and stamp the assumptions.

        The assumptions are stamped because the engine made them, not because
        the author declared them -- the same contract
        `forecast/contract.py` follows when it widens a `mean`+`sigma` record
        into quantiles and says `gaussian_from_mean_sigma` out loud.
        """
        for entity_id, deltas in imagined.items():
            node = self.topology.get_node(entity_id)
            if node is None:
                continue
            for prop_name, delta in deltas.items():
                base = node.entity.properties.get(prop_name)
                if not isinstance(base, (int, float)) or isinstance(base, bool):
                    continue
                result.imagined_values.setdefault(entity_id, {})[
                    prop_name] = float(base) + delta
                result.imagined_sources.setdefault(entity_id, {})[
                    prop_name] = imagined_via.get(entity_id, {}).get(
                        prop_name, "")
                # THE SQUARES ARE TAKEN HERE, once, over the
                # per-source contributions the walk accumulated signed. A
                # caller that has to combine several walks (the rollout does,
                # one per movement instant) needs the contributions rather
                # than this number, so both are reported.
                contributions = imagined_spread.get(entity_id, {}).get(
                    prop_name, {})
                if contributions:
                    result.imagined_spread.setdefault(entity_id, {})[
                        prop_name] = dict(contributions)
                variance = sum(c * c for c in contributions.values())
                if variance > 0.0:
                    result.imagined_sigma.setdefault(entity_id, {})[
                        prop_name] = math.sqrt(variance)

        if result.transitions_unapplied:
            result.simulation_declines.append(SimulationDecline(
                reason="budget_exhausted",
                location=f"max_transitions={request.max_transitions}",
                detail=(f"{result.transitions_unapplied} of "
                        f"{result.transitions_attempted} transitions were not "
                        f"applied: the budget was reached. Raise "
                        f"`max_transitions` to widen the walk.")))

        projected = set(result.imagined_values)
        result.nodes_not_projected = sorted(
            n for n in visited
            if n not in projected and n not in request.start_nodes)

        if result.imagined_sigma:
            # Said out loud, because an interval is the thing a reader is most
            # likely to take as exact.
            #
            # `independent_declared_spreads` is now only what it
            # says. It used to cover two different things at once: the
            # genuine assumption that two authors' `gain_sigma:` lines are
            # unrelated -- which this engine cannot check and a reader should
            # know it is making -- and the arithmetic mistake of treating ONE
            # declared number as independent of itself when it reached a
            # property twice. The second is gone, so the stamp is a claim
            # about the model rather than an excuse for the walk.
            result.assumptions.append("first_order_uncertainty")
            result.assumptions.append("independent_declared_spreads")
        if result.transitions_applied:
            result.assumptions.append("linear_superposition")
            result.assumptions.append("first_order_response")
            result.assumptions.append("exogenous_inputs_held")
            if any(t.fraction >= 1.0 for t in result.transitions_applied):
                result.assumptions.append("steady_state_reached")
            result.assumptions.append("declared_coupling_not_probability_pruned")

    def _evaluate_axioms(
        self, node: TwinNode, values: Dict[str, Any],
        imagined_properties: Optional[Set[str]] = None,
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

        **BOUNDEDNESS only** — and, until, only HALF of BOUNDEDNESS.
        The body compared against `warning` and `critical` and never against
        `lower_warning` / `lower_critical`, so a declared FLOOR was invisible
        here while `UnifiedAxiomReasoner` reported it: a traversal over a
        pump below its stall floor returned no finding and an
        `invariants` denominator saying two invariants had been evaluated.
        A count that says a check ran is worse than a silent gap, because it
        is the surface a caller would use to notice one. Both directions are
        read now; see `TwinBuilder._read_indicator` for the other half of the
        fix, which is where the floors were being dropped.

        The line this docstring used to carry — "other
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
        imagined_properties = imagined_properties or set()
        before = 0
        for key, axiom_state in node.axiom_states.items():
            prop_name = axiom_state.indicator_name
            if not prop_name or prop_name not in values:
                continue
            value = values.get(prop_name)
            if value is None or not isinstance(value, (int, float)):
                continue

            # Check BOUNDEDNESS bounds from evidence — both directions.
            if axiom_state.axiom == Axiom.BOUNDEDNESS:
                # Counted HERE and not at the top of the loop: the two
                # `continue`s above skip states that were never evaluated, and
                # a non-BOUNDEDNESS state reaching this line is not evaluated
                # either. The denominator has to mean attempted, so it is
                # incremented at the point an attempt actually begins.
                attempted += 1
                before = len(problems)
                warning = axiom_state.evidence.get('warning')
                critical = axiom_state.evidence.get('critical')
                lower_warning = axiom_state.evidence.get('lower_warning')
                lower_critical = axiom_state.evidence.get('lower_critical')
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
                # the floor half. `elif` against the ceiling chain
                # deliberately: one reading cannot be both above a ceiling and
                # below a floor unless the declaration itself is inverted, and
                # reporting one finding for one reading is what the dedup in
                # the reasoner assumes.
                elif lower_critical is not None and value < lower_critical:
                    problems.append(Problem.from_entity(
                        entity=node.entity,
                        problem_type=f'twin_boundedness:{prop_name}',
                        severity=Severity.CRITICAL,
                        reason=(
                            f"{prop_name}={value} is below "
                            f"lower_critical={lower_critical}"
                        ),
                        axiom=Axiom.BOUNDEDNESS,
                        source_layer=DetectionLayer.ONTOLOGY,
                        evidence={
                            'property': prop_name,
                            'value': value,
                            'lower_critical': lower_critical,
                        },
                    ))
                elif lower_warning is not None and value < lower_warning:
                    problems.append(Problem.from_entity(
                        entity=node.entity,
                        problem_type=f'twin_boundedness:{prop_name}',
                        severity=Severity.WARNING,
                        reason=(
                            f"{prop_name}={value} is below "
                            f"lower_warning={lower_warning}"
                        ),
                        axiom=Axiom.BOUNDEDNESS,
                        source_layer=DetectionLayer.ONTOLOGY,
                        evidence={
                            'property': prop_name,
                            'value': value,
                            'lower_warning': lower_warning,
                        },
                    ))
                # a finding drawn from a value this traversal
                # IMAGINED says so in its own type. Before this, a what-if
                # that pushed a pump past its ceiling reported
                # `twin_boundedness:speed_rpm` -- byte-identical to the
                # finding a pump actually past its ceiling produces. A reader
                # holding the two envelopes could not tell "your system is
                # breaking" from "your model of your system would break".
                if prop_name in imagined_properties:
                    for problem in problems[before:]:
                        problem.problem_type = (
                            IMAGINED_PREFIX + problem.problem_type)
                        problem.evidence['imagined'] = True
        return problems, attempted

    def _compute_priority(self, gap: TopologyGap, hop: int) -> float:
        """Higher = more blocking.

        **`probability` was a third factor here and is gone.** It was the edge's
        `propagation_probability` -- fault-propagation dynamics, sitting in the
        model beside `propagation_delay_s` and `time_constant_s` -- multiplied
        into the priority of a DISCOVERY question. Those are different
        questions: a dangling reference is worth the same to ask about whether
        or not disturbances travel strongly along the edge that led you to it.

        It made the ranking incoherent rather than merely odd. The default
        probability is 0.3, so a gap two hops out was scaled by 0.09 on top of
        the hop decay, and measured, a MISSING_NODE -- the highest weight in the
        table, because it means the topology itself is wrong -- came out at 0.03
        and sorted below every structural gap in the same list. `gaps` documents
        itself as priority-ranked, and with two populations on two scales it was
        not one.

        What is left is one meaning: **the type's weight, decayed by how far the
        walk had to go to find it.** A structural gap has no hops and is scored
        at hop zero, so both populations sit on this scale by construction.
        """
        hop_factor = 1.0 / (1 + hop)
        type_weight = {
            GapType.MISSING_NODE: 1.0,
            GapType.MISSING_EDGE: 0.8,
            GapType.MISSING_PROPERTY: 0.6,
            GapType.MISSING_THRESHOLD: 0.4,
            GapType.MISSING_DYNAMICS: 0.2,
            # between a missing edge and a missing property. It
            # blocks a whole axiom family on the entity rather than one
            # reading, and unlike every other member it cannot be cleared by
            # collecting more data.
            GapType.MISSING_DECLARATION: 0.7,
        }
        # Rounded because this is a ranking key, not a measurement: a raw
        # third of one is `0.3333333333333333` in published JSON, and three
        # places separate every pair the table can produce.
        return round(hop_factor * type_weight.get(gap.gap_type, 0.5), 3)

    def _check_flow_balance(self, cycle_path: List[str]) -> List[Problem]:
        """Verify conservation around a flow cycle, from DECLARED directions.

        This used to decide which of an entity's properties were inflows by
        matching their names against English tokens. That blind spot was
        recorded once and then narrowed twice before it was removed, because
        the information is not in the names. It now reads
        ``TwinNode.flow_directions`` — seeded by the builder from the model's
        declared ``flow:`` — and a node with no declaration yields a gap rather
        than a balance.

        The gap matters more than the silence it replaces. Dropping the check
        quietly would leave an operator who wanted a balance with no way to
        find out why they were not getting one; the gap names the candidate
        properties a name scan would have offered, so confirming them is a
        declaration to write rather than a search to run.
        """
        problems: List[Problem] = []
        for node_id in cycle_path[:-1]:
            node = self.topology.get_node(node_id)
            if not node:
                continue
            props = node.entity.properties
            declared = getattr(node, 'flow_directions', None) or {}
            if not declared:
                self._report_undeclared_flow(node, node_id, props)
                continue
            # bool is a subclass of int, so it is excluded explicitly: a flag
            # named engage_human_in_loop would otherwise contribute 1 to
            # inflow. It no longer reaches here by name — but a model is free
            # to declare `flow:` on a STATE indicator, and the sum must still
            # refuse to add a boolean to a quantity.
            flow_in = sum(
                v for k, v in props.items()
                if declared.get(k) == 'in'
                and isinstance(v, (int, float))
                and not isinstance(v, bool)
            )
            flow_out = sum(
                v for k, v in props.items()
                if declared.get(k) == 'out'
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

    def _report_undeclared_flow(
        self, node: TwinNode, node_id: str, props: Dict[str, Any],
    ) -> None:
        """The candidates surface for an undeclared flow balance.

        Records ONE gap per node naming the properties whose names suggest a
        direction. The suggestion is carried in the description and nowhere
        else: nothing downstream reads it as a direction, which is the
        difference between this and the path it replaces.

        Idempotent on ``(gap_type, location)``. ``traverse`` reaches the same
        node once per cycle it participates in, and `api.gaps` deduplicates on
        that key anyway — but a list that grows without bound across a long
        session is a leak whether or not its reader deduplicates.
        """
        location = f"{node_id}.flow"
        if any(g.gap_type == GapType.MISSING_DECLARATION
               and g.location == location for g in node.gaps):
            return
        candidates = sorted(
            f"{k}={suggest_flow_direction(k)}"
            for k, v in props.items()
            if suggest_flow_direction(k) is not None
            and isinstance(v, (int, float)) and not isinstance(v, bool)
        )
        detail = (f"; name-based candidates, none of them asserted: "
                  f"{', '.join(candidates)}" if candidates else
                  "; no property name even suggests a direction")
        gap = TopologyGap(
            gap_type=GapType.MISSING_DECLARATION,
            location=location,
            description=(
                f"{node_id} is on a flow cycle and no indicator on its type "
                f"declares flow:, so no balance was computed{detail}"),
            suggested_strategy=ResolutionStrategy.HUMAN_PROVIDE,
        )
        node.gaps.append(gap)
        self.topology.gaps.append(gap)

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
    the internal notes). It was BUILT in, it does not live here: the full system
    holds it, outside the published distribution, and takes a translator as its
    first argument.

    **This class is rule-based, and that is now the whole of it** rather than a
    stage it is passing through. Earlier wording here described the wiring as
    unfinished, and stayed after finished it a few hundred lines below,
    so the docstring and the code disagreed inside one file. An outside
    verification read the docstring and reported the path as unbuilt; it was
    built, and in the shipped package it was inert, which is a third thing
    again. (The superseded phrasing is deliberately not quoted: a guard below
    greps this docstring for it, and prose about a removal reads to a grep
    exactly like the removal not having happened.)

    Substrate-discovery surface for partners (the established pattern
    bootstrap-aware shape): the GET /nl-query endpoint enumerates the 7
    keyword-pattern set + 3-direction + 3-value-mode vocabularies +
    decision-doc cross-link. The two citations were pinned by a test and
    absent from this docstring before -- red from the day they were
    written, and unnoticed because the file they guard was not in a lane
    anybody watched.
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

    # THE LLM FALLBACK IS NOT PART OF THIS CLASS ANY MORE, AND NOT PART OF
    # THE PUBLISHED ENGINE. Shipped, its env gate was inert and silent: the
    # path it enabled imports `shared.llm`, which the distribution does not
    # carry, and the failure was swallowed -- so `true` and `false` both
    # returned None, with no error and no log. Enabling the feature and
    # leaving it off were indistinguishable.
    #
    # It now lives in the full system, which is held
    # back from the distribution, and takes the translator as its first
    # argument. `translate()` below is deterministic and needs no client.


# ---------------------------------------------------------------------------
#: 3-tier escalation decision
# ---------------------------------------------------------------------------

# The canonical-invariant shape (promotion).
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


def classify_escalation_tier(
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

    The canonical-invariant shape (rule/template + LLM-fallback
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

        The canonical-invariant shape.
        """
        rule_based = self.base.translate(nl_text, entity_ids=entity_ids)

        if rule_based is not None:
            tier, reason = classify_escalation_tier(
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
        # A caller inside the orchestrator may bypass to the LLM via
        # the full system, which is not shipped; the
        # 3-tier shape's default is candidate-presentation either way.
        return NLTranslationResult(
            tier=2,
            nl_text=nl_text,
            tier2_candidates=[],  # an orchestrator caller may fill these; not shipped
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
