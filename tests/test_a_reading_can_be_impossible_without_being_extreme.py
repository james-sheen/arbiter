"""Three ways a number is wrong that no threshold can see.

NOT A MEASUREMENT AT ALL. NaN compares False against everything, so a threshold
is never breached, a count is never negative and a setpoint is never departed
from: the cell produces no finding and no decline. Measured before the guard
below existed, a NaN on an indicator declaring BOUNDEDNESS and CONSISTENCY
returned a completely clean pass. Infinity is worse than silent — it compares
fine, so BOUNDEDNESS reports `threshold_exceeded`, which is a precise wrong
answer sending somebody to look at a quantity when the sensor is broken.

BETWEEN THE STEPS IT CAN TAKE. A quantised quantity — a tick, a lot, a dial
position — has values it cannot hold, and one of those is not high or low, it
is impossible.

IMPOSSIBLE IN COMPANY. Two readings individually plausible and contradictory
together, which single-value plausibility cannot see by construction.

WHY NO NEW ROLE WORDS. The design this implements proposed four roles --
`price`, `quantity`, `amount`, `rate` -- whose stated built-in rules were
`finite` for all four, non-negativity for one, and a grid for two. Finite is
true of EVERY numeric indicator, so gating it behind a declared role would mean
opting in to having NaN noticed; non-negativity is what `count` already does;
and a grid is better said as a number than implied by a domain's word for its
own quantities. All four remain expressible -- the last test here shows it --
without the engine learning any of those words.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, check
from arbiter_engine.clock import as_of
from arbiter_engine.ontology.axioms.roles import (
    UNGATED_CONSISTENCY_KEYS,
)
from arbiter_engine.ontology.domain_loader import load_domain

T0 = datetime(2026, 6, 1, 12, 0)
AT = T0 + timedelta(minutes=6)


def _session(indicator, properties, extra_entities=()):
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Unit", "Peer"],
        "relationship_types": ["paired_with"],
        "indicators": {"Unit": [indicator]}}})
    session.add_entity("u1", "Unit", dict(properties))
    for entity_id, props in extra_entities:
        session.add_entity(entity_id, "Peer", dict(props))
        session.add_relationship("u1", "paired_with", entity_id)
    return session


def _run(session, feed=None):
    if feed is not None:
        for index in range(5):
            session.history.add("u1", "setting", feed,
                                timestamp=T0 + timedelta(minutes=index))
    with as_of(AT):
        return check(session).to_dict()


# --- not a measurement ------------------------------------------------------

GUARDED = {"name": "setting", "type": "NUMERIC",
           "axioms": ["BOUNDEDNESS", "CONSISTENCY"], "window": "1h",
           "critical": 1000, "role": "count"}


@pytest.mark.parametrize("value,name", [
    (float("nan"), "NaN"),
    (float("inf"), "infinity"),
    (float("-inf"), "negative infinity"),
])
def test_a_non_finite_reading_stops_every_axiom(value, name):
    """EVERY axiom, not one: the value is not a number, so none of them can
    judge the cell, and each says so rather than comparing against it."""
    envelope = _run(_session(GUARDED, {"setting": value}), feed=1.0)
    reasons = {(d["reason"], d["axiom"]) for d in envelope["not_checked"]}
    assert reasons == {("undefined_for_values", "BOUNDEDNESS"),
                       ("undefined_for_values", "CONSISTENCY")}
    assert envelope["findings"] == []
    assert name in envelope["not_checked"][0]["detail"]


def test_infinity_no_longer_reports_a_threshold_breach():
    """The precise wrong answer. A sensor returning infinity is broken, and
    `threshold_exceeded` sends somebody to look at the quantity instead."""
    envelope = _run(_session(GUARDED, {"setting": float("inf")}), feed=1.0)
    assert [f["problem_type"] for f in envelope["findings"]] == []


def test_a_non_numeric_indicator_is_left_to_its_own_axiom():
    """The guard's warrant is numeric comparison, so it stops at the type.
    Checked rather than assumed: thirty identical `NaN` readings on a STATE
    indicator report no flapping, so nothing downstream is silently misreading
    them and there is nothing here for this guard to rescue."""
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Unit"],
        "indicators": {"Unit": [
            {"name": "state", "type": "STATE", "axioms": ["STABILITY"],
             "window": "2h", "max_transitions": 2}]}}})
    session.add_entity("u1", "Unit", {"state": float("nan")})
    for index in range(30):
        session.history.add("u1", "state", float("nan"),
                            timestamp=T0 + timedelta(seconds=index * 30))
    with as_of(T0 + timedelta(minutes=15)):
        envelope = check(session).to_dict()
    assert envelope["not_checked"] == []
    assert envelope["findings"] == []


def test_a_finite_reading_is_untouched():
    """The discriminator: a guard that declined everything would satisfy the
    tests above and make the engine useless."""
    envelope = _run(_session(GUARDED, {"setting": 42.0}), feed=1.0)
    assert envelope["not_checked"] == []
    assert envelope["findings"] == []


def test_the_existing_rules_still_fire_on_finite_values():
    envelope = _run(_session(GUARDED, {"setting": -5.0}), feed=1.0)
    assert [f["problem_type"] for f in envelope["findings"]] == ["impossible_value"]


def test_a_breach_is_still_a_breach():
    envelope = _run(_session(GUARDED, {"setting": 5000.0}), feed=1.0)
    assert "threshold_exceeded:setting" in [f["problem_type"]
                                            for f in envelope["findings"]]


# --- between the steps ------------------------------------------------------

def _grid_indicator(grid=0.5, **extra):
    indicator = {"name": "setting", "type": "NUMERIC", "axioms": ["CONSISTENCY"],
                 "window": "1h", "consistency": {"grid": grid}}
    indicator["consistency"].update(extra)
    return indicator


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0, 100.0, -2.5])
def test_a_reading_on_the_grid_is_accepted(value):
    assert _run(_session(_grid_indicator(), {"setting": value}))["findings"] == []


@pytest.mark.parametrize("value", [0.25, 100.3, -2.6])
def test_a_reading_between_the_steps_is_impossible(value):
    findings = _run(_session(_grid_indicator(), {"setting": value}))["findings"]
    assert [f["problem_type"] for f in findings] == ["impossible_value"]
    assert "not a multiple of the declared grid" in findings[0]["reason"]


#: Readings whose quotient by 0.01 is NOT an exact integer in binary. MEASURED,
#: not chosen for looking awkward: the first version of this list was 100.01,
#: 0.07, 12.34 and 1e6+0.01, every one of which divides exactly, so the test
#: claimed to guard the tolerance while a tolerance of zero passed it. The
#: errors here are 4.4e-16, 1.4e-14 and 1.1e-16 of the reading.
OFF_BY_BINARY = (3.03, 70.07, 0.57)


def test_binary_floating_point_does_not_make_every_tick_off_grid():
    """A check with no tolerance calls a real reading impossible, which is the
    way this rule would most likely have been wrong."""
    for value in OFF_BY_BINARY:
        assert round(value / 0.01) * 0.01 != value, value   # the premise
        envelope = _run(_session(_grid_indicator(grid=0.01), {"setting": value}))
        assert envelope["findings"] == [], value


def test_the_nearest_step_is_the_nearest_one_and_not_the_one_below():
    """Truncating instead of rounding calls a reading just under a step
    impossible and, when it does fire, names a step further away than the one
    the author would reach for."""
    for value in (0.29, 0.57, 70.07):
        assert int(value / 0.01) * 0.01 != value, value     # the premise
        assert _run(_session(_grid_indicator(grid=0.01),
                             {"setting": value}))["findings"] == [], value
    findings = _run(_session(_grid_indicator(), {"setting": 100.3}))["findings"]
    assert "the nearest value it could take is 100.5" in findings[0]["reason"]


def test_a_grid_needs_no_role():
    """Outside the role gate, like `agrees_with`: the grid is declared
    directly, so requiring a role beside it asks twice for one fact."""
    indicator = _grid_indicator()
    assert "role" not in indicator
    assert _run(_session(indicator, {"setting": 0.25}))["findings"]


def test_a_nonsense_grid_is_ignored_rather_than_dividing_by_zero():
    for grid in (0, -1, "wide"):
        assert _run(_session(_grid_indicator(grid=grid),
                             {"setting": 0.25}))["findings"] == []


# --- impossible in company --------------------------------------------------

def _ordered_indicator(upper="ceiling"):
    return {"name": "setting", "type": "NUMERIC", "axioms": ["CONSISTENCY"],
            "window": "1h", "consistency": {"ordered_below": upper}}


def test_a_reading_below_its_declared_ceiling_is_accepted():
    assert _run(_session(_ordered_indicator(),
                         {"setting": 10.0, "ceiling": 20.0}))["findings"] == []


def test_equal_is_below_enough():
    """`ordered_below` is not `strictly_below`; a reading touching its ceiling
    is the boundary case a strict reading would call a fault."""
    assert _run(_session(_ordered_indicator(),
                         {"setting": 20.0, "ceiling": 20.0}))["findings"] == []


def test_a_reading_above_its_declared_ceiling_is_impossible():
    findings = _run(_session(_ordered_indicator(),
                             {"setting": 30.0, "ceiling": 20.0}))["findings"]
    assert [f["problem_type"] for f in findings] == ["impossible_value"]
    # Read from the reason, because the envelope does not publish `evidence`:
    # a finding carries entity, type, axiom, severity and prose. Asserted here
    # against what a consumer can actually see, after a first version of this
    # test read a key the serialiser drops.
    assert "reads 30 and is declared to sit below ceiling, which reads 20" \
        in findings[0]["reason"]
    assert findings[0]["severity"] == "high"


def test_both_readings_can_be_individually_plausible():
    """The point of the rule. Neither 30 nor 20 breaches anything on its own;
    they are impossible together, and no threshold can see that."""
    indicator = dict(_ordered_indicator(), critical=1000)
    envelope = _run(_session(indicator, {"setting": 30.0, "ceiling": 20.0}))
    assert [f["problem_type"] for f in envelope["findings"]] == ["impossible_value"]


def test_a_ceiling_the_entity_does_not_carry_declines():
    envelope = _run(_session(_ordered_indicator(), {"setting": 30.0}))
    assert [d["reason"] for d in envelope["not_checked"]] == ["missing_property"]


def test_a_ceiling_that_is_not_a_number_declines_rather_than_raising():
    """The entity carries the property, so it is not missing -- it is unusable,
    and `float()` on it raises. A comparison this check cannot make is a
    decline, not a traceback out of the public API."""
    envelope = _run(_session(_ordered_indicator(),
                             {"setting": 30.0, "ceiling": "twenty"}))
    assert [d["reason"] for d in envelope["not_checked"]] == ["undefined_for_values"]
    assert "needs two numbers" in envelope["not_checked"][0]["detail"]


def test_a_ceiling_on_another_entity_is_reached_across_the_edge():
    """The same reference syntax the balance and the agreement take."""
    indicator = _ordered_indicator(
        {"via": "paired_with", "property": "ceiling", "aggregate": "min"})
    envelope = _run(_session(indicator, {"setting": 30.0},
                             extra_entities=[("p1", {"ceiling": 20.0})]))
    assert [f["problem_type"] for f in envelope["findings"]] == ["impossible_value"]


def test_an_edge_that_reaches_nobody_declines():
    indicator = _ordered_indicator({"via": "nowhere", "property": "ceiling"})
    envelope = _run(_session(indicator, {"setting": 30.0}))
    assert [d["reason"] for d in envelope["not_checked"]] == ["precondition_unmet"]


# --- what the author is told ------------------------------------------------

def _unreachable(indicator):
    model = load_domain({"domain": {"id": "d", "name": "d",
                                    "entity_types": ["Unit"],
                                    "indicators": {"Unit": [indicator]}}})
    return model.unreachable_declarations()


BARE = {"name": "setting", "type": "NUMERIC", "axioms": ["CONSISTENCY"],
        "window": "1h"}


def test_an_indicator_with_no_role_and_no_block_is_still_unreachable():
    assert len(_unreachable(BARE)) == 1


@pytest.mark.parametrize("key,value", [
    ("agrees_with", ["mid"]), ("grid", 0.5), ("ordered_below", "ceiling"),
])
def test_every_ungated_key_makes_the_axiom_reachable(key, value):
    assert _unreachable(dict(BARE, consistency={key: value})) == []


def test_the_remedy_names_every_way_rather_than_one():
    """It named `agrees_with` alone while three keys reached this axiom, which
    would send an author to declare a redundant peer they do not have."""
    remedy = _unreachable(BARE)[0]["remedy"]
    for key in UNGATED_CONSISTENCY_KEYS:
        assert f"`{key}`" in remedy


def test_the_checker_and_the_report_read_one_list():
    """They drifted the moment a third key was added. Asserted as identity of
    the source, not equality of two transcriptions."""
    assert UNGATED_CONSISTENCY_KEYS == ("agrees_with", "grid", "ordered_below")


# --- the design claim -------------------------------------------------------

def test_the_four_proposed_roles_are_expressible_without_new_role_words():
    """`price`, `quantity`, `amount` and `rate` were the four roles proposed.
    Each is declarable with what already exists plus what this change added,
    and the engine learns none of those words.
    """
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Unit"],
        "indicators": {"Unit": [
            # a price: on a tick grid, under a ceiling, no positivity rule
            # because negative prices happen
            {"name": "unit_rate", "type": "NUMERIC", "axioms": ["CONSISTENCY"],
             "window": "1h",
             "consistency": {"grid": 0.01, "ordered_below": "cap"}},
            # a quantity: non-negative via the role that already means that,
            # on a lot grid
            {"name": "volume", "type": "NUMERIC", "role": "count",
             "axioms": ["CONSISTENCY"], "window": "1h",
             "consistency": {"grid": 5}},
            # an amount and a rate: finite is all that is universally true,
            # and that is now checked for every numeric indicator
            {"name": "balance", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
             "window": "1h", "lower_critical": -1e9, "critical": 1e9},
        ]}}})
    session.add_entity("u1", "Unit", {"unit_rate": 10.005, "cap": 9.0,
                                      "volume": -3.0, "balance": float("nan")})
    envelope = _run(session)
    # FOUR, not three: the off-grid rate, the rate above its cap, the negative
    # volume and the off-grid volume. The count was written as three first,
    # forgetting that one indicator can be impossible in two ways at once.
    named = sorted(name for f in envelope["findings"]
                   for name in ("unit_rate", "volume") if name in f["reason"])
    assert named == ["unit_rate", "unit_rate", "volume", "volume"]
    assert {f["problem_type"] for f in envelope["findings"]} == {"impossible_value"}
    assert [d["reason"] for d in envelope["not_checked"]] == ["undefined_for_values"]


# --- one predicate, two questions -------------------------------------------

def test_a_grid_alone_is_not_a_declared_redundancy():
    """The defect this separation fixes. While one predicate answered both
    *may CONSISTENCY run* and *is there an agreement to check*, an indicator
    declaring only a grid entered the agreement arm and declined for a missing
    `tolerance:` -- asking its author how close two readings must be when they
    had never named a second reading."""
    envelope = _run(_session(_grid_indicator(), {"setting": 0.5}))
    assert envelope["not_checked"] == []
    assert envelope["findings"] == []


def test_an_ordering_alone_is_not_a_declared_redundancy():
    envelope = _run(_session(_ordered_indicator(),
                             {"setting": 10.0, "ceiling": 20.0}))
    assert envelope["not_checked"] == []


def test_an_agreement_alone_still_demands_its_tolerance():
    """The discriminator: narrowing the gate must not have switched the demand
    off, which would restore the silent 5% this decline replaced."""
    indicator = {"name": "setting", "type": "NUMERIC", "axioms": ["CONSISTENCY"],
                 "window": "1h", "consistency": {"agrees_with": ["mirror"]}}
    envelope = _run(_session(indicator, {"setting": 10.0, "mirror": 10.2}))
    assert [d["reason"] for d in envelope["not_checked"]] == ["missing_config"]


def test_an_empty_block_gives_the_axiom_nothing_to_do():
    """Presence of the key is not declaration of a rule. Reading these as
    declared would report the pair reachable and tell an author their empty
    block was working."""
    for key, empty in (("agrees_with", []), ("grid", 0), ("ordered_below", "")):
        assert len(_unreachable(dict(BARE, consistency={key: empty}))) == 1, key


def test_a_misspelled_key_is_caught_by_the_reachability_report():
    """The consistency block is passed through opaquely, so a typo is not an
    error -- the key is simply never read. What catches it is the pair going
    unreachable, and the remedy then spells the three keys correctly."""
    report = _unreachable(dict(BARE, consistency={"orderd_below": "ceiling"}))
    assert len(report) == 1
    assert "`ordered_below`" in report[0]["remedy"]
