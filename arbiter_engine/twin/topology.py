"""
Topology-Based Digital Twin Data Model.

Core data structures for the unified topology: TwinNode (entity + axiom
states + predictions), TwinEdge (relationship + dynamics + physics),
TopologyGap (missing knowledge), DigitalTwinTopology (container).

All problem solving reduces to graph traversal on this topology.
"""

import math
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from ..interfaces import Entity, Problem
from ..types import Axiom, Severity
from ..temporal.temporal_edge import ResponseModel
from ..temporal.trend_projection import TrendResult
from ..propagation.impact_estimator import DownstreamImpact

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EdgeDirection(str, Enum):
    """Semantic direction of a relationship edge."""
    CAUSAL = "causal"
    FLOW = "flow"
    STRUCTURAL = "structural"
    TEMPORAL = "temporal"


class FlowType(str, Enum):
    """Type of conserved quantity flowing through FLOW edges."""
    ENERGY = "energy"
    MASS = "mass"
    INFORMATION = "information"
    FINANCIAL = "financial"
    CUSTOM = "custom"


class EdgeSource(str, Enum):
    """How this edge was discovered."""
    YAML = "yaml"
    AUTO_DISCOVERY = "auto"
    LLM_INFERRED = "llm"
    HUMAN_PROVIDED = "human"
    CROSS_DOMAIN = "transfer"


class GapType(str, Enum):
    """What is missing in the topology."""
    MISSING_NODE = "missing_node"
    MISSING_EDGE = "missing_edge"
    MISSING_PROPERTY = "missing_property"
    MISSING_THRESHOLD = "missing_threshold"
    MISSING_DYNAMICS = "missing_dynamics"


class ResolutionStrategy(str, Enum):
    """How to resolve a gap."""
    AUTO_DISCOVER = "auto_discover"
    LLM_INFER = "llm_infer"
    HUMAN_PROVIDE = "human_provide"
    CROSS_DOMAIN = "cross_domain"


class TraversalDirection(str, Enum):
    """Direction of graph traversal."""
    FORWARD = "forward"
    REVERSE = "reverse"
    BIDIRECTIONAL = "bidirectional"


class ValueMode(str, Enum):
    """Which property values to use during traversal."""
    CURRENT = "current"
    PROJECTED = "projected"
    HYPOTHETICAL = "hypothetical"


# ---------------------------------------------------------------------------
# Node-related dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AxiomState:
    """Per-axiom evaluation result stored on a node."""
    axiom: Axiom
    verdict: Severity = Severity.INFO  # INFO = not yet evaluated
    checked_at: datetime = field(default_factory=datetime.utcnow)
    evidence: Dict[str, Any] = field(default_factory=dict)
    indicator_name: str = ""


@dataclass
class ProjectedValue:
    """A property value projected into the future."""
    value: float
    confidence: float
    horizon_s: float
    model: str = ""


@dataclass
class NodeConfidence:
    """Confidence scores for different aspects of a node."""
    entity_type: float = 1.0
    properties: Dict[str, float] = field(default_factory=dict)
    relationships: float = 1.0
    overall: float = 1.0


# ---------------------------------------------------------------------------
# TopologyGap
# ---------------------------------------------------------------------------

@dataclass
class TopologyGap:
    """A missing piece of knowledge in the topology.

    Uses an open-world assumption: what's not in the graph is UNKNOWN
    (a Gap), not FALSE.
    """
    gap_type: GapType
    location: str
    description: str
    discovered_during: str = ""
    discovered_at: datetime = field(default_factory=datetime.utcnow)
    suggested_strategy: ResolutionStrategy = ResolutionStrategy.AUTO_DISCOVER
    resolution_attempts: List[Dict[str, Any]] = field(default_factory=list)
    resolved: bool = False
    resolution_value: Optional[Any] = None
    resolution_confidence: float = 0.0

    @property
    def question(self) -> str:
        """Generate the natural-language question this gap implies."""
        templates = {
            GapType.MISSING_NODE: "What entity is at the other end of '{location}'?",
            GapType.MISSING_EDGE: "What does entity '{location}' connect to?",
            GapType.MISSING_PROPERTY: "What is the value of '{location}'?",
            GapType.MISSING_THRESHOLD: "What is the normal range for '{location}'?",
            GapType.MISSING_DYNAMICS: "How fast does a change propagate through '{location}'?",
        }
        return templates.get(self.gap_type, self.description).format(
            location=self.location
        )


# ---------------------------------------------------------------------------
# TwinNode
# ---------------------------------------------------------------------------

@dataclass
class TwinNode:
    """A node in the Digital Twin topology.

    Wraps Entity by reference (not copy). The Entity continues to be
    updated by collectors; TwinNode adds prediction and axiom state
    as a parallel layer.
    """
    entity: Entity
    axiom_states: Dict[str, AxiomState] = field(default_factory=dict)
    trend: Optional[TrendResult] = None
    # `degradation: Optional[DegradationCurve]` removed. It was a
    # field with zero writers and zero readers: no production site passed
    # it (both `TwinNode(...)` constructions are in `builder.py` and
    # neither does), nothing read `node.degradation`, and `TwinNode` is not
    # serialised anywhere. Its only effect was to import
    # `entity_tracker.degradation` into the kernel's closure for a type
    # annotation — which asserted would drop when the traverser's
    # unread `degradation_fitter` parameter went, and measurement showed it
    # did not, because THIS was the carrier.
    #
    # Third instance of the shape (`axiom_checkers`) and
    # (`degradation_fitter`), and the first that is a field rather
    # than a parameter. `DegradationCurve` itself is live and unaffected —
    # wired it into the full system, which is where
    # degradation belongs.
    projected_values: Dict[str, ProjectedValue] = field(default_factory=dict)
    confidence: NodeConfidence = field(default_factory=NodeConfidence)
    gaps: List[TopologyGap] = field(default_factory=list)


# ---------------------------------------------------------------------------
# TwinEdge
# ---------------------------------------------------------------------------

@dataclass
class TwinEdge:
    """A relationship edge in the Digital Twin topology.

    Unifies RelationshipGraph tuple, TemporalEdge fields, LearnedWeight,
    and physics constraints into a single structure.
    """
    source_id: str
    target_id: str
    relation_type: str
    direction: EdgeDirection = EdgeDirection.STRUCTURAL

    # Propagation dynamics (absorbs TemporalEdge)
    propagation_probability: float = 0.3
    propagation_delay_s: float = 60.0
    time_constant_s: float = 60.0
    response_model: ResponseModel = ResponseModel.EXPONENTIAL
    coupling_strength: float = 1.0

    # Physics constraints
    flow_type: Optional[FlowType] = None
    conservation: bool = False
    conservation_tolerance: float = 0.05

    # Learning (absorbs LearnedWeight)
    learned_weight: float = 1.0
    observation_count: int = 0

    # Metadata
    confidence: float = 1.0
    source: EdgeSource = EdgeSource.YAML
    gaps: List[TopologyGap] = field(default_factory=list)

    def response_fraction(self, elapsed_s: float) -> float:
        """Fraction of final impact realized at time t."""
        if elapsed_s < self.propagation_delay_s:
            return 0.0
        t = elapsed_s - self.propagation_delay_s
        tau = max(self.time_constant_s, 0.001)
        if self.response_model == ResponseModel.EXPONENTIAL:
            return 1.0 - math.exp(-t / tau)
        elif self.response_model == ResponseModel.LINEAR:
            return min(t / tau, 1.0)
        elif self.response_model == ResponseModel.STEP:
            return 1.0
        elif self.response_model == ResponseModel.LOGARITHMIC:
            return min(math.log(1 + t / tau) / math.log(2), 1.0)
        return 1.0

    def effective_impact(self, elapsed_s: float) -> float:
        """Combined impact = coupling_strength x response_fraction(t)."""
        return self.coupling_strength * self.response_fraction(elapsed_s)


# ---------------------------------------------------------------------------
# Traversal dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TraversalRequest:
    """Configuration for a topology traversal."""
    start_nodes: List[str]
    direction: TraversalDirection
    value_mode: ValueMode = ValueMode.CURRENT
    max_hops: int = 4
    min_probability: float = 0.05
    max_delay_s: float = float('inf')
    stop_on_gap: bool = True
    collect_axiom_violations: bool = True
    collect_gaps: bool = True
    edge_filter: Optional[Set[EdgeDirection]] = None
    flow_filter: Optional[Set[FlowType]] = None
    overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    horizon_s: float = 3600.0


@dataclass
class TraversalStep:
    """One node visit during traversal."""
    node_id: str
    hop: int
    cumulative_probability: float
    cumulative_delay_s: float
    path: List[str]
    axiom_violations: List[Problem] = field(default_factory=list)
    gaps_encountered: List[TopologyGap] = field(default_factory=list)


@dataclass
class TopologyQuestion:
    """A question generated from a blocked traversal."""
    gap: TopologyGap
    question_text: str
    priority: float
    context_path: List[str]
    suggested_resolvers: List[ResolutionStrategy] = field(default_factory=list)


@dataclass
class TraversalResult:
    """Output of a topology traversal."""
    steps: List[TraversalStep] = field(default_factory=list)
    total_nodes_visited: int = 0
    problems_detected: List[Problem] = field(default_factory=list)
    impacts_predicted: List[DownstreamImpact] = field(default_factory=list)
    gaps_discovered: List[TopologyGap] = field(default_factory=list)
    questions_generated: List[TopologyQuestion] = field(default_factory=list)
    conservation_violations: List[Problem] = field(default_factory=list)
    traversal_time_ms: float = 0.0
    #:. Axiom evaluations this traversal ATTEMPTED, counted where they
    #: happen. The envelope's denominator was previously derived in `api.py` by
    #: counting `axiom_states` on each walked node, which counts what the
    #: builder SEEDED rather than what ran: a node carries one state per
    #: declared axiom, `_evaluate_axioms` handles BOUNDEDNESS only, and it
    #: skips any state whose property is absent from the values. With
    #: `collect_axiom_violations=False` — no evaluation at all — that
    #: derivation still returned the full seeded count. Counting in the caller
    #: was a second implementation of a predicate only the traverser knows.
    axiom_evaluations_attempted: int = 0


# ---------------------------------------------------------------------------
# DigitalTwinTopology container
# ---------------------------------------------------------------------------

@dataclass
class DigitalTwinTopology:
    """The complete Digital Twin topology.

    Replaces RelationshipGraph as the central data structure.
    Holds all nodes, edges, and gaps with O(1) node lookup and
    O(degree) edge lookup.
    """
    domain_id: str = ""
    version: int = 0

    # Core storage
    nodes: Dict[str, TwinNode] = field(default_factory=dict)
    edges: Dict[str, List[TwinEdge]] = field(default_factory=dict)
    reverse_edges: Dict[str, List[TwinEdge]] = field(default_factory=dict)

    # Gap tracking
    gaps: List[TopologyGap] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_traversal_at: Optional[datetime] = None
    fidelity: float = 0.0

    def add_node(self, node: TwinNode) -> None:
        self.nodes[node.entity.id] = node

    def add_edge(self, edge: TwinEdge) -> None:
        self.edges.setdefault(edge.source_id, []).append(edge)
        self.reverse_edges.setdefault(edge.target_id, []).append(edge)

    def get_node(self, entity_id: str) -> Optional[TwinNode]:
        return self.nodes.get(entity_id)

    def get_outgoing(
        self,
        entity_id: str,
        direction: Optional[EdgeDirection] = None,
        flow_type: Optional[FlowType] = None,
    ) -> List[TwinEdge]:
        result = self.edges.get(entity_id, [])
        if direction:
            result = [e for e in result if e.direction == direction]
        if flow_type:
            result = [e for e in result if e.flow_type == flow_type]
        return result

    def get_incoming(
        self,
        entity_id: str,
        direction: Optional[EdgeDirection] = None,
    ) -> List[TwinEdge]:
        result = self.reverse_edges.get(entity_id, [])
        if direction:
            result = [e for e in result if e.direction == direction]
        return result

    def get_flow_cycles(self, start_id: str) -> List[List[TwinEdge]]:
        """Find cycles on FLOW edges starting from start_id (DFS)."""
        cycles: List[List[TwinEdge]] = []
        flow_edges = self.get_outgoing(start_id, direction=EdgeDirection.FLOW)
        for edge in flow_edges:
            self._dfs_cycle(
                edge.target_id, start_id, [edge], set(), cycles, max_depth=6
            )
        return cycles

    def _dfs_cycle(
        self,
        current_id: str,
        target_id: str,
        path: List[TwinEdge],
        visited: Set[str],
        cycles: List[List[TwinEdge]],
        max_depth: int,
    ) -> None:
        if len(path) > max_depth:
            return
        if current_id == target_id and len(path) > 0:
            cycles.append(list(path))
            return
        if current_id in visited:
            return
        visited.add(current_id)
        for edge in self.get_outgoing(current_id, direction=EdgeDirection.FLOW):
            self._dfs_cycle(
                edge.target_id, target_id, path + [edge],
                visited, cycles, max_depth,
            )
        visited.discard(current_id)

    def get_unresolved_gaps(self) -> List[TopologyGap]:
        all_gaps: List[TopologyGap] = []
        all_gaps.extend(g for g in self.gaps if not g.resolved)
        for node in self.nodes.values():
            all_gaps.extend(g for g in node.gaps if not g.resolved)
        for edge_list in self.edges.values():
            for edge in edge_list:
                all_gaps.extend(g for g in edge.gaps if not g.resolved)
        return all_gaps

    def resolve_gap(
        self, gap: TopologyGap, value: Any, confidence: float
    ) -> None:
        gap.resolved = True
        gap.resolution_value = value
        gap.resolution_confidence = confidence
        self._update_fidelity()

    def _update_fidelity(self) -> None:
        total_expected = len(self.nodes) + sum(
            len(e) for e in self.edges.values()
        )
        if total_expected == 0:
            self.fidelity = 0.0
            return
        unresolved = len(self.get_unresolved_gaps())
        self.fidelity = max(0.0, 1.0 - (unresolved / max(total_expected, 1)))

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return sum(len(e) for e in self.edges.values())

    @property
    def gap_count(self) -> int:
        return len(self.get_unresolved_gaps())
