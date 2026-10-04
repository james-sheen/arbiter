"""A walk the engine bounded says so -- ruling 6, guarded.

`TopologyTraverser` is one of the names the README promises, and its own
walks set their bounds themselves: `find_root_causes`, `predict_impact` and
`simulate_what_if` walk four hops with a probability floor of 0.05, and every edge
the builder makes carries 0.3, which no model key sets. So on undeclared edges
they stop at the second hop. Measured on what users installed (engine 0.2.32), on
a chain with every node over its bound: `find_root_causes` named two roots on a
four-node chain whose head explains all four; `predict_impact` reported 2
affected where 4 lie within its hops; `simulate_what_if` reached three nodes of
five. `gaps` asked from a start node walks four hops of its own, and asked nothing
about a missing node five hops out. No answer said it had been cut, and none of
their types had anywhere to say it.

The ruling: guard. Each walk records the edges it did not follow, and each method
whose own number cut it stamps `walk_floor_not_declared` or
`walk_depth_not_declared`. No answer changes.

`predict_all` walked two hops from every node, and every node is a start
of its own, so the walk only re-read findings already read: 11 problems for 6
findings on a six-node chain. It evaluates each node once.
"""

from __future__ import annotations

import json

from arbiter_engine import api
from arbiter_engine.assumptions import (
    ASSUMPTION_STAMPS, DECLARED_COUPLING_NOT_PROBABILITY_PRUNED,
    WALK_DEPTH_NOT_DECLARED, WALK_FLOOR_NOT_DECLARED,
)
from arbiter_engine.interfaces import Problem
from arbiter_engine.twin.builder import TopologyBuilder
from arbiter_engine.twin.topology import (
    TraversalDirection, TraversalRequest,
)
from arbiter_engine.twin.traverser import TopologyTraverser
from arbiter_engine.types import Severity

MODEL = """
domain:
  id: chain
  name: Chain
  entity_types: [Node]
  relationship_types: [feeds]
  indicators:
    Node:
      - {name: x, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 50, critical: 80}
"""

COUPLED = MODEL + """
  relationship_rules:
    - type: feeds
      source_type: Node
      target_type: Node
      temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step}
      transition: {from: x, to: x, gain: 1.0, source: datasheet}
"""

WALK_STAMPS = {WALK_FLOOR_NOT_DECLARED, WALK_DEPTH_NOT_DECLARED}


def _chain(n, *, value=99.0, ghost_after=None, model=MODEL, extra=()):
    session = api.EngineSession()
    session.load_model(model)
    nodes = [f"N{i}" for i in range(n)]
    for node in nodes:
        session.add_entity(node, "Node", {"x": value})
    for source, target in list(zip(nodes, nodes[1:])) + list(extra):
        session.add_relationship(source, "feeds", target)
    if ghost_after:
        session.add_relationship(ghost_after, "feeds", "GHOST")
    return session, nodes


def _traverser(session):
    model = session.model
    topology = TopologyBuilder().build_from_relationship_graph(
        dict(session.entities), session.graph,
        getattr(model, "indicators", None), getattr(model, "relationship_rules", None))
    return TopologyTraverser(topology)


def _problem(session, entity_id):
    return Problem.from_entity(entity=session.entities[entity_id],
                               problem_type="threshold_exceeded:x",
                               severity=Severity.CRITICAL, reason="a test")


def _named(record, kind):
    return [(e["start"], e["from"], e["to"], e["hop"])
            for e in (record or {}).get(kind, {}).get("first", [])]


class TestFindRootCauses:

    def test_the_cover_its_floor_cut_says_so(self):
        """Two roots on a chain whose head explains all four. Which two was a
        tie the cover broke by set order -- `N0` and `N3`, or `N1` and `N0` --
        until the lower id took it."""
        session, nodes = _chain(4)
        answer = _traverser(session).find_root_causes(set(nodes))
        assert [c.entity_id for c in answer.root_causes] == ["N0", "N3"]
        assert answer.assumptions == [WALK_FLOOR_NOT_DECLARED]
        assert ("N0", "N2", "N3", 3) in _named(answer.not_followed, "below_floor")
        assert answer.not_followed["below_floor"]["bound"] == 0.05

    def test_a_cover_inside_its_bounds_says_nothing(self):
        session, nodes = _chain(3)
        answer = _traverser(session).find_root_causes(set(nodes))
        assert [c.entity_id for c in answer.root_causes] == ["N0"]
        assert (answer.assumptions, answer.not_followed) == ([], {})


class TestPredictImpact:

    def test_the_forecast_its_floor_cut_says_so(self):
        session, _ = _chain(6)
        forecast = _traverser(session).predict_impact(_problem(session, "N0"))
        assert (forecast.total_affected, forecast.max_hop_distance) == (2, 2)
        assert forecast.assumptions == [WALK_FLOOR_NOT_DECLARED]
        [named] = forecast.not_followed["below_floor"]["first"]
        assert (named["from"], named["to"], named["hop"], named["probability"]) == (
            "N2", "N3", 3, 0.027)

    def test_a_forecast_inside_its_bounds_says_nothing(self):
        session, _ = _chain(3)
        forecast = _traverser(session).predict_impact(_problem(session, "N0"))
        assert forecast.total_affected == 2
        assert (forecast.assumptions, forecast.not_followed) == ([], {})


class TestSimulateWhatIf:

    def test_a_what_if_its_floor_cut_says_so(self):
        session, _ = _chain(6)
        walk = _traverser(session).simulate_what_if({"N0": {"x": 99.0}})
        assert walk.total_nodes_visited == 3
        assert WALK_FLOOR_NOT_DECLARED in walk.assumptions
        assert ("N0", "N2", "N3", 3) in _named(walk.not_followed, "below_floor")

    def test_a_declared_coupling_is_not_cut_and_not_stamped(self):
        """A declared coupling is never pruned on probability, so on a chain
        that ends within the four hops every node is reached and neither walk
        stamp appears."""
        session, _ = _chain(5, value=10.0, model=COUPLED)
        walk = _traverser(session).simulate_what_if({"N0": {"x": 99.0}})
        assert walk.total_nodes_visited == 5
        assert DECLARED_COUPLING_NOT_PROBABILITY_PRUNED in walk.assumptions
        assert not WALK_STAMPS & set(walk.assumptions)
        assert walk.not_followed == {}


class TestPredictAll:

    def test_each_finding_comes_back_once(self):
        session, nodes = _chain(6)
        found = _traverser(session).predict_all(horizon_s=600.0)
        assert sorted(p.entity_id for p in found) == nodes


class TestGapsFromAStartNode:

    def test_a_missing_node_past_the_four_hops_is_named_as_left(self):
        session, _ = _chain(6, value=10.0, ghost_after="N4")
        payload = api.gaps(session, start_node="N0").to_dict()
        assert not [q for q in payload["questions"] if "GHOST" in json.dumps(q)]
        assert payload["assumptions"] == [WALK_DEPTH_NOT_DECLARED]
        assert payload["walk"]["from"] == "N0" and payload["walk"]["max_hops"] == 4
        assert ("N0", "N4", "GHOST", 5) in _named(
            payload["walk"]["not_followed"], "past_max_hops")

    def test_a_walk_that_reached_everything_says_nothing(self):
        session, _ = _chain(5, value=10.0)
        payload = api.gaps(session, start_node="N0").to_dict()
        assert payload["assumptions"] == []
        assert payload["walk"]["not_followed"] == {}

    def test_with_no_start_node_there_is_no_single_walk(self):
        session, _ = _chain(6, value=10.0, ghost_after="N4")
        payload = api.gaps(session).to_dict()
        assert "walk" not in payload and "assumptions" not in payload
        assert [q for q in payload["questions"] if "GHOST" in json.dumps(q)]


class TestTheRecord:

    def test_a_cut_another_path_makes_up_for_costs_nothing(self):
        """`N4` is at the bound and its edge to `X` is not taken, but `N3`
        reaches `X` at the fourth hop: nothing was left."""
        session, _ = _chain(5, value=10.0)
        session.add_entity("X", "Node", {"x": 10.0})
        session.add_relationship("N3", "feeds", "X")
        session.add_relationship("N4", "feeds", "X")
        walk = _traverser(session).traverse(TraversalRequest(
            start_nodes=["N0"], direction=TraversalDirection.FORWARD,
            max_hops=4, min_probability=0.0))
        assert walk.not_followed == {}

    def test_a_bound_the_caller_set_is_recorded_and_not_stamped(self):
        session, _ = _chain(6)
        walk = _traverser(session).traverse(TraversalRequest(
            start_nodes=["N0"], direction=TraversalDirection.FORWARD,
            max_hops=1, min_probability=0.0))
        assert walk.not_followed["past_max_hops"]["edges"] == 1
        assert not WALK_STAMPS & set(walk.assumptions)

    def test_the_traverse_verb_stamps_nothing(self):
        """Its floor is 0.0 and its bound is its caller's."""
        session, _ = _chain(6)
        payload = api.traverse(session, ["N0"], max_hops=2).to_dict()
        text = json.dumps(payload)
        assert not [stamp for stamp in WALK_STAMPS if stamp in text]

    def test_both_stamps_are_in_the_published_vocabulary(self):
        assert WALK_STAMPS <= set(ASSUMPTION_STAMPS)
