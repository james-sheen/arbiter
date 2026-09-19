"""A seed that forecasts no CHANGE still forecasts with a BAND.

The band reached the target only when the seed's median happened to
differ from the live reading, and the predicate that decided it was value
inequality:

    for entity_id, values in state.items():
        for name, value in values.items():
            if value != baseline.get(entity_id, {}).get(name, value):
                moved_at[(entity_id, name)] = 0.0

`random_walk` is the case that breaks it, and it is not an exotic one. A
random walk's forecast median IS its last observation -- the model's whole
content is *what you saw last is the best guess for what comes next* -- so an
entity whose property was set from the last reading, which is what a collector
writes, seeds a median exactly equal to the baseline. Measured on a 200-sample
walk: the two agreed bit for bit, and

  - the tank carried NO interval at any step (the source's own band was
    +/- 62.75 rpm, which through a gain of 0.02 is +/- 1.25 points);
  - `transitions_applied` was 0, so the declared coupling never ran;
  - and `values_driven` was 0, which let `_file_step` file the SEED as this
    rollout's own prediction -- twelve of them -- while the tank, the only
    thing this rollout actually predicted, was counted in
    `values_without_tolerance`.

That third one is the worst of the three. A projected seed is the `project`
verb's forecast and `project` has already filed it; filing it again scores one
forecast twice in the calibration, which is the exact double-count
`_file_step` documents and refuses. Its guard reads `moved_at`, so the empty
map disabled it.

THE SECOND GATE IS IN THE WALK. `_apply_transitions` skipped an edge whose
source delta was exactly zero before computing the variance term, and
`(gain *fraction)**2 *source_variance` is non-zero for any uncertain source
whatever its median does. A source can stand still and still be uncertain;
those are different facts and the walk conflated them.

WHAT DID NOT CHANGE: a source that has not moved still contributes no VALUE.
The offset is part of a change, not a standing term, so a zero delta puts
`delta_target` at exactly 0.0 rather than `offset *fraction`.
"""
from __future__ import annotations

import random
from datetime import timedelta

import pytest

from arbiter_engine import api

MODEL = """
domain:
  id: standstill
  name: A forecast that predicts no change
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 4h, lookback: 24h, dynamics: {model: random_walk}}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 4h, lookback: 24h}
  relationship_rules:
    - {type: feeds, source_type: Pump, target_type: Tank,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: speed_rpm, to: level_pct, gain: 0.02, source: datasheet}}
"""

GAIN = 0.02
HORIZON_S, STEP_S = 3600.0, 300.0
STEPS = int(HORIZON_S // STEP_S)


def _walk(seed=5, n=200, start=2000.0, sd=25.0):
    rng = random.Random(seed)
    value, out = start, []
    for _ in range(n):
        value += rng.gauss(0.0, sd)
        out.append(value)
    return out


def _session(tmp_path, name):
    """The ordinary setup: the property carries the last reading."""
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL)
    session = api.EngineSession()
    session.load_model(str(path))
    values = _walk()
    session.add_entity("pump1", "Pump", {"speed_rpm": values[-1]})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_relationship("pump1", "feeds", "tank1")
    now = api.now_utc()
    for k, value in enumerate(values):
        session.add_observations(
            "pump1", "speed_rpm",
            [(now - timedelta(seconds=60 * (len(values) - k)), value)])
    return session


def _steps(session, **kw):
    kw.setdefault("horizon_s", HORIZON_S)
    kw.setdefault("step_s", STEP_S)
    kw.setdefault("seed_mode", "projected")
    kw.setdefault("file_predictions", True)
    return api.rollout(session, **kw).to_dict()["simulation"]


class TestTheMedianStandsStill:

    def test_the_seed_really_does_equal_the_reading(self, tmp_path):
        """The premise, pinned. If a future projector stops returning the
        last observation as a random walk's median this test still passes for
        the right reason -- and the three below stop being about anything."""
        simulation = _steps(_session(tmp_path, "premise"))
        seeded = simulation["per_step"][0]["values"]["pump1"]["speed_rpm"]
        assert seeded == _walk()[-1], (
            f"the seed is {seeded} and the last reading is {_walk()[-1]}; "
            f"this fixture is meant to sit on the equal case")


class TestTheBandStillReachesTheTarget:

    def test_a_standing_median_still_carries_its_band(self, tmp_path):
        steps = _steps(_session(tmp_path, "band"))["per_step"]
        assert steps
        missing = [s["at_s"] for s in steps
                   if not s["sigma"].get("tank1", {}).get("level_pct")]
        assert not missing, (
            f"the source forecast carries a band and the target carries none "
            f"at {missing}")

    def test_it_is_the_source_band_through_the_gain(self, tmp_path):
        """Zero delta, so the whole interval is the source's own, scaled."""
        first = _steps(_session(tmp_path, "arith"))["per_step"][0]
        source_sigma = first["sigma"]["pump1"]["speed_rpm"]
        assert first["sigma"]["tank1"]["level_pct"] == pytest.approx(
            GAIN * source_sigma, rel=1e-6)

    def test_the_declared_coupling_actually_ran(self, tmp_path):
        simulation = _steps(_session(tmp_path, "ran"))
        assert simulation["checked"]["transitions_applied"] > 0, (
            "no walk ran: the seed was never registered as a movement "
            "because its median equalled the reading")

    def test_the_value_does_not_move_when_the_source_does_not(self, tmp_path):
        """The floor half. Letting the band through must not let a VALUE
        through: a source standing still moves nothing downstream."""
        steps = _steps(_session(tmp_path, "flat"))["per_step"]
        for step in steps:
            assert step["values"]["tank1"]["level_pct"] == pytest.approx(
                50.0, abs=1e-9), "a standing source moved the target"


class TestTheSeedIsNotFiledAsItsOwnPrediction:

    def test_the_seed_is_counted_as_driven(self, tmp_path):
        checked = _steps(_session(tmp_path, "driven"))["checked"]
        assert checked["values_driven"] == STEPS, (
            f"the pump is seeded from `project`'s forecast at every one of "
            f"{STEPS} steps; {checked['values_driven']} were counted as "
            f"driven, so the rest were filed as this rollout's own")

    def test_what_is_filed_is_the_target_and_only_the_target(self, tmp_path):
        checked = _steps(_session(tmp_path, "filed"))["checked"]
        assert checked["predictions_filed"] == STEPS
        assert checked["values_without_tolerance"] == 0

    def test_the_three_counts_still_partition_every_value(self, tmp_path):
        simulation = _steps(_session(tmp_path, "partition"))
        checked = simulation["checked"]
        total = sum(len(values)
                    for step in simulation["per_step"]
                    for values in step["values"].values())
        assert (checked["predictions_filed"]
                + checked["values_without_tolerance"]
                + checked["values_driven"]) == total
