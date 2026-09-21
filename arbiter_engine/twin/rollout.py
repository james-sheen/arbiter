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

from ..fire_frequency import counting_aside
from ..assumptions import (EXOGENOUS_INPUTS_HELD, NO_ACTION_SCHEDULED,
                           SEEDED_FROM_PROJECTION)
from ..projection.projector import (BASELINE_MODEL_ID, PROJECTORS,
                                    RandomWalk, SOURCE_ENGINE)
from ..residual.predict_vs_mirror import normal_quantiles
from ..subenvelope import Decline
from .actions import (ActionInstance, ActionRefused, ActionTemplate,
                      deltas_for, load_templates, resolve)
from .topology import (SimulationDecline, TraversalDirection,
                       TraversalRequest, TransitionApplied, ValueMode)
from .traverser import IMAGINED_PREFIX, TopologyTraverser

#: A rollout with no step is not a rollout. Guarded rather than defaulted
#: because a zero or negative step is an author error, and silently
#: substituting one would hide it.
MIN_STEP_S = 1e-6

#: WHO MADE THE FORECAST, for a ledger that holds more than one filer's.
#: The engine names itself rather than being told apart by the shape of an id
#: -- the name-heuristic class this package has removed from three axioms --
#: and it is a fixed string because there is exactly one of it. A DOMAIN never
#: appears here: the verb is the producer, whatever the model is about.
_SELF_MODEL_ID: str = "arbiter_engine:rollout"

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
    #:. Which declared couplings this rollout actually crossed,
    #: as `source->target`. Recorded so that the verb which USED an
    #: undeclared number can name it: a `missing_declaration` question
    #: about an edge nothing traversed would be asking an author to
    #: declare a number this result does not rest on.
    edges_traversed: Set[str] = field(default_factory=set)
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
    #:. Per step, the product the walk composed against the exact
    #: convolution the declared dynamics imply, for every chain where a
    #: closed form exists. The `series_edges_compose_by_product` stamp says
    #: an approximation was used; these say what it cost.
    series_errors: List[Dict[str, Any]] = field(default_factory=list)
    #:. One row per filed prediction saying whether a random walk was
    #: fitted beside it and, when it was not, WHICH of the reasons applied --
    #: the same vocabulary `ingest_forecasts` reports for a producer. A bare
    #: count would leave *this projection did not beat a random walk* and
    #: *nothing ran a random walk* reading identically, which is the pair
    #: this engine exists to keep apart.
    raced: List[Dict[str, Any]] = field(default_factory=list)
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


def _deliver(topology: Any, *,
             movements: Dict[Tuple[str, str], Dict[float, float]],
             baseline: Dict[str, Dict[str, float]],
             state: Dict[str, Dict[str, float]],
             starts: Sequence[str],
             clock: float,
             budget: int,
             spread_at: Any,
             offsets_charged: Set[Tuple[str, str]],
             ) -> Tuple[Dict[str, Dict[str, float]],
                        Dict[str, Dict[str, Dict[Any, float]]],
                        List[Any]]:
    """What the declared couplings have put into each property by `clock`.

    ONE implementation, two callers, and the second is why it was
    lifted out of `run`. Building a trajectory needs this at the step clock;
    resolving an action whose delta READS the standing value -- `set` and
    `scale` -- needs the same answer at the action's own instant, which is
    somewhere inside the step and not at either end of it. Resolving against
    the step boundary instead left a `set 20` reporting 22.3865, an error of
    exactly one step's worth of the coupling's delivery, counted twice.

    Returns the contributions, the signed spread that came with them, and the
    walks themselves -- so the caller building a trajectory can count them
    against its budget and read their declines, and the caller merely ASKING
    can discard them. An asking caller passes a COPY of `offsets_charged`:
    a declared `offset:` is spent once per coupling, and a question must not
    spend it on the answer's behalf.
    """
    contributions: Dict[str, Dict[str, float]] = {}
    spreads: Dict[str, Dict[str, Dict[Any, float]]] = {}
    walks: List[Any] = []
    groups: Dict[float, Dict[Tuple[str, str], float]] = {}
    for key, by_instant in movements.items():
        for when, delta in by_instant.items():
            groups.setdefault(when, {})[key] = delta
    budget_left = budget
    for when in sorted(groups):
        elapsed = clock - when
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
        # The doubt a movement carries is an INPUT to the walk, so a
        # transition carries it downstream through its own gain the same way
        # it carries a declared `gain_sigma:`.
        traverser.seed_spread = spread_at(when)
        # The SAME set across the step's groups: the walk reads it to
        # know which offsets are spent and adds the ones it spends.
        traverser.offsets_charged = offsets_charged
        walk = traverser.traverse(request)
        walks.append(walk)
        budget_left = max(0, budget_left - len(walk.transitions_applied))
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
    return contributions, spreads, walks


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

    # One random-walk fit per `(entity, property)` for the whole
    # walk, reused across every step. The fit depends only on the readings
    # held at `predicted_at`, which do not change as the walk advances; only
    # the horizon does. Refitting per step would read the same series twelve
    # times and, worse, invite the series to differ between steps.
    baseline_fits: Dict[Tuple[str, str], Any] = {}

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
        result.assumptions.append(SEEDED_FROM_PROJECTION)

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
    #:. (entity, property) -> what the declared couplings had
    #: delivered to it by the END OF THE LAST COMPLETED STEP, and the signed
    #: doubt that came with it.
    #:
    #: Held apart from `movements` because the two propagate differently: a
    #: movement is walked from this property OUTWARD, while a contribution
    #: that arrived here has already been walked onward by the walk that
    #: delivered it. Folding the second into the first counts it twice; and
    #: dropping it, which is what this module did, loses the coupling
    #: altogether. Measured on a tank an `add` touched at t=600 s under a
    #: 120/600 exponential pump edge: the tank froze at 60.03 for the rest of
    #: the hour where 64.97 was declared, lost its declared spread, and
    #: handed the 5.03 it had already received to the sump a second time --
    #: with `transitions_applied` counting every one of them and nothing
    #: declined. The invariant every step restores is
    #:
    #:     state = baseline + sum(movements) + received
    #: The DOUBT that came with it is deliberately NOT held here beside the
    #: value. An action's delta is resolved at the action's own instant, so
    #: the doubt it inherits has to be read at that instant too -- which the
    #: same walk returns, one step fresher than anything carried over from
    #: the last one. A second copy here would be the staler of two records of
    #: one fact, which is how the two come to disagree.
    received: Dict[Tuple[str, str], float] = {}
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
    #:. (entity, property) -> {instant -> {uncertainty source -> the
    #: SIGNED doubt this action's own movement carries from it}}. The same
    #: quantity `seed_sensitivity` holds for a forecast band, for doubt that
    #: arrived through a declared `gain_sigma:` instead. An action whose delta
    #: is measured FROM the standing value inherits the standing value's
    #: doubt: a `set` pins the property and carries that doubt away with the
    #: opposite sign, a `scale k` multiplies it, an `add` neither reads nor
    #: removes it. Without this the doubt stayed where the value no longer
    #: was -- a tank `set` to 20 went on reporting the whole coupling's
    #: spread, and a tank `scale`d by 2 reported half of what it carried.
    action_sensitivity: Dict[Tuple[str, str],
                             Dict[float, Dict[Any, float]]] = {}
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

    def _spread_at(when: float) -> Dict[str, Dict[str, Dict[Any, float]]]:
        """The doubt the movements at `when` carry into the walk, signed.

        this group's SHARE of each seed's doubt. The whole variance
        used to be handed to every group, so a property both seeded and acted
        on propagated its forecast's band once per group and the two were then
        added in quadrature -- measured at sqrt(2) times a doubt the action
        had in fact removed.

        and the same share of whatever the COUPLINGS had put into a
        property an action then moved. Both are doubt an action's own delta
        inherited by being measured from a value that had it, so both ride out
        on that delta; `seed_spread` has been keyed by the source of the doubt
        since and needs no widening to carry a `gain` key beside a
        `seed` one. MERGED rather than assigned, because one property can be
        both: a forecast-seeded tank that a declared coupling also drives.
        """
        out: Dict[str, Dict[str, Dict[Any, float]]] = {}
        for (eid, prop), by_when in seed_sensitivity.items():
            sensitivity = by_when.get(when)
            sigma = seed_sigma.get((eid, prop), 0.0)
            if not sensitivity or not sigma:
                continue
            bucket = out.setdefault(eid, {}).setdefault(prop, {})
            key = ("seed", eid, prop)
            bucket[key] = bucket.get(key, 0.0) + sensitivity * sigma
        for (eid, prop), by_instant in action_sensitivity.items():
            carried = by_instant.get(when)
            if not carried:
                continue
            bucket = out.setdefault(eid, {}).setdefault(prop, {})
            for key, contribution in carried.items():
                bucket[key] = bucket.get(key, 0.0) + contribution
        return out

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
            # plus what the couplings had delivered here. The
            # forecast describes this property's OWN trajectory; overwriting
            # the state with it alone would discard every coupling into it.
            state.setdefault(entity_id, {})[prop] = (
                float(value) + received.get((entity_id, prop), 0.0))
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
        # WHAT THE COUPLINGS HAVE DELIVERED BY THE INSTANT EACH
        # ACTION LANDS. `set` and `scale` are the two effects whose delta
        # READS the standing value, and on a property that is also a
        # transition's `to:` the standing value includes what the couplings
        # put there. This resolved the delta against `state`, which is written
        # at the END of a step, while the state it then wrote used what the
        # couplings had delivered by THIS one -- two clocks, one subtraction.
        # Measured on a tank SET to 20 at t=600 s under a 600 s exponential
        # pump edge: 22.3865 reported at `step_s=300`, 20.3869 at 60, 20.1247
        # at 20. The error is exactly one step's worth of the coupling's
        # delivery and it shrinks with the step, which is the signature of a
        # discretisation artefact in a module whose whole design is that it
        # has none.
        #
        # Asked once per distinct instant rather than once per property, and
        # only when something is actually being resolved. The walks are
        # DISCARDED: they are the engine reading its own state to answer a
        # question, not transitions it applied to build this trajectory, and
        # counting them would inflate the denominator a caller reads to find
        # out how much of the declared topology ran. They are handed a COPY of
        # `offsets_charged` so a question cannot spend a declared `offset:`.
        delivered_at: Dict[float, Tuple[Dict[str, Dict[str, float]],
                                        Dict[str, Dict[str, Dict[Any,
                                                                 float]]]]] = {}
        for (entity_id, prop), items in intents.items():
            if {kind for kind, _, _ in items} == {"add"}:
                # An increment does not read the standing value, so there is
                # nothing here for it to be resolved against.
                continue
            when = action_times.get((entity_id, prop), at_s)
            if when in delivered_at:
                continue
            values_then, spread_then, _ = _deliver(
                topology, movements=movements, baseline=baseline, state=state,
                starts=starts, clock=when, budget=budget_left,
                spread_at=_spread_at, offsets_charged=set())
            delivered_at[when] = (values_then, spread_then)

        for (entity_id, prop), items in sorted(intents.items()):
            standing = state.get(entity_id, {}).get(prop)
            if (not isinstance(standing, (int, float))
                    or isinstance(standing, bool)):
                continue
            kinds = {kind for kind, _, _ in items}
            values = {value for _, value, _ in items}
            bucket = action_deltas.setdefault(entity_id, {})
            # how much of the forecast's doubt this movement
            # carries, and how much the property keeps afterwards. `carried`
            # is the property's current sensitivity to its own seed, 1.0
            # while the forecast still describes it.
            carried = seed_carried.get((entity_id, prop), 0.0)
            when_acted = action_times.get((entity_id, prop), at_s)
            values_then, spread_then = delivered_at.get(when_acted, ({}, {}))
            arrived_then = values_then.get(entity_id, {}).get(prop, 0.0)
            # the value this property ACTUALLY HAS at the instant
            # the action lands: its baseline, plus every movement of its own
            # registered so far, plus what the couplings had delivered by
            # then. `state` is the same quantity one step later, which is the
            # whole of the defect above.
            base = (baseline.get(entity_id, {}).get(prop, 0.0)
                    + sum(movements.get((entity_id, prop), {}).values())
                    + arrived_then)
            # The doubt that came with what arrived, per declared source. The
            # seed's own share is excluded: `_seed_moves` already carries it,
            # and counting it in both places would carry it twice.
            received_then = {
                key: contribution
                for key, contribution in spread_then.get(
                    entity_id, {}).get(prop, {}).items()
                if not (isinstance(key, tuple) and key and key[0] == "seed")}

            def _seed_moves(delta_sensitivity: float, left: float) -> None:
                # ADDED to whatever this instant already carries,
                # not assigned. The seed's own share sits at instant 0.0 and
                # an action at `at_s=0` -- *do this now* -- lands on the same
                # key: assigning overwrote +1 with -1, so a source pinned by a
                # `set` at t=0 handed its whole forecast band to its targets
                # with the sign flipped. Measured, the pinned pump reported no
                # spread and the tank it feeds reported 0.861, which is the
                # pump's band through the gain; the same action at `at_s=1`
                # left the tank with none, which is the answer for both.
                if carried:
                    by_when = seed_sensitivity.setdefault(
                        (entity_id, prop), {})
                    by_when[when_acted] = (by_when.get(when_acted, 0.0)
                                           + delta_sensitivity)
                    seed_carried[(entity_id, prop)] = left

            def _received_moves(factor: float) -> None:
                """how much of the doubt the COUPLINGS had put into
                this property the action's own movement carries away with it:
                all of it with the opposite sign for a `set`, which pins the
                property and leaves only later arrivals in doubt; `k - 1`
                times it for a `scale k`, which multiplies what is standing;
                none for an `add`, which neither reads the standing value nor
                removes it. The same three cases `_seed_moves` states for a
                forecast band, because it is the same kind of quantity.
                """
                if not received_then or not factor:
                    return
                by_key = action_sensitivity.setdefault(
                    (entity_id, prop), {}).setdefault(when_acted, {})
                for key, contribution in received_then.items():
                    by_key[key] = by_key.get(key, 0.0) + factor * contribution

            if kinds == {"add"}:
                # The one effect that superposes, and the only one whose
                # composition needs no ordering AND no single answer: two
                # increments are two increments.
                for _, value, _ in items:
                    bucket[prop] = bucket.get(prop, 0.0) + value
                # An increment does not depend on where the property was, so
                # it carries none of the doubt and erases none of it.
                _seed_moves(0.0, carried)
                _received_moves(0.0)
                continue
            if kinds == {"scale"}:
                factor = 1.0
                for _, value, _ in items:
                    factor *= value
                bucket[prop] = bucket.get(prop, 0.0) + (base * factor - base)
                _seed_moves((factor - 1.0) * carried, factor * carried)
                _received_moves(factor - 1.0)
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
                _received_moves(-1.0)
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
            decomposed = (baseline.get(eid, {}).get(prop, 0.0)
                          + sum(by_instant.values())
                          + received.get((eid, prop), 0.0))
            drift = float(standing) - decomposed
            if drift:
                # REPORTED, not only absorbed. `received` is the
                # third term of the invariant this step restores, and with it
                # subtracted the decomposition and the state agree in every
                # case the module has a name for, so a residue here is a
                # defect rather than a displacement. The fold stays, because
                # the alternative is propagating a state the source does not
                # show; what changes is that it stops being silent.
                #
                # `math.isclose` at its own default, rather than a threshold
                # this engine picked: the question is whether two floats are
                # the same number, which is a question about floats.
                by_instant[max(by_instant)] += drift
                if not math.isclose(float(standing), decomposed,
                                    rel_tol=1e-9):
                    result.declines.append(SimulationDecline(
                        "internal_error", f"{eid}.{prop}",
                        f"the imagined value {float(standing):g} and its own "
                        f"movement decomposition {decomposed:g} disagree by "
                        f"{drift:g} at t={at_s:g}s; the difference was folded "
                        f"into the latest movement so the value stands, and "
                        f"the time course of this property is not derived "
                        f"from the declarations alone"))

        fractions: set = set()
        # Sources whose declared `offset:` this step has already taken. The
        # offset belongs to the coupling, not to each movement of its
        # source, so it develops from the first instant the source moved and
        # later groups charge the gain term alone. Handed to each walk and
        # added to BY the walk, so a constant term further down a chain is
        # counted once as well. A fresh set per step, and the walks that
        # merely ANSWER a question above were handed a copy of it.
        offsets_charged: Set[Tuple[str, str]] = set()
        # `spreads` is entity -> property -> {uncertainty source -> that
        # source's SIGNED contribution}, accumulated across movement groups.
        #
        # This summed the groups' VARIANCES, on the reasoning that
        # groups are separate couplings firing from different instants. They
        # are not: the groups are the same declared couplings walked at
        # different elapsed times, so one `gain_sigma:` fires in every group a
        # source moved in, and adding those in quadrature counted one number
        # as several independent ones. Measured on a pump moved +500 then
        # +100 with `gain_sigma: 0.002`: the tank settled at 1.0198 where the
        # declaration says 1.2, and two EQUAL movements were narrow by
        # sqrt(2). Contributions from one source add linearly there and the
        # squares are taken once below -- which also lets them CANCEL, so a
        # source moved out and back leaves a target with no spread at all,
        # the answer for a target sitting where it started.
        contributions, spreads, walks = _deliver(
            topology, movements=movements, baseline=baseline, state=state,
            starts=starts, clock=at_s, budget=budget_left,
            spread_at=_spread_at, offsets_charged=offsets_charged)
        for walk in walks:
            result.transitions_attempted += walk.transitions_attempted
            result.transitions_applied += len(walk.transitions_applied)
            budget_left = max(0, budget_left - len(walk.transitions_applied))
            step.transitions_applied += len(walk.transitions_applied)
            for applied in walk.transitions_applied:
                fractions.add(round(float(applied.fraction), 6))
                result.edges_traversed.add(applied.edge)
            for decline in walk.simulation_declines:
                if decline not in result.declines:
                    result.declines.append(decline)
            for assumption in walk.assumptions:
                if assumption not in result.assumptions:
                    result.assumptions.append(assumption)
            # the cost of the composition this step relied on.
            # Collected per step rather than pooled, because the divergence
            # between the product and the convolution PEAKS mid-transient and
            # vanishes at both ends: a single figure for the walk would
            # describe neither the instant a breach was predicted nor the
            # steady state that is exact.
            result.series_errors.extend(walk.series_errors)

        step.response_fractions = sorted(fractions)
        # a seeded property's OWN spread is what it still carries
        # of its forecast: all of it while nobody has acted, none once a
        # `set` has pinned it, `k` times it after a `scale k`.
        #
        # written as a KEYED contribution rather than straight into
        # `step.sigma`, so that a property which is both seeded and driven by
        # a declared coupling gets ONE accounting instead of two, and the
        # later one no longer silently replaces the earlier. SET rather than
        # added: a walk that started at this property already carried this
        # group's share of its seed into the bucket, and the shares summed
        # over the groups are exactly `carried`. Written even when it is zero,
        # because a `set` pins the property and the two shares the walk
        # delivered cancel only if BOTH of them arrive.
        for (eid, prop), sigma in seed_sigma.items():
            carried = seed_carried.get((eid, prop), 0.0) * sigma
            spreads.setdefault(eid, {}).setdefault(prop, {})[
                ("seed", eid, prop)] = carried
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
                # no longer skipped for a property in `movements`.
                # An action or a seed drives a property directly; that does
                # not stop a declared coupling driving it too, and the doubt
                # on what the coupling delivered is the property's doubt.
                if variance > 0.0:
                    step.sigma.setdefault(eid, {})[prop] = math.sqrt(variance)
                    result.has_declared_spread = True

        # A COUPLING INTO A MOVED PROPERTY STILL ARRIVES.
        # This skipped every property in `movements`, on the reasoning that a
        # transition must not overwrite what an operator set or a forecast
        # supplied. It did not overwrite: it DROPPED, while the envelope went
        # on reporting the transition as applied. Superposition is the whole
        # rule, so a property is its baseline plus its own movements plus what
        # the couplings delivered -- and what they delivered is remembered, so
        # the next step does not mistake it for a movement of this property's
        # own and walk it outward a second time.
        arrived: Dict[Tuple[str, str], float] = {}
        for eid, props in contributions.items():
            for prop, delta in props.items():
                arrived[(eid, prop)] = delta
        for key in set(arrived) | set(received):
            eid, prop = key
            state.setdefault(eid, {})[prop] = (
                baseline.get(eid, {}).get(prop, 0.0)
                + sum(movements.get(key, {}).values())
                + arrived.get(key, 0.0))
        received = arrived

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
                       episode_id, now, baseline_fits)

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
    for assumption in (EXOGENOUS_INPUTS_HELD,
                       NO_ACTION_SCHEDULED if not schedule else ""):
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
        # THE IMAGINED WORLD DOES NOT WRITE INTO THE LIVE COUNTER.
        # The reasoner counts every finding it dispatches into the
        # process-wide fire tracker, and these findings are about a state
        # nobody has: measured on the shipped example, one live `check`
        # recorded 2 fires and one `plan` recorded 600 in the same buckets,
        # tripping the tracker's own high-rate WARN on a world that does not
        # exist. Nothing reads the counts back today, which is why it could
        # sit there; the rule this module opens with -- the clone is never
        # the live history -- is the same rule, and this was the one channel
        # it was not being kept on.
        with counting_aside():
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
               episode_id: str, predicted_at: Any,
               fits: Optional[Dict[Tuple[str, str], Any]] = None) -> None:
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
                    # THE SPREAD ITSELF, not only the band derived
                    # from it. The tolerance above asks *did the world land
                    # inside the band we chose*, and that question rewards
                    # choosing a wider one: measured on one reality, a
                    # `gain_sigma:` ten times too wide scored a `confirm_rate`
                    # of 1.0 where an honest declaration scored 0.95. Stating
                    # the quantiles makes the proper scores computable, and
                    # pinball loss grows with the width of an interval whether
                    # or not it contained the answer.
                    #
                    # Same sigma, same instant, two levels -- so the tolerance
                    # and the quantiles cannot come to disagree about how sure
                    # the model said it was.
                    quantiles=normal_quantiles(float(value), float(sigma)),
                    model_id=_SELF_MODEL_ID,
                    # NOT A PRODUCER'S SUBMISSION, said in the vocabulary the
                    # forecast surfaces already read. Every producer path
                    # filters on `kind == "distribution"` today so nothing
                    # currently depends on it -- which is exactly why it is
                    # stated now: the fact is free at the one moment the filer
                    # knows it, and a later filter widened past `kind` would
                    # otherwise read the engine's own forecasts as somebody
                    # else's.
                    source=SOURCE_ENGINE,
                )
                result.predictions_filed += 1
            except Exception:  # noqa: BLE001 - a ledger refusal is not a crash
                result.values_without_tolerance += 1
                continue
            # AND FILE THE YARDSTICK BESIDE IT. Inside the same
            # loop rather than a pass afterwards, so a projection and its
            # reference cannot come to disagree about which horizon and
            # instant they are about: both read the same locals.
            result.raced.append({
                "entity_id": entity_id,
                "indicator": prop,
                "horizon_s": float(at_s),
                "model_id": _SELF_MODEL_ID,
                "baseline": _file_rollout_baseline(
                    session, entity_id, prop, float(at_s), predicted_at,
                    episode_id, fits if fits is not None else {}),
            })


def _file_rollout_baseline(session: Any, entity_id: str, prop: str,
                           horizon_s: float, predicted_at: Any,
                           episode_id: str,
                           fits: Dict[Tuple[str, str], Any]) -> str:
    """Fit a random walk beside one filed projection. Returns the `raced` reason.

    **The engine's own rollout was the one forecaster in this ledger
    with nothing to beat.** `ingest_forecasts` files a yardstick beside every
    producer record and `project` files one beside its own; a rollout filed
    six projections and no reference, so `own_projections` reported a
    calibration that could not distinguish a declared `gain:` carrying real
    information from one whose `gain_sigma:` was merely generous. That is the
    failure `RandomWalk`'s docstring names: *a forecaster can be beautifully
    calibrated and still carry no information at all.*

    WHY THIS IS A THIRD FILER AND NOT A CALL INTO `ingest._file_baseline`.
    That one files a DISTRIBUTION record, graded by `_grade_distribution_record`
    against its own maturity and matching rules. A rollout's projections are
    VALUE records. Racing across the two kinds would compare a figure graded
    one way with a figure graded another and call the difference skill. The
    reason vocabulary is deliberately the SAME closed set, so a reader
    branching on `raced[].baseline` needs one vocabulary and not two.

    THE NULL IS *THIS VALUE DID NOT MOVE*, fitted on the driven property's own
    readings as of the instant the rollout was run for -- so the reference sees
    what the engine could have seen and not one reading more. A declared
    coupling that cannot beat it is not earning its declaration, which is the
    question `transition_learner` answers only where there is enough history
    for an OLS fit.

    NOTHING RAISES. A rollout must not fail because a reference could not be
    fitted; the reason is reported and the walk continues.
    """
    from ..clock import as_of
    from ..forecast.ingest import _indicator_for, _reading_history

    ledger = getattr(session, "ledger", None)
    if ledger is None:
        return "no_entity_or_model"
    entity = getattr(session, "entities", {}).get(entity_id)
    if entity is None or getattr(session, "model", None) is None:
        return "no_entity_or_model"

    cached = fits.get((entity_id, prop))
    if cached is None:
        spec = _indicator_for(session, entity, prop)
        if spec is None:
            cached = "no_such_indicator"
        else:
            lookback = (getattr(spec, "lookback", None)
                        or getattr(spec, "time_window", None))
            if lookback is None:
                cached = "no_lookback_or_window"
            else:
                try:
                    with as_of(predicted_at):
                        series = _reading_history(session).get_values(
                            entity_id, prop, lookback)
                    fitted = PROJECTORS[RandomWalk.name].fit(
                        series, {}, {"entity_id": entity_id, "property": prop})
                    cached = ("too_little_history"
                              if isinstance(fitted, Decline) else fitted)
                except (ValueError, KeyError, ArithmeticError, TypeError):
                    cached = "fit_failed"
        fits[(entity_id, prop)] = cached
    if isinstance(cached, str):
        return cached

    try:
        forecast = cached.forecast(float(horizon_s))
        ledger.record_value_prediction(
            entity_id=entity_id,
            property_name=prop,
            predicted_value=float(forecast.mean),
            tolerance=1.96 * float(forecast.sigma),
            horizon_s=float(horizon_s),
            confidence=0.95,
            # THE SAME EPISODE as the projection it races, on purpose. The
            # sibling rule in `_grade_value_record` keys on `traversal_id`
            # and the horizon, so sharing one puts both records on the SAME
            # reading -- which is what a race is. Filing under a separate
            # episode would grade them against two observations and compare
            # the results.
            traversal_id=episode_id,
            predicted_at=predicted_at,
            quantiles=forecast.quantiles,
            model_id=BASELINE_MODEL_ID,
            source=SOURCE_ENGINE,
        )
    except Exception:  # noqa: BLE001 - a ledger refusal is not a crash
        return "fit_failed"
    return "filed"


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
