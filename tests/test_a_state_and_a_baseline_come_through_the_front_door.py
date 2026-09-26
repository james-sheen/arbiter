"""A state series and the evaluation parameters, both through the session.

Issue #14 named two things a caller following the front door could not do, and
they were one defect: the session dropped a capability the layer beneath it
had.

- `add_observations` cast every reading to `float`, so a STATE raised. The
  history underneath takes any value and STABILITY reads states out of it, so
  the state arm declined for ever on a series that existed -- measured on an
  operating model, nine `status` indicators declining at one capture and at
  thirty-six alike.
- `load_model` built its reasoner with no parameters, so HOMEOSTASIS kept a
  seven-day baseline whatever the model's cadence. Observed monthly, that
  baseline holds about one sample, and the axiom declined whatever the data
  did.

The model now declares both: `type: state` on the indicator decides how a
reading is kept, and `axiom_parameters:` sets what the reasoner is built with.
"""

from __future__ import annotations

import dataclasses
import math
import random
from datetime import datetime, timedelta

import pytest

from arbiter_engine import api
from arbiter_engine.history.calendar import (CalendarHistory,
                                                          SessionCalendar)
from arbiter_engine.history.observation import \
    InMemoryObservationHistory
from arbiter_engine.history.sqlite_store import \
    SqliteObservationHistory
from arbiter_engine.ontology.domain_loader import (
    MalformedDomainModelError, load_domain)
from arbiter_engine.types import AxiomParameters

AT = datetime(2026, 9, 26, 12, 0)
MONTH = timedelta(days=30)


def _model(**parameters):
    """One unit type with a state, a margin and a count -- the three shapes an
    operating review reports -- and whatever parameters the test declares."""
    domain = {
        "id": "front-door",
        "name": "a unit reported monthly",
        "entity_types": ["Unit"],
        "indicators": {"Unit": [
            {"name": "status", "type": "STATE", "axioms": ["STABILITY"],
             "window": "3650d", "normal": ["healthy", "growing"],
             "transient": ["restructuring"], "bad": ["declining"]},
            {"name": "margin_pct", "type": "NUMERIC", "axioms": ["HOMEOSTASIS"],
             "window": "3650d", "role": "percentage"},
            {"name": "headcount", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
             "window": "3650d", "warning": 500, "critical": 800},
        ]},
    }
    if parameters:
        domain["axiom_parameters"] = parameters
    return {"domain": domain}


def _session(history=None, **parameters):
    session = api.EngineSession(history=history)
    session.load_model(_model(**parameters))
    session.add_entity("u-1", "Unit", {"status": "healthy", "margin_pct": 10.0,
                                       "headcount": 120})
    return session


def _monthly(values):
    """Timestamped samples a month apart, ending at `AT`."""
    return [(AT - MONTH * (len(values) - 1 - i), v) for i, v in enumerate(values)]


def _declines(envelope, indicator, axiom=None):
    return [d.get("reason") for d in envelope["not_checked"]
            if d.get("entity_id") == "u-1" and d.get("indicator") == indicator
            and (axiom is None or d.get("axiom") == axiom)]


def _findings(envelope):
    return [f.get("type") or f.get("problem_type") for f in envelope["findings"]
            if f.get("entity_id") == "u-1"]


HISTORIES = {
    "in_memory": lambda: InMemoryObservationHistory(),
    "sqlite": lambda: SqliteObservationHistory(":memory:"),
    "calendar": lambda: CalendarHistory(InMemoryObservationHistory(),
                                        SessionCalendar()),
}


class TestAStateIsKeptAsAState:

    @pytest.mark.parametrize("kind", sorted(HISTORIES))
    def test_a_declared_state_reaches_the_state_arm_in_every_store(self, kind):
        """Twelve monthly states and the state arm evaluates; before, the same
        call raised on the first one."""
        session = _session(HISTORIES[kind]())
        cycle = ["healthy", "growing", "healthy", "restructuring"] * 3
        with api.as_of(AT):
            session.add_observations("u-1", "status", _monthly(cycle))
            envelope = api.check(session).to_dict()
            states = session.history.get_states("u-1", "status",
                                                timedelta(days=3650))
        assert [s for _, s in states] == cycle
        assert "insufficient_samples" not in _declines(envelope, "status")

    def test_a_state_that_flaps_is_judged_now(self):
        """What the series is FOR. A unit flipping between two states every
        month is an oscillation, and only a history of states can show one --
        the current value on its own is always a single, unremarkable state."""
        session = _session()
        with api.as_of(AT):
            session.add_observations("u-1", "status",
                                     _monthly(["healthy", "growing"] * 6))
            envelope = api.check(session).to_dict()
        assert "stability_oscillation:status" in _findings(envelope)

    def test_a_state_that_holds_is_clean(self):
        session = _session()
        with api.as_of(AT):
            session.add_observations("u-1", "status", _monthly(["healthy"] * 12))
            envelope = api.check(session).to_dict()
        assert not [f for f in _findings(envelope) if f.endswith(":status")]
        assert _declines(envelope, "status") == []

    def test_bare_readings_take_the_same_door(self):
        session = _session()
        with api.as_of(AT):
            session.add_observations("u-1", "status", ["healthy", "growing"],
                                     interval_seconds=MONTH.total_seconds())
            states = session.history.get_states("u-1", "status",
                                                timedelta(days=3650))
        assert [s for _, s in states] == ["healthy", "growing"]

    def test_a_state_is_stored_as_text_whatever_it_arrived_as(self):
        """Every store reads a state back as text; a code arriving as a number
        must not come back as `1.0` from one store and `1` from another."""
        session = _session(SqliteObservationHistory(":memory:"))
        with api.as_of(AT):
            session.add_observations("u-1", "status", _monthly([1, 2]))
            states = session.history.get_states("u-1", "status",
                                                timedelta(days=3650))
        assert [s for _, s in states] == ["1", "2"]

    def test_an_empty_state_is_refused(self):
        session = _session()
        with pytest.raises(ValueError, match="cannot be None"):
            session.add_observations("u-1", "status", [None])


class TestANumberIsStillANumber:

    def test_a_numeric_string_for_a_numeric_indicator_is_a_number(self):
        """The regression dropping the cast outright would have caused: an
        export's `"3.5"` becoming a state, and the numeric axioms going quiet."""
        session = _session()
        with api.as_of(AT):
            session.add_observations("u-1", "margin_pct", _monthly(["3.5", "4"]))
            values = session.history.get_values("u-1", "margin_pct",
                                                timedelta(days=3650))
        assert [v for _, v in values] == [3.5, 4.0]
        assert all(isinstance(v, float) for _, v in values)

    def test_a_word_for_a_numeric_indicator_is_refused_with_the_remedy(self):
        session = _session()
        with pytest.raises(ValueError, match=r"type: state"):
            session.add_observations("u-1", "margin_pct", ["high"])

    def test_an_entity_fed_before_it_is_added_is_read_as_numbers(self):
        """The declaration is found through the entity's type, so an entity
        the session has not been told about has none -- the cast stands, and
        the refusal says to add the entity first."""
        session = api.EngineSession()
        session.load_model(_model())
        with pytest.raises(ValueError, match="add the entity"):
            session.add_observations("u-9", "status", ["healthy"])

    def test_the_mixed_shape_refusal_is_unchanged(self):
        session = _session()
        with pytest.raises(ValueError, match="mix of bare readings"):
            session.add_observations("u-1", "status",
                                     [(AT, "healthy"), "growing"])


class TestTheModelSetsItsOwnParameters:

    def test_a_model_declaring_nothing_is_evaluated_exactly_as_before(self):
        session = _session()
        assert session.reasoner.params == AxiomParameters()

    def test_a_declared_parameter_reaches_the_reasoner(self):
        session = _session(homeostasis_baseline_days=2000,
                           stability_window_size=4)
        assert session.reasoner.params.homeostasis_baseline_days == 2000
        assert session.reasoner.params.stability_window_size == 4

    def test_every_parameter_is_reported_with_where_it_came_from(self):
        session = _session(homeostasis_baseline_days=2000)
        described = api.model_describe(session).to_dict()["model"]
        in_effect = described["axiom_parameters"]
        # DERIVED: every field of the dataclass, not a list written here.
        assert set(in_effect) == {f.name for f in
                                  dataclasses.fields(AxiomParameters)}
        assert in_effect["homeostasis_baseline_days"] == {
            "value": 2000, "source": "declared"}
        assert in_effect["homeostasis_min_samples"] == {
            "value": AxiomParameters().homeostasis_min_samples,
            "source": "default"}

    def test_an_unknown_parameter_is_reported_and_read_by_nothing(self):
        session = _session(homeostasis_baselin_days=2000)
        rows = [r for r in session.model.unread_fields()
                if r["field"].startswith("axiom_parameters")]
        assert [(r["field"], r["reason"], r["did_you_mean"]) for r in rows] == [
            ("axiom_parameters.homeostasis_baselin_days", "unknown_key",
             "homeostasis_baseline_days")]
        assert session.reasoner.params.homeostasis_baseline_days == 7

    @pytest.mark.parametrize("value", ["seven", True, 2.5, float("nan"),
                                       [7], None])
    def test_a_value_that_is_not_a_count_is_refused_and_says_so(self, value):
        session = _session(homeostasis_baseline_days=value)
        rows = [r for r in session.model.unread_fields()
                if r["field"] == "axiom_parameters.homeostasis_baseline_days"]
        assert [r["reason"] for r in rows] == ["malformed_value"]
        assert "the engine's own 7 was used" in rows[0]["remedy"]
        assert session.reasoner.params.homeostasis_baseline_days == 7
        in_effect = api.model_describe(session).to_dict()["model"][
            "axiom_parameters"]["homeostasis_baseline_days"]
        assert in_effect == {"value": 7, "source": "default"}

    def test_a_whole_number_written_as_a_decimal_is_a_count(self):
        session = _session(homeostasis_baseline_days=30.0)
        assert session.reasoner.params.homeostasis_baseline_days == 30
        assert isinstance(session.reasoner.params.homeostasis_baseline_days, int)

    def test_a_rate_takes_any_finite_number(self):
        session = _session(homeostasis_z_warning=2)
        assert session.reasoner.params.homeostasis_z_warning == 2.0
        assert not math.isnan(session.reasoner.params.homeostasis_z_critical)

    def test_a_block_that_is_not_a_mapping_refuses_the_model(self):
        with pytest.raises(MalformedDomainModelError, match="axiom_parameters"):
            load_domain({"domain": {"id": "x", "entity_types": ["Unit"],
                                    "axiom_parameters": [7]}})


class TestHomeostasisAnswersAtAMonthlyCadence:
    """The measurement the second half of the issue was about: thirty-six
    monthly captures, enough for the axiom's own sample floor, and a baseline
    that could never hold them."""

    @staticmethod
    def _run(tail, **parameters):
        rng = random.Random(7)
        steady = [10.0 + rng.uniform(-0.4, 0.4) for _ in range(35)]
        session = _session(**parameters)
        # The current reading is the latest capture's, as a vertical adding
        # the unit from that capture would give it.
        session.entities["u-1"].properties["margin_pct"] = tail
        with api.as_of(AT):
            session.add_observations("u-1", "margin_pct",
                                     _monthly(steady + [tail]))
            return api.check(session).to_dict()

    def test_with_the_default_baseline_it_can_never_answer(self):
        for tail in (10.1, 2.0):
            envelope = self._run(tail)
            assert _declines(envelope, "margin_pct", "HOMEOSTASIS") == [
                "insufficient_samples"]

    def test_with_a_declared_baseline_a_steady_margin_is_clean(self):
        envelope = self._run(10.1, homeostasis_baseline_days=2000)
        assert _declines(envelope, "margin_pct", "HOMEOSTASIS") == []
        assert not [f for f in _findings(envelope) if "margin_pct" in f]

    def test_with_a_declared_baseline_a_collapse_is_a_finding(self):
        envelope = self._run(2.0, homeostasis_baseline_days=2000)
        assert _declines(envelope, "margin_pct", "HOMEOSTASIS") == []
        assert "homeostasis_anomaly:margin_pct" in _findings(envelope)
