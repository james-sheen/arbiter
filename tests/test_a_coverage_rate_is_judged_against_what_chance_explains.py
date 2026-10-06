"""A coverage rate is judged against what chance explains at its own count.

The modelling guide declared `coverage_90` under HOMEOSTASIS with
`setpoint: 0.90, tolerance: 0.05`, and the one vertical that judges a forecaster
copied it. A rate is k of n graded forecasts, and with six or fewer it can only
be 1.0 or at most 0.833 -- both farther than 0.05 from 0.90 -- so every producer
warned on every early run however well calibrated it was: certainly up to six
graded, about 60% of the time at seven to ten, a quarter at twenty to thirty-six.
Measured through margin-book-audit, the third audit of a clean book exited 1 on
`homeostasis_setpoint:coverage_90` for producers at three and one graded.

The engine now publishes `coverage_90_band` beside the rate: the exact binomial
band at 95%, the smallest distance from 0.90 that a producer covering exactly
0.90 exceeds at most one time in twenty. The guide's example and the shipped
margin-book example take their tolerance from it.
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timedelta
from math import comb

import pytest
import yaml

from arbiter_engine.api import EngineSession, check
from arbiter_engine.clock import as_of
from arbiter_engine.forecast import ingest_forecasts, model_figures
from arbiter_engine.forecast.monitor import coverage_band

NOMINAL, ALPHA = 0.90, 0.05
T0 = datetime(2026, 9, 17, 10, 0)


def _rate(k, n):
    """The rate as the ledger publishes it."""
    return round(k / n, 6)


def _beyond(n, distance):
    """How often a producer covering exactly 0.90 lands farther than `distance`."""
    return sum(comb(n, k) * NOMINAL ** k * (1 - NOMINAL) ** (n - k)
               for k in range(n + 1) if abs(_rate(k, n) - NOMINAL) > distance)


# --- the band -------------------------------------------------------------------

@pytest.mark.parametrize("n", range(1, 151))
def test_a_calibrated_producer_warns_at_most_one_time_in_twenty(n):
    assert _beyond(n, coverage_band(n)) <= ALPHA


@pytest.mark.parametrize("n", range(1, 81))
def test_and_it_is_the_narrowest_band_that_does(n):
    """Any narrower and the claim fails: the next distance in breaches it."""
    band = coverage_band(n)
    narrower = [d for d in {abs(_rate(k, n) - NOMINAL) for k in range(n + 1)} if d < band]
    if narrower:
        assert _beyond(n, max(narrower)) > ALPHA


def test_one_graded_forecast_admits_every_rate_it_can_produce():
    """A single outcome cannot show miscalibration at 95%, and the band says so."""
    band = coverage_band(1)
    assert all(abs(rate - NOMINAL) <= band for rate in (0.0, 1.0))


def test_six_or_fewer_no_longer_warn_on_a_perfect_record():
    """The fixed 0.05 warned on 1.0 at every n up to six."""
    for n in range(1, 7):
        assert abs(1.0 - NOMINAL) <= coverage_band(n)
        assert abs(1.0 - NOMINAL) > 0.05


def test_no_graded_forecast_has_no_band():
    assert coverage_band(0) is None


def test_a_large_count_is_answered_without_overflow():
    band = coverage_band(4000)
    assert 0.005 < band < 0.02


# --- the figure ------------------------------------------------------------------

def _graded_session(graded=1):
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Acct"],
        "indicators": {"Acct": [{"name": "balance", "type": "NUMERIC",
                                 "axioms": ["BOUNDEDNESS"], "window": "1h",
                                 "critical": 1e9, "forecast": {"expected": True}}]}}})
    for index in range(graded):
        entity = f"a{index}"
        session.add_entity(entity, "Acct", {"balance": 50.0})
        ingest_forecasts(session, [{
            "model_id": "garch_v3", "entity_id": entity, "property": "balance",
            "horizon_s": 3600.0, "issued_at": T0 - timedelta(minutes=90),
            "quantiles": {"q05": 10.0, "q50": 11.0, "q95": 12.0}}], at=T0)
        session.history.add(entity, "balance", 11.0, timestamp=T0 - timedelta(minutes=30))
    with as_of(T0):
        session.ledger.grade_matured(problems=[], observed_entity_ids=set(session.entities),
                                     histories=[session.history])
    return session


def test_the_band_travels_with_the_rate():
    with as_of(T0):
        figures = model_figures(_graded_session(graded=3))["garch_v3"]
    assert figures["graded_n"] == 3.0 and figures["coverage_90"] == 1.0
    assert figures["coverage_90_band"] == coverage_band(3)


def test_a_model_never_graded_has_no_band_either():
    session = _graded_session(graded=0)
    session.add_entity("a0", "Acct", {"balance": 50.0})
    ingest_forecasts(session, [{
        "model_id": "garch_v3", "entity_id": "a0", "property": "balance",
        "horizon_s": 3600.0, "issued_at": T0 - timedelta(minutes=5),
        "quantiles": {"q05": 10.0, "q50": 11.0, "q95": 12.0}}], at=T0)
    with as_of(T0):
        figures = model_figures(session)["garch_v3"]
    assert "coverage_90" not in figures and "coverage_90_band" not in figures


# --- the declaration ---------------------------------------------------------------

def _examples_dir() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / "margin_book.yaml").is_file():
            return candidate
    raise AssertionError("no margin_book.yaml found in this tree")


def _guide() -> str:
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "MODELING.md",
                      here.parents[2] / "docs" / "publication" / "domain-model-spec.md"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError("no modelling guide found")


def _coverage_warnings(n, rate):
    """The shipped example's own declaration, judging one forecaster's figures."""
    model = yaml.safe_load((_examples_dir() / "margin_book.yaml").read_text(encoding="utf-8"))
    session = EngineSession()
    session.load_model(model)
    session.add_entity("garch_v3", "ForecastModel", {
        "coverage_90": rate, "coverage_90_band": coverage_band(n), "graded_n": float(n)})
    return [f["problem_type"] for f in check(session).to_dict()["findings"]
            if f["entity_id"] == "garch_v3" and "coverage_90" in f["problem_type"]]


@pytest.mark.parametrize("n, rate, warns", [
    (3, 1.0, False),            # a perfect record over three: chance, not evidence
    (1, 0.0, False),            # one miss: still chance
    (3, 0.0, True),             # none of three covered: evidence
    (100, 0.5, True),           # half of a hundred: evidence
    (100, 0.9, False),          # the claim, met
], ids=["perfect-at-3", "miss-at-1", "none-of-3", "half-of-100", "nominal-at-100"])
def test_the_shipped_example_warns_on_evidence_not_on_chance(n, rate, warns):
    assert bool(_coverage_warnings(n, rate)) is warns


def test_the_guide_and_the_example_take_the_tolerance_from_the_band():
    for text in (_guide(), (_examples_dir() / "margin_book.yaml").read_text(encoding="utf-8")):
        assert "from_property: coverage_90_band" in text
        assert "name: coverage_90_band" in text
    assert "homeostasis: {setpoint: 0.90, tolerance: 0.05}" not in _guide()
