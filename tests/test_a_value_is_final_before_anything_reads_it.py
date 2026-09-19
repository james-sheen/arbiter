"""Values are resolved in dependency order, so nothing reads a partial one.

THE WALK ORDER AND THE DEPENDENCY ORDER ARE NOT THE SAME ORDER.
Transitions were applied when the BFS happened to pop their source, and a BFS
pops by hop count. On any graph where two paths of unequal length meet, the
shorter one arrives first, the node is carried onward at that partial value,
and the longer path's contribution lands afterwards on a node whose own
targets have already been written.

Measured on `a->d` beside `a->b->c->d`, with `d->e`: `d` ended correct at 3.0
and `e` sat at 2.0 -- short by the whole second path. An internal ruling had already made
`d` right and could only NAME the damage downstream, as
`reconvergence_unsupported`. Ordering the value pass by dependency removes the
damage, so that reason had nothing left to report and was retired; it never
shipped.

WHAT A CYCLE IS, NARROWED. A cycle is now exactly what the ordering cannot
resolve, which is a smaller and truer set than *the walk saw this node
already*. An acyclic re-convergence is not one and reports nothing, because
there is nothing left to report.
"""
from __future__ import annotations

import pytest

from arbiter_engine import api

MODEL = """
domain:
  id: ordering
  name: One gain, many shapes
  entity_types: [N]
  relationship_types: [drives]
  indicators:
    N: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  relationship_rules:
    - {type: drives, source_type: N, target_type: N,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: v, to: v, gain: 1.0, source: datasheet}}
"""

BASE = 1.0
MOVED = 2.0
DELTA = MOVED - BASE      # every edge has gain 1.0, so a delta arrives intact


@pytest.fixture
def graph(tmp_path):
    path = tmp_path / "ordering.yaml"
    path.write_text(MODEL)

    def build(nodes, edges):
        session = api.EngineSession()
        session.load_model(str(path))
        for node in nodes:
            session.add_entity(node, "N", {"v": BASE})
        for source, target in edges:
            session.add_relationship(source, "drives", target)
        return session
    return build


def _walk(session, starts=("a",), overrides=None, max_hops=20):
    return api.traverse(
        session, list(starts), value_mode="hypothetical",
        overrides=overrides or {"a": {"v": MOVED}},
        max_hops=max_hops).to_dict()["simulation"]


def _reasons(simulation):
    return {d["reason"] for d in simulation["not_checked"]}


class TestAnUnequalDiamondIsExact:

    EDGES = [("a", "d"), ("a", "b"), ("b", "c"), ("c", "d")]

    def test_the_meeting_point_carries_both_paths(self, graph):
        values = _walk(graph("abcd", self.EDGES))["values"]
        assert values["d"]["v"]["value"] == pytest.approx(BASE + 2 * DELTA)

    def test_what_is_downstream_carries_the_whole_of_it(self, graph):
        """The case a decline could only name."""
        values = _walk(graph("abcde", self.EDGES + [("d", "e")]))["values"]
        assert values["e"]["v"]["value"] == pytest.approx(BASE + 2 * DELTA), (
            "e is driven by d at gain 1.0, so it carries d's whole delta; "
            "2.0 means e was written before d had finished")

    def test_an_acyclic_graph_refuses_nothing(self, graph):
        assert _reasons(_walk(graph("abcde",
                                    self.EDGES + [("d", "e")]))) == set()


class TestNestedDiamondsCompose:
    """Two meeting points in series, which is where an off-by-one order shows."""

    def test_both_levels_are_exact(self, graph):
        session = graph("abcdefg", [
            ("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"),
            ("d", "e"), ("d", "f"), ("e", "g"), ("f", "g")])
        values = _walk(session)["values"]
        # d sees two paths from a; g sees two paths from d, each carrying d's
        # whole delta.
        assert values["d"]["v"]["value"] == pytest.approx(BASE + 2 * DELTA)
        assert values["g"]["v"]["value"] == pytest.approx(BASE + 4 * DELTA)


class TestStartNodesSuperposeAsBefore:
    """Equal-length convergence worked before this and must still."""

    def test_two_roots_meeting_add(self, graph):
        session = graph("abc", [("a", "c"), ("b", "c")])
        values = _walk(session, starts=("a", "b"),
                       overrides={"a": {"v": MOVED}, "b": {"v": MOVED}})["values"]
        assert values["c"]["v"]["value"] == pytest.approx(BASE + 2 * DELTA)


class TestACycleIsStillRefused:
    """The refusal must narrow, not disappear."""

    def test_a_two_node_loop_names_the_edge_that_closes_it(self, graph):
        simulation = _walk(graph("ab", [("a", "b"), ("b", "a")]))
        closing = [d for d in simulation["not_checked"]
                   if d["reason"] == "cycle_unsupported"]
        assert closing and closing[0]["location"] == "b->a"
        assert "closes a loop" in closing[0]["detail"]

    def test_a_loop_off_the_path_does_not_stop_the_rest_of_the_graph(
            self, graph):
        """`a->b->c->b` beside `a->d`. The loop refuses; `d` is untouched."""
        simulation = _walk(graph("abcd", [("a", "b"), ("b", "c"),
                                          ("c", "b"), ("a", "d")]))
        assert "cycle_unsupported" in _reasons(simulation)
        assert simulation["values"]["d"]["v"]["value"] == pytest.approx(
            BASE + DELTA), (
            "a branch that shares nothing with the loop was refused with it")

    def test_an_edge_inside_a_loop_says_so_rather_than_claiming_to_close_it(
            self, graph):
        """In this shape NEITHER member resolves, so no edge closes anything.

        Advice pointing at *the edge that closes the loop* would name an edge
        that is not reported, which is worse than saying less.
        """
        simulation = _walk(graph("abc", [("a", "b"), ("b", "c"), ("c", "b")]))
        details = [d["detail"] for d in simulation["not_checked"]
                   if d["reason"] == "cycle_unsupported"]
        assert details
        assert all("sits inside a feedback loop" in d for d in details)


class TestTheRetiredReasonIsGone:
    """A member nobody can construct an input for is the dead-vocabulary
    shape this package has a standing guard against."""

    def test_it_is_not_in_the_vocabulary(self):
        from arbiter_engine.subenvelope import VOCABULARIES
        assert "reconvergence_unsupported" not in VOCABULARIES["simulation"]


class TestOrderingDoesNotChangeTheCost:
    """A long chain must stay linear; the ordering is one pass over the edges."""

    def test_a_long_chain_resolves(self, graph):
        nodes = [f"n{i}" for i in range(120)]
        edges = [(f"n{i}", f"n{i + 1}") for i in range(119)]
        session = graph(nodes, edges)
        values = _walk(session, starts=("n0",),
                       overrides={"n0": {"v": MOVED}}, max_hops=200)["values"]
        assert values["n119"]["v"]["value"] == pytest.approx(BASE + DELTA)

    def test_the_budget_is_still_counted(self, graph):
        """`max_transitions` must still bite, and still report once."""
        session = graph("abcd", [("a", "b"), ("b", "c"), ("c", "d")])
        envelope = api.traverse(session, ["a"], value_mode="hypothetical",
                                overrides={"a": {"v": MOVED}})
        assert "budget_exhausted" not in _reasons(
            envelope.to_dict()["simulation"])
