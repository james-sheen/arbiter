"""Two different things undeclared in one place are two questions.

`gaps` deduplicated its questions on `(gap_type, location)`, which
assumes each type asks a single question at a given place. `MISSING_DECLARATION`
stopped being one claim when a refused `transition:` block started using it, and
a second arrived that an internal ruling added: an edge whose time course this engine
supplied. An internal ruling had already recorded in a comment that the type no longer
determines the question, and fixed the question TEMPLATE. The key beside it kept the old
assumption, so the second claim was collapsed into the first and dropped.

HOW TO REPRODUCE IT, because the obvious attempt does not. Removing both
`temporal:` and `transition.source` from the shipped model yields ONE gap, not
two deduplicated: a transition missing a required key is refused, and a refused
transition means there is nothing to project across the edge, so the time-course
gap is never raised at all. The two claims coexist only where one transition on
the rule is complete -- raising the time-course question -- and another is
refused. That is the fixture below.

WHAT WAS LOST WHEN THEY COLLAPSED. The surviving question was the refusal, so
the dropped one was the time course -- the question that names the NUMBER this
engine substituted. A reader saw a model missing one declaration when it was
missing two, and the one they could not see was the one affecting every value.
"""
from __future__ import annotations

import copy
import pathlib

import pytest
import yaml

from arbiter_engine import api
from arbiter_engine.api import _build_topology, _gap_key

def _example_path() -> pathlib.Path:
    """The worked dynamics example, from whichever copy this tree has.

    Published beside the package as `examples/`, and kept one directory deeper
    in the tree this package is derived from, so one candidate pair serves both.
    The path parts are separate literals for the reason the sibling guide helper
    uses them that way: written as one string it is an internal path in prose,
    and the scrub rewrites it into the middle of a sentence.

    It RAISES rather than skipping. The ship leg runs these tests against the
    staged tree, and a fixture that quietly vanishes there would take its whole
    file green with it.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples" / "pump_tank_dynamics.yaml",
                      here.parents[2] / "docs" / "publication"
                      / "engine-example" / "pump_tank_dynamics.yaml"):
        if candidate.exists():
            return candidate
    raise AssertionError("no pump_tank_dynamics example found in this tree")


EXAMPLE = _example_path()


def _two_claim_model():
    """One rule, two transitions: one complete, one missing `source`.

    The complete transition is what makes the edge projectable, so the absent
    `temporal:` block raises the time-course question; the incomplete one is
    refused by name. Both land at the same `p1->t1` location.
    """
    model = yaml.safe_load(EXAMPLE.read_text())
    rule = model["domain"]["relationship_rules"][0]
    del rule["temporal"]
    rule["transition"] = [
        {"from": "speed_rpm", "to": "level_pct", "gain": 0.02,
         "source": "datasheet", "gain_sigma": 0.002},
        {"from": "speed_rpm", "to": "level_pct", "gain": 0.01},
    ]
    return model


def _session(model):
    session = api.EngineSession()
    session.load_model(model)
    session.add_entity("p1", "Pump", properties={"speed_rpm": 2000})
    session.add_entity("t1", "Tank", properties={"level_pct": 50})
    session.add_relationship("p1", "feeds", "t1")
    session.add_observations("p1", "speed_rpm", [2000.0] * 40)
    session.add_observations("t1", "level_pct", [50.0] * 40)
    return session


@pytest.fixture(scope="module")
def two_claim_gaps():
    topology = _build_topology(_session(_two_claim_model()))
    return [g for g in topology.get_unresolved_gaps() if g.location == "p1->t1"]


class TestTheFixtureReallyHoldsTwoClaims:
    """Guard the fixture before trusting anything measured through it. A test
    whose premise quietly stops holding passes for the wrong reason."""

    def test_the_edge_carries_two_distinct_gaps(self, two_claim_gaps):
        assert len(two_claim_gaps) == 2

    def test_both_are_missing_declaration_at_one_location(self, two_claim_gaps):
        assert {g.gap_type.value for g in two_claim_gaps} == {"missing_declaration"}
        assert {g.location for g in two_claim_gaps} == {"p1->t1"}

    def test_they_ask_different_questions(self, two_claim_gaps):
        assert len({g.question for g in two_claim_gaps}) == 2


class TestTheKeyDistinguishesThem:
    def test_the_old_key_collapsed_them(self, two_claim_gaps):
        """The defect, stated as an assertion. Keyed on type and place alone
        these two are one, and one of them was silently discarded."""
        old = {(g.gap_type.value, g.location) for g in two_claim_gaps}
        assert len(old) == 1

    def test_the_key_in_use_keeps_them_apart(self, two_claim_gaps):
        assert len({_gap_key(g) for g in two_claim_gaps}) == 2

    def test_the_same_claim_twice_still_collapses(self, two_claim_gaps):
        """The dedup is still a dedup: identical claims about one place render
        one sentence and must stay one question."""
        doubled = two_claim_gaps + [copy.deepcopy(two_claim_gaps[0])]
        assert len({_gap_key(g) for g in doubled}) == 2


class TestGapsReportsBoth:
    def test_both_questions_reach_the_caller(self):
        envelope = api.gaps(_session(_two_claim_model())).to_dict()
        asked = [q["question"] for q in envelope["questions"]]
        assert len(asked) == 2, asked

    def test_the_time_course_question_is_among_them(self):
        """It is the one the old key dropped, and the one naming the number."""
        envelope = api.gaps(_session(_two_claim_model())).to_dict()
        joined = " ".join(q["question"] for q in envelope["questions"])
        assert "time_constant_s" in joined
        assert "propagation_delay_s" in joined

    def test_the_refusal_question_is_still_there_too(self):
        envelope = api.gaps(_session(_two_claim_model())).to_dict()
        joined = " ".join(q["question"] for q in envelope["questions"])
        assert "`source`" in joined


class TestTheShippedModelIsUnaffected:
    def test_a_fully_declared_model_asks_nothing(self):
        envelope = api.gaps(_session(yaml.safe_load(EXAMPLE.read_text()))).to_dict()
        assert envelope["questions"] == []
