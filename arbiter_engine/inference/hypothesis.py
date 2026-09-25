"""What could explain a finding, and what reading would tell the candidates apart.

Phase B4. `gaps` says what the MODEL does not declare. This says what
the WORLD might be doing given what it does declare, which is the same question
turned around: a finding names an entity that is wrong, and an operator's next
move is to decide where to look.

THE PHASE PLAN CALLED THIS A PROMOTION AND IT IS NOT. `twin/hypothesis_generator.py`
was named as the thing to promote. Measured: it walks a topology for STRUCTURAL
patterns -- conservation, feedback loops, property bounds, monotonicity -- and
emits a `TopologyHypothesis` carrying a `precondition_pattern`, a `confidence`
and a `tenant_id`. None of that is `(cause, evidence_needed, test_action)` for a
finding, and `tenant_id` is an orchestrator concept this engine does not have.
Promoting it would have shipped the wrong verb wearing the right name, and
carried a multi-tenant field into a domain-free package.

So this is a composition over machinery that already exists, which is the
cheaper and more honest build: the causal subgraph supplies the candidates, the
inference runner scores them, and the model supplies the two things neither of
those knows -- which reading would discriminate, and whether an action is
declared that could test it.

IT RUNS UNDER THE `inference` DISCIPLINE AND DECLARES NO VOCABULARY OF ITS OWN.
The discipline set is closed and so is each discipline's decline vocabulary, and
BOTH refused an eighth member when this verb first asked for one -- which is the
refuse-what-you-cannot-read rule working on its own author. Using `inference` is
also the truer answer: this runs that discipline's machinery on a causal
question, and an eighth name for the seventh engine would be a second record of
one thing.

Its two refusals therefore share `not_identifiable`, distinguished by their
detail. This project normally SPLITS a reason into named arms rather than
sharing one, so that is a debt and not a design: growing a published closed
vocabulary has a measured cost on a fail-closed consumer -- one broke this month
on exactly such an addition -- and that decision should not ride along inside
the commit that ships a feature.

WHAT IT REFUSES. It ranks only DECLARED causal ancestors. It does not search for
a cause outside the graph, does not invent an edge, and does not rank an entity
the author never connected -- the same refusal `infer` makes, for the same
reason: an engine that proposed causes nobody declared would be doing the
inference this project removed from `role:` and from flow direction.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from ..subenvelope import Decline, SubEnvelope
from .causal import CausalGraph, causal_subgraph
from .runner import Query, run_inference

#: How far upstream a hypothesis may reach. BOUNDED, and the bound is the point:
#: an unbounded ancestor walk over a graph with a cycle does not return, and the
#: project rule is that verification stays in P. The graph's own `cycle()` check
#: guards the declaration; this guards the walk.
MAX_HOPS = 4


def _ancestors(graph: CausalGraph, node: str,
               max_hops: int = MAX_HOPS) -> List[Tuple[str, int]]:
    """`(node, hops)` upstream of `node`, nearest first, each reported once."""
    seen: Set[str] = {node}
    out: List[Tuple[str, int]] = []
    frontier = [node]
    for hop in range(1, max_hops + 1):
        nxt: List[str] = []
        for current in frontier:
            for parent in graph.parents.get(current, ()) or ():
                if parent in seen:
                    continue
                seen.add(parent)
                out.append((parent, hop))
                nxt.append(parent)
        if not nxt:
            break
        frontier = nxt
    return out


def _readable_properties(model, entity_type: str) -> List[str]:
    """What the model says can be read on this type, in declared order."""
    indicators = (getattr(model, "indicators", None) or {}).get(entity_type) or []
    names: List[str] = []
    for indicator in indicators:
        name = getattr(indicator, "name", None)
        if name is None and isinstance(indicator, dict):
            name = indicator.get("name")
        if name:
            names.append(str(name))
    return names


def _test_action(model, entity_type: str) -> Optional[str]:
    """A declared action that applies to this type, or None.

    NAMED, NEVER INVENTED. An engine that suggested an action nobody declared
    would be recommending a thing it cannot know is safe, on a system it cannot
    see. `None` here means the model declares no way to test this candidate,
    which is a fact about the model and is worth reporting as one.
    """
    for template in (getattr(model, "action_templates", None) or ()):
        applies = getattr(template, "applies_to", None)
        name = getattr(template, "name", None)
        if applies is None and isinstance(template, dict):
            applies, name = template.get("applies_to"), template.get("name")
        if applies == entity_type and name:
            return str(name)
    return None


def hypothesize(session: Any, entity_id: str, *,
                report_above: Optional[float] = None
                ) -> Tuple[SubEnvelope, List[Dict[str, Any]]]:
    """Rank the declared causes of a finding on `entity_id`.

    Returns the sub-envelope and the ranked candidates, which the caller
    attaches -- the shape `entail` already uses, because `SubEnvelope` is
    frozen and a verb that mutated one would be the only thing here that did.

    Each candidate carries the posterior `infer` computes for it, the reading
    that would discriminate it, and the declared action that could test it --
    or an honest `None` where the model offers neither.
    """
    checked: Dict[str, Any] = {"candidates": 0, "ranked": 0, "max_hops": MAX_HOPS}
    declines: List[Decline] = []

    if getattr(session, "model", None) is None:
        return (SubEnvelope("inference", {"candidates": 0}, source="unavailable",
                            reason="no domain model loaded"), [])

    graph = causal_subgraph(session.model, session.graph, session.entities)
    if entity_id not in graph.nodes:
        declines.append(Decline(
            "not_identifiable", {"entity": entity_id},
            detail=(f"`{entity_id}` is not in the declared causal subgraph, so "
                    f"there is nothing upstream of it to rank. An edge enters "
                    f"that graph by declaring `edge_direction: causal`; this "
                    f"verb does not search for one.")))
        return SubEnvelope("inference", checked, not_checked=declines), []

    candidates = _ancestors(graph, entity_id)
    checked["candidates"] = len(candidates)
    if not candidates:
        declines.append(Decline(
            "not_identifiable", {"entity": entity_id},
            detail=(f"`{entity_id}` has no declared causal ancestor within "
                    f"{MAX_HOPS} hops, so the model offers nothing that could "
                    f"explain a finding on it. That is a statement about the "
                    f"model and not about the system.")))
        return SubEnvelope("inference", checked, not_checked=declines), []

    ranked: List[Dict[str, Any]] = []
    for node, hops in candidates:
        sub = run_inference(session, Query(target=node), report_above=None)
        payload = sub.to_dict()
        posterior = (payload.get("checked") or {}).get("posterior")
        entity_type = graph.entity_type.get(node, "")
        properties = _readable_properties(session.model, entity_type)
        ranked.append({
            "cause": node,
            "entity_type": entity_type,
            "hops": hops,
            "posterior": posterior,
            # The FIRST declared readable property, which is the model's own
            # ordering rather than this verb's opinion about which matters.
            "evidence_needed": (f"{node}.{properties[0]}" if properties else None),
            "test_action": _test_action(session.model, entity_type),
        })

    # Nearest first on a tie, because a cause two hops away explains a finding
    # only through one that is nearer, and asking about the nearer one first is
    # how an operator narrows rather than guesses.
    ranked.sort(key=lambda row: (-(row["posterior"] or 0.0), row["hops"],
                                 row["cause"]))
    checked["ranked"] = len(ranked)
    if report_above is not None:
        ranked = [r for r in ranked
                  if r["posterior"] is not None and r["posterior"] >= report_above]
        checked["reported"] = len(ranked)

    return SubEnvelope("inference", checked, not_checked=declines), ranked
