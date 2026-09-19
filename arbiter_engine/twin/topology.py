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

from ..clock import now_utc
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
    # the model does not say something the check needs, and no
    # amount of looking at the data will supply it. Distinct from
    # MISSING_PROPERTY, which says the telemetry is short of a value the model
    # DID declare: that one is answered by feeding data, this one only by
    # editing the model, and telling an operator to go find data that will not
    # help is worse than saying nothing.
    #
    # A new member rather than the nearest existing one,: a closed
    # enum missing a member does not raise, it reclassifies the case as the
    # nearest member and reports it with confidence. `gap_type` is an open
    # string in `schema/envelope.schema.json`, and COMPATIBILITY.md permits a
    # patch release to add an enum member for exactly this reason.
    MISSING_DECLARATION = "missing_declaration"


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
    checked_at: datetime = field(default_factory=now_utc)
    evidence: Dict[str, Any] = field(default_factory=dict)
    indicator_name: str = ""


@dataclass
class ProjectedValue:
    """A property value projected into the future."""
    value: float
    confidence: float
    horizon_s: float
    #: THE FORECAST'S OWN SPREAD, which used to be thrown away. A
    #: projector returns a distribution; this carried only its median, so a
    #: rollout seeded from a forecast inherited the number and none of the
    #: doubt. Measured on a random walk at a 60-minute horizon: the forecast's
    #: own 90% band was +/- 357.55 rpm, and the predictions the rollout filed
    #: off it carried a tolerance of +/- 0.45 pct -- sixteen times too narrow,
    #: which falsifies a projection that was never wrong and makes the
    #: engine's own calibration figure say its forecasts are worthless.
    sigma: float = 0.0
    model: str = ""
    #: where the NUMBER came from, carried so a value produced by a
    #: declared transition can be told from one fitted off a series. Empty
    #: means the producer did not say, which is how every value read before
    #: transitions existed.
    source: str = ""
    #: Engine-made assumptions this value rests on, stamped the way
    #: `forecast/contract.py` stamps `gaussian_from_mean_sigma` rather than
    #: quietly choosing on the caller's behalf.
    assumptions: List[str] = field(default_factory=list)


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
    discovered_at: datetime = field(default_factory=now_utc)
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
            # the only template that asks for an edit to the model
            # rather than for an observation. Every question above is
            # answerable by looking harder at the system; this one is not, and
            # phrasing it like the others would send an operator to the
            # telemetry for something the telemetry does not contain.
            GapType.MISSING_DECLARATION: "Which quantities on '{location}' balance against which, and in which direction?",
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
    # annotation — which an internal ruling asserted would drop when the traverser's
    # unread `degradation_fitter` parameter went, and measurement showed it
    # did not, because THIS was the carrier.
    #
    # Third instance of the shape (`axiom_checkers`) and
    # (`degradation_fitter`), and the first that is a field rather
    # than a parameter. `DegradationCurve` itself is live and unaffected —
    # An internal ruling wired it into the full system, which is where
    # degradation belongs.
    projected_values: Dict[str, ProjectedValue] = field(default_factory=dict)
    confidence: NodeConfidence = field(default_factory=NodeConfidence)
    gaps: List[TopologyGap] = field(default_factory=list)
    #: property name -> ``"in"`` / ``"out"``, seeded by the builder
    #: from every indicator on this entity's type that declares ``flow:``.
    #:
    #: Written by ``TwinBuilder._flow_directions_from_indicators`` and read by
    #: ``TopologyTraverser._check_flow_balance``, which is the whole reason the
    #: field exists: that check used to decide which of an entity's properties
    #: were inflows by matching their NAMES against English tokens, and there
    #: was no route from the model — which knows — to the traverser, which was
    #: guessing. Empty means undeclared, and undeclared means no balance is
    #: computed; on the check that consulted no declaration at all.
    #:
    #: Both writer and reader exist on purpose. An internal ruling removed a `TwinNode`
    #: field that had neither, and the lesson from it is recorded here rather
    #: than relearned.
    flow_directions: Dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Transition — declared dynamics on an edge
# ---------------------------------------------------------------------------

#: the keys a `transition:` block must carry to load at all. A block
#: missing any of them is refused and reported, not completed with a default:
#: a gain the author did not write is a guess wearing a declaration's clothes,
#: and the same argument `consistency:` makes about a tolerance and
#: `homeostasis:` makes about a setpoint applies here with more force, because
#: a wrong gain moves a NUMBER a reader will act on.
REQUIRED_TRANSITION_KEYS = ("from", "to", "gain", "source")

#: `gain: estimate` says the author declares the COUPLING and asks
#: the engine to fit the MAGNITUDE.
#:
#: This is what lets a learned gain exist without the engine guessing which
#: properties are coupled. Pairing every numeric property on one entity with
#: every numeric property on another and keeping whatever correlates is the
#: inference this package removed from `role:`, from flow direction and from
#: `agrees_with:` -- it would find a gain between a pump's run-hours counter
#: and a tank's level, because both rise.
#:
#: So the pair is always declared. Only the number may be learned, the fitted
#: value is a PROPOSAL until adopted, and a transition carrying it projects
#: nothing until then.
ESTIMATE_SENTINEL = "estimate"


@dataclass
class Transition:
    """How much a target property moves per unit of a source property.

    The edge already carried the TIME COURSE of a propagation
    (``propagation_delay_s``, ``time_constant_s``, ``response_model``) and had
    no way to say WHICH property drives WHICH, or by how much. So
    ``traverse()`` could report that a tank was reachable from a pump with a
    probability and a delay, and could not report what the tank's level
    became. This is the missing half.

    ``gain`` is a STEADY-STATE gain in units of ``to_property`` per unit of
    ``from_property``. The transient comes from the edge's own temporal block
    through ``TwinEdge.response_fraction``; the two are deliberately separate
    because the same coupling can be declared with or without a time course,
    and a model that knows the end state but not the rate should be able to
    say so.

    ``source`` is the provenance of the NUMBER and is required. ``datasheet``
    and ``contract`` are claims the author is standing behind; ``measured``
    and ``estimated`` say a human fitted it; a learned gain carries the
    identity of whatever produced it. Nothing in the engine infers a
    transition from a property's name, its units, or a correlation -- the
    inference the repository spent several releases removing from `role:`,
    from flow direction and from `agrees_with:`.
    """
    from_property: str
    to_property: str
    gain: float
    source: str
    #: True when the block said `gain: estimate`. The pair is
    #: declared and the magnitude is not, so `gain` is 0.0 and this
    #: transition moves NOTHING until a fitted value is adopted. A
    #: zero-gain transition that reported a value would be the engine
    #: answering with a number nobody supplied.
    estimated: bool = False
    #: the DECLARED standard deviation of `gain`, in the same units.
    #: A datasheet that says *0.02 per rpm, plus or minus 0.002* has stated
    #: one; nothing infers it. `0.0` means NOT DECLARED, which is why the
    #: default is a number rather than `None`: a zero spread and an
    #: undeclared spread produce the same arithmetic, and the difference that
    #: matters to a reader is carried by `has_uncertainty` below and reported
    #: as a stamp, not smuggled into the value.
    #:
    #: WHY NOT REUSE `confidence`. That field is a weight on how much to
    #: believe the coupling exists at all, on a 0-1 scale with no units. A
    #: spread on the gain is a different quantity in different units, and
    #: mapping one onto the other would be the engine inventing a variance
    #: from a number nobody declared as one.
    gain_sigma: float = 0.0
    #: True when the block said `gain_sigma: estimate`. The author
    #: is saying a spread exists and that they have not measured it, which is
    #: a different claim from declaring none: the first asks the learner for a
    #: proposal, the second says the question was never raised. Until a fitted
    #: spread is adopted the transition carries no interval either way -- a
    #: band nobody supplied is not a band of zero width.
    sigma_estimated: bool = False
    offset: float = 0.0
    clamp_to_bounds: bool = False
    #: Sample support behind a fitted gain. Zero for a declared one, and that
    #: asymmetry is the point: a declaration is not evidence with n=0, it is a
    #: different KIND of claim.
    observation_count: int = 0
    confidence: float = 1.0

    #:. The `source:` values MODELING.md documents for a transition.
    #: Named here so the property below and the guide cannot drift apart
    #: silently, which they had: the check accepted `runbook`, which is an
    #: ACTION TEMPLATE's provenance and has never been a documented
    #: transition source, and rejected `measured` and `estimated`, which are
    #: two of the four the guide lists.
    DECLARED_SOURCES = ("datasheet", "contract", "measured", "estimated")

    @property
    def has_uncertainty(self) -> bool:
        """True when the author declared a spread on this gain.

        Distinct from `gain_sigma > 0` only in intent, and the intent is what
        a reader needs: an edge with no declared spread is not an edge whose
        spread is zero, it is one nobody measured. The engine reports the
        difference rather than treating the second as the first.
        """
        return self.gain_sigma > 0.0

    @property
    def is_declared(self) -> bool:
        """True when a human supplied this number, however they arrived at it.

        The distinction is PROVENANCE, not method. All four documented values
        are a person standing behind a gain -- off a datasheet, out of a
        contract, measured on the plant, or estimated by an engineer. What is
        NOT declared is a gain some producer FITTED, which carries the
        identity of whatever produced it (`learned`, or a model id) precisely
        so it can be told apart from the four above.

        Whether a fitted gain has been ADOPTED is a different question and has
        its own field: `estimated` is True when the block said
        `gain: estimate`, and such a transition projects nothing at all.
        """
        return self.source in self.DECLARED_SOURCES


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

    #: declared value dynamics, seeded by the builder from the
    #: relationship rule's `transition:` block. Empty means the edge says how
    #: FAST and how LIKELY a change propagates and not how MUCH, which is a
    #: `missing_dynamics` gap the moment a caller asks for a value.
    #:
    #: A list because one relationship can drive more than one property: a
    #: pump feeding a tank moves both its level and its inflow.
    transitions: List['Transition'] = field(default_factory=list)

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
    #: a ceiling on transitions applied in one walk. Exhausting it
    #: is a DECLINE carrying the number, never a timeout: `inference/ve.py`
    #: states the rule this follows -- an engine that does not return is
    #: worse than one that refuses.
    max_transitions: int = 100_000


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
class TransitionApplied:
    """One declared transition, fired across one edge, with its arithmetic.

    Recorded rather than summarised so a reader can reconstruct the
    number: which edge, which properties, what the source moved by, what
    fraction of the response the horizon allowed, and where the gain came
    from. A projected value whose derivation cannot be inspected is the kind
    of confident number this engine declines to produce.
    """
    edge: str                      # "source->target"
    relation_type: str
    from_property: str
    to_property: str
    delta_source: float
    gain: float
    fraction: float
    delta_target: float
    source: str
    elapsed_s: float


@dataclass
class SimulationDecline:
    """A value this traversal would not compute, and why.

    Mirrors `Decline` in the discipline sub-envelopes rather than importing
    it: the traverser is below that layer and `api` translates.
    """
    reason: str
    location: str
    detail: str = ""


@dataclass
class TraversalResult:
    """Output of a topology traversal."""
    steps: List[TraversalStep] = field(default_factory=list)
    #: the simulation legs. Empty on a CURRENT-mode walk, which
    #: asks for no values and therefore projects none.
    transitions_applied: List['TransitionApplied'] = field(
        default_factory=list)
    simulation_declines: List['SimulationDecline'] = field(
        default_factory=list)
    #: entity_id -> {property -> imagined absolute value}
    imagined_values: Dict[str, Dict[str, float]] = field(default_factory=dict)
    #: entity_id -> {property -> provenance of the number}
    imagined_sources: Dict[str, Dict[str, str]] = field(default_factory=dict)
    #: entity_id -> {property -> standard deviation of the imagined
    #: value}. PRESENT ONLY where a declared `gain_sigma:` reached it, so an
    #: absent entry says nobody declared a spread rather than that the spread
    #: is zero. That distinction is the whole point: a value with no interval
    #: and a value known to be exact are different claims, and an engine that
    #: printed 0.0 for both would be making the weaker one look like the
    #: stronger.
    imagined_sigma: Dict[str, Dict[str, float]] = field(default_factory=dict)
    #: Engine-made assumptions the imagined values rest on.
    assumptions: List[str] = field(default_factory=list)
    transitions_attempted: int = 0
    #: Transitions the budget stopped. Reported as ONE decline carrying this
    #: count, not one decline each.
    transitions_unapplied: int = 0
    nodes_not_projected: List[str] = field(default_factory=list)
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
    created_at: datetime = field(default_factory=now_utc)
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
