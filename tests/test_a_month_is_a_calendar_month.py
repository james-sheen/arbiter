"""A month is a calendar month.

Since 0.2.23 months and years were refused by name, having no fixed
length, and the causal delay took seconds only. So an author on a monthly series
wrote days, and a month written as 30 days read the wrong month: measured on what
users installed (engine 0.2.33), a source over its bound in February only, driving
a finding on the March capture, was read on January's capture and screened when the
captures fell on the 1st or the 15th, and read correctly when they fell at month
end. The same declared number was right or wrong by the day of the month.

Since 0.2.34 months and years are calendar units, laid at the instant each reader
measures from, the day clamped to the month's last: back from now for `window`,
`lookback`, `timeout`, `homeostasis.must_return_within` and `forecast.max_age`, back
from the finding for a cause's delay, and forward from now for `horizon`. The
causal rule gains `propagation_delay:`, a duration, beside `propagation_delay_s:`;
both on one rule are refused by name. `align_tolerance:` keeps refusing months.

`1M` was one minute: the reader lower-cased it. A capital `M` is refused
outside ISO 8601. The RDF loader parsed durations its own way and dropped
`P30D` and its kind silently; it reads through the one reader now.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from arbiter_engine import api
from arbiter_engine.clock import (
    CalendarSpan, shift_months, span_back, span_seconds_forward)
from arbiter_engine.forecast import ingest_forecasts
from arbiter_engine.history.calendar import CalendarHistory
from arbiter_engine.history.observation import InMemoryObservationHistory
from arbiter_engine.ontology.domain_loader import read_duration
from arbiter_engine.ontology.loader import OntologyLoader

MONTH_CAPTURES = {"on the 1st": (1, 1, 1), "on the 15th": (15, 15, 15),
                  "at month end": (31, 28, 31)}


class TestTheReader:

    @pytest.mark.parametrize("written, months, fixed", [
        ("1mo", 1, timedelta(0)), ("1 month", 1, timedelta(0)),
        ("3 months", 3, timedelta(0)), ("P1M", 1, timedelta(0)),
        ("1y", 12, timedelta(0)), ("P1Y2M10D", 14, timedelta(days=10)),
        ("1mo 15d", 1, timedelta(days=15)), ("10y", 120, timedelta(0)),
        ("0.5y", 6, timedelta(0)),
    ])
    def test_months_and_years_are_read_as_calendar_months(self, written, months, fixed):
        value, problem = read_duration(written)
        assert problem is None
        assert (value.months, value.fixed, str(value)) == (months, fixed, written)

    @pytest.mark.parametrize("written, read", [
        ("4w", timedelta(days=28)), ("90d", timedelta(days=90)),
        ("1m", timedelta(minutes=1)), ("PT1M", timedelta(minutes=1)),
    ])
    def test_a_duration_naming_no_month_is_what_it_was(self, written, read):
        assert read_duration(written) == (read, None)

    @pytest.mark.parametrize("written", ["1M", "3M", "2M30D"])
    def test_a_capital_m_is_refused_and_both_meanings_offered(self, written):
        value, problem = read_duration(written)
        assert value is None and "`mo` for a month" in problem and "`min`" in problem

    @pytest.mark.parametrize("written", ["1.5 months", "P1.5M", "0.1y"])
    def test_a_fraction_of_a_month_is_refused(self, written):
        value, problem = read_duration(written)
        assert value is None and "fraction of a month" in problem


class TestTheCalendar:

    @pytest.mark.parametrize("instant, months, landed", [
        (datetime(2026, 3, 31), -1, datetime(2026, 2, 28)),
        (datetime(2024, 3, 31), -1, datetime(2024, 2, 29)),
        (datetime(2026, 1, 31), 1, datetime(2026, 2, 28)),
        (datetime(2026, 1, 15), -1, datetime(2025, 12, 15)),
        (datetime(2026, 12, 5), 2, datetime(2027, 2, 5)),
    ])
    def test_a_month_keeps_the_day_clamped_to_the_months_last(self, instant, months, landed):
        assert shift_months(instant, months) == landed

    def test_the_months_apply_before_the_fixed_part(self):
        span = CalendarSpan(1, timedelta(days=15), "1mo 15d")
        assert span_back(span, datetime(2026, 3, 31)) == datetime(2026, 2, 13)


def _month_starts(start_month, count, value=1.0):
    return [(datetime(2026, start_month + i, 1), value) for i in range(count)]


class TestAWindowOfMonths:

    @pytest.mark.parametrize("now", [datetime(2026, 3, 1), datetime(2026, 5, 1),
                                     datetime(2026, 7, 1)])
    def test_three_months_hold_three_monthly_captures_from_any_month(self, now):
        history = InMemoryObservationHistory()
        for ts, value in _month_starts(1, 7):
            history.add("u-1", "x", value, ts)
        with api.as_of(now):
            held = history.get_values("u-1", "x", read_duration("3 months")[0])
        assert len(held) == 3

    def test_ninety_days_do_not(self):
        """Measured beside it: ninety days hold three captures from March and
        four from May."""
        history = InMemoryObservationHistory()
        for ts, value in _month_starts(1, 7):
            history.add("u-1", "x", value, ts)
        counts = []
        for now in (datetime(2026, 3, 1), datetime(2026, 5, 1)):
            with api.as_of(now):
                counts.append(len(history.get_values("u-1", "x", timedelta(days=90))))
        assert counts == [3, 4]

    def test_a_month_under_a_session_calendar_is_a_month_on_the_wall_clock(self):
        span = read_duration("1 month")[0]
        assert CalendarHistory._wall_window(object.__new__(CalendarHistory), span) is span


REVIEW = """
domain:
  id: review_months
  name: review months
  entity_types: [Review]
  indicators:
    Review:
      - name: phase
        type: STATE
        axioms: [STABILITY]
        normal: [done]
        transient: [in_review]
        bad: [failed]
        timeout: {timeout}
"""


def _stuck_since(start, judged, timeout):
    session = api.EngineSession()
    session.load_model(REVIEW.format(timeout=timeout))
    session.add_entity("r-1", "Review", {"phase": "in_review"})
    session.add_observations("r-1", "phase", [(start, "in_review"), (judged, "in_review")])
    with api.as_of(judged):
        body = api.check(session).to_dict()
    body = body.get("check") or body
    return [f for f in body.get("findings") or []
            if str(f.get("problem_type", "")).startswith("transient_state_timeout")]


SECOND = timedelta(seconds=1)


class TestATimeoutOfMonths:
    """Past its timeout once the state began before the month laid back from
    now -- the measure a window takes. A state begun on 31 January has not
    lasted a month at the end of 28 February, a month back from then being 28
    January, and has on 1 March; one begun on the 15th has the second after
    15 February."""

    @pytest.mark.parametrize("start, last_within", [
        (datetime(2026, 1, 31), datetime(2026, 2, 28, 23, 59, 59)),
        (datetime(2026, 1, 15), datetime(2026, 2, 15)),
        (datetime(2024, 1, 31), datetime(2024, 2, 29, 23, 59, 59)),
    ])
    def test_a_state_is_past_a_month_once_it_began_before_the_month_back(
            self, start, last_within):
        assert _stuck_since(start, last_within, "1 month") == []
        assert len(_stuck_since(start, last_within + SECOND, "1 month")) == 1

    def test_three_months_and_a_year(self):
        start = datetime(2026, 1, 15)
        assert len(_stuck_since(start, datetime(2026, 4, 16), "3 months")) == 1
        assert _stuck_since(start, datetime(2026, 4, 16), "1y") == []


FORECAST = """
domain:
  id: monthly_forecast
  name: monthly forecast
  entity_types: [Node]
  indicators:
    Node:
      - {name: x, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 80, window: 1y,
         horizon: 1 month, dynamics: {model: random_walk}}
"""


def _horizon_s(now):
    """The seconds a forecast asked a month ahead of `now` was filed at."""
    with api.as_of(now):
        session = api.EngineSession()
        session.load_model(FORECAST)
        session.add_entity("n-1", "Node", {"x": 10.0})
        session.add_observations("n-1", "x", [(shift_months(now, -k), 10.0 + k)
                                              for k in range(6, 0, -1)])
        reply = api.project(session).to_dict()
    return {row["horizon_s"] for row in reply["projection"]["raced"]}


class TestAHorizonOfAMonthIsLaidForward:

    @pytest.mark.parametrize("now, days", [
        (datetime(2026, 2, 1), 28), (datetime(2026, 1, 1), 31),
        (datetime(2026, 1, 31), 28), (datetime(2024, 1, 31), 29)])
    def test_a_month_ahead_is_as_long_as_the_month_ahead(self, now, days):
        assert _horizon_s(now) == {days * 86400.0}


DELAY_MODEL = """
domain:
  id: monthly_delay
  name: monthly delay
  entity_types: [Source, Sink]
  relationship_types: [drives]
  indicators:
    Source:
      - {name: x, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 80}
    Sink:
      - {name: y, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 80}
  relationship_rules:
    - type: drives
      source_type: Source
      target_type: Sink
      edge_direction: causal
      causal: {weight: 0.8}
      temporal: TEMPORAL
"""


def _walk(temporal, days):
    """The source over its bound in the second month only; the sink over its
    bound at the third capture, walked from there."""
    t = [datetime(2026, 1, days[0]), datetime(2026, 2, days[1]), datetime(2026, 3, days[2])]
    with api.as_of(t[2]):
        session = api.EngineSession()
        session.load_model(DELAY_MODEL.replace("TEMPORAL", temporal))
        session.add_entity("src", "Source", {"x": 10.0})
        session.add_entity("snk", "Sink", {"y": 95.0})
        session.add_relationship("src", "drives", "snk")
        session.add_observations("src", "x", [(t[0], 10.0), (t[1], 95.0), (t[2], 10.0)])
        session.add_observations("snk", "y", [(t[0], 10.0), (t[1], 10.0), (t[2], 95.0)])
        api.check(session)
        hypothesis = api.hypothesize(session, "snk").to_dict()["hypothesis"]
    [row] = [r for r in hypothesis["candidates"] if r["cause"] == "src"]
    return session, row, hypothesis


class TestADelayOfAMonth:

    @pytest.mark.parametrize("alignment", list(MONTH_CAPTURES))
    def test_a_month_reads_the_previous_months_capture_from_every_alignment(self, alignment):
        _, row, hypothesis = _walk("{propagation_delay: 1 month}", MONTH_CAPTURES[alignment])
        assert row["read_at"] == [shift_months(
            datetime(2026, 3, MONTH_CAPTURES[alignment][2]), -1).isoformat()]
        assert (row["standing"], hypothesis["walk"]["state"]) == ("frontier", "traced")

    @pytest.mark.parametrize("alignment, standing", [
        ("on the 1st", "screened"), ("on the 15th", "screened"), ("at month end", "frontier")])
    def test_thirty_days_in_seconds_still_read_by_the_day_of_the_month(self, alignment, standing):
        """What an author wrote before 0.2.34, unchanged: seconds are seconds."""
        _, row, _ = _walk("{propagation_delay_s: 2592000}", MONTH_CAPTURES[alignment])
        assert row["standing"] == standing

    def test_a_fixed_duration_is_read_as_its_seconds(self):
        _, row, _ = _walk("{propagation_delay: 28d}", MONTH_CAPTURES["on the 1st"])
        assert row["read_at"] == [datetime(2026, 2, 1).isoformat()]

    def test_two_monthly_edges_are_two_months_back(self):
        model = DELAY_MODEL.replace("[Source, Sink]", "[Source, Mid, Sink]") \
            .replace("TEMPORAL", "{propagation_delay: 1 month}") \
            .replace("""    Sink:
      - {name: y""", """    Mid:
      - {name: m, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 80}
    Sink:
      - {name: y""").replace("""      source_type: Source
      target_type: Sink""", """      source_type: Source
      target_type: Mid
      edge_direction: causal
      causal: {weight: 0.8}
      temporal: {propagation_delay: 1 month}
    - type: drives
      source_type: Mid
      target_type: Sink""")
        at = datetime(2026, 3, 31)
        with api.as_of(at):
            session = api.EngineSession()
            session.load_model(model)
            for entity, kind, prop in (("src", "Source", "x"), ("mid", "Mid", "m"),
                                       ("snk", "Sink", "y")):
                session.add_entity(entity, kind, {prop: 95.0 if entity == "snk" else 10.0})
            session.add_relationship("src", "drives", "mid")
            session.add_relationship("mid", "drives", "snk")
            session.add_observations("snk", "y", [(at, 95.0)])
            api.check(session)
            hypothesis = api.hypothesize(session, "snk").to_dict()["hypothesis"]
        assert hypothesis["read_at"]["entities"]["src"] == [datetime(2026, 1, 31).isoformat()]


def _unread(model_text):
    session = api.EngineSession()
    session.load_model(model_text)
    described = api.model_describe(session).to_dict()
    return session, (described.get("model") or described)


class TestTheLoaderSaysWhatItRead:

    @pytest.mark.parametrize("key, line", [
        ("window", "window: 3 months"), ("timeout", "timeout: 1 month"),
        ("horizon", "horizon: 1y"), ("lookback", "lookback: 2 months"),
    ])
    def test_a_month_under_a_key_is_read_and_reported_nowhere(self, key, line):
        _, described = _unread(f"""
domain:
  id: k
  name: k
  entity_types: [Node]
  indicators:
    Node:
      - {{name: x, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 80, {line}}}
""")
        assert not [r for r in described.get("unread_fields") or []
                    if r.get("field") == key and r.get("reason") == "malformed_value"]

    def test_align_tolerance_refuses_a_month_by_name(self):
        _, described = _unread("""
domain:
  id: k
  name: k
  entity_types: [Node]
  indicators:
    Node:
      - {name: x, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 80, align_tolerance: 1 month}
""")
        [row] = [r for r in described["unread_fields"] if r["field"] == "align_tolerance"]
        assert row["reason"] == "malformed_value" and "fixed length" in row["remedy"]

    def test_a_capital_m_under_a_key_is_named(self):
        _, described = _unread("""
domain:
  id: k
  name: k
  entity_types: [Node]
  indicators:
    Node:
      - {name: x, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 80, window: 1M}
""")
        [row] = [r for r in described["unread_fields"] if r["field"] == "window"]
        assert "`mo` for a month" in row["remedy"]

    def test_both_delay_keys_are_refused_and_neither_applies(self):
        session, described = _unread(DELAY_MODEL.replace(
            "TEMPORAL", "{propagation_delay: 1 month, propagation_delay_s: 60}"))
        [row] = [r for r in described["unread_fields"]
                 if r["field"] == "temporal.propagation_delay"]
        assert row["reason"] == "malformed_value" and "neither was applied" in row["remedy"]
        [declared] = described["causal"]["declared"]
        assert (declared["propagation_delay"], declared["propagation_delay_s"]) == (None, None)

    def test_an_unreadable_delay_is_named_and_not_applied(self):
        _, described = _unread(DELAY_MODEL.replace("TEMPORAL", "{propagation_delay: soon}"))
        [row] = [r for r in described["unread_fields"]
                 if r["field"] == "temporal.propagation_delay"]
        assert row["reason"] == "malformed_value"

    def test_a_calendar_delay_is_described_as_written(self):
        _, described = _unread(DELAY_MODEL.replace("TEMPORAL", "{propagation_delay: 1 month}"))
        [declared] = described["causal"]["declared"]
        assert (declared["propagation_delay"], declared["propagation_delay_s"]) == ("1 month", None)
        assert not [r for r in described.get("unread_fields") or []
                    if "propagation_delay" in r.get("field", "")]


class TestTheSimulationMeasuresAMonthFromItsStart:

    def test_the_edges_dead_time_is_the_month_from_the_instant_built(self):
        at = datetime(2026, 2, 1)
        with api.as_of(at):
            session = api.EngineSession()
            session.load_model(DELAY_MODEL.replace(
                "TEMPORAL", "{propagation_delay: 1 month, time_constant_s: 60}"))
            session.add_entity("src", "Source", {"x": 10.0})
            session.add_entity("snk", "Sink", {"y": 10.0})
            session.add_relationship("src", "drives", "snk")
            from arbiter_engine.api import _build_topology
            topology = _build_topology(session)
        [edge] = [e for edges in topology.edges.values() for e in edges]
        assert edge.propagation_delay_s == span_seconds_forward(CalendarSpan(1), at) == 28 * 86400


class TestTheOntologyPath:

    @pytest.mark.parametrize("written, read", [
        ("P1D", timedelta(days=1)), ("P30D", timedelta(days=30)),
        ("P1W", timedelta(weeks=1)), ("P1DT12H", timedelta(days=1, hours=12)),
        ("12w", timedelta(weeks=12)), ("PT90M", timedelta(minutes=90)),
    ])
    def test_the_rdf_loader_reads_what_the_yaml_loader_reads(self, written, read):
        assert OntologyLoader.__new__(OntologyLoader)._parse_duration(written) == read

    def test_and_refuses_what_it_refuses(self):
        assert OntologyLoader.__new__(OntologyLoader)._parse_duration("1M") is None


def _stale(issued_days_ago, now):
    """Whether a producer's forecast, issued that long before `now`, is past a
    `max_age:` of one month."""
    with api.as_of(now):
        session = api.EngineSession()
        session.load_model({"domain": {
            "id": "aged", "name": "aged", "entity_types": ["Account"],
            "indicators": {"Account": [{
                "name": "balance", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                "critical": 9e9, "window": "1h",
                "forecast": {"expected": True, "max_age": "1 month"}}]}}})
        session.add_entity("a-1", "Account", {"balance": 10.0})
        ingest_forecasts(session, [{
            "model_id": "garch_v3", "entity_id": "a-1", "property": "balance",
            "horizon_s": 3600.0, "issued_at": now - timedelta(days=issued_days_ago),
            "quantiles": {"q05": 1.0, "q50": 2.0, "q95": 3.0}}])
        leg = api.check(session).to_dict()["forecasts"]
    assert not [d for d in leg["not_checked"] if d["reason"] == "internal_error"]
    return [d for d in leg["not_checked"] if d["reason"] == "stale_forecast"] != []


class TestAnAgeOfAMonthIsCountedBack:
    """`forecast.max_age:` raised on a month, and the leg read as unanswered."""

    @pytest.mark.parametrize("now, fresh, stale", [
        (datetime(2026, 3, 1), 27, 29), (datetime(2026, 3, 31), 30, 32)])
    def test_a_forecast_is_stale_past_the_month_back_from_now(self, now, fresh, stale):
        assert (_stale(fresh, now), _stale(stale, now)) == (False, True)


def test_every_verb_answers_a_model_writing_months_under_every_key():
    """The sweep that found `max_age`: every indicator shape the axiom contract
    uses, with a month under every duration key it takes, and a monthly delay
    on the causal edge. No verb may raise, or answer with a discipline that did."""
    from conftest import INDICATOR_BY_AXIOM, unhealthy_series
    now = datetime(2026, 3, 31, 12, 0)
    indicators = []
    for axiom, declared in INDICATOR_BY_AXIOM.items():
        spec = json.loads(json.dumps(declared))
        if spec["type"] == "NUMERIC":
            spec.update({"window": "3 months", "lookback": "6 months", "horizon": "1 month",
                         "dynamics": {"model": "random_walk"},
                         "forecast": {"expected": True, "max_age": "1 month"}})
        if axiom == "HOMEOSTASIS":
            spec["homeostasis"] = {"setpoint": 20, "tolerance": 2,
                                   "must_return_within": "1 month"}
        indicators.append(spec)
    indicators.append({"name": "phase", "type": "STATE", "axioms": ["STABILITY"],
                       "normal": ["done"], "transient": ["in_review"], "bad": ["failed"],
                       "timeout": "1 month", "window": "2 months"})
    model = {"domain": {
        "id": "months_everywhere", "name": "months everywhere",
        "entity_types": ["Unit", "Sink"], "relationship_types": ["feeds"],
        "indicators": {"Unit": indicators, "Sink": [{
            "name": "level_pct", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
            "warning": 85, "critical": 95, "window": "1y", "horizon": "P1M",
            "dynamics": {"model": "random_walk"}}]},
        "relationship_rules": [{
            "type": "feeds", "source_type": "Unit", "target_type": "Sink",
            "edge_direction": "causal", "causal": {"weight": 0.8},
            "temporal": {"propagation_delay": "1 month", "time_constant_s": 60,
                         "response_model": "step"},
            "transition": {"from": "level_pct", "to": "level_pct", "gain": 0.5,
                           "gain_sigma": 0.05, "source": "datasheet"}}]}}
    months = [shift_months(now, -k) for k in range(11, -1, -1)]
    verbs = {
        "model_describe": api.model_describe, "check": api.check, "gaps": api.gaps,
        "traverse": lambda s: api.traverse(s, ["u-1"], value_mode="projected"),
        "rollout": lambda s: api.rollout(s, horizon_s=3600.0, step_s=600.0,
                                         seed_mode="projected", file_predictions=True),
        "plan": api.plan, "project": api.project, "entail": api.entail,
        "discover": lambda s: api.discover(s, alpha=0.05),
        "hypothesize": lambda s: api.hypothesize(s, "s-1"),
        "infer": lambda s: api.infer(s, "s-1"),
        "attest": lambda s: api.attest(s, "threshold_exceeded:level_pct", "s-1"),
        "case_book": api.case_book,
    }
    unanswered = {}
    with api.as_of(now):
        session = api.EngineSession()
        session.load_model(model)
        current = {i["name"]: unhealthy_series(a, 1)[0]
                   for a, i in INDICATOR_BY_AXIOM.items() if i["type"] == "NUMERIC"}
        session.add_entity("u-1", "Unit", dict(current, phase="in_review"))
        session.add_entity("s-1", "Sink", {"level_pct": 97.0})
        session.add_relationship("u-1", "feeds", "s-1")
        for axiom, declared in INDICATOR_BY_AXIOM.items():
            if declared["type"] == "NUMERIC":
                session.add_observations("u-1", declared["name"], list(zip(
                    months, reversed(unhealthy_series(axiom, 12)))))
        session.add_observations("u-1", "outflow_lps", [(m, 1.0) for m in months])
        session.add_observations("u-1", "phase", [(m, "in_review") for m in months[-4:]])
        session.add_observations("s-1", "level_pct", [(m, 50.0) for m in months])
        ingest_forecasts(session, [{
            "model_id": "garch_v3", "entity_id": "u-1", "property": "level_pct",
            "horizon_s": 3600.0, "issued_at": now - timedelta(days=40),
            "quantiles": {"q05": 1.0, "q50": 2.0, "q95": 3.0}}])
        for name, verb in verbs.items():
            text = json.dumps(verb(session).to_dict(), default=str)
            if "internal_error" in text or "checker_error" in text:
                unanswered[name] = text[:400]
    assert unanswered == {}
