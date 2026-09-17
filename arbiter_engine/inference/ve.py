"""Exact inference by variable elimination over binary noisy-OR factors.

WHY NOISY-OR

It is the assumption an operator can actually state: each faulty parent
independently has some chance of breaking the child, and there is a leak for
everything that was not modelled. Writing a full conditional table for a node
with four parents means sixteen numbers nobody has; noisy-OR asks for one per
edge, which is the number an author can defend from a datasheet or a count.

WHY EXACT, AND WHERE EXACT STOPS

Variable elimination is exact -- no sampling, no convergence to argue about --
and its cost is exponential in the size of the largest intermediate factor,
not in the number of nodes. A chain of a thousand nodes is trivial; a node
with thirty parents is not, because eliminating it builds a factor over
thirty-one variables, which is two billion entries.

That is the same shape as the entailment join: a bound that keeps the WORST
case describable does not make it affordable. So elimination stops at a
declared factor size and says so, and the refusal names the variable whose
elimination was too wide.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = ["Factor", "noisy_or_factor", "eliminate", "FactorTooWide",
           "FACTOR_VARIABLE_LIMIT"]

#: The widest intermediate factor elimination will build. 2**20 entries is a
#: million; past that the answer stops arriving rather than stops being exact,
#: and an engine that does not return is worse than one that refuses.
FACTOR_VARIABLE_LIMIT = 20


class FactorTooWide(Exception):
    """Raised with the variable whose elimination exceeded the limit."""

    def __init__(self, variable: str, width: int) -> None:
        super().__init__(f"eliminating {variable!r} needs a factor over {width} "
                         f"variables; the limit is {FACTOR_VARIABLE_LIMIT}")
        self.variable = variable
        self.width = width


@dataclass
class Factor:
    """A function from an assignment of `variables` to a non-negative number."""

    variables: Tuple[str, ...]
    table: Dict[Tuple[int, ...], float]

    def multiply(self, other: "Factor") -> "Factor":
        merged = tuple(self.variables) + tuple(
            v for v in other.variables if v not in self.variables)
        if len(merged) > FACTOR_VARIABLE_LIMIT:
            raise FactorTooWide(",".join(merged), len(merged))
        left = [merged.index(v) for v in self.variables]
        right = [merged.index(v) for v in other.variables]
        table: Dict[Tuple[int, ...], float] = {}
        for assignment in itertools.product((0, 1), repeat=len(merged)):
            a = tuple(assignment[i] for i in left)
            b = tuple(assignment[i] for i in right)
            value = self.table.get(a, 0.0) * other.table.get(b, 0.0)
            if value:
                table[assignment] = value
        return Factor(merged, table)

    def sum_out(self, variable: str) -> "Factor":
        if variable not in self.variables:
            return self
        index = self.variables.index(variable)
        kept = tuple(v for v in self.variables if v != variable)
        table: Dict[Tuple[int, ...], float] = {}
        for assignment, value in self.table.items():
            reduced = assignment[:index] + assignment[index + 1:]
            table[reduced] = table.get(reduced, 0.0) + value
        return Factor(kept, table)

    def restrict(self, evidence: Dict[str, int]) -> "Factor":
        relevant = [v for v in self.variables if v in evidence]
        if not relevant:
            return self
        kept = tuple(v for v in self.variables if v not in evidence)
        keep_index = [self.variables.index(v) for v in kept]
        table: Dict[Tuple[int, ...], float] = {}
        for assignment, value in self.table.items():
            if any(assignment[self.variables.index(v)] != evidence[v]
                   for v in relevant):
                continue
            table[tuple(assignment[i] for i in keep_index)] = value
        return Factor(kept, table)


def noisy_or_factor(node: str, parents: Sequence[str],
                    weights: Sequence[float], leak: float) -> Factor:
    """P(node | parents) under noisy-OR.

    P(node = 0 | parents) = (1 - leak) * PRODUCT over faulty parents of (1 - w).
    Each faulty parent independently fails to break the child; the leak covers
    everything nobody modelled.
    """
    variables = (node,) + tuple(parents)
    if len(variables) > FACTOR_VARIABLE_LIMIT:
        raise FactorTooWide(node, len(variables))
    table: Dict[Tuple[int, ...], float] = {}
    for assignment in itertools.product((0, 1), repeat=len(parents)):
        survive = 1.0 - leak
        for parent_state, weight in zip(assignment, weights):
            if parent_state:
                survive *= (1.0 - weight)
        table[(0,) + assignment] = survive
        table[(1,) + assignment] = 1.0 - survive
    return Factor(variables, table)


def _elimination_order(factors: Sequence[Factor], keep: Iterable[str]) -> List[str]:
    """Min-degree: eliminate the variable sharing factors with the fewest others.

    A heuristic, and named as one. The elimination ORDER does not change the
    answer -- only how wide the intermediate factors get -- so a bad order
    costs time or a refusal, never correctness.
    """
    keep = set(keep)
    remaining = {v for factor in factors for v in factor.variables} - keep
    order: List[str] = []
    live = list(factors)
    while remaining:
        best, best_degree = None, None
        for variable in sorted(remaining):
            neighbours = {v for factor in live if variable in factor.variables
                          for v in factor.variables} - {variable}
            degree = len(neighbours)
            if best_degree is None or degree < best_degree:
                best, best_degree = variable, degree
        order.append(best)
        remaining.discard(best)
        touching = [f for f in live if best in f.variables]
        merged = {v for f in touching for v in f.variables} - {best}
        live = [f for f in live if best not in f.variables]
        live.append(Factor(tuple(sorted(merged)), {}))
    return order


def eliminate(factors: Sequence[Factor], target: str,
              evidence: Dict[str, int]) -> Optional[float]:
    """P(target = 1 | evidence). None when the evidence has probability zero.

    Returning None rather than raising: evidence that cannot happen under the
    declared model is a fact about the MODEL, and the caller turns it into a
    decline naming it. Dividing by zero would turn it into a crash.
    """
    live = [f.restrict(evidence) for f in factors]
    live = [f for f in live if f.variables or f.table]
    for variable in _elimination_order(live, keep={target}):
        touching = [f for f in live if variable in f.variables]
        if not touching:
            continue
        product = touching[0]
        for other in touching[1:]:
            product = product.multiply(other)
        live = [f for f in live if variable not in f.variables]
        live.append(product.sum_out(variable))

    result = None
    for factor in live:
        result = factor if result is None else result.multiply(factor)
    if result is None:
        return None
    for variable in [v for v in result.variables if v != target]:
        result = result.sum_out(variable)
    if target not in result.variables:
        return None
    positive = result.table.get((1,), 0.0)
    total = positive + result.table.get((0,), 0.0)
    if total <= 0:
        return None
    return positive / total
