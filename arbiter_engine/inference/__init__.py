"""Probabilistic inference over the declared causal subgraph.

The eight axioms say what is wrong. Traversal says what is reachable from it.
Neither answers the question an operator actually asks next -- *given what I
can see, how likely is it that THIS is faulty* -- because that is a question
about a distribution, and nothing in the engine held one.

Nothing here infers structure. The causal edges are the ones the author
declared `edge_direction: causal`, the strengths are the ones the author
declared or a learner measured, and a strength nobody supplied stops the
answer rather than being filled in.
"""

from .causal import CausalGraph, EdgeWeight, causal_subgraph
from .ve import FACTOR_VARIABLE_LIMIT, Factor, eliminate, noisy_or_factor
from .runner import Query, run_inference

__all__ = ["CausalGraph", "EdgeWeight", "causal_subgraph", "Factor",
           "eliminate", "noisy_or_factor", "FACTOR_VARIABLE_LIMIT",
           "Query", "run_inference"]
