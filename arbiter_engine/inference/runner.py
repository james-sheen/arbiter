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

from ..assumptions import (CLEAN_BESIDE_DECLINES_NO_READING_CURES,
                           EVIDENCE_SEVERITY_NOT_DECLARED,
                           EVIDENCE_SEVERITY_UNUSABLE, LEAK_NOT_DECLARED,
                           ROOT_PRIOR_NOT_DECLARED, TARGET_READING_SET_ASIDE)
from ..subenvelope import Decline, SubEnvelope
from ..twin.gap import GAP_CONFIDENCE_THRESHOLDS as _GAP_WEIGHT
from ..twin.topology import GapType, TopologyGap, TopologyQuestion
from ..types import (DEFAULT_CAUSAL_ROOT_PRIOR, Axiom, NotEvaluatedReason,
                     Severity, decline_remedy, read_severity_floor)
from .causal import SOURCE_DEFAULT, CausalGraph, causal_subgraph
from .ve import Factor, FactorTooWide, eliminate, noisy_or_factor

__all__ = ["Query", "Evidence", "run_inference", "ROOT_PRIOR"]

#: The prior on a root cause with no parents and no evidence, when the model
#: declares none. a model declares it under `causal.root_prior` now,
#: and an answer resting on this default is stamped `root_prior_not_declared`.
#: Until then it was reported only in the evidence of a posterior FINDING, and
#: this comment named a `priors` key that never existed. Kept under its
#: published name; the graph carries the prior in effect.
ROOT_PRIOR = DEFAULT_CAUSAL_ROOT_PRIOR


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


@dataclass(frozen=True)
class Evidence:
    """What each node of the causal subgraph read, for a caller that did not
    take it from the last `check()`: `observed` maps a node to 1 (faulty) or 0
    (clean), `unobserved` lists the nodes left out, and `severity` is each
    node's own worst finding at the instant it was read, for `target_reading`.
    """
    observed: Dict[str, int] = field(default_factory=dict)
    unobserved: Tuple[str, ...] = ()
    severity: Dict[str, Optional[str]] = field(default_factory=dict)
    #: what each node's checks said at the instant it was read, as
    #: `entity_evidence` gives it. Empty for a caller that built the evidence
    #: itself; a node absent here is summarised from the last check.
    summaries: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def _question(gap_type, location, description, text):
    return TopologyQuestion(
        gap=TopologyGap(gap_type=gap_type, location=location,
                        description=description),
        question_text=text, priority=_GAP_WEIGHT.get(gap_type, 0.5),
        context_path=[])


#: The floor this engine uses when a model declares none. It was a literal in
#: the loop below and said so nowhere -- and the stamp it emits.
DEFAULT_EVIDENCE_SEVERITIES: FrozenSet[str] = frozenset({"HIGH", "CRITICAL"})


def evidence_severities(model) -> Tuple[FrozenSet[str], bool, bool]:
    """`(floor, declared, unusable)` -- which severities make evidence FAULTY.

    An unusable declaration falls back to the engine's floor and is NOT
    partially applied. Applying the half that parsed would leave an author
    reading a posterior computed against a floor they did not write and cannot
    see; `[critical, hihg]` therefore becomes the default rather than quietly
    becoming `[critical]`.

    `unusable` SEPARATES TRYING FROM NOT TRYING. Until a later change this returned
    two values and an author who mistyped a severity got the same bare
    `evidence_severity_not_declared` as one who declared nothing -- the reading
    an outside review reproduced was *not declared*, therefore *my file did not
    load*, and there was no thread to pull. The floor is still the engine's in
    both cases, so the first stamp stays; the second says a declaration was
    refused, and `model_describe` names the word.
    """
    read = read_severity_floor(getattr(model, "causal", None))
    if read.floor:
        return read.floor, True, False
    # `present` can only be True here if the declaration was unusable -- a
    # usable one returned above with a non-empty floor.
    return DEFAULT_EVIDENCE_SEVERITIES, False, read.present


def entity_evidence(session, entity_id: str,
                    severities: Optional[FrozenSet[str]] = None,
                    result: Any = None) -> Dict[str, Any]:
    """What the last check said about one entity, as the inference reads it.

    The inference used to infer an entity's state from the records
    that were ABSENT: faulty on a finding at the evidence floor, left out on a
    decline of any reason, clean otherwise -- so an entity nothing was checked
    on read clean, and one carrying a decline no reading could cure (a
    threshold nobody declared) could never read clean at all. On the
    consulting model that was every unit.

    `state` is one of five:

    - `faulty` -- a finding at the evidence floor;
    - `deviating` -- a finding below it, and none at it;
    - `clean` -- no finding, at least one check ran, and nothing is
      outstanding that a reading would cure or that the engine failed at;
    - `partial` -- no finding, at least one check ran, and something a
      reading would cure, or the engine failed at, is outstanding;
    - `unread` -- no finding, and nothing ran.

    A check is one declared axiom on one declared indicator; it ran unless it
    declined, and `partially_checked` counts as ran, because part of it did.
    `looked` is `[ran, declared]`. `needs` names each reading the check could
    not take, with its reason: the declines a reading would cure, and the
    engine's own. `declines_no_reading_cures` lists the reasons that stood
    beside a reading without blocking it -- the declines only a declaration
    would cure, or that nobody owes. Counting those as clean is the ruling
    the posterior stamps.
    """
    result = result if result is not None else getattr(session, "_last_result", None)
    floor = {str(s).upper() for s in (severities or DEFAULT_EVIDENCE_SEVERITIES)}
    findings: Dict[str, int] = {}
    at_floor = False
    if result is not None:
        for problem in list(getattr(result, "problems", ()) or ()) + \
                list(getattr(result, "warnings", ()) or ()):
            if str(getattr(problem, "entity_id", "")) != entity_id:
                continue
            kind = str(getattr(problem, "problem_type", "") or "")
            findings[kind] = findings.get(kind, 0) + 1
            raw = getattr(problem, "severity", None)
            if str(getattr(raw, "value", raw)).upper() in floor:
                at_floor = True

    entity = getattr(session, "entities", {}).get(entity_id)
    declared = set()
    if entity is not None:
        model = getattr(session, "model", None)
        for spec in ((getattr(model, "indicators", None) or {}).get(entity.type) or ()):
            for axiom in getattr(spec, "relevant_axioms", None) or ():
                declared.add((str(spec.name), str(getattr(axiom, "value", axiom))))

    silent = set()
    needs: List[Dict[str, str]] = []
    beside: Set[str] = set()
    for record in (getattr(result, "not_evaluated", ()) or ()) if result is not None else ():
        if str(getattr(record, "entity_id", "") or "") != entity_id:
            continue
        reason = str(getattr(getattr(record, "reason", None), "value",
                             getattr(record, "reason", "")))
        indicator = str(getattr(record, "indicator", "") or "")
        axiom = str(getattr(getattr(record, "axiom", None), "value",
                            getattr(record, "axiom", "")))
        if reason != NotEvaluatedReason.PARTIALLY_CHECKED.value:
            silent.add((indicator, axiom))
        if decline_remedy(reason) in ("reading", "engine"):
            need = {"reading": f"{entity_id}.{indicator}" if indicator else entity_id,
                    "reason": reason}
            if need not in needs:
                needs.append(need)
        else:
            beside.add(reason)

    ran = declared - silent
    if findings:
        state = "faulty" if at_floor else "deviating"
    elif not ran:
        state = "unread"
    elif needs:
        state = "partial"
    else:
        state = "clean"
    return {"state": state,
            "severity": _own_severity_from(result, entity_id),
            "looked": [len(ran), len(declared)],
            "findings": dict(sorted(findings.items())),
            "needs": sorted(needs, key=lambda n: (n["reading"], n["reason"])),
            "declines_no_reading_cures": sorted(beside)}


def node_evidence(session, graph: CausalGraph,
                  severities: Optional[FrozenSet[str]] = None
                  ) -> Tuple[Dict[str, int], List[str], Dict[str, Dict[str, Any]]]:
    """`(observed, unobserved, summaries)` from the last check, by each node's
    `entity_evidence` state: `faulty` is 1, `clean` and `deviating` are 0,
    and `partial` and `unread` are left out.

    `deviating` counts as 0 for the reason it always has: the evidence floor
    says which findings make an entity faulty, and a finding below it does not.
    """
    result = getattr(session, "_last_result", None)
    if result is None:
        return {}, list(graph.nodes), {}
    summaries = {node: entity_evidence(session, node, severities, result)
                 for node in graph.nodes}
    observed: Dict[str, int] = {}
    unobserved: List[str] = []
    for node in graph.nodes:
        state = summaries[node]["state"]
        if state == "faulty":
            observed[node] = 1
        elif state in ("clean", "deviating"):
            observed[node] = 0
        else:
            unobserved.append(node)
    return observed, unobserved, summaries


def evidence_from(session, graph: CausalGraph,
                  severities: Optional[FrozenSet[str]] = None
                  ) -> Tuple[Dict[str, int], List[str]]:
    """`(observed, unobserved)` from the last check.

    An entity is read by what its checks said, not by which records are
    absent -- `entity_evidence` gives the rule. Reporting the list of the
    unobserved is half the answer: a posterior computed with six of ten nodes
    unobserved is a different claim from one computed with all ten.

    `severities` is the floor above which a finding makes an entity FAULTY.
    Default when the caller supplies none, which is the shape this function had
    before the floor was declarable at all.
    """
    observed, unobserved, _summaries = node_evidence(session, graph, severities)
    return observed, unobserved


#: Severity order for reporting the worst one, most urgent first. Ties in
#: `priority_score` (WARNING and MEDIUM share one) fall to declaration order, so
#: the same findings always report the same word.
_SEVERITY_ORDER: Tuple[Severity, ...] = tuple(Severity)


def _own_severity(session, entity_id: str) -> Optional[str]:
    """The most urgent severity the last check gave `entity_id`, at ANY level.

    Deliberately not filtered by the evidence floor. A panel carrying a warning
    under an engine floor of `high` counted as CLEAN, and a reader looking at
    the set-aside reading is owed both facts -- what the floor made of it and
    what the check actually said -- or *clean* reads as *nothing was found*.
    """
    return _own_severity_from(getattr(session, "_last_result", None), entity_id)


def _own_severity_from(result: Any, entity_id: str) -> Optional[str]:
    """`_own_severity` over a given check result -- the one `entity_evidence`
    was handed, which may be a check at a read instant rather than the last."""
    if result is None:
        return None
    worst: Optional[Severity] = None
    for problem in list(getattr(result, "problems", ()) or ()) + \
            list(getattr(result, "warnings", ()) or ()):
        if str(getattr(problem, "entity_id", "")) != entity_id:
            continue
        raw = getattr(problem, "severity", None)
        try:
            severity = Severity(str(getattr(raw, "value", raw)).lower())
        except ValueError:
            continue
        if worst is None or (
                (severity.priority_score, _SEVERITY_ORDER.index(severity))
                < (worst.priority_score, _SEVERITY_ORDER.index(worst))):
            worst = severity
    return None if worst is None else worst.value


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
        entity_type=dict(graph.entity_type),
        delays={e: v for e, v in graph.delays.items() if e[1] not in do},
        time_constants={e: v for e, v in graph.time_constants.items()
                        if e[1] not in do},
        root_prior=graph.root_prior,
        root_prior_declared=graph.root_prior_declared)
    return cut


def _relevant_nodes(graph: CausalGraph, query: Query,
                    observed: Dict[str, int]) -> Set[str]:
    """The target, the evidence, what is set, and everything upstream of
    them: the nodes an answer can depend on."""
    relevant = {query.target} | set(observed) | set(query.do)
    for node in list(relevant):
        relevant |= graph.ancestors(node)
    return relevant


def _relevant_edges(graph: CausalGraph, query: Query,
                    observed: Dict[str, int]) -> List[Tuple[str, str]]:
    """Edges the answer can depend on: those among the target, the evidence,
    and everything upstream of either. Conservative on purpose -- naming too
    many edges makes a refusal noisier, naming too few makes it wrong."""
    relevant = _relevant_nodes(graph, query, observed)
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
            out.append(Factor((node,), {(0,): 1.0 - graph.root_prior,
                                        (1,): graph.root_prior}))
    return out


def run_inference(session, query: Query,
                  report_above: Optional[float] = None, *,
                  evidence: Optional["Evidence"] = None,
                  predicted_at: Optional[Any] = None) -> SubEnvelope:
    """Answer one query over the declared causal subgraph.

    `evidence` replaces what the last `check()` said, for a caller
    that read the graph at other instants: `hypothesize` reads each cause at
    its declared delay. `predicted_at` is the instant the answered posterior
    is a claim about, when that is not now. Both absent, nothing changes.
    """
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

    # AN INTERVENTION ON THE TARGET IS THE ANSWER. `do(x=v)` sets x,
    # so P(x faulty | do(x=v)) is v, whatever the evidence says and however the
    # graph is wired. Until this branch the intervened value went into the
    # evidence and was then popped with the target's reading below, so the
    # surgery cut x's parents and the elimination answered for an x nobody had
    # set: measured on the specimen, `do={fdr-1: 0}` and `do={fdr-1: 1}` both
    # returned 0.984981. Answered here, BEFORE the backdoor check, because an
    # answer that reads no edge cannot be unidentifiable. Nothing is filed and
    # nothing is reported: a value the caller forced is not a prediction about
    # the world, and a finding would report the caller's own act back to them.
    if query.target in query.do:
        checked["answered"] = 1
        checked["method"] = "intervention"
        checked["posterior"] = float(query.do[query.target])
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

    severities, floor_declared, floor_unusable = \
        evidence_severities(session.model)
    if evidence is None:
        observed, unobserved, summaries = node_evidence(session, working, severities)
    else:
        observed, unobserved = dict(evidence.observed), list(evidence.unobserved)
        summaries = dict(evidence.summaries or {})
    for node in query.do:
        observed[node] = query.do[node]
    # The target's own state is left out, because conditioning on it answers 1
    # or 0 by construction. What is asked is whether EVERYTHING ELSE implicates
    # it -- and since the answer says that is what was asked.
    set_aside = observed.pop(query.target, None)
    checked["evidence"] = len(observed)
    checked["unobserved"] = len(unobserved)
    # from here down the answer depends on WHICH severities counted
    # as faulty, so every exit below carries the disclosure. The returns
    # above this line are refusals decided from the GRAPH alone -- a cycle, an
    # open backdoor -- or an intervention that fixes the answer, and read no
    # evidence, so stamping them would name a choice that did not touch it.
    stamps: Tuple[str, ...] = () if floor_declared else (
        (EVIDENCE_SEVERITY_NOT_DECLARED,)
        + ((EVIDENCE_SEVERITY_UNUSABLE,) if floor_unusable else ()))
    # RULING 2, AND IT IS STAMPED. A node whose only declines are
    # ones no reading would cure counts as clean evidence; it used to be left
    # out on any decline, and on a model with a threshold it cannot declare
    # that left every node out. The stamp names the reading the posterior took.
    if any(value == 0 and (summaries.get(node) or {}).get("declines_no_reading_cures")
           for node, value in observed.items() if node not in query.do):
        stamps = stamps + (CLEAN_BESIDE_DECLINES_NO_READING_CURES,)
    # AND WHICH READING WAS NOT USED. A target in breach answered
    # exactly as a healthy one did, with nothing on the envelope saying its own
    # reading had been excluded: measured, the supply at 9.0 kV and at 11.0 kV
    # both 0.670634. Stamped whenever the target HAD a reading, clean as well
    # as faulty -- a clean reading set aside misleads just as far, the other
    # way. `severity` is the target's own worst finding at any level, beside
    # the state the evidence floor made of it, because under the engine's floor
    # a warning counts as clean and *clean* alone would read as *nothing found*.
    target_reading: Optional[Dict[str, Any]] = None
    if set_aside is not None:
        own = (_own_severity(session, query.target) if evidence is None
               else evidence.severity.get(query.target))
        # `deviating` is a finding below the floor. It read
        # `clean`, with the severity beside it, which told a reader the floor
        # set the finding aside and left them to notice there was one.
        target_reading = {"state": ("faulty" if set_aside
                                    else "deviating" if own else "clean"),
                          "severity": own}
        checked["target_reading"] = target_reading
        stamps = stamps + (TARGET_READING_SET_ASIDE,)

    relevant = _relevant_edges(working, query, observed)
    defaulted = sorted(f"{s}->{t}" for (s, t) in relevant
                       if working.weights[(s, t)].source == SOURCE_DEFAULT)
    if defaulted:
        declines.append(Decline(
            "cpt_missing", scope,
            # this offered learned weights as a second remedy, and
            # nothing can take them: no verb accepts them and neither caller
            # fills the slot.
            detail=("declare `causal.weight` on these edges; the engine will "
                    "not spend its own number on a path the answer depends "
                    "on"),
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

    # A LEAK NOBODY DECLARED IS SPENT, AND SAID SO. The weights on
    # every edge the answer depends on are declared by this point; each node at
    # the head of one spends its leak too, and where the leak in effect is the
    # engine's 0.01 the answer rests on a number nobody wrote.
    if any(not working.leak_declared(node) for node in {t for _s, t in relevant}):
        stamps = stamps + (LEAK_NOT_DECLARED,)
    # AND A ROOT PRIOR NOBODY DECLARED. A root cause the answer
    # depends on, not observed, enters at its prior -- a node set by `do` is
    # in the evidence by now -- and where the model declares no
    # `causal.root_prior` that prior is the engine's.
    if not working.root_prior_declared and any(
            not working.parents.get(node) and node not in observed
            for node in _relevant_nodes(working, query, observed)):
        stamps = stamps + (ROOT_PRIOR_NOT_DECLARED,)

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
    # ONE CLAIM IS FILED ONCE. Every answered call filed its
    # posterior, so a walk asked twice over one check filed each candidate
    # twice, and the ledger graded the same claim as two. The same entity,
    # value, check and instant is the same claim, and is not filed again.
    filed = getattr(session, "_filed_posteriors", None)
    claim = (query.target, round(posterior, 6),
             getattr(session, "_last_checked_at", None), predicted_at)
    # AN INTERVENED POSTERIOR IS NOT A CLAIM. Under `do` the answer
    # is what the target would be with a node SET, and filing it had the ledger
    # grade a value nobody observed as a claim about now -- the rule the
    # modelling guide already states for `do_would_answer`.
    if not query.do and (filed is None or claim not in filed):
        if filed is not None:
            filed.add(claim)
        session.ledger.record_prediction(
            entity_id=query.target, probability=posterior,
            horizon_s=0.0, severity="medium", kind="stated",
            predicted_at=predicted_at)

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
            report_above, target_reading))

    return SubEnvelope("inference", checked, findings, declines, questions,
                       assumptions=stamps)


def _posterior_finding(session, graph, query, posterior, observed,
                       unobserved, report_above, target_reading=None):
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
                  # a finding travels without its envelope, so the
                  # reading it did not use travels with it.
                  "target_reading": target_reading,
                  "root_prior": graph.root_prior,
                  "root_prior_source": ("declared" if graph.root_prior_declared
                                        else "default"),
                  "do": dict(query.do)})
