"""A distributional forecast is recorded so that it can be SCORED, and the
scoring carries the denominator it was computed from.

The ledger already grades two apertures: an impact prediction against the
problem stream, and a value prediction against the observation stream. Both
answer *was it right*. Neither can answer *is this producer calibrated*, which
is the only question worth asking of a forecaster and needs a distribution
rather than a point.

What these tests pin, in order of how quietly each would otherwise fail:

- a rate reported without its count. ``coverage_90`` over four records and over
  four thousand are different statements, and the second is the only one worth
  acting on;
- ``None`` rather than ``0`` before anything is graded. A zero here reads as
  *perfectly calibrated* for a model that has never been looked at;
- a record with no stated interval, which ``coverage_90`` would silently skip
  while still counting in a figure it never contributed to;
- two quantile keys naming one level, which double-weights that level in the
  mean and cannot raise on its own;
- a silent channel graded as a miss. Not-looking is not evidence, and the
  existing ``ungradeable`` verdict is what says so.

The verdict on a single distribution record is deliberately weak: a
well-calibrated 90% interval is SUPPOSED to be missed one time in ten, so a
miss is not a finding and is not emitted as one.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.history.observation import InMemoryObservationHistory
from arbiter_engine.residual.predict_vs_mirror import (
    GRADE_CONFIRMED, GRADE_FALSIFIED, GRADE_UNGRADEABLE,
    PredictionLedger, pinball_loss, quantile_level,
)

AT = datetime(2026, 5, 1, 12, 0, 0)
HORIZON = 3600.0
BAND = {"q05": 100.0, "q50": 130.0, "q95": 160.0}


def _ledger_with(observed=None, quantiles=None, model_id="forecaster_v3",
                 horizon_s=HORIZON):
    ledger = PredictionLedger()
    ledger.record_distribution("unit_7", "level_pct",
                               dict(quantiles or BAND), horizon_s,
                               model_id, predicted_at=AT)
    history = InMemoryObservationHistory()
    if observed is not None:
        history.add("unit_7", "level_pct", observed,
                    timestamp=AT + timedelta(seconds=horizon_s))
    matured = AT + timedelta(seconds=horizon_s + ledger.grace_s + 1)
    ledger.grade_matured([], set(), now=matured, histories=[history])
    return ledger


# --- the quantile key rule --------------------------------------------------

def test_the_digits_after_q_are_the_fractional_part():
    assert quantile_level("q05") == 0.05
    assert quantile_level("q50") == 0.5
    assert quantile_level("q975") == 0.975


def test_a_degenerate_level_is_refused():
    """A 0th or 100th percentile is unbounded for anything the engine will be
    handed, so a number there is a placeholder rather than a forecast."""
    with pytest.raises(ValueError, match="not strictly in"):
        quantile_level("q0")


def test_a_key_that_is_not_a_quantile_is_refused():
    for key in ("median", "p95", "q", "qx5"):
        with pytest.raises(ValueError, match="not `q` followed by digits"):
            quantile_level(key)


def test_two_keys_naming_one_level_are_refused():
    """`q1`, `q10` and `q100` all read as 0.1. Two scores for one quantile
    double-weight it in the mean that becomes CRPS, and nothing about that
    raises on its own."""
    ledger = PredictionLedger()
    with pytest.raises(ValueError, match="two quantile keys name one level"):
        ledger.record_distribution("e", "p",
                                   {"q05": 1.0, "q10": 2.0, "q100": 2.0,
                                    "q95": 3.0}, HORIZON, "m")


# --- what a distribution record must carry ---------------------------------

def test_a_forecast_with_no_interval_is_refused():
    """The same argument that makes `tolerance` mandatory on a value
    prediction: the ledger never guesses resolution. A caller with only a
    median has a point prediction, and there is already an aperture for it."""
    ledger = PredictionLedger()
    with pytest.raises(ValueError, match="requires"):
        ledger.record_distribution("e", "p", {"q50": 1.0}, HORIZON, "m")


def test_non_monotone_quantiles_are_refused():
    """If the 95th sits below the 5th the producer has mislabelled its own
    output, and every score computed from it would be meaningless."""
    ledger = PredictionLedger()
    with pytest.raises(ValueError, match="not monotone"):
        ledger.record_distribution("e", "p", {"q05": 9.0, "q95": 1.0},
                                   HORIZON, "m")


def test_a_non_numeric_quantile_is_refused():
    ledger = PredictionLedger()
    with pytest.raises(ValueError, match="not a number"):
        ledger.record_distribution("e", "p", {"q05": "low", "q95": 3.0},
                                   HORIZON, "m")


# --- pinball ---------------------------------------------------------------

def test_pinball_is_zero_when_exact():
    assert pinball_loss(0.5, 10.0, 10.0) == 0.0


def test_pinball_punishes_a_high_low_quantile_nineteen_times_harder():
    """At the 5th percentile, an outcome BELOW the forecast means the forecast
    was not a 5th percentile. Symmetry here would let a producer win by
    forecasting the median everywhere."""
    too_high = pinball_loss(0.05, 10.0, 9.0)
    too_low = pinball_loss(0.05, 10.0, 11.0)
    assert too_high == pytest.approx(0.95)
    assert too_low == pytest.approx(0.05)
    assert too_high == pytest.approx(19 * too_low)


# --- grading ---------------------------------------------------------------

def test_an_outcome_inside_the_interval_confirms():
    ledger = _ledger_with(observed=131.0)
    record = ledger.records()[0]
    assert record.verdict == GRADE_CONFIRMED
    assert record.scores["covered_90"] is True


def test_an_outcome_outside_the_interval_falsifies():
    ledger = _ledger_with(observed=205.0)
    assert ledger.records()[0].verdict == GRADE_FALSIFIED
    assert ledger.records()[0].scores["covered_90"] is False


def test_a_miss_is_not_emitted_as_a_finding():
    """A well-calibrated 90% interval is supposed to be missed one time in
    ten. Emitting each miss would make a correct forecaster look broken."""
    ledger = PredictionLedger()
    ledger.record_distribution("unit_7", "level_pct", dict(BAND),
                               HORIZON, "forecaster_v3", predicted_at=AT)
    history = InMemoryObservationHistory()
    history.add("unit_7", "level_pct", 900.0,
                timestamp=AT + timedelta(seconds=HORIZON))
    emissions = ledger.grade_matured(
        [], set(), now=AT + timedelta(seconds=HORIZON + 120),
        histories=[history])
    assert emissions == []
    assert ledger.records()[0].verdict == GRADE_FALSIFIED


def test_a_silent_channel_is_ungradeable_rather_than_a_miss():
    ledger = _ledger_with(observed=None)
    assert ledger.records()[0].verdict == GRADE_UNGRADEABLE
    assert ledger.records()[0].scores is None


def test_an_open_window_stays_pending():
    """A distribution stated for a horizon is not scoreable early."""
    ledger = PredictionLedger()
    ledger.record_distribution("unit_7", "level_pct", dict(BAND),
                               HORIZON, "forecaster_v3", predicted_at=AT)
    history = InMemoryObservationHistory()
    history.add("unit_7", "level_pct", 131.0, timestamp=AT)
    ledger.grade_matured([], set(), now=AT + timedelta(seconds=60),
                         histories=[history])
    assert ledger.records()[0].verdict is None
    assert len(ledger.pending()) == 1


def test_the_scores_name_every_level_supplied():
    ledger = _ledger_with(observed=131.0)
    scores = ledger.records()[0].scores
    assert set(scores["pinball"]) == set(BAND)
    assert scores["crps_approx"] == pytest.approx(
        2 * scores["pinball_mean"], rel=1e-9)


# --- calibration ------------------------------------------------------------

def test_nothing_scored_reports_none_and_not_zero():
    """A zero would read as perfectly calibrated for a model nobody has
    graded. The count beside it is the honest zero."""
    calibration = PredictionLedger().calibration()
    assert calibration["coverage_90"] is None
    assert calibration["coverage_90_n"] == 0
    assert calibration["pinball"] is None
    assert calibration["crps_approx"] is None


def test_every_rate_carries_the_count_it_was_computed_from():
    calibration = _ledger_with(observed=131.0).calibration()
    assert calibration["coverage_90"] == 1.0
    assert calibration["coverage_90_n"] == 1
    assert calibration["pinball_n"] == 1


def test_coverage_is_the_rate_across_records():
    ledger = PredictionLedger()
    history = InMemoryObservationHistory()
    for i, observed in enumerate([131.0, 131.0, 131.0, 900.0]):
        ledger.record_distribution(f"unit_{i}", "level_pct", dict(BAND),
                                   HORIZON, "forecaster_v3", predicted_at=AT)
        history.add(f"unit_{i}", "level_pct", observed,
                    timestamp=AT + timedelta(seconds=HORIZON))
    ledger.grade_matured([], set(), now=AT + timedelta(seconds=HORIZON + 120),
                         histories=[history])
    calibration = ledger.calibration()
    assert calibration["coverage_90"] == 0.75
    assert calibration["coverage_90_n"] == 4


def test_the_strata_separate_the_producers():
    """The reason `model_id` is mandatory. A pooled score cannot say which
    model to stop using."""
    ledger = PredictionLedger()
    history = InMemoryObservationHistory()
    for model, observed in (("good", 131.0), ("bad", 900.0)):
        ledger.record_distribution(f"unit_{model}", "level_pct",
                                   dict(BAND), HORIZON, model, predicted_at=AT)
        history.add(f"unit_{model}", "level_pct", observed,
                    timestamp=AT + timedelta(seconds=HORIZON))
    ledger.grade_matured([], set(), now=AT + timedelta(seconds=HORIZON + 120),
                         histories=[history])
    by_model = ledger.calibration()["by_model"]
    assert by_model["good"]["coverage_90"] == 1.0
    assert by_model["bad"]["coverage_90"] == 0.0
    assert by_model["good"]["pinball"] < by_model["bad"]["pinball"]


def test_the_horizon_stratum_is_separate_from_the_model_stratum():
    """A model well calibrated at an hour and useless at a day is one number
    that describes neither."""
    ledger = PredictionLedger()
    history = InMemoryObservationHistory()
    for horizon in (3600.0, 86400.0):
        ledger.record_distribution(f"unit_{horizon:g}", "level_pct",
                                   dict(BAND), horizon, "m", predicted_at=AT)
        history.add(f"unit_{horizon:g}", "level_pct", 131.0,
                    timestamp=AT + timedelta(seconds=horizon))
    ledger.grade_matured([], set(), now=AT + timedelta(days=2),
                         histories=[history])
    by_horizon = ledger.calibration()["by_horizon"]
    assert set(by_horizon) == {"3600s", "86400s"}
    assert all(bucket["n"] == 1 for bucket in by_horizon.values())


def test_the_existing_calibration_keys_are_untouched():
    """Additive, because a consumer already reads these."""
    calibration = _ledger_with(observed=131.0).calibration()
    for key in ("recorded", "pending", "evicted_pending", "by_kind",
                "confirmed", "falsified", "ungradeable", "confirm_rate",
                "mean_predicted_probability", "brier"):
        assert key in calibration
    assert calibration["by_kind"]["distribution"]["confirmed"] == 1
