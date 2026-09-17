"""`{from_property:}` is one declaration, and every reader of it must agree.

FOUR READERS HONOURED IT AND TWO DID NOT, inside one release. BOUNDEDNESS,
RESPONSIVENESS, HOMEOSTASIS and the breach arithmetic resolved a per-instance
bound correctly. `project` read `spec.critical_threshold` and its three
siblings -- the LITERAL slots -- which a `{from_property:}` declaration leaves
`None`, so every per-instance bound looked like no bound at all and every
entity declined `no_threshold` with the sentence *no declared line says what
would count as breaching it*. That sentence is false of a model that declares
one, and `examples/margin_book.yaml` declares exactly this shape: on the
flagship example `project` could never report a `projected_breach`.

THE SECOND READER was found by running the first fix, not by reading. The
shadow check calls `effective_thresholds`, which looked right -- but it calls
it against the SHADOW entity, which is synthetic and carries forecast medians
and nothing else. So the bound resolved for the breach arithmetic (which holds
the real entity) and failed for the axiom pass over the same forecast, and one
cycle produced both an answer and a refusal to answer about one declaration.

The fix carries the RESOLVED NUMBER onto the shadow entity rather than the
source property: an observed present value sitting on a forecast entity would
be judged by its own axioms and reported under the `forecast_` prefix as though
somebody had predicted it.

WHAT MAKES THIS A TEST AND NOT A RESTATEMENT: each case below is run twice,
once with a literal bound and once with the same number reached through
`{from_property:}`. The two must agree. A reader that resolves neither passes
a test that only checks the property form.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, check, project
from arbiter_engine.clock import as_of
from arbiter_engine.forecast import ingest_forecasts

T0 = datetime(2026, 9, 17, 9, 35)
FLOOR = 900.0


def _session(*, literal: bool):
    balance = {
        "name": "margin_balance", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
        "window": "1h", "lookback": "7d", "horizon": "1h",
        "forecast": {"expected": True},
        "dynamics": {"model": "local_level", "report_above": 0.25},
        "lower_critical": (FLOOR if literal
                           else {"from_property": "margin_requirement"}),
    }
    session = EngineSession()
    session.load_model({"domain": {
        "id": "margin-book", "name": "book", "entity_types": ["Account"],
        "indicators": {"Account": [
            balance,
            {"name": "margin_requirement", "type": "NUMERIC", "axioms": []},
        ]}}})
    session.add_entity("acct_01", "Account",
                       {"margin_balance": 1000.0, "margin_requirement": FLOOR})
    base = T0 - timedelta(days=1)
    session.add_observations("acct_01", "margin_balance", [
        (base + timedelta(minutes=7 * i), 1000.0 + (i % 11) * 3.0)
        for i in range(200)])
    return session


def _projection(session):
    with as_of(T0):
        payload = project(session, horizon_s=3600.0).to_dict()
    return payload.get("projection", payload)


def _shadow(session):
    with as_of(T0):
        ingest_forecasts(session, [{
            "model_id": "garch_v3", "entity_id": "acct_01",
            "property": "margin_balance", "horizon_s": 3600.0,
            "issued_at": T0 - timedelta(minutes=5),
            "quantiles": {"q05": 850.0, "q50": 1000.0, "q95": 1120.0}}], at=T0)
        return check(session).to_dict()["shadow"]


@pytest.mark.parametrize("literal", [True, False],
                         ids=["literal-bound", "from-property-bound"])
class TestBothFormsOfOneBoundReadTheSame:

    def test_project_does_not_claim_no_line_was_declared(self, literal):
        declines = _projection(_session(literal=literal))["not_checked"]
        offending = [d for d in declines
                     if d["reason"] == "no_threshold"
                     and d.get("property") == "margin_balance"]
        assert offending == []

    def test_the_shadow_axioms_do_not_claim_the_bound_is_missing(self, literal):
        declines = _shadow(_session(literal=literal))["not_checked"]
        offending = [d for d in declines if d["reason"] == "no_threshold"]
        assert offending == []


class TestAnUnresolvableBoundStillDeclines:
    """The other half, and the reason this is not just a looser check: a bound
    the author asked for and the engine could not find is an UNANSWERED check,
    and must not quietly become no check at all."""

    def _without_the_requirement(self):
        session = _session(literal=False)
        session.entities["acct_01"].properties.pop("margin_requirement")
        return session

    def test_project_declines_in_the_resolvers_own_words(self):
        declines = _projection(self._without_the_requirement())["not_checked"]
        offending = [d for d in declines if d["reason"] == "no_threshold"]
        assert offending, "a declared bound that cannot resolve must decline"
        assert "margin_requirement" in offending[0]["detail"], (
            "the decline must name the property it went looking for, not "
            "report that nothing was declared")

    def test_the_shadow_axioms_decline_too(self):
        declines = _shadow(self._without_the_requirement())["not_checked"]
        assert any(d["reason"] == "no_threshold" for d in declines)


class TestTheBoundIsRESOLVEDOntoTheShadowAndNotTheSourceProperty:

    def test_the_source_property_does_not_appear_on_a_forecast_entity(self):
        """It would be an observed present value wearing a prediction's
        clothes -- judged by its own axioms, reported under the `forecast_`
        prefix, and attributable to a forecaster who never sent it."""
        from arbiter_engine.forecast.shadow import shadow_entities

        session = _session(literal=False)
        with as_of(T0):
            ingest_forecasts(session, [{
                "model_id": "garch_v3", "entity_id": "acct_01",
                "property": "margin_balance", "horizon_s": 3600.0,
                "issued_at": T0 - timedelta(minutes=5),
                "quantiles": {"q05": 850.0, "q50": 1000.0,
                              "q95": 1120.0}}], at=T0)
            shadows, _declines = shadow_entities(session)
        assert len(shadows) == 1
        assert "margin_requirement" not in shadows[0].properties
