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

#: -- BOUND LAZILY, and the reason is that this file was the whole
#: import chain. `domain_loader.py` imports `.axioms.roles`, importing any
#: submodule executes THIS file first, and the two lines that used to sit here
#: imported `loader`, which imports rdflib at module scope. So reading a YAML
#: domain model pulled 50 rdflib modules -- an extra the project advertises as
#: OPTIONAL (`arbiter-engine[rdf]`) and which an internal ruling measured the engine never
#: reads. Nothing was broken by it: `HAS_RDFLIB` handles absence and the
#: behaviour is identical either way. It simply made `optional` mean less than
#: it says, and cost the import on every consumer that never wanted the graph.
#:
#: THE GUARD AGAINST THIS EXISTED AND WAS VACUOUS. `test_rdflib_not_pulled_in
#: _transitively` asserts rdflib is absent from `sys.modules`, which
#: is true for free on any box where rdflib is NOT INSTALLED -- every box it had
#: ever run on. It measured the absence of a package rather than the shape of
#: this import graph, and went red the day the extra became real.
#:
#: WHAT A CALLER SEES IS UNCHANGED. `from ... import OntologyLoader` and
#: `UnifiedAxiomReasoner` both resolve, here or through the package, and a
#: submodule import (`from ...ontology import loader`) was never affected by
#: this file. The name is resolved on FIRST ACCESS and cached in globals, so
#: the import happens once and only for a caller that asked for it.
_LAZY = {
    "UnifiedAxiomReasoner": ".reasoner",
    "OntologyLoader": ".loader",
}

__all__ = ['UnifiedAxiomReasoner', 'OntologyLoader']


def __getattr__(name: str):
    """PEP 562 module-level attribute hook."""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value          # resolved once, not per access
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY))
