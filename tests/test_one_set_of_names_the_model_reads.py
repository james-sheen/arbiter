"""Three readers answered *which properties does this model read* differently.

`unread_properties` counted an indicator's own name, a derived indicator's
operands and a `{from_property:}` bound's source. `unconsumed_observations`
counted only the first, so one report called a fed `margin_requirement`
`undeclared_property` while its sibling counted it as read -- about the same
declaration, in the same envelope. `sync_current_from_history` iterated
indicator SPECS, so a replay never advanced a bound's source at all.

THE REPLAY CASE IS THE ONE THAT BITES, and it is silent. A model whose floor is
`lower_critical: {from_property: margin_requirement}` has that floor advanced by
nothing: the balance moves with the clock and the requirement stays at whatever
was fed at construction, so every step after the first checks today's balance
against step one's floor. No decline fires, because from the axiom's side the
bound resolved perfectly well.

The workaround was to declare the source a second time as an `axioms: []`
indicator -- which the shipped example and the margin-book bridge were both
doing. A report that trains authors around itself is the thing these reports
exist to prevent.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from arbiter_engine import replay
from arbiter_engine.api import EngineSession
from arbiter_engine.clock import as_of

T0 = datetime(2026, 9, 17, 9, 35)
SENTINEL = -1.0


def _session() -> EngineSession:
    """A model that reads three KINDS of name and declares only one of them."""
    session = EngineSession()
    session.load_model({"domain": {
        "id": "book", "name": "book", "entity_types": ["Account"],
        "indicators": {"Account": [
            {"name": "margin_balance", "type": "NUMERIC",
             "axioms": ["BOUNDEDNESS"], "window": "1h", "lookback": "7d",
             "lower_critical": {"from_property": "margin_requirement"}},
            {"name": "basis", "type": "NUMERIC", "axioms": [],
             "derived": "futures - spot"},
        ]}}})
    session.add_entity("a1", "Account", {
        "margin_balance": 1000.0, "margin_requirement": 900.0,
        "futures": 101.0, "spot": 100.0})
    base = T0 - timedelta(days=1)
    for name in ("margin_balance", "margin_requirement", "futures", "spot"):
        session.add_observations("a1", name, [
            (base + timedelta(minutes=7 * i), 100.0 + (i % 11))
            for i in range(30)])
    return session


class TestTheReportsAgree:

    def test_a_bounds_source_is_not_called_undeclared(self):
        records = _session().unconsumed_observations()
        offending = [r for r in records
                     if r["property"] == "margin_requirement"]
        assert offending == [], (
            "the history report called a `{from_property:}` bound's source an "
            "undeclared property; the entity report counts it as read")

    def test_derived_operands_are_not_called_undeclared(self):
        records = _session().unconsumed_observations()
        offending = sorted(r["property"] for r in records
                           if r["property"] in ("futures", "spot"))
        assert offending == [], (
            "the operands of a derived indicator are read by the join")

    def test_both_reports_draw_on_one_definition(self):
        """Not *they happen to agree today* -- they are the same set."""
        session = _session()
        readable = session.readable_properties()["Account"]
        assert {"margin_balance", "margin_requirement",
                "futures", "spot", "basis"} <= readable


class TestReplayAdvancesEveryNameTheModelReads:

    def _replayed(self) -> dict:
        session = _session()
        for name in ("margin_requirement", "futures", "spot"):
            session.entities["a1"].properties[name] = SENTINEL
        with as_of(T0):
            replay.sync_current_from_history(session, T0)
        return session.entities["a1"].properties

    def test_a_per_instance_floor_moves_with_the_clock(self):
        assert self._replayed()["margin_requirement"] != SENTINEL, (
            "a replay left the floor at its construction value, so every step "
            "after the first checked a moving balance against a frozen bound "
            "-- and nothing declined, because the bound still resolved")

    def test_derived_operands_move_too(self):
        properties = self._replayed()
        assert properties["futures"] != SENTINEL
        assert properties["spot"] != SENTINEL
