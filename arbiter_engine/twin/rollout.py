"""A multi-step rollout: the model run forward under actions.

Stage 1 made one hop of a what-if compute a downstream value. This
steps that forward in time, lets actions enter at the moment they are
scheduled, and evaluates the eight axioms over each imagined state -- so the
question a caller can ask moves from *what does this become* to *what happens,
and when, and does it breach anything on the way*.

WHY EACH STEP WRITES AN IMAGINED OBSERVATION. STABILITY, HOMEOSTASIS,
MONOTONICITY and the windowed half of RESPONSIVENESS read an
`ObservationHistory`, not a value. A rollout that produced only end states
could never ask them anything. So each step writes its imagined state into a
CLONE of the session's history at the imagined timestamp, and a windowed axiom
over the imagined series behaves exactly as it would over a real one --
including declining `insufficient_samples` when the horizon is shorter than
the window. That decline is the correct answer to *would this be stable* asked
over ten minutes of a thirty-minute window, and it is not suppressed.

THE CLONE IS NEVER THE LIVE HISTORY. An imagined observation written into the
session would be indistinguishable from a reading afterwards, and every
subsequent `check` would be judging a future somebody asked about as though it
had happened. The clone is built per rollout and discarded with the envelope.

WHAT THIS DOES NOT DO. It does not dispatch, approve, or rank. A rollout
reports; `traverse` already classifies overrides as Tier 3 and this carries
the same classification. Choosing BETWEEN rollouts is planning, needs a
declared objective, and is not in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .actions import (ActionInstance, ActionRefused, ActionTemplate,
                      deltas_for, load_templates, resolve)
from .topology import (SimulationDecline, TraversalDirection,
                       TraversalRequest, TransitionApplied, ValueMode)
from .traverser import IMAGINED_PREFIX, TopologyTraverser

#: A rollout with no step is not a rollout. Guarded rather than defaulted
#: because a zero or negative step is an author error, and silently
#: substituting one would hide it.
MIN_STEP_S = 1e-6

#: How far back the clone copies. Wide on purpose: a declared `window:` is the
#: thing being honoured, and truncating the seed would make a windowed axiom
#: decline `insufficient_samples` inside a rollout for a series that has
#: plenty -- a decline caused by the simulator rather than by the question.
_CLONE_WINDOW = timedelta(days=3650)


@dataclass
class RolloutStep:
    """One imagined instant."""
    index: int
    at_s: float
    values: Dict[str, Dict[str, float]] = field(default_factory=dict)
    findings: List[Any] = field(default_factory=list)
    declines: List[SimulationDecline] = field(default_factory=list)
    actions_applied: List[str] = field(default_factory=list)
    transitions_applied: int = 0


@dataclass
class RolloutResult:
    steps: List[RolloutStep] = field(default_factory=list)
    steps_requested: int = 0
    declines: List[SimulationDecline] = field(default_factory=list)
    refused_actions: List[ActionRefused] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    transitions_attempted: int = 0
    transitions_applied: int = 0
    #: Real readings copied into the imagined timeline before stepping. A
    #: reported COUNT rather than a silent seed: a windowed axiom over an
    #: imagined series behaves completely differently depending on whether the
    #: real past came with it, and a reader cannot tell from the findings.
    history_seeded: int = 0
    tier: int = 1
    tier_reason: str = ""

    @property
    def steps_completed(self) -> int:
        return len(self.steps)


def _clone_history(session: Any) -> Tuple[Any, int]:
    """A private copy of the session's series, and how many readings it took.

    Copied rather than shared. `session.reading_history()` is what the model
    says the feed MEANS, and that is the right thing to seed from -- a
    windowed axiom inside a declared calendar must see the same window in the
    rollout that it sees live.
    """
    from ..history.observation import InMemoryObservationHistory
    clone = InMemoryObservationHistory()
    seeded = 0
    source = session.reading_history()
    if not hasattr(source, "series_keys"):
        return clone, seeded
    # `get_values(entity, property, window)` is the per-SERIES reader and
    # returns `(timestamp, value)` pairs. `get_observations` takes a time
    # range, not a property, and reading it as a per-series call is a
    # TypeError that only fires once a session actually holds history -- which
    # a first test with no observations will never reach.
    for key in source.series_keys():
        try:
            entity_id, property_name = key
        except (TypeError, ValueError):
            continue
        # NOT WRAPPED IN A BARE `except`. It was, and that is what made the
        # wrong reader invisible: `get_observations(entity, property)` raises
        # TypeError -- its second argument is a START TIME -- and the except
        # turned that into an empty clone. Every test still passed, because a
        # rollout with no seeded history still completes its steps; only a
        # windowed axiom would have noticed, and quietly. A history this
        # engine cannot read is worth a raised error, which `api.rollout`
        # catches at its boundary and reports as `internal_error`.
        for when, value in source.get_values(
                entity_id, property_name, _CLONE_WINDOW):
            clone.add(entity_id, property_name, value, when)
            seeded += 1
    return clone, seeded


def run(session: Any, topology: Any, *,
        actions: Sequence[ActionInstance] = (),
        horizon_s: float = 3600.0,
        step_s: float = 60.0,
        seed_mode: str = "current",
        max_transitions: int = 100_000,
        start_nodes: Optional[Sequence[str]] = None) -> RolloutResult:
    """Step the model forward, evaluating the axioms on each imagined state."""
    result = RolloutResult()

    if step_s <= MIN_STEP_S:
        result.declines.append(SimulationDecline(
            "malformed_request", f"step_s={step_s}",
            "a rollout needs a positive step; it is not defaulted because a "
            "non-positive one is an author error"))
        return result
    if horizon_s <= 0:
        result.declines.append(SimulationDecline(
            "malformed_request", f"horizon_s={horizon_s}",
            "a rollout over no time has nothing to report"))
        return result

    templates, refused = load_templates(getattr(session, "model", None))
    result.refused_actions.extend(refused)

    entities = dict(getattr(session, "entities", {}) or {})
    schedule: List[Tuple[ActionInstance, ActionTemplate]] = []
    for instance in actions or ():
        template, refusal = resolve(instance, templates, entities)
        if refusal is not None:
            result.refused_actions.append(refusal)
            continue
        schedule.append((instance, template))

    if schedule:
        # `traverser.py` classifies HYPOTHETICAL + overrides as Tier 3
        # (operator confirmation). An action is the same claim about the
        # world, so it carries the same tier rather than a new scale.
        result.tier = 3
        result.tier_reason = "actions_present"

    history, seeded = _clone_history(session)
    result.history_seeded = seeded
    now = _now(session)

    # The imagined state, as absolute values per entity. Seeded from the
    # present, or from the projections if the caller asked for them.
    state: Dict[str, Dict[str, float]] = {}
    for entity_id, entity in entities.items():
        state[entity_id] = {
            name: float(value)
            for name, value in (getattr(entity, "properties", {}) or {}).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    if seed_mode == "projected":
        seeded = _seed_from_projection(topology, state)
        if not seeded:
            result.declines.append(SimulationDecline(
                "insufficient_samples", "seed_mode=projected",
                "no entity had the observation history to fit a projection, "
                "so there is nothing to seed a rollout from; use "
                "seed_mode='current'"))
            return result
        result.assumptions.append("seeded_from_projection")

    steps = int(horizon_s // step_s)
    result.steps_requested = steps
    if steps <= 0:
        result.declines.append(SimulationDecline(
            "malformed_request", f"horizon_s={horizon_s}, step_s={step_s}",
            "the step is longer than the horizon, so no step fits inside it"))
        return result

    # AN ACTION THAT CANNOT FIRE IS REFUSED, NOT DROPPED. Both of these were
    # silently accepted and silently never applied: the envelope reported
    # `actions_scheduled: 1`, `actions_refused: 0`, and a flat trajectory that
    # was indistinguishable from doing nothing on purpose.
    in_horizon: List[Tuple[ActionInstance, ActionTemplate]] = []
    for instance, template in schedule:
        location = f"{instance.template}@{instance.entity_id}"
        if instance.at_s < 0:
            result.refused_actions.append(ActionRefused(
                "malformed_action", location,
                f"at_s={instance.at_s} is before the rollout starts"))
            continue
        if instance.at_s > steps * step_s:
            result.refused_actions.append(ActionRefused(
                "malformed_action", location,
                f"at_s={instance.at_s} is past the last step at "
                f"{steps * step_s}s, so this action never enters the "
                f"rollout; lengthen horizon_s or move the action"))
            continue
        in_horizon.append((instance, template))
    schedule = in_horizon

    budget_left = max(0, int(max_transitions))
    starts = list(start_nodes or sorted(entities))

    for index in range(1, steps + 1):
        at_s = index * step_s
        step = RolloutStep(index=index, at_s=at_s)

        # 1. Actions whose time falls inside this step.
        action_deltas: Dict[str, Dict[str, float]] = {}
        for instance, template in schedule:
            # Half-open on the left EXCEPT for the first step, which is closed
            # at zero. `at_s=0` -- *do this now* -- is the most natural thing a
            # caller writes, and with a uniformly half-open window it fell
            # through every step and fired in none of them: the rollout
            # reported `actions_scheduled: 1`, `actions_refused: 0`, and a
            # flat trajectory. An action that is accepted and silently never
            # applied is worse than one that is refused.
            lower = at_s - step_s
            in_window = (instance.at_s <= at_s and
                         (instance.at_s >= lower if index == 1
                          else instance.at_s > lower))
            if not in_window:
                continue

            deltas, assumptions, refusals = deltas_for(
                instance, template, state.get(instance.entity_id, {}))
            result.refused_actions.extend(refusals)
            for assumption in assumptions:
                if assumption not in result.assumptions:
                    result.assumptions.append(assumption)
            if not deltas:
                continue
            step.actions_applied.append(
                f"{instance.template}@{instance.entity_id}")
            if template.settle_s > step_s:
                # The actuator is slower than the step. Reported rather than
                # ramped: ramping would be the engine choosing a trajectory
                # the model did not declare.
                result.declines.append(SimulationDecline(
                    "settle_exceeds_step",
                    f"{instance.template}@{instance.entity_id}",
                    f"settle_s={template.settle_s} is longer than "
                    f"step_s={step_s}; the effect is applied as a step at "
                    f"t={at_s}s and the ramp is not modelled"))
            bucket = action_deltas.setdefault(instance.entity_id, {})
            for prop, delta in deltas.items():
                bucket[prop] = bucket.get(prop, 0.0) + delta

        for entity_id, deltas in action_deltas.items():
            for prop, delta in deltas.items():
                state.setdefault(entity_id, {})
                state[entity_id][prop] = state[entity_id].get(prop, 0.0) + delta

        # 2. Transitions, for one step's worth of elapsed time. Reuses the
        #    Stage 1 traversal so there is one implementation of a gain.
        moved = {eid: props for eid, props in action_deltas.items() if props}
        if moved or index == 1:
            overrides = {
                entity_id: dict(values)
                for entity_id, values in state.items()
                if entity_id in (moved or {})
            }
            if overrides:
                request = TraversalRequest(
                    start_nodes=[n for n in starts if n in overrides] or
                    sorted(overrides),
                    direction=TraversalDirection.FORWARD,
                    value_mode=ValueMode.HYPOTHETICAL,
                    max_hops=8,
                    overrides=overrides,
                    horizon_s=step_s,
                    max_transitions=budget_left,
                )
                walk = TopologyTraverser(topology).traverse(request)
                result.transitions_attempted += walk.transitions_attempted
                result.transitions_applied += len(walk.transitions_applied)
                budget_left = max(
                    0, budget_left - len(walk.transitions_applied))
                step.transitions_applied = len(walk.transitions_applied)
                for decline in walk.simulation_declines:
                    if decline not in result.declines:
                        result.declines.append(decline)
                for assumption in walk.assumptions:
                    if assumption not in result.assumptions:
                        result.assumptions.append(assumption)
                for entity_id, values in walk.imagined_values.items():
                    for prop, value in values.items():
                        state.setdefault(entity_id, {})[prop] = float(value)

        # 3. Write the imagined state into the clone, at the imagined time.
        stamp = now + timedelta(seconds=at_s)
        for entity_id, values in state.items():
            for prop, value in values.items():
                history.add(entity_id, prop, float(value), stamp)

        # 4. The eight axioms, over the imagined state and the imagined past.
        findings, declines = _evaluate(session, state, entities, history)
        step.findings.extend(findings)
        step.declines.extend(declines)

        step.values = {eid: dict(vals) for eid, vals in state.items()}
        result.steps.append(step)

    # De-duplicated: the per-step walk stamps its own, and a stamp repeated
    # reads as two separate assumptions rather than one made twice.
    for assumption in ("exogenous_inputs_held",
                       "no_action_scheduled" if not schedule else ""):
        if assumption and assumption not in result.assumptions:
            result.assumptions.append(assumption)
    return result


def _evaluate(session: Any, state: Dict[str, Dict[str, float]],
              entities: Dict[str, Any],
              history: Any) -> Tuple[List[Any], List[SimulationDecline]]:
    """Run the reasoner over the imagined state, with the imagined history.

    SHADOW ENTITIES CARRY IMAGINED PROPERTIES ONLY. `forecast/shadow.py`
    states the rule and the reason: filling the unimagined half from today's
    readings would let a balance close because one side came from the present,
    and the answer would look exactly like a real one.

    THE HISTORY IS PASSED, AND THAT IS THE DIFFERENCE FROM SHADOW. The shadow
    pass hands the reasoner an empty history on purpose -- its entities exist
    at one horizon instant, so a windowed axiom has nothing to read and
    declines. A rollout has the opposite situation: it has written a whole
    imagined SERIES, step by step, at imagined timestamps. So STABILITY,
    HOMEOSTASIS and MONOTONICITY can be asked, and when the horizon is shorter
    than a declared window they decline `insufficient_samples` -- the correct
    answer to a question asked over too little time, and not suppressed.
    """
    from ..interfaces import Entity

    reasoner = getattr(session, "reasoner", None)
    if reasoner is None:
        return [], [SimulationDecline(
            "precondition_unmet", "<session>",
            "this session has no reasoner, so no axiom can be run over the "
            "imagined state")]

    shadows: List[Any] = []
    for entity_id, values in state.items():
        real = entities.get(entity_id)
        if real is None or not values:
            continue
        shadows.append(Entity(
            id=entity_id,
            type=getattr(real, "type", ""),
            properties=dict(values),
            name=getattr(real, "name", "") or "",
        ))
    if not shadows:
        return [], []

    findings: List[Any] = []
    declines: List[SimulationDecline] = []
    try:
        outcome = reasoner.detect(shadows, session.graph, history)
    except Exception as exc:  # noqa: BLE001 - a decline must not become a crash
        return [], [SimulationDecline(
            "internal_error", "<reasoner>",
            f"the reasoner raised {type(exc).__name__} over the imagined "
            f"state: {exc!r}")]

    # BOTH LEGS. `DetectionResult` separates `problems` from `warnings`, and
    # reading only the first drops every warning-severity finding: measured on
    # a node at 88% against a declared `warning: 80`, `check` reported
    # `threshold_warning:memory_used_pct` and a rollout over the identical
    # values reported nothing at all. `check` has always summed the two and
    # `envelope.py` does too; this reader did not, and a planner built on it
    # ranked a plan that causes a warning level with a plan that causes
    # nothing.
    everything = (list(getattr(outcome, "problems", []) or [])
                  + list(getattr(outcome, "warnings", []) or []))
    for problem in everything:
        problem.problem_type = f"{IMAGINED_PREFIX}{problem.problem_type}"
        if isinstance(getattr(problem, "evidence", None), dict):
            problem.evidence["imagined"] = True
        findings.append(problem)
    for record in getattr(outcome, "not_evaluated", []) or []:
        reason = getattr(record.reason, "value", None) or str(record.reason)
        declines.append(SimulationDecline(
            reason,
            f"{getattr(record, 'entity_id', '?')}."
            f"{getattr(record, 'indicator', '?')}",
            detail=getattr(record, "detail", None) or ""))
    return findings, declines


def _now(session: Any):
    from ..clock import now_utc
    return now_utc()


def _seed_from_projection(topology: Any,
                          state: Dict[str, Dict[str, float]]) -> bool:
    """Overlay whatever `project_values` fitted. True if anything was fitted."""
    seeded = False
    for entity_id, node in getattr(topology, "nodes", {}).items():
        for prop, projected in (
                getattr(node, "projected_values", {}) or {}).items():
            value = getattr(projected, "value", None)
            if isinstance(value, (int, float)):
                state.setdefault(entity_id, {})[prop] = float(value)
                seeded = True
    return seeded
