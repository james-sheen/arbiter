"""A declared dead time applies to the whole contribution, offset included.

`_apply_transitions` computed

    delta_target = gain *delta_source *fraction + offset

so the gain term was charged the declared response and the offset walked
straight through it. The moment the source moved, the far end of the edge
jumped by the offset -- including while `response_fraction` was returning
0.0, which is the engine's own way of saying nothing has propagated yet.

Measured before the fix, on the fixture below: a 120-second declared delay,
`offset: 7.0`, and a walk at a 60-second horizon reported the target 7 units
from its reading with `fraction` 0.0 on the `TransitionApplied` record. A dead
time a constant term ignores is not a dead time.

The fix multiplies the whole contribution by the fraction, so at
`fraction == 1.0` the arithmetic is identical to what it replaced and no
steady-state answer moves. What `offset` MEANS is not documented on
`Transition` -- it carries a bare default and no prose -- so this pins the
relationship between the offset and the declared time course, which is
well-defined either way, and does not pin an interpretation of the term
itself.
"""
from __future__ import annotations

import math

import pytest

from arbiter_engine import api

MODEL = """
domain:
  id: offsetting
  name: A coupling with a constant term
  entity_types: [P, T]
  relationship_types: [feeds]
  indicators:
    P: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    T: [{name: w, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  relationship_rules:
    - type: feeds
      source_type: P
      target_type: T
      temporal: {propagation_delay_s: 120, time_constant_s: 600,
                 response_model: exponential}
      transition: {from: v, to: w, gain: 1.0, offset: 7.0, source: datasheet}
"""

DELAY, TAU = 120.0, 600.0
BASE_V, BASE_W, MOVED_V = 10.0, 100.0, 20.0
OFFSET, GAIN = 7.0, 1.0


@pytest.fixture
def session(tmp_path):
    path = tmp_path / "offset.yaml"
    path.write_text(MODEL)
    loaded = api.EngineSession()
    loaded.load_model(str(path))
    loaded.add_entity("p1", "P", {"v": BASE_V})
    loaded.add_entity("t1", "T", {"w": BASE_W})
    loaded.add_relationship("p1", "feeds", "t1")
    return loaded


def _w(session, horizon_s):
    values = api.traverse(session, ["p1"], value_mode="hypothetical",
                          overrides={"p1": {"v": MOVED_V}},
                          horizon_s=horizon_s).to_dict()["simulation"]["values"]
    return values.get("t1", {}).get("w", {}).get("value")


def _fraction(at_s):
    if at_s < DELAY:
        return 0.0
    return 1.0 - math.exp(-(at_s - DELAY) / TAU)


class TestNothingCrossesTheDeclaredDelay:

    @pytest.mark.parametrize("horizon_s", [1.0, 60.0, 119.0])
    def test_the_target_holds_while_the_delay_has_not_elapsed(
            self, session, horizon_s):
        assert _w(session, horizon_s) == pytest.approx(BASE_W), (
            f"at {horizon_s}s the declared 120s dead time has not elapsed, so "
            f"nothing has reached the target -- an offset that arrives anyway "
            f"is the constant term ignoring the time course")


class TestTheOffsetFollowsTheSameResponse:

    @pytest.mark.parametrize("horizon_s", [180.0, 600.0, 1800.0])
    def test_the_whole_contribution_is_charged_the_fraction(
            self, session, horizon_s):
        expected = BASE_W + (GAIN * (MOVED_V - BASE_V) + OFFSET) * _fraction(
            horizon_s)
        assert _w(session, horizon_s) == pytest.approx(expected, abs=1e-6)

    def test_the_steady_state_answer_is_unchanged(self, session):
        """The compatibility guard: at a full response this must equal what
        the previous arithmetic produced, `gain * delta + offset`."""
        settled = _w(session, 3600.0 * 24)
        assert settled == pytest.approx(
            BASE_W + GAIN * (MOVED_V - BASE_V) + OFFSET, abs=1e-6)


class TestAnEdgeWithNoOffsetIsUnaffected:
    """Guard: the change must be invisible to every model that declares none,
    which is every example and fixture this package ships."""

    NO_OFFSET = MODEL.replace(", offset: 7.0", "")

    def test_the_gain_term_alone_is_untouched(self, tmp_path):
        path = tmp_path / "plain.yaml"
        path.write_text(self.NO_OFFSET)
        loaded = api.EngineSession()
        loaded.load_model(str(path))
        loaded.add_entity("p1", "P", {"v": BASE_V})
        loaded.add_entity("t1", "T", {"w": BASE_W})
        loaded.add_relationship("p1", "feeds", "t1")
        for horizon_s in (60.0, 600.0, 3600.0):
            expected = BASE_W + GAIN * (MOVED_V - BASE_V) * _fraction(horizon_s)
            assert _w(loaded, horizon_s) == pytest.approx(expected, abs=1e-6)
