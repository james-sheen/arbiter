"""`expected_findings` is a sum of reciprocals, and it is summed EXACTLY.

`severity_weight` derives a cost from the engine's one priority
scale -- `1.0 / priority_score`, so critical costs 1, high 1/2, medium and
warning 1/3, low 1/4, info 1/5. Deriving rather than tabulating is right and
is not what this is about. The objective then added those reciprocals in
BINARY FLOATING POINT, where 1/3 and 1/5 have no exact representation, so the
total depended on how many findings of which severity arrived in what order.

Two consequences, and the second is the one that changes an answer.

THE REPORTED NUMBER IS WRONG IN ITS LAST BITS, on the package's own published
example. `pump_tank_dynamics.yaml` at a 92 % tank scores its first two
candidates over 24 findings of priorities 1 and 3, whose exact cost is 16.
Measured: `16.000000000000004`.

TWO PLANS THAT COST THE SAME STOP COMPARING EQUAL. The planner sorts on
`(objective, len(actions))` and its own comment says *fewer actions wins an
EXACT tie* -- so a tie broken by rounding is not a tie at all, and the
candidate carrying more actions wins on 4e-16 of accumulated error. Searching
every multiset of at most eight findings over the five reachable weights
finds 67 exact totals that more than one float value can represent. The
sharpest:

    priorities [2, 3, 3, 3, 5, 5, 5, 5] -> 2.3
    priorities [1, 2, 5, 5, 5, 5] -> 2.3000000000000003

Both are exactly 23/10. Under `minimise` the eight-finding plan beats the
six-finding one, and `ties_break_toward_fewer_actions` -- which the engine
stamps on the envelope -- never fires.

THE FIX NEEDS NO TOLERANCE, which is why it is the right one here. A
tolerance would be the engine deciding how close two costs have to be before
it calls them equal, and that is a domain question nobody declared. The
weights are reciprocals of small positive integers, so the sum has an exact
rational value; accumulating it as one and converting to float at the end
makes equal things compare equal by construction. The engine reports the same
`float` it always did, only now it is the correctly rounded one.
"""
from __future__ import annotations

import pathlib
from fractions import Fraction
from itertools import combinations_with_replacement

import pytest

from arbiter_engine import api
from arbiter_engine.twin.planner import score, severity_weight
from arbiter_engine.types import Severity


def _examples_dir() -> pathlib.Path:
    """Whichever copy this tree has: the built package ships `examples/` at its
    root, the source tree keeps them under the publication docs. NOT an
    absolute path -- an absolute path into the source repository is a reference the
    build refuses, and rightly: this file ships."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "docs" / "publication"
                      / "engine-example"):
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    raise AssertionError("no examples directory found in this tree")


EXAMPLE = str(_examples_dir() / "pump_tank_dynamics.yaml")


class _Finding:
    """The only thing `score` reads off a finding."""

    def __init__(self, severity):
        self.severity = severity


BY_PRIORITY = {1: Severity.CRITICAL, 2: Severity.HIGH, 3: Severity.MEDIUM,
               4: Severity.LOW, 5: Severity.INFO}


def _objective(priorities):
    value, interval, assumptions = score(
        None, "expected_findings", "warning",
        [_Finding(BY_PRIORITY[p]) for p in priorities], 0, 0)
    return value


def _exact(priorities):
    return sum((Fraction(1, p) for p in priorities), Fraction(0))


class TestThePremise:
    """If the scale ever stops being reciprocals of small integers this file
    stops being about anything, and should say so rather than pass."""

    def test_every_weight_is_the_reciprocal_of_its_priority(self):
        for priority, severity in BY_PRIORITY.items():
            assert severity.priority_score == priority
            assert severity_weight(severity) == pytest.approx(1.0 / priority)


class TestTwoPlansThatCostTheSameCompareEqual:

    def test_the_sharpest_reachable_pair(self):
        wide = [2, 3, 3, 3, 5, 5, 5, 5]
        narrow = [1, 2, 5, 5, 5, 5]
        assert _exact(wide) == _exact(narrow) == Fraction(23, 10), (
            "the premise: these two cost the same by the engine's own scale")
        assert _objective(wide) == _objective(narrow), (
            f"eight findings score {_objective(wide)!r} and six score "
            f"{_objective(narrow)!r}; they cost the same, so a planner "
            f"sorting on (objective, len(actions)) hands the win to whichever "
            f"one rounded lower")

    def test_no_reachable_multiset_disagrees_with_its_exact_cost(self):
        """The general statement, over every multiset the engine can produce
        up to eight findings: the objective IS the exact cost, correctly
        rounded, so equal costs are equal floats."""
        wrong = []
        for size in range(1, 9):
            for priorities in combinations_with_replacement(range(1, 6), size):
                got = _objective(list(priorities))
                want = float(_exact(priorities))
                if got != want:
                    wrong.append((priorities, got, want))
        assert not wrong, (
            f"{len(wrong)} multisets scored something other than their exact "
            f"cost; first three: {wrong[:3]}")


class TestTheShippedExampleReportsAWholeNumber:

    def _session(self):
        session = api.EngineSession()
        session.load_model(EXAMPLE)
        session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
        session.add_entity("tank1", "Tank", {"level_pct": 92.0})
        session.add_relationship("pump1", "feeds", "tank1")
        return session

    def test_the_do_nothing_objective_is_exactly_sixteen(self):
        plan = api.plan(self._session(), horizon_s=3600.0,
                        step_s=300.0).to_dict()["plan"]
        candidates = plan["candidates"]
        assert candidates, "the example must still produce candidates"
        do_nothing = [c for c in candidates if c["plan"] == "do_nothing"]
        assert do_nothing, "the example must still score doing nothing"
        assert do_nothing[0]["objective"] == 16.0, (
            f"the published example reports "
            f"{do_nothing[0]['objective']!r} over 24 findings whose exact "
            f"cost is 16")


class TestTheOrderingItselfIsUnchanged:
    """The floors. Making the sum exact must not touch what the scale MEANS:
    a worse finding still costs more, and more findings still cost more."""

    def test_a_worse_finding_still_costs_more(self):
        assert _objective([1]) > _objective([2]) > _objective([3]) > (
            _objective([4])) > _objective([5])

    def test_more_findings_still_cost_more(self):
        assert _objective([3, 3, 3]) > _objective([3, 3]) > _objective([3])

    def test_an_unscored_severity_still_costs_nothing(self):
        value, _, _ = score(None, "expected_findings", "warning",
                            [_Finding(None)], 0, 0)
        assert value == 0.0

    def test_no_findings_is_zero_not_none(self):
        value, _, _ = score(None, "expected_findings", "warning", [], 0, 0)
        assert value == 0.0
