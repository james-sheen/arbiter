"""A tie in the root-cause cover goes to the lower id.

`TopologyTraverser.find_root_causes` and `RootCauseIdentifier` share one
greedy set cover, and it kept the first of two candidates tied in coverage and
score, in the order the candidates were collected -- from sets, whose order follows
the process's string hashing. Measured on engine 0.2.34 as installed, a four-node
chain with every node over its bound: under eight hash seeds, six named `N0` and
`N3` and two named `N1` and `N0`, through both callers.

The cover now takes the lower id on such a tie. And both callers average a
footprint with an exact sum: floats added in order follow that order, and the
engine's own 0.3 powers average to two different floats by order alone -- as
Python's `sum` adds them before 3.12 -- so two equal footprints could tie or not by
the order their walks found them.
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys

import pytest

from arbiter_engine import api
from arbiter_engine.interfaces import RelationshipGraph
from arbiter_engine.propagation import root_cause
from arbiter_engine.propagation.root_cause import (
    RootCauseIdentifier, footprint_mean)
from arbiter_engine.propagation.weight_learner import LearnedWeight
from arbiter_engine.twin.builder import TopologyBuilder
from arbiter_engine.twin.traverser import TopologyTraverser

#: The package under test, read off a module, so the child process imports the
#: same tree under either name.
PACKAGE = api.__name__.rsplit(".", 1)[0]

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

CHILD = """
import json
from {pkg} import api
from {pkg}.propagation.root_cause import RootCauseIdentifier
from {pkg}.twin.builder import TopologyBuilder
from {pkg}.twin.traverser import TopologyTraverser
session = api.EngineSession()
session.load_model({model!r})
nodes = ["N0", "N1", "N2", "N3"]
for node in nodes:
    session.add_entity(node, "Node", {{"x": 99.0}})
for source, target in zip(nodes, nodes[1:]):
    session.add_relationship(source, "feeds", target)
topology = TopologyBuilder().build_from_relationship_graph(
    dict(session.entities), session.graph, session.model.indicators,
    session.model.relationship_rules)
print(json.dumps([
    [c.entity_id for c in TopologyTraverser(topology).find_root_causes(set(nodes)).root_causes],
    [c.entity_id for c in RootCauseIdentifier().identify(set(nodes), session.graph).root_causes]]))
"""


def _chain():
    session = api.EngineSession()
    session.load_model(MODEL)
    nodes = ["N0", "N1", "N2", "N3"]
    for node in nodes:
        session.add_entity(node, "Node", {"x": 99.0})
    for source, target in zip(nodes, nodes[1:]):
        session.add_relationship(source, "feeds", target)
    return session, nodes


class TestOneInputOneAnswer:

    def test_the_chain_names_the_lower_of_two_tied_roots(self):
        """`N0` and `N1` each cover three nodes at the same probability; `N0`
        is taken, and `N3`, which only it leaves, after it."""
        session, nodes = _chain()
        topology = TopologyBuilder().build_from_relationship_graph(
            dict(session.entities), session.graph, session.model.indicators,
            session.model.relationship_rules)
        kernel = TopologyTraverser(topology).find_root_causes(set(nodes))
        identifier = RootCauseIdentifier().identify(set(nodes), session.graph)
        assert [c.entity_id for c in kernel.root_causes] == ["N0", "N3"]
        assert [c.entity_id for c in identifier.root_causes] == ["N0", "N3"]

    @pytest.mark.parametrize("seed", ["0", "1", "5", "7"])
    def test_every_hash_seed_gets_the_same_roots(self, seed):
        done = subprocess.run(
            [sys.executable, "-c", CHILD.format(pkg=PACKAGE, model=MODEL)],
            capture_output=True, text=True, timeout=120,
            env=dict(os.environ, PYTHONHASHSEED=seed,
                     PYTHONPATH=os.pathsep.join(p for p in sys.path if p),
                     PYTHONDONTWRITEBYTECODE="1"))
        assert done.returncode == 0, done.stderr[-2000:]
        assert json.loads(done.stdout.strip().splitlines()[-1]) == [["N0", "N3"], ["N0", "N3"]]


def _picked(candidates, scores):
    cover = root_cause.greedy_set_cover(
        candidates=candidates, universe=set().union(*candidates.values()), scores=scores)
    return [selected[0] for selected in cover.selected]


class TestTheCover:

    @pytest.mark.parametrize("order", [("b", "a"), ("a", "b")])
    def test_a_tie_in_coverage_and_score_goes_to_the_lower_id(self, order):
        footprints = {"a": {1, 2}, "b": {2, 3}}
        candidates = {cid: footprints[cid] for cid in order}
        assert _picked(candidates, {"a": 0.5, "b": 0.5}) == ["a", "b"]

    def test_a_higher_score_still_wins_over_a_lower_id(self):
        assert _picked({"a": {1, 2}, "b": {2, 3}}, {"a": 0.4, "b": 0.5}) == ["b", "a"]

    def test_more_coverage_still_wins_over_a_lower_id(self):
        assert _picked({"a": {1}, "b": {1, 2}}, {"a": 0.9, "b": 0.1}) == ["b"]


def _added_in_order(values):
    """Floats added left to right, as `sum` adds them before Python 3.12; from
    3.12 `sum` compensates, so it is not the control on every interpreter."""
    total = 0.0
    for value in values:
        total += value
    return total


class TestTheMean:

    def test_the_mean_is_the_same_in_every_order(self):
        powers = [1.0, 0.3, 0.09, 0.027, 0.0081]
        in_order = {_added_in_order(p) / len(p) for p in itertools.permutations(powers)}
        assert len(in_order) == 2   # what adding in order does with these values
        assert {footprint_mean(list(p)) for p in itertools.permutations(powers)} == {0.28502}

    def test_an_empty_footprint_means_nothing(self):
        assert footprint_mean([]) == 0.0


#: Two candidates whose footprints are the same three probabilities, found in
#: opposite orders: `B` walks 0.1, 0.2, 0.3 and `A` walks 0.3, 0.2, 0.1. Added
#: in that order -- `sum` before Python 3.12 -- they average to
#: 0.20000000000000004 and 0.19999999999999998, so `B` won on its walk order;
#: exactly, they tie and the lower id is taken.
WEIGHTED = [("A", "a3", 0.3), ("A", "a2", 0.2), ("A", "a1", 0.1),
            ("B", "b1", 0.1), ("B", "b2", 0.2), ("B", "b3", 0.3)]
ANOMALIES = {"a1", "a2", "a3", "b1", "b2", "b3"}


class TestEqualFootprintsTieWhateverTheirWalkOrder:

    def test_through_the_identifiers_learned_weights(self):
        graph = RelationshipGraph()
        weights = {}
        for source, target, probability in WEIGHTED:
            graph.add_relationship(source, "feeds", target)
            weights[(source, target)] = LearnedWeight(
                total_source_occurrences=5, confidence=0.5, probability=probability)
        answer = RootCauseIdentifier().identify(set(ANOMALIES), graph, learned_weights=weights)
        assert [c.entity_id for c in answer.root_causes] == ["A", "B"]

    def test_through_the_kernels_edge_probabilities(self):
        session = api.EngineSession()
        session.load_model(MODEL)
        for node in ["A", "B", *sorted(ANOMALIES)]:
            session.add_entity(node, "Node", {"x": 99.0 if node in ANOMALIES else 10.0})
        for source, target, _ in WEIGHTED:
            session.add_relationship(source, "feeds", target)
        topology = TopologyBuilder().build_from_relationship_graph(
            dict(session.entities), session.graph, session.model.indicators,
            session.model.relationship_rules)
        probability = {(s, t): p for s, t, p in WEIGHTED}
        for edges in topology.edges.values():
            for edge in edges:
                edge.propagation_probability = probability[(edge.source_id, edge.target_id)]
        answer = TopologyTraverser(topology).find_root_causes(set(ANOMALIES))
        assert [c.entity_id for c in answer.root_causes] == ["A", "B"]
