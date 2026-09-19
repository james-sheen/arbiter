"""A what-if says WHEN, and the envelope says when it answered.

THE PUBLISHED VERB HAD NO HORIZON. `api.traverse` took `direction`,
`value_mode`, `max_hops` and `overrides`, built a `TraversalRequest` without
touching `horizon_s`, and got the request default of one hour. So every
hypothetical walk reached through `api` or MCP was evaluated at 3600 s, a
caller could not ask what a value becomes in ten minutes, and
`response_fraction` was read at an hour with nothing in the envelope naming
the instant.

The kernel had the parameter and dropped it too: `simulate_what_if` accepted
`horizon_s` and never passed it into the request it built, so asking it for
ten minutes returned the one-hour answer. A parameter a method takes and
ignores is worse than one it does not offer -- the caller has been told the
question was asked.

The horizon is now stamped into `payload.simulation`, because a value caught
partway through a declared response and one that has finished moving are the
same number to a reader who cannot see the instant.
"""
from __future__ import annotations

import math

import pytest

from arbiter_engine import api

MODEL = """
domain:
  id: horizon
  name: MODELING.md's own declared response
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 120, time_constant_s: 600,
                 response_model: exponential}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02, source: datasheet}
"""

DELAY, TAU, GAIN = 120.0, 600.0, 0.02
BASE_LEVEL, BASE_SPEED, TARGET_SPEED = 50.0, 1000.0, 4000.0
STEADY_DELTA = GAIN * (TARGET_SPEED - BASE_SPEED)


@pytest.fixture
def session(tmp_path):
    path = tmp_path / "horizon.yaml"
    path.write_text(MODEL)
    loaded = api.EngineSession()
    loaded.load_model(str(path))
    loaded.add_entity("pump1", "Pump", {"speed_rpm": BASE_SPEED})
    loaded.add_entity("tank1", "Tank", {"level_pct": BASE_LEVEL})
    loaded.add_relationship("pump1", "feeds", "tank1")
    return loaded


def _walk(session, **kw):
    return api.traverse(session, ["pump1"], value_mode="hypothetical",
                        overrides={"pump1": {"speed_rpm": TARGET_SPEED}},
                        **kw).to_dict()["simulation"]


def _declared(at_s):
    """Written out rather than read off the edge under test."""
    if at_s < DELAY:
        return BASE_LEVEL
    return BASE_LEVEL + STEADY_DELTA * (1.0 - math.exp(-(at_s - DELAY) / TAU))


class TestTheHorizonReachesTheWalk:

    @pytest.mark.parametrize("horizon_s", [60.0, 300.0, 600.0, 3600.0])
    def test_the_value_is_the_declared_response_at_that_instant(
            self, session, horizon_s):
        values = _walk(session, horizon_s=horizon_s)["values"]
        got = values["tank1"]["level_pct"]["value"]
        assert got == pytest.approx(_declared(horizon_s), abs=1e-6)

    def test_a_horizon_inside_the_delay_moves_nothing(self, session):
        values = _walk(session, horizon_s=60.0)["values"]
        assert values["tank1"]["level_pct"]["value"] == pytest.approx(
            BASE_LEVEL), "60s is inside a declared 120s delay"

    def test_two_horizons_do_not_give_the_same_answer(self, session):
        """The symptom: every horizon returned the one-hour number."""
        short = _walk(session, horizon_s=600.0)["values"][
            "tank1"]["level_pct"]["value"]
        long = _walk(session, horizon_s=3600.0)["values"][
            "tank1"]["level_pct"]["value"]
        assert short != pytest.approx(long), (
            "ten minutes and one hour of a 600s first-order response are not "
            "the same value; one of them is not being asked for")

    def test_the_default_is_still_an_hour(self, session):
        """Additive, so an existing caller keeps the answer it had."""
        assert _walk(session)["values"]["tank1"]["level_pct"][
            "value"] == pytest.approx(_declared(3600.0), abs=1e-6)


class TestTheEnvelopeNamesTheInstant:

    @pytest.mark.parametrize("horizon_s", [60.0, 600.0, 3600.0])
    def test_the_horizon_used_is_reported(self, session, horizon_s):
        assert _walk(session, horizon_s=horizon_s)["horizon_s"] == pytest.approx(
            horizon_s)


class TestTheKernelForwardsItToo:
    """`simulate_what_if` took the parameter and dropped it."""

    def test_the_kernel_honours_the_horizon_it_was_given(self, session):
        from arbiter_engine.twin.traverser import TopologyTraverser
        topology = api._build_topology(session)
        overrides = {"pump1": {"speed_rpm": TARGET_SPEED}}
        short = TopologyTraverser(topology).simulate_what_if(
            overrides, horizon_s=600.0)
        long = TopologyTraverser(topology).simulate_what_if(
            overrides, horizon_s=3600.0)
        assert short.imagined_values["tank1"]["level_pct"] == pytest.approx(
            _declared(600.0), abs=1e-6)
        assert long.imagined_values["tank1"]["level_pct"] == pytest.approx(
            _declared(3600.0), abs=1e-6)
