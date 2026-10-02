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

A CAUSE AT THE TARGET OF ITS RELATION. A process depends on
a department, and a failure runs from the department to the process: against the
edge the author feeds. `cause: target` on the rule says so, and `cause: source`
says what `edge_direction: causal` says. The key stands alone: beside
`edge_direction: causal`, which names the source, `cause: target` contradicts it,
and neither is applied -- the rule carries no causal direction, and the loader
names the pair. An engine before the key reads a rule carrying only `cause:` as
no causal direction at all, so the walk stops there and is never walked
backwards; the pair is refused rather than reconciled because such an engine
WOULD walk it backwards.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..temporal.temporal_edge import resolve_number
from ..types import DEFAULT_CAUSAL_ROOT_PRIOR, read_causal_root_prior

__all__ = ["EdgeWeight", "CausalGraph", "causal_subgraph",
           "SOURCE_DECLARED", "SOURCE_LEARNED", "SOURCE_DEFAULT",
           "DEFAULT_WEIGHT", "DEFAULT_LEAK", "cause_end"]

#: the ends of a relation a `cause:` key may name.
_CAUSE_ENDS = ("source", "target")


def cause_end(rule: Any) -> Optional[str]:
    """`"source"` or `"target"` -- the end of the rule's relation where a failure
    starts -- or `None` when the rule declares no causal direction.

    `edge_direction: causal` names the source. `cause:` names either end on its
    own. Beside `edge_direction: causal`, `cause: target` contradicts it and
    neither applies. A `cause:` value that is not an end is not applied, and the
    rule keeps whatever `edge_direction` says. The loader reports both.
    """
    if not isinstance(rule, dict):
        return None
    causal = str(rule.get("edge_direction", "")) == "causal"
    end = rule.get("cause")
    if end not in _CAUSE_ENDS:
        return "source" if causal else None
    if causal and end == "target":
        return None
    return end

SOURCE_DECLARED = "declared"
SOURCE_LEARNED = "learned"
SOURCE_DEFAULT = "default"

#: What an undeclared edge would be worth, and the number this module refuses
#: to spend. It exists to be REPORTED -- a reader asking what the engine would
#: have assumed gets an answer -- and `run_inference` declines any query whose
#: active paths rest on one.
DEFAULT_WEIGHT = 0.3
#: The chance a node is faulty with no faulty parent. Also a default -- and
#: SPENT, not refused. this said *also refused on an active path*, and
#: nothing refused it; a declared weight beside an undeclared leak was answered
#: with this number and nothing said so. An answer it reaches is now stamped
#: `leak_not_declared`.
DEFAULT_LEAK = 0.01


@dataclass(frozen=True)
class EdgeWeight:
    weight: float
    leak: float
    source: str
    observations: Optional[int] = None
    #: where the leak came from, beside where the weight did:
    #: `declared`, or `default` for the engine's `DEFAULT_LEAK`.
    leak_source: str = SOURCE_DECLARED

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
    #: the dead time each edge's rule DECLARES, in seconds, and its
    #: time constant: `None` wherever nothing was declared. Never the engine's
    #: own 60 s, which a transition falls back to and stamps: a read shifted by
    #: a number nobody declared would place the evidence at an instant the
    #: model never named, and on a monthly series it is last month's reading.
    delays: Dict[Tuple[str, str], Optional[float]] = field(default_factory=dict)
    time_constants: Dict[Tuple[str, str], Optional[float]] = field(
        default_factory=dict)
    #: the prior on a root cause, and whether the model declared it
    #: under `causal.root_prior`.
    root_prior: float = DEFAULT_CAUSAL_ROOT_PRIOR
    root_prior_declared: bool = False

    def leak_for(self, node: str) -> float:
        incoming = [self.weights[(p, node)] for p in self.parents.get(node, ())]
        return max((w.leak for w in incoming), default=DEFAULT_LEAK)

    def leak_declared(self, node: str) -> bool:
        """Whether the leak in effect at `node` is one somebody declared.
        The leak in effect is the largest its incoming rules give, so
        a leak declared BELOW the engine's beside an undeclared one still
        leaves the engine's number deciding; a node with no parents has no
        leak to spend."""
        incoming = [self.weights[(p, node)] for p in self.parents.get(node, ())]
        if not incoming:
            return True
        leak = max(w.leak for w in incoming)
        return any(w.leak == leak and w.leak_source == SOURCE_DECLARED
                   for w in incoming)

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


def resolve_strength(raw: Any) -> Tuple[Optional[float], Optional[str]]:
    """`(value, unresolved)` for a declared `weight` or `leak` -- never raises.

    A strength is a NUMBER in the model file. A quoted `"0.8"` or a
    word was taken as no weight at all -- `cpt_missing`, asking for the number
    the author wrote -- or as the engine's own leak, with nothing said. The
    domain loader asks this same function, so its report and this reader
    cannot disagree about what a strength is.
    """
    if raw is None:
        return None, None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw), None
    return None, str(raw)


def _weight_from(rule: Dict[str, Any],
                 learned: Optional[Tuple[float, int]]) -> EdgeWeight:
    causal = rule.get("causal")
    if not isinstance(causal, dict):
        # `causal: 0.8` raised here and came back `internal_error`,
        # an engine fault's name for an author's mistake. Skipped as though
        # absent; the domain loader reports it.
        causal = {}
    declared, _unresolved = resolve_strength(causal.get("weight"))
    leak_value, _unresolved = resolve_strength(causal.get("leak"))
    leak = DEFAULT_LEAK if leak_value is None else leak_value
    leak_source = SOURCE_DEFAULT if leak_value is None else SOURCE_DECLARED
    if declared is not None:
        return EdgeWeight(declared, leak, SOURCE_DECLARED, leak_source=leak_source)
    if learned is not None:
        value, count = learned
        return EdgeWeight(float(value), leak, SOURCE_LEARNED,
                          observations=int(count), leak_source=leak_source)
    return EdgeWeight(DEFAULT_WEIGHT, leak, SOURCE_DEFAULT, leak_source=leak_source)


def causal_subgraph(model, graph, entities,
                    learned: Optional[Dict[Tuple[str, str], Tuple[float, int]]] = None
                    ) -> CausalGraph:
    """Every edge the author declared causal, with its strength and provenance."""
    rules = _rule_index(model)
    learned = learned or {}
    out = CausalGraph()
    out.entity_type = {eid: e.type for eid, e in entities.items()}
    root = read_causal_root_prior(getattr(model, "causal", None))
    out.root_prior, out.root_prior_declared = root.prior, root.declared

    for source_id in list(getattr(graph, "edges", {}) or {}):
        for relation in graph.get_relationship_types(source_id) or ():
            for target_id in graph.get_relationships(source_id, relation) or ():
                source, target = entities.get(source_id), entities.get(target_id)
                if source is None or target is None:
                    continue
                rule = rules.get((source.type, target.type, str(relation)))
                end = cause_end(rule)
                if end is None:
                    continue
                # the cause is the end the rule names; with
                # `cause: target` the edge is walked against its feed.
                cause, effect = ((source_id, target_id) if end == "source"
                                 else (target_id, source_id))
                for node in (cause, effect):
                    if node not in out.parents:
                        out.parents[node] = []
                        out.nodes.append(node)
                out.parents[effect].append(cause)
                out.weights[(cause, effect)] = _weight_from(
                    rule, learned.get((cause, effect)))
                latent = rule.get("latent_confounder")
                if latent:
                    out.latents[(cause, effect)] = str(latent)
                delay, tau = _declared_time_course(rule)
                out.delays[(cause, effect)] = delay
                out.time_constants[(cause, effect)] = tau
    return out


def _declared_time_course(rule: Dict[str, Any]
                          ) -> Tuple[Optional[float], Optional[float]]:
    """`(dead time, time constant)` as the rule's `temporal:` block declares
    them, each `None` when absent, unreadable, negative or not finite -- the
    loader reports an unreadable one; this reader only declines to use it."""
    block = rule.get("temporal")
    if not isinstance(block, dict):
        return None, None

    def declared(key: str) -> Optional[float]:
        value, _unresolved = resolve_number(block.get(key))
        if value is None or not math.isfinite(value) or value < 0:
            return None
        return value

    return declared("propagation_delay_s"), declared("time_constant_s")
