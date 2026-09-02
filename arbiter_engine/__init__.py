"""arbiter-engine v0.1 — the public API.

The names below are the contract. Everything else in this package is
importable and UNSUPPORTED: reaching for a deeper path is legitimate and
unpromised, and those paths may move without a major version.

This file is generated. Edits here are overwritten by the next build;
the exports below are a declared contract rather than a hand-written list.
`__version__` is part of that contract and is read from installed
metadata, so it is None when this package runs from a source tree.
"""

from . import api
from .history.observation import InMemoryObservationHistory
from .interfaces import Entity, Observation, Problem, RelationshipGraph
from .ontology.domain_loader import DomainModel
from .ontology.reasoner import UnifiedAxiomReasoner
from .twin.traverser import TopologyTraverser
from .types import Axiom, Severity
from .envelope import engine_version as _engine_version

#: The installed distribution's version, or None when this package
#: runs from a source tree with no distribution. Read from metadata
#: through the same function the envelope reports, so the two cannot
#: disagree about which engine produced a judgment.
__version__ = _engine_version()

__all__ = [
    "Axiom",
    "DomainModel",
    "Entity",
    "InMemoryObservationHistory",
    "Observation",
    "Problem",
    "RelationshipGraph",
    "Severity",
    "TopologyTraverser",
    "UnifiedAxiomReasoner",
    "api",
]
