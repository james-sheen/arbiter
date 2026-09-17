"""Indicators that are COMPUTED rather than fed, and the two places they are read.

WHY THIS IS NOT A NINTH AXIOM

An arbitrage-free relation, a parity residual, a spread, a conservation gap --
each looks like it wants its own checker, and none of them does. Every one is
an expression over properties the model already declares, plus an axiom that
already exists: declare `call - put - spot + strike * discount` and give it
HOMEOSTASIS with a setpoint of zero, and the engine reports departures from
parity without learning the word parity. The axioms judge the RESULT and none
of them knows it was computed.

TWO READ SITES, AND THEY FAIL DIFFERENTLY

The CURRENT value comes from `Entity.properties` at check time and is missing
when an operand is. The SERIES comes from the history and is missing when the
operands were never sampled close enough together to be treated as one moment:
two feeds are not sampled on the same tick, and subtracting a reading from one
taken a minute later is a different quantity from the one declared. The second
failure is invisible in the first, which is why `align_tolerance` is declared
and why the decline says how many points survived the join.

REFERENCES RESOLVE ONE LEVEL, FLAT

A derived indicator over another derived indicator is refused at load. The
modelling guide's third structural rule already says so for the format, and it
is the same rule: with cycles allowed there is no evaluation order and no fixed
point, and with chains allowed the order matters and nothing declares it.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..interfaces import Observation, ObservationHistory
from .parser import SafeExpressionParser

__all__ = ["operands_of", "derived_specs", "compute_current",
           "DerivedHistoryView", "DEFAULT_ALIGN_TOLERANCE"]

#: How close two operand samples must be to count as one moment when nothing is
#: declared. A default that decides which points EXIST in a derived series, so
#: it is reported on every decline that rests on it and an author who cares
#: declares `align_tolerance:`.
DEFAULT_ALIGN_TOLERANCE = timedelta(seconds=1)

_PARSER = SafeExpressionParser()


def operands_of(expression: str) -> List[str]:
    """Every property name the expression reads, or `[]` if it will not parse."""
    try:
        node = _PARSER.parse(expression)
    except (ValueError, KeyError):
        return []
    return sorted({n.id for n in ast.walk(node) if isinstance(n, ast.Name)})


def derived_specs(model, entity_type: str) -> List[Any]:
    return [spec for spec in (model.indicators.get(entity_type) or ())
            if spec.derived]


def _property_of(spec) -> str:
    return spec.property_name or spec.name


def compute_current(spec, properties: Dict[str, Any]
                    ) -> Tuple[Optional[float], List[str]]:
    """`(value, missing operands)`. A missing operand yields no value.

    Returning the MISSING NAMES rather than just None is the whole point: a
    derived indicator that does not compute declines on a property nobody
    feeds, so an author told only `missing_property: basis` goes looking for a
    feed that was never supposed to exist.
    """
    names = operands_of(spec.derived or "")
    if not names:
        return None, []
    missing = [n for n in names
               if not isinstance(properties.get(n), (int, float))
               or isinstance(properties.get(n), bool)]
    if missing:
        return None, missing
    try:
        node = _PARSER.parse(spec.derived)
        return float(_PARSER.evaluate(node, {n: float(properties[n]) for n in names})), []
    except (ValueError, KeyError, ArithmeticError, OverflowError, TypeError):
        return None, []


class DerivedHistoryView(ObservationHistory):
    """A history that also answers for indicators nobody fed.

    Wraps any store. A request for a declared derived indicator is served by
    as-of joining its operand series; everything else is passed straight
    through, so a model with no derived indicators is a pure delegation.
    """

    def __init__(self, inner: ObservationHistory, model: Any) -> None:
        self.inner = inner
        self.model = model
        self._by_property: Dict[str, Any] = {}
        for specs in (getattr(model, "indicators", {}) or {}).values():
            for spec in specs:
                if spec.derived:
                    self._by_property.setdefault(_property_of(spec), spec)

    # -- the derived series --------------------------------------------------

    def _join(self, entity_id: str, spec, window: timedelta
              ) -> Tuple[List[Tuple[datetime, float]], Dict[str, int]]:
        """As-of join the operands. Returns the series and the counts behind it."""
        names = operands_of(spec.derived or "")
        tolerance = spec.align_tolerance or DEFAULT_ALIGN_TOLERANCE
        series = {n: self.inner.get_values(entity_id, n, window) for n in names}
        counts = {n: len(s) for n, s in series.items()}
        if not names or any(not s for s in series.values()):
            return [], counts
        anchor_name = min(series, key=lambda n: len(series[n]))
        others = [n for n in names if n != anchor_name]
        out: List[Tuple[datetime, float]] = []
        for stamp, value in series[anchor_name]:
            bindings = {anchor_name: value}
            for other in others:
                nearest = _nearest(series[other], stamp, tolerance)
                if nearest is None:
                    break
                bindings[other] = nearest
            else:
                try:
                    node = _PARSER.parse(spec.derived)
                    out.append((stamp, float(_PARSER.evaluate(node, bindings))))
                except (ValueError, KeyError, ArithmeticError,
                        OverflowError, TypeError):
                    continue
        return out, counts

    def alignment(self, entity_id: str, property_name: str,
                  window: timedelta) -> Optional[Dict[str, Any]]:
        """What the join produced, for a decline that has to explain itself."""
        spec = self._by_property.get(property_name)
        if spec is None:
            return None
        joined, counts = self._join(entity_id, spec, window)
        return {"operands": counts, "aligned": len(joined),
                "align_tolerance_s": (spec.align_tolerance
                                      or DEFAULT_ALIGN_TOLERANCE).total_seconds()}

    # -- the contract --------------------------------------------------------

    def get_values(self, entity_id: str, property_name: str,
                   window: timedelta) -> List[Tuple[datetime, float]]:
        spec = self._by_property.get(property_name)
        if spec is None:
            return self.inner.get_values(entity_id, property_name, window)
        return self._join(entity_id, spec, window)[0]

    def get_states(self, entity_id: str, property_name: str,
                   window: timedelta) -> List[Tuple[datetime, str]]:
        return self.inner.get_states(entity_id, property_name, window)

    def get_observations(self, entity_id: str, start: datetime,
                         end: datetime) -> List[Observation]:
        return self.inner.get_observations(entity_id, start, end)

    def get_observation_count(self, entity_id: str, property_name: str) -> int:
        spec = self._by_property.get(property_name)
        if spec is None:
            return self.inner.get_observation_count(entity_id, property_name)
        # The count of a derived series is the count of its SCARCEST operand:
        # no join can produce more points than that, and reporting the richest
        # would promise a series the engine cannot build.
        names = operands_of(spec.derived or "")
        if not names:
            return 0
        return min(self.inner.get_observation_count(entity_id, n) for n in names)

    def add(self, entity_id: str, property_name: str, value: Any,
            timestamp: Optional[datetime] = None) -> None:
        self.inner.add(entity_id, property_name, value, timestamp)


def _nearest(series: Sequence[Tuple[datetime, float]], stamp: datetime,
             tolerance: timedelta) -> Optional[float]:
    best, best_gap = None, None
    for other_stamp, value in series:
        gap = abs((other_stamp - stamp).total_seconds())
        if best_gap is None or gap < best_gap:
            best, best_gap = value, gap
    if best_gap is None or best_gap > tolerance.total_seconds():
        return None
    return best
