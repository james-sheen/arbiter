"""Per-entity axiom threshold overrides — resolution, and the key they live under.

This code was in `arbiter_engine/twin/monte_carlo_predictor.py`, which is
where it was first needed and not where it belongs. Six of the eight axiom
checkers import `resolve_axiom_threshold`, and none of them have anything to
do with Monte Carlo simulation — they were reaching across the package into a
1,080-line predictor to fetch eighty lines of dictionary lookup.

That coupling had a concrete cost: `arbiter-oss-strategy.md` puts the Monte
Carlo predictor out of the v0.1 engine extraction, and executing that cut as
written would have taken six checkers with it. Moving the resolver here makes
the predictor deletable without touching `ontology/axioms/` at all.

The behaviour is unchanged and deliberately so — this is a relocation, not a
rewrite. `monte_carlo_predictor` re-exports both names so existing imports
keep working.

## What an override is

A simulation (or any caller) can stamp per-entity threshold overrides onto an
entity's own properties under a single sentinel key. Checkers read through
`resolve_axiom_threshold`, which returns the override when one is present for
`(indicator, axiom)` and the caller's fallback otherwise. Fallbacks are
normally scalars from the global `AxiomParameters`.

Storing overrides on the entity rather than in a side channel is what lets a
per-sample perturbation flow through the ordinary detection path without any
checker knowing it is being simulated.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Entity-property key carrying per-entity threshold overrides. The value is a
#: dict of ``(indicator, axiom) -> (warn, critical)``. Named with the sentinel
#: dunder shape so it cannot collide with a real domain property.
AXIOM_THRESHOLD_OVERRIDES_KEY = "__axiom_threshold_overrides__"

# =====================================================================
# WHAT AN OVERRIDE ACTUALLY REACHES —, measured rather than read
# =====================================================================
#
# An outside report asked for this resolver to be "wired into the checkers",
# on the finding that BOUNDEDNESS never calls it. It does call it, and has
# since long before the report; that finding was measured against a release
# the reporter did not pin. What measuring the CURRENT tree found instead is
# two facts that matter more, and neither is visible by reading a call site.
#
# FIRST: an override reaches FIVE of the eight axioms. Six checkers call the
# resolver, and ONE of those calls sits on a path nothing invokes -- so setting
# an override for that one is silent and always has been.
#
# An internal ruling corrected this from four/two on 2026-08-28. RESPONSIVENESS was filed
# as unreachable and is not: `check_io_pair` runs, fires, and honours the
# override, on any session given I/O relationships through the public
# `session.reasoner.set_io_relationships(...)`. Undocumented is not
# unreachable, and this table claimed the second.
#
# SECOND, and this is the one a consumer needs: **an override never touches a
# declared threshold.** The `warning:` and `critical:` an indicator declares in
# its domain model are read straight off the spec, on a path with no override
# lookup at all. What the five reachable axioms override is their CALIBRATION
# parameter -- how oscillation is scored, how fast a counter may fall, how much
# loss a balance tolerates, how many deviations count as drift. Those are
# genuinely useful and they are not what "per-entity thresholds" sounds like.
#
# The gap that leaves is CLOSED, and this comment described it as open for a
# release after it was. A consumer needing per-instance `warning`/`critical`
# -- hundreds of sensors, each with its own vendor limits -- declares
# `{from_property: <name>}` and the bound is read off each entity at check
# time; `set_declared_thresholds` does the same for a bound a caller holds
# rather than a model declares. Both live in this module, below. What remains
# true is the distinction the paragraph above draws: an axiom override retunes
# CALIBRATION and has never touched a declared bound, and the two are separate
# tables so that a reader cannot mistake one for the other.
#
# Every row below is established by running the engine both ways -- with the
# override absent and present -- and watching the verdict move or not. The
# table is documentation; `tests/test_threshold_overrides.py` is the oracle,
# and it re-derives every row against the engine rather than trusting this.
#
# AND IT WAS DRIVEN, WHICH IS WHY IS WORTH READING. The unreachable
# rows had a both-ways test of their own -- run with the override, run
# without, assert the verdict does NOT move -- and RESPONSIVENESS passed it
# for months while the engine honoured its override.
#
# The scenario was the predicate. This axiom carries TWO override-relevant
# paths: a declared `warning:`/`critical:` on latency, and
# `correlation_drop_threshold` on the I/O pair. The row's scenario fired the
# first, where an override correctly does nothing -- because no DECLARED
# bound is overridable in any axiom -- so the test confirmed *unreachable*
# by exercising the one path on which that answer is right for another
# reason entirely. A wrong scenario that yields the claimed answer reads
# exactly like a confirmation.
#
# The remedy is in the scenario, not the assertion: the row now supplies two
# entities and an I/O relationship, and puts the override on the OUTPUT
# entity, which is the side the resolver reads.

#: Axioms whose firing decision consults an override, and the parameter it
#: replaces. Reaching these is proven, both directions, per axiom.
OVERRIDE_CONSULTED_BY = {
    "STABILITY": "oscillation_threshold — how much hunting counts as unstable",
    "MONOTONICITY": "rate_warning / rate_critical — how fast a counter may move",
    "CONSERVATION": "loss_margin — how much imbalance a flow may lose",
    "HOMEOSTASIS": "z_warning / z_critical — deviations from baseline",
    "RESPONSIVENESS": (
        "correlation_drop_threshold — how far an I/O correlation may fall; "
        "read off the OUTPUT entity, and only on a session given I/O "
        "relationships"
    ),
}

#: Axioms that CALL the resolver on a path the engine's own entry points never
#: reach. An override for these is accepted, stored, and never read.
OVERRIDE_DECLARED_BUT_UNREACHABLE: dict = {}
#:, executed. Its one entry was BOUNDEDNESS, whose only call to the
#: resolver sat inside `check_capacity_ratio` -- a used/limit method nothing in
#: the package invoked, so a per-entity override was accepted and ignored. The
#: ruling deleted the method rather than wiring it: wiring means designing a
#: declaration channel, a loader change, documentation and tests for a
#: capability no consumer has asked for, which is far harder to withdraw than a
#: method is to restore.
#:
#: **The constant stays, empty, and that is the point.** An empty group is a
#: checkable claim that no axiom is in this state; deleting it would turn the
#: claim into an absence, and the partition test covering all eight axioms
#: would have nothing to cover the gap with.

#: Axioms with no override lookup anywhere. Listed so the set is closed and a
#: reader can tell "not supported" from "we did not check".
OVERRIDE_NOT_CONSULTED = ("BOUNDEDNESS", "CONNECTIVITY", "CONSISTENCY")


def resolve_axiom_threshold(
    entity: Any,
    indicator: str,
    axiom: str,
    fallback: Any,
    *,
    bound: str = "warn",
) -> Any:
    """Return the per-entity override for ``(indicator, axiom)``, else ``fallback``.

    Integration pattern at an axiom-checker read site:

        warn = resolve_axiom_threshold(
            entity, "cpu", "BOUNDEDNESS",
            fallback=self.params.boundedness_warning_ratio,
            bound="warn",
        )

    Args:
        entity: Detection Entity (real or test fixture). Read via
            ``entity.properties.get(AXIOM_THRESHOLD_OVERRIDES_KEY, {})``.
        indicator: Indicator name, e.g. ``"cpu"``.
        axiom: Axiom name, e.g. ``"BOUNDEDNESS"``.
        fallback: Returned when no override applies. Typically a scalar from
            ``self.params.<field>``; may be None.
        bound: ``"warn"`` (default) / ``"critical"`` / ``"both"``. ``"both"``
            returns the whole ``(warn, critical)`` tuple; unknown values fall
            through to ``"warn"``.

    Returns:
        The override for the selected bound when present and non-None,
        otherwise ``fallback``.

    The return shape follows the caller: a scalar fallback yields a scalar, and
    ``bound="both"`` yields a tuple. That variance is intentional — it lets each
    read site consume the shape it actually wants — but single-threshold check
    paths should prefer the scalar forms, which read more clearly.

    Every failure path returns ``fallback``. A malformed override is a fault in
    whatever wrote it, and the right behaviour is to fall back to the
    configured threshold with a warning rather than to let a simulation artifact
    crash live detection.
    """
    if entity is None:
        return fallback

    props = getattr(entity, "properties", None)
    if not props:
        return fallback

    override_dict = props.get(AXIOM_THRESHOLD_OVERRIDES_KEY)
    if not override_dict or not isinstance(override_dict, dict):
        return fallback

    bounds_tuple = override_dict.get((indicator, axiom))
    if bounds_tuple is None:
        return fallback

    if not isinstance(bounds_tuple, tuple) or len(bounds_tuple) != 2:
        # The marker is load-bearing, not decoration: it is the audit
        # grep handle for this fallback and is pinned by
        # test_axiom_threshold_resolver_cd509. Dropping it during the
        # relocation broke that pin, which is how it was found.
        logger.warning(
            "resolve_axiom_threshold: malformed override entry for "
            "(%r, %r) on entity %r — expected a (warn, critical) 2-tuple, "
            "got %r. Falling back.",
            indicator, axiom, getattr(entity, "id", "<unknown>"), bounds_tuple,
        )
        return fallback

    warn, critical = bounds_tuple
    if bound == "critical":
        return critical if critical is not None else fallback
    if bound == "both":
        return bounds_tuple
    return warn if warn is not None else fallback


# --------------------------------------------------------------------------
# B-2.7 — declared bounds that differ per instance
#
# EVERYTHING ABOVE IS A DIFFERENT CAPABILITY and the two are easy to confuse.
# `resolve_axiom_threshold` replaces an axiom's CALIBRATION PARAMETER -- how
# much hunting counts as unstable, how far an I/O correlation may fall -- and
# `set_threshold_override` says in its own docstring that it does not touch a
# declared `warning:` or `critical:`. BOUNDEDNESS sits in
# `OVERRIDE_NOT_CONSULTED` for exactly that reason. What follows is the thing
# that docstring tells a caller the engine does not have.
#
# Two ways in, and they answer different questions:
#
#   `critical: {from_property: contracted_ceiling}` in the MODEL -- the bound
#   is a number that arrives with the entity, from whatever system owns it. It
#   moves when the data moves and nobody has to call anything.
#
#   `set_declared_thresholds(...)` on the SESSION -- this one entity's bound,
#   set by a caller, with no model edit. Reaches indicators whose model
#   declares a literal or nothing at all, which the first cannot.
# --------------------------------------------------------------------------

#: Entity-property key carrying per-instance DECLARED bounds. Keyed
#: ``(property_name, field)`` where field is one of `THRESHOLD_FIELDS`, holding
#: a number. A second sentinel rather than a second meaning for the first:
#: `AXIOM_THRESHOLD_OVERRIDES_KEY` is keyed by AXIOM and holds calibration
#: parameters, and one table holding both kinds would make the two capabilities
#: indistinguishable at the point a reader most needs to tell them apart.
DECLARED_THRESHOLDS_KEY = "__declared_thresholds__"

#: The four YAML keys a bound is declared under. Ordered ceiling-then-floor to
#: match the dataclass, and iterated wherever all four must be handled the same
#: way -- handling three of four is how the floor pair was missed once already
#: (the overlay resolution).
#:
#: HERE, and the loader IMPORTS it. It was written out in both for an afternoon,
#: which is the number-written-twice defect this package has a long record of:
#: the copy goes stale the first time a fifth field is added, and the direction
#: of the import is what makes one copy possible -- this module holds only
#: stdlib imports, so nothing cycles.
THRESHOLD_FIELDS = ("warning", "critical", "lower_warning", "lower_critical")


def resolve_declared_threshold(entity: Any, spec: Any, field: str,
                               literal: Any) -> tuple:
    """``(value, origin, detail)`` for one bound on one entity.

    ``origin`` is ``instance``, ``property``, ``declared`` or ``absent`` and is
    returned rather than inferred, because the three cases produce the same
    kind of number and a reader who has to act needs to know which system to go
    and look at.

    ``detail`` is a sentence when a bound was DECLARED and could not be
    resolved, and None otherwise. The caller declines on it. A bound the author
    asked for and the engine could not find is not the same as no bound: the
    first is an unanswered check, the second is a check nobody asked for, and
    silently treating one as the other is how `axioms: [BOUNDEDNES]` used to
    produce a clean envelope.
    """
    table = getattr(entity, "properties", None) or {}
    instance = (table.get(DECLARED_THRESHOLDS_KEY) or {}).get(
        (getattr(spec, "property_name", "") or getattr(spec, "name", ""), field))
    if instance is not None:
        try:
            return float(instance), "instance", None
        except (TypeError, ValueError):
            return None, "absent", (
                f"an instance {field} was set for this entity and is not a "
                f"number: {instance!r}")

    source = (getattr(spec, "threshold_sources", None) or {}).get(field)
    if source is not None:
        raw = table.get(source)
        if raw is None:
            return None, "absent", (
                f"`{field}: {{from_property: {source}}}` is declared and this "
                f"entity carries no {source}; the bound comes from your data, "
                f"so there is nothing to check against until it arrives")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None, "absent", (
                f"`{field}: {{from_property: {source}}}` resolved to {raw!r}, "
                f"which is not a number")
        if value != value or value in (float("inf"), float("-inf")):
            return None, "absent", (
                f"`{field}: {{from_property: {source}}}` resolved to a value "
                f"that is not a measurement; a bound has to be a finite number")
        return value, "property", None

    if literal is not None:
        return float(literal), "declared", None
    return None, "absent", None


def resolve_config_number(entity: Any, raw: Any, *, where: str) -> tuple:
    """``(value, detail)`` for one number inside an axiom configuration block.

    The same `{from_property: <name>}` form the four bounds take, for the
    numbers that do not live in a spec slot -- a HOMEOSTASIS setpoint and its
    tolerance. A target balance differs per account exactly as a margin
    requirement does, and offering the form on four keys and not on these two
    would make which keys accept it a thing to memorise.

    Returns the value unchanged when it is not a mapping, so every existing
    literal keeps working and this function can sit on the read path without a
    caller asking first whether it applies.
    """
    from collections.abc import Mapping
    if not isinstance(raw, Mapping):
        return raw, None
    name = raw.get("from_property")
    if not isinstance(name, str) or not name.strip():
        return None, (f"`{where}` was declared as a mapping this engine cannot "
                      f"read: {dict(raw)!r}; the form is "
                      f"`{{from_property: <property name>}}`")
    name = name.strip()
    value = (getattr(entity, "properties", None) or {}).get(name)
    if value is None:
        return None, (f"`{where}: {{from_property: {name}}}` is declared and "
                      f"this entity carries no {name}")
    try:
        return float(value), None
    except (TypeError, ValueError):
        return None, (f"`{where}: {{from_property: {name}}}` resolved to "
                      f"{value!r}, which is not a number")


def effective_thresholds(entity: Any, spec: Any) -> tuple:
    """``(values, origins, detail)`` for all four bounds on one entity.

    One call, because the contradiction check reads all four together and a
    band assembled from bounds resolved at different times would be checked
    against itself. The first unresolvable declaration wins the decline --
    reporting four sentences for one missing feed would bury the one that
    matters.
    """
    literals = {
        "warning": getattr(spec, "warning_threshold", None),
        "critical": getattr(spec, "critical_threshold", None),
        "lower_warning": getattr(spec, "lower_warning_threshold", None),
        "lower_critical": getattr(spec, "lower_critical_threshold", None),
    }
    values, origins, first = {}, {}, None
    for field in THRESHOLD_FIELDS:
        value, origin, detail = resolve_declared_threshold(
            entity, spec, field, literals[field])
        values[field], origins[field] = value, origin
        if detail is not None and first is None:
            first = detail
    return values, origins, first
