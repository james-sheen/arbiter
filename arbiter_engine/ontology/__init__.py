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
#: THE GUARD AGAINST THIS EXISTED AND WAS VACUOUS. It asserted rdflib was
#: absent from `sys.modules`, which is true for free on any box where rdflib is
#: NOT INSTALLED -- every box it had ever run on. It measured the absence of a
#: package rather than the shape of this import graph, and went red the day the
#: extra became real.
#:
#: -- AND THIS BLOCK WAS NOT THE WHOLE CHAIN, though it says so above.
#: The sentence is kept rather than quietly corrected, because what was wrong
#: with it is the point: it is true of THIS tree, whose package root binds its
#: re-exports lazily too, and false of the derived one, whose root is
#: generated from a declared export list and cannot be lazy. There the chain ran
#: root -> `api` -> `reasoner` -> `loader` and reached rdflib without passing
#: through here at all. A claim measured on one side of a transform is a claim
#: about that side.
#:
#: The fix that holds in both is in `loader.py`, which now imports rdflib on
#: first use. The guard that catches it is a test in this package's own suite,
#: so it ships with the derived tree and runs on the lane that installs the
#: extra -- named by its subject rather than by a path, because the last comment
#: to name a file here named one that does not ship.
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
