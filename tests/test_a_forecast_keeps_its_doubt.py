"""A rollout seeded from a forecast inherits the doubt, not just the number.

TWO DEFECTS, BOTH IN THE LOOP THIS PACKAGE HAD JUST CLOSED.

A projector returns a DISTRIBUTION. `ProjectedValue` carried only its median,
so a rollout seeded from a forecast took the number and threw away the band.
The predictions it then filed were bounded by the declared `gain_sigma:`
alone. Measured on a random walk at a 60-minute horizon: the source forecast's
own 90 % band was +/- 357.55 rpm, which through a gain of 0.02 is +/- 7.15
points on the target -- and the filed tolerance was +/- 0.45. Sixteen times
too narrow, which falsifies projections that were never wrong and makes the
engine's own calibration figure say its forecasts are worthless.

And the band was the same at every step, because the seed was a single
forecast taken at the FULL horizon and then held. Measured on a 60-minute
rollout in 5-minute steps: step one reported the target at the value it
reaches after an hour. That is the frozen transient again in a different
place -- a single-point answer stretched across a trajectory.

The seed is now read off the fitted curve AT EACH STEP'S OWN INSTANT, and its
spread rides into the walk so a transition carries it downstream through the
gain exactly as it carries a declared one.

WHAT THE MEDIAN DOES IS THE PROJECTOR'S BUSINESS, NOT THIS FILE'S. All three
shipped models return a constant mean with a widening band -- `TrendCurve`
encodes its slope as process noise rather than committing to a direction,
which is the stated reason a curve fit is not the default. So these tests pin
that the SPREAD grows and that the value is whatever the declared model says,
and they do not assert a direction the models decline to state.
"""
from __future__ import annotations

import math
import random
from datetime import timedelta

import pytest

from arbiter_engine import api

MODEL = """
domain:
  id: doubt
  name: A forecast with a band
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
       transition: {from: speed_rpm, to: level_pct, gain: %(gain)s%(sigma)s,
                    source: datasheet}}
"""

GAIN = 0.02
HORIZON_S, STEP_S = 3600.0, 300.0


def _session(tmp_path, name, sigma=""):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL % {"gain": GAIN, "sigma": sigma})
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": 2000.0})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_relationship("pump1", "feeds", "tank1")
    rng = random.Random(5)
    now, value = api.now_utc(), 2000.0
    for k in range(200):
        value += rng.gauss(0.0, 25.0)
        session.add_observations(
            "pump1", "speed_rpm",
            [(now - timedelta(seconds=60 * (200 - k)), value)])
    return session


def _steps(session, **kw):
    kw.setdefault("horizon_s", HORIZON_S)
    kw.setdefault("step_s", STEP_S)
    kw.setdefault("seed_mode", "projected")
    kw.setdefault("file_predictions", True)
    return api.rollout(session, **kw).to_dict()["simulation"]


def _tank_sigma(step):
    return step["sigma"].get("tank1", {}).get("level_pct")


class TestTheBandReachesTheTarget:

    def test_the_target_is_uncertain_because_the_source_is(self, tmp_path):
        """No `gain_sigma:` declared at all: every bit of this comes from the
        seed's own forecast, passed through the gain."""
        steps = _steps(_session(tmp_path, "band"))["per_step"]
        assert steps
        assert all(_tank_sigma(s) for s in steps), (
            "the source's forecast carries a band and the gain passes it "
            "through; the target cannot be certain")

    def test_it_is_the_source_band_through_the_gain(self, tmp_path):
        """Checked against the arithmetic, not against the engine."""
        steps = _steps(_session(tmp_path, "arith"))["per_step"]
        first = steps[0]
        source_sigma = first["sigma"]["pump1"]["speed_rpm"]
        assert _tank_sigma(first) == pytest.approx(
            GAIN * source_sigma, rel=1e-6)

    def test_a_declared_gain_spread_adds_in_quadrature(self, tmp_path):
        """Two independent doubts, combined the way independent doubts are."""
        declared = 0.002
        steps = _steps(_session(tmp_path, "both",
                                sigma=f", gain_sigma: {declared}"))["per_step"]
        first = steps[0]
        source_sigma = first["sigma"]["pump1"]["speed_rpm"]
        delta = abs(first["values"]["pump1"]["speed_rpm"] - 2000.0)
        expected = math.sqrt((GAIN * source_sigma) ** 2
                             + (declared * delta) ** 2)
        assert _tank_sigma(first) == pytest.approx(expected, rel=1e-6)


class TestTheBandWidensWithTheHorizon:

    def test_a_later_step_is_less_certain_than_an_earlier_one(self, tmp_path):
        steps = _steps(_session(tmp_path, "widen"))["per_step"]
        spreads = [_tank_sigma(s) for s in steps]
        assert all(b > a for a, b in zip(spreads, spreads[1:])), (
            f"the band did not widen across the horizon: {spreads}")

    def test_it_widens_as_a_random_walk_should(self, tmp_path):
        """A random walk's variance grows with time, so its sigma grows as
        the square root of it. Twelve steps in, the band should be about
        sqrt(12) times the first one."""
        steps = _steps(_session(tmp_path, "sqrt"))["per_step"]
        ratio = _tank_sigma(steps[-1]) / _tank_sigma(steps[0])
        assert ratio == pytest.approx(math.sqrt(len(steps)), rel=0.05), (
            f"the band grew by {ratio:.3f} over {len(steps)} steps")

    def test_the_filed_tolerances_widen_too(self, tmp_path):
        """The point of all of it: a prediction at an hour must not be graded
        against a five-minute window."""
        session = _session(tmp_path, "tolerances")
        _steps(session)
        tolerances = [r.tolerance for r in session.ledger.pending()]
        assert len(set(tolerances)) > 1, (
            "every filed prediction carried the same tolerance, so the one at "
            "the far end of the horizon is held to the near end's precision")
        assert max(tolerances) > 2 * min(tolerances)


class TestAnInputIsNotAPredictionOfOurs:

    def test_the_seed_itself_is_not_filed(self, tmp_path):
        """`project` already files the source's forecast as a distribution.
        Filing it again here would score one forecast twice."""
        session = _session(tmp_path, "notwice")
        simulation = _steps(session)
        filed = {(r.entity_id, r.indicator) for r in session.ledger.pending()}
        assert ("pump1", "speed_rpm") not in filed
        assert ("tank1", "level_pct") in filed
        assert simulation["checked"]["values_driven"] > 0

    def test_the_counts_still_partition(self, tmp_path):
        simulation = _steps(_session(tmp_path, "partition"))
        seen = sum(len(props) for step in simulation["per_step"]
                   for props in step["values"].values())
        checked = simulation["checked"]
        assert (checked["predictions_filed"]
                + checked["values_without_tolerance"]
                + checked["values_driven"]) == seen
