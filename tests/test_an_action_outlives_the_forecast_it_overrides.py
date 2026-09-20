"""A forecast says where a property is HEADING. An action says where it IS.

`seed_mode='projected'` overlays each step's projection onto the
imagined state. It ran AFTER the actions and wrote straight over them, and it
re-ran every step, so a property carrying a `dynamics:` block could not be
acted on at all:

    for entity_id, deltas in action_deltas.items():
.
        state[entity_id][prop] = state[entity_id].get(prop, 0.0) + delta

    # 1b. the seed at *this* instant
    for (entity_id, prop), curve in curves.items():
.
        state.setdefault(entity_id, {})[prop] = float(value)

Measured on the fixture below -- a 200-sample random walk, the pump SET to
2500 rpm at `t=0`, a declared `gain: 0.02` to the tank:

  | seed_mode | pump reads | tank reads | actions_applied | declines |
  |-------------|------------|------------|---------------------|----------|
  | `current` | 2500.000 | 62.2840 | throttle@pump1 | none |
  | `projected` | 1885.798 | 50.0000 | throttle@pump1 | none |

1885.798 is the last observation. The action was accepted, counted, reported
applied, and discarded; the tank -- the only thing the rollout was asked
about -- never moved. The drift reconciliation then made the movement list
agree with that state by zeroing the action's own movement, so the
decomposition was consistent and consistently wrong.

This module already says what is wrong with that, in the comment a
hundred lines up: AN ACTION THAT IS ACCEPTED AND SILENTLY NEVER APPLIED IS
WORSE THAN ONE THAT IS REFUSED.

THE RULE. A projection is fitted from history and cannot know about an
action scheduled in the future, so it describes the UNMANAGED trajectory. The
two compose without anyone guessing: the projection governs a property up to
the instant it is acted on, and the action governs it from there. So the seed
is overlaid BEFORE the actions of the same step -- which also makes the
action's delta the distance from where the forecast put the property, which
is what the caller asked -- and a property that has been acted on is not
re-seeded in any later step.

WHAT THIS IS NOT: the action does not delete the forecast's contribution to
the past. The movement registered at `t=0` keeps the displacement the seed
had reached when the intervention landed, so the target's response to the
forecast still develops on its own clock and the two superpose.
"""
from __future__ import annotations

import random
from datetime import timedelta

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance

MODEL = """
domain:
  id: override
  name: Acting on a property that carries a forecast
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 4h, lookback: 24h, dynamics: {model: random_walk}}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 4h, lookback: 24h}
  action_templates:
    - name: throttle
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm,
                    candidates: [2500]}
      effect: set
      settle_s: 0
      source: runbook
  relationship_rules:
    - {type: feeds, source_type: Pump, target_type: Tank,
       temporal: {propagation_delay_s: 0, time_constant_s: 1,
                  response_model: step},
       transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                    source: datasheet}}
"""

GAIN = 0.02
BASE_LEVEL = 50.0
SET_TO = 2500.0
HORIZON_S, STEP_S = 3600.0, 600.0


def _walk(seed=5, n=200, start=2000.0, sd=25.0):
    rng = random.Random(seed)
    value, out = start, []
    for _ in range(n):
        value += rng.gauss(0.0, sd)
        out.append(value)
    return out


LAST_READING = _walk()[-1]


def _session(tmp_path, name):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL)
    session = api.EngineSession()
    session.load_model(str(path))
    values = _walk()
    session.add_entity("pump1", "Pump", {"speed_rpm": values[-1]})
    session.add_entity("tank1", "Tank", {"level_pct": BASE_LEVEL})
    session.add_relationship("pump1", "feeds", "tank1")
    now = api.now_utc()
    for k, value in enumerate(values):
        session.add_observations(
            "pump1", "speed_rpm",
            [(now - timedelta(seconds=60 * (len(values) - k)), value)])
    return session


def _throttle(at_s=0.0, rpm=SET_TO):
    return ActionInstance("throttle", "pump1", {"speed_rpm": rpm}, at_s)


def _run(session, seed_mode, actions=None, **kw):
    kw.setdefault("horizon_s", HORIZON_S)
    kw.setdefault("step_s", STEP_S)
    return api.rollout(
        session, actions=actions if actions is not None else [_throttle()],
        seed_mode=seed_mode, **kw).to_dict()["simulation"]


class TestThePremise:
    """A `random_walk` median IS the last observation, so the seed and the
    reading agree bit for bit here. If that ever stops being true this file
    stops being about anything, and it should say so rather than pass."""

    def test_the_seed_equals_the_last_reading(self, tmp_path):
        steps = _run(_session(tmp_path, "premise"), "projected",
                     actions=[])["per_step"]
        assert steps[0]["values"]["pump1"]["speed_rpm"] == pytest.approx(
            LAST_READING)


class TestTheActionSurvivesTheSeed:

    def test_the_acted_property_reads_what_the_action_set(self, tmp_path):
        steps = _run(_session(tmp_path, "value"), "projected")["per_step"]
        for step in steps:
            got = step["values"]["pump1"]["speed_rpm"]
            assert got == pytest.approx(SET_TO), (
                f"at {step['at_s']}s the pump reads {got}; it was SET to "
                f"{SET_TO} and the forecast's {LAST_READING:.3f} wrote over "
                f"it")

    def test_the_target_moves_at_all(self, tmp_path):
        """The consequence that matters. The tank is the only thing this
        rollout was asked about and it never left its baseline."""
        last = _run(_session(tmp_path, "target"), "projected")["per_step"][-1]
        assert last["values"]["tank1"]["level_pct"] != pytest.approx(
            BASE_LEVEL), "the tank never moved, so the action reached nothing"

    def test_both_seed_modes_settle_in_the_same_place(self, tmp_path):
        """A `set` pins the property, so where the forecast HAD it stops
        mattering once the response has developed. The two modes may differ
        while the transient runs and must agree at the end."""
        current = _run(_session(tmp_path, "sm-cur"), "current")
        projected = _run(_session(tmp_path, "sm-proj"), "projected")
        a = current["per_step"][-1]["values"]["tank1"]["level_pct"]
        b = projected["per_step"][-1]["values"]["tank1"]["level_pct"]
        assert b == pytest.approx(a, abs=1e-6), (
            f"seed_mode='current' settles the tank at {a} and "
            f"seed_mode='projected' at {b}; the pump is pinned at {SET_TO} "
            f"in both")

    def test_the_settled_value_is_the_declared_arithmetic(self, tmp_path):
        last = _run(_session(tmp_path, "arith"), "projected")["per_step"][-1]
        expected = BASE_LEVEL + GAIN * (SET_TO - LAST_READING)
        assert last["values"]["tank1"]["level_pct"] == pytest.approx(
            expected, abs=1e-6)


class TestTheEngineSaysItSupersededTheForecast:
    """Stamped rather than silent. A reader comparing the two seed modes sees
    a property stop following its forecast, and nothing else in the envelope
    explains why."""

    def test_the_stamp_is_there_when_a_projection_is_overridden(
            self, tmp_path):
        simulation = _run(_session(tmp_path, "stamp"), "projected")
        assert "projection_superseded_by_action" in simulation["assumptions"]

    def test_the_stamp_is_absent_when_nothing_was_superseded(self, tmp_path):
        """Two ways to have superseded nothing, and neither may stamp it: no
        projection to override, and a projection nobody acted on."""
        acted_only = _run(_session(tmp_path, "cur-stamp"), "current")
        assert "projection_superseded_by_action" not in (
            acted_only["assumptions"])
        seeded_only = _run(_session(tmp_path, "seed-stamp"), "projected",
                           actions=[])
        assert "projection_superseded_by_action" not in (
            seeded_only["assumptions"])


class TestAnUnactedPropertyIsStillSeededEveryStep:
    """The floor for. Skipping the re-seed must be keyed on having
    been ACTED ON, not on having been seeded once."""

    def test_a_property_nobody_acts_on_follows_its_forecast(self, tmp_path):
        steps = _run(_session(tmp_path, "unacted"), "projected",
                     actions=[])["per_step"]
        for step in steps:
            assert step["values"]["pump1"]["speed_rpm"] == pytest.approx(
                LAST_READING), "the seed stopped being applied"

    def test_seed_mode_current_is_untouched(self, tmp_path):
        last = _run(_session(tmp_path, "cur"), "current")["per_step"][-1]
        assert last["values"]["pump1"]["speed_rpm"] == pytest.approx(SET_TO)
        assert last["values"]["tank1"]["level_pct"] == pytest.approx(
            BASE_LEVEL + GAIN * (SET_TO - LAST_READING), abs=1e-6)
