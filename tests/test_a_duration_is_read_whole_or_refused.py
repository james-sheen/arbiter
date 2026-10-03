"""A duration is read whole, or refused by name, and a refused `timeout:` declares none.

the loader read a duration as a PREFIX: `3 months` as three minutes,
`1h30m` as one hour, `1 ms` as one minute. What it could not read at all --
`12w`, `1y`, `P90D`, `600` -- became nothing, which `timeout:` turned into five
minutes, the number the previous release had stopped using. Measured on the
released engine, and worse than it reads, because STABILITY looks back twice
the timeout:

- a state in review for two hours, read a minute apart, was reported stuck
  under `timeout: 12w`;
- one in review for five months, captured monthly, was NOT reported under the
  same `12w`, since a five-minute look back holds one capture.

`unread_fields` named neither. Now a duration is seconds, minutes, hours, days
or weeks, joined or ISO 8601, read whole; months and years are refused by name,
having no fixed length; every refusal is a `malformed_value` row; and a refused
`timeout:` is not a declared one.

Since 0.2.34 the one refusal that cost the author a correct answer is
reversed: months and years are calendar units, laid at the instant each reader
measures from, as `test_a_month_is_a_calendar_month.py` pins. What is still
refused here is what still has no reading -- a fraction of a month, a capital `M`
that is a month to some and a minute to others, and a month under
`align_tolerance:`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from arbiter_engine import api
from arbiter_engine.ontology.domain_loader import (
    load_domain, parse_duration, read_duration)

READ = [
    ("90s", timedelta(seconds=90)),
    ("15m", timedelta(minutes=15)),
    ("2h", timedelta(hours=2)),
    ("90d", timedelta(days=90)),
    ("13w", timedelta(weeks=13)),
    ("2 hours", timedelta(hours=2)),
    ("5 minutes", timedelta(minutes=5)),
    ("1h30m", timedelta(minutes=90)),
    ("2 days, 6 hours", timedelta(days=2, hours=6)),
    ("1.5h", timedelta(minutes=90)),
    ("PT15M", timedelta(minutes=15)),
    ("PT1H30M", timedelta(minutes=90)),
    ("P90D", timedelta(days=90)),
    ("P2W", timedelta(weeks=2)),
    ("P1DT12H", timedelta(days=1, hours=12)),
    ("PT0.5S", timedelta(seconds=0.5)),
]

REFUSED = [
    ("1.5 months", "fraction of a month"),
    ("P0.5M", "fraction of a month"),
    ("3M", "`mo` for a month"),
    ("600", "no unit"),
    ("1 ms", "'ms'"),
    ("3 fortnights", "'fortnights'"),
    ("PT", "not a duration"),
    ("soon", "not a duration"),
    ("", "no value"),
]


class TestTheWholeValueIsRead:

    @pytest.mark.parametrize("written, read", READ)
    def test_a_duration_is_read(self, written, read):
        assert parse_duration(written) == read

    @pytest.mark.parametrize("written, why", REFUSED)
    def test_anything_else_is_refused_and_says_why(self, written, why):
        value, problem = read_duration(written)
        assert value is None and why in problem

    def test_a_number_written_bare_is_not_a_duration(self):
        assert read_duration(600) == (None, "is a number with no unit")

    def test_no_prefix_of_a_value_is_read_as_the_value(self):
        """The defect in one line each: what the prefix read used to return."""
        assert parse_duration("3 months").months == 3   # was three minutes
        assert parse_duration("1h30m") == timedelta(minutes=90)   # was one hour
        assert parse_duration("1 ms") is None           # was one minute


MODEL = """
domain:
  id: review_states
  name: review states
  entity_types: [Review]
  indicators:
    Review:
      - name: phase
        type: STATE
        axioms: [STABILITY]
        normal: [done]
        transient: [in_review]
        bad: [failed]
        {timeout}
"""
END = datetime(2026, 9, 28, 12, 0)
TWO_HOURS = [(END - timedelta(minutes=120 - i), "in_review") for i in range(121)]
FIVE_MONTHS = [(END - timedelta(days=30 * (5 - i)), "in_review") for i in range(6)]


def _judged(timeout_line, readings):
    session = api.EngineSession()
    session.load_model(MODEL.format(timeout=timeout_line))
    session.add_entity("r-1", "Review", {"phase": "in_review"})
    session.add_observations("r-1", "phase", readings)
    with api.as_of(END):
        body = api.check(session).to_dict()
    body = body.get("check") or body
    fired = [f for f in body.get("findings") or []
             if str(f.get("problem_type", "")).startswith("transient_state_timeout")]
    declined = [d for d in body.get("not_checked") or []
                if d.get("reason") == "missing_config"]
    return session, fired, declined


class TestStabilityTimesOnlyWhatWasDeclared:

    @pytest.mark.parametrize("timeout", ["timeout: 12w", "timeout: 90d", "timeout: P90D",
                                         "timeout: 3 months"])
    def test_a_long_timeout_does_not_fire_on_two_hours(self, timeout):
        _, fired, declined = _judged(timeout, TWO_HOURS)
        assert fired == [] and declined == []

    @pytest.mark.parametrize("timeout", ["timeout: 12w", "timeout: 90d", "timeout: P90D",
                                         "timeout: 3 months"])
    def test_and_fires_on_five_months_of_monthly_captures(self, timeout):
        _, fired, _ = _judged(timeout, FIVE_MONTHS)
        assert len(fired) == 1

    @pytest.mark.parametrize("readings", [TWO_HOURS, FIVE_MONTHS])
    @pytest.mark.parametrize("timeout", ["timeout: 1.5 months", "timeout: 3M", "timeout: 0s"])
    def test_a_refused_timeout_declares_none_and_the_decline_says_what_was_written(
            self, timeout, readings):
        _, fired, declined = _judged(timeout, readings)
        assert fired == []
        [decline] = declined
        assert timeout.split(": ", 1)[1] in decline["detail"]


class TestEachRefusalIsReported:

    @pytest.mark.parametrize("key, written, consequence", [
        ("timeout", "1.5 months", "STABILITY declines"),
        ("window", "a while", "engine's own 1h"),
        ("horizon", "1M", "not written"),
        ("lookback", "600", "not written"),
        ("align_tolerance", "1 ms", "not written"),
    ])
    def test_a_malformed_value_row_names_the_key_the_value_and_what_came_of_it(
            self, key, written, consequence):
        session = api.EngineSession()
        session.load_model({"domain": {
            "id": "durations", "name": "durations", "entity_types": ["Unit"],
            "indicators": {"Unit": [{"name": "load", "type": "NUMERIC",
                                     "axioms": ["BOUNDEDNESS"], "critical": 95,
                                     key: written}]}}})
        # `timeout:` on an indicator STABILITY does not read also gets its
        # `axiom_not_declared` row; the value's row is the one asked about.
        [row] = [r for r in session.model.unread_fields()
                 if r.get("indicator") == "load" and r["field"] == key
                 and r["reason"] == "malformed_value"]
        assert row["value"] == written
        assert consequence in row["remedy"]

    def test_the_nested_return_span_is_reported_too(self):
        session = api.EngineSession()
        session.load_model({"domain": {
            "id": "durations", "name": "durations", "entity_types": ["Unit"],
            "indicators": {"Unit": [{"name": "load", "type": "NUMERIC",
                                     "axioms": ["HOMEOSTASIS"],
                                     "homeostasis": {"must_return_within": "2.5 months"}}]}}})
        [row] = [r for r in session.model.unread_fields()
                 if r["field"] == "homeostasis.must_return_within"]
        assert row["reason"] == "malformed_value" and row["value"] == "2.5 months"

    def test_a_refused_window_is_the_hour_it_was_before_and_now_says_so(self):
        session, _, _ = _judged("window: a while", TWO_HOURS)
        [spec] = session.model.indicators["Review"]
        assert spec.time_window == timedelta(hours=1)

    def test_a_readable_value_reports_nothing(self):
        session, _, _ = _judged("timeout: 1h30m", TWO_HOURS)
        [spec] = session.model.indicators["Review"]
        assert spec.transient_timeout == timedelta(minutes=90)
        assert [r for r in session.model.unread_fields()
                if r["reason"] == "malformed_value"] == []


def _examples() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples", here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / "pump_tank_planning.yaml").is_file():
            return candidate
    raise AssertionError("no examples directory in this tree carries them")


def test_every_shipped_example_writes_durations_this_engine_reads():
    """The rule above would refuse a shipped example's duration in silence of
    its own making, so every example is loaded and none may carry one."""
    refused = []
    for path in sorted(_examples().glob("*.yaml")):
        try:
            model = load_domain(path)
        except Exception:        # not every example file is a domain model
            continue
        refused += [(path.name, r["field"], r.get("value"))
                    for r in model.unread_fields()
                    if r.get("reason") == "malformed_value"
                    and r.get("indicator") is not None]
    assert refused == []
