"""Indicators the engine computes, and the two ways they fail to compute.

WHY THERE IS NO NINTH AXIOM. A parity relation, an arbitrage-free condition, a
spread that should hold, a conservation gap -- each looks like it wants its own
checker. Each is an expression over declared properties plus an axiom that
already exists: declare the difference and give it HOMEOSTASIS with a setpoint
of zero, and departures are reported without the engine learning the word
parity. The test that matters most below is the one showing exactly that.

THE TWO READ SITES FAIL DIFFERENTLY, and the second is invisible in the first.
A current value is missing when an operand is. A SERIES is missing when the
operands were never sampled close enough together to be one moment -- two feeds
are not sampled on the same tick, and subtracting a reading from one taken a
minute later is a different quantity from the one declared. So the tolerance is
declared, and a decline says how many points survived the join.

THE EXPRESSION PARSER IS PROMOTED, NOT WRITTEN, and its security claims are
tested rather than trusted: fifteen injections below, each of which must be
refused by SHAPE rather than by a denylist of names.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, check
from arbiter_engine.clock import as_of
from arbiter_engine.derived.indicator import (
    DEFAULT_ALIGN_TOLERANCE, DerivedHistoryView, compute_current, operands_of,
)
from arbiter_engine.derived.parser import (
    MAX_FORMULA_LENGTH, SafeExpressionParser,
)
from arbiter_engine.history.observation import InMemoryObservationHistory
from arbiter_engine.ontology.domain_loader import load_domain

T0 = datetime(2026, 4, 1, 12, 0)

#: A difference that should hold near zero. Neutral on purpose: the same shape
#: is a temperature drop across a stage, a parity residual and a settlement gap.
SPREAD = {"name": "drop_c", "derived": "inlet_c - outlet_c",
          "align_tolerance": "2s", "axioms": ["HOMEOSTASIS"], "window": "1h",
          "homeostasis": {"setpoint": 0, "tolerance": 0.5}}


def _model(indicators):
    return load_domain({"domain": {"id": "d", "name": "d",
                                   "entity_types": ["Stage"],
                                   "indicators": {"Stage": list(indicators)}}})


def _session(properties=None, indicators=(SPREAD,)):
    session = EngineSession()
    session.load_model({"domain": {"id": "d", "name": "d",
                                   "entity_types": ["Stage"],
                                   "indicators": {"Stage": list(indicators)}}})
    session.add_entity("s1", "Stage", dict(properties or {}))
    return session


def _feed(session, offset_seconds=1, count=20, outlet=100.0):
    for i in range(count):
        stamp = T0 + timedelta(seconds=30 * i)
        session.history.add("s1", "inlet_c", 100.2, timestamp=stamp)
        session.history.add("s1", "outlet_c", outlet,
                            timestamp=stamp + timedelta(seconds=offset_seconds))


# --- the promoted parser, attacked ------------------------------------------

@pytest.mark.parametrize("source", [
    '__import__("os").system("id")', "().__class__", "(1).__class__",
    "[1,2][0]", "(lambda: 1)()", "a > b", "a if b else c", 'f"{a}"',
    "(x := 1)", "math.sqrt(4)", 'eval("1")', "min(1, key=None)",
    "a and b", "(1, 2)", "min(*[1,2])",
])
def test_the_parser_refuses_everything_that_is_not_arithmetic(source):
    """By SHAPE, not by a denylist of names: each of these is rejected for the
    AST node it is, so the next one nobody thought of is rejected too."""
    with pytest.raises((ValueError, KeyError)):
        SafeExpressionParser().parse(source)


def test_an_over_long_formula_is_refused():
    with pytest.raises(ValueError, match="maximum length"):
        SafeExpressionParser().parse("a" * (MAX_FORMULA_LENGTH + 1))


def test_exponentiation_cannot_be_used_to_hang_the_engine():
    """Operands are coerced to float, so a tower overflows rather than
    computing an integer with a billion digits."""
    parser = SafeExpressionParser()
    with pytest.raises((OverflowError, ArithmeticError)):
        parser.evaluate(parser.parse("9**9**9**9"), {})


def test_arithmetic_still_works():
    parser = SafeExpressionParser()
    assert parser.evaluate(parser.parse("(a - b) * 2 + abs(c)"),
                           {"a": 5.0, "b": 3.0, "c": -4.0}) == 8.0


# --- operands ---------------------------------------------------------------

def test_the_operands_are_the_names_the_expression_reads():
    assert operands_of("call - put - spot + strike * discount") == [
        "call", "discount", "put", "spot", "strike"]


def test_an_expression_that_will_not_parse_has_no_operands():
    assert operands_of("lambda: 1") == []


# --- the current value ------------------------------------------------------

def test_a_derived_current_value_is_computed_from_the_operands():
    spec = _model([SPREAD]).indicators["Stage"][0]
    assert compute_current(spec, {"inlet_c": 101.5, "outlet_c": 100.0}) == (1.5, [])


def test_a_missing_operand_is_named():
    """THE POINT. The axiom declines on `drop_c`, a property nobody feeds, so
    an author told only `missing_property: drop_c` goes looking for a feed that
    was never supposed to exist."""
    spec = _model([SPREAD]).indicators["Stage"][0]
    assert compute_current(spec, {"inlet_c": 101.5}) == (None, ["outlet_c"])


def test_a_non_numeric_operand_counts_as_missing():
    spec = _model([SPREAD]).indicators["Stage"][0]
    assert compute_current(spec, {"inlet_c": 101.5, "outlet_c": "warm"})[1] == ["outlet_c"]


def test_check_reports_the_operand_rather_than_only_the_indicator():
    session = _session({"inlet_c": 101.5})
    envelope = check(session).to_dict()
    assert envelope["underived"][0]["missing_operands"] == ["outlet_c"]
    assert [d["reason"] for d in envelope["not_checked"]] == ["missing_property"]


def test_nothing_derived_means_an_empty_report():
    session = _session({"level": 1.0}, indicators=(
        {"name": "level", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
         "window": "1h", "critical": 9},))
    assert check(session).to_dict()["underived"] == []


def test_a_fed_value_under_the_derived_name_does_not_survive():
    """The declaration says the property IS the expression. A fed value under
    the same name is a second source for one fact, and the one the author
    wrote down wins."""
    session = _session({"inlet_c": 101.0, "outlet_c": 100.0, "drop_c": 999.0})
    check(session)
    assert session.entities["s1"].properties["drop_c"] == pytest.approx(1.0)


def test_a_stale_derived_value_does_not_survive_a_missing_operand():
    """THE CASE THE TEST ABOVE DOES NOT REACH, and the dangerous one. When the
    operands ARE present the computed value overwrites whatever was there, so
    nothing about that proves the stale one is removed. When an operand goes
    missing, a value left behind under the derived name is judged by the
    axioms as though it were today's -- a number from an earlier cycle,
    reported as current, with no decline to say so."""
    session = _session({"inlet_c": 101.0, "drop_c": 999.0})
    envelope = check(session).to_dict()
    assert "drop_c" not in session.entities["s1"].properties
    assert envelope["underived"][0]["missing_operands"] == ["outlet_c"]
    assert [d["reason"] for d in envelope["not_checked"]] == ["missing_property"]


# --- no ninth axiom ---------------------------------------------------------

def test_a_relation_that_should_hold_is_a_derived_value_plus_homeostasis():
    """The claim this whole feature rests on. A spread that departs from its
    declared setpoint is reported, and no checker learned what a spread is."""
    session = _session({"inlet_c": 102.0, "outlet_c": 100.0})
    _feed(session)
    with as_of(T0 + timedelta(seconds=600)):
        envelope = check(session).to_dict()
    assert [f["problem_type"] for f in envelope["findings"]] == \
        ["homeostasis_setpoint:drop_c"]


def test_the_same_relation_holding_reports_nothing():
    """The discriminator: a finding that fires either way is not a finding."""
    session = _session({"inlet_c": 100.2, "outlet_c": 100.0})
    _feed(session)
    with as_of(T0 + timedelta(seconds=600)):
        envelope = check(session).to_dict()
    assert envelope["findings"] == []


# --- the series -------------------------------------------------------------

def _view(session):
    return DerivedHistoryView(session.history, session.model)


def test_the_series_is_an_as_of_join_of_the_operands():
    session = _session()
    _feed(session, offset_seconds=1)
    with as_of(T0 + timedelta(seconds=600)):
        series = _view(session).get_values("s1", "drop_c", timedelta(hours=1))
    assert len(series) == 20
    assert series[0][1] == pytest.approx(0.2)


def test_operands_sampled_too_far_apart_join_to_nothing():
    """SAME OPERAND COUNTS, no aligned points. The declared tolerance is what
    decides which moments exist, and a series that silently paired readings a
    minute apart would be a different quantity reported under the same name."""
    session = _session()
    _feed(session, offset_seconds=5)
    with as_of(T0 + timedelta(seconds=600)):
        alignment = _view(session).alignment("s1", "drop_c", timedelta(hours=1))
    assert alignment["operands"] == {"inlet_c": 20, "outlet_c": 20}
    assert alignment["aligned"] == 0


def test_a_wider_declared_tolerance_admits_them():
    wide = dict(SPREAD, align_tolerance="10s")
    session = _session(indicators=(wide,))
    _feed(session, offset_seconds=5)
    with as_of(T0 + timedelta(seconds=600)):
        alignment = _view(session).alignment("s1", "drop_c", timedelta(hours=1))
    assert alignment["aligned"] == 20
    assert alignment["align_tolerance_s"] == 10.0


def test_the_default_tolerance_is_reported_when_none_is_declared():
    """A default that decides which points EXIST, so it rides in the answer."""
    bare = {k: v for k, v in SPREAD.items() if k != "align_tolerance"}
    session = _session(indicators=(bare,))
    _feed(session, offset_seconds=1)
    with as_of(T0 + timedelta(seconds=600)):
        alignment = _view(session).alignment("s1", "drop_c", timedelta(hours=1))
    assert alignment["align_tolerance_s"] == DEFAULT_ALIGN_TOLERANCE.total_seconds()


def test_a_window_axiom_sees_the_derived_series_through_check():
    """THE WRAP, exercised where it matters. The series tests above build the
    view directly, so none of them shows that `check` uses it -- and a window
    axiom reading an underived history finds nothing and declines for want of
    samples, on a series the engine can build perfectly well."""
    varying = {"name": "drop_c", "derived": "inlet_c - outlet_c",
               "align_tolerance": "2s", "axioms": ["STABILITY"],
               "window": "1h", "expect_variation": True}
    session = _session({"inlet_c": 100.2, "outlet_c": 100.0},
                       indicators=(varying,))
    for i in range(20):
        stamp = T0 + timedelta(seconds=30 * i)
        session.history.add("s1", "inlet_c", 100.2 + i * 0.01, timestamp=stamp)
        session.history.add("s1", "outlet_c", 100.0,
                            timestamp=stamp + timedelta(seconds=1))
    with as_of(T0 + timedelta(seconds=600)):
        envelope = check(session).to_dict()
    starved = [d for d in envelope["not_checked"]
               if d["reason"] == "insufficient_samples"]
    assert starved == []
    assert envelope["checked"]["invariants"] == 1


def test_a_property_nobody_derived_passes_straight_through():
    session = _session()
    _feed(session)
    with as_of(T0 + timedelta(seconds=600)):
        assert len(_view(session).get_values(
            "s1", "inlet_c", timedelta(hours=1))) == 20


def test_the_count_of_a_derived_series_is_its_scarcest_operand():
    """No join can produce more points than that, and reporting the richest
    would promise a series the engine cannot build."""
    session = _session()
    for i in range(20):
        session.history.add("s1", "inlet_c", 100.2, timestamp=T0 + timedelta(seconds=30 * i))
    for i in range(3):
        session.history.add("s1", "outlet_c", 100.0, timestamp=T0 + timedelta(seconds=30 * i))
    assert _view(session).get_observation_count("s1", "drop_c") == 3


# --- references resolve one level -------------------------------------------

def _underivable(indicators):
    return [r["remedy"] for r in _model(indicators).unreachable_declarations()
            if r.get("reason") == "underivable"]


def test_an_operand_that_is_itself_derived_is_refused_at_load():
    """With chains allowed the evaluation order matters and nothing declares
    it; with cycles allowed there is no order at all."""
    remedies = _underivable([SPREAD, {"name": "doubled", "derived": "drop_c * 2",
                                      "axioms": ["HOMEOSTASIS"], "window": "1h"}])
    assert remedies and "themselves derived" in remedies[0]


def test_a_self_reference_is_refused():
    remedies = _underivable([{"name": "x", "derived": "x + 1",
                              "axioms": ["HOMEOSTASIS"], "window": "1h"}])
    assert remedies and "derives from itself" in remedies[0]


def test_an_expression_that_is_not_arithmetic_is_refused():
    remedies = _underivable([{"name": "y", "derived": "lambda: 1",
                              "axioms": ["HOMEOSTASIS"], "window": "1h"}])
    assert remedies and "not an arithmetic expression" in remedies[0]


def test_a_flat_derivation_is_accepted():
    assert _underivable([SPREAD]) == []


# --- the side effect --------------------------------------------------------

def test_an_operand_is_read_by_something_the_author_declared():
    """Without this, feeding both operands to a model whose only use of them is
    the derivation reports both as read by nobody -- which would send an author
    to delete the feed the indicator depends on."""
    session = _session({"inlet_c": 101.0, "outlet_c": 100.0})
    assert check(session).to_dict()["unread_properties"] == []


def test_a_property_nothing_reads_is_still_reported():
    """The discriminator: counting operands as read must not silence the
    report it was widened for."""
    session = _session({"inlet_c": 101.0, "outlet_c": 100.0, "stray": 7.0})
    unread = check(session).to_dict()["unread_properties"]
    assert [u["property"] for u in unread] == ["stray"]
