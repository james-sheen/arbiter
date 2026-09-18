"""A declared transition makes a what-if report what the value BECOMES.

Before `traverse()` propagated *probability x delay x severity decay*
across edges and never touched a downstream property. A what-if on a pump told
you which tank was reachable, with what probability and after how long, and
told you the tank's level was exactly what it is now. `TwinEdge` already
carried `coupling_strength`, `propagation_delay_s`, `time_constant_s` and a
`response_fraction()` method; nothing in the traversal loop called any of them.

THE ARITHMETIC IS PINNED AGAINST A CLOSED FORM, not against a recorded output.
A test that asserts whatever the code returned today cannot fail when the code
is wrong tomorrow; these compute the expected number from `gain`, the declared
response model and the horizon, independently of the implementation.

ELAPSED TIME IS MEASURED FROM WHEN THE SOURCE MOVED. `response_fraction()`
subtracts the edge's own propagation delay internally, so passing it
`horizon - (cum_delay + edge_delay)` charges that delay twice. The error is
invisible at long horizons -- 0.9963 against 0.9970 on a one-hour walk -- and
total near the boundary: an edge with a 120s delay asked about a 200s horizon
returns 0.0000 instead of 0.1248, which reads as *nothing has happened yet*
for a response that is well under way. `test_the_edge_delay_is_charged_once`
is the pin.
"""
from __future__ import annotations

import math

import pytest

from arbiter_engine import api

CHAIN = """
domain:
  id: gain-chain
  name: Chain
  entity_types: [Pump, Header, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9000}
    Header:
      - {name: pressure_kpa, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 900}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 95}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Header
      temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step}
      transition: {from: speed_rpm, to: pressure_kpa, gain: 0.1, source: datasheet}
    - type: feeds
      source_type: Header
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step}
      transition: {from: pressure_kpa, to: level_pct, gain: 0.5, source: measured}
"""

LAGGED = """
domain:
  id: gain-lagged
  name: Lagged
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
        response_model: exponential
      transition: {from: speed_rpm, to: level_pct, gain: 0.02, source: datasheet}
"""

CONFLUENCE = """
domain:
  id: gain-confluence
  name: Confluence
  entity_types: [PumpA, PumpB, Tank]
  relationship_types: [feeds]
  indicators:
    PumpA:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9000}
    PumpB:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9000}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 95}
  relationship_rules:
    - type: feeds
      source_type: PumpA
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step}
      transition: {from: speed_rpm, to: level_pct, gain: 0.01, source: datasheet}
    - type: feeds
      source_type: PumpB
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02, source: datasheet}
"""


def _model(tmp_path, text: str, name: str) -> str:
    path = tmp_path / f"{name}.yaml"
    path.write_text(text)
    return str(path)


def _chain(tmp_path) -> api.EngineSession:
    session = api.EngineSession()
    session.load_model(_model(tmp_path, CHAIN, "chain"))
    session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("hdr", "Header", {"pressure_kpa": 100.0})
    session.add_entity("tank1", "Tank", {"level_pct": 40.0})
    session.add_relationship("pump1", "feeds", "hdr")
    session.add_relationship("hdr", "feeds", "tank1")
    return session


def _sim(envelope) -> dict:
    return envelope.to_dict()["simulation"]


class TestAGainMovesTheValue:

    def test_a_single_edge_moves_the_downstream_property(self, tmp_path):
        envelope = api.traverse(
            _chain(tmp_path), ["pump1"], value_mode="hypothetical",
            overrides={"pump1": {"speed_rpm": 2000.0}})
        values = _sim(envelope)["values"]
        # +1000 rpm x gain 0.1, step response, from 100 kPa
        assert values["hdr"]["pressure_kpa"]["value"] == pytest.approx(200.0)

    def test_the_move_carries_all_the_way_along_a_chain(self, tmp_path):
        envelope = api.traverse(
            _chain(tmp_path), ["pump1"], value_mode="hypothetical",
            overrides={"pump1": {"speed_rpm": 2000.0}})
        values = _sim(envelope)["values"]
        # header moved +100 kPa; tank sees +100 x 0.5 on top of 40
        assert values["tank1"]["level_pct"]["value"] == pytest.approx(90.0)

    def test_no_change_at_the_source_moves_nothing(self, tmp_path):
        """The delta is what propagates, not the value."""
        envelope = api.traverse(
            _chain(tmp_path), ["pump1"], value_mode="hypothetical",
            overrides={"pump1": {"speed_rpm": 1000.0}})
        assert _sim(envelope)["values"] == {}
        assert _sim(envelope)["checked"]["transitions_applied"] == 0

    def test_a_current_walk_projects_nothing_at_all(self, tmp_path):
        """CURRENT asks for no values, so it must not manufacture any."""
        payload = api.traverse(
            _chain(tmp_path), ["pump1"], value_mode="current").to_dict()
        assert "simulation" not in payload


class TestTheNumberCarriesItsDerivation:

    def test_the_value_names_where_its_gain_came_from(self, tmp_path):
        values = _sim(api.traverse(
            _chain(tmp_path), ["pump1"], value_mode="hypothetical",
            overrides={"pump1": {"speed_rpm": 2000.0}}))["values"]
        assert values["hdr"]["pressure_kpa"]["source"] == "datasheet"
        assert values["tank1"]["level_pct"]["source"] == "measured"

    def test_the_value_names_the_edge_it_came_through(self, tmp_path):
        values = _sim(api.traverse(
            _chain(tmp_path), ["pump1"], value_mode="hypothetical",
            overrides={"pump1": {"speed_rpm": 2000.0}}))["values"]
        assert values["tank1"]["level_pct"]["via"] == ["hdr->tank1"]

    def test_every_engine_made_assumption_is_stamped(self, tmp_path):
        stamped = _sim(api.traverse(
            _chain(tmp_path), ["pump1"], value_mode="hypothetical",
            overrides={"pump1": {"speed_rpm": 2000.0}}))["assumptions"]
        for assumption in ("linear_superposition", "first_order_response",
                           "exogenous_inputs_held"):
            assert assumption in stamped


class TestTheTimeCourseIsTheEdgesOwn:

    def test_the_edge_delay_is_charged_once(self, tmp_path):
        """The regression this file's docstring describes.

        delay=120, tau=600, exponential. At a 600-second horizon the response
        has had 480 seconds to develop, so the fraction is 1-exp(-480/600).
        Charging the delay twice would give 1-exp(-360/600), and at short
        horizons it gives zero.
        """
        session = api.EngineSession()
        session.load_model(_model(tmp_path, LAGGED, "lagged"))
        session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
        session.add_entity("tank1", "Tank", {"level_pct": 10.0})
        session.add_relationship("pump1", "feeds", "tank1")
        from arbiter_engine.twin.topology import (
            TraversalDirection, TraversalRequest, ValueMode)
        from arbiter_engine.twin.traverser import TopologyTraverser
        topology = api._build_topology(session)
        result = TopologyTraverser(topology).traverse(TraversalRequest(
            start_nodes=["pump1"], direction=TraversalDirection.FORWARD,
            value_mode=ValueMode.HYPOTHETICAL, max_hops=4,
            overrides={"pump1": {"speed_rpm": 2000.0}}, horizon_s=600.0))
        expected_fraction = 1.0 - math.exp(-(600.0 - 120.0) / 600.0)
        applied = result.transitions_applied
        assert len(applied) == 1
        assert applied[0].fraction == pytest.approx(expected_fraction)
        assert result.imagined_values["tank1"]["level_pct"] == pytest.approx(
            10.0 + 1000.0 * 0.02 * expected_fraction)

    def test_a_horizon_inside_the_delay_moves_nothing(self, tmp_path):
        """Not yet is a real answer, and it must come from the real delay."""
        session = api.EngineSession()
        session.load_model(_model(tmp_path, LAGGED, "lagged"))
        session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
        session.add_entity("tank1", "Tank", {"level_pct": 10.0})
        session.add_relationship("pump1", "feeds", "tank1")
        from arbiter_engine.twin.topology import (
            TraversalDirection, TraversalRequest, ValueMode)
        from arbiter_engine.twin.traverser import TopologyTraverser
        result = TopologyTraverser(api._build_topology(session)).traverse(
            TraversalRequest(
                start_nodes=["pump1"], direction=TraversalDirection.FORWARD,
                value_mode=ValueMode.HYPOTHETICAL, max_hops=4,
                overrides={"pump1": {"speed_rpm": 2000.0}}, horizon_s=60.0))
        assert result.transitions_applied[0].fraction == 0.0


class TestTwoInflowsAddAndSaySo:

    def _confluence(self, tmp_path):
        session = api.EngineSession()
        session.load_model(_model(tmp_path, CONFLUENCE, "confluence"))
        session.add_entity("pa", "PumpA", {"speed_rpm": 1000.0})
        session.add_entity("pb", "PumpB", {"speed_rpm": 1000.0})
        session.add_entity("tk", "Tank", {"level_pct": 10.0})
        session.add_relationship("pa", "feeds", "tk")
        session.add_relationship("pb", "feeds", "tk")
        return session

    def test_concurrent_inflows_superpose(self, tmp_path):
        envelope = api.traverse(
            self._confluence(tmp_path), ["pa", "pb"],
            value_mode="hypothetical",
            overrides={"pa": {"speed_rpm": 2000.0},
                       "pb": {"speed_rpm": 3000.0}})
        # 10 + (1000 x 0.01) + (2000 x 0.02)
        assert _sim(envelope)["values"]["tk"]["level_pct"]["value"] == (
            pytest.approx(60.0))

    def test_superposition_is_stamped_as_an_assumption(self, tmp_path):
        envelope = api.traverse(
            self._confluence(tmp_path), ["pa", "pb"],
            value_mode="hypothetical",
            overrides={"pa": {"speed_rpm": 2000.0},
                       "pb": {"speed_rpm": 3000.0}})
        assert "linear_superposition" in _sim(envelope)["assumptions"]

    def test_both_contributing_edges_are_named(self, tmp_path):
        envelope = api.traverse(
            self._confluence(tmp_path), ["pa", "pb"],
            value_mode="hypothetical",
            overrides={"pa": {"speed_rpm": 2000.0},
                       "pb": {"speed_rpm": 3000.0}})
        assert _sim(envelope)["values"]["tk"]["level_pct"]["via"] == [
            "pa->tk", "pb->tk"]


class TestTheBudgetRefusesRatherThanRuns:
    """`inference/ve.py`: an engine that does not return is worse than one
    that refuses. Exhaustion is a counted decline, never a timeout."""

    def _walk(self, tmp_path, budget):
        session = api.EngineSession()
        session.load_model(_model(tmp_path, CONFLUENCE, "confluence"))
        session.add_entity("pa", "PumpA", {"speed_rpm": 1000.0})
        session.add_entity("pb", "PumpB", {"speed_rpm": 1000.0})
        session.add_entity("tk", "Tank", {"level_pct": 10.0})
        session.add_relationship("pa", "feeds", "tk")
        session.add_relationship("pb", "feeds", "tk")
        from arbiter_engine.twin.topology import (
            TraversalDirection, TraversalRequest, ValueMode)
        from arbiter_engine.twin.traverser import TopologyTraverser
        return TopologyTraverser(api._build_topology(session)).traverse(
            TraversalRequest(
                start_nodes=["pa", "pb"], direction=TraversalDirection.FORWARD,
                value_mode=ValueMode.HYPOTHETICAL, max_hops=4,
                overrides={"pa": {"speed_rpm": 2000.0},
                           "pb": {"speed_rpm": 3000.0}},
                max_transitions=budget))

    def test_an_exhausted_budget_declines_once_with_a_count(self, tmp_path):
        result = self._walk(tmp_path, 1)
        budget = [d for d in result.simulation_declines
                  if d.reason == "budget_exhausted"]
        assert len(budget) == 1, (
            "one decline carrying the count, the way `discovery.py` reports "
            "`pairs_untested` -- not one decline per skipped transition")
        assert "1 of 2" in budget[0].detail

    def test_a_budget_that_is_not_reached_declines_nothing(self, tmp_path):
        result = self._walk(tmp_path, 100)
        assert [d for d in result.simulation_declines
                if d.reason == "budget_exhausted"] == []

    def test_the_attempted_count_still_counts_what_was_refused(self, tmp_path):
        """The denominator must not shrink to match what succeeded."""
        assert self._walk(tmp_path, 0).transitions_attempted == 2
        assert self._walk(tmp_path, 0).transitions_unapplied == 2
