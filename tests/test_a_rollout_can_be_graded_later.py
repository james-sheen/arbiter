"""A rollout that is a forecast is filed, matured and scored.

THE LOOP WAS OPEN AT BOTH ENDS. The durable ledger shipped in 0.2.3,
`grade_matured` already handled `kind == "value"`, and nothing ever filed one:
no rollout wrote a prediction and the learner read none back. So the engine
could project a value, judge it, and never find out whether it had been right
-- which is the one thing a world model is FOR.

TWO REFUSALS GUARD WHAT GETS FILED, and both are about honesty rather than
book-keeping.

A ROLLOUT UNDER ACTIONS IS A COUNTERFACTUAL. This engine never dispatches: a
rollout carrying actions reports `tier: 3` and stops. So it cannot know the
actions were taken, and grading *what would have happened if we throttled the
pump* against a world where nobody throttled it would fill the ledger with
falsified records that say nothing about the model -- while the calibration
figure read off that ledger is the number meant to say whether this engine's
projections can be trusted at all. Poisoning it with counterfactuals is worse
than filing nothing.

A POINT PREDICTION WITHOUT A RESOLUTION IS NOT FALSIFIABLE. The ledger demands
a tolerance and refuses to guess one; so does this. The resolution comes from
the author's own declared `gain_sigma:`, which is the same rule
applies to a floor: a number that decides whether something counts as wrong is
a specification, and one nobody wrote down is an assumption with a decimal
point. Values with no declared spread are COUNTED and declined by name.
"""
from __future__ import annotations

import random
from datetime import timedelta

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance

GAIN, SIGMA = 0.02, 0.002
BASE_SPEED, BASE_LEVEL = 2000.0, 50.0
STEP_S, HORIZON_S = 60.0, 300.0
STEPS = int(HORIZON_S // STEP_S)

MODEL = """
domain:
  id: gradeable
  name: A forecast this engine can be graded on
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      # DECLARED, because `seed_mode: projected` now refuses to
      # choose a model on the author's behalf. This fixture used to be
      # seeded by a curve fit nobody asked for, which is the disagreement
      # between the two projection paths that closed.
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         dynamics: {model: trend}}
    Tank: [{name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  relationship_rules:
    - {type: feeds, source_type: Pump, target_type: Tank,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: speed_rpm, to: level_pct, gain: %(gain)s%(sigma)s,
                    source: datasheet}}
  action_templates:
    - name: throttle_pump
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm}
      effect: set
      settle_s: 0
      source: runbook
"""


def _session(tmp_path, name, sigma=f", gain_sigma: {SIGMA}", history=True):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL % {"gain": GAIN, "sigma": sigma})
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": BASE_SPEED})
    session.add_entity("tank1", "Tank", {"level_pct": BASE_LEVEL})
    session.add_relationship("pump1", "feeds", "tank1")
    if history:
        # ONLY THE SOURCE. The tank's value must come from the declared
        # transition, because a value the projection seeded directly is the
        # `project` verb's prediction to file, not this one's.
        now = api.now_utc()
        # A RAMP WITH SCATTER ON IT. A perfectly noiseless straight line is
        # degenerate to fit -- the trend projector refuses it
        # `covariance_unbounded`, correctly -- and no real series is one. The
        # jitter is deterministic so the fixture stays reproducible.
        rng = random.Random(4)
        for k in range(24):
            session.add_observations(
                "pump1", "speed_rpm",
                [(now - timedelta(seconds=STEP_S * (24 - k)),
                  BASE_SPEED + 50.0 * k + rng.gauss(0.0, 8.0))])
    return session


def _forecast(session, **kw):
    kw.setdefault("horizon_s", HORIZON_S)
    kw.setdefault("step_s", STEP_S)
    kw.setdefault("seed_mode", "projected")
    kw.setdefault("file_predictions", True)
    return api.rollout(session, **kw).to_dict()["simulation"]


def _reasons(simulation):
    return {d["reason"] for d in simulation["not_checked"]}


class TestAForecastIsFiled:

    def test_one_prediction_per_step(self, tmp_path):
        session = _session(tmp_path, "filed")
        simulation = _forecast(session)
        assert simulation["checked"]["predictions_filed"] == STEPS

    def test_the_ledger_holds_them_as_value_predictions(self, tmp_path):
        session = _session(tmp_path, "held")
        _forecast(session)
        by_kind = session.ledger.calibration()["by_kind"]
        assert by_kind["value"]["pending"] == STEPS

    def test_the_tolerance_is_the_declared_band(self, tmp_path):
        """Not invented here: 1.96 sigma, from the spread the author declared."""
        session = _session(tmp_path, "tolerance")
        simulation = _forecast(session)
        spread = simulation["per_step"][0]["sigma"]["tank1"]["level_pct"]
        pending = session.ledger.pending()
        assert pending
        assert pending[0].tolerance == pytest.approx(1.96 * spread, rel=1e-6)

    def test_the_calibration_figure_is_surfaced(self, tmp_path):
        simulation = _forecast(_session(tmp_path, "surfaced"))
        assert "calibration" in simulation
        assert simulation["calibration"]["recorded"] == STEPS


class TestACounterfactualIsNotFiled:

    def test_a_rollout_under_actions_files_nothing(self, tmp_path):
        session = _session(tmp_path, "cf")
        simulation = _forecast(
            session,
            actions=[ActionInstance("throttle_pump", "pump1",
                                    {"speed_rpm": 3000.0}, 0.0)])
        assert simulation["checked"]["predictions_filed"] == 0
        assert "counterfactual_not_a_prediction" in _reasons(simulation)

    def test_the_ledger_stays_empty(self, tmp_path):
        session = _session(tmp_path, "cf2")
        _forecast(session,
                  actions=[ActionInstance("throttle_pump", "pump1",
                                          {"speed_rpm": 3000.0}, 0.0)])
        assert session.ledger.calibration()["recorded"] == 0, (
            "a world nobody brought about must not score the model")


class TestAValueWithNoDeclaredWindowIsNotFiled:

    def test_it_is_counted_and_declined_by_name(self, tmp_path):
        """Nothing uncertain anywhere: no `gain_sigma:`, and a current seed
        rather than a forecast, so no spread reaches any value.

        this used to be constructed by dropping `gain_sigma:` alone.
        That stopped working, and the reason is the fix: a PROJECTED seed
        carries its own forecast band now, and a transition passes that band
        through its gain. So a declared `dynamics:` model gives the downstream
        value a tolerance even when the gain's own spread was never declared,
        and the only way left to have nothing filable is to have nothing
        uncertain.
        """
        session = _session(tmp_path, "notol", sigma="")
        simulation = api.rollout(session, horizon_s=HORIZON_S, step_s=STEP_S,
                                 seed_mode="current", file_predictions=True
                                 ).to_dict()["simulation"]
        assert simulation["checked"]["predictions_filed"] == 0
        assert simulation["checked"]["values_without_tolerance"] > 0
        assert "no_declared_tolerance" in _reasons(simulation)

    def test_a_projected_seed_alone_makes_a_value_filable(self, tmp_path):
        """The other half of the same fact, pinned so it cannot regress to a
        silent zero: the seed's own doubt is enough."""
        session = _session(tmp_path, "seedonly", sigma="")
        simulation = _forecast(session)
        assert simulation["checked"]["predictions_filed"] > 0, (
            "the source's forecast carries a band and the gain passes it "
            "through; the target is uncertain whether or not anyone declared "
            "a spread on the gain")

    def test_the_three_counts_partition_the_values(self, tmp_path):
        """Filed, unfilable, and NOT OURS TO PREDICT — together, every
        imagined value.

        The third bucket is the. A projected seed is the `project`
        verb's forecast and that verb files it; an action-set value is what
        the caller said they would do. Filing either here would score one
        forecast twice, or score the engine on a decision. Counted rather
        than skipped, so the numbers still add up to what the rollout saw.
        """
        session = _session(tmp_path, "partition")
        simulation = _forecast(session)
        seen = sum(len(props) for step in simulation["per_step"]
                   for props in step["values"].values())
        checked = simulation["checked"]
        assert (checked["predictions_filed"]
                + checked["values_without_tolerance"]
                + checked["values_driven"]) == seen
        assert checked["values_driven"] > 0, (
            "the projected source is an input; it should be counted as one")


class TestFilingIsOptIn:

    def test_nothing_is_filed_unless_asked(self, tmp_path):
        session = _session(tmp_path, "optin")
        simulation = _forecast(session, file_predictions=False)
        assert simulation["checked"]["predictions_filed"] == 0
        assert session.ledger.calibration()["recorded"] == 0
        assert "no_declared_tolerance" not in _reasons(simulation), (
            "a caller who did not ask to file is not owed a refusal to file")


class TestTheLoopCloses:
    """Predict, wait, read the world, score. The whole point."""

    def _file_then_observe(self, tmp_path, name, readings):
        session = _session(tmp_path, name)
        _forecast(session)
        t0 = api.now_utc()
        for index, value in enumerate(readings, start=1):
            session.add_observations(
                "tank1", "level_pct",
                [(t0 + timedelta(seconds=STEP_S * index), value)])
        with api.as_of(t0 + timedelta(seconds=HORIZON_S * 3)):
            api.check(session)
        return session

    def test_a_projection_the_world_agreed_with_is_confirmed(self, tmp_path):
        projected = _forecast(_session(tmp_path, "peek"))[
            "per_step"][0]["values"]["tank1"]["level_pct"]
        session = self._file_then_observe(
            tmp_path, "confirmed", [projected] * STEPS)
        calibration = session.ledger.calibration()
        assert calibration["by_kind"]["value"]["confirmed"] == STEPS
        assert calibration["by_kind"]["value"]["pending"] == 0

    def test_a_projection_the_world_contradicted_is_falsified(self, tmp_path):
        session = self._file_then_observe(
            tmp_path, "falsified", [10_000.0] * STEPS)
        calibration = session.ledger.calibration()
        assert calibration["by_kind"]["value"]["falsified"] == STEPS

    def test_a_brier_score_exists_once_anything_has_matured(self, tmp_path):
        """The figure that says whether this engine's projections are worth
        acting on. `None` before anything matured, a number after."""
        fresh = _session(tmp_path, "brier_fresh")
        _forecast(fresh)
        assert fresh.ledger.calibration()["brier"] is None

        projected = _forecast(_session(tmp_path, "brier_peek"))[
            "per_step"][0]["values"]["tank1"]["level_pct"]
        graded = self._file_then_observe(
            tmp_path, "brier", [projected] * STEPS)
        brier = graded.ledger.calibration()["brier"]
        assert brier is not None
        # Every record was filed at the declared 0.95 and every one confirmed.
        assert brier == pytest.approx((0.95 - 1.0) ** 2, abs=1e-9)
