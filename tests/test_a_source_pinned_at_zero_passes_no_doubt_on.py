"""A forecast source pinned by a `set` hands its target no band, whatever
instant the `set` lands on.

The rollout tracks, per seeded property, how much of its forecast band each
movement instant carries: +1 at the seed's own instant, and a `set` at
`when_acted` contributes -1 so the two cancel and a pinned property passes
nothing downstream. The seed's instant is `0.0`. An action at `at_s=0` --
*do this now*, the instant this suite already singles out because it once
fired in no step -- lands on the same key, and the contribution was ASSIGNED
rather than added: +1 became -1, and the pinned source handed its whole band
to its target with the sign flipped.

Measured on a `random_walk` pump feeding a tank through gain 0.02 with no
declared `gain_sigma:`, the pump SET to 2000 rpm:

    at_s=0.0   pump sigma None   tank sigma 0.861   (the pump's band, times 0.02)
    at_s=1.0   pump sigma None   tank sigma None
    at_s=60.0  pump sigma None   tank sigma None

`plan` pins `seed_mode='current'` and is not reached; `rollout(seed_mode=
'projected')` reports the wrong `sigma` and `has_declared_spread`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from arbiter_engine import api
from arbiter_engine.clock import as_of
from arbiter_engine.twin.actions import ActionInstance

T0 = datetime(2026, 9, 10, 12, 0, 0)

MODEL = """
domain:
  id: pinned
  name: A forecast source pinned by a set
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS],
         lower_critical: 100, critical: 4000,
         dynamics: {model: random_walk}}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS],
         warning: 85, critical: 95}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 1,
                 response_model: step}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                   source: datasheet}
  action_templates:
    - name: throttle_pump
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm}
      effect: set
      source: runbook
"""


@pytest.fixture
def session(tmp_path):
    path = tmp_path / "pinned.yaml"
    path.write_text(MODEL)
    s = api.EngineSession()
    s.load_model(str(path))
    rng = np.random.default_rng(5)
    speeds = 1000 + np.cumsum(rng.normal(0, 20, 200))
    for i, speed in enumerate(speeds):
        s.add_observations("pump1", "speed_rpm", [
            (T0 - timedelta(seconds=(199 - i) * 60), float(speed))])
    s.add_entity("pump1", "Pump", {"speed_rpm": float(speeds[-1])})
    s.add_entity("tank1", "Tank", {"level_pct": 50.0})
    s.add_relationship("pump1", "feeds", "tank1")
    return s


@pytest.mark.parametrize("at_s", [0.0, 1.0, 60.0])
def test_the_target_of_a_pinned_source_carries_no_band(session, at_s):
    with as_of(T0):
        simulation = api.rollout(
            session,
            actions=[ActionInstance("throttle_pump", "pump1",
                                    {"speed_rpm": 2000.0}, at_s)],
            horizon_s=600.0, step_s=300.0,
            seed_mode="projected").to_dict()["simulation"]
    for step in simulation["per_step"]:
        assert step["sigma"].get("pump1", {}).get("speed_rpm") is None
        assert step["sigma"].get("tank1", {}).get("level_pct") is None, (
            f"at_s={at_s}, t={step['at_s']}: the pump is pinned and declares "
            f"no gain spread, yet the tank reports "
            f"{step['sigma']['tank1']['level_pct']}")
        # And the value is the pinned one, through the gain, at every step.
        assert step["values"]["pump1"]["speed_rpm"] == 2000.0
