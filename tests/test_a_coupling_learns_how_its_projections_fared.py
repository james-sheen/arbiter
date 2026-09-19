"""A declared coupling reports how its own projections turned out.

THE LOOP RAN ONE WAY. Rollouts file value predictions and `check`
grades them, so the ledger knows whether a declared gain's forecasts held.
Nothing read that back to the gain. An author could look at a coupling, see a
fitted disagreement beside it, and not see that every projection the coupling
had produced was contradicted by the world -- which is the stronger evidence
of the two, because it is about the model's OUTPUT rather than about a slope.

A FITTED SPREAD, PROPOSED THE SAME WAY A FITTED GAIN IS. The learner
already computed a standard error on every gain it fitted -- a measured
statement of how well the readings pin the slope down, sitting one field away
from the `gain_sigma:` that declares the same quantity. It is now surfaced,
and `gain_sigma: estimate` is how an author asks for it.

BOTH ARE REPORTS, NEITHER IS AN EDIT. The engine does not rewrite a
declaration, does not adopt a fitted spread, and does not quietly widen an
interval because the last five forecasts missed. A confirm rate is evidence an
author weighs; the remedy says what to consider and nothing does it.
"""
from __future__ import annotations

import random
from datetime import timedelta

import pytest

from arbiter_engine import api

GAIN, SIGMA = 0.02, 0.002
BASE_SPEED, BASE_LEVEL = 2000.0, 50.0
STEP_S, HORIZON_S = 60.0, 300.0
STEPS = int(HORIZON_S // STEP_S)

MODEL = """
domain:
  id: fedback
  name: A coupling that hears back
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      # declared; `seed_mode: projected` will not pick a model.
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         dynamics: {model: trend}}
    Tank: [{name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  relationship_rules:
    - {type: feeds, source_type: Pump, target_type: Tank,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: speed_rpm, to: level_pct, gain: %(gain)s%(sigma)s,
                    source: datasheet}}
"""


def _session(tmp_path, name, sigma=f", gain_sigma: {SIGMA}"):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL % {"gain": GAIN, "sigma": sigma})
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": BASE_SPEED})
    session.add_entity("tank1", "Tank", {"level_pct": BASE_LEVEL})
    session.add_relationship("pump1", "feeds", "tank1")
    now = api.now_utc()
    # Only the SOURCE has history, and it carries scatter: a noiseless line
    # is degenerate to fit and the projector refuses it by name.
    rng = random.Random(4)
    for k in range(24):
        session.add_observations(
            "pump1", "speed_rpm",
            [(now - timedelta(seconds=STEP_S * (24 - k)),
              BASE_SPEED + 50.0 * k + rng.gauss(0.0, 8.0))])
    return session


def _declared(session):
    return api.model_describe(session).to_dict()[
        "model"]["transitions"]["declared"][0]


def _forecast_then_observe(session, readings):
    simulation = api.rollout(session, horizon_s=HORIZON_S, step_s=STEP_S,
                             seed_mode="projected", file_predictions=True
                             ).to_dict()["simulation"]
    t0 = api.now_utc()
    for index, value in enumerate(readings, start=1):
        session.add_observations(
            "tank1", "level_pct",
            [(t0 + timedelta(seconds=STEP_S * index), value)])
    with api.as_of(t0 + timedelta(seconds=HORIZON_S * 4)):
        api.check(session)
    return simulation


class TestTheCouplingHearsBack:

    def test_nothing_graded_reports_a_zero_not_an_absence(self, tmp_path):
        """An omitted entry would read as `no problem found`."""
        record = _declared(_session(tmp_path, "fresh"))["projections"]
        assert record["graded"] == 0
        assert record["confirm_rate"] is None

    def test_a_contradicted_coupling_says_so(self, tmp_path):
        session = _session(tmp_path, "wrong")
        _forecast_then_observe(session, [9_999.0] * STEPS)
        record = _declared(session)["projections"]
        assert record["graded"] == STEPS
        assert record["falsified"] == STEPS
        assert record["confirm_rate"] == pytest.approx(0.0)

    def test_a_confirmed_coupling_says_so(self, tmp_path):
        peek = _session(tmp_path, "peek")
        projected = api.rollout(
            peek, horizon_s=HORIZON_S, step_s=STEP_S, seed_mode="projected"
        ).to_dict()["simulation"]["per_step"][0]["values"]["tank1"]["level_pct"]
        session = _session(tmp_path, "right")
        _forecast_then_observe(session, [projected] * STEPS)
        record = _declared(session)["projections"]
        assert record["confirm_rate"] == pytest.approx(1.0)
        assert record["falsified"] == 0

    def test_the_denominator_travels_with_the_rate(self, tmp_path):
        """A rate over five is not the statement a rate over five hundred is."""
        session = _session(tmp_path, "denominator")
        _forecast_then_observe(session, [9_999.0] * STEPS)
        record = _declared(session)["projections"]
        assert record["confirmed"] + record["falsified"] == record["graded"]


class TestTheRemedyIsAdviceAndNothingElse:

    def test_a_poor_rate_earns_a_remedy(self, tmp_path):
        session = _session(tmp_path, "remedy")
        _forecast_then_observe(session, [9_999.0] * STEPS)
        entry = _declared(session)
        assert "remedy" in entry
        assert str(STEPS) in entry["remedy"]

    def test_a_good_rate_earns_none(self, tmp_path):
        """Guard: advice that fires on every input is not advice."""
        peek = _session(tmp_path, "peek2")
        projected = api.rollout(
            peek, horizon_s=HORIZON_S, step_s=STEP_S, seed_mode="projected"
        ).to_dict()["simulation"]["per_step"][0]["values"]["tank1"]["level_pct"]
        session = _session(tmp_path, "noremedy")
        _forecast_then_observe(session, [projected] * STEPS)
        assert "remedy" not in _declared(session)

    def test_the_declared_gain_is_untouched(self, tmp_path):
        """Every forecast missed, and the model still says what it said."""
        session = _session(tmp_path, "untouched")
        _forecast_then_observe(session, [9_999.0] * STEPS)
        entry = _declared(session)
        assert entry["gain"] == pytest.approx(GAIN)
        assert entry["gain_sigma"] == pytest.approx(SIGMA)


class TestAFittedSpreadIsProposed:

    SPREAD_MODEL = """
domain:
  id: fitspread
  name: A spread fitted from readings
  entity_types: [P, T]
  relationship_types: [feeds]
  indicators:
    P: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    T: [{name: w, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  relationship_rules:
    - {type: feeds, source_type: P, target_type: T,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: v, to: w, gain: 2.0%(sigma)s, source: datasheet}}
"""

    def _fitted(self, tmp_path, name, sigma="", noise=0.05):
        path = tmp_path / f"{name}.yaml"
        path.write_text(self.SPREAD_MODEL % {"sigma": sigma})
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("p1", "P", {"v": 1.0})
        session.add_entity("t1", "T", {"w": 10.0})
        session.add_relationship("p1", "feeds", "t1")
        rng = random.Random(3)
        v, now = 1.0, api.now_utc()
        for k in range(300):
            v += rng.uniform(-1.0, 1.0)
            w = 10.0 + 2.0 * (v - 1.0) + rng.gauss(0.0, noise)
            when = now - timedelta(seconds=60 * (300 - k))
            session.add_observations("p1", "v", [(when, v)])
            session.add_observations("t1", "w", [(when, w)])
        proposed = api.model_describe(session).to_dict()[
            "model"]["proposed_transitions"]
        return session, proposed["fitted"][0]

    def test_a_spread_is_proposed_beside_the_gain(self, tmp_path):
        _, fitted = self._fitted(tmp_path, "prop")
        assert fitted["gain_sigma"] > 0.0

    def test_noisier_readings_propose_a_wider_spread(self, tmp_path):
        """The property that makes it a measurement rather than a constant."""
        _, tight = self._fitted(tmp_path, "tight", noise=0.05)
        _, loose = self._fitted(tmp_path, "loose", noise=1.0)
        assert loose["gain_sigma"] > tight["gain_sigma"] * 5, (
            f"twenty times the noise proposed {loose['gain_sigma']} against "
            f"{tight['gain_sigma']}; a spread that does not widen with the "
            f"scatter is not reading the data")

    def test_the_model_can_ask_for_one(self, tmp_path):
        _, asked = self._fitted(tmp_path, "asked", sigma=", gain_sigma: estimate")
        assert asked["gain_sigma_requested"] is True
        _, unasked = self._fitted(tmp_path, "unasked")
        assert unasked["gain_sigma_requested"] is False

    def test_asking_for_one_adopts_nothing(self, tmp_path):
        """`gain_sigma: estimate` is a question, and the answer is a proposal.

        The value must carry NO interval until a number is written into the
        model -- the same contract `gain: estimate` keeps, where the pair is
        declared and the magnitude is withheld.
        """
        session, _ = self._fitted(tmp_path, "unadopted",
                                  sigma=", gain_sigma: estimate")
        values = api.traverse(session, ["p1"], value_mode="hypothetical",
                              overrides={"p1": {"v": 6.0}}
                              ).to_dict()["simulation"]["values"]
        assert "sigma" not in values["t1"]["w"], (
            "a spread nobody has adopted became an interval a reader would "
            "act on")
