"""Answering one query, and refusing the ones the declarations cannot support.

WHAT THE EVIDENCE IS

The last `check()`. A finding at HIGH or above sets a node faulty; an entity the
pass evaluated and found nothing on sets it clean; an entity that appears in
`not_checked` is UNOBSERVED and is left free. That third case is the one that
matters: treating a cell nobody could evaluate as clean is exactly the silence
this engine's envelope exists to stop, and it would push every posterior down.

WHAT STOPS AN ANSWER

A default weight on a path the query depends on. An open backdoor through a
latent the author declared. A cycle. Evidence the declared model gives zero
probability to. Each is a decline naming the declaration that would fix it,
and none of them is a number substituted quietly so the call can return one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import (Any, Dict, FrozenSet, List, Optional, Sequence, Set,
                    Tuple)

from ..assumptions import EVIDENCE_SEVERITY_NOT_DECLARED
from ..subenvelope import Decline, SubEnvelope
from ..twin.gap import GAP_CONFIDENCE_THRESHOLDS as _GAP_WEIGHT
from ..twin.topology import GapType, TopologyGap, TopologyQuestion
from ..types import Axiom, Severity
from .causal import SOURCE_DEFAULT, CausalGraph, causal_subgraph
from .ve import Factor, FactorTooWide, eliminate, noisy_or_factor

__all__ = ["Query", "run_inference", "ROOT_PRIOR"]

#: The prior on a root cause with no parents and no evidence. A DEFAULT, and
#: it is reported as one in every answer's evidence -- but unlike an edge
#: weight it cannot be declared away yet, so it is stated rather than refused.
#: An answer that rests on it says so in `priors`.
ROOT_PRIOR = 0.05


@dataclass(frozen=True)
class Query:
    target: str
    #: Interventions: `{node: 0 or 1}`. Under `do`, the node's incoming edges
    #: are CUT -- that is what distinguishes an intervention from an
    #: observation, and computing one as the other is the mistake the whole
    #: apparatus exists to avoid.
    do: Dict[str, int] = field(default_factory=dict)

    @property
    def text(self) -> str:
        if not self.do:
            return f"P({self.target} faulty | evidence)"
        acts = ", ".join(f"do({k}={v})" for k, v in sorted(self.do.items()))
        return f"P({self.target} faulty | evidence, {acts})"


def _question(gap_type, location, description, text):
    return TopologyQuestion(
        gap=TopologyGap(gap_type=gap_type, location=location,
                        description=description),
        question_text=text, priority=_GAP_WEIGHT.get(gap_type, 0.5),
        context_path=[])


#: The floor this engine uses when a model declares none. It was a literal in
#: the loop below and said so nowhere -- and the stamp it emits.
DEFAULT_EVIDENCE_SEVERITIES: FrozenSet[str] = frozenset({"HIGH", "CRITICAL"})


def evidence_severities(model) -> Tuple[FrozenSet[str], bool]:
    """`(floor, declared)` -- which severities make an entity FAULTY evidence.

    An unusable declaration is treated as NO declaration and reported the same
    way, deliberately. Partially applying a list with a typo in it would leave
    an author reading a posterior computed against a floor they did not write
    and cannot see; the stamp says the floor was the engine's, which is then
    true. So `[critical, hihg]` falls back and discloses, rather than quietly
    becoming `[critical]`.
    """
    known = {member.value.upper() for member in Severity}
    declared = (getattr(model, "causal", None) or {}).get("evidence_severity")
    if not isinstance(declared, (list, tuple)) or not declared:
        return DEFAULT_EVIDENCE_SEVERITIES, False
    asked = {str(value).strip().upper() for value in declared}
    if not asked or not asked <= known:
        return DEFAULT_EVIDENCE_SEVERITIES, False
    return frozenset(asked), True


def evidence_from(session, graph: CausalGraph,
                  severities: Optional[FrozenSet[str]] = None
                  ) -> Tuple[Dict[str, int], List[str]]:
    """`(observed, unobserved)` from the last check.

    An entity in `not_checked` is left OUT, not set clean. Reporting the list
    is half the answer: a posterior computed with six of ten nodes unobserved
    is a different claim from one computed with all ten.

    `severities` is the floor above which a finding makes an entity FAULTY.
    Default when the caller supplies none, which is the shape this function had
    before the floor was declarable at all.
    """
    result = getattr(session, "_last_result", None)
    if result is None:
        return {}, list(graph.nodes)

    faulty: Set[str] = set()
    for problem in list(getattr(result, "problems", ()) or ()) + \
            list(getattr(result, "warnings", ()) or ()):
        severity = getattr(getattr(problem, "severity", None), "value", "")
        if str(severity).upper() in (severities or DEFAULT_EVIDENCE_SEVERITIES):
            faulty.add(str(getattr(problem, "entity_id", "")))

    declined: Set[str] = set()
    for record in getattr(result, "not_evaluated", ()) or ():
        entity_id = str(getattr(record, "entity_id", "") or "")
        if entity_id:
            declined.add(entity_id)

    observed: Dict[str, int] = {}
    unobserved: List[str] = []
    for node in graph.nodes:
        if node in faulty:
            observed[node] = 1
        elif node in declined:
            unobserved.append(node)
        else:
            observed[node] = 0
    return observed, unobserved


def _surgery(graph: CausalGraph, do: Dict[str, int]) -> CausalGraph:
    """Cut the incoming edges of every intervened node. THIS is the difference
    between `do(x)` and observing x, and the reason a hypothetical cannot be
    answered by conditioning."""
    cut = CausalGraph(
        nodes=list(graph.nodes),
        parents={n: ([] if n in do else list(p))
                 for n, p in graph.parents.items()},
        weights={e: w for e, w in graph.weights.items() if e[1] not in do},
        latents={e: v for e, v in graph.latents.items() if e[1] not in do},
        entity_type=dict(graph.entity_type))
    return cut


def _relevant_edges(graph: CausalGraph, query: Query,
                    observed: Dict[str, int]) -> List[Tuple[str, str]]:
    """Edges the answer can depend on: those among the target, the evidence,
    and everything upstream of either. Conservative on purpose -- naming too
    many edges makes a refusal noisier, naming too few makes it wrong."""
    relevant = {query.target} | set(observed) | set(query.do)
    for node in list(relevant):
        relevant |= graph.ancestors(node)
    return [edge for edge in graph.weights
            if edge[0] in relevant and edge[1] in relevant]


def _open_backdoor_latent(graph: CausalGraph, query: Query) -> Optional[str]:
    """A declared latent on an edge into the target's ancestry, under an
    intervention. Only a latent can make this unidentifiable here: everything
    else in the subgraph is observed by construction."""
    if not query.do:
        return None
    reachable = {query.target} | graph.ancestors(query.target)
    for (source, target), latent in graph.latents.items():
        if target in reachable or source in reachable:
            return latent
    return None


def _factors(graph: CausalGraph) -> List[Factor]:
    out: List[Factor] = []
    for node in graph.nodes:
        parents = list(graph.parents.get(node, ()))
        if parents:
            weights = [graph.weights[(p, node)].weight for p in parents]
            out.append(noisy_or_factor(node, parents, weights,
                                       graph.leak_for(node)))
        else:
            out.append(Factor((node,), {(0,): 1.0 - ROOT_PRIOR, (1,): ROOT_PRIOR}))
    return out


def run_inference(session, query: Query,
                  report_above: Optional[float] = None) -> SubEnvelope:
    """Answer one query over the declared causal subgraph."""
    checked: Dict[str, Any] = {"queries": 1, "answered": 0, "method": "exact_ve"}
    declines: List[Decline] = []
    questions: List[Any] = []
    findings: List[Any] = []

    if session.model is None:
        return SubEnvelope("inference", {"queries": 0}, source="unavailable",
                           reason="no domain model loaded")

    graph = causal_subgraph(session.model, session.graph, session.entities)
    checked["causal_edges"] = len(graph.weights)
    checked["cpts"] = graph.sources()
    scope = {"query": query.text}

    if query.target not in graph.nodes:
        return SubEnvelope(
            "inference", checked, source="unavailable",
            reason=(f"{query.target!r} is on no edge declared "
                    f"`edge_direction: causal`"))

    loop = graph.cycle()
    if loop:
        declines.append(Decline(
            "cycle_unsupported", scope,
            detail="the declared causal edges form a loop; exact inference needs a DAG",
            evidence={"cycle": loop}))
        return SubEnvelope("inference", checked, findings, declines, questions)

    working = _surgery(graph, query.do) if query.do else graph
    latent = _open_backdoor_latent(working, query)
    if latent is not None:
        declines.append(Decline(
            "not_identifiable", scope,
            detail=(f"an open backdoor through the declared latent {latent!r}; "
                    f"declare an observed proxy for it, or an edge"),
            evidence={"latent": latent}))
        return SubEnvelope("inference", checked, findings, declines, questions)

    severities, floor_declared = evidence_severities(session.model)
    observed, unobserved = evidence_from(session, working, severities)
    for node in query.do:
        observed[node] = query.do[node]
    observed.pop(query.target, None)
    checked["evidence"] = len(observed)
    checked["unobserved"] = len(unobserved)
    # from here down the answer depends on WHICH severities counted
    # as faulty, so every exit below carries the disclosure. The two returns
    # above this line are refusals decided from the GRAPH alone -- a cycle, an
    # open backdoor -- and read no evidence, so stamping them would name a
    # choice that did not touch the answer.
    stamps: Tuple[str, ...] = (
        () if floor_declared else (EVIDENCE_SEVERITY_NOT_DECLARED,))

    relevant = _relevant_edges(working, query, observed)
    defaulted = sorted(f"{s}->{t}" for (s, t) in relevant
                       if working.weights[(s, t)].source == SOURCE_DEFAULT)
    if defaulted:
        declines.append(Decline(
            "cpt_missing", scope,
            detail=("declare `causal.weight` on these edges, or supply learned "
                    "weights; the engine will not spend its own number on a "
                    "path the answer depends on"),
            evidence={"edges": defaulted, "default_weight": working.weights[
                (relevant[0][0], relevant[0][1])].weight}))
        for edge in defaulted:
            questions.append(_question(
                GapType.MISSING_THRESHOLD, edge,
                "no causal weight declared on an edge the query depends on",
                f"How strongly does a fault at {edge.split('->')[0]} break "
                f"{edge.split('->')[1]}? Declare `causal.weight`."))
        return SubEnvelope("inference", checked, findings, declines, questions,
                           assumptions=stamps)

    try:
        posterior = eliminate(_factors(working), query.target, observed)
    except FactorTooWide as wide:
        declines.append(Decline(
            "treewidth_exceeded", scope,
            detail=("exact elimination needs an intermediate factor wider than "
                    "this engine will build; the graph is a DAG and the answer "
                    "is well defined, but not by this method"),
            evidence={"variable": wide.variable, "width": wide.width}))
        return SubEnvelope("inference", checked, findings, declines, questions,
                           assumptions=stamps)

    if posterior is None:
        declines.append(Decline(
            "evidence_conflict", scope,
            detail=("the declared model gives this evidence probability zero, so "
                    "there is no posterior to report -- the model and the "
                    "observations disagree"),
            evidence={"observed": len(observed)}))
        return SubEnvelope("inference", checked, findings, declines, questions,
                           assumptions=stamps)

    checked["answered"] = 1
    checked["posterior"] = round(posterior, 6)
    session.ledger.record_prediction(
        entity_id=query.target, probability=posterior,
        horizon_s=0.0, severity="medium", kind="stated")

    if report_above is None:
        # The number in this sentence was the literal `0.31` at every
        # call, beside an `evidence` key carrying the posterior the engine had
        # just computed. Measured on the example this round shipped: the
        # message read `whether 0.31 is alarming` while the answer was 0.02.
        # A decline is the engine explaining what it did NOT decide, so a
        # constant standing where its own arithmetic belongs is the one place
        # a reader has no way to catch it. Both now read the same variable.
        reported = round(posterior, 6)
        declines.append(Decline(
            "no_report_probability", scope,
            detail=(f"pass `report_above` to say which posterior is worth a "
                    f"finding; whether {reported} is alarming is a fact about "
                    f"the domain rather than about the arithmetic"),
            evidence={"posterior": reported}))
    elif posterior >= report_above:
        findings.append(_posterior_finding(
            session, working, query, posterior, observed, unobserved,
            report_above))

    return SubEnvelope("inference", checked, findings, declines, questions,
                       assumptions=stamps)


def _posterior_finding(session, graph, query, posterior, observed,
                       unobserved, report_above):
    from ..interfaces import Problem
    entity = session.entities.get(query.target)
    return Problem.from_entity(
        entity, problem_type=f"posterior:{query.target}",
        severity=Severity.HIGH if posterior >= 0.5 else Severity.MEDIUM,
        reason=f"{query.text} = {posterior:.2f}, at or above the declared "
               f"{report_above:g}",
        axiom=None,
        evidence={"posterior": round(posterior, 6),
                  "report_above": report_above,
                  "method": "exact_ve",
                  "cpt_sources": graph.sources(),
                  "evidence_set": sorted(observed),
                  "unobserved": sorted(unobserved),
                  "root_prior": ROOT_PRIOR,
                  "root_prior_source": "default",
                  "do": dict(query.do)})
