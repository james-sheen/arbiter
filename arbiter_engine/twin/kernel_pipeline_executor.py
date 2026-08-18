""" KernelPipelineExecutor core —.

Atomic multi-mode cognitive workflow substrate. Composes TopologyTraverser
+ HypothesisGenerator + TopologyOptimizer + /dt-gaps into single round-trip
via `pipeline: List[PipelineStep]` field — partners submit DISCOVER →
HYPOTHESIZE → OPTIMIZE workflows in one /traverse-pipeline call.

Per Lever 1+4 cross-cut: kernel parameter-
space extension (pipeline field) + NL-translator depth (NLPipelineTranslator).

the established pattern design-center reuse — kernel mode composition is the canonical
kernel-amplification move.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import uuid

from ..clock import now_utc


KERNEL_MODE_TRAVERSE: str = "TRAVERSE"
KERNEL_MODE_DISCOVER: str = "DISCOVER"
KERNEL_MODE_HYPOTHESIZE: str = "HYPOTHESIZE"
KERNEL_MODE_OPTIMIZE: str = "OPTIMIZE"
KNOWN_KERNEL_MODES: tuple = (
    KERNEL_MODE_TRAVERSE,
    KERNEL_MODE_DISCOVER,
    KERNEL_MODE_HYPOTHESIZE,
    KERNEL_MODE_OPTIMIZE,
)

PIPELINE_MAX_STEPS: int = 16

# (Track-A A-5): per-step honesty markers — the same vocabulary the
# the established pattern envelopes speak one layer up. "unavailable" means the step ran
# but had no substrate/topology to consult; "no findings" (live + zero
# counts) stays distinguishable from "not looking".
STEP_SOURCE_LIVE: str = "live"
STEP_SOURCE_UNAVAILABLE: str = "unavailable"


@dataclass(frozen=True)
class PipelineStep:
    """Single step in a multi-mode kernel pipeline schema."""

    step_id: str
    mode: str
    parameters: Dict[str, Any]
    downstream_field: Optional[str] = None


@dataclass(frozen=True)
class PipelineRequest:
    """Atomic multi-mode pipeline request schema."""

    pipeline_id: str
    pipeline: List[PipelineStep]
    tenant_id: str = "default"
    nl_text: Optional[str] = None


@dataclass(frozen=True)
class PipelineStepResult:
    """Result of one pipeline step execution."""

    step_id: str
    mode: str
    status: str  # one of {"success", "skipped", "failed"}
    output: Dict[str, Any]
    error: Optional[str] = None


@dataclass(frozen=True)
class PipelineResult:
    """Aggregate result of pipeline execution."""

    pipeline_id: str
    step_results: List[PipelineStepResult]
    total_steps: int
    succeeded_steps: int
    failed_steps: int
    execution_time_ms: float


class KernelPipelineExecutor:
    """Orchestrates step-by-step kernel-mode invocations + chains outputs.

    Each step.mode routes to corresponding kernel substrate. downstream_field
    mapping carries output-of-step-N as input-of-step-N+1.

    Domain-agnostic by construction — modes + parameters are opaque to the
    executor.
    """

    def __init__(
        self,
        max_steps: int = PIPELINE_MAX_STEPS,
        tenant_id: str = "default",
        fail_fast: bool = True,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        self.max_steps = int(max_steps)
        self.tenant_id = str(tenant_id)
        self.fail_fast = bool(fail_fast)

    def execute(
        self,
        topology: Any,
        request: PipelineRequest,
    ) -> PipelineResult:
        """Execute pipeline; return aggregate result."""
        start = now_utc()
        steps_to_run = list(request.pipeline)[: self.max_steps]
        results: List[PipelineStepResult] = []
        upstream_output: Dict[str, Any] = {}

        for step in steps_to_run:
            if step.mode not in KNOWN_KERNEL_MODES:
                results.append(PipelineStepResult(
                    step_id=step.step_id,
                    mode=step.mode,
                    status="failed",
                    output={},
                    error=f"unknown_mode:{step.mode}",
                ))
                if self.fail_fast:
                    break
                continue

            params = dict(step.parameters)
            if upstream_output:
                params.setdefault("_upstream", upstream_output)

            try:
                output = self._dispatch_step(step.mode, topology, params)
                results.append(PipelineStepResult(
                    step_id=step.step_id,
                    mode=step.mode,
                    status="success",
                    output=output,
                ))
                if step.downstream_field and step.downstream_field in output:
                    upstream_output = {step.downstream_field: output[step.downstream_field]}
            except Exception as exc:  # noqa: BLE001
                results.append(PipelineStepResult(
                    step_id=step.step_id,
                    mode=step.mode,
                    status="failed",
                    output={},
                    error=f"{type(exc).__name__}:{str(exc)[:64]}",
                ))
                if self.fail_fast:
                    break

        end = now_utc()
        succeeded = sum(1 for r in results if r.status == "success")
        failed = sum(1 for r in results if r.status == "failed")

        return PipelineResult(
            pipeline_id=request.pipeline_id,
            step_results=results,
            total_steps=len(steps_to_run),
            succeeded_steps=succeeded,
            failed_steps=failed,
            execution_time_ms=(end - start).total_seconds() * 1000,
        )

    def _dispatch_step(
        self,
        mode: str,
        topology: Any,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Route step to corresponding kernel substrate by mode.

        each mode
        calls the same substrate its single-mode sibling endpoint calls
        (dt_traverse / dt_gaps / dt_hypotheses / dt_optimization under
        the full system). The stub-era output keys are preserved, now
        carrying real values, so ``downstream_field`` chaining contracts
        hold. Honesty contract: without a usable topology, or with a
        substrate module absent from the deployment, the step degrades
        to its zero shape plus ``source: unavailable`` + ``reason`` and
        still counts as a success step (chaining semantics) —
        substrate *runtime* errors propagate to ``execute()``, which
        marks the step failed (fail_fast contract unchanged). Upstream
        payloads arrive via ``parameters["_upstream"]``; semantic
        consumption beyond substrate signatures is deferred (A-7-era).
        """
        if mode == KERNEL_MODE_TRAVERSE:
            return self._run_traverse(topology, parameters)
        if mode == KERNEL_MODE_DISCOVER:
            return self._run_discover(topology, parameters)
        if mode == KERNEL_MODE_HYPOTHESIZE:
            return self._run_hypothesize(topology, parameters)
        if mode == KERNEL_MODE_OPTIMIZE:
            return self._run_optimize(topology, parameters)
        return {
            "mode": mode,
            "source": STEP_SOURCE_UNAVAILABLE,
            "reason": f"unknown_mode:{mode}",
        }

    # -- per-mode kernel dispatch ----------------------------------

    @staticmethod
    def _topology_usable(topology: Any) -> bool:
        return topology is not None and hasattr(topology, "nodes")

    @staticmethod
    def _unavailable(mode: str, reason: str, zero: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "mode": mode,
            "source": STEP_SOURCE_UNAVAILABLE,
            "reason": reason,
        }
        out.update(zero)
        return out

    @staticmethod
    def _question_dict(q: Any) -> Dict[str, Any]:
        gap = getattr(q, "gap", None)
        gap_type = getattr(gap, "gap_type", None)
        return {
            "gap_type": gap_type.value if hasattr(gap_type, "value") else str(gap_type),
            "location": getattr(gap, "location", None),
            "question_text": getattr(q, "question_text", None),
            "priority": getattr(q, "priority", None),
        }

    def _run_traverse(self, topology: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        zero = {"steps_count": 0, "traversal_time_ms": 0.0}
        if not self._topology_usable(topology):
            return self._unavailable(KERNEL_MODE_TRAVERSE, "topology_unavailable", zero)
        try:
            from arbiter_engine.twin.topology import (
                TraversalDirection,
                TraversalRequest,
                ValueMode,
            )
            from arbiter_engine.twin.traverser import TopologyTraverser
        except ImportError:
            return self._unavailable(KERNEL_MODE_TRAVERSE, "substrate_unavailable", zero)
        start_nodes = [str(n) for n in (params.get("start_nodes") or [])]
        if not start_nodes:
            start_nodes = [str(n) for n in list(topology.nodes.keys())[:1]]
        if not start_nodes:
            return self._unavailable(KERNEL_MODE_TRAVERSE, "empty_topology", zero)
        request = TraversalRequest(
            start_nodes=start_nodes,
            direction=TraversalDirection(str(params.get("direction", "forward"))),
            value_mode=ValueMode(str(params.get("value_mode", "current"))),
            max_hops=int(params.get("max_hops", 4)),
            min_probability=float(params.get("min_probability", 0.05)),
            max_delay_s=float(params.get("max_delay_s", float("inf"))),
            stop_on_gap=bool(params.get("stop_on_gap", True)),
            overrides=dict(params.get("overrides", {})),
            horizon_s=float(params.get("horizon_s", 3600.0)),
        )
        result = TopologyTraverser(topology=topology).traverse(request)
        traversal_id = str(uuid.uuid4())
        try:
            # (A-7): file impact predictions with the PREDICT-vs-
            # MIRROR ledger (gated inside; no-op while OFF).
            from arbiter_engine.residual.predict_vs_mirror import (
                record_traversal_impacts,
            )
            record_traversal_impacts(result.impacts_predicted, traversal_id=traversal_id)
        except ImportError:
            pass
        return {
            "mode": KERNEL_MODE_TRAVERSE,
            "source": STEP_SOURCE_LIVE,
            "traversal_id": traversal_id,
            "steps_count": len(result.steps),
            "total_nodes_visited": result.total_nodes_visited,
            "problems_count": len(result.problems_detected),
            "gaps_count": len(result.gaps_discovered),
            "questions": [self._question_dict(q) for q in result.questions_generated],
            "traversal_time_ms": result.traversal_time_ms,
        }

    def _run_discover(self, topology: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        zero = {"gaps_count": 0, "questions": []}
        if not self._topology_usable(topology):
            return self._unavailable(KERNEL_MODE_DISCOVER, "topology_unavailable", zero)
        try:
            from arbiter_engine.twin.traverser import TopologyTraverser
        except ImportError:
            return self._unavailable(KERNEL_MODE_DISCOVER, "substrate_unavailable", zero)
        traverser = TopologyTraverser(topology=topology)
        start_node = params.get("start_node")
        questions: List[Any] = []
        if start_node:
            questions = list(traverser.discover_gaps(str(start_node)))
        else:
            # whole-topology walk with (gap_type, location) dedup — the same
            # aggregation the /dt-gaps sibling endpoint performs.
            seen = set()
            for node_id in list(topology.nodes.keys()):
                for q in traverser.discover_gaps(node_id):
                    gap = getattr(q, "gap", None)
                    gap_type = getattr(gap, "gap_type", None)
                    key = (
                        gap_type.value if hasattr(gap_type, "value") else str(gap_type),
                        getattr(gap, "location", None),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    questions.append(q)
        serialized = [self._question_dict(q) for q in questions]
        return {
            "mode": KERNEL_MODE_DISCOVER,
            "source": STEP_SOURCE_LIVE,
            "gaps_count": len(serialized),
            "questions": serialized,
        }

    def _run_hypothesize(self, topology: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        zero = {"hypotheses_count": 0, "hypotheses": []}
        if not self._topology_usable(topology):
            return self._unavailable(KERNEL_MODE_HYPOTHESIZE, "topology_unavailable", zero)
        try:
            from arbiter_engine.twin.hypothesis_generator import (
                HypothesisGenerator,
            )
        except ImportError:
            return self._unavailable(KERNEL_MODE_HYPOTHESIZE, "substrate_unavailable", zero)
        kwargs: Dict[str, Any] = {"tenant_id": self.tenant_id}
        if "min_confidence" in params:
            kwargs["min_confidence"] = float(params["min_confidence"])
        if "max_hypotheses" in params:
            kwargs["max_per_generation"] = int(params["max_hypotheses"])
        generator = HypothesisGenerator(**kwargs)
        hypotheses = generator.generate(
            topology,
            mode=KERNEL_MODE_HYPOTHESIZE,
            evidence_traversal_id=params.get("evidence_traversal_id"),
            hypothesis_types=params.get("hypothesis_types"),
            nl_text=params.get("nl_text"),
        )
        serialized = [
            {
                "hypothesis_id": h.hypothesis_id,
                "hypothesis_type": h.hypothesis_type,
                "confidence": h.confidence,
                "precondition_pattern": h.precondition_pattern,
                "effect_pattern": h.effect_pattern,
            }
            for h in hypotheses
        ]
        return {
            "mode": KERNEL_MODE_HYPOTHESIZE,
            "source": STEP_SOURCE_LIVE,
            "hypotheses_count": len(serialized),
            "hypotheses": serialized,
        }

    def _run_optimize(self, topology: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        zero = {"pareto_front_size": 0, "pareto_front": []}
        if not self._topology_usable(topology):
            return self._unavailable(KERNEL_MODE_OPTIMIZE, "topology_unavailable", zero)
        try:
            from arbiter_engine.twin.topology_optimizer import (
                ConstraintExpr,
                OptimizationRequest,
                TopologyOptimizer,
            )
        except ImportError:
            return self._unavailable(KERNEL_MODE_OPTIMIZE, "substrate_unavailable", zero)
        constraints = []
        for c in params.get("constraints") or []:
            try:
                constraints.append(ConstraintExpr(
                    expression=c["expression"],
                    operator=c["operator"],
                    bound=float(c["bound"]),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        start_nodes = [str(n) for n in (params.get("start_nodes") or [])]
        if not start_nodes:
            start_nodes = [str(n) for n in list(topology.nodes.keys())[:1]]
        if not start_nodes:
            return self._unavailable(KERNEL_MODE_OPTIMIZE, "empty_topology", zero)
        optimizer_kwargs: Dict[str, Any] = {"tenant_id": self.tenant_id}
        if "max_evaluations" in params:
            optimizer_kwargs["max_evaluations"] = int(params["max_evaluations"])
        optimizer = TopologyOptimizer(**optimizer_kwargs)
        request = OptimizationRequest(
            request_id=str(uuid.uuid4()),
            objective_function=str(
                params.get("objective_function") or "entity.properties.cost"
            ),
            constraints=constraints,
            start_nodes=start_nodes,
            max_evaluations=optimizer.max_evaluations,
            tenant_id=self.tenant_id,
            nl_text=params.get("nl_text"),
        )
        points = optimizer.optimize(topology, request)
        front = [
            {
                "plan_id": p.plan_id,
                "action_plan": p.action_plan,
                "objective_value": p.objective_value,
                "constraint_satisfaction": p.constraint_satisfaction,
            }
            for p in points
        ]
        return {
            "mode": KERNEL_MODE_OPTIMIZE,
            "source": STEP_SOURCE_LIVE,
            "pareto_front_size": len(front),
            "pareto_front": front,
        }

    def emit(self, request: PipelineRequest, result: PipelineResult) -> int:
        """The established pattern callsite-wire to production substrate."""
        try:
            from arbiter_engine.twin.pipeline_production import (
                record_production_pipeline,
            )
        except ImportError:
            return 0
        try:
            record_production_pipeline(
                pipeline_id=request.pipeline_id,
                total_steps=result.total_steps,
                succeeded_steps=result.succeeded_steps,
                failed_steps=result.failed_steps,
                tenant_id=request.tenant_id,
                observed_at=now_utc(),
            )
        except (TypeError, ValueError):
            return 0
        return result.total_steps


# ---------------------------------------------------------------------------
# NLPipelineTranslator — the established pattern LOAD-BEARING promotion
# per the follow-up. Mirrors NLHypothesisTranslator
# discipline applied to pipeline-mode NL parsing.
# ---------------------------------------------------------------------------


from dataclasses import field as _field
from typing import Tuple as _Tuple


@dataclass
class NLPipelineTranslationResult:
    """Discriminated 3-tier outcome of NL → PipelineRequest."""

    tier: int
    nl_text: str
    tier1_pipeline: Optional[PipelineRequest] = None
    tier2_candidates: List[PipelineRequest] = _field(default_factory=list)
    tier3_pending_confirmation: Optional[PipelineRequest] = None
    tier3_reason: Optional[str] = None


class NLPipelineTranslator:
    """3-tier NL → PipelineRequest translator LOAD-BEARING reference-architecture-of-reference-architectures-of-
    reference-architectures promotion (6 prior + this 7th).

    Mirrors NLHypothesisTranslator discipline applied to multi-
    mode pipeline composition. Per Lever 4.
    """

    _MODE_KEYWORDS: Dict[str, List[str]] = {
        KERNEL_MODE_TRAVERSE: ["traverse", "walk", "explore"],
        KERNEL_MODE_DISCOVER: ["discover", "find", "gaps", "unknown"],
        KERNEL_MODE_HYPOTHESIZE: ["hypothesize", "hypothesis", "cause", "propose"],
        KERNEL_MODE_OPTIMIZE: ["optimize", "minimize", "maximize", "best"],
    }

    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = str(tenant_id)

    def translate_with_3_tier_escalation(
        self,
        nl_text: str,
        severity_floor: str = "MEDIUM",
        cross_tenant_start_nodes: Optional[List[str]] = None,
    ) -> NLPipelineTranslationResult:
        """NL → PipelineRequest with 3-tier escalation.

        Tier 1: auto-translate via keyword-dispatch for unambiguous mode-sequence.
        Tier 2: LLM-fallback when ambiguous (no modes OR > 4 modes detected).
        Tier 3: operator-confirmation on cross-tenant OR HIGH+ severity.
        """
        nl_lower = nl_text.lower()
        detected_modes: List[str] = []
        for mode, kws in self._MODE_KEYWORDS.items():
            if any(kw in nl_lower for kw in kws):
                detected_modes.append(mode)

        if len(detected_modes) == 0:
            return NLPipelineTranslationResult(
                tier=3,
                nl_text=nl_text,
                tier3_reason="no_modes_detected",
            )

        steps = [
            PipelineStep(
                step_id=str(uuid.uuid4()),
                mode=m,
                parameters={},
            )
            for m in detected_modes
        ]
        pipeline_request = PipelineRequest(
            pipeline_id=str(uuid.uuid4()),
            pipeline=steps,
            tenant_id=self.tenant_id,
            nl_text=nl_text,
        )

        # Tier 3 escalation checks
        if cross_tenant_start_nodes and len(set(cross_tenant_start_nodes)) > 1:
            return NLPipelineTranslationResult(
                tier=3,
                nl_text=nl_text,
                tier3_pending_confirmation=pipeline_request,
                tier3_reason="cross_tenant",
            )
        if severity_floor.upper() in ("HIGH", "CRITICAL"):
            return NLPipelineTranslationResult(
                tier=3,
                nl_text=nl_text,
                tier3_pending_confirmation=pipeline_request,
                tier3_reason="high_severity",
            )

        # Tier 2 if modes ambiguous (> 4 detected = ambiguous superset)
        if len(detected_modes) > len(KNOWN_KERNEL_MODES):
            return NLPipelineTranslationResult(
                tier=2,
                nl_text=nl_text,
                tier2_candidates=[pipeline_request],
                tier3_reason="ambiguous_modes",
            )

        return NLPipelineTranslationResult(
            tier=1,
            nl_text=nl_text,
            tier1_pipeline=pipeline_request,
        )


# Anthropic + OpenAI tool-use schema
PIPELINE_COMPOSE_TOOL_DEF: Dict[str, Any] = {
    "name": "pipeline_compose",
    "description": (
        'Submit multi-mode kernel pipeline via NL → typed PipelineRequest. an established pattern promotion.  Lever 4. 4 canonical modes: TRAVERSE + DISCOVER + HYPOTHESIZE + OPTIMIZE.'
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
