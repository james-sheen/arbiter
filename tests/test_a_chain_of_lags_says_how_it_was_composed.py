"""Two first-order edges in series: what the second hop reports, and whether
the envelope says how it got there.

`_apply_transitions` charges each edge `response_fraction(horizon -
cum_delay_at_source)` against the source's ALREADY-LAGGED value, so a value
two hops out is the PRODUCT `f_1(t) * f_2(t - d_1)` of the two step
responses. The series response of two linear first-order stages is their
convolution, and the two are not the same curve: for two equal lags with no
dead time the series step response is `1 - (1 + t/tau) exp(-t/tau)` while the
product is `(1 - exp(-t/tau))^2`. Measured on tau = 600 s, gain 1 twice,
a 100-unit step at the head:

    t=600   second hop 39.96   series 26.42
    t=960   second hop 63.61   series 47.42   (worst: 16.19 units early)
    t=3600  second hop 99.51   series 98.27

The steady state agrees; the TRANSIENT is faster than the declared dynamics
imply, so a breach two hops out is predicted earlier than the model says and
`plan` ranks on that. This is an engine assumption, not an author's: every
other one the walk makes is stamped (`first_order_response` names ONE edge's
curve, `linear_superposition` names how concurrent edges into one property
add). Nothing names how edges in SERIES compose. Either the engine composes
them as a series response, or it stamps the product form so a reader of the
envelope knows which curve they are looking at. This file accepts either.
"""
from __future__ import annotations

import math

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance

TAU = 600.0

MODEL = """
domain:
  id: chain
  name: Two lags in series
  entity_types: [A, B, C]
  relationship_types: [ab, bc]
  indicators:
    A: [{name: x, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 1e9}]
    B: [{name: x, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 1e9}]
    C: [{name: x, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 1e9}]
  relationship_rules:
    - type: ab
      source_type: A
      target_type: B
      temporal: {propagation_delay_s: 0, time_constant_s: 600,
                 response_model: exponential}
      transition: {from: x, to: x, gain: 1.0, source: datasheet}
    - type: bc
      source_type: B
      target_type: C
      temporal: {propagation_delay_s: 0, time_constant_s: 600,
                 response_model: exponential}
      transition: {from: x, to: x, gain: 1.0, source: datasheet}
  action_templates:
    - name: set_a
      applies_to: A
      parameters_schema:
        x: {type: number, entity_property: x}
      effect: set
      source: runbook
"""


@pytest.fixture
def simulation(tmp_path):
    path = tmp_path / "chain.yaml"
    path.write_text(MODEL)
    s = api.EngineSession()
    s.load_model(str(path))
    for entity in "abc":
        s.add_entity(entity, entity.upper(), {"x": 0.0})
    s.add_relationship("a", "ab", "b")
    s.add_relationship("b", "bc", "c")
    return api.rollout(
        s, actions=[ActionInstance("set_a", "a", {"x": 100.0}, 0.0)],
        horizon_s=3600.0, step_s=60.0).to_dict()["simulation"]


def _series(t):
    return 1.0 - (1.0 + t / TAU) * math.exp(-t / TAU)


def _product(t):
    return (1.0 - math.exp(-t / TAU)) ** 2


def test_the_first_hop_is_the_declared_curve(simulation):
    for step in simulation["per_step"]:
        t = step["at_s"]
        assert step["values"]["b"]["x"] == pytest.approx(
            100.0 * (1.0 - math.exp(-t / TAU)), abs=1e-6)


def test_the_second_hop_is_either_the_series_response_or_says_it_is_not(
        simulation):
    """Composed as a series, or stamped as a product. Silence is the one
    outcome this refuses."""
    worst = max(
        abs(step["values"]["c"]["x"] - 100.0 * _series(step["at_s"]))
        for step in simulation["per_step"])
    composed_as_series = worst < 0.5
    stamped = any("product" in stamp or "series" in stamp or
                  "cascade" in stamp or "chain" in stamp
                  for stamp in simulation["assumptions"])
    assert composed_as_series or stamped, (
        f"second hop departs from the series response by up to {worst:.2f} "
        f"units and the assumptions are {simulation['assumptions']}: "
        f"nothing on the envelope names how edges in series compose")


def test_what_the_second_hop_currently_is(simulation):
    """Pinned so the number cannot move without somebody noticing. If the
    composition changes to a series response this test is the one to
    retire, and the one above stops needing the stamp."""
    for step in simulation["per_step"]:
        t = step["at_s"]
        assert step["values"]["c"]["x"] == pytest.approx(
            100.0 * _product(t), abs=1e-6), f"at t={t}"


# ---------------------------------------------------------------------------
# The three cases the stamp must NOT appear on, without which a stamp
# on every rollout says nothing. A reader learns from a stamp only by its
# absence somewhere.

SINGLE_HOP = MODEL.replace("""    - type: bc
      source_type: B
      target_type: C
      temporal: {propagation_delay_s: 0, time_constant_s: 600,
                 response_model: exponential}
      transition: {from: x, to: x, gain: 1.0, source: datasheet}
""", "")

STEP_CHAIN = MODEL.replace("response_model: exponential",
                           "response_model: step")

STAMP = "series_edges_compose_by_product"


def _assumptions(tmp_path, text, entities="abc", edges=(("a", "ab", "b"),
                                                        ("b", "bc", "c"))):
    path = tmp_path / "case.yaml"
    path.write_text(text)
    session = api.EngineSession()
    session.load_model(str(path))
    for entity in entities:
        session.add_entity(entity, entity.upper(), {"x": 0.0})
    for source, relation, target in edges:
        session.add_relationship(source, relation, target)
    return api.rollout(
        session, actions=[ActionInstance("set_a", "a", {"x": 100.0}, 0.0)],
        horizon_s=3600.0, step_s=600.0).to_dict()["simulation"]["assumptions"]


class TestTheStampSaysSomethingByBeingAbsent:

    def test_a_chain_of_two_lags_carries_it(self, tmp_path):
        assert STAMP in _assumptions(tmp_path, MODEL)

    def test_one_hop_does_not(self, tmp_path):
        """One edge IS its declared curve; `first_order_response` already
        says so and there is nothing composed to qualify."""
        assert STAMP not in _assumptions(
            tmp_path, SINGLE_HOP, entities="ab", edges=(("a", "ab", "b"),))

    def test_a_chain_of_STEP_edges_does_not(self, tmp_path):
        """A step response composes with a step response EXACTLY: the product
        of two unit steps delayed by d1 and d2 is a unit step delayed by
        d1 + d2, which is the series answer. The approximation is in the
        TIME CONSTANT, so an edge that declares no transient shape cannot be
        part of one."""
        assumptions = _assumptions(tmp_path, STEP_CHAIN)
        assert STAMP not in assumptions, (
            f"two `step` edges compose exactly and were stamped anyway: "
            f"{assumptions}")
