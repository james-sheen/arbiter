"""The shadow check: a forecast can be incoherent before it is wrong.

A FORECAST NAV THAT DOES NOT EQUAL THE SUM OF THE FORECAST HOLDINGS needs no
observation to be refuted, and calibration will never mention it. A model can
be beautifully calibrated on every indicator taken alone and still predict a
world that cannot exist -- so the eight axioms run a second time, over the
forecast rather than over the present.

THE SAME RULES, NOT A SECOND SET. The shadow entities go through
`reasoner.detect`, so every product of Path A applies again: the roles, the
grid, the ordering, cross-entity conservation, derived indicators. A separate
validator would be a second copy of the model's meaning and would drift from it
the first time an axiom changed.

WHAT P(BREACH) REFUSES TO INVENT. A producer sending `q05/q50/q95` has said
nothing about the shape past those levels. A threshold beyond `q95` supports
*at most 0.05* and no more; that settles a reporting line of 0.1 and settles
NOTHING at 0.01. The third state -- cannot tell -- is the reason the bound is
carried at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession
from arbiter_engine.forecast import ingest_forecasts, run_shadow_check
from arbiter_engine.forecast.shadow import (
    AT_LEAST, AT_MOST, EXACT, SHADOW_PREFIX, breach_probability,
    shadow_entities)

T0 = datetime(2026, 9, 17, 10, 0)
ISSUED = T0 - timedelta(minutes=30)

BOOK = {"domain": {
    "id": "d", "name": "d", "entity_types": ["Book"],
    "indicators": {"Book": [
        {"name": "bid", "type": "NUMERIC", "axioms": ["CONSISTENCY"],
         "window": "1h", "consistency": {"ordered_below": "ask"}},
        {"name": "ask", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
         "window": "1h", "critical": 1e9},
        {"name": "volume", "type": "NUMERIC", "role": "count",
         "axioms": ["CONSISTENCY"], "window": "1h"}]}}}


def _session(model=BOOK, properties=None):
    session = EngineSession()
    session.load_model(model)
    session.add_entity("b1", "Book",
                       properties or {"bid": 10.0, "ask": 11.0, "volume": 5.0})
    return session


def _feed(session, **quantiles):
    records = [{"model_id": "m", "entity_id": "b1", "property": name,
                "horizon_s": 3600.0, "issued_at": ISSUED, "quantiles": q}
               for name, q in quantiles.items()]
    return ingest_forecasts(session, records, at=T0)


def _kinds(sub):
    return sorted(f.problem_type for f in sub.findings)


def _reasons(sub):
    return sorted(d.reason for d in sub.not_checked)


# --- the forecast judged by the model's own rules -----------------------------

def test_a_forecast_bid_above_a_forecast_ask_is_impossible():
    session = _session()
    _feed(session, bid={"q05": 30.0, "q50": 40.0, "q95": 50.0},
          ask={"q05": 15.0, "q50": 20.0, "q95": 25.0})
    assert "forecast_impossible_value" in _kinds(run_shadow_check(session))


def test_a_forecast_count_below_zero_is_impossible():
    session = _session()
    _feed(session, volume={"q05": -9.0, "q50": -5.0, "q95": -1.0})
    assert _kinds(run_shadow_check(session)) == ["forecast_impossible_value"]


def test_a_coherent_forecast_is_silent():
    """The discriminator. A check that fired on every forecast would be
    useless, and every test above would still pass."""
    session = _session()
    _feed(session, bid={"q05": 8.0, "q50": 10.0, "q95": 12.0},
          ask={"q05": 18.0, "q50": 20.0, "q95": 22.0},
          volume={"q05": 1.0, "q50": 5.0, "q95": 9.0})
    assert run_shadow_check(session).findings == []


def test_every_finding_says_it_is_about_a_forecast():
    """`your system is breaking` and `your prediction of your system is
    impossible` call for different people."""
    session = _session()
    _feed(session, bid={"q05": 30.0, "q50": 40.0, "q95": 50.0},
          ask={"q05": 15.0, "q50": 20.0, "q95": 25.0},
          volume={"q05": -9.0, "q50": -5.0, "q95": -1.0})
    sub = run_shadow_check(session)
    assert sub.findings
    for finding in sub.findings:
        assert finding.problem_type.startswith(SHADOW_PREFIX)


def test_the_present_is_not_judged_by_the_forecast():
    """The real entity keeps its own readings. A shadow run that wrote into
    the session would make a prediction indistinguishable from a measurement."""
    session = _session()
    _feed(session, bid={"q05": 30.0, "q50": 40.0, "q95": 50.0})
    run_shadow_check(session)
    assert session.entities["b1"].properties == {
        "bid": 10.0, "ask": 11.0, "volume": 5.0}


# --- what a shadow entity is made of ------------------------------------------

def test_a_shadow_entity_carries_the_medians():
    session = _session()
    _feed(session, bid={"q05": 8.0, "q50": 10.0, "q95": 12.0})
    shadows, _ = shadow_entities(session)
    assert [e.id for e in shadows] == ["b1"]
    assert shadows[0].properties == {"bid": 10.0}


def test_it_does_not_inherit_the_readings_nobody_forecast():
    """THE DECISION THAT MATTERS MOST HERE. Filling the gaps from reality lets
    a balance close because its unforecast side came from today -- reporting a
    forecast as coherent when half of it is not a forecast at all."""
    session = _session()
    _feed(session, bid={"q05": 30.0, "q50": 40.0, "q95": 50.0})
    shadows, _ = shadow_entities(session)
    assert "ask" not in shadows[0].properties
    assert "volume" not in shadows[0].properties


def test_a_partial_forecast_declines_rather_than_passing():
    """The other half of the rule above: with no forecast ask, the ordering
    cannot be checked, and the decline names what was missing."""
    session = _session()
    _feed(session, bid={"q05": 30.0, "q50": 40.0, "q95": 50.0})
    sub = run_shadow_check(session)
    assert "missing_property" in _reasons(sub)
    assert sub.findings == []


def test_the_shadow_entity_keeps_the_name_a_reader_knows():
    session = _session()
    _feed(session, bid={"q05": 8.0, "q50": 10.0, "q95": 12.0})
    shadows, _ = shadow_entities(session)
    assert shadows[0].name == session.entities["b1"].name
    assert shadows[0].type == "Book"


def test_a_forecast_with_no_median_cannot_make_a_shadow():
    """`q05` and `q95` alone is scoreable -- the ledger requires only those --
    and says nothing about the central case. Declined rather than filled from
    the middle of the interval, which would be the engine inventing a median."""
    session = _session()
    _feed(session, bid={"q05": 8.0, "q95": 12.0})
    shadows, declines = shadow_entities(session)
    assert shadows == []
    assert [d.reason for d in declines] == ["missing_property"]


def test_a_forecast_for_an_entity_the_session_lost_declines():
    session = _session()
    _feed(session, bid={"q05": 8.0, "q50": 10.0, "q95": 12.0})
    del session.entities["b1"]
    shadows, declines = shadow_entities(session)
    assert shadows == []
    assert [d.reason for d in declines] == ["precondition_unmet"]


def test_an_empty_ledger_produces_an_empty_sub_envelope_with_a_denominator():
    sub = run_shadow_check(_session())
    assert sub.checked["entities"] == 0
    assert sub.findings == []


def test_the_denominator_is_never_summed_with_the_axiom_one():
    """Forecast subjects and axiom evaluations are two questions. `invariants`
    is 0 here for the same reason every other discipline reports it so."""
    session = _session()
    _feed(session, bid={"q05": 8.0, "q50": 10.0, "q95": 12.0})
    sub = run_shadow_check(session)
    assert sub.checked["invariants"] == 0
    assert sub.checked["entities"] == 1
    assert sub.checked["properties"] == 1


# --- the temporal axioms, asked about a moment that has not arrived -----------

def test_a_temporal_axiom_declines_rather_than_reading_the_real_past():
    """Feeding the observed series under a forecast present would let
    STABILITY and HOMEOSTASIS answer about a series that is half prediction,
    and the answer would look exactly like a real one."""
    model = {"domain": {
        "id": "d", "name": "d", "entity_types": ["Book"], "indicators": {"Book": [
            {"name": "bid", "type": "NUMERIC", "axioms": ["HOMEOSTASIS"],
             "window": "1h"}]}}}
    session = _session(model, {"bid": 10.0})
    for index in range(40):
        session.history.add("b1", "bid", 10.0 + index,
                            timestamp=T0 - timedelta(minutes=40 - index))
    _feed(session, bid={"q05": 8.0, "q50": 10.0, "q95": 12.0})
    sub = run_shadow_check(session)
    assert sub.findings == []
    assert "insufficient_samples" in _reasons(sub)


def test_the_shadow_history_refuses_to_be_written_to():
    from arbiter_engine.forecast.shadow import _EmptyHistory
    with pytest.raises(RuntimeError, match="read-only"):
        _EmptyHistory().add("b1", "bid", 1.0)


# --- the probability, and the tail it was not given ---------------------------

QUANTILES = {"q05": 10.0, "q50": 20.0, "q95": 30.0}


@pytest.mark.parametrize("threshold,expected", [
    (15.0, 0.725), (20.0, 0.500), (25.0, 0.275)])
def test_a_line_inside_the_declared_range_is_interpolated(threshold, expected):
    probability = breach_probability(QUANTILES, threshold, lower=False)
    assert probability.bound == EXACT
    assert probability.value == pytest.approx(expected)


def test_a_line_beyond_the_declared_range_is_a_bound_not_a_number():
    """Saying 0.03 here would be choosing a tail shape the producer never
    sent -- the silent Gaussian assumption the contract refuses one file over."""
    probability = breach_probability(QUANTILES, 35.0, lower=False)
    assert probability.bound == AT_MOST
    # approx, because `1.0 - 0.95` is 0.050000000000000044 in binary. The
    # implementation does NOT round: a bound rounded to look tidy is invented
    # precision, and the evidence dict rounds only where it is reported.
    assert probability.value == pytest.approx(0.05)


def test_a_line_below_everything_declared_is_the_other_bound():
    probability = breach_probability(QUANTILES, 5.0, lower=False)
    assert probability.bound == AT_LEAST
    assert probability.value == pytest.approx(0.95)


def test_the_two_sides_are_not_the_same_question():
    """Conflating them reports the complement of the answer, which looks
    entirely plausible."""
    up = breach_probability(QUANTILES, 15.0, lower=False)
    down = breach_probability(QUANTILES, 15.0, lower=True)
    assert up.value == pytest.approx(1.0 - down.value)
    assert up.value != down.value


def test_a_bound_settles_a_line_it_can_settle():
    assert breach_probability(QUANTILES, 35.0, lower=False).decides(0.10) is False


def test_a_bound_refuses_a_line_it_cannot_settle():
    """AT MOST 0.05 and a line of 0.01: the truth might be 0.04 or 0.0001.
    Returning False would read as *checked, and fine*."""
    assert breach_probability(QUANTILES, 35.0, lower=False).decides(0.01) is None


def test_the_other_bound_also_refuses_a_line_it_cannot_settle():
    """The mirror of the test above, and it was missing: *at least 0.95* does
    not settle a line of 0.99. Only the AT_MOST side was covered, so a mutation
    turning this arm into a plain comparison passed every test in the file."""
    probability = breach_probability(QUANTILES, 5.0, lower=False)
    assert probability.bound == AT_LEAST
    assert probability.decides(0.90) is True
    assert probability.decides(0.99) is None


def test_an_exact_probability_always_decides():
    probability = breach_probability(QUANTILES, 15.0, lower=False)
    assert probability.decides(0.5) is True
    assert probability.decides(0.9) is False


def test_fewer_than_two_levels_says_nothing():
    assert breach_probability({"q50": 20.0}, 15.0, lower=False) is None


def test_the_levels_it_interpolated_between_travel_with_the_answer():
    """So a reader can see the arithmetic rather than take the number."""
    assert breach_probability(QUANTILES, 15.0, lower=False).between == (0.05, 0.5)
    assert breach_probability(QUANTILES, 35.0, lower=False).between == (0.95,)
    # BOTH SIDES. These are two objects built on two lines, and testing one
    # left the other free: a mutation emptying the lower side's `between`
    # passed, because every assertion here read the upper one.
    assert breach_probability(QUANTILES, 15.0, lower=True).between == (0.05, 0.5)
    assert breach_probability(QUANTILES, 35.0, lower=True).between == (0.95,)


# --- breach findings ----------------------------------------------------------

def _account(report_above=0.1, critical=100.0):
    indicator = {"name": "balance", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                 "window": "1h"}
    if critical is not None:
        indicator["critical"] = critical
    if report_above is not None:
        indicator["dynamics"] = {"model": "local_level",
                                 "report_above": report_above}
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Acct"],
        "indicators": {"Acct": [indicator]}}})
    session.add_entity("a1", "Acct", {"balance": 50.0})
    return session


def _forecast(session, q=(80.0, 95.0, 110.0)):
    ingest_forecasts(session, [{
        "model_id": "m", "entity_id": "a1", "property": "balance",
        "horizon_s": 3600.0, "issued_at": ISSUED,
        "quantiles": {"q05": q[0], "q50": q[1], "q95": q[2]}}], at=T0)
    return session


def test_a_likely_breach_is_reported_with_its_probability():
    sub = run_shadow_check(_forecast(_account()))
    assert _kinds(sub) == ["forecast_breach:balance"]
    assert sub.findings[0].evidence["report_above"] == 0.1
    assert sub.findings[0].evidence["model_id"] == "m"


def test_a_forecast_well_inside_its_line_is_silent():
    sub = run_shadow_check(_forecast(_account(), q=(10.0, 20.0, 30.0)))
    assert _kinds(sub) == []


def test_without_a_declared_line_the_probability_is_reported_and_nothing_is_invented():
    """Whether 0.2 is alarming is a property of the engagement. A constant
    here would be the engine deciding an answer from a number nobody
    published."""
    sub = run_shadow_check(_forecast(_account(report_above=None)))
    assert "no_report_probability" in _reasons(sub)
    decline = next(d for d in sub.not_checked
                   if d.reason == "no_report_probability")
    assert decline.evidence["p_breach"]["critical"] > 0


def test_a_line_in_the_undeclared_tail_declines_and_says_what_to_do():
    sub = run_shadow_check(_forecast(_account(report_above=0.001),
                                     q=(10.0, 20.0, 30.0)))
    decline = next(d for d in sub.not_checked if d.reason == "tail_not_declared")
    assert "send more quantile levels" in decline.detail
    assert sub.findings == []


def test_with_no_declared_line_at_all_there_is_nothing_to_breach():
    """ASSERTED ON THE BREACH ARM'S OWN DECLINE, not on the reason alone.
    BOUNDEDNESS declines `no_threshold` for the same indicator in the same
    run, so `"no_threshold" in reasons` was satisfied by a decline this test
    was not about -- and a mutation deleting the breach arm's check passed."""
    sub = run_shadow_check(_forecast(_account(critical=None)))
    mine = [d for d in sub.not_checked
            if d.reason == "no_threshold"
            and "would count as breaching it" in (d.detail or "")]
    assert len(mine) == 1
    assert mine[0].scope["indicator"] == "balance"
    assert sub.findings == []


def test_a_per_instance_bound_is_the_line_the_forecast_is_judged_against():
    """Reading the spec's literal would compare a forecast for one account to
    a limit belonging to the whole book."""
    session = _account()
    session.set_declared_thresholds("a1", "balance", critical=1000.0)
    sub = run_shadow_check(_forecast(session))
    assert sub.findings == []
    session_two = _account()
    assert run_shadow_check(_forecast(session_two)).findings
