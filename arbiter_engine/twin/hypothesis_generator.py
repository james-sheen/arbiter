""" HypothesisGenerator core —.

5th DT-mode HYPOTHESIZE substrate. Walks DigitalTwinTopology + emits
TopologyHypothesis instances per structural pattern across 4 canonical
hypothesis types (conservation / feedback_loop / property_bound / monotonicity).

Per /round-eval Part 4.C criterion #7 + Lever 2,
this is the kernel-amplification axis sibling to (4th DT-mode DISCOVER
externalization). Schema decided at Flavor D hybrid frozen-typed +
NL-overlay.

the established pattern design-center (traversal-kernel-as-atom codification) cited as
the canonical kernel-amplification methodology.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


# ---------------------------------------------------------------------------
# Module-level canonical constants (Flavor D schema)
# ---------------------------------------------------------------------------

HYPOTHESIS_TYPES: tuple = (
    "conservation",
    "feedback_loop",
    "property_bound",
    "monotonicity",
)

HYPOTHESIS_MIN_CONFIDENCE: float = 0.3
HYPOTHESIS_MAX_PER_GENERATION: int = 64


# ---------------------------------------------------------------------------
# Frozen-typed hypothesis schema Decision (9 fields)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TopologyHypothesis:
    """Frozen-typed hypothesis. Hash-stable identity via hypothesis_id.

    Per audit-pin: this is hash-stable BY CONSTRUCTION. Mutation flows
    (drift_marker_count, confirmation_count) belong in companion sidecar
    records (ProductionHypothesis ring), not in identity.

    nl_text is audit-only (not load-bearing). Per 7-trigger off-ramps:
    if NLHypothesisTranslator drift exceeds 10%, audit-pin re-opens.
    """

    hypothesis_id: str
    hypothesis_type: str
    precondition_pattern: Dict[str, Any]
    effect_pattern: Dict[str, Any]
    confidence: float
    evidence_traversal_id: Optional[str]
    tenant_id: str
    observed_at: datetime
    nl_text: Optional[str] = None


# ---------------------------------------------------------------------------
# HypothesisGenerator core
# ---------------------------------------------------------------------------

class HypothesisGenerator:
    """Walks a DigitalTwinTopology + emits hypotheses per structural pattern.

    Composes with TopologyTraverser kernel via evidence_traversal_id
    backlink. Per CLAUDE.md domain-agnostic foundation: pattern types are
    kernel-substrate; per-domain content comes from EdgeDirection +
    FlowType + AxiomState that the underlying topology carries.
    """

    def __init__(
        self,
        min_confidence: float = HYPOTHESIS_MIN_CONFIDENCE,
        max_per_generation: int = HYPOTHESIS_MAX_PER_GENERATION,
        tenant_id: str = "default",
    ) -> None:
        if min_confidence < 0.0 or min_confidence > 1.0:
            raise ValueError("min_confidence must be in [0.0, 1.0]")
        if max_per_generation < 1:
            raise ValueError("max_per_generation must be >= 1")
        self.min_confidence = float(min_confidence)
        self.max_per_generation = int(max_per_generation)
        self.tenant_id = str(tenant_id)

    def generate(
        self,
        topology: Any,
        mode: str = "HYPOTHESIZE",
        evidence_traversal_id: Optional[str] = None,
        hypothesis_types: Optional[List[str]] = None,
        nl_text: Optional[str] = None,
    ) -> List[TopologyHypothesis]:
        """Walk topology + emit hypotheses across selected types.

        Returns up to max_per_generation hypotheses with confidence >=
        min_confidence. Empty list if topology has no qualifying patterns.
        """
        types = list(hypothesis_types or HYPOTHESIS_TYPES)
        out: List[TopologyHypothesis] = []
        for htype in types:
            if htype not in HYPOTHESIS_TYPES:
                continue
            emitter = getattr(self, f"_emit_{htype}", None)
            if emitter is None:
                continue
            for h in emitter(topology, evidence_traversal_id, nl_text):
                if h.confidence < self.min_confidence:
                    continue
                out.append(h)
                if len(out) >= self.max_per_generation:
                    return out
        return out

    # ----- pattern-type emitters (kernel-substrate; domain-opaque) -----

    def _emit_conservation(
        self,
        topology: Any,
        evidence_traversal_id: Optional[str],
        nl_text: Optional[str],
    ) -> List[TopologyHypothesis]:
        """FLOW cycle → conservation hypothesis (sum_in approx sum_out + bounded leak)."""
        out: List[TopologyHypothesis] = []
        nodes = getattr(topology, "nodes", {})
        for node_id in list(nodes.keys()):
            try:
                cycles = topology.get_flow_cycles(node_id)
            except (AttributeError, TypeError):
                continue
            for cycle in cycles:
                if len(cycle) < 2:
                    continue
                first = cycle[0]
                last = cycle[-1]
                source_id = getattr(first, "source_id", None)
                target_id = getattr(last, "target_id", None)
                if not source_id or not target_id:
                    continue
                flow_type = getattr(first, "flow_type", None)
                ft_value = getattr(flow_type, "value", str(flow_type) if flow_type else "unknown")
                confidence = min(0.9, 0.4 + 0.1 * len(cycle))
                out.append(
                    TopologyHypothesis(
                        hypothesis_id=str(uuid.uuid4()),
                        hypothesis_type="conservation",
                        precondition_pattern={
                            "cycle_source": source_id,
                            "flow_type": ft_value,
                            "cycle_len": len(cycle),
                        },
                        effect_pattern={
                            "sum_inflow_approx_sum_outflow": True,
                            "bounded_leak": True,
                            "cycle_target": target_id,
                        },
                        confidence=confidence,
                        evidence_traversal_id=evidence_traversal_id,
                        tenant_id=self.tenant_id,
                        observed_at=datetime.now(timezone.utc),
                        nl_text=nl_text,
                    )
                )
        return out

    def _emit_feedback_loop(
        self,
        topology: Any,
        evidence_traversal_id: Optional[str],
        nl_text: Optional[str],
    ) -> List[TopologyHypothesis]:
        """CAUSAL cycle → feedback-loop hypothesis (X → Y → X with lag)."""
        out: List[TopologyHypothesis] = []
        nodes = getattr(topology, "nodes", {})
        edges_map = getattr(topology, "edges", {})
        for node_id in list(nodes.keys()):
            outgoing = edges_map.get(node_id, [])
            for first_edge in outgoing:
                if getattr(getattr(first_edge, "direction", None), "value", None) != "causal":
                    continue
                mid_id = getattr(first_edge, "target_id", None)
                if not mid_id or mid_id == node_id:
                    continue
                second_outgoing = edges_map.get(mid_id, [])
                for second_edge in second_outgoing:
                    if getattr(getattr(second_edge, "direction", None), "value", None) != "causal":
                        continue
                    if getattr(second_edge, "target_id", None) != node_id:
                        continue
                    confidence = 0.6
                    out.append(
                        TopologyHypothesis(
                            hypothesis_id=str(uuid.uuid4()),
                            hypothesis_type="feedback_loop",
                            precondition_pattern={
                                "source": node_id,
                                "mid": mid_id,
                                "direction": "causal",
                            },
                            effect_pattern={
                                "loop_back_to_source": True,
                                "lag_present": True,
                            },
                            confidence=confidence,
                            evidence_traversal_id=evidence_traversal_id,
                            tenant_id=self.tenant_id,
                            observed_at=datetime.now(timezone.utc),
                            nl_text=nl_text,
                        )
                    )
        return out

    def _emit_property_bound(
        self,
        topology: Any,
        evidence_traversal_id: Optional[str],
        nl_text: Optional[str],
    ) -> List[TopologyHypothesis]:
        """STRUCTURAL containment → property-bound hypothesis (child <= parent)."""
        out: List[TopologyHypothesis] = []
        edges_map = getattr(topology, "edges", {})
        for source_id, edges in edges_map.items():
            for edge in edges:
                if getattr(getattr(edge, "direction", None), "value", None) != "structural":
                    continue
                target_id = getattr(edge, "target_id", None)
                if not target_id:
                    continue
                confidence = 0.5
                out.append(
                    TopologyHypothesis(
                        hypothesis_id=str(uuid.uuid4()),
                        hypothesis_type="property_bound",
                        precondition_pattern={
                            "parent": source_id,
                            "child": target_id,
                            "direction": "structural",
                        },
                        effect_pattern={
                            "child_property_bounded_by_parent": True,
                        },
                        confidence=confidence,
                        evidence_traversal_id=evidence_traversal_id,
                        tenant_id=self.tenant_id,
                        observed_at=datetime.now(timezone.utc),
                        nl_text=nl_text,
                    )
                )
        return out

    def _emit_monotonicity(
        self,
        topology: Any,
        evidence_traversal_id: Optional[str],
        nl_text: Optional[str],
    ) -> List[TopologyHypothesis]:
        """TEMPORAL → monotonicity hypothesis (non-decreasing over window)."""
        out: List[TopologyHypothesis] = []
        edges_map = getattr(topology, "edges", {})
        for source_id, edges in edges_map.items():
            for edge in edges:
                if getattr(getattr(edge, "direction", None), "value", None) != "temporal":
                    continue
                target_id = getattr(edge, "target_id", None)
                if not target_id:
                    continue
                confidence = 0.45
                out.append(
                    TopologyHypothesis(
                        hypothesis_id=str(uuid.uuid4()),
                        hypothesis_type="monotonicity",
                        precondition_pattern={
                            "source": source_id,
                            "target": target_id,
                            "direction": "temporal",
                        },
                        effect_pattern={
                            "non_decreasing_over_window": True,
                            "window_seconds": 300,
                        },
                        confidence=confidence,
                        evidence_traversal_id=evidence_traversal_id,
                        tenant_id=self.tenant_id,
                        observed_at=datetime.now(timezone.utc),
                        nl_text=nl_text,
                    )
                )
        return out

    # ----- emit() — the established pattern callsite-wire to production substrate -----

    def emit(self, hypothesis: TopologyHypothesis) -> TopologyHypothesis:
        """Record the hypothesis to the established pattern production substrate.

        Defensive import — production module may not be present (the established pattern
        bootstrap-aware contract). Returns the hypothesis unchanged so callers
        can chain.
        """
        try:
            from arbiter_engine.twin.hypothesis_production import (
                record_production_hypothesis,
            )
        except ImportError:
            return hypothesis
        try:
            record_production_hypothesis(
                hypothesis_id=hypothesis.hypothesis_id,
                hypothesis_type=hypothesis.hypothesis_type,
                confidence=hypothesis.confidence,
                evidence_traversal_id=hypothesis.evidence_traversal_id,
                tenant_id=hypothesis.tenant_id,
                observed_at=hypothesis.observed_at,
            )
        except (TypeError, ValueError):
            # production substrate signature may diverge during landing —
            # don't crash; owns reconciliation
            pass
        return hypothesis


# ---------------------------------------------------------------------------
# (Round-57 P3): NLHypothesisTranslator — the established pattern
# LOAD-BEARING reference-architecture-of-reference-architectures implementation
# Decision Flavor D hybrid POST /hypothesize/test + auto-traversal.
#
# Mirrors NLTraversalTranslator3Tier discipline applied to
# hypothesis-verdict surface. 3-tier escalation:
# Tier 1 — auto-translate NL → typed VerdictRequest (no operator action)
# Tier 2 — LLM-ambiguity-resolution candidate-presentation (2-3 picks)
# Tier 3 — operator-confirmation (cross-tenant OR HIGH+/CRITICAL severity)
#
# Per Lever 4 + the established pattern promotion.
# ---------------------------------------------------------------------------


VERDICT_CONFIRM: str = "confirm"
VERDICT_REFUTE: str = "refute"
VERDICT_ABSTAIN: str = "abstain"
KNOWN_VERDICTS: tuple = (VERDICT_CONFIRM, VERDICT_REFUTE, VERDICT_ABSTAIN)


@dataclass(frozen=True)
class VerdictRequest:
    """Frozen-typed verdict body Decision concrete shape.

    Hash-stable identity for downstream posterior-update pipelines per established pattern LOAD-BEARING promotion.
    """

    hypothesis_id: str
    verdict: str
    verdict_confidence: float
    evidence_traversal: Optional[Dict[str, Any]] = None
    evidence_ref: Optional[str] = None
    tenant_id: str = "default"


@dataclass
class NLHypothesisTranslationResult:
    """discriminated 3-tier outcome of NL → VerdictRequest.

    Exactly one of (tier1_verdict, tier2_candidates,
    tier3_pending_confirmation) is non-None. Per Decision Tier-3
    fires when cross-tenant boundary detected OR HIGH+/CRITICAL severity-floor.
    """

    tier: int
    nl_text: str
    tier1_verdict: Optional[VerdictRequest] = None
    tier2_candidates: List[VerdictRequest] = field(default_factory=list)
    tier3_pending_confirmation: Optional[VerdictRequest] = None
    tier3_reason: Optional[str] = None  # "cross_tenant" / "high_severity" / "ambiguous_verdict"


def classify_escalation_tier_per_cd1291(
    verdict_request: VerdictRequest,
    severity_floor: str = "MEDIUM",
    cross_tenant_start_nodes: Optional[List[str]] = None,
) -> tuple:
    """classify which tier a candidate VerdictRequest triggers.

    Mirrors classify_escalation_tier_per_cd1280 discipline.
    Returns (tier, reason).
    """
    if cross_tenant_start_nodes and len(set(cross_tenant_start_nodes)) > 1:
        return (3, "cross_tenant")
    if severity_floor.upper() in ("HIGH", "CRITICAL"):
        return (3, "high_severity")
    if verdict_request.verdict not in KNOWN_VERDICTS:
        return (3, "ambiguous_verdict")
    return (1, None)


class NLHypothesisTranslator:
    """ (Round-57 P3): 3-tier escalation NL → VerdictRequest translator.

    the established pattern LOAD-BEARING reference-architecture-of-reference-
    architectures implementation Decision Flavor D (rule/template
    + LLM-fallback + human escape-hatch family — HTN/STRIPS/LLM +
     LLMClient fallback + NarrationInterface audit gate +
     LLMCounterfactual + NLTraversalTranslator + this 6th).

    Per Lever 4 applied to hypothesis-testing
    pipeline (sibling to NLTraversalTranslator + hypothesis
    schema NL-overlay).

    Domain-agnostic by construction: NL phrases map to verdict + hypothesis_id
    + optional evidence_traversal; no per-domain dispatch.
    """

    # Rule-based verdict-keyword dispatch (Tier 1 auto-translate)
    _VERDICT_KEYWORDS: Dict[str, List[str]] = {
        VERDICT_CONFIRM: ["confirm", "agree", "validate", "verify"],
        VERDICT_REFUTE: ["refute", "reject", "disagree", "falsify"],
        VERDICT_ABSTAIN: ["abstain", "unclear", "insufficient", "skip"],
    }

    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = str(tenant_id)

    def translate_with_3_tier_escalation(
        self,
        nl_text: str,
        hypothesis_id: str,
        severity_floor: str = "MEDIUM",
        cross_tenant_start_nodes: Optional[List[str]] = None,
        evidence_traversal: Optional[Dict[str, Any]] = None,
    ) -> NLHypothesisTranslationResult:
        """Translate NL → VerdictRequest with 3-tier escalation.

        Tier 1: auto-translate via keyword dispatch (single unambiguous verdict).
        Tier 2: LLM-fallback when keywords ambiguous (>1 match).
        Tier 3: operator-confirmation on cross-tenant + HIGH+/CRITICAL severity.
        """
        nl_lower = nl_text.lower()
        matched = [
            v for v, kws in self._VERDICT_KEYWORDS.items()
            if any(kw in nl_lower for kw in kws)
        ]

        if len(matched) == 1:
            verdict_request = VerdictRequest(
                hypothesis_id=hypothesis_id,
                verdict=matched[0],
                verdict_confidence=0.85,
                evidence_traversal=evidence_traversal,
                tenant_id=self.tenant_id,
            )
        elif len(matched) >= 2:
            return NLHypothesisTranslationResult(
                tier=2,
                nl_text=nl_text,
                tier2_candidates=[
                    VerdictRequest(
                        hypothesis_id=hypothesis_id,
                        verdict=v,
                        verdict_confidence=0.6,
                        evidence_traversal=evidence_traversal,
                        tenant_id=self.tenant_id,
                    )
                    for v in matched
                ],
                tier3_reason="ambiguous_verdict",
            )
        else:
            return NLHypothesisTranslationResult(
                tier=3,
                nl_text=nl_text,
                tier3_pending_confirmation=VerdictRequest(
                    hypothesis_id=hypothesis_id,
                    verdict=VERDICT_ABSTAIN,
                    verdict_confidence=0.0,
                    evidence_traversal=evidence_traversal,
                    tenant_id=self.tenant_id,
                ),
                tier3_reason="no_verdict_detected",
            )

        tier, reason = classify_escalation_tier_per_cd1291(
            verdict_request, severity_floor, cross_tenant_start_nodes
        )

        if tier == 3:
            return NLHypothesisTranslationResult(
                tier=3,
                nl_text=nl_text,
                tier3_pending_confirmation=verdict_request,
                tier3_reason=reason,
            )

        return NLHypothesisTranslationResult(
            tier=1,
            nl_text=nl_text,
            tier1_verdict=verdict_request,
        )


# Anthropic + OpenAI tool-use schema mirroring Decision concrete shape
HYPOTHESIZE_TEST_TOOL_DEF: Dict[str, Any] = {
    "name": "hypothesize_test",
    "description": (
        "Submit partner verdict on a generated TopologyHypothesis per "
        "Flavor D hybrid typed POST + auto-traversal evidence. Returns posterior "
        "confidence delta. an established pattern."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "hypothesis_id": {"type": "string"},
            "verdict": {
                "type": "string",
                "enum": list(KNOWN_VERDICTS),
            },
            "verdict_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "evidence_traversal": {
                "type": ["object", "null"],
                "description": "Optional TraversalRequest for evidence; auto-supplied if absent.",
            },
            "evidence_ref": {"type": ["string", "null"]},
            "tenant_id": {"type": ["string", "null"]},
        },
        "required": ["hypothesis_id", "verdict"],
    },
}
