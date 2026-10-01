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

Its two refusals therefore share `not_identifiable`, ON PURPOSE: a
subject outside the causal subgraph and one at its root both lack a declared
causal edge in, and declaring one is what mends either. The reasoning is
written once, beside the member in `subenvelope.VOCABULARIES`.

WHAT IT REFUSES. It ranks only DECLARED causal ancestors. It does not search for
a cause outside the graph, does not invent an edge, and does not rank an entity
the author never connected -- the same refusal `infer` makes, for the same
reason: an engine that proposed causes nobody declared would be doing the
inference this project removed from `role:` and from flow direction.

TIME, AND THE READING THAT WOULD CHANGE THE ANSWER. A finding is
found at an instant, and a cause some declared hops upstream acted earlier by
the dead times declared along the way. So when a causal edge DECLARES a
`propagation_delay_s`, every entity upstream of the finding is read at the
finding's instant minus the dead times summed along its path, on a scratch
copy of the session the live one never sees, and the ranking rests on that
aligned evidence. Measured on a pump feeding a tank feeding a basin, 60 s per
edge: a tank fault one delay back, cleared by the finding's instant, put the
pump first (0.808 against the tank's 0.415), where read at the finding the tank
led (0.415 against 0.010). Only a declared delay moves a read; the engine's own
60 s, which a transition falls back to, would put a monthly reading on the
month before.

`evidence_needed` stays each candidate's first declared reading. What the
ranking itself answers is `most_discriminating`: the one entity whose reading
would move it most, weighed by the model's own chance of each outcome where
strengths are declared, and by the shape of the declared graph where none are
-- the entity on every declared path from the most candidates, stamped as the
assumption it is. On the same chain it names the tank, whose faulty reading
reverses the order.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from ..assumptions import (ASSUMPTION_STAMPS, EVIDENCE_READ_AT_DECLARED_DELAY,
                           FAULTS_VISIBLE_ALONG_CHANNELS, READ_AT_DEAD_TIME,
                           READ_AT_EACH_PATH_DELAY, TIME_COURSE_NOT_DECLARED)
from ..clock import now_utc
from ..subenvelope import Decline, SubEnvelope
from ..types import (DEFAULT_CAUSAL_MAX_HOPS, Severity,
                     read_causal_max_hops)
from .causal import SOURCE_DEFAULT, CausalGraph, causal_subgraph
from .runner import (Evidence, Query, _factors, _open_backdoor_latent,
                     _own_severity, _relevant_edges, _surgery, evidence_from,
                     evidence_severities, run_inference)
from .ve import FactorTooWide, eliminate

#: How far upstream a hypothesis reaches when the model declares no
#: `causal.max_hops:`. BOUNDED, and the bound is the point: an unbounded
#: ancestor walk over a graph with a cycle does not return, and the project
#: rule is that verification stays in P. The graph's own `cycle()` check guards
#: the declaration; this guards the walk. An internal ruling made it declarable; the name
#: stays for the readers that import it.
MAX_HOPS = DEFAULT_CAUSAL_MAX_HOPS

#: How far before an instant a past reading is looked for: the replay module's
#: own span, reported beside every shifted read rather than hidden in it.
READ_LOOKBACK = timedelta(days=30)

#: A walk's summary: the dead time declared along it, whether an edge on it
#: declared none, and whether one declared a time constant.
_Walk = Tuple[float, bool, bool]


def _ancestors(graph: CausalGraph, node: str, max_hops: int = MAX_HOPS
               ) -> List[Tuple[str, int, List[str]]]:
    """`(node, hops, path)` upstream of `node`, nearest first, each reported
    once with the first shortest path the walk found, as `source->target`
    edges from the cause down to `node`."""
    seen: Set[str] = {node}
    via: Dict[str, List[str]] = {node: []}
    out: List[Tuple[str, int, List[str]]] = []
    frontier = [node]
    for hop in range(1, max_hops + 1):
        nxt: List[str] = []
        for current in frontier:
            for parent in graph.parents.get(current, ()) or ():
                if parent in seen:
                    continue
                seen.add(parent)
                via[parent] = [f"{parent}->{current}"] + via[current]
                out.append((parent, hop, via[parent]))
                nxt.append(parent)
        if not nxt:
            break
        frontier = nxt
    return out


def _walks(graph: CausalGraph, subject: str, max_hops: int
           ) -> Dict[str, Set[_Walk]]:
    """Per upstream entity, the distinct summaries of every walk of at most
    `max_hops` declared causal edges down to `subject`.

    Layered, never recursive, and bounded by the hop count, so a cycle in the
    declaration costs at most `max_hops` layers. An edge declaring no dead time
    adds nothing and marks its walk; the ENGINE'S dead time is never added.
    """
    found: Dict[str, Set[_Walk]] = {}
    level: Dict[str, Set[_Walk]] = {subject: {(0.0, False, False)}}
    for _hop in range(max_hops):
        nxt: Dict[str, Set[_Walk]] = {}
        for child, summaries in level.items():
            for parent in graph.parents.get(child, ()) or ():
                delay = graph.delays.get((parent, child))
                tau = graph.time_constants.get((parent, child))
                for dead, undeclared, lagged in summaries:
                    nxt.setdefault(parent, set()).add(
                        (dead + (delay or 0.0), undeclared or delay is None,
                         lagged or bool(tau)))
        for parent, summaries in nxt.items():
            found.setdefault(parent, set()).update(summaries)
        if not nxt:
            break
        level = nxt
    return found


def _readable_properties(model, entity_type: str) -> List[str]:
    """What the model says can be READ on this type, in declared order.

    A RELATIONSHIP INDICATOR IS NOT A READING. It declares an edge an
    entity must have, which CONNECTIVITY checks against the graph, and nobody
    takes a value of it. Returned here, it was named as the reading a ranking
    rests on and as each candidate's `evidence_needed` wherever a type lists a
    relation first: a finding one hop up named `<entity>.<relation>` while the
    entity declares values anyone can read. Skipped by its declared type, so no
    domain decides it.
    """
    indicators = (getattr(model, "indicators", None) or {}).get(entity_type) or []
    names: List[str] = []
    for indicator in indicators:
        name = getattr(indicator, "name", None)
        kind = getattr(indicator, "indicator_type", None)
        if isinstance(indicator, dict):
            name = indicator.get("name") if name is None else name
            kind = indicator.get("type") if kind is None else kind
        if str(getattr(kind, "value", kind) or "").lower() == "relationship":
            continue
        if name:
            names.append(str(name))
    return names


def _test_action(model, entity_type: str) -> Optional[str]:
    """A declared action that applies to this type, or None.

    NAMED, NEVER INVENTED. An engine that suggested an action nobody declared
    would be recommending a thing it cannot know is safe, on a system it cannot
    see. `None` here means the model declares no way to test this candidate,
    which is a fact about the model and is worth reporting as one.

    ASKED THE WAY THE ACTION VERBS ASK. This matched `applies_to`
    against the type exactly, so a template declared for a parent type, or one
    naming no type, was never named for a subtype -- while `file_action` and
    `plan` applied it there through `actions.applies()`. Measured: a
    `SmallPump extends Pump` candidate got `None` for a `Pump` template. It
    reads the templates the action verbs accept, too, so a malformed one the
    verbs would refuse is not offered as a test. The first in declaration order
    is named, as before.
    """
    from ..twin.actions import applies, load_templates
    templates, _refused = load_templates(model)
    lineage = getattr(model, "lineage", None)
    for name, template in templates.items():
        if applies(template, entity_type, lineage):
            return name
    return None


def _worst(severities: Sequence[Optional[str]]) -> Optional[str]:
    """The most urgent of several severities, by the order `_own_severity`
    uses, or None when none was read."""
    worst: Optional[Severity] = None
    order = tuple(Severity)
    for raw in severities:
        if raw is None:
            continue
        try:
            severity = Severity(str(raw).lower())
        except ValueError:
            continue
        if worst is None or ((severity.priority_score, order.index(severity))
                             < (worst.priority_score, order.index(worst))):
            worst = severity
    return None if worst is None else worst.value


def _states_at(session: Any, graph: CausalGraph, at: datetime,
               severities, check: Callable[[Any], Any]
               ) -> Dict[str, Tuple[Optional[int], Optional[str], bool]]:
    """Each causal node as a check at `at` saw it: `(state, severity, unread)`.

    ON A SCRATCH COPY. The live session's entities, ledger, case book and last
    result are never touched: an explanation that rewrote the state it explains
    would change the next answer by asking this one. Every property the model
    reads is set to its last reading at or before `at`, within `READ_LOOKBACK`,
    and REMOVED where there is none -- a present value read as a past one is
    the invented time this function exists to avoid.

    `check` is the verb itself, handed down by `api.hypothesize`: this module
    sits below the API and does not import it, so the package keeps one
    direction of dependency.
    """
    from ..clock import as_of
    from ..residual.predict_vs_mirror import PredictionLedger

    scratch = copy.copy(session)
    scratch.entities = {key: copy.deepcopy(value)
                        for key, value in session.entities.items()}
    scratch.ledger = PredictionLedger()
    readable = session.readable_properties()
    derived = {etype: {spec.property_name or spec.name for spec in specs
                       if getattr(spec, "derived", None)}
               for etype, specs in (session.model.indicators or {}).items()}
    unread: Set[str] = set()
    for entity in scratch.entities.values():
        names = readable.get(entity.type, set()) - derived.get(entity.type, set())
        observations = session.history.get_observations(
            entity.id, at - READ_LOOKBACK, at)
        restored = 0
        for name in names:
            latest = None
            for observation in observations:
                if observation.property_name == name and (
                        latest is None or observation.timestamp > latest.timestamp):
                    latest = observation
            if latest is None:
                entity.properties.pop(name, None)
            else:
                entity.properties[name] = latest.value
                restored += 1
        if names and not restored:
            unread.add(entity.id)
    with as_of(at):
        check(scratch)
    observed, _unobserved = evidence_from(scratch, graph, severities)
    return {node: (observed.get(node), _own_severity(scratch, node),
                   node in unread)
            for node in graph.nodes}


def _aligned_evidence(session: Any, graph: CausalGraph, subject: str,
                      walks: Dict[str, Set[_Walk]], anchor: datetime,
                      severities, check: Callable[[Any], Any]
                      ) -> Tuple[Evidence, Dict[str, List[str]], List[Decline]]:
    """The evidence with every shifted entity read at its declared delays.

    An entity reached by walks of unequal dead time is read at each, and is
    FAULTY if any reading was: a fault at any of those instants could have
    reached the finding by its own path. It is left UNOBSERVED when no instant
    gave a definite answer, and `insufficient_samples` names it when no
    instant held a reading at all.
    """
    observed, unobserved = evidence_from(session, graph, severities)
    severity = {node: _own_severity(session, node) for node in graph.nodes}
    shifts = {node: sorted({walk[0] for walk in summaries})
              for node, summaries in walks.items()}
    instants = sorted({dead for dead_times in shifts.values()
                       for dead in dead_times if dead > 0})
    states = {dead: _states_at(session, graph,
                               anchor - timedelta(seconds=dead), severities,
                               check)
              for dead in instants}
    live = dict(observed)
    left_out = set(unobserved)
    read_at: Dict[str, List[str]] = {}
    declines: List[Decline] = []
    for node, dead_times in sorted(shifts.items()):
        if node == subject or node not in graph.nodes \
                or not any(dead > 0 for dead in dead_times):
            continue
        readings: List[Tuple[Optional[int], Optional[str], bool]] = []
        for dead in dead_times:
            if dead > 0:
                readings.append(states[dead][node])
            else:
                readings.append((None if node in left_out else observed.get(node),
                                 severity.get(node), False))
        read_at[node] = [(anchor - timedelta(seconds=dead)).isoformat()
                         for dead in dead_times]
        if any(state == 1 for state, _sev, _unread in readings):
            value: Optional[int] = 1
        elif all(state == 0 for state, _sev, _unread in readings):
            value = 0
        else:
            value = None
        if value is None:
            live.pop(node, None)
            left_out.add(node)
            if all(unread for _state, _sev, unread in readings):
                declines.append(Decline(
                    "insufficient_samples", {"entity": node},
                    detail=(f"`{node}` has no reading at the instants its "
                            f"declared delays imply, so it was left out of the "
                            f"evidence rather than read at the finding's instant"),
                    evidence={"read_at": read_at[node],
                              "lookback_s": READ_LOOKBACK.total_seconds()}))
        else:
            live[node] = value
            left_out.discard(node)
        severity[node] = _worst([sev for _state, sev, _unread in readings])
    return (Evidence(live, tuple(sorted(left_out)), severity), read_at,
            declines)


def _do_answer(graph: CausalGraph, subject: str, cause: str,
               observed: Dict[str, int]) -> Optional[float]:
    """P(subject faulty | do(cause faulty)), or None where `infer` would decline.

    Computed here and not through `run_inference`, which files every answered
    posterior into the ledger: a value the caller forced is not a prediction
    about the world. None for a cycle, an open backdoor, a weight on the path
    that is the engine's default, or elimination too wide -- the ranking's own
    declines already say which.
    """
    query = Query(target=subject, do={cause: 1})
    working = _surgery(graph, query.do)
    if working.cycle() or _open_backdoor_latent(working, query) is not None:
        return None
    evidence = {node: value for node, value in observed.items() if node != subject}
    evidence[cause] = 1
    if any(working.weights[edge].source == SOURCE_DEFAULT
           for edge in _relevant_edges(working, query, evidence)):
        return None
    try:
        answer = eliminate(_factors(working), subject, evidence)
    except FactorTooWide:
        return None
    return None if answer is None else round(answer, 6)


def _reading(model, graph: CausalGraph, node: str) -> Dict[str, Any]:
    properties = _readable_properties(model, graph.entity_type.get(node, ""))
    return {"entity": node,
            "reading": f"{node}.{properties[0]}" if properties else None}


def _by_information(graph: CausalGraph, subject: str,
                    ranked: List[Dict[str, Any]], observed: Dict[str, int],
                    model) -> Optional[Dict[str, Any]]:
    """The entity whose reading would move the ranking most, by the strengths.

    Each outcome of the reading is weighed by the model's own probability of
    it given everything else, and the move is the summed change in the
    candidates' posteriors. A reading already taken counts only through the
    outcome it did NOT give. None when elimination is too wide or no reading
    moves anything, and the caller then answers from the graph's shape.
    """
    causes = [row["cause"] for row in ranked]
    hops = {row["cause"]: row["hops"] for row in ranked}
    top = ranked[0]["cause"]
    pool: List[str] = []
    for node in causes + [parent for cause in causes
                          for parent in graph.parents.get(cause, ())] + [
            child for child in graph.nodes
            if any(cause in graph.parents.get(child, ()) for cause in causes)]:
        if node != subject and node not in pool:
            pool.append(node)
    factors = _factors(graph)
    best: Optional[Tuple[float, str, List[str]]] = None
    try:
        # THE MOVE IS MEASURED AGAINST AN UNROUNDED BASE. The rows
        # carry each posterior rounded to six places; set against unrounded
        # answers, the rounding itself read as a move above the guard, so a
        # reading that moves nothing could be named with `expected_change: 0.0`.
        base: Dict[str, float] = {}
        for row in ranked:
            answer = eliminate(factors, row["cause"], {
                key: value for key, value in observed.items() if key != row["cause"]})
            base[row["cause"]] = row["posterior"] if answer is None else answer
        for node in pool:
            rest = {key: value for key, value in observed.items() if key != node}
            chance = eliminate(factors, node, rest)
            if chance is None:
                continue
            moved, flips = 0.0, []
            for value, weight in ((1, chance), (0, 1.0 - chance)):
                if observed.get(node) == value or weight <= 0.0:
                    continue
                after: Dict[str, float] = {}
                for cause in causes:
                    if cause == node:
                        after[cause] = base[cause]
                        continue
                    evidence = {key: val for key, val in observed.items()
                                if key != cause}
                    evidence[node] = value
                    answer = eliminate(factors, cause, evidence)
                    after[cause] = base[cause] if answer is None else answer
                moved += weight * sum(abs(after[cause] - base[cause])
                                      for cause in causes)
                leader = min(causes, key=lambda cause: (-after[cause],
                                                        hops[cause], cause))
                if leader != top:
                    flips.append("faulty" if value else "clean")
            if best is None or moved > best[0] + 1e-12:
                best = (moved, node, flips)
    except FactorTooWide:
        return None
    # A move the reported six places would print as 0.0 is not a reason to
    # name a reading; the caller then answers from the graph's shape.
    if best is None or round(best[0], 6) <= 0.0:
        return None
    moved, node, flips = best
    return dict(_reading(model, graph, node), basis="strengths",
                expected_change=round(moved, 6), changes_top_if=flips)


def _by_structure(graph: CausalGraph, subject: str,
                  ranked: List[Dict[str, Any]], max_hops: int,
                  model) -> Dict[str, Any]:
    """The candidate lying on every declared path from the most candidates.

    With no strength declared nothing can be weighed, and the question left is
    which reading splits the candidates most evenly: a candidate that reads
    clean rules out every cause whose only way down to the finding runs through
    it, on the stamped assumption that a fault shows along its channel.
    """
    causes = [row["cause"] for row in ranked]
    hops = {row["cause"]: row["hops"] for row in ranked}

    def reached_avoiding(blocked: str) -> Set[str]:
        seen, frontier = {subject}, [subject]
        for _hop in range(max_hops):
            nxt = []
            for current in frontier:
                for parent in graph.parents.get(current, ()) or ():
                    if parent != blocked and parent not in seen:
                        seen.add(parent)
                        nxt.append(parent)
            if not nxt:
                break
            frontier = nxt
        return seen

    best: Optional[Tuple[Tuple[int, int, int], str, int]] = None
    for node in causes:
        reached = reached_avoiding(node)
        covered = 1 + sum(1 for cause in causes
                          if cause != node and cause not in reached)
        key = (min(covered, len(causes) - covered), covered, -hops[node])
        if best is None or key > best[0]:
            best = (key, node, covered)
    _key, node, covered = best
    return dict(_reading(model, graph, node), basis="structure",
                splits=[covered, len(causes) - covered])


def hypothesize(session: Any, entity_id: str, *,
                report_above: Optional[float] = None,
                check: Optional[Callable[[Any], Any]] = None
                ) -> Tuple[SubEnvelope, List[Dict[str, Any]], Dict[str, Any]]:
    """Rank the declared causes of a finding on `entity_id`.

    Returns the sub-envelope, the ranked candidates and what the ranking
    carries beside them -- `most_discriminating` and, when a declared delay
    moved a read, `read_at` -- which the caller attaches. The shape `entail`
    already uses, because `SubEnvelope` is frozen and a verb that mutated one
    would be the only thing here that did.

    Each candidate carries the posterior `infer` computes for it, the path it
    was reached by, the reading that would discriminate it, the declared action
    that could test it, and what forcing it faulty would make of the finding --
    or an honest `None` where the model offers none of these.

    `check` is the `check` verb, which reading a cause at its declared delay
    runs on a scratch session; a caller that passes none cannot ask for that,
    and a model declaring a delay then raises rather than being read at the
    finding's instant as though none were declared.
    """
    extras: Dict[str, Any] = {"most_discriminating": None}
    hop_bound = read_causal_max_hops(getattr(session.model, "causal", None)
                                     if getattr(session, "model", None)
                                     is not None else None).hops
    checked: Dict[str, Any] = {"candidates": 0, "ranked": 0, "max_hops": hop_bound}
    declines: List[Decline] = []

    if getattr(session, "model", None) is None:
        return (SubEnvelope("inference", {"candidates": 0}, source="unavailable",
                            reason="no domain model loaded"), [], extras)

    graph = causal_subgraph(session.model, session.graph, session.entities)
    if entity_id not in graph.nodes:
        declines.append(Decline(
            "not_identifiable", {"entity": entity_id},
            detail=(f"`{entity_id}` is not in the declared causal subgraph, so "
                    f"there is nothing upstream of it to rank. An edge enters "
                    f"that graph by declaring `edge_direction: causal`; this "
                    f"verb does not search for one.")))
        return SubEnvelope("inference", checked, not_checked=declines), [], extras

    candidates = _ancestors(graph, entity_id, hop_bound)
    checked["candidates"] = len(candidates)
    beyond = len(graph.ancestors(entity_id) - {entity_id}) - len(candidates)
    if beyond > 0:
        # A RANKING CUT SHORT IS NEVER READ AS WHOLE. Declared causes
        # past the bound are not ranked, and the count says how many.
        checked["beyond_bound"] = beyond
        declines.append(Decline(
            "depth_exceeded", {"entity": entity_id},
            detail=(f"{beyond} declared cause(s) of `{entity_id}` lie more than "
                    f"{hop_bound} causal hop(s) upstream and were not ranked; "
                    f"`causal.max_hops` raises the bound"),
            evidence={"max_hops": hop_bound, "beyond": beyond}))
    if not candidates:
        declines.append(Decline(
            "not_identifiable", {"entity": entity_id},
            detail=(f"`{entity_id}` has no declared causal ancestor within "
                    f"{hop_bound} hops, so the model offers nothing that could "
                    f"explain a finding on it. That is a statement about the "
                    f"model and not about the system.")))
        return SubEnvelope("inference", checked, not_checked=declines), [], extras

    # WHEN EACH CAUSE IS READ. Only a declared dead time moves a
    # read, and a model declaring none gets exactly the evidence it always did.
    severities, _declared, _unusable = evidence_severities(session.model)
    walks = _walks(graph, entity_id, hop_bound)
    aligned = any(walk[0] > 0 for summaries in walks.values() for walk in summaries)
    stamps: set = set()
    evidence: Optional[Evidence] = None
    read_at: Dict[str, List[str]] = {}
    anchor = getattr(session, "_last_checked_at", None) or now_utc()
    if aligned:
        if check is None:
            raise TypeError("hypothesize reads a cause at its declared delay "
                            "through the check verb; pass check=")
        evidence, read_at, read_declines = _aligned_evidence(
            session, graph, entity_id, walks, anchor, severities, check)
        declines.extend(read_declines)
        stamps.add(EVIDENCE_READ_AT_DECLARED_DELAY)
        cone = [walk for summaries in walks.values() for walk in summaries]
        if any(undeclared for _dead, undeclared, _lagged in cone):
            stamps.add(TIME_COURSE_NOT_DECLARED)
        if any(dead > 0 and lagged for dead, _undeclared, lagged in cone):
            stamps.add(READ_AT_DEAD_TIME)
        if any(len({walk[0] for walk in summaries}) > 1
               for summaries in walks.values()):
            stamps.add(READ_AT_EACH_PATH_DELAY)
        extras["read_at"] = {"anchor": anchor.isoformat(),
                             "lookback_s": READ_LOOKBACK.total_seconds(),
                             "entities": read_at}

    ranked: List[Dict[str, Any]] = []
    # THE STAMPS OF EVERY INFERENCE THIS RANKING RESTS ON. Each
    # candidate is scored by `run_inference`, which stamps the defaults it
    # applied; this verb used to drop them all, so a ranking computed against
    # the engine's evidence floor carried no `evidence_severity_not_declared`
    # while the verb's own docstring told the reader to check for it.
    #: AND THEIR DECLINES, which the stamps' fix left behind. A
    #: model declaring causal edges and no strengths makes `infer` decline
    #: `cpt_missing`, by name; this verb ran that same inference per candidate
    #: and returned each cause with `posterior: null` beside an EMPTY
    #: `not_checked` -- a ranking with no numbers and no word on why. Found by
    #: the first vertical to declare fault channels without strengths.
    seen: set = set()
    #: THE QUESTIONS THE INFERENCES RAISE. Each candidate's inference
    #: asks, per edge it needed and nobody gave a strength, how strongly a
    #: fault there breaks the next node; `infer` returns that question and this
    #: verb dropped it, so a ranking under `cpt_missing` said what was missing
    #: and never asked for it. Once per edge, however many candidates share it.
    questions: List[Any] = []
    asked: set = set()
    for node, hops, path in candidates:
        dead_times = sorted({walk[0] for walk in walks.get(node, ())})
        # A cause read only in the past is a claim about that instant, and the
        # ledger grades it there; one read at the finding is a claim about now.
        when = (anchor - timedelta(seconds=dead_times[0])
                if aligned and dead_times and dead_times[0] > 0 else None)
        sub = run_inference(session, Query(target=node), report_above=None,
                            evidence=evidence, predicted_at=when)
        payload = sub.to_dict()
        checked_here = payload.get("checked") or {}
        posterior = checked_here.get("posterior")
        stamps.update(payload.get("assumptions") or ())
        reasons: set = set()
        for decline in getattr(sub, "not_checked", ()) or ():
            if decline.reason == "no_report_probability":
                # This verb asks each inference for its posterior with no
                # report line, on purpose, and applies its own `report_above`
                # below; the inference's word on that is about the call, not
                # about the cause.
                continue
            reasons.add(decline.reason)
            key = (decline.reason, tuple(sorted(
                (str(k), str(v)) for k, v in (decline.scope or {}).items())))
            if key not in seen:
                seen.add(key)
                declines.append(decline)
        for question in getattr(sub, "questions", ()) or ():
            gap = getattr(question, "gap", None)
            gap_type = getattr(gap, "gap_type", None)
            asked_key = (getattr(gap_type, "value", gap_type),
                         getattr(gap, "location", None))
            if asked_key not in asked:
                asked.add(asked_key)
                questions.append(question)
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
            # WHAT THAT READING ALREADY SAID, when it was taken. The
            # posterior above leaves the candidate's own reading out, which is
            # what makes it a ranking at all; without this row a feeder READ
            # CLEAN came back first at 0.962 with its own meter as the evidence
            # needed, sending an operator to take a reading already taken.
            # `None` means unread -- the case `evidence_needed` is written for.
            "own_reading": checked_here.get("target_reading"),
            "test_action": _test_action(session.model, entity_type),
            # why this cause's inference answered less than a
            # number, in the vocabulary `not_checked` above uses. Empty when
            # it declined nothing.
            "declined": sorted(reasons),
            # the declared edges this cause was reached by, the
            # instants it was read at when a delay moved it, and what forcing
            # it faulty makes of the finding.
            "path": path,
            "read_at": read_at.get(node),
            "do_would_answer": None,
        })

    # Nearest first on a tie, because a cause two hops away explains a finding
    # only through one that is nearer, and asking about the nearer one first is
    # how an operator narrows rather than guesses.
    ranked.sort(key=lambda row: (-(row["posterior"] or 0.0), row["hops"],
                                 row["cause"]))
    checked["ranked"] = len(ranked)

    observed = (dict(evidence.observed) if evidence is not None
                else evidence_from(session, graph, severities)[0])
    for row in ranked:
        if row["posterior"] is not None:
            row["do_would_answer"] = _do_answer(graph, entity_id, row["cause"],
                                                observed)
    extras["most_discriminating"] = _most_discriminating(
        session, graph, entity_id, ranked, observed, hop_bound, stamps)

    if report_above is not None:
        ranked = [r for r in ranked
                  if r["posterior"] is not None and r["posterior"] >= report_above]
        checked["reported"] = len(ranked)

    # In the vocabulary's own order, so one set of findings always reports one
    # list; a stamp outside the published tuple sorts last rather than vanishing.
    order = {stamp: i for i, stamp in enumerate(ASSUMPTION_STAMPS)}
    assumptions = tuple(sorted(stamps, key=lambda s: (order.get(s, len(order)), s)))
    return (SubEnvelope("inference", checked, not_checked=declines,
                        questions=questions, assumptions=assumptions),
            ranked, extras)


def _most_discriminating(session: Any, graph: CausalGraph, subject: str,
                         ranked: List[Dict[str, Any]], observed: Dict[str, int],
                         max_hops: int, stamps: set) -> Optional[Dict[str, Any]]:
    """The one reading that would change this ranking most, and how it was
    chosen: by the strengths where every candidate has a posterior, by the
    declared graph's shape where none can, and the candidate itself where
    there is only one."""
    if not ranked:
        return None
    if len(ranked) == 1:
        return dict(_reading(session.model, graph, ranked[0]["cause"]),
                    basis="only_candidate")
    if all(row["posterior"] is not None for row in ranked):
        found = _by_information(graph, subject, ranked, observed, session.model)
        if found is not None:
            return found
    stamps.add(FAULTS_VISIBLE_ALONG_CHANNELS)
    return _by_structure(graph, subject, ranked, max_hops, session.model)
