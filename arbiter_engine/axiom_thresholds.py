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
CD508_ENTITY_PROPERTY_KEY = "__cd508_axiom_thresholds__"


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

        warn = resolve_axiom_threshold(entity, "cpu", "BOUNDEDNESS",
            fallback=self.params.boundedness_warning_ratio,
            bound="warn")

    Args:
        entity: Detection Entity (real or test fixture). Read via
            ``entity.properties.get(CD508_ENTITY_PROPERTY_KEY, {})``.
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

    override_dict = props.get(CD508_ENTITY_PROPERTY_KEY)
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
