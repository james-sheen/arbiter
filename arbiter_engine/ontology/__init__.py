"""
Ontology Reasoning - Layer 2 Detection.

The ontology layer uses semantic reasoning based on health indicators
defined in RDF/OWL ontologies. It maps entities to health concepts
and checks the 6 System Health Axioms.

Key Features:
- RDF/TTL ontology support via rdflib
- Health meta-ontology for domain-agnostic concepts
- Per-axiom reasoning with configurable thresholds
- History-aware detection for temporal axioms
"""

from .reasoner import UnifiedAxiomReasoner
from .loader import OntologyLoader

__all__ = ['UnifiedAxiomReasoner', 'OntologyLoader']
