"""Topology-Based Digital Twin module."""

from .topology import (
    TwinNode, TwinEdge, TopologyGap, DigitalTwinTopology,
    AxiomState, ProjectedValue, NodeConfidence,
    EdgeDirection, FlowType, EdgeSource, GapType, ResolutionStrategy,
    TraversalDirection, ValueMode, TraversalRequest, TraversalResult,
    TraversalStep, TopologyQuestion,
)
from .traverser import TopologyTraverser, NLTraversalTranslator
from .builder import TopologyBuilder
from .gap import GapResolver, ResolutionResult

__all__ = [
    "TwinNode", "TwinEdge", "TopologyGap", "DigitalTwinTopology",
    "AxiomState", "ProjectedValue", "NodeConfidence",
    "EdgeDirection", "FlowType", "EdgeSource", "GapType", "ResolutionStrategy",
    "TraversalDirection", "ValueMode", "TraversalRequest", "TraversalResult",
    "TraversalStep", "TopologyQuestion",
    "TopologyTraverser", "NLTraversalTranslator",
    "TopologyBuilder",
    "GapResolver", "ResolutionResult",
]
