"""`forecast:` is a nested block, and nothing checked its keys.

The loader validates the keys an author types at the top of an indicator: a
`directon:` is reported `unknown_key` with a `did_you_mean`. One level down, the
`forecast:` block was stored whole and consumed by name -- `expected`, `models`
and `max_age` by the forecasts leg, `expected_from` by the monitor -- and any
other key the author typed was accepted and read by nothing.

WHAT THE AUTHOR SAW INSTEAD. A misspelled `expected_from` did not report an
unknown key. It reported `missing_property` on `forecasts_expected`, which sends
someone to look at their FEED for a figure whose absence was caused by their
model. The two keys most worth misspelling are the two that were added most
recently, which is the usual shape.

`dynamics:` is deliberately NOT checked this way: it carries a model's own
parameters, and which of those exist is the model's business, not the loader's.
"""
from __future__ import annotations

from arbiter_engine.api import EngineSession, model_describe


def _describe(forecast_block: dict) -> list:
    session = EngineSession()
    session.load_model({"domain": {
        "id": "book", "name": "book", "entity_types": ["Account"],
        "indicators": {"Account": [
            {"name": "margin_balance", "type": "NUMERIC",
             "axioms": ["BOUNDEDNESS"], "critical": 5000.0,
             "window": "1h", "lookback": "7d", "horizon": "1h",
             "forecast": forecast_block},
        ]}}})
    return model_describe(session).to_dict()["model"]["unread_fields"]


def _unknown(fields) -> dict:
    return {f["field"]: f.get("did_you_mean")
            for f in fields if f["reason"] == "unknown_key"}


class TestAMisspelledKeyIsReported:

    def test_the_two_newest_keys_are_caught_with_a_suggestion(self):
        fields = _describe({"expected": True, "expected_frm": ["garch_v3"],
                            "max_aeg": "15m"})
        assert _unknown(fields) == {
            "forecast.expected_frm": "expected_from",
            "forecast.max_aeg": "max_age",
        }

    def test_a_key_nothing_resembles_is_still_reported(self):
        """`did_you_mean` is None and the row still exists -- the report is
        *nothing reads this*, and a suggestion is a courtesy on top of it."""
        fields = _describe({"expected": True, "zzz_not_a_key": 1})
        assert _unknown(fields) == {"forecast.zzz_not_a_key": None}


class TestEveryRealKeyStaysSilent:

    def test_the_four_keys_the_engine_reads_are_not_reported(self):
        """The check measures the engine's own key set, so a fifth key added to
        the block without being added to that set would go red here rather than
        being reported to authors as a mistake."""
        fields = _describe({"expected": True, "models": ["garch_v3"],
                            "expected_from": ["garch_v3"], "max_age": "15m"})
        assert _unknown(fields) == {}

    def test_an_absent_block_reports_nothing(self):
        session = EngineSession()
        session.load_model({"domain": {
            "id": "b", "name": "b", "entity_types": ["A"],
            "indicators": {"A": [{"name": "x", "type": "NUMERIC",
                                  "axioms": ["BOUNDEDNESS"],
                                  "critical": 1.0}]}}})
        fields = model_describe(session).to_dict()["model"]["unread_fields"]
        assert _unknown(fields) == {}
