"""The causal subgraph, and where every number in it came from.

WHY PROVENANCE IS A FIELD AND NOT A COMMENT

A posterior is a product of edge strengths. If one of them is a constant the
engine chose, the posterior is partly a statement about the engine, and a
reader cannot tell which part by looking at the number. So each weight carries
whether it was DECLARED by the author, LEARNED from observations with the count
behind it, or is a DEFAULT -- and a default on a path that decides the answer
stops the answer instead of being spent.

WHY THE SUBGRAPH IS DECLARED AND NOT DISCOVERED

`discover` proposes causal structure from lead-lag and is careful to call it
predictive precedence. This module consumes only `edge_direction: causal` from
`relationship_rules` -- what the author asserted. Letting discovery's output in
here silently would close a loop the engine is not entitled to close: infer
structure from correlation, then compute probabilities as though the structure
were given.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

__all__ = ["EdgeWeight", "CausalGraph", "causal_subgraph",
           "SOURCE_DECLARED", "SOURCE_LEARNED", "SOURCE_DEFAULT",
           "DEFAULT_WEIGHT", "DEFAULT_LEAK"]

SOURCE_DECLARED = "declared"
SOURCE_LEARNED = "learned"
SOURCE_DEFAULT = "default"

#: What an undeclared edge would be worth, and the number this module refuses
#: to spend. It exists to be REPORTED -- a reader asking what the engine would
#: have assumed gets an answer -- and `run_inference` declines any query whose
#: active paths rest on one.
DEFAULT_WEIGHT = 0.3
#: The chance a node is faulty with no faulty parent. Also a default, also
#: refused on an active path.
DEFAULT_LEAK = 0.01


@dataclass(frozen=True)
class EdgeWeight:
    weight: float
    leak: float
    source: str
    observations: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        out = {"weight": self.weight, "leak": self.leak, "source": self.source}
        if self.observations is not None:
            out["observations"] = self.observations
        return out


@dataclass
class CausalGraph:
    nodes: List[str] = field(default_factory=list)
    parents: Dict[str, List[str]] = field(default_factory=dict)
    weights: Dict[Tuple[str, str], EdgeWeight] = field(default_factory=dict)
    #: Declared unobserved common causes, keyed by the edge that named one.
    latents: Dict[Tuple[str, str], str] = field(default_factory=dict)
    entity_type: Dict[str, str] = field(default_factory=dict)

    def leak_for(self, node: str) -> float:
        incoming = [self.weights[(p, node)] for p in self.parents.get(node, ())]
        return max((w.leak for w in incoming), default=DEFAULT_LEAK)

    def sources(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for weight in self.weights.values():
            counts[weight.source] = counts.get(weight.source, 0) + 1
        return counts

    def cycle(self) -> Optional[List[str]]:
        """A cycle, if there is one. Returned rather than flagged, because the
        useful refusal names the loop the author has to break."""
        colour: Dict[str, int] = {}
        stack: List[str] = []

        def visit(node: str) -> Optional[List[str]]:
            colour[node] = 1
            stack.append(node)
            for parent in self.parents.get(node, ()):
                state = colour.get(parent, 0)
                if state == 1:
                    return stack[stack.index(parent):] + [parent]
                if state == 0:
                    found = visit(parent)
                    if found:
                        return found
            colour[node] = 2
            stack.pop()
            return None

        for node in self.nodes:
            if colour.get(node, 0) == 0:
                found = visit(node)
                if found:
                    return found
        return None

    def ancestors(self, node: str) -> Set[str]:
        seen: Set[str] = set()
        frontier = list(self.parents.get(node, ()))
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            frontier.extend(self.parents.get(current, ()))
        return seen


def _rule_index(model) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    index = {}
    for rule in model.relationship_rules or ():
        key = (str(rule.get("source_type", "")), str(rule.get("target_type", "")),
               str(rule.get("type", "")))
        index[key] = rule
    return index


def _weight_from(rule: Dict[str, Any],
                 learned: Optional[Tuple[float, int]]) -> EdgeWeight:
    causal = rule.get("causal") or {}
    declared = causal.get("weight")
    leak = causal.get("leak")
    if isinstance(declared, (int, float)) and not isinstance(declared, bool):
        return EdgeWeight(float(declared),
                          float(leak) if isinstance(leak, (int, float)) else DEFAULT_LEAK,
                          SOURCE_DECLARED)
    if learned is not None:
        value, count = learned
        return EdgeWeight(float(value),
                          float(leak) if isinstance(leak, (int, float)) else DEFAULT_LEAK,
                          SOURCE_LEARNED, observations=int(count))
    return EdgeWeight(DEFAULT_WEIGHT,
                      float(leak) if isinstance(leak, (int, float)) else DEFAULT_LEAK,
                      SOURCE_DEFAULT)


def causal_subgraph(model, graph, entities,
                    learned: Optional[Dict[Tuple[str, str], Tuple[float, int]]] = None
                    ) -> CausalGraph:
    """Every edge the author declared causal, with its strength and provenance."""
    rules = _rule_index(model)
    learned = learned or {}
    out = CausalGraph()
    out.entity_type = {eid: e.type for eid, e in entities.items()}

    for source_id in list(getattr(graph, "edges", {}) or {}):
        for relation in graph.get_relationship_types(source_id) or ():
            for target_id in graph.get_relationships(source_id, relation) or ():
                source, target = entities.get(source_id), entities.get(target_id)
                if source is None or target is None:
                    continue
                rule = rules.get((source.type, target.type, str(relation)))
                if not rule or str(rule.get("edge_direction", "")) != "causal":
                    continue
                for node in (source_id, target_id):
                    if node not in out.parents:
                        out.parents[node] = []
                        out.nodes.append(node)
                out.parents[target_id].append(source_id)
                out.weights[(source_id, target_id)] = _weight_from(
                    rule, learned.get((source_id, target_id)))
                latent = rule.get("latent_confounder")
                if latent:
                    out.latents[(source_id, target_id)] = str(latent)
    return out
