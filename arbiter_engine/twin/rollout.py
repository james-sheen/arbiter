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
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

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
    #:. entity -> {property -> the couplings that drove this value},
    #: each as `relation:from->to`. Taken from the per-source spread
    #: breakdown the walk already computes, so it costs nothing to derive and
    #: cannot drift from what actually contributed. It is what lets a
    #: coupling's confirm rate be over ITS OWN projections: the report used
    #: to resolve the entities of a rule's target type and match on the
    #: target property alone, so two rules into one property each claimed
    #: every record and four records produced eight attributions.
    drivers: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
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
    #:. ONE id for everything this rollout files. A rollout is one
    #: trajectory however many instants it reports, so the records it files
    #: are one episode -- which is what `traversal_id` has always meant on an
    #: impact record, and what a calibration needs in order to say whether
    #: `confirm_rate: 1.0` came from twelve trials or from one.
    episode_id = str(uuid.uuid4())

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
    #: (entity, property) -> {instant: the delta attributable to THAT
    #: instant}. The response is re-derived from each instant at every step
    #: and the contributions superpose.
    #:
    #:. This held ONE instant per property -- the latest movement's --
    #: while `state` held the cumulative delta, so a property that moved twice
    #: was walked once as though the whole displacement had arrived at the
    #: second instant. The progress the first movement had made along its own
    #: response was discarded and the trajectory dropped back to its baseline:
    #: measured on a 120/600 exponential edge, +500 rpm at t=0 then +100 rpm
    #: at t=1800 put the tank at 59.33 and then at exactly 50.00, a 9.50-point
    #: collapse the simulator invented and a HOMEOSTASIS axiom then reported.
    #: The steady state was right throughout, which is why a test that checks
    #: where a trajectory ENDS could not see it.
    movements: Dict[Tuple[str, str], Dict[float, float]] = {}
    #:. (entity, property) -> a reader over the fitted forecast. A
    #: rollout wants the CURVE, not one horizon's answer: every step is a
    #: different instant, and holding one across all of them says the source
    #: finished moving before the first step ran.
    curves: Dict[Tuple[str, str], Any] = {}
    #:. (entity, property) pairs an action has moved, cumulative
    #: across steps. A forecast describes the unmanaged trajectory, so it
    #: stops being overlaid on a property somebody has intervened on.
    acted: Set[Tuple[str, str]] = set()
    #:. The forecast's own spread, and how much of it each movement
    #: of the property carries. A seeded property that is then acted on has
    #: its action's delta measured FROM the seeded value, so the two
    #: movements depend on the one forecast with OPPOSITE signs and the
    #: doubt cancels exactly as far as the action pins it: `set` leaves
    #: none, `add` leaves all of it, `scale k` leaves k times it. Without
    #: the sign both movements propagated the same band and a rollout
    #: reported sqrt(2) times a doubt that should have been gone.
    seed_sigma: Dict[Tuple[str, str], float] = {}
    seed_sensitivity: Dict[Tuple[str, str], Dict[float, float]] = {}
    seed_carried: Dict[Tuple[str, str], float] = {}
    if seed_mode == "projected":
        curves = dict(getattr(
            getattr(topology, "_last_projector", None),
            "projection_curves", {}) or {})
        # EVERY SEEDED PROPERTY IS A MOVEMENT, including one whose
        # forecast says it will not move. This compared the seed against the
        # reading and registered only the ones that differed, which loses the
        # `random_walk` case entirely: that model's median IS the last
        # observation, so an entity whose property was set from its last
        # reading seeds a value equal to its baseline, bit for bit. The band
        # then never left the source, the declared coupling never ran, and --
        # worst of the three -- the seed fell out of `values_driven`, which is
        # the guard that stops `_file_step` filing `project`'s own forecast a
        # second time under this rollout's name.
        for entity_id, prop in seeded:
            seed = state.get(entity_id, {}).get(prop)
            if seed is None:
                continue
            # Defaulting the baseline to the SEED, not to zero: a property
            # with no baseline has not moved, and calling the whole seeded
            # value a movement would propagate an entity's absolute reading
            # as though it were a change.
            movements.setdefault((entity_id, prop), {})[0.0] = float(
                seed) - baseline.get(entity_id, {}).get(prop, float(seed))

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

        # 1. THE SEED AT *THIS* INSTANT, not at the horizon.
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
        # AND IT RUNS BEFORE THE ACTIONS, not after.
        #     It used to overwrite them: a property carrying a `dynamics:`
        #     block could not be acted on at all, because this loop reassigned
        #     `state` from the curve every step. Measured with the pump SET to
        #     2500 rpm, `seed_mode='projected'` reported the pump at 1885.798
        #     -- its last observation -- the tank at its untouched baseline,
        #     and `throttle@pump1` in `actions_applied`, with nothing
        #     declined. The drift reconciliation below then zeroed the
        #     action's own movement to agree with that state, so the
        #     decomposition was consistent and consistently wrong.
        #
        #     A projection is fitted from history and cannot know about an
        #     action scheduled in the future, so it describes the UNMANAGED
        #     trajectory. The two compose with nobody guessing: the forecast
        #     governs a property up to the instant it is acted on, and the
        #     action governs it from there. Hence the order, and hence
        #     `acted` -- once an action has moved a property, no later step
        #     re-seeds it, and the movement registered at t=0 keeps the
        #     displacement the forecast had reached when the intervention
        #     landed, so the target's response to both still superposes.
        for (entity_id, prop), curve in curves.items():
            if (entity_id, prop) in acted:
                continue
            at = curve(at_s)
            if at is None:
                continue
            value, sigma = at
            state.setdefault(entity_id, {})[prop] = float(value)
            # The seed is one movement, at t=0, whose DELTA is re-read from
            # the curve at every step. Registered here as well as at the
            # overlay so a curve that starts flat and moves later is still a
            # movement when it does.
            movements.setdefault((entity_id, prop), {})[0.0] = float(
                value) - baseline.get(entity_id, {}).get(prop, float(value))
            if sigma > 0.0:
                seed_sigma[(entity_id, prop)] = float(sigma)
                seed_sensitivity.setdefault((entity_id, prop), {})[0.0] = 1.0
                seed_carried[(entity_id, prop)] = 1.0

        # 1b. Actions whose time falls inside this step.
        action_deltas: Dict[str, Dict[str, float]] = {}
        #:. (entity, property) -> the action's OWN scheduled time, not
        #: this step's. An action at `at_s=0` fires in step 1, whose clock
        #: reads 60 s; stamping the movement with the step would charge the
        #: response one step less elapsed time than actually passed, and the
        #: whole trajectory would lag by exactly one step.
        action_times: Dict[Tuple[str, str], float] = {}
        #:. (entity, property) -> [(effect, value, label)] for EVERY
        #: effect this step carries, additive ones included.
        #:
        #: Recording only the non-additive ones was the first version and it
        #: left a hole one review found before any test did: an `add` was
        #: summed into the bucket on its way past, so `add 100` beside
        #: `set 1500` on a pump at 1000 came out at 1600 -- neither value,
        #: unrefused, and reachable whenever two templates touch one property.
        #: The rule is about the SET of effects meeting at one instant, so the
        #: set has to be complete before anything is decided.
        intents: Dict[Tuple[str, str], List[Tuple[str, float, str]]] = {}
        #:. (label, the (entity, property) pairs that instance asked
        #: for), one entry per instance that got this far. `actions_applied`
        #: is rebuilt from it once the refusals are known, so an instance
        #: survives when ANY of its effects did -- an action touching two
        #: properties, one of which collided, still happened.
        intended: List[Tuple[str, Set[Tuple[str, str]]]] = []
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

            deltas, assumptions, refusals, effects = deltas_for(
                instance, template, state.get(instance.entity_id, {}))
            result.refused_actions.extend(refusals)
            for assumption in assumptions:
                if assumption not in result.assumptions:
                    result.assumptions.append(assumption)
            if not deltas:
                continue
            # RECORDED PER INSTANCE, not per label. The label is
            # `template@entity` and carries neither the parameters nor
            # `at_s`, so two instances of one template on one entity share
            # it. This list was appended to once per instance -- twice -- and
            # the refusal below removed once per DISTINCT label, over a set,
            # so one occurrence survived a refusal that applied nothing: a
            # step in which the pump never moved reported `throttle_pump@
            # pump1` as applied, in the one field a caller reads to find out
            # what happened.
            intended.append((f"{instance.template}@{instance.entity_id}",
                             {(instance.entity_id, prop) for prop in deltas}))

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
            label = f"{instance.template}@{instance.entity_id}"
            bucket = action_deltas.setdefault(instance.entity_id, {})
            for prop, delta in deltas.items():
                kind, value = effects.get(prop, ("add", delta))
                # Held back, all of them, and resolved once every instance in
                # this step has been read: this loop sees one at a time and
                # the rule needs the whole set.
                intents.setdefault(
                    (instance.entity_id, prop), []).append(
                        (kind, value, label))
                action_times[(instance.entity_id, prop)] = max(
                    0.0, float(instance.at_s))

        # RESOLVE THE NON-ADDITIVE EFFECTS, one property at a time.
        #
        # `at_s` is the only ordering this engine has. Two effects sharing it
        # are simultaneous, and list position is an accident of how a caller
        # built the sequence, so it cannot break the tie without the engine
        # choosing which instruction the author meant.
        #
        # Scalings do not need a tie broken: multiplication is commutative, so
        # `scale 2` and `scale 3` have one answer whatever order they are read
        # in, and the engine computes it. Two DIFFERENT settings have no
        # answer, so they are refused by name with both values in the refusal
        # and the property is left where it was.
        refused_pairs: Set[Tuple[str, str]] = set()
        for (entity_id, prop), items in sorted(intents.items()):
            base = state.get(entity_id, {}).get(prop)
            if not isinstance(base, (int, float)) or isinstance(base, bool):
                continue
            base = float(base)
            kinds = {kind for kind, _, _ in items}
            values = {value for _, value, _ in items}
            bucket = action_deltas.setdefault(entity_id, {})
            # how much of the forecast's doubt this movement
            # carries, and how much the property keeps afterwards. `carried`
            # is the property's current sensitivity to its own seed, 1.0
            # while the forecast still describes it.
            carried = seed_carried.get((entity_id, prop), 0.0)
            when_acted = action_times.get((entity_id, prop), at_s)

            def _seed_moves(delta_sensitivity: float, left: float) -> None:
                if carried:
                    seed_sensitivity.setdefault(
                        (entity_id, prop), {})[when_acted] = delta_sensitivity
                    seed_carried[(entity_id, prop)] = left

            if kinds == {"add"}:
                # The one effect that superposes, and the only one whose
                # composition needs no ordering AND no single answer: two
                # increments are two increments.
                for _, value, _ in items:
                    bucket[prop] = bucket.get(prop, 0.0) + value
                # An increment does not depend on where the property was, so
                # it carries none of the doubt and erases none of it.
                _seed_moves(0.0, carried)
                continue
            if kinds == {"scale"}:
                factor = 1.0
                for _, value, _ in items:
                    factor *= value
                bucket[prop] = bucket.get(prop, 0.0) + (base * factor - base)
                _seed_moves((factor - 1.0) * carried, factor * carried)
                if len(items) > 1:
                    _assume(result, "scalings_compose_by_multiplication")
                continue
            if kinds == {"set"} and len(values) == 1:
                # Redundant rather than contradictory: applied once, which is
                # what asking for it twice asks for.
                bucket[prop] = bucket.get(prop, 0.0) + (
                    items[0][1] - base)
                # A SETTING PINS THE PROPERTY. Whatever the forecast said, the
                # property is now the number asked for, so the delta carries
                # exactly the doubt the seed had -- with the opposite sign,
                # because it is measured FROM the seeded value -- and the
                # property keeps none.
                _seed_moves(-carried, 0.0)
                continue
            labels = sorted({label for _, _, label in items})
            asked = ", ".join(f"{kind} {value:g}" for kind, value, _ in items)
            mixed = len(kinds) > 1
            result.refused_actions.append(ActionRefused(
                "contradictory_actions", ", ".join(labels),
                f"{entity_id}.{prop} is given {len(items)} effects at the "
                f"same instant ({asked}), "
                + ("which do not all compose the same way"
                   if mixed else "which do not agree") +
                f"; `at_s` is the only ordering this engine has and they "
                f"share it, so nothing was applied to it. Schedule them at "
                f"different times, or declare the one effect meant."))
            action_times.pop((entity_id, prop), None)
            refused_pairs.add((entity_id, prop))

        # what actually happened, rebuilt once every refusal is
        # known. An instance is reported applied when at least one of the
        # properties it asked for survived.
        step.actions_applied = [label for label, pairs in intended
                                if pairs - refused_pairs]

        for entity_id, deltas in action_deltas.items():
            for prop, delta in deltas.items():
                state.setdefault(entity_id, {})
                state[entity_id][prop] = state[entity_id].get(prop, 0.0) + delta
                # from here on this property is managed, and the
                # forecast that described it unmanaged is not overlaid again.
                # SAID OUT LOUD when it actually happens, because a reader
                # comparing two seed modes sees a property stop following its
                # forecast and nothing else in the envelope explains why.
                if (entity_id, prop) in curves and (
                        entity_id, prop) not in acted:
                    _assume(result, "projection_superseded_by_action")
                acted.add((entity_id, prop))

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
            for prop, delta in deltas.items():
                when = action_times.get((entity_id, prop), at_s)
                by_instant = movements.setdefault((entity_id, prop), {})
                by_instant[when] = by_instant.get(when, 0.0) + delta

        # THE DECOMPOSITION MUST SUM TO WHERE THE PROPERTY ACTUALLY IS.
        # `state` is the one account of that, and a movement list disagreeing
        # with it would propagate a displacement the source itself does not
        # show. They agree in every ordinary case; where they do not -- a
        # property both seeded and acted on, where the seed overwrites the
        # action, as it did before this change too -- the latest movement
        # absorbs the difference, so the steady state is exactly what it was
        # and only the TIME COURSE is decomposed.
        for (eid, prop), by_instant in movements.items():
            standing = state.get(eid, {}).get(prop)
            if standing is None or not by_instant:
                continue
            drift = (float(standing) - baseline.get(eid, {}).get(prop, 0.0)
                     - sum(by_instant.values()))
            if drift:
                by_instant[max(by_instant)] += drift

        contributions: Dict[str, Dict[str, float]] = {}
        #:. entity -> property -> {uncertainty source -> that
        #: source's SIGNED contribution}, accumulated across movement groups.
        #:
        #: This summed the groups' VARIANCES, on the reasoning that groups are
        #: separate couplings firing from different instants. They are not:
        #: the groups are the same declared couplings walked at different
        #: elapsed times, so one `gain_sigma:` fires in every group a source
        #: moved in, and adding those in quadrature counted one number as
        #: several independent ones. Measured on a pump moved +500 then +100
        #: with `gain_sigma: 0.002`: the tank settled at 1.0198 where the
        #: declaration says 1.2, and two EQUAL movements were narrow by
        #: sqrt(2). Contributions from one source add linearly here and the
        #: squares are taken once below -- which also lets them CANCEL, so a
        #: source moved out and back leaves a target with no spread at all,
        #: the answer for a target sitting where it started.
        spreads: Dict[str, Dict[str, Dict[Any, float]]] = {}
        fractions: set = set()
        #: Sources whose declared `offset:` this step has already taken. The
        #: offset belongs to the coupling, not to each movement of its
        #: source, so it develops from the first instant the source moved and
        #: later groups charge the gain term alone. Handed to each walk and
        #: added to BY the walk, so a constant term further down a chain is
        #: counted once as well.
        offsets_charged: Set[Tuple[str, str]] = set()
        groups: Dict[float, Dict[Tuple[str, str], float]] = {}
        for key, by_instant in movements.items():
            for when, delta in by_instant.items():
                groups.setdefault(when, {})[key] = delta
        for when in sorted(groups):
            elapsed = at_s - when
            if elapsed < 0:
                continue
            moved = groups[when]
            props_by_entity: Dict[str, set] = {}
            for eid, prop in moved:
                props_by_entity.setdefault(eid, set()).add(prop)
            # Only THIS group's properties carry a moved value, and the value
            # they carry is the baseline plus the delta of THIS MOVEMENT --
            # not the cumulative state, which would charge an earlier
            # movement's displacement this group's elapsed time. Every other
            # property sits at its baseline, so it measures a zero delta and
            # contributes nothing to this walk.
            overrides = {
                eid: {
                    name: (baseline.get(eid, {}).get(name, value)
                           + moved[(eid, name)]
                           if name in props_by_entity[eid]
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
            # this group's SHARE of each seed's doubt, signed. The
            # whole variance used to be handed to every group, so a property
            # both seeded and acted on propagated its forecast's band once per
            # group and the two were then added in quadrature -- measured at
            # sqrt(2) times a doubt the action had in fact removed.
            traverser.seed_spread = {}
            for (eid, prop), by_when in seed_sensitivity.items():
                sensitivity = by_when.get(when)
                sigma = seed_sigma.get((eid, prop), 0.0)
                if not sensitivity or not sigma:
                    continue
                traverser.seed_spread.setdefault(eid, {})[prop] = {
                    ("seed", eid, prop): sensitivity * sigma}
            # The SAME set across the step's groups: the walk reads it to
            # know which offsets are spent and adds the ones it spends.
            traverser.offsets_charged = offsets_charged
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
            for eid, props in getattr(walk, "imagined_spread", {}).items():
                for prop, contributions_by_source in props.items():
                    sbucket = spreads.setdefault(eid, {}).setdefault(prop, {})
                    for source_key, contribution in (
                            contributions_by_source.items()):
                        sbucket[source_key] = sbucket.get(
                            source_key, 0.0) + float(contribution)

        step.response_fractions = sorted(fractions)
        # a seeded property's OWN spread is what it still carries
        # of its forecast: all of it while nobody has acted, none once a
        # `set` has pinned it, `k` times it after a `scale k`.
        for (eid, prop), sigma in seed_sigma.items():
            carried = abs(seed_carried.get((eid, prop), 0.0)) * sigma
            if carried > 0.0:
                step.sigma.setdefault(eid, {})[prop] = carried
                result.has_declared_spread = True
        for eid, props in spreads.items():
            for prop, contributions_by_source in props.items():
                # WHO DROVE THIS VALUE. `gain` keys carry the
                # coupling; `seed` keys carry a forecast and are not a
                # coupling's doing.
                drove = sorted({
                    f"{key[3]}:{key[5]}->{key[6]}"
                    for key in contributions_by_source
                    if isinstance(key, tuple) and key and key[0] == "gain"})
                if drove:
                    step.drivers.setdefault(eid, {})[prop] = drove
                variance = sum(c * c for c in contributions_by_source.values())
                if variance > 0.0 and (eid, prop) not in movements:
                    step.sigma.setdefault(eid, {})[prop] = math.sqrt(variance)
                    result.has_declared_spread = True

        for eid, props in contributions.items():
            for prop, delta in props.items():
                if (eid, prop) in movements:
                    # An action or a projected seed drives this property
                    # directly; a transition into it must not overwrite the
                    # value the operator set or the forecast supplied.
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
            _file_step(session, result, step, at_s, movements,
                       episode_id, now)

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


def _assume(result: 'RolloutResult', assumption: str) -> None:
    """Record a stamp once. Every other site in this module open-codes the
    membership test; this is the same rule with one copy of it."""
    if assumption not in result.assumptions:
        result.assumptions.append(assumption)


def _file_step(session: Any, result: 'RolloutResult',
               step: 'RolloutStep', at_s: float,
               driven: Dict[Tuple[str, str], Dict[float, float]],
               episode_id: str, predicted_at: Any) -> None:
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
                    # ONE EPISODE ID FOR THE WHOLE ROLLOUT, and the
                    # instant it was RUN FOR rather than the instant the row
                    # was written. `traversal_id` means *the episode this came
                    # from* -- `record_impacts` has always shared one across a
                    # traversal -- and passing none minted a fresh uuid per
                    # record, so twelve steps of ONE trajectory looked like
                    # twelve unrelated episodes to anything reading the
                    # calibration. They are not independent: one declared gain
                    # drives every step, and measured against a mirror the
                    # tank either tracked the curve or did not -- 12 confirmed
                    # and 0 falsified, or 0 and 12, never a mix.
                    traversal_id=episode_id,
                    predicted_at=predicted_at,
                    couplings=tuple(
                        step.drivers.get(entity_id, {}).get(prop, ())),
                )
                result.predictions_filed += 1
            except Exception:  # noqa: BLE001 - a ledger refusal is not a crash
                result.values_without_tolerance += 1


def _now(session: Any):
    from ..clock import now_utc
    return now_utc()


def _seed_from_projection(
        topology: Any,
        state: Dict[str, Dict[str, float]]) -> Set[Tuple[str, str]]:
    """Overlay whatever `project_values` fitted; return WHICH keys it seeded.

    This returned a bool and the caller then re-derived the set by
    comparing the overlaid state against the baseline, which is a second
    reading of one fact -- the shape `_declared_dynamics` documents as how two
    paths come to disagree. The comparison also answered a different question:
    *did this value change* rather than *is this value a forecast*, and a
    forecast of no change is still a forecast.
    """
    seeded: Set[Tuple[str, str]] = set()
    for entity_id, node in getattr(topology, "nodes", {}).items():
        for prop, projected in (
                getattr(node, "projected_values", {}) or {}).items():
            value = getattr(projected, "value", None)
            if isinstance(value, (int, float)):
                state.setdefault(entity_id, {})[prop] = float(value)
                seeded.add((entity_id, prop))
    return seeded
