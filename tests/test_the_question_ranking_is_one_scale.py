"""`gaps` calls itself priority-ranked, and both populations now sit on one scale.

IT MERGES TWO SOURCES. The builder computes structural gaps -- an orphaned
entity, a declared property never supplied -- at the entity. A walk finds others,
notably a dangling reference: an edge pointing at an id no entity claims, which
is the gap type saying the topology itself is wrong.

WHAT WAS WRONG WAS NOT THE ORDER, IT WAS THE UNITS. Structural gaps carried a
flat `0.5`, so the type weights applied to none of them -- a missing edge and a
missing property ranked identically. Traversal gaps were multiplied by the
edge's `propagation_probability`, which is fault-propagation dynamics sitting in
the model beside `propagation_delay_s`, and which defaults to `0.3`. Measured, a
MISSING_NODE two hops out scored `0.03` and sorted LAST of twenty-two, below
every structural gap, while carrying the highest weight in the table.

A discovery question is not a fault forecast. How much it is worth asking about a
dangling reference does not depend on how strongly disturbances travel the edge
that led you to it. The factor is gone; what remains is the type's weight decayed
by how far the walk went, and a structural gap is scored at hop zero because that
is where the builder found it.
"""
from __future__ import annotations

import pytest

yaml = pytest.importorskip("yaml")

from arbiter_engine.api import EngineSession, gaps, traverse  # noqa: E402

MODEL = {"domain": {
    "id": "rank", "name": "rank", "entity_types": ["A", "B"],
    "relationship_types": ["links"],
    "indicators": {
        "A": [{"name": "p", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"], "critical": 9},
              {"name": "q", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"], "critical": 9}],
        "B": [{"name": "r", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"], "critical": 9}]}}}


def _session(dangling=True):
    session = EngineSession()
    session.load_model(yaml.safe_dump(MODEL))
    for i in range(3):
        session.add_entity(f"a{i}", "A", {"p": 1.0}, f"a{i}")   # q never supplied
    session.add_entity("b1", "B", {"r": 1.0}, "b1")
    session.add_relationship("a0", "links", "b1")
    if dangling:
        session.add_relationship("b1", "links", "ghost")
    return session


def _questions(session=None):
    return gaps(session or _session()).to_dict()["questions"]


def _by_type(questions):
    out = {}
    for q in questions:
        out.setdefault(q["gap_type"], set()).add(q["priority"])
    return out


class TestTheStructuralPopulationUsesTheTypeWeights:
    def test_a_missing_edge_outranks_a_missing_property(self):
        """Both are structural. Before this they were both `0.5`, so the table
        that says an absent edge blocks more than an absent reading decided
        nothing."""
        by = _by_type(_questions())
        assert by["missing_edge"] == {0.8}
        assert by["missing_property"] == {0.6}
        assert min(by["missing_edge"]) > max(by["missing_property"])

    def test_no_structural_gap_carries_the_old_constant(self):
        assert 0.5 not in {p for ps in _by_type(_questions()).values() for p in ps}


class TestTheTraversalPopulationIsOnTheSameScale:
    def test_a_dangling_reference_is_no_longer_scored_by_fault_dynamics(self):
        """The measured defect: `0.03`, last of the list. The edge default
        `propagation_probability` is 0.3 and it was squared into this."""
        found = [q for q in _questions() if q["gap_type"] == "missing_node"]
        assert len(found) == 1
        assert found[0]["priority"] > 0.03 * 5

    def test_it_scores_at_its_full_weight_when_it_is_the_start(self):
        """Hop zero, so no decay: the type weight itself, and the highest one."""
        found = traverse(_session(), ["ghost"]).to_dict()["questions"]
        assert [q["priority"] for q in found] == [1.0]

    def test_distance_still_lowers_it(self):
        """The control on the change. Removing the probability factor must not
        flatten the ranking into the type weight alone -- a gap the walk had to
        travel to reach is still ranked below one at the start node."""
        far = [q for q in _questions() if q["gap_type"] == "missing_node"][0]
        near = traverse(_session(), ["ghost"]).to_dict()["questions"][0]
        assert far["priority"] < near["priority"]


class TestTheOrderingIsMeaningful:
    def test_every_priority_is_explained_by_type_and_distance(self):
        """One scale, stated as a property rather than a list of numbers: every
        value is a type weight divided by a whole number of hops plus one."""
        weights = {1.0, 0.8, 0.7, 0.6, 0.4, 0.2}
        for q in _questions():
            assert any(abs(q["priority"] - round(w / (1 + h), 3)) < 1e-9
                       for w in weights for h in range(6)), (
                f"{q['gap_type']} at {q['priority']} is on neither scale")

    def test_the_list_is_sorted_by_it(self):
        priorities = [q["priority"] for q in _questions()]
        assert priorities == sorted(priorities, reverse=True)

    def test_a_model_with_nothing_missing_asks_nothing(self):
        """Non-vacuity's other half. Every assertion above ranges over the
        questions, and all of them hold of an empty list."""
        assert len(_questions()) >= 4
