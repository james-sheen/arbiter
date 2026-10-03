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
`propagation_delay_s` -- or, since 0.2.34, a `propagation_delay`, which may
name calendar months -- every entity upstream of the finding is read at the
finding's instant minus the dead times summed along its path, on a scratch
copy of the session the live one never sees, and the ranking rests on that
aligned evidence. Measured on a pump feeding a tank feeding a basin, 60 s per
edge: a tank fault one delay back, cleared by the finding's instant, put the
pump first (0.808 against the tank's 0.415), where read at the finding the tank
led (0.415 against 0.010). Only a declared delay moves a read; the engine's own
60 s, which a transition falls back to, would put a monthly reading on the
month before.

`evidence_needed` stays each candidate's first declared reading. What the
ranking itself answers is `most_discriminating`: the one reading that would
move it most, weighed by the model's own chance of each outcome where
strengths are declared.

WHERE EACH CANDIDATE STANDS. A candidate read clean screens every
cause whose only way down to the finding runs through it, on the stamped
assumption that a fault shows along its channel, and each candidate is
`frontier`, `trail`, `open` or `screened` by its own checks and that rule. The
walk as a whole is `traced`, `partly_traced`, `open`, `unexplained` or `cut`.
Without posteriors the order is the standing, and the reading named is one an
OPEN candidate's check could not take -- never one already taken, and none at
all when nothing is open. On the same chain, with the tank read clean, the pump
is screened and the finding is unexplained.

AND THE FIRST RUNG DOWN. Each frontier entity says what it
explains: the entities downstream of it along declared causal edges, within the
bound, that show a finding at the walk's instant, and how many findings that is;
and which declared actions apply to it, asked the way the action verbs ask. Where
the visible fault stops is where to look, and this is what looking there would
account for. -- a rule may name the end where a failure starts,
`cause: target` walking against the edge the author feeds; see `causal`.

AND WHERE A WALK ENDS, FOR `gaps`. Everything this verb reads before
it infers -- the graph, the candidates, the evidence -- is `_upward`, and
`walk_up` takes the standings off it with nothing inferred, so `gaps` cannot
disagree with this verb about where a walk stands. `walk_residuals` locates what
the walk cannot explain: a cause the model expects and nothing connects, a
finding every connected cause screened, a relation fed with no causal
direction, and a cause a person confirmed outside the graph.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import (Any, Callable, Dict, List, NamedTuple, Optional, Sequence,
                    Set, Tuple)

from ..assumptions import (ASSUMPTION_STAMPS, EVIDENCE_READ_AT_DECLARED_DELAY,
                           FAULTS_VISIBLE_ALONG_CHANNELS, READ_AT_DEAD_TIME,
                           READ_AT_EACH_PATH_DELAY, TIME_COURSE_NOT_DECLARED)
from ..clock import CalendarSpan, now_utc, shift_months
from ..subenvelope import Decline, SubEnvelope
from ..types import (DEFAULT_CAUSAL_MAX_HOPS, Severity,
                     read_causal_max_hops)
from .causal import SOURCE_DEFAULT, CausalGraph, causal_subgraph, cause_end
from .runner import (Evidence, Query, _factors, _open_backdoor_latent,
                     _own_severity, _relevant_edges, _surgery, entity_evidence,
                     evidence_from, evidence_severities, node_evidence,
                     run_inference)
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
#:
#: the dead time is a PAIR, calendar months and seconds. A delay
#: declared as months has no length in seconds until it is laid back from an
#: instant, so a walk adds the months and the seconds separately and the read
#: instant applies them once, months first: two monthly edges are two months
#: before the finding, which is not one month before one month before.
_Dead = Tuple[int, float]
_Walk = Tuple[_Dead, bool, bool]
_NO_DEAD: _Dead = (0, 0.0)


def _dead_plus(dead: _Dead, delay: Any) -> _Dead:
    """`dead` with one edge's declared delay added: seconds, a `CalendarSpan`,
    or None for an edge that declared none."""
    months, seconds = dead
    if isinstance(delay, CalendarSpan):
        return months + delay.months, seconds + delay.fixed.total_seconds()
    return months, seconds + (delay or 0.0)


def _moved(dead: _Dead) -> bool:
    """Whether a walk's dead time moves the read at all."""
    return dead[0] != 0 or dead[1] > 0


def _read_instant(anchor: datetime, dead: _Dead) -> datetime:
    """The instant a walk with dead time `dead` reads at: the months, then the
    seconds, laid back from the finding's instant."""
    return shift_months(anchor, -dead[0]) - timedelta(seconds=dead[1])


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
    level: Dict[str, Set[_Walk]] = {subject: {(_NO_DEAD, False, False)}}
    for _hop in range(max_hops):
        nxt: Dict[str, Set[_Walk]] = {}
        for child, summaries in level.items():
            for parent in graph.parents.get(child, ()) or ():
                delay = graph.delays.get((parent, child))
                tau = graph.time_constants.get((parent, child))
                for dead, undeclared, lagged in summaries:
                    nxt.setdefault(parent, set()).add(
                        (_dead_plus(dead, delay), undeclared or delay is None,
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
               ) -> Dict[str, Tuple[Optional[int], Optional[str], bool,
                                    Optional[Dict[str, Any]]]]:
    """Each causal node as a check at `at` saw it: `(state, severity, unread,
    summary)`, the summary being `entity_evidence` at that instant.

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
    observed, _unobserved, summaries = node_evidence(scratch, graph, severities)
    return {node: (observed.get(node), _own_severity(scratch, node),
                   node in unread, summaries.get(node))
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
    observed, unobserved, base = node_evidence(session, graph, severities)
    severity = {node: _own_severity(session, node) for node in graph.nodes}
    summaries: Dict[str, Dict[str, Any]] = dict(base)
    shifts = {node: sorted({walk[0] for walk in summaries})
              for node, summaries in walks.items()}
    instants = sorted({dead for dead_times in shifts.values()
                       for dead in dead_times if _moved(dead)})
    states = {dead: _states_at(session, graph,
                               _read_instant(anchor, dead), severities,
                               check)
              for dead in instants}
    live = dict(observed)
    left_out = set(unobserved)
    read_at: Dict[str, List[str]] = {}
    declines: List[Decline] = []
    for node, dead_times in sorted(shifts.items()):
        if node == subject or node not in graph.nodes \
                or not any(_moved(dead) for dead in dead_times):
            continue
        readings: List[Tuple[Optional[int], Optional[str], bool,
                             Optional[Dict[str, Any]]]] = []
        for dead in dead_times:
            if _moved(dead):
                readings.append(states[dead][node])
            else:
                readings.append((None if node in left_out else observed.get(node),
                                 severity.get(node), False, base.get(node)))
        read_at[node] = [_read_instant(anchor, dead).isoformat()
                         for dead in dead_times]
        if any(state == 1 for state, _sev, _unread, _summary in readings):
            value: Optional[int] = 1
        elif all(state == 0 for state, _sev, _unread, _summary in readings):
            value = 0
        else:
            value = None
        # the summary of the instant that decided the node: the
        # first faulty reading, or the first reading when all were clean, or
        # the first that gave no definite answer.
        deciding = next((summary for state, _sev, _unread, summary in readings
                         if state == value and summary), None)
        if deciding is not None:
            summaries[node] = deciding
        if value is None:
            live.pop(node, None)
            left_out.add(node)
            if all(unread for _state, _sev, unread, _summary in readings):
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
        severity[node] = _worst([sev for _state, sev, _unread, _summary in readings])
    return (Evidence(live, tuple(sorted(left_out)), severity, summaries), read_at,
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
                    model, among: Optional[Set[str]] = None
                    ) -> Optional[Dict[str, Any]]:
    """The entity whose reading would move the ranking most, by the strengths.

    Each outcome of the reading is weighed by the model's own probability of
    it given everything else, and the move is the summed change in the
    candidates' posteriors. A reading already taken counts only through the
    outcome it did NOT give. None when elimination is too wide or no reading
    moves anything, and the caller then answers by screening. `among` limits
    the entities weighed: weighs only the open candidates.
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
    if among is not None:
        pool = [node for node in pool if node in among]
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
    # name a reading; the caller then answers by screening.
    if best is None or round(best[0], 6) <= 0.0:
        return None
    moved, node, flips = best
    return dict(_reading(model, graph, node), basis="strengths",
                expected_change=round(moved, 6), changes_top_if=flips)


class _Upward(NamedTuple):
    """What a walk up from a finding reads before anything is inferred."""
    graph: CausalGraph
    checked: Dict[str, Any]
    declines: List[Decline]
    candidates: List[Tuple[str, int, List[str]]]
    severities: Any
    walks: Dict[str, Set[_Walk]]
    aligned: bool
    evidence: Optional[Evidence]
    read_at: Dict[str, List[str]]
    anchor: Optional[datetime]
    stamps: Set[str]
    #: the declared causes past `causal.max_hops`, by name.
    beyond: List[str]


def _upward(session: Any, entity_id: str, check: Optional[Callable[[Any], Any]],
            graph: Optional[CausalGraph] = None) -> _Upward:
    """ -- the walk up from a finding as far as it goes without
    inference: the declared causal graph, the candidates within the bound -- or
    the decline saying why there are none -- and the evidence, each cause read
    at its declared delays. `hypothesize` infers on top of it, and `walk_up`
    reads the walk off it and infers nothing, so the two cannot disagree about
    where a walk stands.

    `graph` is the causal subgraph when the caller has already built it for
    this session, as `gaps` does once for every finding it walks.
    """
    hop_bound = read_causal_max_hops(getattr(session.model, "causal", None)).hops
    checked: Dict[str, Any] = {"candidates": 0, "ranked": 0, "max_hops": hop_bound}
    declines: List[Decline] = []
    if graph is None:
        graph = causal_subgraph(session.model, session.graph, session.entities)

    def nothing(beyond: List[str]) -> _Upward:
        return _Upward(graph, checked, declines, [], None, {}, False, None, {},
                       None, set(), beyond)

    if entity_id not in graph.nodes:
        declines.append(Decline(
            "not_identifiable", {"entity": entity_id},
            detail=(f"`{entity_id}` is not in the declared causal subgraph, so "
                    f"there is nothing upstream of it to rank. An edge enters "
                    f"that graph by declaring `edge_direction: causal`, or the "
                    f"end its cause sits at with `cause:`; this verb does not "
                    f"search for one.")))
        return nothing([])

    candidates = _ancestors(graph, entity_id, hop_bound)
    checked["candidates"] = len(candidates)
    # BY NAME, so a case can say a confirmed cause was declared and
    # out of reach rather than not connected at all.
    past = sorted(graph.ancestors(entity_id) - {entity_id}
                  - {node for node, _hops, _path in candidates})
    beyond = len(past)
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
        return nothing(past)

    # WHEN EACH CAUSE IS READ. Only a declared dead time moves a
    # read, and a model declaring none gets exactly the evidence it always did.
    severities, _declared, _unusable = evidence_severities(session.model)
    walks = _walks(graph, entity_id, hop_bound)
    aligned = any(_moved(walk[0]) for summaries in walks.values() for walk in summaries)
    stamps: Set[str] = set()
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
        if any(_moved(dead) and lagged for dead, _undeclared, lagged in cone):
            stamps.add(READ_AT_DEAD_TIME)
        if any(len({walk[0] for walk in summaries}) > 1
               for summaries in walks.values()):
            stamps.add(READ_AT_EACH_PATH_DELAY)
    return _Upward(graph, checked, declines, candidates, severities, walks,
                   aligned, evidence, read_at, anchor, stamps, past)


def _evidence_of(session: Any, up: _Upward, node: str) -> Dict[str, Any]:
    """What a candidate's checks said, at the instant it was read where a
    declared delay moved the read, and at the finding's otherwise."""
    return ((up.evidence.summaries.get(node) if up.evidence is not None else None)
            or entity_evidence(session, node, up.severities))


def hypothesize(session: Any, entity_id: str, *,
                report_above: Optional[float] = None,
                check: Optional[Callable[[Any], Any]] = None
                ) -> Tuple[SubEnvelope, List[Dict[str, Any]], Dict[str, Any]]:
    """Rank the declared causes of a finding on `entity_id`.

    Returns the sub-envelope, the ranked candidates and what the ranking
    carries beside them -- `most_discriminating`, the declared causes past the
    bound by name as `beyond_bound`, and, when a declared delay moved a read,
    `read_at` -- which the caller attaches. The shape `entail`
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
    if getattr(session, "model", None) is None:
        return (SubEnvelope("inference", {"candidates": 0}, source="unavailable",
                            reason="no domain model loaded"), [], extras)

    # everything before the first inference is the walk's own, and
    # `gaps` reads the same walk through `walk_up` with nothing inferred.
    up = _upward(session, entity_id, check)
    graph, checked, declines, candidates = (up.graph, up.checked, up.declines,
                                            up.candidates)
    extras["beyond_bound"] = list(up.beyond)
    if not candidates:
        extras["walk"] = _cut_walk()
        return SubEnvelope("inference", checked, not_checked=declines), [], extras
    walks, aligned, evidence, stamps = up.walks, up.aligned, up.evidence, up.stamps
    severities, read_at, anchor = up.severities, up.read_at, up.anchor
    if aligned:
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
        when = (_read_instant(anchor, dead_times[0])
                if aligned and dead_times and _moved(dead_times[0]) else None)
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
            # WHAT ITS CHECKS SAID, whether or not the posterior
            # used it: `state` (faulty, deviating, clean, partial, unread),
            # `looked` as ran of declared, the findings by type, and `needs`
            # -- each reading the check could not take, with its reason. Read
            # at the instant the cause was read, where a delay moved it.
            "evidence": _evidence_of(session, up, node),
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

    # WHERE EACH CANDIDATE STANDS on the walk up from the finding,
    # from step 1's states at the instant each was read. A candidate read clean
    # screens everything whose only way down runs through it, on the stamped
    # assumption that a fault shows along its channel; nothing is screened
    # through a candidate that is not clean.
    standings, screened_by = _standings(graph, entity_id, ranked)
    for row in ranked:
        row["standing"] = standings[row["cause"]]
        row["screened_by"] = screened_by.get(row["cause"])
    if any(standing == "screened" for standing in standings.values()):
        stamps.add(FAULTS_VISIBLE_ALONG_CHANNELS)

    # Nearest first on a tie, because a cause two hops away explains a finding
    # only through one that is nearer, and asking about the nearer one first is
    # how an operator narrows rather than guesses.
    #
    # BY POSTERIOR ONLY WHERE EVERY CANDIDATE HAS ONE. Without them
    # the order was hops and then id, and nothing said so (round 18's N16); it
    # is the standing now -- frontier, trail, open, screened -- and the walk's
    # `ranked_by` says which order a reader is looking at.
    by_posterior = all(row["posterior"] is not None for row in ranked)
    if by_posterior:
        ranked.sort(key=lambda row: (-(row["posterior"] or 0.0), row["hops"],
                                     row["cause"]))
    else:
        ranked.sort(key=lambda row: (_STANDING_ORDER[row["standing"]], row["hops"],
                                     row["cause"]))
    checked["ranked"] = len(ranked)

    observed = (dict(evidence.observed) if evidence is not None
                else evidence_from(session, graph, severities)[0])
    for row in ranked:
        if row["posterior"] is not None:
            row["do_would_answer"] = _do_answer(graph, entity_id, row["cause"],
                                                observed)
    found, why = _most_discriminating(
        session, graph, entity_id, ranked, observed, stamps, standings)
    extras["most_discriminating"] = found
    if why:
        extras["most_discriminating_reason"] = why
    extras["walk"] = _walk_record(ranked, standings,
                                  "posterior" if by_posterior else "standing")
    _downward(session, graph, extras["walk"]["frontier"], checked["max_hops"])

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
                         stamps: set, standings: Dict[str, str]
                         ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """The one reading that would move the walk most, how it was chosen, and,
    when none is named, why.

    AMONG OPEN CANDIDATES ONLY, naming a reading the last check
    could not take. A candidate already read has nothing left to tell, and
    this named one anyway: the clean tank's own level on a chain it already
    screened, a faulty executive's tenure beside the finding that explains the
    department. Chosen by the strengths where every candidate has a posterior;
    otherwise the candidate whose clean reading would screen the most of what
    remains; and the candidate itself where only one is open. `None`, with the
    reason, when nothing is open.
    """
    if not ranked:
        return None, None
    open_rows = [row for row in ranked if standings.get(row["cause"]) == "open"]
    if not open_rows:
        return None, ("no candidate is open: every one the walk reached was "
                      "read, and any other is screened behind one read clean")
    if len(open_rows) == 1:
        basis = "only_candidate" if len(ranked) == 1 else "only_open"
        return dict(_need(session.model, graph, open_rows[0]), basis=basis), None
    if all(row["posterior"] is not None for row in ranked):
        found = _by_information(graph, subject, ranked, observed, session.model,
                                among={row["cause"] for row in open_rows})
        if found is not None:
            chosen = next(row for row in open_rows if row["cause"] == found["entity"])
            found.update(_need(session.model, graph, chosen))
            return found, None
    stamps.add(FAULTS_VISIBLE_ALONG_CHANNELS)
    return _by_screening(session.model, graph, subject, ranked, standings,
                         open_rows), None


#: the order standings rank in where any candidate lacks a posterior.
_STANDING_ORDER: Dict[str, int] = {"frontier": 0, "trail": 1, "open": 2, "screened": 3}

#: The states a candidate's checks give that count as a finding on the walk.
_FOUND = ("faulty", "deviating")


def _standings(graph: CausalGraph, subject: str, ranked: List[Dict[str, Any]]
               ) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """Where each candidate stands on the walk up from `subject`.

    - `trail` -- it has a finding (`faulty` or `deviating`), and it is
      reachable from the subject through candidates that are not clean;
    - `frontier` -- on the trail, and every cause connected to it within the
      bound is clean, or none is: where the visible fault stops;
    - `open` -- `partial` or `unread`, and reachable the same way;
    - `screened` -- `clean`, or reachable only through a clean candidate.

    `screened_by` names, for each candidate reachable only through clean ones,
    the clean candidates the walk stopped at below it.
    """
    state = {row["cause"]: (row.get("evidence") or {}).get("state") for row in ranked}
    reached: Set[str] = set()
    queue = [subject]
    while queue:
        current = queue.pop(0)
        for parent in graph.parents.get(current, ()) or ():
            if parent not in state or parent in reached:
                continue
            reached.add(parent)
            if state[parent] != "clean":
                queue.append(parent)
    live = {node for node in reached if state[node] != "clean"}
    above = {node: _upstream_within(graph, node, live) for node in live}
    standings: Dict[str, str] = {}
    for cause, read in state.items():
        if cause not in live:
            standings[cause] = "screened"
        elif read in _FOUND:
            # Nothing that is not clean lies above it -- or what does lies on a
            # loop back to it and has a finding too: a ring of faulty causes is
            # where the visible fault stops, not a trail with no top.
            standings[cause] = ("frontier" if all(
                state[node] in _FOUND and cause in above[node]
                for node in above[cause]) else "trail")
        else:
            standings[cause] = "open"
    blockers = [node for node in reached if state[node] == "clean"]
    screened_by: Dict[str, List[str]] = {}
    for cause in state:
        if cause not in reached:
            screened_by[cause] = sorted(
                blocker for blocker in blockers
                if cause in _upstream_within(graph, blocker, state))
    return standings, screened_by


def _upstream_within(graph: CausalGraph, node: str, within: Any) -> Set[str]:
    """Every member of `within` that reaches `node` along declared causal
    edges whose every node is a member too."""
    seen: Set[str] = set()
    queue = [node]
    while queue:
        current = queue.pop(0)
        for parent in graph.parents.get(current, ()) or ():
            if parent in within and parent not in seen:
                seen.add(parent)
                queue.append(parent)
    return seen


def _walk_record(ranked: List[Dict[str, Any]], standings: Dict[str, str],
                 ranked_by: Optional[str]) -> Dict[str, Any]:
    """The walk as a whole: its state, where the visible fault stops, what is
    still open and what each open candidate needs, the counts by standing, and
    the order the candidates are in.

    `traced` -- a frontier and nothing open; `partly_traced` -- a frontier and
    something open; `open` -- no frontier, something open; `unexplained` --
    every connected cause screened; `cut` -- no cause connected. A trail always
    has a frontier above it, so the five are the only answers.
    """
    frontier = [{"entity": row["cause"],
                 "findings": sorted((row.get("evidence") or {}).get("findings") or {})}
                for row in ranked if standings.get(row["cause"]) == "frontier"]
    still_open = [{"entity": row["cause"],
                   "needs": list((row.get("evidence") or {}).get("needs") or [])}
                  for row in ranked if standings.get(row["cause"]) == "open"]
    counts = {name: sum(1 for standing in standings.values() if standing == name)
              for name in _STANDING_ORDER}
    if not standings:
        state = "cut"
    elif frontier:
        state = "partly_traced" if still_open else "traced"
    elif still_open:
        state = "open"
    else:
        state = "unexplained"
    return {"state": state, "frontier": frontier, "open": still_open,
            "counts": counts, "ranked_by": ranked_by}


def _cut_walk() -> Dict[str, Any]:
    """The walk for a subject no declared cause reaches."""
    return _walk_record([], {}, None)


def _findings_now(session: Any) -> Dict[str, List[str]]:
    """Each entity's findings in the session's last check, by problem type: the
    walk's instant. A cause read at a declared delay is read on a scratch
    session, so this is never a past reading."""
    result = getattr(session, "_last_result", None)
    now: Dict[str, List[str]] = {}
    for problem in (list(getattr(result, "problems", ()) or ())
                    + list(getattr(result, "warnings", ()) or ())) if result is not None else ():
        entity = str(getattr(problem, "entity_id", "") or "")
        if entity:
            now.setdefault(entity, []).append(str(getattr(problem, "problem_type", "") or ""))
    return now


def _downward(session: Any, graph: CausalGraph, frontier: List[Dict[str, Any]],
              hop_bound: int) -> None:
    """ -- the first rung down from each frontier entity, written onto its
    row: `explains`, the entities downstream of it along declared causal edges,
    within the walk's bound, that show a finding at the walk's instant, nearest
    first, with `findings_explained` counting those findings; and `actions`,
    every declared template that applies to its type, asked the way the action
    verbs ask. Layered and bounded by the hops, as the walk up is, so a cycle in
    the declaration costs at most `hop_bound` layers.

    It says where a fix would reach, not that one exists: an action is listed
    because it applies to the entity, and nothing here says it would relieve
    anything -- `plan` answers that, against a declared objective.
    """
    if not frontier:
        return
    from ..twin.actions import applies, load_templates
    templates, _refused = load_templates(session.model)
    lineage = getattr(session.model, "lineage", None)
    children: Dict[str, List[str]] = {}
    for child, parents in graph.parents.items():
        for parent in parents:
            children.setdefault(parent, []).append(child)
    now = _findings_now(session)
    for row in frontier:
        node = row["entity"]
        reached, layer, explained = {node}, [node], []
        for hops in range(1, hop_bound + 1):
            nxt: List[str] = []
            for current in layer:
                for child in sorted(children.get(current, ())):
                    if child in reached:
                        continue
                    reached.add(child)
                    nxt.append(child)
                    if now.get(child):
                        explained.append({"entity": child, "hops": hops,
                                          "findings": sorted(now[child])})
            if not nxt:
                break
            layer = nxt
        row["explains"] = sorted(explained, key=lambda r: (r["hops"], r["entity"]))
        row["findings_explained"] = sum(len(r["findings"]) for r in explained)
        row["actions"] = [name for name, template in templates.items()
                          if applies(template, graph.entity_type.get(node, ""), lineage)]


def _need(model, graph: CausalGraph, row: Dict[str, Any]) -> Dict[str, Any]:
    """The reading an open candidate is waiting on: of those its last check
    could not take, the first value its type declares. `None` where none of
    them is a value -- a relation is outstanding, or nothing a reading would
    cure -- because a reading named is one a person can take and
    one the walk is owed."""
    node = row["cause"]
    owed = {need.get("reading") for need in (row.get("evidence") or {}).get("needs") or []}
    for name in _readable_properties(model, graph.entity_type.get(node, "")):
        if f"{node}.{name}" in owed:
            return {"entity": node, "reading": f"{node}.{name}"}
    return {"entity": node, "reading": None}


def _by_screening(model, graph: CausalGraph, subject: str,
                  ranked: List[Dict[str, Any]], standings: Dict[str, str],
                  open_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The open candidate whose clean reading would screen the most of what
    remains, nearest first on a tie; `screens` counts the others it would
    screen., replacing the even split of the graph's shape, which
    counted candidates already read as still in play."""
    scored = []
    for row in open_rows:
        trial = [dict(other, evidence=dict(other.get("evidence") or {}, state="clean"))
                 if other["cause"] == row["cause"] else other for other in ranked]
        after, _blocked_by = _standings(graph, subject, trial)
        screens = sum(1 for cause, standing in after.items()
                      if cause != row["cause"] and standing == "screened"
                      and standings.get(cause) != "screened")
        scored.append((-screens, row["hops"], row["cause"], row))
    scored.sort(key=lambda item: item[:3])
    negative, _hops, _cause, row = scored[0]
    return dict(_need(model, graph, row), basis="screening", screens=-negative)


#: the states a walk ends in, counted in this order.
_WALK_STATES = ("traced", "partly_traced", "open", "unexplained", "cut")


def walk_up(session: Any, entity_id: str, *,
            check: Optional[Callable[[Any], Any]] = None,
            graph: Optional[CausalGraph] = None) -> Dict[str, Any]:
    """ -- the walk up from a finding on `entity_id` as `hypothesize`
    takes it, with nothing inferred: no posterior is computed, so nothing is
    filed. `walk` is the record `hypothesize` reports, but its `ranked_by` is
    null, since nothing here is ranked; `standings` and `screened_by` are per
    candidate."""
    up = _upward(session, entity_id, check, graph)
    if not up.candidates:
        return {"walk": _cut_walk(), "standings": {}, "screened_by": {}}
    rows = [{"cause": node, "hops": hops, "evidence": _evidence_of(session, up, node)}
            for node, hops, _path in up.candidates]
    standings, screened_by = _standings(up.graph, entity_id, rows)
    rows.sort(key=lambda row: (_STANDING_ORDER[standings[row["cause"]]],
                               row["hops"], row["cause"]))
    walk = _walk_record(rows, standings, None)
    _downward(session, up.graph, walk["frontier"], up.checked["max_hops"])
    return {"walk": walk, "standings": standings, "screened_by": screened_by}


def walk_residuals(session: Any, problems: Optional[Sequence[Any]], *,
                   check: Optional[Callable[[Any], Any]] = None
                   ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Decline]]:
    """ -- where the walk up from each finding ends, and what the
    declaration says about why: `gaps`' fourth arm. The located shape is the
    other arms', with `basis: walk`.

    - `no_cause_connected`: the subject of a walk, or an entity on its
      frontier, is of a type some causal rule targets, and no causal edge of
      that relation reaches it. Its `evidence_needed` is the relation on the
      entity, as the presence arm gives it.
    - `unexplained_finding`: every cause the walk reaches read clean, or sits
      behind one that did. Its `candidates` are the undeclared channels at it,
      or there are none and the `reason` says so.
    - `undeclared_channel`: a relation somebody fed joins a subject, or an
      entity on a trail, to an entity that shows a finding, and no rule gives
      that relation, between those types, a causal direction. Not where a
      causal edge already joins the two. Per relation, `undeclared_channels`
      counts the instances and the findings each direction would connect --
      both, and neither preferred: a count says what a direction would
      connect, not which way a failure runs.
    - `confirmed_outside_graph`: a person confirmed a cause that is no declared
      ancestor of the case's subject at any distance. Its `basis` is the
      confirmation's own.

    It proposes nothing into the graph, infers nothing and files nothing. A
    model that declares no causal rule has no walk to fail, and is told so by
    name rather than shown every relation between two findings.
    """
    counts: Dict[str, Any] = {"walks_read": 0, "walk_states": {},
                              "confirmations_read": 0, "undeclared_channels": {}}
    model = session.model
    causal = [rule for rule in (model.relationship_rules or ()) if cause_end(rule)]
    if not causal:
        return [], counts, [Decline(
            "missing_config", {"location": "walk"},
            detail=("no relationship rule declares `edge_direction: causal` or a "
                    "`cause:` end, so no walk runs from a finding and nothing can "
                    "be missing from one"))]
    if problems is None:
        return [], counts, [Decline(
            "precondition_unmet", {"location": "walk"},
            detail=("no check has run, so there is no finding to walk from; run "
                    "check first"))]

    entities = session.entities
    graph = causal_subgraph(model, session.graph, entities)

    def type_of(entity_id: str) -> str:
        return str(getattr(entities.get(entity_id), "type", "") or "")

    found: Dict[str, int] = {}
    for problem in problems:
        unit = str(getattr(problem, "entity_id", "") or "")
        if unit:
            found[unit] = found.get(unit, 0) + 1
    walked = {unit: walk_up(session, unit, check=check, graph=graph) for unit in found}
    states = dict.fromkeys(_WALK_STATES, 0)
    for result in walked.values():
        states[result["walk"]["state"]] = states.get(result["walk"]["state"], 0) + 1
    counts["walks_read"], counts["walk_states"] = len(walked), states

    outgoing = getattr(session.graph, "edges", {}) or {}
    incoming = getattr(session.graph, "reverse_edges", {}) or {}

    # No cause connected: a relation a causal rule says brings a cause in, and
    # nothing arrives by it. -- from the end the rule names: with the
    # cause at the source it arrives on an edge into the entity, with the cause
    # at the target on an edge out of it.
    sources: Dict[Tuple[str, str, str], Set[str]] = {}
    for rule in causal:
        end = cause_end(rule)
        effect, cause = ((rule.get("target_type"), rule.get("source_type"))
                         if end == "source" else
                         (rule.get("source_type"), rule.get("target_type")))
        sources.setdefault((str(effect or ""), str(rule.get("type", "")), end),
                           set()).add(str(cause or ""))
    unconnected: Dict[Tuple[str, str], List[str]] = {}
    for unit, result in walked.items():
        for entity_id in [unit] + [row["entity"] for row in result["walk"]["frontier"]]:
            for (effect_type, relation, end), cause_types in sorted(sources.items()):
                arriving = (incoming if end == "source" else outgoing).get(entity_id, ())
                if effect_type != type_of(entity_id) or any(
                        str(kind) == relation and type_of(other) in cause_types
                        for kind, other in arriving):
                    continue
                subjects = unconnected.setdefault((entity_id, relation), [])
                if unit not in subjects:
                    subjects.append(unit)
    located: List[Dict[str, Any]] = [
        {"kind": "no_cause_connected", "at": entity_id, "basis": "walk",
         "relation": relation, "subjects": sorted(subjects),
         "evidence_needed": f"{entity_id}.{relation}"}
        for (entity_id, relation), subjects in unconnected.items()]

    # Undeclared channels: a relation somebody fed, between an entity on a walk
    # and one that shows a finding, along which no rule says a failure runs. An
    # instance a causal rule covers is a causal edge, so the pairs a causal edge
    # joins are the only ones left out -- the instance itself, and any other
    # relation between two entities the walk can already cross.
    joined = {frozenset((parent, child))
              for child, parents in graph.parents.items() for parent in parents}
    on_walk: Dict[str, List[str]] = {}
    for unit, result in walked.items():
        on_walk.setdefault(unit, [])
        for entity_id in [unit] + [cause for cause, standing in result["standings"].items()
                                   if standing in ("trail", "frontier")]:
            subjects = on_walk.setdefault(entity_id, [])
            if unit not in subjects:
                subjects.append(unit)
    channels: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for entity_id, subjects in on_walk.items():
        instances = ([(entity_id, str(kind), other) for kind, other in
                      outgoing.get(entity_id, ())]
                     + [(other, str(kind), entity_id) for kind, other in
                        incoming.get(entity_id, ())])
        for source, relation, target in instances:
            other = target if source == entity_id else source
            if (other == entity_id or other not in found
                    or frozenset((source, target)) in joined):
                continue
            entry = channels.setdefault((source, relation, target), {
                "kind": "undeclared_channel", "between": [source, target],
                "basis": "walk", "relation": relation, "subjects": [],
                "evidence_needed": None,
                "reason": (f"no rule gives `{relation}` from {type_of(source)} to "
                           f"{type_of(target)} a causal direction, so no walk crosses "
                           f"it; which way a failure runs along it is the model's to "
                           f"declare, as `cause: source` or `cause: target` on its "
                           f"rule, and no reading settles it")})
            entry["subjects"] = sorted(set(entry["subjects"]) | set(subjects))
    per: Dict[str, Dict[str, Any]] = {}
    for source, relation, target in sorted(channels):
        row = per.setdefault(relation, {"instances": 0, "sources": set(), "targets": set()})
        row["instances"] += 1
        row["sources"].add(source)
        row["targets"].add(target)
    counts["undeclared_channels"] = {
        relation: {"instances": row["instances"],
                   # Declared with the cause at the source, it would connect the
                   # findings at the targets; at the target, those at the sources.
                   "if_cause_is_source": sum(found[node] for node in row["targets"]),
                   "if_cause_is_target": sum(found[node] for node in row["sources"])}
        for relation, row in sorted(per.items())}

    for unit, result in walked.items():
        if result["walk"]["state"] != "unexplained":
            continue
        candidates = [{"between": entry["between"], "relation": entry["relation"]}
                      for _key, entry in sorted(channels.items())
                      if unit in entry["between"]]
        located.append({
            "kind": "unexplained_finding", "at": unit, "basis": "walk",
            "screened": sorted(cause for cause, standing in result["standings"].items()
                               if standing == "screened"),
            "candidates": candidates, "evidence_needed": None,
            "reason": ("every declared cause it reaches read clean, or sits behind "
                       "one that did; a causal direction declared on a candidate "
                       "would connect another" if candidates else
                       "every declared cause it reaches read clean, or sits behind "
                       "one that did, and no relation without a causal direction "
                       "joins it to an entity that shows a finding")})
    located.extend(entry for _key, entry in sorted(channels.items()))

    # Confirmed outside the graph: the cause a person named, which no declared
    # channel connects to the finding.
    book = getattr(getattr(session, "ledger", None), "case_book", None)
    for case in (book.cases() if book is not None else ()):
        subject = str(getattr(case, "entity_id", "") or "")
        ancestors = graph.ancestors(subject)
        for confirmation in (getattr(case, "stages", None) or {}).get("confirm") or ():
            counts["confirmations_read"] += 1
            reference = confirmation.get("reference") or {}
            cause = reference.get("cause")
            if not cause or str(cause) == subject or str(cause) in ancestors:
                continue
            located.append({
                "kind": "confirmed_outside_graph", "between": [str(cause), subject],
                "basis": reference.get("basis"), "case_id": case.case_id,
                "indicator": getattr(case, "indicator", None),
                "evidence_needed": None,
                "reason": ("a person confirmed a cause that no declared causal "
                           "channel connects to this finding; a channel between "
                           "them is the model's to declare")})
    return located, counts, []
