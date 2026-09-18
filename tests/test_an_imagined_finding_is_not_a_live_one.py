"""A finding about an imagined state never shares a type with a real one.

Measured at 0.1.18, before a what-if driving a pump past its declared
ceiling returned `twin_boundedness:speed_rpm`, and a pump that was ACTUALLY
past its ceiling returned `twin_boundedness:speed_rpm`. Byte-identical. A
consumer holding the two envelopes could not tell *your system is breaking*
from *your model of your system would break*, and the second one is not an
incident.

`forecast/shadow.py` already solved this for forecasts, prefixing `forecast_`,
and states the reason. The prefix here is `imagined_` and deliberately not
`forecast_`: a forecast is something a PRODUCER supplied and the engine grades
against a random walk, and the repository separates the engine's own output
from a producer's everywhere else -- there is a standing test that the
engine's `project` output is never counted as a bridge's forecast. One prefix
for both would make `forecast_boundedness:x` mean two different things
depending on which verb produced it.

THE RULE IS PER-VALUE, NOT PER-VERB, and that distinction is the subtle part.
A HYPOTHETICAL walk reads most of the topology at its current reading: only
the overridden node and whatever a transition moved are imagined. A finding
drawn from a real reading is a real finding whichever walk found it, so
prefixing everything a simulating walk returns would be as wrong as prefixing
nothing -- it would relabel live breaches as hypothetical and hide them.
"""
from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.twin.traverser import IMAGINED_PREFIX

MODEL = """
domain:
  id: imagined
  name: Imagined versus live
  entity_types: [Pump, Tank, Gauge]
  relationship_types: [feeds, reports]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 3200}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 95}
    Gauge:
      - {name: reading, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 10}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step}
      transition: {from: speed_rpm, to: level_pct, gain: 0.05, source: datasheet}
    - type: reports
      source_type: Pump
      target_type: Gauge
      temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step}
"""


def _session(tmp_path, *, speed, level, reading):
    path = tmp_path / "imagined.yaml"
    path.write_text(MODEL)
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": speed})
    session.add_entity("tank1", "Tank", {"level_pct": level})
    session.add_entity("gauge", "Gauge", {"reading": reading})
    session.add_relationship("pump1", "feeds", "tank1")
    session.add_relationship("pump1", "reports", "gauge")
    return session


def _types(payload):
    return [f["problem_type"] for f in payload["findings"]]


class TestTheTwoKindsOfFindingAreDistinguishable:

    def test_a_live_breach_is_unprefixed(self, tmp_path):
        payload = api.traverse(
            _session(tmp_path, speed=3500.0, level=50.0, reading=1.0),
            ["pump1"], value_mode="current").to_dict()
        assert _types(payload) == ["twin_boundedness:speed_rpm"]

    def test_an_imagined_breach_is_prefixed(self, tmp_path):
        payload = api.traverse(
            _session(tmp_path, speed=2000.0, level=50.0, reading=1.0),
            ["pump1"], value_mode="hypothetical",
            overrides={"pump1": {"speed_rpm": 3500.0}}).to_dict()
        assert IMAGINED_PREFIX + "twin_boundedness:speed_rpm" in _types(payload)

    def test_the_two_never_share_a_problem_type(self, tmp_path):
        live = set(_types(api.traverse(
            _session(tmp_path, speed=3500.0, level=50.0, reading=1.0),
            ["pump1"], value_mode="current").to_dict()))
        imagined = set(_types(api.traverse(
            _session(tmp_path, speed=2000.0, level=50.0, reading=1.0),
            ["pump1"], value_mode="hypothetical",
            overrides={"pump1": {"speed_rpm": 3500.0}}).to_dict()))
        assert live and imagined
        assert not (live & imagined), (
            f"{live & imagined} means an incident and a simulation are "
            f"indistinguishable to a consumer routing on problem_type")

    def test_a_finding_on_a_derived_value_is_also_prefixed(self, tmp_path):
        """The value the TRANSITION produced, not the one the caller set."""
        payload = api.traverse(
            _session(tmp_path, speed=2000.0, level=50.0, reading=1.0),
            ["pump1"], value_mode="hypothetical",
            overrides={"pump1": {"speed_rpm": 3000.0}}).to_dict()
        assert IMAGINED_PREFIX + "twin_boundedness:level_pct" in _types(payload)

    def test_the_evidence_says_imagined_too(self, tmp_path):
        """A consumer reading evidence must not have to parse the type.

        Read off the DISCIPLINE leg, which is where evidence lives: the
        top-level findings leg carries none, by the envelope's own design.
        """
        payload = api.traverse(
            _session(tmp_path, speed=2000.0, level=50.0, reading=1.0),
            ["pump1"], value_mode="hypothetical",
            overrides={"pump1": {"speed_rpm": 3500.0}}).to_dict()
        imagined = [f for f in payload["simulation"]["findings"]
                    if f["problem_type"].startswith(IMAGINED_PREFIX)]
        assert imagined, "guard: an empty list satisfies `all` trivially"
        assert all(f["evidence"].get("imagined") is True for f in imagined)


class TestARealReadingStaysRealInsideASimulation:
    """The per-value rule. `gauge` is reached by an edge with no transition,
    so it is read at its actual value and any finding on it is live."""

    def test_an_untouched_node_breaching_reports_an_unprefixed_finding(
            self, tmp_path):
        payload = api.traverse(
            _session(tmp_path, speed=2000.0, level=50.0, reading=99.0),
            ["pump1"], value_mode="hypothetical",
            overrides={"pump1": {"speed_rpm": 2100.0}}).to_dict()
        assert "twin_boundedness:reading" in _types(payload), (
            "the gauge is genuinely over its ceiling and nothing imagined "
            "touched it; relabelling that as hypothetical hides a real breach")
        assert (IMAGINED_PREFIX + "twin_boundedness:reading"
                not in _types(payload))

    def test_an_imagined_value_never_borrows_a_current_reading(self, tmp_path):
        """`shadow.py`'s rule, applied here.

        The gauge has no declared transition, so no imagined value exists for
        it. It must be absent from the simulation's values -- not present
        carrying today's number, which would read as a projection.
        """
        values = api.traverse(
            _session(tmp_path, speed=2000.0, level=50.0, reading=1.0),
            ["pump1"], value_mode="hypothetical",
            overrides={"pump1": {"speed_rpm": 3000.0}}
        ).to_dict()["simulation"]["values"]
        assert "gauge" not in values
        assert "tank1" in values


class TestTheSimulationDenominatorIsItsOwn:

    def _payload(self, tmp_path):
        return api.traverse(
            _session(tmp_path, speed=2000.0, level=50.0, reading=1.0),
            ["pump1"], value_mode="hypothetical",
            overrides={"pump1": {"speed_rpm": 3000.0}}).to_dict()

    def test_invariants_counts_axioms_not_transitions(self, tmp_path):
        payload = self._payload(tmp_path)
        simulation = payload["simulation"]["checked"]
        assert payload["checked"]["invariants"] != (
            payload["checked"]["invariants"]
            + simulation["transitions_attempted"]), "guard against a no-op"
        # The two denominators count different things in different units and
        # are never added. An axiom evaluation is not a transition.
        assert simulation["transitions_attempted"] >= 1
        assert payload["checked"]["invariants"] >= 1

    def test_applied_and_declined_do_not_exceed_attempted(self, tmp_path):
        checked = self._payload(tmp_path)["simulation"]["checked"]
        assert checked["transitions_applied"] <= checked[
            "transitions_attempted"]

    def test_the_findings_appear_in_both_legs_and_agree(self, tmp_path):
        """The `project` verb's rule: a discipline's findings ride in the
        generic leg too, and something holds the two copies to each other."""
        payload = self._payload(tmp_path)
        generic = {f["problem_type"] for f in payload["findings"]
                   if f["problem_type"].startswith(IMAGINED_PREFIX)}
        discipline = {f["problem_type"]
                      for f in payload["simulation"]["findings"]}
        assert generic == discipline
        assert generic, "guard: an empty comparison passes trivially"
