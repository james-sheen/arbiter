"""A check that computed a probability and reached no verdict must SAY so.

THE LEG READ CLEAN WHILE THE ENGINE HAD REFUSED TWICE. `run_forecasts`
composed the shadow run, took its `findings`, and dropped everything else it
returned -- its `checked`, its declines, its whole sub-envelope. Through
`check` a consumer therefore never saw `no_threshold`, `no_report_probability`,
`tail_not_declared`, `undefined_for_values`, the `missing_property` for a
forecast with no median, or any axiom decline raised on a forecast at all.

Measured on a model declaring `forecast: {expected: true}` and no
`dynamics.report_above`: the shadow run declined `no_report_probability`, and
`check(...)["forecasts"]["not_checked"]` was the empty list. A reader saw
`expected: 1, received: 1` and no refusals -- which reads as *we compared the
forecast against its bound and found nothing wrong*, when nothing had been
compared at all. The changelog calls the bound arithmetic's whole point the
fact that "the undecidable case declines rather than answering no breach"; the
undecidable case was invisible on the only path most callers use.

WHY A SECOND KEY RATHER THAN ONE MERGED LEG. `subenvelope.py` argues it: a
vocabulary that accepts another discipline's reasons has stopped being evidence
about either. So the shadow envelope is mounted whole, beside the forecasts
leg, and the two closed sets stay closed.

THE TEST THAT EXISTED could not catch this. It called `run_shadow_check`
directly and asserted on what that returned -- so the composition was the one
thing never exercised, which is where the whole of the defect lived.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, check
from arbiter_engine.clock import as_of
from arbiter_engine.forecast import ingest_forecasts

T0 = datetime(2026, 9, 17, 9, 35)


def _session(*, report_above=None, quantiles=None, bound="lower_critical"):
    indicator = {
        "name": "margin_balance", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
        "window": "1h", "forecast": {"expected": True},
        bound: {"from_property": "margin_requirement"},
    }
    if report_above is not None:
        indicator["dynamics"] = {"model": "local_level",
                                 "report_above": report_above}
    session = EngineSession()
    session.load_model({"domain": {
        "id": "margin-book", "name": "book", "entity_types": ["Account"],
        "indicators": {"Account": [
            indicator,
            {"name": "margin_requirement", "type": "NUMERIC", "axioms": []},
        ]}}})
    session.add_entity("acct_01", "Account",
                       {"margin_balance": 1000.0, "margin_requirement": 900.0})
    return session


def _feed(session, quantiles=None):
    with as_of(T0):
        return ingest_forecasts(session, [{
            "model_id": "garch_v3", "entity_id": "acct_01",
            "property": "margin_balance", "horizon_s": 3600.0,
            "issued_at": T0 - timedelta(minutes=5),
            "quantiles": quantiles or {"q05": 850.0, "q50": 1000.0,
                                       "q95": 1120.0}}], at=T0)


def _envelope(session):
    with as_of(T0):
        return check(session).to_dict()


class TestTheShadowRunIsReportedAndNotOnlyConsulted:

    def test_the_envelope_carries_a_shadow_leg(self):
        session = _session(report_above=0.25)
        _feed(session)
        assert "shadow" in _envelope(session)

    def test_a_refusal_to_decide_is_visible_to_a_consumer(self):
        """The defect, stated as the thing a reader could not find out."""
        session = _session(report_above=None)      # no reporting line declared
        _feed(session)
        envelope = _envelope(session)
        reasons = [d["reason"] for d in envelope["shadow"]["not_checked"]]
        assert "no_report_probability" in reasons

    def test_the_shadow_leg_carries_its_own_denominator(self):
        session = _session(report_above=0.25)
        _feed(session)
        checked = _envelope(session)["shadow"]["checked"]
        assert checked["entities"] == 1
        # ONE, not two. The per-instance bound table rides on the shadow entity
        # as a sentinel property so the resolver can find it, and counting it
        # would claim an axiom looked at something that is not a reading.
        assert checked["properties"] == 1

    def test_the_two_vocabularies_stay_separate(self):
        """A shadow reason must not appear in the forecasts leg, and vice
        versa. Merging them is what stops a closed enum being evidence."""
        session = _session(report_above=None)
        _feed(session)
        envelope = _envelope(session)
        forecasts = {d["reason"] for d in envelope["forecasts"]["not_checked"]}
        assert "no_report_probability" not in forecasts

    def test_a_forecast_with_no_median_is_declined_where_a_reader_looks(self):
        session = _session(report_above=0.25)
        with as_of(T0):
            ingest_forecasts(session, [{
                "model_id": "garch_v3", "entity_id": "acct_01",
                "property": "margin_balance", "horizon_s": 3600.0,
                "issued_at": T0 - timedelta(minutes=5),
                "quantiles": {"q05": 850.0, "q95": 1120.0}}], at=T0)
        reasons = [d["reason"]
                   for d in _envelope(session)["shadow"]["not_checked"]]
        assert "missing_property" in reasons

    def test_the_findings_still_climb_into_the_forecasts_leg(self):
        """Unchanged on purpose -- this is additive. A reader written against
        the previous shape keeps working."""
        session = _session(report_above=0.01)
        _feed(session, quantiles={"q05": 700.0, "q50": 800.0, "q95": 890.0})
        envelope = _envelope(session)
        climbed = [f.get("problem_type") or f.get("type")
                   for f in envelope["forecasts"]["findings"]]
        assert any(str(name).startswith("forecast_") for name in climbed)
