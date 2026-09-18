"""A `temporal:` block an author wrote reaches the topology `api` builds.

There are two builders. `build_from_yaml` reads `relationship_rules` and
enriches every edge from them. `build_from_relationship_graph` does not -- and
it is the one the published `api` calls. So every declared propagation delay,
time constant, coupling strength and response model was dropped on the only
path a released caller can reach.

MEASURED AT 0.1.18, on a rule declaring 120s / 600s / 0.9: the edge carried
60.0 / 60.0 / 1.0. Three silent defaults, and none of them named in any
envelope. An author could write a temporal block, run `traverse` through
`api`, and get the identical answer to an author who wrote nothing at all.

The edge also reported `EdgeSource.AUTO_DISCOVERY` -- the engine telling a
reader that nobody declared an edge the author had declared. That field is the
one a consumer would use to tell a modelled edge from an inferred one, so it
was wrong in the direction that matters.

THIS IS THE THIRD TIME THIS EXACT SHAPE HAS BEEN FIXED ON THIS FILE. An internal ruling
found gap discovery running only on the YAML builder, so `gaps` returned an
empty questions leg for every model. An internal ruling found axiom states seeded only
there, so the findings leg could not fire from a declaration. Both docstrings
describe a leg *structurally unable to perform rather than merely
under-performing*, and both fixed one parameter without asking what else the
builder was not being given.
"""
from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.twin.topology import EdgeSource, ResponseModel

DECLARED = """
domain:
  id: declared-edge
  name: A fully declared edge
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9000}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 95}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal:
        propagation_delay_s: 120
        time_constant_s: 600
        coupling_strength: 0.9
        response_model: exponential
      transition: {from: speed_rpm, to: level_pct, gain: 0.02, source: datasheet}
"""

UNDECLARED = """
domain:
  id: undeclared-edge
  name: No relationship rules at all
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9000}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 95}
"""


def _edge(tmp_path, text, name):
    path = tmp_path / f"{name}.yaml"
    path.write_text(text)
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("tank1", "Tank", {"level_pct": 40.0})
    session.add_relationship("pump1", "feeds", "tank1")
    topology = api._build_topology(session)
    edges = [e for lst in topology.edges.values() for e in lst]
    assert len(edges) == 1
    return edges[0]


class TestTheDeclaredNumbersSurvive:

    @pytest.mark.parametrize("attribute,declared", [
        ("propagation_delay_s", 120.0),
        ("time_constant_s", 600.0),
        ("coupling_strength", 0.9),
    ])
    def test_a_declared_temporal_field_is_the_one_on_the_edge(
            self, tmp_path, attribute, declared):
        edge = _edge(tmp_path, DECLARED, "declared")
        assert getattr(edge, attribute) == declared, (
            f"{attribute} was declared as {declared} and the edge carries "
            f"{getattr(edge, attribute)} -- a silent default on the only "
            f"builder the published api uses")

    def test_the_declared_response_model_is_the_one_on_the_edge(self, tmp_path):
        assert _edge(tmp_path, DECLARED, "declared").response_model is (
            ResponseModel.EXPONENTIAL)

    def test_a_declared_edge_does_not_claim_to_be_auto_discovered(
            self, tmp_path):
        edge = _edge(tmp_path, DECLARED, "declared")
        assert edge.source is EdgeSource.YAML, (
            "`source` is how a consumer tells a modelled edge from an "
            "inferred one, and it said `auto` for a declared edge")

    def test_the_transition_reaches_the_edge_too(self, tmp_path):
        transitions = _edge(tmp_path, DECLARED, "declared").transitions
        assert len(transitions) == 1
        assert transitions[0].gain == 0.02
        assert transitions[0].source == "datasheet"


class TestAnUndeclaredEdgeIsUnchanged:
    """The fix widens what a DECLARATION can reach. It must not change what
    an undeclared edge does, or every existing caller's traversal moves."""

    def test_an_edge_with_no_rule_keeps_the_old_defaults(self, tmp_path):
        edge = _edge(tmp_path, UNDECLARED, "undeclared")
        assert edge.propagation_delay_s == 60.0
        assert edge.time_constant_s == 60.0
        assert edge.coupling_strength == 1.0

    def test_an_edge_with_no_rule_is_still_auto(self, tmp_path):
        assert _edge(tmp_path, UNDECLARED, "undeclared").source is (
            EdgeSource.AUTO_DISCOVERY)

    def test_an_edge_with_no_rule_carries_no_transition(self, tmp_path):
        assert _edge(tmp_path, UNDECLARED, "undeclared").transitions == []


class TestTheTwoBuildersAgreeOnADeclaredEdge:
    """The defect was disagreement between two builders reading one model,
    so the pin is that they now answer the same."""

    def test_both_builders_read_the_same_temporal_block(self, tmp_path):
        import yaml
        from arbiter_engine.twin.builder import TopologyBuilder

        path = tmp_path / "declared.yaml"
        path.write_text(DECLARED)
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
        session.add_entity("tank1", "Tank", {"level_pct": 40.0})
        session.add_relationship("pump1", "feeds", "tank1")

        raw = yaml.safe_load(DECLARED)
        from_yaml = TopologyBuilder().build_from_yaml(
            raw, dict(session.entities), session.graph)
        from_graph = api._build_topology(session)

        def only(topology):
            return [e for lst in topology.edges.values() for e in lst][0]

        for attribute in ("propagation_delay_s", "time_constant_s",
                          "coupling_strength"):
            assert getattr(only(from_yaml), attribute) == getattr(
                only(from_graph), attribute), (
                f"the two builders disagree on {attribute} for one model")
        assert len(only(from_yaml).transitions) == len(
            only(from_graph).transitions) == 1
