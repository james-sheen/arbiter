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
import math
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
    #:. The response fractions the declared edges actually reached at
    #: this instant. Surfaced because a `0.0` here is the difference between
    #: `the model says nothing moves yet` and `the rollout never asked`, and
    #: the envelope carried no way to tell those apart.
    response_fractions: List[float] = field(default_factory=list)
    #:. entity -> {property -> standard deviation of the imagined
    #: value at this instant}. Present only where a declared `gain_sigma:`
    #: reached it, on the same rule the walk follows: an absent entry means
    #: nobody declared a spread, not that the spread is zero.
    sigma: Dict[str, Dict[str, float]] = field(default_factory=dict)
    #:. What the reasoner ATTEMPTED over this imagined state, taken
    #: from `DetectionResult.evaluations_attempted`. Not derivable from
    #: `findings` and `declines`: an evaluation that ran and found nothing
    #: appears in neither, so summing those two is a denominator that moves
    #: with its own numerator.
    invariants: int = 0


@dataclass
class RolloutResult:
    steps: List[RolloutStep] = field(default_factory=list)
    steps_requested: int = 0
    declines: List[SimulationDecline] = field(default_factory=list)
    refused_actions: List[ActionRefused] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    transitions_attempted: int = 0
    transitions_applied: int = 0
    #:. Sum of the per-step `invariants`, for `CheckedSummary`.
    invariants: int = 0
    #:. True when any declared `gain_sigma:` reached any imagined
    #: value. What it gates is the difference between a clearance figure that
    #: is a PROBABILITY and one that is a boolean wearing a decimal point.
    has_declared_spread: bool = False
    #:. Per-step value predictions filed into the session ledger, and
    #: the values that could not be filed because nobody declared how close
    #: counts as right.
    predictions_filed: int = 0
    values_without_tolerance: int = 0
    #:. Values this rollout did not predict because it was TOLD them:
    #: a projected seed (whose forecast `project` files itself) and anything
    #: an action set. Counted rather than skipped so the three numbers
    #: partition every imagined value -- filed, unfilable, and not ours to
    #: predict. Two of them alone left a reader unable to tell a rollout that
    #: filed little from one that had little to file.
    values_driven: int = 0
    #: The topology this was rolled over. Carried so a figure measured against
    #: a declared bound reads that bound off the same structure the axioms
    #: judged against -- two readings of one declared number are how the two
    #: drift apart.
    topology: Any = None
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


def _clone_history(session: Any) -> Tuple[Any, int, Optional[SimulationDecline]]:
    """A private copy of the session's series, how many readings it took, and
    a decline when it could not be read at all.

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
        # REPORTED, not silently empty. A history without
        # `series_keys` cannot be enumerated, so the rollout steps forward
        # with no imagined past behind it and every windowed axiom declines
        # `insufficient_samples` -- which reads as `the horizon was too
        # short`, a different statement with a different remedy. The count in
        # `history_seeded` made it visible only to a reader who already knew
        # to look.
        return clone, seeded, SimulationDecline(
            "precondition_unmet", "<history>",
            "this session's reading history cannot be enumerated, so the "
            "rollout ran with no imagined past behind it; any windowed axiom "
            "below declines for lack of samples rather than for lack of "
            "horizon")
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
    return clone, seeded, None


def run(session: Any, topology: Any, *,
        actions: Sequence[ActionInstance] = (),
        horizon_s: float = 3600.0,
        step_s: float = 60.0,
        seed_mode: str = "current",
        file_predictions: bool = False,
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

    result.topology = topology
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

    history, seeded, unreadable = _clone_history(session)
    result.history_seeded = seeded
    if unreadable is not None:
        result.declines.append(unreadable)
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
            # TWO REASONS, AND THIS NAMED ONLY ONE. An indicator
            # with no `dynamics:` declared is not a series short of readings,
            # and a remedy that says *collect more data* cannot work: the
            # engine will not choose a model however much arrives. The
            # projector records which it was, and the decline says so.
            projector = getattr(topology, "_last_projector", None)
            undeclared = list(getattr(projector, "undeclared_dynamics", [])
                              or [])
            refusals = list(getattr(projector, "projection_refusals", []) or [])
            if refusals:
                # A DECLARED model whose fit refused. Reported with the
                # projector's own reason, because `model_missing` would send
                # the author to declare something already in the file.
                for location, reason, detail in refusals:
                    result.declines.append(SimulationDecline(
                        reason, location, detail))
            elif undeclared:
                result.declines.append(SimulationDecline(
                    "model_missing", "seed_mode=projected",
                    f"{len(undeclared)} indicator(s) declare no `dynamics:` "
                    f"block, so there is no model to project them with: "
                    f"{', '.join(sorted(undeclared)[:5])}"
                    f"{' and others' if len(undeclared) > 5 else ''}. This is "
                    f"the refusal `project` already makes on the same "
                    f"question; declare a model, or use seed_mode='current'."))
            else:
                result.declines.append(SimulationDecline(
                    "insufficient_samples", "seed_mode=projected",
                    "no entity had the observation history to fit a "
                    "projection, so there is nothing to seed a rollout from; "
                    "use seed_mode='current'"))
            return result
        result.assumptions.append("seeded_from_projection")

    # THE REAL BASELINE, kept apart from the imagined state.
    # `_apply_transitions` measures every delta from the entity's real
    # property and `_finalise_simulation` emits `base + delta`, so holding the
    # same baseline here lets a walk's absolute answer be read back as a
    # CONTRIBUTION and summed across movements that started at different
    # times. Snapshotted BEFORE the projection overlay, so a projected seed is
    # itself a movement that propagates rather than a silent substitution.
    baseline: Dict[str, Dict[str, float]] = {
        entity_id: {
            name: float(value)
            for name, value in (getattr(entity, "properties", {}) or {}).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        for entity_id, entity in entities.items()
    }
    #: (entity, property) -> the instant an action (or a projected seed) last
    #: moved it. The response is re-derived from this instant at every step.
    moved_at: Dict[Tuple[str, str], float] = {}
    #:. (entity, property) -> a reader over the fitted forecast. A
    #: rollout wants the CURVE, not one horizon's answer: every step is a
    #: different instant, and holding one across all of them says the source
    #: finished moving before the first step ran.
    curves: Dict[Tuple[str, str], Any] = {}
    #: The seed's own forecast variance, per step. Held apart from the
    #: transitions' because it GROWS with the horizon and theirs does not.
    seed_variance: Dict[str, Dict[str, float]] = {}
    if seed_mode == "projected":
        curves = dict(getattr(
            getattr(topology, "_last_projector", None),
            "projection_curves", {}) or {})
        for entity_id, values in state.items():
            for name, value in values.items():
                if value != baseline.get(entity_id, {}).get(name, value):
                    moved_at[(entity_id, name)] = 0.0

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

    # A ROLLOUT UNDER ACTIONS IS A COUNTERFACTUAL, NOT A FORECAST.
    # This engine never dispatches: a rollout carrying actions reports
    # `tier: 3` and stops there, so it cannot know whether anyone took them.
    # Filing *what would happen if we throttled the pump* and grading it
    # against a world where nobody throttled the pump would fill the ledger
    # with falsified records that say nothing about the model -- and the
    # calibration figure read off that ledger is the one number meant to say
    # whether this engine's projections can be trusted.
    #
    # Decided ONCE, before the loop, and reported whether or not it fires:
    # a caller who asked to file and got nothing is entitled to the reason.
    filing = bool(file_predictions)
    if filing and schedule:
        filing = False
        result.declines.append(SimulationDecline(
            "counterfactual_not_a_prediction", "file_predictions",
            f"this rollout carries {len(schedule)} scheduled action(s), so it "
            f"describes a world nobody has brought about; nothing was filed. "
            f"Roll forward with no actions to file a forecast this engine can "
            f"later be graded on."))
    if filing and getattr(session, "ledger", None) is None:
        filing = False
        result.declines.append(SimulationDecline(
            "precondition_unmet", "file_predictions",
            "this session has no prediction ledger to file into"))

    for index in range(1, steps + 1):
        at_s = index * step_s
        step = RolloutStep(index=index, at_s=at_s)

        # 1. Actions whose time falls inside this step.
        action_deltas: Dict[str, Dict[str, float]] = {}
        #:. (entity, property) -> the action's OWN scheduled time, not
        #: this step's. An action at `at_s=0` fires in step 1, whose clock
        #: reads 60 s; stamping the movement with the step would charge the
        #: response one step less elapsed time than actually passed, and the
        #: whole trajectory would lag by exactly one step.
        action_times: Dict[Tuple[str, str], float] = {}
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
                action_times[(instance.entity_id, prop)] = max(
                    0.0, float(instance.at_s))

        for entity_id, deltas in action_deltas.items():
            for prop, delta in deltas.items():
                state.setdefault(entity_id, {})
                state[entity_id][prop] = state[entity_id].get(prop, 0.0) + delta

        # 1b. THE SEED AT *THIS* INSTANT, not at the horizon.
        #     `_seed_from_projection` overlays one forecast, taken at the full
        #     `horizon_s`, and every step then read it. Measured on a 60-minute
        #     rollout in 5-minute steps: step one reported the tank at the
        #     value it reaches after an hour, because the source had been
        #     seeded with its 60-minute projection and held there. The same
        #     shape as the frozen transient -- a single-point answer stretched
        #     across a trajectory.
        #
        #     The forecast's own SPREAD comes with it, which it did not
        #     before. A projector returns a distribution and only the median
        #     was kept, so a rollout seeded from a forecast inherited the
        #     number and none of the doubt.
        seed_variance = {}
        for (entity_id, prop), curve in curves.items():
            at = curve(at_s)
            if at is None:
                continue
            value, sigma = at
            state.setdefault(entity_id, {})[prop] = float(value)
            if sigma > 0.0:
                seed_variance.setdefault(entity_id, {})[prop] = float(sigma) ** 2

        # 2. Transitions, re-derived from the instant each source MOVED.
        #
        # THIS RAN ONCE PER MOVEMENT, WITH `horizon_s = step_s`,
        #    AND NEVER AGAIN. A first-order edge therefore froze at whatever
        #    fraction one step's worth of elapsed time reached, for the whole
        #    horizon. With the engine's own edge defaults -- delay 60 s, tau
        #    60 s, exponential -- and the default 60 s step, that fraction is
        #    `response_fraction(60)` = 0: measured, the tank sat at 50.0 for
        #    all sixty steps of an hour-long rollout while the declared
        #    response said 109.8, `transitions_applied` said 1, and nothing
        #    declined. MODELING.md's own `transition:` example (120 / 600 /
        #    exponential) produced the same flat line. `plan` inherited it:
        #    every candidate tied on downstream effect and `do_nothing` won
        #    the tie-break, so the planner recommended inaction because the
        #    dynamics had never run.
        #
        #    WHY RE-RUN THE WALK RATHER THAN ADVANCE AN ACCUMULATOR HERE.
        #    `response_fraction` lives on `TwinEdge` and is the single
        #    implementation of the declared time course; stepping a local
        #    accumulator would put a second copy of it in this module, which
        #    is the one-fact-read-in-two-places shape `builder.py` documents
        #    twice. A walk at `elapsed = at_s - t_moved` already returns the
        #    whole declared trajectory to that instant, superposition
        #    included, because the delta is measured from the real baseline.
        #    So the rollout subtracts the baseline to read a CONTRIBUTION and
        #    sums the contributions of movements that began at different
        #    times. Cost is one walk per distinct movement time per step,
        #    charged against `max_transitions`, which already declines.
        for entity_id, deltas in action_deltas.items():
            for prop in deltas:
                moved_at[(entity_id, prop)] = action_times.get(
                    (entity_id, prop), at_s)

        contributions: Dict[str, Dict[str, float]] = {}
        #: Variances, summed across movement groups. Groups are separate
        #: declared couplings firing from different instants, so their spreads
        #: add the same way the walk adds them WITHIN a group: in variance.
        variances: Dict[str, Dict[str, float]] = {}
        fractions: set = set()
        groups: Dict[float, List[Tuple[str, str]]] = {}
        for key, when in moved_at.items():
            groups.setdefault(when, []).append(key)
        for when in sorted(groups):
            elapsed = at_s - when
            if elapsed < 0:
                continue
            props_by_entity: Dict[str, set] = {}
            for eid, prop in groups[when]:
                props_by_entity.setdefault(eid, set()).add(prop)
            # Only THIS group's properties carry their moved value; every
            # other property sits at its baseline, so it measures a zero
            # delta and contributes nothing to this walk. That is what keeps
            # two movements at different times from being charged the same
            # elapsed time.
            overrides = {
                eid: {
                    name: (value if name in props_by_entity[eid]
                           else baseline.get(eid, {}).get(name, value))
                    for name, value in state.get(eid, {}).items()
                }
                for eid in props_by_entity
            }
            if not overrides:
                continue
            request = TraversalRequest(
                start_nodes=[n for n in starts if n in overrides] or
                sorted(overrides),
                direction=TraversalDirection.FORWARD,
                value_mode=ValueMode.HYPOTHETICAL,
                max_hops=8,
                overrides=overrides,
                horizon_s=max(elapsed, 0.0),
                max_transitions=budget_left,
            )
            traverser = TopologyTraverser(topology)
            # The seed's doubt is an INPUT to the walk, so a transition
            # carries it downstream through its own gain the same way it
            # carries a declared `gain_sigma:`.
            traverser.seed_variance = {
                eid: dict(props) for eid, props in seed_variance.items()}
            walk = traverser.traverse(request)
            result.transitions_attempted += walk.transitions_attempted
            result.transitions_applied += len(walk.transitions_applied)
            budget_left = max(0, budget_left - len(walk.transitions_applied))
            step.transitions_applied += len(walk.transitions_applied)
            for applied in walk.transitions_applied:
                fractions.add(round(float(applied.fraction), 6))
            for decline in walk.simulation_declines:
                if decline not in result.declines:
                    result.declines.append(decline)
            for assumption in walk.assumptions:
                if assumption not in result.assumptions:
                    result.assumptions.append(assumption)
            for eid, values in walk.imagined_values.items():
                for prop, value in values.items():
                    base = baseline.get(eid, {}).get(prop)
                    if base is None:
                        continue
                    bucket = contributions.setdefault(eid, {})
                    bucket[prop] = bucket.get(prop, 0.0) + (
                        float(value) - float(base))
            for eid, spreads in getattr(walk, "imagined_sigma", {}).items():
                for prop, sigma in spreads.items():
                    vbucket = variances.setdefault(eid, {})
                    vbucket[prop] = vbucket.get(prop, 0.0) + float(sigma) ** 2

        step.response_fractions = sorted(fractions)
        for eid, props in seed_variance.items():
            for prop, variance in props.items():
                if variance > 0.0:
                    step.sigma.setdefault(eid, {})[prop] = math.sqrt(variance)
                    result.has_declared_spread = True
        for eid, props in variances.items():
            for prop, variance in props.items():
                if variance > 0.0 and (eid, prop) not in moved_at:
                    step.sigma.setdefault(eid, {})[prop] = math.sqrt(variance)
                    result.has_declared_spread = True

        for eid, props in contributions.items():
            for prop, delta in props.items():
                if (eid, prop) in moved_at:
                    # An action drives this property directly; a transition
                    # into it must not overwrite the value the operator set.
                    continue
                state.setdefault(eid, {})[prop] = (
                    baseline.get(eid, {}).get(prop, 0.0) + delta)

        # 3. Write the imagined state into the clone, at the imagined time.
        stamp = now + timedelta(seconds=at_s)
        for entity_id, values in state.items():
            for prop, value in values.items():
                history.add(entity_id, prop, float(value), stamp)

        # 4. The eight axioms, over the imagined state and the imagined past.
        findings, declines, attempted = _evaluate(
            session, state, entities, history)
        step.findings.extend(findings)
        step.declines.extend(declines)
        step.invariants = attempted
        result.invariants += attempted

        step.values = {eid: dict(vals) for eid, vals in state.items()}
        result.steps.append(step)

        # 5. FILE THIS INSTANT AS A PREDICTION, if asked and if the
        #    model declared enough to make it falsifiable. AFTER `step.values`
        #    is assigned, which is the whole of what this reads: placed before
        #    it, the filer saw an empty mapping and filed nothing while
        #    reporting nothing missing, because there was nothing to miss.
        if filing:
            _file_step(session, result, step, at_s, moved_at)

    if filing and result.values_without_tolerance:
        # ONE decline carrying the count, which is the rule every other
        # counted refusal in this module follows: a decline per value makes
        # one missing declaration look like hundreds of different problems.
        result.declines.append(SimulationDecline(
            "no_declared_tolerance", "file_predictions",
            f"{result.values_without_tolerance} imagined value(s) were not "
            f"filed because no `gain_sigma:` reached them, so there is no "
            f"declared window inside which a later reading would count as "
            f"confirming them. Declare a spread on the transition that drives "
            f"the property to make its projection gradeable."))

    # De-duplicated: the per-step walk stamps its own, and a stamp repeated
    # reads as two separate assumptions rather than one made twice.
    for assumption in ("exogenous_inputs_held",
                       "no_action_scheduled" if not schedule else ""):
        if assumption and assumption not in result.assumptions:
            result.assumptions.append(assumption)
    return result


def _evaluate(session: Any, state: Dict[str, Dict[str, float]],
              entities: Dict[str, Any],
              history: Any) -> Tuple[List[Any], List[SimulationDecline], int]:
    """Run the reasoner over the imagined state, with the imagined history.

    SHADOW ENTITIES CARRY THE IMAGINED STATE, WHICH IS EVERY NUMERIC PROPERTY.
    this said `imagined properties only`, borrowing
    `forecast/shadow.py`'s rule, and that is not what a rollout does. A
    shadow entity exists at one horizon instant with only the half somebody
    forecast, so filling the rest from today's readings would let a balance
    close across two different times. A ROLLOUT is a different object: its
    state is seeded from the present and then MOVED, so every numeric property
    is part of the imagined state at that step, whether an action or a
    transition changed it or it simply held. Properties that are not numeric
    are absent, which is why an axiom reading a string declines inside a
    rollout where it would not live.

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
            "imagined state")], 0

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
        return [], [], 0

    findings: List[Any] = []
    declines: List[SimulationDecline] = []
    try:
        outcome = reasoner.detect(shadows, session.graph, history)
    except Exception as exc:  # noqa: BLE001 - a decline must not become a crash
        return [], [SimulationDecline(
            "internal_error", "<reasoner>",
            f"the reasoner raised {type(exc).__name__} over the imagined "
            f"state: {exc!r}")], 0

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
    return findings, declines, int(
        getattr(outcome, "evaluations_attempted", 0) or 0)


def _file_step(session: Any, result: 'RolloutResult',
               step: 'RolloutStep', at_s: float,
               driven: Dict[Tuple[str, str], float]) -> None:
    """File one imagined instant as a falsifiable value prediction.

    TOLERANCE IS NOT INVENTED HERE. `PredictionLedger.record_value_prediction`
    requires one and says why: a point prediction with no resolution cannot be
    graded, and the ledger will not guess. Neither will this. The resolution
    comes from the author's own declared `gain_sigma:` -- the 95% band around
    the projected value -- which is the same rule applies to a floor:
    a number that decides whether something counts as wrong is a
    specification, and one nobody wrote down is an assumption wearing a
    decimal point.

    So a value carrying a declared spread is filed, and a value without one is
    COUNTED and declined by name rather than filed against a made-up window.
    """
    ledger = getattr(session, "ledger", None)
    if ledger is None:
        return
    for entity_id, values in step.values.items():
        spreads = step.sigma.get(entity_id, {})
        for prop, value in values.items():
            if (entity_id, prop) in driven:
                result.values_driven += 1
                # AN INPUT, NOT A PREDICTION OF THIS ROLLOUT'S.
                # A projected seed is the `project` verb's forecast, and that
                # verb already files it as a distribution record. Filing it
                # again here would score one forecast twice in the calibration
                # and make a rollout look better or worse than it is by
                # however many sources it happened to be seeded from. An
                # action-set value is not a prediction at all: it is what the
                # caller said they would do.
                continue
            sigma = spreads.get(prop)
            if not sigma:
                result.values_without_tolerance += 1
                continue
            try:
                ledger.record_value_prediction(
                    entity_id=entity_id,
                    property_name=prop,
                    predicted_value=float(value),
                    # The declared 95% band. Stated as the tolerance AND as
                    # the confidence below, so the two cannot disagree.
                    tolerance=1.96 * float(sigma),
                    horizon_s=float(at_s),
                    confidence=0.95,
                )
                result.predictions_filed += 1
            except Exception:  # noqa: BLE001 - a ledger refusal is not a crash
                result.values_without_tolerance += 1


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
