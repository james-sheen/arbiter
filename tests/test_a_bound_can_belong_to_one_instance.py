"""Every account has its own margin line.

A DECLARED BOUND WAS A FACT ABOUT AN ENTITY TYPE. `critical: 1000000` on
`margin_balance` says every account in the book has the same requirement, which
is false of every book; expressing the truth meant one entity type per account,
and a model with one type per instance has stopped being a model.

TWO WAYS IN, AND THEY ANSWER DIFFERENT QUESTIONS. `{from_property: ...}` in the
model says the bound is a number that arrives with the entity from whatever
system owns it -- a margin requirement, a contracted ceiling, a regulatory floor
-- and it moves when the data moves with nobody calling anything.
`set_declared_thresholds` says THIS entity's bound, set by a caller, reaching
indicators whose model declares a literal or nothing at all, which the first
cannot.

NOT `set_threshold_override`, which sits one method above it and does something
else: that one replaces an axiom's CALIBRATION parameter and says in its own
docstring that it does not touch a declared bound. BOUNDEDNESS is in
`OVERRIDE_NOT_CONSULTED` for exactly that reason. The two tables are kept apart
below, because a caller who confuses them gets silence either way.

A DECLARED BOUND THAT CANNOT BE RESOLVED IS NOT NO BOUND. The first is a check
the author asked for and the engine could not run; the second is a check nobody
asked for. Treating one as the other is the `axioms: [BOUNDEDNES]` shape -- a
clean envelope for a question that never got asked.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, check, model_describe
from arbiter_engine.axiom_thresholds import (
    AXIOM_THRESHOLD_OVERRIDES_KEY,
    DECLARED_THRESHOLDS_KEY,
    THRESHOLD_FIELDS,
    effective_thresholds,
)
from arbiter_engine.ontology import domain_loader

T0 = datetime(2026, 6, 1, 12, 0)
AT = T0 + timedelta(minutes=16)

FROM_DATA = {"name": "margin_balance", "type": "NUMERIC",
             "axioms": ["BOUNDEDNESS"], "window": "1h",
             "lower_critical": {"from_property": "margin_requirement"}}
LITERAL = {"name": "margin_balance", "type": "NUMERIC",
           "axioms": ["BOUNDEDNESS"], "window": "1h", "lower_critical": 0}


def _session(indicator, entities):
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Acct"],
        "indicators": {"Acct": [indicator]}}})
    for entity_id, props in entities.items():
        session.add_entity(entity_id, "Acct", dict(props))
    return session


def _run(session):
    from arbiter_engine.clock import as_of
    with as_of(AT):
        return check(session).to_dict()


def _kinds(envelope):
    return [(f["entity_id"], f["problem_type"]) for f in envelope["findings"]]


# --- the bound arrives with the data ---------------------------------------

def test_two_accounts_are_judged_against_their_own_requirements():
    """The whole point, in one assertion: one book, one entity type, one
    indicator, and two different lines."""
    envelope = _run(_session(FROM_DATA, {
        "acct_7": {"margin_balance": 9.0e5, "margin_requirement": 1.0e6},
        "acct_8": {"margin_balance": 9.0e5, "margin_requirement": 5.0e5},
    }))
    assert _kinds(envelope) == [
        ("acct_7", "below_critical_threshold:margin_balance")]


def test_the_bound_moves_when_the_data_moves():
    session = _session(FROM_DATA, {
        "acct_7": {"margin_balance": 9.0e5, "margin_requirement": 5.0e5}})
    assert _run(session)["findings"] == []
    session.entities["acct_7"].properties["margin_requirement"] = 1.0e6
    assert len(_run(session)["findings"]) == 1


def test_a_bound_declared_and_not_arrived_declines_naming_the_property():
    """NOT a clean pass, and not `no rule declared` either. The author wrote a
    floor; the feed carrying it has not turned up."""
    envelope = _run(_session(FROM_DATA, {"acct_7": {"margin_balance": 9.0e5}}))
    assert [d["reason"] for d in envelope["not_checked"]] == ["no_threshold"]
    detail = envelope["not_checked"][0]["detail"]
    # THE WORDING, not just the property name. *Has not arrived* and *is not a
    # number* both decline naming the same property, and they send an author to
    # different places -- one to the feed, one to what the feed is sending. A
    # test that only looked for `margin_requirement` stayed green with the
    # not-arrived arm deleted, because `float(None)` raises into the other one.
    assert "carries no margin_requirement" in detail
    assert "resolved to" not in detail
    assert envelope["findings"] == []


@pytest.mark.parametrize("bad", ["soon", float("nan"), float("inf")])
def test_a_bound_that_is_not_a_finite_number_declines(bad):
    """A threshold read from data is data, and data is wrong sometimes. NaN is
    the one that matters: every comparison against it is False, so a NaN floor
    would silently pass every account in the book."""
    envelope = _run(_session(FROM_DATA, {
        "acct_7": {"margin_balance": 9.0e5, "margin_requirement": bad}}))
    assert [d["reason"] for d in envelope["not_checked"]] == ["no_threshold"]
    assert "margin_requirement" in envelope["not_checked"][0]["detail"]
    assert envelope["findings"] == []


def test_a_mapping_the_loader_cannot_read_is_reported_not_dropped():
    """Silently ignoring it gives the author an indicator with no bound, which
    looks exactly like never having declared one."""
    session = _session(dict(FROM_DATA, lower_critical={"tick": 5}),
                       {"acct_7": {"margin_balance": 9.0e5}})
    dropped = session.dropped_declarations()
    assert [(d["field"], d["reason"]) for d in dropped] == [
        ("lower_critical", "unknown_value")]
    assert "from_property" in dropped[0]["remedy"]


def test_a_literal_is_untouched_by_any_of_this():
    """The discriminator. Every model in the world declares literal bounds and
    they must behave exactly as before."""
    envelope = _run(_session(dict(LITERAL, critical=1.0e6), {
        "acct_7": {"margin_balance": -1.0},
        "acct_8": {"margin_balance": 2.0e6},
        "acct_9": {"margin_balance": 5.0e5},
    }))
    assert sorted(_kinds(envelope)) == [
        ("acct_7", "below_critical_threshold:margin_balance"),
        ("acct_8", "threshold_exceeded:margin_balance")]


# --- the caller sets one -----------------------------------------------------

def test_one_account_can_be_given_its_own_line():
    session = _session(LITERAL, {"acct_7": {"margin_balance": 9.0e5},
                                 "acct_8": {"margin_balance": 9.0e5}})
    assert _run(session)["findings"] == []
    session.set_declared_thresholds("acct_7", "margin_balance",
                                    lower_critical=1.0e6)
    assert _kinds(_run(session)) == [
        ("acct_7", "below_critical_threshold:margin_balance")]


def test_it_reaches_an_indicator_whose_model_declares_nothing():
    """What `{from_property:}` cannot do: there is no key on the indicator to
    hang a source off, and no model edit is being asked for."""
    bare = {"name": "margin_balance", "type": "NUMERIC",
            "axioms": ["BOUNDEDNESS"], "window": "1h"}
    session = _session(bare, {"acct_7": {"margin_balance": 9.0e5}})
    session.set_declared_thresholds("acct_7", "margin_balance",
                                    lower_critical=1.0e6)
    assert len(_run(session)["findings"]) == 1


def test_passing_none_removes_it_rather_than_storing_a_null():
    session = _session(LITERAL, {"acct_7": {"margin_balance": 9.0e5}})
    session.set_declared_thresholds("acct_7", "margin_balance",
                                    lower_critical=1.0e6)
    assert len(_run(session)["findings"]) == 1
    session.set_declared_thresholds("acct_7", "margin_balance",
                                    lower_critical=None)
    assert _run(session)["findings"] == []
    assert not session.entities["acct_7"].properties[DECLARED_THRESHOLDS_KEY]


def test_an_instance_bound_wins_over_the_property_it_would_have_read():
    """Precedence stated rather than left to whichever arm runs first."""
    session = _session(FROM_DATA, {
        "acct_7": {"margin_balance": 9.0e5, "margin_requirement": 1.0e6}})
    assert len(_run(session)["findings"]) == 1
    session.set_declared_thresholds("acct_7", "margin_balance",
                                    lower_critical=5.0e5)
    assert _run(session)["findings"] == []


def test_a_keyword_that_is_not_a_bound_is_refused_at_the_call():
    """REFUSED, unlike a model file, which is reported. A keyword argument is a
    typo in the caller's own source and they are standing in front of it."""
    session = _session(LITERAL, {"acct_7": {"margin_balance": 1.0}})
    with pytest.raises(ValueError, match="lower_criticall"):
        session.set_declared_thresholds("acct_7", "margin_balance",
                                        lower_criticall=1.0)


def test_an_entity_the_session_does_not_hold_raises():
    session = _session(LITERAL, {"acct_7": {"margin_balance": 1.0}})
    with pytest.raises(KeyError, match="add_entity first"):
        session.set_declared_thresholds("nobody", "margin_balance", critical=1.0)


def test_the_two_tables_are_not_the_same_table():
    """`set_threshold_override` and this one are different capabilities, and a
    caller who confuses them gets silence either way. Kept apart so that the
    override report can keep classifying by axiom -- which has no answer for an
    entry that names no axiom."""
    session = _session(LITERAL, {"acct_7": {"margin_balance": 1.0}})
    session.set_declared_thresholds("acct_7", "margin_balance", critical=1.0)
    session.set_threshold_override("acct_7", "margin_balance", "HOMEOSTASIS",
                                   warning=2.0)
    props = session.entities["acct_7"].properties
    assert AXIOM_THRESHOLD_OVERRIDES_KEY != DECLARED_THRESHOLDS_KEY
    assert list(props[DECLARED_THRESHOLDS_KEY]) == [("margin_balance", "critical")]
    assert list(props[AXIOM_THRESHOLD_OVERRIDES_KEY]) == [
        ("margin_balance", "HOMEOSTASIS")]


# --- the other two readers ---------------------------------------------------

def test_responsiveness_reads_a_bound_that_is_not_on_the_spec():
    """Asked of the resolver, not the spec. Reading the spec here declines *no
    threshold declared* at an indicator that declares one, and the author goes
    looking for a missing `critical:` that is in front of them."""
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Svc"], "indicators": {"Svc": [
            {"name": "latency_ms", "type": "NUMERIC", "role": "latency",
             "axioms": ["RESPONSIVENESS"], "window": "1h",
             "critical": {"from_property": "sla_ms"}}]}}})
    session.add_entity("s1", "Svc", {"latency_ms": 900.0, "sla_ms": 500.0})
    for index in range(12):
        session.history.add("s1", "latency_ms", 900.0,
                            timestamp=T0 + timedelta(seconds=index * 30))
    envelope = _run(session)
    assert [f["problem_type"] for f in envelope["findings"]] == [
        "response_time_critical:latency_ms"]
    # NOT read off `evidence`, which the envelope does not publish -- the first
    # version of this line asserted into that key behind an inline `if`, so it
    # evaluated to a bare `assert True` and guarded nothing. The discriminator
    # is that the SAME latency is clean under a laxer SLA on the same model.
    session.entities["s1"].properties["sla_ms"] = 2000.0
    assert _run(session)["findings"] == []


def test_homeostasis_reads_a_setpoint_that_is_not_on_the_spec():
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Room"], "indicators": {"Room": [
            {"name": "temp", "type": "NUMERIC", "axioms": ["HOMEOSTASIS"],
             "window": "1h", "homeostasis": {
                 "setpoint": {"from_property": "target_temp"},
                 "tolerance": 2.0}}]}}})
    session.add_entity("r1", "Room", {"temp": 40.0, "target_temp": 20.0})
    for index in range(12):
        session.history.add("r1", "temp", 40.0,
                            timestamp=T0 + timedelta(seconds=index * 30))
    assert [f["problem_type"] for f in _run(session)["findings"]] == [
        "homeostasis_setpoint:temp"]


def test_a_setpoint_from_a_property_the_entity_lacks_falls_back_not_fires():
    """The existing contract for an unusable setpoint: abandon the setpoint
    path and use the learned baseline. Kept, rather than turned into a new
    decline, because that is what every other unusable setpoint already does."""
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Room"], "indicators": {"Room": [
            {"name": "temp", "type": "NUMERIC", "axioms": ["HOMEOSTASIS"],
             "window": "1h", "homeostasis": {
                 "setpoint": {"from_property": "target_temp"},
                 "tolerance": 2.0}}]}}})
    session.add_entity("r1", "Room", {"temp": 40.0})
    for index in range(12):
        session.history.add("r1", "temp", 40.0,
                            timestamp=T0 + timedelta(seconds=index * 30))
    assert [f["problem_type"] for f in _run(session)["findings"]] == []


# --- what the reader is told -------------------------------------------------

def test_the_summary_says_how_much_is_not_from_the_model():
    session = _session(FROM_DATA, {
        "acct_7": {"margin_balance": 9.0e5, "margin_requirement": 1.0e6},
        "acct_8": {"margin_balance": 9.0e5}})
    session.set_declared_thresholds("acct_7", "margin_balance", critical=1.0e7)
    summary = session.instance_thresholds()
    assert summary == {"entities": 1, "fields": ["critical", "lower_critical"],
                       "by_origin": {"instance": 1, "property": 1}}


def test_the_summary_is_a_summary_and_not_a_row_per_bound():
    """A listing grows with the session. On a book of ten thousand accounts it
    would be ten thousand rows of ordinary configuration in front of the
    findings, which is why the shape is counts."""
    session = _session(LITERAL, {f"acct_{n}": {"margin_balance": 1.0}
                                 for n in range(200)})
    for n in range(200):
        session.set_declared_thresholds(f"acct_{n}", "margin_balance",
                                        critical=float(n))
    summary = session.instance_thresholds()
    assert summary["entities"] == 200
    assert summary["fields"] == ["critical"]
    assert len(str(summary)) < 200


def test_a_bound_set_on_an_indicator_the_model_does_not_declare_is_reported():
    session = _session(LITERAL, {"acct_7": {"margin_balance": 1.0}})
    session.set_declared_thresholds("acct_7", "no_such_thing", critical=5.0)
    assert [(r["indicator"], r["reason"])
            for r in session.unread_declared_thresholds()] == [
        ("no_such_thing", "undeclared_indicator")]


def test_a_bound_on_an_indicator_with_no_axiom_that_reads_one_is_reported():
    """Different remedy, so a different reason. The indicator exists; the check
    that would consult the number is not declared on it."""
    session = _session({"name": "margin_balance", "type": "NUMERIC",
                        "axioms": ["STABILITY"], "window": "1h"},
                       {"acct_7": {"margin_balance": 1.0}})
    session.set_declared_thresholds("acct_7", "margin_balance", critical=5.0)
    assert [r["reason"] for r in session.unread_declared_thresholds()] == [
        "axiom_not_declared"]


def test_a_bound_that_will_be_read_is_not_reported_as_unread():
    session = _session(LITERAL, {"acct_7": {"margin_balance": 1.0}})
    session.set_declared_thresholds("acct_7", "margin_balance", critical=5.0)
    assert session.unread_declared_thresholds() == []


def test_both_reports_ride_the_describe_payload():
    session = _session(LITERAL, {"acct_7": {"margin_balance": 1.0}})
    payload = model_describe(session).to_dict()
    assert "instance_thresholds" in payload
    assert "unread_declared_thresholds" in payload


def test_an_entity_bound_is_not_handed_to_the_type_wide_overlay():
    """The overlay retunes a number for a whole entity TYPE: it is keyed by
    (domain, indicator, threshold_type) and knows nothing about which entity it
    is being asked about, so passing an account's own margin requirement
    through it would replace every account's line with one number.

    Needs an overlay wired to be falsifiable at all. Without one the resolver
    and the overlay path return the same value, and the guard could be deleted
    with every other test in this file still green -- which is what happened.
    """
    class _FlatOverlay:
        """Answers for ONE field and defers on the rest.

        A version answering 1.0 for all four made every band contradictory --
        a floor at or above its own ceiling -- so the cell declined instead of
        firing and the test failed for a reason that had nothing to do with
        what it was asking.
        """
        def get_threshold(self, domain, indicator, threshold_type, default):
            return 1.0 if threshold_type == "lower_critical" else default

    session = _session(FROM_DATA, {
        "acct_7": {"margin_balance": 9.0e5, "margin_requirement": 1.0e6}})
    session.entities["acct_7"].metadata = {"domain_id": "d"}
    wired = 0
    for checker in session.reasoner._axiom_checkers.values():
        if hasattr(checker, "overlay"):
            checker.overlay = _FlatOverlay()
            wired += 1
    assert wired, "no checker took the overlay; this would prove nothing"
    # The account is below its OWN requirement and far above the overlay's 1.0.
    # If the overlay had the last word there would be no finding at all.
    assert _kinds(_run(session)) == [
        ("acct_7", "below_critical_threshold:margin_balance")]


def test_the_feeder_speaks_the_model_own_vocabulary():
    """The checkers look the bound up under `property_name`, which differs from
    the declared name exactly when the model carries a `property_mapping`.
    Keying on the declared name stores it where nothing will look."""
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Acct"],
        "property_mapping": {"Acct": {"margin_balance": "bal_usd"}},
        "indicators": {"Acct": [LITERAL]}}})
    session.add_entity("acct_7", "Acct", {"bal_usd": 9.0e5})
    session.set_declared_thresholds("acct_7", "margin_balance",
                                    lower_critical=1.0e6)
    assert list(session.entities["acct_7"].properties[DECLARED_THRESHOLDS_KEY]) \
        == [("bal_usd", "lower_critical")]
    assert len(_run(session)["findings"]) == 1


def test_the_payload_carries_the_summary_and_not_just_the_key():
    """Asserting the key is present passes on an empty dict, and an empty
    report reads exactly like nothing to report."""
    session = _session(FROM_DATA, {
        "acct_7": {"margin_balance": 9.0e5, "margin_requirement": 1.0e6}})
    session.set_declared_thresholds("acct_7", "margin_balance", critical=1.0e7)
    payload = model_describe(session).to_dict()
    assert payload["instance_thresholds"]["entities"] == 1
    assert payload["instance_thresholds"]["by_origin"] == {
        "instance": 1, "property": 1}
    session.set_declared_thresholds("acct_8" if False else "acct_7",
                                    "no_such_thing", critical=1.0)
    assert [r["reason"] for r in
            model_describe(session).to_dict()["unread_declared_thresholds"]] == [
        "undeclared_indicator"]


# --- the list itself ---------------------------------------------------------

def test_the_loader_and_the_resolver_read_one_list():
    """Written out in both for an afternoon, with a comment claiming a test
    pinned them equal -- a test that did not exist. Asserted as identity of the
    object, which no second copy can satisfy."""
    assert domain_loader.THRESHOLD_FIELDS is THRESHOLD_FIELDS
    assert THRESHOLD_FIELDS == ("warning", "critical",
                                "lower_warning", "lower_critical")


def test_the_resolver_names_where_each_bound_came_from():
    """Returned rather than inferred: the three cases produce the same kind of
    number, and a reader who has to act needs to know which system to go and
    look at."""
    session = _session(dict(FROM_DATA, critical=1.0e7), {
        "acct_7": {"margin_balance": 9.0e5, "margin_requirement": 1.0e6}})
    session.set_declared_thresholds("acct_7", "margin_balance", warning=2.0)
    spec = session.model.indicators["Acct"][0]
    values, origins, detail = effective_thresholds(
        session.entities["acct_7"], spec)
    assert detail is None
    assert origins == {"warning": "instance", "critical": "declared",
                       "lower_warning": "absent", "lower_critical": "property"}
    assert values["warning"] == 2.0
    assert values["critical"] == 1.0e7
    assert values["lower_critical"] == 1.0e6
    assert values["lower_warning"] is None


def test_a_contradictory_band_is_caught_across_mechanisms():
    """The band is assembled from three different places and checked as one.
    Resolving the four at different moments would check a band against itself."""
    session = _session(dict(LITERAL, critical=100.0), {
        "acct_7": {"margin_balance": 50.0}})
    session.set_declared_thresholds("acct_7", "margin_balance",
                                    lower_critical=500.0)
    envelope = _run(session)
    assert [d["reason"] for d in envelope["not_checked"]] == ["missing_config"]
    assert "is at or above critical" in envelope["not_checked"][0]["detail"]
