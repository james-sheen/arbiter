""" -- a unit that has left the world the model describes can be retired.

An entity added to a session stayed for good. A unit that closed could be held only with no values, and then every
check declined on it, every walk that reached it counted it as an open cause, and every case open on it restarted its
count for ever: on the nursing homes case, five cases at two homes CMS no longer lists; on the hearing offices case,
six closed offices the case had to count in the nation instead of holding. `retire_entity` takes the unit out of the
session and out of the graph with every relationship to or from it, and each case open on it resolves at that instant
and says so. The history keeps its readings, and the book what was found while it stood.

A cause and the unit it loads, each held to a fixed line. No domain.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from arbiter_engine import api
from arbiter_engine.residual.cases import RESOLVED_BY, SqliteCaseBook

AT = datetime(2026, 10, 14, 12, 0)
MODEL = {"domain": {
    "id": "retired_cd2311", "name": "a feeder and the unit it loads",
    "entity_types": ["Feeder", "Unit"], "relationship_types": ["loads"],
    "relationship_rules": [{"type": "loads", "source_type": "Feeder", "target_type": "Unit",
                            "edge_direction": "causal"}],
    "causal": {"evidence_severity": ["warning", "low", "medium", "high", "critical"], "max_hops": 3},
    "cases": {"severity": "warning", "consecutive_checks": 2},
    "indicators": {
        "Feeder": [{"name": "draw", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"], "window": "1d", "warning": 50}],
        "Unit": [{"name": "load", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"], "window": "1d", "warning": 80}]}}}
BASIS = "not listed in the operator's register of 2026-10"


def _session() -> api.EngineSession:
    """Both across their lines, a case open on each."""
    session = api.EngineSession()
    session.load_model(MODEL)
    session.add_entity("feeder-1", "Feeder", {"draw": 60.0})
    session.add_entity("unit-1", "Unit", {"load": 90.0})
    session.add_relationship("feeder-1", "loads", "unit-1")
    session.add_observations("feeder-1", "draw", [(AT, 60.0)])
    with api.as_of(AT):
        api.check(session)
        for entity_id, indicator in (("feeder-1", "draw"), ("unit-1", "load")):
            api.open_case(session, entity_id, indicator, basis="over the line")
    return session


def _retire(session, entity_id="feeder-1", minutes=10):
    with api.as_of(AT + timedelta(minutes=minutes)):
        return api.retire_entity(session, entity_id, basis=BASIS).to_dict()


def _case(session, entity_id):
    [case] = [c for c in session.ledger.case_book.cases() if c.entity_id == entity_id]
    return case


class TestTheUnitLeaves:

    def test_it_is_gone_from_the_session_and_the_graph(self):
        session = _session()
        leg = _retire(session)["retire"]
        assert (leg["entity_id"], leg["removed"], leg["relationships_removed"]) == ("feeder-1", True, 1)
        assert "feeder-1" not in session.entities
        assert not session.graph.get_reverse_relationships("unit-1")

    def test_no_check_sees_it(self):
        session = _session()
        _retire(session)
        with api.as_of(AT + timedelta(minutes=20)):
            env = api.check(session).to_dict()
        assert all(f["entity_id"] != "feeder-1" for f in env["findings"])
        assert all(d.get("entity_id") != "feeder-1" for d in env["not_checked"])

    def test_no_walk_reaches_it(self):
        session = _session()
        with api.as_of(AT + timedelta(minutes=5)):
            before = api.check(session).to_dict()
            ranked = api.hypothesize(session, "unit-1").to_dict()
        assert [c["cause"] for c in ranked["hypothesis"]["candidates"]] == ["feeder-1"]
        assert before["findings"]
        _retire(session)
        with api.as_of(AT + timedelta(minutes=20)):
            api.check(session)
            after = api.hypothesize(session, "unit-1").to_dict()
        assert [c["cause"] for c in (after.get("hypothesis") or {}).get("candidates") or []] == []

    def test_the_history_keeps_its_readings(self):
        session = _session()
        _retire(session)
        assert session.history.get_observations("feeder-1", AT - timedelta(days=1), AT + timedelta(days=1))


class TestItsCasesResolve:

    def test_each_open_case_on_it_resolves_now_and_says_so(self):
        session = _session()
        leg = _retire(session)["retire"]
        case = _case(session, "feeder-1")
        assert leg["cases_resolved"] == [case.case_id]
        assert case.status == "resolved"
        assert case.resolved_at.startswith((AT + timedelta(minutes=10)).isoformat())
        assert case.resolved_by == {"by": "retired", "basis": BASIS}

    def test_nothing_is_recorded_as_a_check(self):
        session = _session()
        _retire(session)
        assert _case(session, "feeder-1").stages["check"] == []

    def test_a_case_on_another_unit_is_untouched(self):
        session = _session()
        _retire(session)
        assert _case(session, "unit-1").status == "open"

    def test_the_book_counts_it(self):
        session = _session()
        _retire(session)
        assert RESOLVED_BY[-1] == "retired"
        assert session.ledger.case_book.summary()["resolved_by"]["retired"] == 1

    def test_a_case_held_only_in_the_book_resolves_too(self):
        """As on a Core, whose walk builds its session from the units still fed: the book holds the case, the
        session no longer the unit."""
        session = _session()
        bare = api.EngineSession(ledger=session.ledger)
        with api.as_of(AT + timedelta(minutes=10)):
            leg = api.retire_entity(bare, "feeder-1", basis=BASIS).to_dict()["retire"]
        assert (leg["removed"], len(leg["cases_resolved"])) == (False, 1)
        assert _case(session, "feeder-1").resolved_by["by"] == "retired"

    def test_the_durable_book_reads_it_back(self):
        db = sqlite3.connect(":memory:")
        book = SqliteCaseBook(db)
        case = book.open(entity_id="feeder-1", indicator="draw", opened_at="t0", basis="b", severity="warning",
                         consecutive_checks=2)
        book.retire(case, at="t1", basis=BASIS)
        again = SqliteCaseBook(db).get(case.case_id)
        assert (again.status, again.resolved_at, again.resolved_by) == ("resolved", "t1",
                                                                        {"by": "retired", "basis": BASIS})


class TestAfterwards:

    def test_retiring_it_again_is_refused_and_resolves_nothing(self):
        session = _session()
        _retire(session)
        leg = _retire(session, minutes=20)["retire"]
        assert ([d["reason"] for d in leg["not_checked"]], "cases_resolved" in leg) == (["missing_entity"], False)

    def test_a_unit_never_held_is_refused(self):
        session = _session()
        leg = _retire(session, entity_id="feeder-9")["retire"]
        assert [d["reason"] for d in leg["not_checked"]] == ["missing_entity"]

    def test_added_again_it_is_a_new_unit_and_a_case_on_it_a_reopening(self):
        session = _session()
        _retire(session)
        session.add_entity("feeder-1", "Feeder", {"draw": 70.0})
        with api.as_of(AT + timedelta(minutes=30)):
            api.check(session)
            api.open_case(session, "feeder-1", "draw", basis="over the line again")
        assert session.ledger.case_book.summary()["reopened"] == 1
