""" — action-clears-problem Monte Carlo substrate.

Composes a ``P(action_clears_problem)`` estimate over the
``MonteCarloPredictor`` for the ACTIVE-mode confidence gate: apply a candidate action's effect to a copy of the state,
re-run detection, and count the samples where the problem's axiom no
longer fires.

The action-effect model is the decision: an action's effect is a
declarative parameter -> entity-property mapping carried by the action
template's ``parameters_schema`` (an ``entity_property`` key per
effect-bearing parameter), with a generic parameter-name fallback when
no ``entity_property`` is declared. The applier is a generic loop over
``parameters_schema`` — there is NO per-action-type branch — so the
substrate is domain-agnostic (per the project's design guidance).

Per read-only-by-design — the live state is never mutated; each
Monte Carlo sample operates on a deep copy.

Substrate scope: the ``simulation_step`` + the
``P(action_clears_problem)`` composition, in-process tested. The live
wiring — running this for the candidate action inside ``_process_problem``
and feeding the 95%-CI lower bound to ``_route_with_active_policy`` —
lands.
"""

from __future__ import annotations

import logging
import random
from typing import Any, Callable, Dict, List, Optional

from .monte_carlo_predictor import (
    MonteCarloOutcomeDistribution,
    MonteCarloPredictor,
    MonteCarloPredictionRequest,
    deepcopy_snapshot,
)

logger = logging.getLogger(__name__)

# The outcome name the simulation_step emits + the predictor aggregates.
ACTION_CLEARS_PROBLEM_OUTCOME = "action_clears_problem"


def resolve_effect_property(
    param_name: str,
    parameters_schema: Optional[Dict[str, Any]],
) -> str:
    """resolve which entity property an action parameter
    writes.

    Per the decision: if the action template's ``parameters_schema``
    declares an ``entity_property`` for ``param_name``, that is the
    property the parameter writes; otherwise fall back to the parameter
    name itself (the generic fallback). The fallback keeps the substrate
    usable for action templates that have not declared their effect
    mapping, while declared mappings stay precise.
    """
    schema = parameters_schema or {}
    spec = schema.get(param_name)
    if isinstance(spec, dict):
        declared = spec.get("entity_property")
        if isinstance(declared, str) and declared:
            return declared
    return param_name


def apply_action_effect(
    entity: Any,
    parameters: Dict[str, Any],
    parameters_schema: Optional[Dict[str, Any]] = None,
    *,
    effect_perturbation: Optional[Callable[[Any, random.Random], Any]] = None,
    rng: Optional[random.Random] = None,
) -> None:
    """apply an action's effect to a single entity, in place.

    Per the action-effect model: for each ``(param_name, value)``
    in ``parameters``, write ``value`` onto the entity property resolved
    by ``resolve_effect_property``. The caller is responsible for passing
    a COPY (read-only-by-design) — this helper mutates
    whatever entity it is handed.

    When ``effect_perturbation`` is supplied, the written value is
    ``effect_perturbation(value, rng)`` rather than ``value`` — this
    models the uncertainty in an action's realised effect (e.g. a
    scale-up does not deterministically yield exactly N healthy
    replicas). Without it the effect is applied exactly (deterministic).
    """
    props = getattr(entity, "properties", None)
    if not isinstance(props, dict):
        return
    for param_name, value in (parameters or {}).items():
        prop = resolve_effect_property(param_name, parameters_schema)
        if effect_perturbation is not None and rng is not None:
            try:
                value = effect_perturbation(value, rng)
            except Exception as e:  # noqa: BLE001
                # Per archetype: a perturbation callable that
                # raises is operator-supplied — log + apply the
                # unperturbed value rather than abort the whole run.
                logger.warning(
                    "effect_perturbation raised %s for param %r: %s "
                    "— applying the unperturbed value",
                    type(e).__name__, param_name, e,
                )
        props[prop] = value


def _lookup_entity(snapshot: Any, entity_id: str) -> Any:
    """Find an entity by id in a snapshot.

    The snapshot is duck-typed: the contract is a plain
    ``Dict[entity_id, entity]`` (the in-process + live shape,
    built from ``Core._det_entity_cache``). Objects exposing a ``.nodes``
    dict (a ``DigitalTwinTopology``) are also accepted so the
    substrate composes with the topology-snapshot type.
    """
    if hasattr(snapshot, "get"):
        return snapshot.get(entity_id)
    nodes = getattr(snapshot, "nodes", None)
    if isinstance(nodes, dict):
        node = nodes.get(entity_id)
        if node is None:
            return None
        return getattr(node, "entity", node)
    return None


def make_action_clears_problem_simulation_step(
    target_entity_ids: List[str],
    parameters: Dict[str, Any],
    parameters_schema: Optional[Dict[str, Any]],
    detection_callable: Callable[[Any], Dict[str, Any]],
    *,
    effect_perturbation: Optional[Callable[[Any, random.Random], Any]] = None,
) -> Callable[[Any, random.Random], Dict[str, bool]]:
    """build a ``MonteCarloPredictor`` ``simulation_step`` that
    estimates ``P(action_clears_problem)``.

    Per the caller-supplied-simulation contract, the returned
    closure is ``simulation_step(snapshot, rng) -> {outcome: bool}``. Per
    sample it:

    1. deep-copies the ``snapshot`` (a ``Dict[entity_id, entity]``),
    2. applies the action's effect (model) to each target entity
       in the copy — perturbed per-sample when ``effect_perturbation``
       is supplied,
    3. runs the caller-supplied ``detection_callable`` on the mutated
       copy,
    4. returns ``{"action_clears_problem": True}`` iff the problem no
       longer persists.

    ``detection_callable(snapshot_copy)`` must return a dict carrying a
    ``problem_persists: bool`` key (the ``build_detection_outcome_dict``
    shape). The caller supplies it — a closure over a real
    ``LayeredDetector`` (live path) or a lightweight predicate
    (in-process tests). A missing key is treated as ``problem_persists``
    True (fail-safe — an unmeasurable outcome does not auto-clear).
    """
    def step(snapshot: Any, rng: random.Random) -> Dict[str, bool]:
        snapshot_copy = deepcopy_snapshot(snapshot)
        for entity_id in target_entity_ids:
            entity = _lookup_entity(snapshot_copy, entity_id)
            if entity is None:
                continue
            apply_action_effect(
                entity, parameters, parameters_schema,
                effect_perturbation=effect_perturbation, rng=rng,
            )
        result = detection_callable(snapshot_copy)
        persists = bool((result or {}).get("problem_persists", True))
        return {ACTION_CLEARS_PROBLEM_OUTCOME: not persists}

    return step


def estimate_action_clears_problem(
    snapshot: Any,
    target_entity_ids: List[str],
    parameters: Dict[str, Any],
    parameters_schema: Optional[Dict[str, Any]],
    detection_callable: Callable[[Any], Dict[str, Any]],
    *,
    n_samples: int = 200,
    seed: Optional[int] = None,
    effect_perturbation: Optional[Callable[[Any, random.Random], Any]] = None,
    max_perturbation_seconds: Optional[float] = None,
) -> MonteCarloOutcomeDistribution:
    """estimate ``P(action_clears_problem)`` for a candidate
    action.

    Composes ``make_action_clears_problem_simulation_step`` over the
    ``MonteCarloPredictor``. Returns the ``MonteCarloOutcomeDistribution``
    for the ``action_clears_problem`` outcome — its
    ``confidence_interval_95`` lower bound is what an internal ruling feeds the
     ACTIVE-mode policy as ``confidence_lower_bound``.

    ``max_perturbation_seconds`` caps the per-call Monte Carlo wall-clock
    (the budget) — load-bearing on the live decision path so a
    slow detection_callable cannot stall action routing.
    """
    predictor = MonteCarloPredictor(seed=seed)
    request = MonteCarloPredictionRequest(
        outcome_names=[ACTION_CLEARS_PROBLEM_OUTCOME],
        n_samples=n_samples,
        seed=seed,
    )
    step = make_action_clears_problem_simulation_step(
        target_entity_ids, parameters, parameters_schema, detection_callable,
        effect_perturbation=effect_perturbation,
    )
    distributions = predictor.predict(
        snapshot, step, request,
        max_perturbation_seconds=max_perturbation_seconds,
    )
    return distributions[ACTION_CLEARS_PROBLEM_OUTCOME]
