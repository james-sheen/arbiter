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
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..types import Severity
from .actions import ActionInstance, ActionRefused, load_templates
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
    invariants: int = 0


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
        applies_to = getattr(template, "applies_to", "") if template else ""
        for entity_id, entity in sorted(entities.items()):
            if applies_to and getattr(entity, "type", None) != applies_to:
                continue
            out.append(ActionInstance(
                template=candidate.template, entity_id=entity_id,
                parameters=dict(candidate.parameters), at_s=candidate.at_s))
    return out


def score(candidate: PlanCandidate, objective: str, min_severity: str,
          findings: Sequence[Any], monte_carlo_samples: int,
          seed: int) -> Tuple[Optional[float], Optional[Tuple[float, float]],
                              List[str]]:
    """The objective value for one rolled-forward candidate."""
    assumptions: List[str] = []
    if objective == "expected_findings":
        return (sum(severity_weight(getattr(f, "severity", None))
                    for f in findings), None, assumptions)

    # clearance_probability: did the horizon stay clear of `min_severity`?
    #
    # The transition model is DETERMINISTIC, so every sample of one candidate
    # is the same sample and the interval collapses to a point. That is the
    # honest report and it is stamped: a reader seeing [1.0, 1.0] is entitled
    # to know the band is narrow because nothing is random here, not because
    # the sample count was large.
    from .monte_carlo_predictor import (MonteCarloPredictionRequest,
                                        MonteCarloPredictor)

    threshold = _severity_at_least(min_severity)
    breached = any(
        _severity_at_least(getattr(
            getattr(f, "severity", None), "value", "")) is not None
        and getattr(f, "severity").priority_score <= threshold
        for f in findings) if threshold is not None else False

    def step(_snapshot, _rng):
        return {"clear": not breached}

    distribution = MonteCarloPredictor(seed=seed).predict(
        None, step,
        MonteCarloPredictionRequest(outcome_names=["clear"],
                                    n_samples=monte_carlo_samples, seed=seed))
    outcome = distribution.get("clear")
    assumptions.append("deterministic_transitions")
    if outcome is None:
        return None, None, assumptions
    return (outcome.estimated_probability,
            outcome.confidence_interval_95, assumptions)


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
           seed: int = 0) -> PlanResult:
    """Greedy receding-horizon search over candidate actions.

    Each round rolls every remaining candidate forward ON TOP of the plan
    chosen so far, keeps the best by the declared objective, and advances. The
    do-nothing plan is always a candidate, because *leave it alone* is an
    answer and a planner that cannot return it will always recommend acting.
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

    def roll(actions: Sequence[ActionInstance]) -> Optional[PlanCandidate]:
        envelope = _rollout.run(
            session, topology, actions=list(actions),
            horizon_s=horizon_s, step_s=step_s, seed_mode="current",
            max_transitions=max_transitions)
        findings = [f for step in envelope.steps for f in step.findings]
        candidate = PlanCandidate(
            actions=list(actions),
            findings=sorted({f.problem_type for f in findings}),
            declines=sorted({d.reason for d in envelope.declines}
                            | {d.reason for step in envelope.steps
                               for d in step.declines}),
            checked={
                "steps_requested": envelope.steps_requested,
                "steps_completed": envelope.steps_completed,
                "transitions_attempted": envelope.transitions_attempted,
                "transitions_applied": envelope.transitions_applied,
            },
            rollouts=1,
        )
        result.refused_actions.extend(envelope.refused_actions)
        for assumption in envelope.assumptions:
            if assumption not in result.assumptions:
                result.assumptions.append(assumption)
        result.invariants += len(findings)
        if result.objective:
            value, interval, stamps = score(
                candidate, result.objective, result.min_severity,
                findings, monte_carlo_samples, seed)
            candidate.objective = value
            candidate.interval = interval
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
        baseline = roll(())
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
        result.assumptions.append("ties_break_toward_fewer_actions")

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
        def key(candidate: PlanCandidate):
            value = candidate.objective
            if value is None:
                value = (float("inf") if result.direction == "minimise"
                         else float("-inf"))
            if result.direction == "maximise":
                value = -value
            return (value, len(candidate.actions))

        evaluated.sort(key=key)
    result.candidates = evaluated
    return result
