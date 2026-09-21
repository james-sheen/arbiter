"""Actions as inputs to a rollout: where and when the first delta enters.

A world model's transition is ``p(s_{t+1} | s_t, a_t)`` -- state AND
action. Stage 1 gave the engine the state half: a declared `transition:` on an
edge moves a downstream value when an upstream one moves. This module supplies
the ``a_t``, and it is deliberately the smallest thing that can: an action
instance names a template, an entity, some parameter values and a time, and
applying it produces a delta on one property at one moment. Everything after
that is Stage 1 again.

WHAT IS NOT HERE, AND WHY. `evidence/tech_brief.md` shows the unpublished
operator half carrying `action_templates:` alongside an `active_mode_policy`
and an `approval_chain`. Only the effect model crosses into the open engine.
The engine reports what an action WOULD do; whether it may run, who approves
it and how it is dispatched are not v0.1 questions and are not made easier by
being answered badly here. `twin/traverser.py` already classifies a
HYPOTHETICAL traversal carrying overrides as Tier 3 -- operator confirmation
-- and a rollout with actions is the same tier and reports the same way.

THE PARAMETER-TO-PROPERTY MAPPING IS NOT REDEFINED HERE. `resolve_effect_property`
in `action_clears_problem.py` has read `parameters_schema[param]["entity_property"]`
since, and this module calls it rather than carrying a second copy of
the rule. Its documented fallback -- to the parameter name when no mapping is
declared -- is kept, and a rollout that relied on it says so in its
assumptions, because a mapping that was guessed is a different claim from one
that was declared.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Mapping

from ..assumptions import ACTION_PROPERTY_FROM_PARAMETER_NAME_PREFIX
from .action_clears_problem import resolve_effect_property

#: How an action's parameter value reaches the property it writes.
#:
#: `set` is the value; `add` is a delta; `scale` is a multiplier. Declared,
#: never inferred -- the same number means three different things under the
#: three verbs, and nothing about the number says which.
EFFECTS = ("set", "add", "scale")

#: The keys a template must carry to load.
REQUIRED_TEMPLATE_KEYS = ("name", "applies_to", "parameters_schema")


@dataclass
class ActionTemplate:
    """A kind of action, and the properties it writes."""
    name: str
    applies_to: str
    parameters_schema: Dict[str, Any] = field(default_factory=dict)
    effect: str = "set"
    #: How long the property takes to reach the set value. 0 is a step.
    #: Distinct from an edge's `propagation_delay_s`: this is the actuator,
    #: that is the coupling.
    settle_s: float = 0.0
    source: str = ""

    def property_for(self, parameter: str) -> Tuple[str, bool]:
        """(property written, whether the mapping was DECLARED)."""
        spec = (self.parameters_schema or {}).get(parameter)
        declared = bool(isinstance(spec, dict)
                        and isinstance(spec.get("entity_property"), str)
                        and spec.get("entity_property"))
        return resolve_effect_property(
            parameter, self.parameters_schema), declared


@dataclass
class ActionInstance:
    """One action, on one entity, at one time."""
    template: str
    entity_id: str
    parameters: Dict[str, float] = field(default_factory=dict)
    #: Seconds from the start of the rollout. An action at t=0 is applied in
    #: the first step; one at t=600 enters in whichever step contains it.
    at_s: float = 0.0


def as_action_instance(raw: Any, *, where: str) -> ActionInstance:
    """One action, however a caller spelled it.

    A WRONG ARGUMENT TYPE IS A CALLER BUG, NOT A COVERAGE GAP.
    `rollout` and `plan` took dataclasses only, and a plain mapping -- the
    shape every JSON consumer has -- reached the walk and raised
    `AttributeError` deep inside it. The discipline caught that and reported
    `internal_error` with `meta.source: unavailable`, which says THE ENGINE
    BROKE over a cell nobody could answer. Nothing was wrong with the model
    and nothing was unanswerable; the caller passed a dict.

    A mapping is accepted because two transports already converted one by
    hand on the way in, in two copies of the same six lines. Anything that is
    neither raises, at the boundary, naming what arrived -- which is what a
    caller bug should do.
    """
    if isinstance(raw, ActionInstance):
        return raw
    if isinstance(raw, Mapping):
        return ActionInstance(
            template=str(raw.get("template", "")),
            entity_id=str(raw.get("entity_id", "")),
            parameters=dict(raw.get("parameters") or {}),
            at_s=float(raw.get("at_s", 0.0) or 0.0),
        )
    raise TypeError(
        f"{where} takes ActionInstance objects or mappings with "
        f"template/entity_id/parameters/at_s; got {type(raw).__name__}")


@dataclass
class ActionRefused:
    """An action instance the rollout would not apply, and why."""
    reason: str
    location: str
    detail: str = ""


def load_templates(model: Any) -> Tuple[Dict[str, ActionTemplate],
                                        List[ActionRefused]]:
    """Read `action_templates:` off a loaded domain model.

    A partial template is refused and named, not completed. The rule is the
    one `transition:` follows and for the same reason: a template missing its
    `parameters_schema` looks declared in the file and writes nothing.
    """
    templates: Dict[str, ActionTemplate] = {}
    refused: List[ActionRefused] = []
    for raw in list(getattr(model, "action_templates", None) or []):
        if not isinstance(raw, dict):
            refused.append(ActionRefused(
                "malformed_action", "<template>",
                f"an action template must be a mapping, got "
                f"{type(raw).__name__}"))
            continue
        name = str(raw.get("name") or "")
        missing = [k for k in REQUIRED_TEMPLATE_KEYS if not raw.get(k)]
        if missing:
            refused.append(ActionRefused(
                "malformed_action", name or "<unnamed>",
                f"template is missing {', '.join(missing)}"))
            continue
        effect = str(raw.get("effect", "set")).lower()
        if effect not in EFFECTS:
            refused.append(ActionRefused(
                "malformed_action", name,
                f"effect {effect!r} is not one of {', '.join(EFFECTS)}"))
            continue
        try:
            settle = float(raw.get("settle_s", 0.0))
        except (TypeError, ValueError):
            refused.append(ActionRefused(
                "malformed_action", name,
                f"settle_s {raw.get('settle_s')!r} is not a number"))
            continue
        templates[name] = ActionTemplate(
            name=name,
            applies_to=str(raw.get("applies_to") or ""),
            parameters_schema=dict(raw.get("parameters_schema") or {}),
            effect=effect,
            settle_s=settle,
            source=str(raw.get("source") or ""),
        )
    return templates, refused


def resolve(instance: ActionInstance,
            templates: Dict[str, ActionTemplate],
            entities: Dict[str, Any]) -> Tuple[Optional[ActionTemplate],
                                               Optional[ActionRefused]]:
    """Check one action instance against the model before it is applied."""
    location = f"{instance.template}@{instance.entity_id}"
    template = templates.get(instance.template)
    if template is None:
        return None, ActionRefused(
            "unknown_action", location,
            f"no action template named {instance.template!r} is declared; "
            f"declared: {sorted(templates) or 'none'}")
    entity = entities.get(instance.entity_id)
    if entity is None:
        return None, ActionRefused(
            "missing_entity", location,
            f"this session holds no entity {instance.entity_id!r}")
    entity_type = getattr(entity, "type", None)
    if template.applies_to and entity_type != template.applies_to:
        return None, ActionRefused(
            "wrong_entity_type", location,
            f"{template.name!r} applies to {template.applies_to!r} and "
            f"{instance.entity_id!r} is a {entity_type!r}")
    unknown = [p for p in instance.parameters
               if p not in (template.parameters_schema or {})]
    if unknown:
        return None, ActionRefused(
            "unknown_parameter", location,
            f"{template.name!r} declares no parameter(s) "
            f"{', '.join(sorted(unknown))}")
    return template, None


def deltas_for(instance: ActionInstance, template: ActionTemplate,
               current: Dict[str, Any]) -> Tuple[Dict[str, float],
                                                 List[str],
                                                 List[ActionRefused],
                                                 Dict[str, Tuple[str, float]]]:
    """What this action does to the entity's properties, as deltas.

    Deltas rather than absolute values so an action composes with the
    TRANSITIONS arriving at the same property in the same step, through the
    one superposition rule Stage 1 already applies. Two mechanisms writing one
    property by two different arithmetics is how a simulator starts disagreeing
    with itself.

    AND A FOURTH RETURN, because that argument covers an action
    composing with a transition and does not cover two ACTIONS composing with
    each other. Only `add` is additive. Two `set` deltas measured from the same
    pre-step reading and then summed give `A + B - base`: measured, `set 1500`
    and `set 2000` on a pump at 1000 put it at 2500, a value neither action
    asked for. Two `scale` deltas summed give `(a + b - 1)` times the reading
    where composing them gives `a *b`.

    So the caller is told WHICH EFFECT produced each property's delta, and
    resolves any collision itself -- it is the only layer that can see two
    instances at once. Nothing is decided here; this function still describes
    one action.
    """
    deltas: Dict[str, float] = {}
    assumptions: List[str] = []
    refused: List[ActionRefused] = []
    #: property -> (effect, the value the author wrote). The raw value rather
    #: than the delta, because composing scalings needs the factor and
    #: resolving settings needs to compare what was asked for.
    effects: Dict[str, Tuple[str, float]] = {}
    for parameter, raw_value in (instance.parameters or {}).items():
        prop, declared = template.property_for(parameter)
        if not declared:
            # the fallback: the parameter name IS the property. Kept, and
            # stamped, because a mapping nobody declared is a guess and the
            # reader is entitled to know one was made.
            assumptions.append(
                f"{ACTION_PROPERTY_FROM_PARAMETER_NAME_PREFIX}{prop}")
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            refused.append(ActionRefused(
                "malformed_action", f"{instance.template}@{instance.entity_id}",
                f"parameter {parameter!r} is {raw_value!r}, not a number"))
            continue
        present = current.get(prop)
        if not isinstance(present, (int, float)) or isinstance(present, bool):
            if template.effect == "set":
                # Nothing to measure a delta FROM. `set` on an absent property
                # is a value the rollout cannot place on the existing scale.
                refused.append(ActionRefused(
                    "missing_property",
                    f"{instance.template}@{instance.entity_id}",
                    f"{instance.entity_id}.{prop} is not a number, so a "
                    f"`set` action has no delta to compute"))
                continue
            present = 0.0
        if template.effect == "set":
            deltas[prop] = deltas.get(prop, 0.0) + (value - float(present))
        elif template.effect == "add":
            deltas[prop] = deltas.get(prop, 0.0) + value
        else:  # scale
            deltas[prop] = deltas.get(prop, 0.0) + (
                float(present) * value - float(present))
        effects[prop] = (template.effect, value)
    return deltas, assumptions, refused, effects
