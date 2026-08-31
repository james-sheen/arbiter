""" TopologyOptimizer core —.

6th DT-mode OPTIMIZE substrate. Walks DigitalTwinTopology under operator
objective function + constraint set, returns Pareto-front of action plans.

Per /round-eval Part 4.C criterion #7 + Lever 1
(kernel parameter-space extension via value_mode), this is the 3rd kernel-
amplification axis sibling to (DISCOVER 4th-mode) + (HYPOTHESIZE
5th-mode). Schema decided at Flavor D hybrid frozen-typed + NL-overlay.

The kernel-as-atom design centre — kernel mode-extension is the canonical
kernel-amplification move.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid

from ..clock import now_utc


# ---------------------------------------------------------------------------
# Module-level canonical constants (Flavor D schema)
# ---------------------------------------------------------------------------

OPTIMIZATION_MIN_PARETO_FRONT_SIZE: int = 1
OPTIMIZATION_MAX_EVALUATIONS: int = 64


# ---------------------------------------------------------------------------
# Frozen-typed request schema Decision (7 fields)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConstraintExpr:
    """Opaque constraint expression evaluated against AxiomState. Domain-opaque."""

    expression: str
    operator: str  # one of {"<=", ">=", "=="}
    bound: float


@dataclass(frozen=True)
class OptimizationRequest:
    """Frozen-typed optimization request. Hash-stable identity via request_id.

    Per audit-pin: hash-stable BY CONSTRUCTION. Mutation flows
    (Pareto-front evaluation results) belong in companion sidecar records
    (ProductionOptimization ring), not in identity.
    """

    request_id: str
    objective_function: str  # opaque expression evaluated against AxiomState
    constraints: List[ConstraintExpr]
    start_nodes: List[str]
    max_evaluations: int
    tenant_id: str
    nl_text: Optional[str] = None


@dataclass(frozen=True)
class ActionPlanPoint:
    """Single point on the Pareto-front: (action_plan, objective_value, constraint_satisfaction)."""

    plan_id: str
    action_plan: Dict[str, Any]
    objective_value: float
    constraint_satisfaction: float  # [0.0, 1.0]
    dominated: bool = False


# ---------------------------------------------------------------------------
# TopologyOptimizer core
# ---------------------------------------------------------------------------

class TopologyOptimizer:
    """Walks a DigitalTwinTopology under objective + constraints, returns
    Pareto-front of action plans.

    Composes with TopologyTraverser kernel (via value_mode='optimal'
    extension per Lever 1) +
    HypothesisGenerator (hypotheses-as-objective-candidates).

    Per the domain-agnostic foundation rule: objective_function +
    constraints are opaque expressions evaluated against AxiomState; per-
    domain semantics come from YAML topology only.
    """

    def __init__(
        self,
        max_evaluations: int = OPTIMIZATION_MAX_EVALUATIONS,
        tenant_id: str = "default",
    ) -> None:
        if max_evaluations < OPTIMIZATION_MIN_PARETO_FRONT_SIZE:
            raise ValueError(
                f"max_evaluations must be >= {OPTIMIZATION_MIN_PARETO_FRONT_SIZE}"
            )
        self.max_evaluations = int(max_evaluations)
        self.tenant_id = str(tenant_id)

    def optimize(
        self,
        topology: Any,
        request: OptimizationRequest,
        objective_evaluator: Optional[Callable[[Any, Any], float]] = None,
        constraint_evaluator: Optional[Callable[[Any, ConstraintExpr], float]] = None,
    ) -> List[ActionPlanPoint]:
        """Walk topology + return Pareto-front of action plans.

        Evaluator callbacks default to canonical-opaque-string-eval helpers
        that interpret objective_function + constraint.expression as
        attribute-path lookups on AxiomState. Partner-side override allowed
        via callable injection (for testing + per-domain plug-in).
        """
        if not request.start_nodes:
            return []
        if objective_evaluator is None:
            objective_evaluator = self._default_objective_evaluator
        if constraint_evaluator is None:
            constraint_evaluator = self._default_constraint_evaluator

        plans: List[ActionPlanPoint] = []
        nodes_map = getattr(topology, "nodes", {})
        edges_map = getattr(topology, "edges", {})
        cap = min(request.max_evaluations, self.max_evaluations)

        for node_id in request.start_nodes:
            node = nodes_map.get(node_id)
            if node is None:
                continue
            for plan_id, plan_data in self._candidate_plans(node, edges_map, cap):
                try:
                    obj_val = objective_evaluator(node, request.objective_function)
                except (AttributeError, TypeError, ValueError):
                    continue
                csat = 1.0
                for c in request.constraints:
                    try:
                        sat = constraint_evaluator(node, c)
                        csat = min(csat, sat)
                    except (AttributeError, TypeError, ValueError):
                        csat = 0.0
                        break
                plans.append(
                    ActionPlanPoint(
                        plan_id=plan_id,
                        action_plan=plan_data,
                        objective_value=obj_val,
                        constraint_satisfaction=csat,
                    )
                )
                if len(plans) >= cap:
                    break
            if len(plans) >= cap:
                break

        return self._pareto_filter(plans)

    def _candidate_plans(
        self,
        node: Any,
        edges_map: Dict[str, Any],
        cap: int,
    ):
        """Generate (plan_id, plan_data) candidates from outgoing edges of node.

        Each outgoing edge becomes a candidate "action plan" with the edge's
        target as the proposed action target.
        """
        entity_id = getattr(getattr(node, "entity", None), "id", None)
        if entity_id is None:
            return
        outgoing = edges_map.get(entity_id, [])
        for i, edge in enumerate(outgoing[:cap]):
            target_id = getattr(edge, "target_id", None)
            if target_id is None:
                continue
            yield (
                str(uuid.uuid4()),
                {
                    "source": entity_id,
                    "target": target_id,
                    "edge_index": i,
                },
            )

    def _default_objective_evaluator(self, node: Any, expression: str) -> float:
        """Default objective evaluator — interprets expression as attribute path.

        Example: expression='entity.properties.cost' → node.entity.properties.cost.
        Domain-opaque (no per-domain dispatch).
        """
        path = expression.split(".")
        obj = node
        for part in path:
            obj = getattr(obj, part, None)
            if obj is None:
                return 0.0
        try:
            return float(obj)
        except (TypeError, ValueError):
            return 0.0

    def _default_constraint_evaluator(
        self,
        node: Any,
        constraint: ConstraintExpr,
    ) -> float:
        """Default constraint evaluator — returns satisfaction in [0.0, 1.0].

        1.0 = fully satisfied; 0.0 = fully violated. Linear interpolation in
        between for partial satisfaction near boundary.
        """
        value = self._default_objective_evaluator(node, constraint.expression)
        bound = constraint.bound
        op = constraint.operator
        if op == "<=":
            return 1.0 if value <= bound else max(0.0, 1.0 - (value - bound) / max(abs(bound), 1.0))
        if op == ">=":
            return 1.0 if value >= bound else max(0.0, 1.0 - (bound - value) / max(abs(bound), 1.0))
        if op == "==":
            return 1.0 if value == bound else max(0.0, 1.0 - abs(value - bound) / max(abs(bound), 1.0))
        return 0.0

    def _pareto_filter(
        self,
        plans: List[ActionPlanPoint],
    ) -> List[ActionPlanPoint]:
        """Return non-dominated plans on (objective_value descending, constraint_satisfaction descending).

        Plan A dominates plan B iff A.objective_value >= B.objective_value AND
        A.constraint_satisfaction >= B.constraint_satisfaction AND at least
        one is strictly greater.
        """
        if len(plans) <= 1:
            return list(plans)
        front: List[ActionPlanPoint] = []
        for candidate in plans:
            dominated = False
            for other in plans:
                if other is candidate:
                    continue
                if (
                    other.objective_value >= candidate.objective_value
                    and other.constraint_satisfaction >= candidate.constraint_satisfaction
                    and (
                        other.objective_value > candidate.objective_value
                        or other.constraint_satisfaction > candidate.constraint_satisfaction
                    )
                ):
                    dominated = True
                    break
            if not dominated:
                front.append(candidate)
        return front

    # ----- emit() — callsite-wire to production substrate -----

    def emit(self, request: OptimizationRequest, plans: List[ActionPlanPoint]) -> int:
        """Record the optimization invocation to the production substrate.

        Defensive import — production module may not be present (the
        bootstrap-aware contract). Returns count of plans recorded.
        """
        try:
            from arbiter_engine.twin.optimization_production import (
                record_production_optimization,
            )
        except ImportError:
            return 0
        try:
            record_production_optimization(
                request_id=request.request_id,
                pareto_front_size=len(plans),
                max_objective_value=max((p.objective_value for p in plans), default=0.0),
                max_constraint_satisfaction=max((p.constraint_satisfaction for p in plans), default=0.0),
                tenant_id=request.tenant_id,
                observed_at=now_utc(),
            )
        except (TypeError, ValueError):
            return 0
        return len(plans)


# ---------------------------------------------------------------------------
# NLOptimizationTranslator — on the canonical-invariant shape.
# ---------------------------------------------------------------------------


from dataclasses import field as _opt_field


@dataclass
class NLOptimizationTranslationResult:
    """Discriminated 3-tier outcome of NL → OptimizationRequest."""

    tier: int
    nl_text: str
    tier1_request: Optional[OptimizationRequest] = None
    tier2_candidates: List[OptimizationRequest] = _opt_field(default_factory=list)
    tier3_pending_confirmation: Optional[OptimizationRequest] = None
    tier3_reason: Optional[str] = None


class NLOptimizationTranslator:
    """3-tier NL → OptimizationRequest translator, on the canonical-invariant
    shape.

    Per Lever 4 applied to optimization
    objective + constraints NL parsing.
    """

    _DIRECTION_KEYWORDS: Dict[str, List[str]] = {
        "minimize": ["minimize", "min", "lowest", "reduce"],
        "maximize": ["maximize", "max", "highest", "increase"],
    }

    _CONSTRAINT_KEYWORDS: Dict[str, List[str]] = {
        "<=": ["at most", "below", "under", "less than"],
        ">=": ["at least", "above", "over", "more than"],
        "==": ["exactly", "equal to", "equals"],
    }

    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = str(tenant_id)

    def translate_with_3_tier_escalation(
        self,
        nl_text: str,
        severity_floor: str = "MEDIUM",
        cross_tenant_start_nodes: Optional[List[str]] = None,
    ) -> NLOptimizationTranslationResult:
        """NL → OptimizationRequest with 3-tier escalation."""
        nl_lower = nl_text.lower()

        # Detect direction (minimize/maximize) for objective_function
        direction_detected = None
        for direction, kws in self._DIRECTION_KEYWORDS.items():
            if any(kw in nl_lower for kw in kws):
                direction_detected = direction
                break

        if direction_detected is None:
            return NLOptimizationTranslationResult(
                tier=3,
                nl_text=nl_text,
                tier3_reason="no_direction_detected",
            )

        # Detect constraint operators
        constraints_detected: List[str] = []
        for op, kws in self._CONSTRAINT_KEYWORDS.items():
            if any(kw in nl_lower for kw in kws):
                constraints_detected.append(op)

        objective_fn = f"{direction_detected}:entity.properties.cost"  # placeholder
        constraints = [
            ConstraintExpr(expression="entity.properties.bound", operator=op, bound=0.0)
            for op in constraints_detected
        ]

        request = OptimizationRequest(
            request_id=str(uuid.uuid4()),
            objective_function=objective_fn,
            constraints=constraints,
            start_nodes=[],
            max_evaluations=64,
            tenant_id=self.tenant_id,
            nl_text=nl_text,
        )

        # Tier 3 escalation
        if cross_tenant_start_nodes and len(set(cross_tenant_start_nodes)) > 1:
            return NLOptimizationTranslationResult(
                tier=3,
                nl_text=nl_text,
                tier3_pending_confirmation=request,
                tier3_reason="cross_tenant",
            )
        if severity_floor.upper() in ("HIGH", "CRITICAL"):
            return NLOptimizationTranslationResult(
                tier=3,
                nl_text=nl_text,
                tier3_pending_confirmation=request,
                tier3_reason="high_severity",
            )

        return NLOptimizationTranslationResult(
            tier=1,
            nl_text=nl_text,
            tier1_request=request,
        )


OPTIMIZE_COMPOSE_TOOL_DEF: Dict[str, Any] = {
    "name": "optimize_compose",
    "description": (
        "Submit optimization request via NL → typed OptimizationRequest. "
        "On the canonical-invariant shape.  "
        "Lever 4. Direction-detection + 3-operator constraint mapping."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "nl_text": {"type": "string"},
            "tenant_id": {"type": ["string", "null"]},
        },
        "required": ["nl_text"],
    },
}
