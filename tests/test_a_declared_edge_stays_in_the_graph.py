"""A declared edge stays in the graph, however many reach the same entity.

The graph bounds each entity's edges, so that relationship discovery cannot grow it without end
(`max_edges_per_entity`, 200). It bounded every edge, declared ones too: past 200 the oldest was
evicted from one direction's index without a word, and the edge stayed in the other's. A hub with
more than 200 declared members -- an agency's facilities, a namespace's pods, a site's racks -- lost
some of them from its incoming index, and which ones depended on the order they were fed in: the
readers that walk outgoing edges still found a cause the readers of incoming edges could not. Now
only edges marked `discovered` count against the bound, and an evicted one leaves both indices.
"""
from __future__ import annotations

from arbiter_engine import api
from arbiter_engine.interfaces import RelationshipGraph

HUB = """
domain:
  id: hub
  name: a hub with many members and one feeder
  entity_types: [Hub, Spoke, Feeder]
  relationship_types: [part_of, feeds]
  causal:
    evidence_severity: [warning, critical]
  relationship_rules:
    - {type: part_of, source_type: Spoke, target_type: Hub, cause: target}
    - {type: feeds, source_type: Feeder, target_type: Hub, edge_direction: causal}
  indicators:
    Hub:
      - {name: load, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 10, critical: 20}
    Spoke:
      - {name: load, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 10, critical: 20}
    Feeder:
      - {name: load, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 10, critical: 20}
"""
SPOKES = 250


def _hub_session():
    """The feeder's edge first, then more members than the bound: the order a caller may well use."""
    session = api.EngineSession()
    session.load_model(HUB)
    session.add_entity("hub", "Hub", {"load": 15.0})
    session.add_entity("feeder", "Feeder", {"load": 1.0})
    session.add_relationship("feeder", "feeds", "hub")
    for i in range(SPOKES):
        session.add_entity(f"s{i}", "Spoke", {"load": 1.0})
        session.add_relationship(f"s{i}", "part_of", "hub")
    return session


class TestADeclaredHubKeepsEveryEdge:

    def test_every_member_and_the_feeder_reach_the_hub(self):
        incoming = _hub_session().graph.reverse_edges["hub"]
        assert len(incoming) == SPOKES + 1
        assert ("feeds", "feeder") in incoming

    def test_the_gap_reader_sees_the_cause_the_walk_sees(self):
        """The hub's one declared cause is fed and clean: its walk is unexplained, and nothing says
        no cause is connected. With the feeder's edge evicted it said `no_cause_connected`."""
        session = _hub_session()
        api.check(session)
        rows = (api.gaps(session).to_dict().get("residuals") or {}).get("hypotheses") or []
        assert [r for r in rows if r.get("kind") == "no_cause_connected"] == []
        assert [r.get("at") for r in rows if r.get("kind") == "unexplained_finding"] == ["hub"]


class TestDiscoveredEdgesAreStillBounded:

    def _graph(self, cap=3):
        graph = RelationshipGraph()
        graph.max_edges_per_entity = cap
        return graph

    def test_past_the_bound_the_oldest_leaves_both_indices(self):
        graph = self._graph()
        for i in range(4):
            graph.add_relationship("S", "correlates_with", f"T{i}", discovered=True)
        assert ("correlates_with", "T0") not in graph.edges["S"]
        assert ("correlates_with", "S") not in graph.reverse_edges["T0"]
        assert graph.get_edge_metadata("S", "correlates_with", "T0") is None
        assert graph.evicted_discovered_edges == 1

    def test_declared_edges_neither_count_nor_leave(self):
        graph = self._graph()
        for i in range(5):
            graph.add_relationship("S", "member_of", f"D{i}")
        for i in range(4):
            graph.add_relationship("S", "correlates_with", f"T{i}", discovered=True)
        assert all(("member_of", f"D{i}") in graph.edges["S"] for i in range(5))
        assert [t for r, t in graph.edges["S"] if r == "correlates_with"] == ["T1", "T2", "T3"]

    def test_an_edge_declared_once_stays_declared(self):
        graph = self._graph(cap=1)
        graph.add_relationship("S", "member_of", "D")
        graph.add_relationship("S", "member_of", "D", discovered=True)     # reported again by discovery
        graph.add_relationship("S", "correlates_with", "T", discovered=True)
        graph.add_relationship("S", "correlates_with", "U", discovered=True)
        assert ("member_of", "D") in graph.edges["S"]
        assert graph.get_edge_metadata("S", "member_of", "D")["discovered"] is False
