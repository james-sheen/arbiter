"""The engine holds its own forecasts to the standard it holds a producer's.

`_grade_distribution_record` states the rule in its own docstring --
*a model at 100% coverage is badly calibrated in the other direction, having
bought its hit-rate with intervals too wide to act on* -- and that path is
reachable only by an outside producer. A rollout filed a POINT with a
tolerance derived from its own declared spread, so the only question the
ledger could answer about the engine's own forecasts was *did reality land
inside the band the engine chose*.

MEASURED, TWO DECLARATIONS AGAINST ONE REALITY. A tank that really scatters
with a standard deviation of 2.3, forecast by the same gain declared twice:
once with an honest `gain_sigma:` and once with one ten times too wide.

    declared spread accepted band confirm_rate brier
    honest +/- 4.5 0.95 0.0475
    ten times too wide +/- 45.0 1.00 0.0025

**The useless declaration won on every figure the engine reported.** Brier is
no second opinion here: every record is filed at one stated confidence, so
`brier` is a monotone restatement of `confirm_rate` and moves with it. An
author who does not know their gain and says so with a wide spread scores
better than one who measured it.

WHAT THIS FILE PINS. A record filed with a spread now carries that spread as
quantiles, and grading scores them -- pinball, a CRPS approximation and the
90% coverage, the same instruments applied to a producer. Those are proper:
pinball loss grows with the width of the interval whether or not it contained
the answer, so the too-wide declaration is finally visible as worse.

THE VERDICT IS UNCHANGED AND SO IS EVERY EXISTING FIGURE. The record is still
graded on the point and its declared tolerance, the distribution calibration
still covers producers only, and the new scores ride under their own leg with
their own denominator. Two bands at two levels sit on one record on purpose:
the 95% tolerance it is GRADED on, and the central 90% it is SCORED on.
"""
from __future__ import annotations

import random
from datetime import timedelta

import pytest

from arbiter_engine import api

GAIN = 0.02
BASE_SPEED, BASE_LEVEL = 2000.0, 50.0
STEP_S, HORIZON_S = 60.0, 1200.0
STEPS = int(HORIZON_S // STEP_S)

#: The world's real scatter about the projection, in percentage points. Chosen
#: so an honest declaration is a little tight and a ten-times-wider one is
#: absurd -- the regime the two-row table above measures.
TRUE_SD = 2.3

HONEST, TOO_WIDE = "0.002", "0.02"

MODEL = """
domain:
  id: own_spread
  name: A forecast the engine can be scored on
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         dynamics: {model: trend}}
    Tank: [{name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  relationship_rules:
    - {type: feeds, source_type: Pump, target_type: Tank,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: speed_rpm, to: level_pct, gain: %(gain)s,
                    gain_sigma: %(sigma)s, source: datasheet}}
"""


def _session(tmp_path, name, sigma=HONEST):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL % {"gain": GAIN, "sigma": sigma})
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": BASE_SPEED})
    session.add_entity("tank1", "Tank", {"level_pct": BASE_LEVEL})
    session.add_relationship("pump1", "feeds", "tank1")
    now = api.now_utc()
    rng = random.Random(4)
    for k in range(24):
        session.add_observations(
            "pump1", "speed_rpm",
            [(now - timedelta(seconds=STEP_S * (24 - k)),
              BASE_SPEED + 50.0 * k + rng.gauss(0.0, 8.0))])
    return session


def _forecast(session):
    return api.rollout(session, horizon_s=HORIZON_S, step_s=STEP_S,
                       seed_mode="projected", file_predictions=True
                       ).to_dict()["simulation"]


def _run(tmp_path, name, sigma, scatter=TRUE_SD):
    """Forecast, let the world happen, grade. Returns (simulation, session)."""
    session = _session(tmp_path, name, sigma)
    simulation = _forecast(session)
    projected = [step["values"]["tank1"]["level_pct"]
                 for step in simulation["per_step"]]
    t0 = api.now_utc()
    rng = random.Random(11)
    for index, value in enumerate(projected, start=1):
        session.add_observations(
            "tank1", "level_pct",
            [(t0 + timedelta(seconds=STEP_S * index),
              value + rng.gauss(0.0, scatter))])
    with api.as_of(t0 + timedelta(seconds=HORIZON_S * 3)):
        api.check(session)
    return simulation, session


class TestAFiledForecastCarriesItsSpread:

    def test_the_record_carries_quantiles(self, tmp_path):
        session = _session(tmp_path, "carries")
        _forecast(session)
        pending = session.ledger.pending()
        assert pending, "the fixture must file something to be about anything"
        assert pending[0].quantiles, (
            "a value filed from a declared spread states that spread; without "
            "it the ledger can only ask whether the engine's own band was hit")

    def test_the_quantiles_are_the_declared_gaussian(self, tmp_path):
        """Derived from the same sigma the tolerance is, so the two cannot
        disagree about how sure the engine said it was."""
        session = _session(tmp_path, "gaussian")
        simulation = _forecast(session)
        sigma = simulation["per_step"][0]["sigma"]["tank1"]["level_pct"]
        record = session.ledger.pending()[0]
        assert record.quantiles["q50"] == pytest.approx(record.value, rel=1e-9)
        half = 1.6448536269514722 * sigma
        assert record.quantiles["q95"] - record.quantiles["q50"] == pytest.approx(
            half, rel=1e-6)
        assert record.quantiles["q50"] - record.quantiles["q05"] == pytest.approx(
            half, rel=1e-6)

    def test_the_tolerance_is_still_the_95_band(self, tmp_path):
        """TWO LEVELS ON ONE RECORD, and neither replaces the other. The
        verdict is the 95% tolerance test it has always been; the quantiles
        are the central 90% the scores are computed on."""
        session = _session(tmp_path, "twolevels")
        simulation = _forecast(session)
        sigma = simulation["per_step"][0]["sigma"]["tank1"]["level_pct"]
        record = session.ledger.pending()[0]
        assert record.tolerance == pytest.approx(1.96 * sigma, rel=1e-6)

    def test_a_value_with_no_spread_files_no_quantiles(self, tmp_path):
        """The refusal is unchanged: nothing is invented where nothing was
        declared. A rollout with no uncertainty anywhere files nothing at all,
        so there is no record to carry a fabricated interval."""
        session = _session(tmp_path, "nospread")
        simulation = api.rollout(session, horizon_s=HORIZON_S, step_s=STEP_S,
                                 seed_mode="current", file_predictions=True
                                 ).to_dict()["simulation"]
        assert simulation["checked"]["predictions_filed"] == 0
        assert all(r.quantiles is None for r in session.ledger.records())


class TestAFiledForecastSaysWhoMadeIt:

    def test_it_names_the_engine_as_the_model(self, tmp_path):
        """A ledger holds more than one filer's records, and `by_coupling`
        cannot be read without knowing whose forecasts it covers."""
        session = _session(tmp_path, "whose")
        _forecast(session)
        assert session.ledger.pending()[0].model_id == "arbiter_engine:rollout"

    def test_it_is_stamped_as_not_a_producers_submission(self, tmp_path):
        """`source is None` is the producer predicate everything downstream
        reads. Nothing filters on it for a value record today, which is why
        stating it now is cheap: the fact is recoverable only at the instant
        it is filed."""
        from arbiter_engine.projection.projector import SOURCE_ENGINE
        session = _session(tmp_path, "notproducer")
        _forecast(session)
        assert session.ledger.pending()[0].source == SOURCE_ENGINE

    def test_the_forecaster_report_does_not_adopt_them(self, tmp_path):
        """The engine's own projections must not turn up in the report that
        monitors outside forecasters -- the yardstick on its own grid."""
        from arbiter_engine.forecast.monitor import model_figures
        session = _session(tmp_path, "notmonitored")
        _forecast(session)
        assert "arbiter_engine:rollout" not in model_figures(session)


class TestTheScoresArePresentForTheEnginesOwnForecasts:

    def test_own_projections_are_scored(self, tmp_path):
        _, session = _run(tmp_path, "scored", HONEST)
        own = session.ledger.calibration()["own_projections"]
        assert own["n"] == STEPS
        assert own["pinball"] is not None
        assert own["crps_approx"] is not None
        assert own["coverage_90"] is not None

    def test_nothing_scored_reports_none_not_zero(self, tmp_path):
        """A zero would read as perfectly calibrated for a model nobody has
        graded -- the rule every other aggregate in this ledger follows."""
        session = _session(tmp_path, "ungraded")
        _forecast(session)
        own = session.ledger.calibration()["own_projections"]
        assert own["n"] == 0
        assert own["pinball"] is None
        assert own["coverage_90"] is None

    def test_the_producer_figures_keep_their_population(self, tmp_path):
        """The engine's own scores do NOT enter `coverage_90`. That figure
        answers *which producer is worth keeping*, and a pooled score cannot.
        """
        _, session = _run(tmp_path, "population", HONEST)
        calibration = session.ledger.calibration()
        assert calibration["coverage_90"] is None
        assert calibration["coverage_90_n"] == 0
        assert calibration["own_projections"]["n"] > 0

    def test_the_scores_are_attributed_to_the_coupling(self, tmp_path):
        """WHICH declared gain's spread is dishonest. A producer's record has
        no coupling to name; the engine's own always does."""
        _, session = _run(tmp_path, "attributed", HONEST)
        by_coupling = session.ledger.calibration()["own_projections"]["by_coupling"]
        assert "feeds:speed_rpm->level_pct" in by_coupling
        assert by_coupling["feeds:speed_rpm->level_pct"]["n"] == STEPS


class TestAnOverWideDeclarationIsFinallyVisible:
    """The whole point. One reality, two declarations, and a figure that can
    tell them apart."""

    def test_confirm_rate_still_rewards_the_useless_declaration(self, tmp_path):
        """Pinned as the PREMISE, not as an acceptable outcome. If this ever
        stops being true the test below is measuring something else."""
        _, honest = _run(tmp_path, "cr_honest", HONEST)
        _, wide = _run(tmp_path, "cr_wide", TOO_WIDE)
        assert (wide.ledger.calibration()["confirm_rate"]
                > honest.ledger.calibration()["confirm_rate"])

    def test_the_crps_ranks_them_the_other_way(self, tmp_path):
        """Pinball loss grows with the width of the interval whether or not it
        contained the answer, so a band bought by declaring ignorance costs
        what it is worth."""
        _, honest = _run(tmp_path, "crps_honest", HONEST)
        _, wide = _run(tmp_path, "crps_wide", TOO_WIDE)
        assert (wide.ledger.calibration()["own_projections"]["crps_approx"]
                > honest.ledger.calibration()["own_projections"]["crps_approx"])

    def test_the_coverage_shows_the_band_was_never_approached(self, tmp_path):
        """An interval missed one time in ten is what a 90% interval is FOR.
        One that is never missed is the other failure."""
        _, wide = _run(tmp_path, "cov_wide", TOO_WIDE)
        assert wide.ledger.calibration()["own_projections"]["coverage_90"] == 1.0


class TestAHitRateIsReportedAgainstWhatItShouldBe:

    def test_calibration_states_the_expected_rate(self, tmp_path):
        """`confirm_rate: 1.0` reads as a perfect score. Beside a target of
        0.95 it reads as what it is: a band wider than the one declared."""
        _, session = _run(tmp_path, "expected", HONEST)
        calibration = session.ledger.calibration()
        assert calibration["expected_confirm_rate"] == pytest.approx(0.95)

    def test_the_coupling_leg_states_it_too(self, tmp_path):
        """The per-coupling report is where an author looks at one declared
        gain, so the target belongs there rather than only in the aggregate."""
        _, session = _run(tmp_path, "expected_coupling", HONEST)
        declared = api.model_describe(session).to_dict()[
            "model"]["transitions"]["declared"][0]
        assert declared["projections"]["expected_confirm_rate"] == pytest.approx(0.95)

    def test_it_is_none_before_anything_matures(self, tmp_path):
        session = _session(tmp_path, "expected_none")
        _forecast(session)
        assert session.ledger.calibration()["expected_confirm_rate"] is None
