"""The contract an outside forecaster speaks, and what the engine refuses to infer.

THE ENGINE CARRIES NO MODEL, which is why this file is about parsing rather than
forecasting. A GARCH or a gradient-boosted tree is domain knowledge, and the
argument for keeping it outside is asymmetry: models change monthly, and the
contract for what a forecast looks like and how it is scored can stand for a
decade.

THREE SHAPES, because three are what producers emit, and two of them have to
become quantiles before anything can be scored. One of those two -- a mean and
a sigma -- requires a distribution the producer never named, and the engine
stamps its own assumption onto the record rather than scoring against a claim
nobody made. That stamp is the subject of half this file.

REJECTIONS ARE RETURNED. A batch of four hundred with one malformed record
files three hundred and ninety-nine and reports the one; an exception would
make one producer's bug cost another producer's data.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from arbiter_engine.forecast import (
    Forecast, REQUIRED_QUANTILES, parse_forecast)
from arbiter_engine.forecast.contract import (
    DERIVED_LEVELS, GAUSSIAN_STAMP)

NOW = datetime(2026, 9, 17, 10, 0)
ISSUED = NOW - timedelta(minutes=30)

BASE = {"model_id": "garch_v3", "entity_id": "acct_7",
        "property": "margin_balance", "horizon_s": 3600.0}


def _parse(**overrides):
    record = dict(BASE, issued_at=ISSUED)
    record.update(overrides)
    return parse_forecast(record, at=NOW)


def _ok(**overrides):
    forecast, rejected = _parse(**overrides)
    assert rejected is None, rejected
    return forecast


def _rejected(**overrides):
    forecast, rejected = _parse(**overrides)
    assert forecast is None, f"expected a rejection, got {forecast}"
    return rejected


# --- the shape a producer states itself ------------------------------------

def test_a_stated_distribution_is_taken_as_given():
    forecast = _ok(quantiles={"q05": 1.02e6, "q50": 1.31e6, "q95": 1.58e6},
                   assumptions=["stationary_vol_1d"], features_hash="9f3a")
    assert isinstance(forecast, Forecast)
    assert forecast.quantiles == {"q05": 1.02e6, "q50": 1.31e6, "q95": 1.58e6}
    assert forecast.assumptions == ["stationary_vol_1d"]
    assert forecast.features_hash == "9f3a"
    assert forecast.sample_count is None


def test_the_engine_adds_no_assumption_to_a_stated_distribution():
    """The producer named its own resolution, so there is nothing to stamp."""
    assert GAUSSIAN_STAMP not in _ok(
        quantiles={"q05": 1.0, "q95": 3.0}).assumptions


def test_extra_levels_are_kept():
    """They widen the score without changing what coverage means."""
    forecast = _ok(quantiles={"q05": 1.0, "q25": 2.0, "q50": 3.0,
                              "q75": 4.0, "q95": 5.0})
    assert sorted(forecast.quantiles) == ["q05", "q25", "q50", "q75", "q95"]


@pytest.mark.parametrize("quantiles", [
    {"q50": 1.0}, {"q05": 1.0}, {"q95": 1.0}, {"q05": 1.0, "q50": 2.0}])
def test_a_forecast_with_no_stated_interval_is_refused(quantiles):
    """An unscoreable record counted in a calibration figure is worse than no
    figure: `coverage_90` would silently skip it and the rate would describe a
    population nobody stated."""
    rejected = _rejected(quantiles=quantiles)
    assert rejected.reason == "malformed_forecast"
    assert "interval" in rejected.detail


def test_quantiles_that_cross_are_refused():
    rejected = _rejected(quantiles={"q05": 9.0, "q95": 1.0})
    assert "not monotone" in rejected.detail
    assert "mislabelled its own output" in rejected.detail


# --- samples ----------------------------------------------------------------

def test_samples_are_reduced_to_quantiles_without_assuming_a_shape():
    forecast = _ok(samples=list(range(1, 11)))
    assert sorted(forecast.quantiles) == [k for k, _ in DERIVED_LEVELS]
    assert forecast.quantiles["q50"] == 5.5
    assert GAUSSIAN_STAMP not in forecast.assumptions


def test_the_sample_count_travels_with_the_record():
    """A q05 from twenty samples and one from twenty thousand are different
    claims, and the quantiles alone present them identically."""
    assert _ok(samples=[1.0, 2.0]).sample_count == 2
    assert _ok(samples=[float(n) for n in range(2000)]).sample_count == 2000


def test_a_single_sample_is_refused():
    """Every level collapses to one number, coverage is 1.0 by construction,
    and the record would flatter its producer forever."""
    rejected = _rejected(samples=[42.0])
    assert "coverage of 1.0 by construction" in rejected.detail


def test_samples_that_are_not_numbers_are_refused():
    assert _rejected(samples=[1.0, "two", 3.0]).reason == "malformed_forecast"
    assert _rejected(samples=[]).reason == "malformed_forecast"
    assert _rejected(samples="1,2,3").reason == "malformed_forecast"


def test_reducing_samples_is_arithmetic_and_not_a_model():
    """The discriminator for the claim in the module docstring: the quantiles
    come out of the data sent, so a skewed sample set produces skewed
    quantiles rather than a symmetric interval around the mean."""
    skewed = [1.0] * 90 + [100.0] * 10
    forecast = _ok(samples=skewed)
    assert forecast.quantiles["q05"] == 1.0
    assert forecast.quantiles["q50"] == 1.0
    assert forecast.quantiles["q95"] > 50.0


# --- mean and sigma: the shape the ENGINE chooses ---------------------------

def test_a_mean_and_sigma_expand_under_a_normal_assumption():
    forecast = _ok(mean=100.0, sigma=10.0)
    assert forecast.quantiles["q50"] == 100.0
    assert forecast.quantiles["q05"] == pytest.approx(83.5514637, abs=1e-6)
    assert forecast.quantiles["q95"] == pytest.approx(116.4485363, abs=1e-6)


def test_the_engine_says_which_assumption_it_made():
    """THE POINT OF THIS ARM. The producer sent two numbers; normality is the
    engine's reading of them, and a score that turns on an assumption nobody
    recorded is what this project refuses everywhere else."""
    assert GAUSSIAN_STAMP in _ok(mean=1.0, sigma=1.0).assumptions


def test_the_stamp_joins_the_producer_assumptions_rather_than_replacing_them():
    forecast = _ok(mean=1.0, sigma=1.0, assumptions=["stationary_vol_1d"])
    assert forecast.assumptions == ["stationary_vol_1d", GAUSSIAN_STAMP]


def test_the_stamp_is_not_written_twice():
    forecast = _ok(mean=1.0, sigma=1.0, assumptions=[GAUSSIAN_STAMP])
    assert forecast.assumptions.count(GAUSSIAN_STAMP) == 1


def test_a_mean_with_no_sigma_is_refused():
    """A mean on its own states no interval, and the engine does not invent
    one -- the same rule that refuses a setpoint with no tolerance."""
    rejected = _rejected(mean=100.0)
    assert "does not invent one" in rejected.detail


def test_a_negative_sigma_is_refused():
    assert _rejected(mean=1.0, sigma=-1.0).reason == "malformed_forecast"


def test_a_zero_sigma_is_accepted_and_collapses_honestly():
    """Zero is a real statement -- this producer claims certainty -- and it is
    not the same as absent. The interval is a point and the score will say so."""
    forecast = _ok(mean=7.0, sigma=0.0)
    assert set(forecast.quantiles.values()) == {7.0}


# --- two shapes are two claims ----------------------------------------------

@pytest.mark.parametrize("pair", [
    {"quantiles": {"q05": 1.0, "q95": 2.0}, "samples": [1.0, 2.0]},
    {"quantiles": {"q05": 1.0, "q95": 2.0}, "mean": 1.5, "sigma": 0.5},
    {"samples": [1.0, 2.0], "mean": 1.5, "sigma": 0.5},
])
def test_a_record_stating_its_distribution_twice_is_refused(pair):
    """NOT a merge and not a precedence rule. Picking one silently would score
    the producer against a claim they may not have meant to make."""
    rejected = _rejected(**pair)
    assert "ONE way" in rejected.detail


def test_a_record_stating_no_distribution_is_refused():
    rejected = _rejected()
    assert "carries none of them" in rejected.detail


# --- identity and time -------------------------------------------------------

@pytest.mark.parametrize("field", ["model_id", "entity_id", "property"])
def test_the_three_identifying_fields_are_required(field):
    rejected = _rejected(quantiles={"q05": 1.0, "q95": 2.0}, **{field: ""})
    assert rejected.reason == "malformed_forecast"
    assert f"`{field}`" in rejected.detail


def test_a_rejection_names_what_it_could_identify():
    """A batch report of four hundred rows is unusable if the rows cannot be
    told apart. What was readable travels with the rejection."""
    rejected = _rejected(quantiles={"q05": 9.0, "q95": 1.0})
    assert rejected.to_dict()["entity_id"] == "acct_7"
    assert rejected.to_dict()["indicator"] == "margin_balance"
    assert rejected.to_dict()["model_id"] == "garch_v3"


@pytest.mark.parametrize("horizon", [0, -1, None, "soon", float("inf"),
                                     float("nan"), True])
def test_a_forecast_needs_a_horizon_to_be_graded_at(horizon):
    rejected = _rejected(quantiles={"q05": 1.0, "q95": 2.0}, horizon_s=horizon)
    assert rejected.reason == "malformed_forecast"


@pytest.mark.parametrize("issued", [
    "2026-09-17T09:30:00Z",
    "2026-09-17T09:30:00+00:00",
    datetime(2026, 9, 17, 9, 30),
    # DERIVED, not transcribed. The first version of this row read
    # 1789644600.0, which is 11:30 -- an hour after the present moment this
    # file declares, so the parser correctly refused it and the test failed
    # for a defect in its own fixture.
    datetime(2026, 9, 17, 9, 30, tzinfo=timezone.utc).timestamp(),
])
def test_the_issue_time_is_read_in_the_shapes_a_producer_sends(issued):
    forecast, rejected = parse_forecast(
        dict(BASE, issued_at=issued, quantiles={"q05": 1.0, "q95": 2.0}), at=NOW)
    assert rejected is None, rejected
    assert forecast.issued_at.tzinfo is None
    assert forecast.issued_at == datetime(2026, 9, 17, 9, 30)


def test_a_trailing_z_is_valid_iso_and_is_accepted():
    """`fromisoformat` did not take it before 3.11, and a producer writing UTC
    the obvious way must not be refused by an interpreter version."""
    forecast, rejected = parse_forecast(
        dict(BASE, issued_at="2026-09-17T09:30:00Z",
             quantiles={"q05": 1.0, "q95": 2.0}), at=NOW)
    assert rejected is None
    assert forecast.issued_at == datetime(2026, 9, 17, 9, 30)


def test_a_record_issued_after_the_present_moment_is_not_a_forecast():
    rejected = _rejected(quantiles={"q05": 1.0, "q95": 2.0},
                         issued_at=NOW + timedelta(seconds=1))
    assert "after the present moment" in rejected.detail


def test_the_present_moment_is_the_session_clock_not_wall_time():
    """So a replay judges a forecast against the replayed present. Without
    this, replaying last month refuses every record in it."""
    record = dict(BASE, issued_at=datetime(2026, 8, 1, 12, 0),
                  quantiles={"q05": 1.0, "q95": 2.0})
    forecast, rejected = parse_forecast(record, at=datetime(2026, 8, 1, 13, 0))
    assert rejected is None, rejected
    forecast, rejected = parse_forecast(record, at=datetime(2026, 8, 1, 11, 0))
    assert forecast is None


def test_an_unusable_issue_time_is_refused_rather_than_defaulted_to_now():
    """Defaulting would make a malformed record score as if it had been issued
    at the moment it was read, which is the most favourable possible reading."""
    rejected = _rejected(quantiles={"q05": 1.0, "q95": 2.0},
                         issued_at="last tuesday")
    assert "`issued_at`" in rejected.detail


# --- the shape of the thing itself -------------------------------------------

def test_a_record_that_is_not_a_mapping_is_refused_rather_than_raising():
    for raw in (None, 42, "a forecast", [1, 2, 3]):
        forecast, rejected = parse_forecast(raw, at=NOW)
        assert forecast is None and rejected.reason == "malformed_forecast"


def test_property_name_is_accepted_beside_property():
    forecast, rejected = parse_forecast(
        {"model_id": "m", "entity_id": "e", "property_name": "p",
         "horizon_s": 60, "issued_at": ISSUED,
         "quantiles": {"q05": 1.0, "q95": 2.0}}, at=NOW)
    assert rejected is None and forecast.property_name == "p"


def test_the_required_levels_are_one_list():
    assert REQUIRED_QUANTILES == ("q05", "q95")


def test_a_boolean_is_not_a_number_anywhere_it_matters():
    """`True` reads as 1.0 under a bare isinstance check, and a forecast of 1.0
    is a real forecast -- so the wrong reading is silent."""
    assert _rejected(quantiles={"q05": True, "q95": 2.0}).reason == \
        "malformed_forecast"
    assert _rejected(samples=[True, False]).reason == "malformed_forecast"
    assert _rejected(mean=True, sigma=1.0).reason == "malformed_forecast"
