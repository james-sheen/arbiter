"""Resolving a reference to a value on ANOTHER entity.

WHY THIS IS SHARED AND NOT WRITTEN TWICE

CONSERVATION balances an input against outputs and CONSISTENCY compares a
reading against readings that must agree with it. Both reach the same way --
follow a declared edge, read a declared property off whatever is at the end of
it -- and both fail the same ways: the edge resolves to nobody, the thing at
the end has no such property, several things answer and nothing said how to
combine them. Two copies of that would disagree about which of those is a
decline and which is a finding, and the whole value of a closed decline
vocabulary is that they cannot.

WHAT A REFERENCE LOOKS LIKE

    output_properties: [orders_filled]                       # this entity
    output_properties: [{via: routes_to, property: filled}]  # across an edge

A bare string is the existing form and means a property of the entity being
checked. A mapping crosses one edge. ONE edge, not a path: the format's third
structural rule is that references resolve one level, and a chain here would
have the same missing evaluation order that `derived:` refuses for the same
reason.

WHY AN ABSENT PEER IS NOT A ZERO

The engine already learned this one property at a time: summing an absent
output as zero turned an unobserved channel into a 100% deficit reported as a
fault in the system, when the fault was a property name the model got wrong.
Across an edge there is one more way to be absent -- no edge at all -- and it
is the one most likely to mean *this model has not been finished*. It declines
rather than resolving to an empty sum.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = ["PeerRef", "parse_reference", "resolve_peer", "AGGREGATES",
           "PeerResolution"]

#: How several answers become one. Declared, never chosen: with two peers
#: answering 10 and 20 there is no reading of the model that says whether the
#: author meant 30, 15 or either one.
AGGREGATES = {
    "sum": sum,
    "mean": statistics.fmean,
    "median": statistics.median,
    "max": max,
    "min": min,
}


@dataclass(frozen=True)
class PeerRef:
    """`{via: <relation>, property: <name>, aggregate: <fn>}`."""

    via: str
    property: str
    aggregate: Optional[str] = None

    def __str__(self) -> str:
        return f"{self.property} via {self.via}"


@dataclass(frozen=True)
class PeerResolution:
    """What the reference resolved to, and why it did not."""

    values: List[float]
    targets: List[str]
    reason: Optional[str] = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.reason is None


def parse_reference(entry: Any) -> Tuple[Optional[str], Optional[PeerRef], Optional[str]]:
    """`(same-entity property, peer reference, why it is neither)`."""
    if isinstance(entry, str):
        return entry, None, None
    if isinstance(entry, Mapping):
        via, prop = entry.get("via"), entry.get("property")
        if not via or not prop:
            return None, None, (
                f"a cross-entity reference needs both `via` and `property`; "
                f"got {dict(entry)!r}")
        aggregate = entry.get("aggregate")
        if aggregate is not None and str(aggregate) not in AGGREGATES:
            return None, None, (
                f"`aggregate: {aggregate}` is not one of {sorted(AGGREGATES)}")
        return None, PeerRef(str(via), str(prop),
                             str(aggregate) if aggregate else None), None
    return None, None, f"{entry!r} is neither a property name nor a reference"


def resolve_peer(entity, ref: PeerRef, graph, entities, history,
                 window: timedelta, *, require_aggregate: bool) -> PeerResolution:
    """Read `ref.property` off everything `ref.via` reaches from `entity`.

    `require_aggregate` is the difference between the two callers, and it is a
    real difference rather than a flag for convenience. CONSERVATION sums an
    output side by definition -- three outfeeds carry three parts of one flow.
    CONSISTENCY compares against a reading, and three readings are three
    candidate answers; picking one without being told would make the verdict
    depend on iteration order.
    """
    if entities is None:
        return PeerResolution([], [], "precondition_unmet", (
            f"`{ref}` crosses an edge and this check was called without the "
            f"entity index, so the other end cannot be read"))

    targets = list(graph.get_relationships(entity.id, ref.via) or ())
    if not targets:
        return PeerResolution([], [], "precondition_unmet", (
            f"no `{ref.via}` edge from {entity.id}, so `{ref}` names nothing; "
            f"declare the relationship or drop the reference"))

    values: List[float] = []
    reached: List[str] = []
    absent: List[str] = []
    for target_id in sorted(targets):
        target = entities.get(target_id)
        if target is None:
            absent.append(target_id)
            continue
        series = history.get_values(target_id, ref.property, window)
        if series:
            values.append(sum(v for _, v in series if v is not None))
            reached.append(target_id)
            continue
        current = target.get_property(ref.property) if hasattr(
            target, "get_property") else (target.properties or {}).get(ref.property)
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            values.append(float(current))
            reached.append(target_id)
        else:
            absent.append(target_id)

    if not values:
        return PeerResolution([], [], "missing_property", (
            f"`{ref.via}` reaches {sorted(targets)} and none of them carries "
            f"`{ref.property}`; the edge is declared and the property is not"))

    if require_aggregate and len(values) > 1 and ref.aggregate is None:
        return PeerResolution(values, reached, "missing_config", (
            f"`{ref}` resolves to {len(values)} readings and no `aggregate:` "
            f"says how to combine them; declare one of {sorted(AGGREGATES)}"))

    if ref.aggregate:
        values = [float(AGGREGATES[ref.aggregate](values))]
    return PeerResolution(values, reached,
                          detail=(f"{len(reached)} of {len(targets)} via "
                                  f"`{ref.via}`"
                                  + (f"; {len(absent)} carried no "
                                     f"`{ref.property}`" if absent else "")))
