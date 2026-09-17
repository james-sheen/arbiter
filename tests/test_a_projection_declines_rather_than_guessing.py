"""The projection runner: its denominator, the order of its refusals, and the
one number it will not invent.

The rule this whole verb is built around is that a breach PROBABILITY is not a
verdict. Whether a 20% chance of crossing a line is worth reporting is a
property of the engagement, not of the arithmetic -- so the engine computes the
probability, declines to rule on it, and asks the author for the line. A
constant in the code would be this engine deciding an answer from a number
nobody published, which is the thing its own floor rule forbids.

The denominator is `series_seen`, and the test that matters most is the one
showing findings plus declines does NOT equal it: a series that forecast
cleanly and crossed nothing appears in neither leg, and a caller reconstructing
the total from what it can see would be wrong on exactly those.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, project
from arbiter_engine.projection import run_projection

AT = datetime(2026, 5, 1, 12, 0, 0)
FITTABLE = {"model": "local_level", "q": 0.001, "r": 0.09}


def _model(indicator):
    return {"domain": {"id": "d", "name": "d", "entity_types": ["Unit"],
                       "indicators": {"Unit": [indicator]}}}


def _indicator(**over):
    spec = {"name": "level_pct", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
            "window": "6h", "critical": 95}
    spec.update(over)
    return spec


def _session(indicator=None, n=80, start=90.0, drift=0.0):
    session = EngineSession()
    session.load_model(_model(indicator if indicator is not None else _indicator()))
    session.add_entity("u1", "Unit")
    rng = random.Random(11)
    level, values = start, []
    for _ in range(n):
        level += rng.gauss(drift, 0.245)
        values.append(level + rng.gauss(0, 0.3))
    session.add_observations("u1", "level_pct", values, interval_seconds=60)
    return session


def _sub(session, horizon_s=3600.0):
    return run_projection(session, horizon_s)


def _reasons(sub):
    return [d.reason for d in sub.not_checked]


# --- the denominator --------------------------------------------------------

def test_every_declared_numeric_series_is_counted():
    sub = _sub(_session(_indicator(dynamics=FITTABLE, report_above=0.1)))
    assert sub.checked["series_seen"] == 1


def test_a_clean_forecast_appears_in_neither_leg():
    """The reason the denominator is reported at all. This series forecasts,
    crosses nothing, and produces no finding and no decline -- so a caller
    adding the two legs together would count zero series looked at."""
    session = _session(_indicator(critical=100000,
                                  dynamics=dict(FITTABLE, report_above=0.9)))
    sub = _sub(session)
    assert sub.findings == [] and sub.not_checked == []
    assert sub.checked["series_seen"] == 1
    assert sub.checked["forecasts_issued"] == 1


def test_the_observations_assimilated_are_counted_separately():
    sub = _sub(_session(_indicator(dynamics=dict(FITTABLE, report_above=0.1))))
    assert sub.checked["observations_assimilated"] == 80


def test_a_non_numeric_indicator_is_not_a_series():
    session = EngineSession()
    session.load_model(_model({"name": "feeds", "type": "RELATIONSHIP",
                               "axioms": ["CONNECTIVITY"], "target_type": "Sink",
                               "relation_type": "feeds", "min_cardinality": 1}))
    session.add_entity("u1", "Unit")
    assert _sub(session).checked["series_seen"] == 0


# --- the number it will not invent -----------------------------------------

def test_without_a_declared_probability_there_is_no_finding():
    sub = _sub(_session(_indicator(dynamics=FITTABLE)))
    assert sub.findings == []
    assert _reasons(sub) == ["no_report_probability"]


def test_the_probability_is_still_computed_and_reported():
    """Declining to rule is not declining to measure. The author gets the
    number they need in order to choose the line."""
    sub = _sub(_session(_indicator(dynamics=FITTABLE)))
    assert sub.not_checked[0].evidence["p_breach"]["critical"] > 0.5


def test_the_forecast_is_still_filed_for_grading():
    """Rule: every prediction gets graded. The calibration of a model is not
    conditional on whether it happened to alarm."""
    session = _session(_indicator(dynamics=FITTABLE))
    _sub(session)
    # TWO now, not one: the model's forecast and the random-walk reference it
    # is measured against, filed on the same series and the same horizon. The
    # count was one until the reference existed, and asserting the PAIR says
    # what a bare count cannot -- that the comparison is available at all.
    filed = {r.model_id for r in session.ledger.records()}
    assert filed == {"local_level:declared_model", "baseline_rw"}


def test_a_declared_probability_decides_and_the_finding_says_so():
    sub = _sub(_session(_indicator(dynamics=dict(FITTABLE, report_above=0.1))))
    assert len(sub.findings) == 1
    finding = sub.findings[0]
    assert finding.problem_type == "projected_breach:level_pct"
    assert finding.evidence["report_above"] == 0.1
    assert finding.evidence["crossed"] == "critical"


def test_the_same_forecast_under_a_higher_line_reports_nothing():
    """The line decides, and nothing else changed between these two runs."""
    high = _sub(_session(_indicator(dynamics=dict(FITTABLE, report_above=0.999))))
    assert high.findings == []
    low = _sub(_session(_indicator(dynamics=dict(FITTABLE, report_above=0.1))))
    assert len(low.findings) == 1


# --- the order of the refusals ---------------------------------------------

def test_a_missing_model_is_reported_before_a_short_series():
    """Both are true here. Reporting the sample floor first tells an author to
    collect more data, which will never produce a forecast while nothing has
    said what model to fit."""
    sub = _sub(_session(_indicator(), n=2))
    assert _reasons(sub) == ["model_missing"]


def test_a_short_series_is_reported_once_a_model_is_declared():
    sub = _sub(_session(_indicator(dynamics=FITTABLE), n=3))
    assert _reasons(sub) == ["insufficient_samples"]
    assert sub.not_checked[0].evidence["n"] == 3


def test_a_missing_model_asks_for_one():
    sub = _sub(_session(_indicator()))
    assert len(sub.questions) == 1
    assert sub.questions[0].gap.gap_type.value == "missing_dynamics"


def test_an_unknown_model_name_is_named_with_what_is_known():
    sub = _sub(_session(_indicator(dynamics={"model": "arima"})))
    assert _reasons(sub) == ["model_missing"]
    assert sub.not_checked[0].evidence["known"] == [
        "local_level", "random_walk", "trend"]


def test_a_series_with_no_declared_line_says_so():
    indicator = _indicator(dynamics=dict(FITTABLE, report_above=0.1))
    indicator.pop("critical")
    sub = _sub(_session(indicator))
    assert _reasons(sub) == ["no_threshold"]


def test_the_loader_supplies_a_window_so_yaml_never_reaches_that_refusal():
    """Recorded rather than assumed: an author who declares no `window` is
    fitted on the LOADER's default, not on one this verb chose. Worth knowing,
    because it is a default that decides how much history a forecast sees."""
    indicator = _indicator(dynamics=dict(FITTABLE, report_above=0.1))
    indicator.pop("window")
    session = _session(indicator)
    spec = session.model.indicators["Unit"][0]
    assert spec.lookback is None and spec.time_window is not None
    assert _reasons(_sub(session)) == []


def test_a_spec_with_no_span_at_all_is_refused():
    """The branch above guards the programmatic path, where `time_window` is
    genuinely optional and a caller can supply a spec the loader never saw."""
    session = _session(_indicator(dynamics=dict(FITTABLE, report_above=0.1)))
    spec = session.model.indicators["Unit"][0]
    object.__setattr__(spec, "time_window", None)
    assert _reasons(_sub(session)) == ["no_lookback"]


def test_the_lookback_falls_back_to_the_declared_window():
    sub = _sub(_session(_indicator(dynamics=dict(FITTABLE, report_above=0.1))))
    assert sub.checked["forecasts_issued"] == 1
    assert sub.checked["observations_assimilated"] == 80


def test_a_declared_lookback_narrows_what_is_assimilated():
    """`lookback` is a documented key, and until this test nothing proved it
    was READ -- a loader that dropped it silently left the whole suite green,
    which is how it was found. Eighty samples a minute apart span eighty
    minutes; a ten-minute lookback must see a fraction of them."""
    sub = _sub(_session(_indicator(dynamics=dict(FITTABLE, report_above=0.1),
                                   lookback="10m")))
    assimilated = sub.checked["observations_assimilated"]
    assert 0 < assimilated < 20, assimilated


# --- the horizon ------------------------------------------------------------

def test_the_horizon_argument_is_used_when_the_model_declares_none():
    session = _session(_indicator(dynamics=dict(FITTABLE, report_above=0.1)))
    _sub(session, horizon_s=1800.0)
    assert session.ledger.records()[0].horizon_s == 1800.0


def test_a_declared_horizon_wins_over_the_argument():
    session = _session(_indicator(dynamics=dict(FITTABLE, report_above=0.1),
                                  horizon="15m"))
    _sub(session, horizon_s=1800.0)
    assert session.ledger.records()[0].horizon_s == 900.0


# --- the verb ---------------------------------------------------------------

def test_the_verb_evaluates_no_invariants():
    """`attest`'s precedent: reporting the series it looked at as `invariants`
    would be the declared-versus-evaluated conflation that field was corrected
    to end."""
    envelope = project(_session(_indicator(dynamics=dict(FITTABLE,
                                                         report_above=0.1)))).to_dict()
    assert envelope["checked"]["invariants"] == 0
    assert envelope["projection"]["checked"]["series_seen"] == 1


def test_the_findings_leg_and_the_discipline_agree():
    """They are the same fact in two places, which is only safe while something
    compares them."""
    envelope = project(_session(_indicator(dynamics=dict(FITTABLE,
                                                         report_above=0.1)))).to_dict()
    assert len(envelope["findings"]) == len(envelope["projection"]["findings"]) == 1
    assert (envelope["findings"][0]["problem_type"]
            == envelope["projection"]["findings"][0]["problem_type"])


def test_the_questions_leg_and_the_discipline_agree():
    envelope = project(_session(_indicator())).to_dict()
    assert len(envelope["questions"]) == len(envelope["projection"]["questions"]) == 1


def test_a_projection_decline_cannot_ride_the_top_level_leg():
    """A top-level decline record REQUIRES one of eight axioms, and *this
    series has no declared dynamics* has none. The projection's declines are
    therefore reported once, in the discipline's own accounting."""
    envelope = project(_session(_indicator())).to_dict()
    assert envelope["not_checked"] == []
    assert len(envelope["projection"]["not_checked"]) == 1


def test_the_verb_refuses_without_a_model_or_entities():
    assert project(EngineSession()).to_dict()["meta"]["source"] == "unavailable"
    session = EngineSession()
    session.load_model(_model(_indicator()))
    assert project(session).to_dict()["meta"]["reason"] == "no entities supplied"
