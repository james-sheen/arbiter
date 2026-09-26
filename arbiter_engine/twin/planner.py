"""Choosing between rollouts: the engine proposes, and ranks only if told how.

Stage 2 answers *what happens if I do this*. This answers *which of
these should I do* -- and the whole difficulty is that the second question has
no answer the arithmetic can supply on its own. Minimising expected findings
and maximising the chance of clearing a severity are different questions, they
disagree on real inputs, and an engine that picked one would be deciding what
the operator cares about. So the objective is DECLARED, and without a
declaration this module evaluates every candidate, reports what each does, and
ranks nothing.

THE WEIGHT IS DERIVED FROM `Severity.priority_score`, AND NOT EQUAL TO IT.
That score is a RANK -- critical is 1, info is 5, lower is more severe -- and
the design note's objective sums it and minimises. Measured on four candidate
plans, that picks *one CRITICAL* over *three INFO*: it recommends the plan
that breaks the most important thing, because a rank used as a magnitude
inverts. `1/priority_score` is monotone in the same scale and introduces no
second table, which is the constraint that matters -- a second severity scale
is how two parts of one engine come to disagree about which finding is worse.

WHY THERE IS NO TREE SEARCH HERE. The design note says to reuse
`propagation/mcts_root_cause.py` rather than fork it. Read, that scaffold is
set-cover: its node is `(selected, uncovered)`, `is_terminal` is
`len(uncovered) == 0`, and expansion is `uncovered - footprints[action]`. An
action SEQUENCE has an ordering and a horizon and no cover set, so reusing it
means replacing the node, the expansion, the terminal test and the action
generator -- forking it in place, while it is the live path behind root-cause
ranking. Greedy receding-horizon search is what the note itself calls
sufficient for *what should I do now*, and it is what this does. If tree
search earns its place later it should be a planner-owned tree, not a
repurposed one.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..types import Severity
from ..assumptions import (
    DECLARED_GAIN_SPREAD_SAMPLED,
    DETERMINISTIC_TRANSITIONS,
    OBJECTIVE_EVALUATED_AT_MEDIAN,
    SEARCH_DEPTH_NOT_DECLARED,
    TIES_BREAK_TOWARD_FEWER_ACTIONS,
    TIES_BREAK_TOWARD_THE_WIDER_MARGIN,
    WORST_STEP_BINDS_THE_HORIZON,
)
from .actions import ActionInstance, ActionRefused, applies, load_templates
from .topology import SimulationDecline

#: The two objectives, and the direction each is good in.
OBJECTIVES = {
    "expected_findings": "minimise",
    "clearance_probability": "maximise",
}

#: Default ceilings, applied only when the model declares none. Deliberately
#: small: an unbounded plan search is the first place this engine's polynomial
#: guarantee is genuinely at risk, and `inference/ve.py` states the rule --
#: an engine that does not return is worse than one that refuses.
DEFAULT_MAX_ROLLOUTS = 200
#: An internal ruling asked whether this should move to 2 and the answer is NO, recorded
#: here rather than in a document nobody reads beside the constant.
#:
#: Raising it changes the cost AND the answer for every caller who never asked
#: for a search: roughly double the rollouts, and a `best` that may now be a
#: pair where a caller's runbook expects one action. The complaint
#: actually landed was not that the default is low -- it is that the default
#: was UNDISCOVERABLE, because nothing on the envelope said how deep the search
#: went. That is fixed by `max_depth` in `checked` and the
#: `search_depth_not_declared` stamp, and fixing it by widening the default
#: instead would have hidden the same defect behind a better answer.
DEFAULT_MAX_DEPTH = 1


def severity_weight(severity: Any) -> float:
    """Cost of one finding, derived from the engine's one priority scale.

    `priority_score` ranks: 1 is critical, 5 is info. A cost must rise WITH
    severity, so the weight is its reciprocal. Deriving rather than tabulating
    is the point -- a hand-written weight table would be a second severity
    scale, and the first time somebody reordered one and not the other the
    planner and the reasoner would disagree about which finding is worse.
    """
    score = getattr(severity, "priority_score", None)
    if not isinstance(score, (int, float)) or score <= 0:
        return 0.0
    return 1.0 / float(score)


@dataclass
class PlanCandidate:
    """One candidate plan and what rolling it forward produced."""
    actions: List[ActionInstance]
    objective: Optional[float] = None
    interval: Optional[Tuple[float, float]] = None
    findings: List[str] = field(default_factory=list)
    declines: List[str] = field(default_factory=list)
    #:. The assumptions THIS candidate's number rests on. `score`
    #: has always returned them per candidate; they were merged into the
    #: plan-level list and the per-candidate fact dropped, so one plan
    #: carrying both `deterministic_transitions` and
    #: `declared_gain_spread_sampled` left a reader unable to say which row
    #: was which -- and `interval` does not settle it, because `[0.0, 0.0]`
    #: is what a deterministic candidate reports AND what a sampled one
    #: reports when no sample cleared.
    assumptions: List[str] = field(default_factory=list)
    #:. How close the nearest threshold decision was, in units of the
    #: value's OWN declared spread -- the closest any imagined value came to
    #: a line it was judged against, divided by the spread the model declared
    #: for it. `None` when nothing declared a spread that reached the
    #: trajectory: a distance measured in units nobody declared is not a
    #: measurement.
    #:
    #: WHY IT IS WORTH REPORTING. `expected_findings` is a step function of
    #: the values it compares, so a candidate that settles a whisker below a
    #: line scores as though it cleared it comfortably. Measured on the
    #: shipped example: settling at 84.912 scored 14.333 and settling at
    #: 85.012 scored 16.000 -- a tenth of a point moving the ranking by 12 %,
    #: while the declared spread on that value at that step was 0.3988. This
    #: number is what tells a reader which of those two they are looking at.
    #: It changes no ranking — briefly made it break ties, which
    #: contradicted this line and was wrong for the reason that an internal ruling records;
    #: `clearance_sigmas` below carries that job.
    margin_sigmas: Optional[float] = None
    #: the SIGNED worst headroom over the horizon, in declared
    #: spreads: positive when the trajectory stayed clear of every line it
    #: was judged against, negative by how far the deepest excursion went
    #: past one. `margin_sigmas` beside it is an ABSOLUTE closest approach
    #: and cannot say WHICH SIDE of a line a value sat on, which is the one
    #: thing a tie-break has to know.
    clearance_sigmas: Optional[float] = None
    checked: Dict[str, Any] = field(default_factory=dict)
    rollouts: int = 0

    @property
    def label(self) -> str:
        if not self.actions:
            return "do_nothing"
        return " + ".join(
            f"{a.template}@{a.entity_id}"
            f"({','.join(f'{k}={v}' for k, v in sorted(a.parameters.items()))})"
            f"@{a.at_s:g}s"
            for a in self.actions)


@dataclass
class PlanResult:
    candidates: List[PlanCandidate] = field(default_factory=list)
    ranked: bool = False
    objective: str = ""
    direction: str = ""
    min_severity: str = ""
    declines: List[SimulationDecline] = field(default_factory=list)
    refused_actions: List[ActionRefused] = field(default_factory=list)
    questions: List[Any] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    rollouts_run: int = 0
    plans_untested: int = 0
    #:. THE LIMITS, beside the counts that were measured against them.
    #: `rollouts_run: 5` alone cannot say whether the budget was 5 or 200, and
    #: `max_depth` is the one a reader most needs: without it a field of
    #: single-action rows is indistinguishable from a search that ran two deep
    #: and had every pair refused.
    max_rollouts: int = 0
    max_depth: int = 0
    invariants: int = 0
    #:. The no-action row's filing, and only its own. Every other
    #: candidate is a counterfactual and is never asked to file, so these
    #: figures describe one trajectory rather than the field -- which is what
    #: makes them comparable with a `rollout`'s.
    predictions_filed: int = 0
    values_without_tolerance: int = 0
    #:. The no-action row's held values, as the rollout counts them.
    values_held: int = 0
    counterfactuals_not_filed: int = 0
    raced: List[Dict[str, Any]] = field(default_factory=list)
    #:. The union of every candidate rollout's crossed edges.
    #: A plan rests on all of them, so it owes a question about any of
    #: them whose declaration this engine had to supply.
    edges_traversed: Set[str] = field(default_factory=set)


def declared_candidates(model: Any) -> Tuple[List[ActionInstance],
                                             List[SimulationDecline]]:
    """Action instances the MODEL says a planner may try.

    A template declares the property a parameter writes; it does not declare
    what VALUES are worth trying, and a planner cannot invent them. A
    `candidates:` list beside the parameter is that declaration:

        parameters_schema:
          speed_rpm:
            entity_property: speed_rpm
            candidates: [1000, 2000, 3000]

    Without one the template is reported and not searched. Sweeping a numeric
    range the author never wrote would be the engine choosing the operating
    envelope, which is exactly the class of guess this package removed from
    `role:` and from flow direction.
    """
    templates, refused = load_templates(model)
    declines = [SimulationDecline("malformed_action", r.location, r.detail)
                for r in refused]
    out: List[ActionInstance] = []
    for name, template in sorted(templates.items()):
        per_parameter: List[List[Tuple[str, float]]] = []
        for parameter, spec in sorted(
                (template.parameters_schema or {}).items()):
            values = (spec or {}).get("candidates") if isinstance(
                spec, dict) else None
            if not values:
                continue
            numeric: List[Tuple[str, float]] = []
            for value in values:
                try:
                    numeric.append((parameter, float(value)))
                except (TypeError, ValueError):
                    declines.append(SimulationDecline(
                        "malformed_action", f"{name}.{parameter}",
                        f"candidate {value!r} is not a number"))
            if numeric:
                per_parameter.append(numeric)
        if not per_parameter:
            declines.append(SimulationDecline(
                "no_candidates", name,
                f"action template {name!r} declares no `candidates:` on any "
                f"parameter, so a planner has no values to try; declare them "
                f"or pass candidate actions to `plan`"))
            continue
        for combination in itertools.product(*per_parameter):
            out.append(ActionInstance(
                template=name, entity_id="",
                parameters=dict(combination), at_s=0.0))
    return out, declines


def _expand_to_entities(candidates: Sequence[ActionInstance],
                        model: Any,
                        entities: Dict[str, Any]) -> List[ActionInstance]:
    """An instance with no entity is a template-level candidate: fan it out."""
    templates, _ = load_templates(model)
    out: List[ActionInstance] = []
    for candidate in candidates:
        if candidate.entity_id:
            out.append(candidate)
            continue
        template = templates.get(candidate.template)
        lineage = getattr(model, "lineage", None)
        for entity_id, entity in sorted(entities.items()):
            if template is not None and not applies(
                    template, getattr(entity, "type", None), lineage):
                continue
            out.append(ActionInstance(
                template=candidate.template, entity_id=entity_id,
                parameters=dict(candidate.parameters), at_s=candidate.at_s))
    return out


def score(candidate: PlanCandidate, objective: str, min_severity: str,
          findings: Sequence[Any], monte_carlo_samples: int,
          seed: int, envelope: Any = None
          ) -> Tuple[Optional[float], Optional[Tuple[float, float]],
                     List[str]]:
    """The objective value for one rolled-forward candidate."""
    assumptions: List[str] = []
    if objective == "expected_findings":
        # SUMMED EXACTLY, then rounded once.
        #
        # `severity_weight` is `1.0 / priority_score`, so this is a sum of
        # reciprocals of small integers -- and 1/3 and 1/5 have no binary
        # representation, so adding them as floats made the total depend on
        # how many findings of which severity arrived in what order. Two
        # consequences, and the second changes an answer:
        #
        #   - the reported number was wrong in its last bits, on this
        #     package's own published example: 24 findings of priorities 1
        #     and 3, exact cost 16, reported `16.000000000000004`;
        #   - TWO PLANS THAT COST THE SAME STOPPED COMPARING EQUAL. The sort
        #     below is `(objective, len(actions))` and its comment says fewer
        #     actions wins an EXACT tie, so a tie lost to rounding is not a
        #     tie: `[2,3,3,3,5,5,5,5]` and `[1,2,5,5,5,5]` are both 23/10 and
        #     came out `2.3` and `2.3000000000000003`, handing the win to the
        #     plan with two more actions in it.
        #
        # NO TOLERANCE, deliberately. Comparing within an epsilon would be
        # the engine deciding how close two costs must be before it calls
        # them equal, which is a domain question nobody declared. The exact
        # rational total needs no such decision: equal costs become equal
        # floats by construction, and the value reported is the same `float`
        # as before, correctly rounded.
        total = Fraction(0)
        for finding in findings:
            priority = getattr(
                getattr(finding, "severity", None), "priority_score", None)
            if not isinstance(priority, (int, float)) or priority <= 0:
                # The same refusal `severity_weight` makes, and for the same
                # reason: a finding with no place on the scale contributes
                # nothing rather than a guessed cost.
                continue
            total += Fraction(1) / Fraction(priority)
        return (float(total), None, assumptions)

    # clearance_probability: did the horizon stay clear of `min_severity`?
    from .monte_carlo_predictor import (MonteCarloPredictionRequest,
                                        MonteCarloPredictor)

    threshold = _severity_at_least(min_severity)
    breached = any(
        _severity_at_least(getattr(
            getattr(f, "severity", None), "value", "")) is not None
        and getattr(f, "severity").priority_score <= threshold
        for f in findings) if threshold is not None else False

    # A PROBABILITY, WHEN THE MODEL DECLARED ENOUGH TO MAKE ONE.
    #
    # This used to sample a function that returned the same constant every
    # time, so the estimate was 0.0 or 1.0 and the interval collapsed to a
    # point. That was honestly stamped `deterministic_transitions`, and it was
    # also the whole of the value-level uncertainty this engine could offer: a
    # boolean wearing a decimal point.
    #
    # With a declared `gain_sigma:` the imagined values carry a spread, so the
    # margin between a trajectory and the line it must not cross is a random
    # variable and the clearance figure is a real probability. Sampled rather
    # than integrated because the axioms that decide `clear` are thresholds
    # over a whole horizon, and a closed form for that needs the joint
    # distribution across steps -- which the engine would have to assume.
    # Sampling the margin needs only what the author declared.
    margin = _worst_margin(envelope, findings, threshold)
    if margin is None:
        assumptions.append(DETERMINISTIC_TRANSITIONS)
        def step(_snapshot, _rng):
            return {"clear": not breached}
    else:
        centre, spread = margin
        assumptions.append(DECLARED_GAIN_SPREAD_SAMPLED)
        # The SAME declared gain drives every step of one rollout, so the
        # steps of a trajectory move together rather than independently. The
        # margin sampled here is the tightest one over the horizon, which is
        # what that correlation makes the binding constraint. Stamped, because
        # it is the engine's assumption and not the author's.
        assumptions.append(WORST_STEP_BINDS_THE_HORIZON)
        def step(_snapshot, rng):
            return {"clear": rng.gauss(centre, spread) > 0.0}

    distribution = MonteCarloPredictor(seed=seed).predict(
        None, step,
        MonteCarloPredictionRequest(outcome_names=["clear"],
                                    n_samples=monte_carlo_samples, seed=seed))
    outcome = distribution.get("clear")
    if outcome is None:
        return None, None, assumptions
    return (outcome.estimated_probability,
            outcome.confidence_interval_95, assumptions)


def _closest_call(envelope: Any) -> Optional[float]:
    """The nearest a value came to a line it was judged against, in units of
    its own declared spread.

    NOT `_worst_margin`, which answers the neighbouring question and was the
    first thing tried here. That one minimises the SIGNED distance, so it
    finds the deepest breach over the horizon -- the binding constraint for
    `clearance_probability`, and the opposite end of the range from what this
    needs. Reusing it reported a knife-edge candidate as sitting 27.6 spreads
    clear of its warning line when the settled value was 0.22 spreads under
    it.

    This minimises the ABSOLUTE distance instead: how close did the decision
    that produced this objective actually come. `None` when nothing declared
    a spread that reached the trajectory.
    """
    if envelope is None or not getattr(envelope, "has_declared_spread", False):
        return None
    closest: Optional[float] = None
    for step in getattr(envelope, "steps", []) or []:
        for entity_id, spreads in (getattr(step, "sigma", {}) or {}).items():
            for prop, spread in spreads.items():
                if spread <= 0.0:
                    continue
                value = (step.values.get(entity_id, {}) or {}).get(prop)
                if value is None:
                    continue
                for limit, _upper in _bounds_for(envelope, entity_id, prop):
                    sigmas = abs(float(limit) - float(value)) / float(spread)
                    if closest is None or sigmas < closest:
                        closest = sigmas
    return closest


def _signed_clearance(envelope: Any, findings: Sequence[Any],
                      threshold: Optional[int]) -> Optional[float]:
    """The worst headroom over the horizon, SIGNED, in declared spreads.

    `_closest_call` IS THE WRONG QUANTITY TO RANK ON, and
    ranked on it. That one minimises the ABSOLUTE distance to a line, which
    is right for the figure it feeds: a reader asking how close the decision
    came does not care which side. A tie-break does.

    Two consequences, both measured on the shipped model. Among candidates
    that BREACH, the absolute closest approach is not a measure of the breach
    at all -- it is wherever a discrete step happened to fall as the
    trajectory crossed the line. Two candidates tied at objective 1.667, one
    settling 4 points past the band edge and one 8 points past, reported 1.443
    and 0.089; and at `step_s=450` the order REVERSED and the engine preferred
    the deeper breach. The ranking moved with the step size and not with the
    risk.

    The signed worst margin is right in both regimes at once: larger is
    further from the line when clear, and a shallower excursion when not.
    `_worst_margin` already computes exactly it for
    `clearance_probability`'s distribution centre, so this divides by the
    same declared spread rather than deriving a second one.
    """
    margin = _worst_margin(envelope, findings, threshold)
    if margin is None:
        return None
    distance, spread = margin
    if not spread:
        return None
    return float(distance) / float(spread)


def _worst_margin(envelope: Any, findings: Sequence[Any],
                  threshold: Optional[int]
                  ) -> Optional[Tuple[float, float]]:
    """The tightest (distance to the line, spread) over the horizon.

    `None` when the model declared no spread that reached a value, which is
    the case the caller reports as deterministic. Returning `None` rather than
    a zero spread is deliberate: a zero-width distribution would make the
    sampler produce the same boolean and look like a probability.

    The sign convention is that a POSITIVE centre means clear. A trajectory
    already breaching is centred negative, so its clearance probability is
    small rather than exactly zero -- the spread says how sure that is.
    """
    if envelope is None or not getattr(envelope, "has_declared_spread", False):
        return None
    best: Optional[Tuple[float, float]] = None
    for step in getattr(envelope, "steps", []) or []:
        for entity_id, spreads in (getattr(step, "sigma", {}) or {}).items():
            for prop, spread in spreads.items():
                if spread <= 0.0:
                    continue
                bounds = _bounds_for(envelope, entity_id, prop)
                value = (step.values.get(entity_id, {}) or {}).get(prop)
                if value is None or not bounds:
                    continue
                for limit, upper in bounds:
                    distance = (limit - value) if upper else (value - limit)
                    if best is None or distance < best[0]:
                        best = (float(distance), float(spread))
    if best is None and findings and threshold is not None:
        return None
    return best


def _bounds_for(envelope: Any, entity_id: str, prop: str
                ) -> List[Tuple[float, bool]]:
    """The declared lines this property must stay inside, as (limit, is_upper).

    Read off the topology the rollout already built rather than re-derived, so
    a bound this engine judges against and a bound this figure is measured
    against cannot be two different numbers.

    EVERY axiom that judges this property, not BOUNDEDNESS alone.
    This read one state by name, so the two figures built on it measured
    distances to a ceiling while the plan they annotate ranked on findings
    from a band. On `examples/pump_tank_dynamics.yaml` the best-tying
    candidate settles 0.03 spreads from the HOMEOSTASIS edge that decides
    whether it files a finding and was reported 45.1 spreads clear.

    Which lines an axiom declares is the axiom's own business, so it is asked
    rather than decoded here; see `AxiomState.declared_lines`.
    """
    topology = getattr(envelope, "topology", None)
    node = topology.get_node(entity_id) if topology is not None else None
    if node is None:
        return []
    out: List[Tuple[float, bool]] = []
    seen: set = set()
    for key, state in (getattr(node, "axiom_states", {}) or {}).items():
        # Either spelling identifies the property. The key carries it because
        # that is how this read the one state it used to look up; matching on
        # `indicator_name` as well makes this strictly a widening, so no line
        # the old lookup found can be lost by a state that spells one and not
        # the other.
        if (getattr(state, "indicator_name", None) != prop
                and not str(key).endswith(f":{prop}")):
            continue
        reader = getattr(state, "declared_lines", None)
        if not callable(reader):
            continue
        for line in reader():
            if line not in seen:
                seen.add(line)
                out.append(line)
    return out


def _severity_at_least(name: str) -> Optional[int]:
    """The priority score of a declared severity name, or None."""
    if not name:
        return None
    for member in Severity:
        if member.value == str(name).lower():
            return member.priority_score
    return None


def read_objective(model: Any) -> Tuple[Dict[str, Any],
                                        Optional[SimulationDecline]]:
    """The declared `planning:` block, validated."""
    block = dict(getattr(model, "planning", None) or {})
    if not block or not block.get("objective"):
        return block, SimulationDecline(
            "no_objective", "planning",
            "no `planning.objective` is declared, so the candidates were "
            "evaluated and NOT ranked. Which objective a plan pursues is a "
            f"domain question; declare one of {', '.join(sorted(OBJECTIVES))}")
    objective = str(block["objective"])
    if objective not in OBJECTIVES:
        return block, SimulationDecline(
            "no_objective", "planning",
            f"`planning.objective` is {objective!r}, which this engine does "
            f"not implement; known: {', '.join(sorted(OBJECTIVES))}")
    if objective == "clearance_probability" and not block.get("min_severity"):
        return block, SimulationDecline(
            "no_objective", "planning",
            "`clearance_probability` needs `planning.min_severity` to say "
            "WHICH severity must stay clear; a probability of avoiding "
            "an unspecified thing is not a number")
    return block, None


def search(session: Any, topology: Any, *,
           candidates: Optional[Sequence[ActionInstance]] = None,
           horizon_s: float = 1800.0,
           step_s: float = 60.0,
           max_transitions: int = 100_000,
           monte_carlo_samples: int = 100,
           seed: int = 0,
           seed_mode: str = "current",
           file_predictions: bool = False) -> PlanResult:
    """Greedy receding-horizon search over candidate actions.

    Each round rolls every remaining candidate forward ON TOP of the plan
    chosen so far, keeps the best by the declared objective, and advances. The
    do-nothing plan is always a candidate, because *leave it alone* is an
    answer and a planner that cannot return it will always recommend acting.

    AND EXACTLY ONE CANDIDATE IS A FORECAST. `plan` states an
    objective per row -- *throttling to 800 rpm produces 4.33 expected
    findings* -- and filed nothing, so its arithmetic was the one claim in
    this engine that nothing could ever grade. Most rows cannot be graded and
    should not be: a candidate carrying actions describes a world nobody has
    brought about, which `rollout` already refuses by name.

    **`do_nothing` is not a counterfactual.** It is the trajectory that
    obtains if nobody acts, and it is the row every other row is measured
    against -- so it is the one whose projections are filable, and it is
    rolled exactly once (below, before the depth loop) rather than per round.
    Default OFF, like `rollout`'s own flag: filing writes into a durable
    ledger, and a verb that reads as a query should not do that unasked.

    `seed_mode` REACHES EVERY CANDIDATE OR NONE, and that is why it is an
    argument here rather than a setting on the row that files. Under the
    default `current` the world is held still, so a do-nothing trajectory
    moves no value, no declared `gain_sigma:` reaches one, and the filable
    row correctly files nothing -- which is honest and nearly useless.
    `projected` lets each source drift under its own declared `dynamics:`,
    which is what gives the no-action row something to be graded on. Applying
    it to the baseline alone would score one row on a trajectory the others
    never saw, which is the defect that an internal ruling recorded: a number claiming a
    measurement of a plan nobody simulated.
    """
    from . import rollout as _rollout

    result = PlanResult()
    model = getattr(session, "model", None)
    block, objection = read_objective(model)
    if objection is not None:
        result.declines.append(objection)
    else:
        result.objective = str(block["objective"])
        result.direction = OBJECTIVES[result.objective]
        result.min_severity = str(block.get("min_severity", ""))

    max_rollouts = int(block.get("max_rollouts", DEFAULT_MAX_ROLLOUTS))
    max_depth = max(1, int(block.get("max_depth", DEFAULT_MAX_DEPTH)))
    result.max_rollouts = max_rollouts
    result.max_depth = max_depth

    pool: List[ActionInstance] = list(candidates or ())
    if not pool:
        pool, declines = declared_candidates(model)
        result.declines.extend(declines)
    pool = _expand_to_entities(pool, model, dict(
        getattr(session, "entities", {}) or {}))

    if not pool:
        result.declines.append(SimulationDecline(
            "no_candidates", "plan",
            "there is nothing to choose between: no candidate actions were "
            "supplied and no action template declares `candidates:`"))
        return result

    # -- STAMPED HERE, not where the limit was read, and gated on the
    # field being wide enough for the limit to bite.
    #
    # Keyed on the KEY BEING ABSENT rather than on the value being 1: a model
    # declaring `max_depth: 1` has made a choice and is not stamped. And
    # withheld when the pool holds one action, because there is then no pair
    # to try and a deeper search would change nothing -- the same rule
    # `ties_break_toward_the_wider_margin` follows two screens down. A stamp
    # describing a limit that cannot fire is noise wearing a disclosure's
    # clothes.
    if "max_depth" not in block and len(pool) > 1:
        result.assumptions.append(SEARCH_DEPTH_NOT_DECLARED)

    def roll(actions: Sequence[ActionInstance],
             filing: bool = False) -> Optional[PlanCandidate]:
        envelope = _rollout.run(
            session, topology, actions=list(actions),
            horizon_s=horizon_s, step_s=step_s, seed_mode=seed_mode,
            file_predictions=filing,
            max_transitions=max_transitions)
        if filing:
            # read off the rollout that actually filed, not summed
            # across the field. Every other candidate is asked with
            # `filing=False`, so these are the no-action row's figures and
            # nothing else's.
            result.predictions_filed += envelope.predictions_filed
            result.values_without_tolerance += envelope.values_without_tolerance
            result.values_held += envelope.values_held
            result.raced.extend(envelope.raced)
        findings = [f for step in envelope.steps for f in step.findings]
        candidate = PlanCandidate(
            actions=list(actions),
            findings=sorted({f.problem_type for f in findings}),
            # AND THE REFUSED ACTIONS. A candidate whose actions
            # were refused ran as though it had none, and said nothing about
            # why: with `max_depth: 2` the planner offers a second setting of
            # a property already set at the same instant, which the rollout
            # now refuses, and three such candidates came back tied with
            # `do_nothing` carrying an empty `declines`. The refusals were
            # reported at plan level, so the fact was never lost -- it was
            # unattributed, which is the harder version of missing for a
            # reader comparing rows.
            declines=sorted({d.reason for d in envelope.declines}
                            | {d.reason for step in envelope.steps
                               for d in step.declines}
                            | {r.reason for r in envelope.refused_actions}),
            checked={
                "steps_requested": envelope.steps_requested,
                "steps_completed": envelope.steps_completed,
                "transitions_attempted": envelope.transitions_attempted,
                "transitions_applied": envelope.transitions_applied,
            },
            rollouts=1,
        )
        result.refused_actions.extend(envelope.refused_actions)
        result.edges_traversed |= envelope.edges_traversed
        for assumption in envelope.assumptions:
            if assumption not in result.assumptions:
                result.assumptions.append(assumption)
        # The rollout's own attempted count, not the findings it
        # produced. Counting findings made a clean candidate contribute zero
        # however many axioms ran over it -- and made the denominator move
        # with the numerator it is supposed to give meaning to.
        result.invariants += envelope.invariants
        # DID ANY OF THIS PLAN'S ACTIONS ACTUALLY HAPPEN.
        #
        # A candidate whose actions were all refused ran the do-nothing
        # trajectory, so scoring it reported do_nothing's cost under a label
        # naming two actions: measured on the shipped example at `max_depth:
        # 2`, three candidates came back with `transitions_applied: 0` and
        # `objective: 16.0`, tying with the row that really did nothing.
        # Naming the refusal in `declines` made that attributable, which is
        # not the same as making it true -- the number still claimed a
        # measurement of a plan nobody simulated.
        #
        # `do_nothing` is the one candidate for which an empty set is the
        # whole point rather than a failure, so it is asked about its actions
        # rather than its results.
        anything_ran = any(step.actions_applied for step in envelope.steps)
        if result.objective and (not actions or anything_ran):
            value, interval, stamps = score(
                candidate, result.objective, result.min_severity,
                findings, monte_carlo_samples, seed, envelope)
            candidate.objective = value
            candidate.interval = interval
            candidate.assumptions = list(stamps)
            # and HOW CLOSE the call was.
            candidate.margin_sigmas = _closest_call(envelope)
            # and WHICH SIDE, which is a different question.
            # `min_severity` is empty for `expected_findings`, and then
            # `_severity_at_least` is None and `_worst_margin` reports the
            # geometry alone — which is what a tie-break wants.
            candidate.clearance_sigmas = _signed_clearance(
                envelope, findings,
                _severity_at_least(result.min_severity))
            for stamp in stamps:
                if stamp not in result.assumptions:
                    result.assumptions.append(stamp)
        return candidate

    def better(a: PlanCandidate, b: PlanCandidate) -> bool:
        if a.objective is None or b.objective is None:
            return False
        return (a.objective < b.objective if result.direction == "minimise"
                else a.objective > b.objective)

    evaluated: List[PlanCandidate] = []
    chosen: List[ActionInstance] = []
    remaining = list(pool)
    budget = max_rollouts

    # `do nothing` is scored first and stays in the field.
    if budget > 0:
        # AND IT IS THE ONE ROW THAT FILES. Here rather than inside
        # the depth loop, which never builds an empty action list, so the
        # filable trajectory is rolled exactly once and one episode reaches
        # the ledger however deep the search goes.
        baseline = roll((), filing=file_predictions)
        budget -= 1
        result.rollouts_run += 1
        if baseline is not None:
            evaluated.append(baseline)

    for depth in range(max_depth):
        best: Optional[PlanCandidate] = None
        best_action: Optional[ActionInstance] = None
        for action in list(remaining):
            if budget <= 0:
                # ONE decline, carrying the count. `discovery.py` reports
                # `pairs_untested` the same way, and for the same reason: a
                # decline per skipped plan buries the number that matters.
                result.plans_untested += 1
                continue
            candidate = roll(list(chosen) + [action])
            budget -= 1
            result.rollouts_run += 1
            if candidate is None:
                continue
            evaluated.append(candidate)
            if best is None or better(candidate, best):
                best, best_action = candidate, action
        if best is None or best_action is None:
            break
        chosen.append(best_action)
        remaining = [a for a in remaining if a is not best_action]
        if not remaining:
            break

    if result.ranked or result.objective:
        result.assumptions.append(TIES_BREAK_TOWARD_FEWER_ACTIONS)
    if any(c.clearance_sigmas is not None for c in evaluated):
        # stamped only when a spread actually reached a
        # trajectory. Claiming this rule on a model that declared no
        # `gain_sigma:` would describe a tie-break that cannot fire.
        # keyed on the quantity the sort actually reads.
        result.assumptions.append(TIES_BREAK_TOWARD_THE_WIDER_MARGIN)
    if result.objective == "expected_findings":
        # SAID ON THE ENVELOPE, not only in the guide. The figure
        # is the weighted finding count of the MEDIAN trajectory; it is not
        # an average over the declared spread, and the name invites the
        # other reading. Stamped for this objective alone, because
        # `clearance_probability` genuinely does sample.
        result.assumptions.append(OBJECTIVE_EVALUATED_AT_MEDIAN)

    # SAID WHETHER OR NOT IT MATTERS, like the rollout's own
    # counterfactual refusal. A caller who asked to file and got one episode
    # out of five candidates is entitled to the reason the other four are
    # missing; without it, *four plans were not filed* and *four plans failed
    # to file* read identically. ONE decline carrying the count, which is the
    # idiom every other counted refusal in this module follows -- and kept
    # off the per-candidate `declines`, where a by-design exclusion would sit
    # beside real faults and make four healthy rows look damaged.
    result.counterfactuals_not_filed = sum(
        1 for candidate in evaluated if candidate.actions)
    if file_predictions and result.counterfactuals_not_filed:
        result.declines.append(SimulationDecline(
            "counterfactual_not_a_prediction", "file_predictions",
            f"{result.counterfactuals_not_filed} candidate plan(s) carry "
            f"actions, so they describe worlds nobody has brought about and "
            f"nothing was filed for them. Only the no-action row is a "
            f"forecast this engine can later be graded on."))

    if result.plans_untested:
        result.declines.append(SimulationDecline(
            "budget_exhausted", f"max_rollouts={max_rollouts}",
            f"{result.plans_untested} candidate plans were not rolled "
            f"forward: the rollout budget was reached after "
            f"{result.rollouts_run}. Raise `planning.max_rollouts` to widen "
            f"the search."))

    result.ranked = bool(result.objective) and any(
        c.objective is not None for c in evaluated)
    if result.ranked:
        # TIES BREAK TOWARD DOING LESS, and that is a decision rather than an
        # artefact. Sorting on the objective alone left the tie to insertion
        # order -- `do_nothing` is scored first and Python's sort is stable --
        # so the right answer came out for the wrong reason and would have
        # changed the first time the evaluation order did.
        #
        # Fewer actions wins an exact tie because this engine proposes to an
        # operator: when acting buys nothing the model can measure, recommending
        # action is worse than recommending none, and it is the recommendation a
        # person has to carry out.
        #
        # AND THE SAME ARGUMENT ONE STEP FURTHER. Two candidates
        # with the same objective AND the same action count still fell to
        # insertion order, which is the order the author listed them in
        # `candidates:`. Measured on the shipped pump-and-tank model: two
        # candidates tie at `expected_findings` 0.000, one settling 0.03
        # declared spreads from the line that decides whether it files a
        # finding and the other 15.08 clear of it -- and swapping the two
        # entries in the YAML swapped their rank. The engine had already
        # measured the difference and reported it as `margin_sigmas`; it
        # simply did not use it.
        #
        # THE SPREAD IS THE AUTHOR'S, so this is not the engine inventing a
        # preference: `gain_sigma:` was declared, `margin_sigmas` is the
        # distance to the nearest line in units of it, and further from a
        # decision is the same direction `clearance_probability` already
        # optimises. A candidate with no measured margin sorts LAST among its
        # ties -- one this engine could not measure should not displace one it
        # measured as clear -- so a model declaring no spread keeps exactly
        # the order it has today.
        def key(candidate: PlanCandidate):
            value = candidate.objective
            if value is None:
                value = (float("inf") if result.direction == "minimise"
                         else float("-inf"))
            if result.direction == "maximise":
                value = -value
            # the SIGNED headroom, not `margin_sigmas`. See
            # `_signed_clearance`: the absolute closest approach reversed
            # this order when the step size changed, because among breaching
            # candidates it measures where a step fell and not how bad the
            # breach is.
            room = candidate.clearance_sigmas
            widest = (-float(room) if isinstance(room, (int, float))
                      and not isinstance(room, bool) else float("inf"))
            return (value, len(candidate.actions), widest)

        evaluated.sort(key=key)
    result.candidates = evaluated
    return result
