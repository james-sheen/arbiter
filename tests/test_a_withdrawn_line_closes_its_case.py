""" -- a case on a line the unit no longer carries closes, and says the line was withdrawn.

A case resolves after `cases.consecutive_checks` checks in a row that looked and found nothing, and a check that
could not look restarts the count: silence is not evidence of health. A line read off the unit (`{from_property:
...}`) that the unit stops carrying made BOUNDEDNESS decline `no_threshold`, and the book counted that as silence.
On the nursing homes case 232 cases opened on the 2024 rule's lines stayed open a year after a court struck the
lines down: each month's check found the home's hours and no line, and none could close. The reading was not
silent; the model had stopped drawing the line. Such a check now counts toward closing as a clean one does, and a
case that closes on one says the line was withdrawn. A reading that falls silent still restarts the count.

One unit whose load is held to a limit it carries itself. No domain.
"""

from __future__ import annotations

import sqlite3

from arbiter_engine import api
from arbiter_engine.axiom_thresholds import DECLARED_THRESHOLDS_KEY
from arbiter_engine.residual.cases import RESOLVED_BY, CaseBook, SqliteCaseBook, resolution_of


def _session(count: int = 2, axioms=("BOUNDEDNESS",), literal: bool = False) -> api.EngineSession:
    load = {"name": "load", "type": "NUMERIC", "axioms": list(axioms), "window": "1d",
            "warning": {"from_property": "limit"}}
    if literal:
        load["critical"] = 150
    session = api.EngineSession()
    session.load_model({"domain": {
        "id": "withdrawn", "name": "one unit held to the limit it carries", "entity_types": ["Unit"],
        "indicators": {"Unit": [load, {"name": "limit", "type": "NUMERIC", "axioms": []}]},
        "cases": {"severity": "warning", "consecutive_checks": count}}})
    session.add_entity("u-1", "Unit", {"load": 97.0, "limit": 95.0})
    return session


def _opened(session: api.EngineSession) -> str:
    """Found at 97 against 95, and a case opened on it, as a walk opens one."""
    api.check(session)
    return api.open_case(session, "u-1", "load", basis="over the limit").to_dict()["case"]["case_id"]


def _checked(session: api.EngineSession, case_id: str, **properties):
    """One check after setting `properties` (None removes one); the case after it."""
    table = session.entities["u-1"].properties
    for name, value in properties.items():
        if value is None:
            table.pop(name, None)
        else:
            table[name] = value
    api.check(session)
    return session.ledger.case_book.get(case_id)


def _outcomes(case) -> list:
    return [c["outcome"] for c in case.stages["check"]]


class TestAWithdrawnLineClosesItsCase:

    def test_the_reading_with_no_line_counts_toward_closing(self):
        session = _session()
        case_id = _opened(session)
        case = _checked(session, case_id, limit=None)
        assert (case.status, case.clean_streak, _outcomes(case)) == ("open", 1, ["withdrawn"])
        case = _checked(session, case_id)
        assert (case.status, _outcomes(case)) == ("resolved", ["withdrawn", "withdrawn"])

    def test_it_says_the_line_was_withdrawn(self):
        session = _session()
        case_id = _opened(session)
        _checked(session, case_id, limit=None)
        case = _checked(session, case_id, load=80.0)
        assert case.resolved_by == {"by": "withdrawn", "reading": [97.0, 80.0], "bounds": {"warning": [95.0, None]}}

    def test_the_check_records_the_reading_and_the_line_it_lacked(self):
        session = _session()
        case_id = _opened(session)
        entry = _checked(session, case_id, limit=None).stages["check"][-1]
        assert (entry["reading"], entry["withdrawn"]) == (97.0, ["warning"])

    def test_the_book_counts_it(self):
        session = _session(count=1)
        _checked(session, _opened(session), limit=None)
        assert session.ledger.case_book.summary()["resolved_by"] == {
            "reading": 0, "bound": 0, "both": 0, "withdrawn": 1, "retired": 0}
        assert "withdrawn" in RESOLVED_BY


class TestSilenceStillRestartsTheCount:

    def test_a_reading_gone_silent(self):
        session = _session()
        case_id = _opened(session)
        case = _checked(session, case_id, load=None)
        assert (case.status, case.clean_streak, _outcomes(case)) == ("open", 0, ["not_looked"])

    def test_the_reading_and_the_line_both_gone(self):
        session = _session()
        case_id = _opened(session)
        case = _checked(session, case_id, load=None, limit=None)
        assert _outcomes(case) == ["not_looked"]

    def test_a_line_that_is_no_number_is_not_withdrawn(self):
        """A property that is there and unreadable is a fault in the data, not a line the model stopped drawing."""
        session = _session()
        case_id = _opened(session)
        assert _outcomes(_checked(session, case_id, limit="n/a")) == ["not_looked"]

    def test_an_instance_bound_that_is_no_number_is_not_withdrawn(self):
        """The resolver reads a per-unit bound before the property, and says so when it is no number
        (`axiom_thresholds.resolve_declared_threshold`): a line there and unreadable, as above."""
        session = _session()
        case_id = _opened(session)
        session.entities["u-1"].properties[DECLARED_THRESHOLDS_KEY] = {("load", "warning"): "n/a"}
        assert _outcomes(_checked(session, case_id, limit=None)) == ["not_looked"]

    def test_a_line_still_standing_is_not_withdrawn(self):
        """A literal line stands while the line read off the unit is gone: BOUNDEDNESS declines both, and the count
        restarts as before -- the model still draws a line there."""
        session = _session(literal=True)
        case_id = _opened(session)
        assert _outcomes(_checked(session, case_id, limit=None)) == ["not_looked"]

    def test_a_decline_besides_the_line_restarts(self):
        """HOMEOSTASIS, with one reading, declines for want of readings: the check did not look for that reason too."""
        session = _session(axioms=("BOUNDEDNESS", "HOMEOSTASIS"))
        case_id = _opened(session)
        assert _outcomes(_checked(session, case_id, limit=None)) == ["not_looked"]


class TestWithTheLineBack:

    def test_across_it_again_restarts(self):
        session = _session(count=3)
        case_id = _opened(session)
        _checked(session, case_id, limit=None)
        case = _checked(session, case_id, limit=95.0)
        assert (case.clean_streak, _outcomes(case)) == (0, ["withdrawn", "found"])

    def test_inside_it_closes_on_the_reading(self):
        """A run of checks mixing the two kinds closes as its closing check says: here the reading crossed."""
        session = _session()
        case_id = _opened(session)
        _checked(session, case_id, limit=None)
        case = _checked(session, case_id, load=50.0, limit=95.0)
        assert (case.status, case.resolved_by["by"]) == ("resolved", "reading")
        assert case.resolved_by["reading"] == [97.0, 50.0]


class TestTheRecord:

    def test_a_closing_check_with_no_found_one_before_it_reads_the_opening(self):
        """Opened, then withdrawn at once: what it was found at is what it opened with."""
        book = CaseBook()
        case = book.open(entity_id="u-1", indicator="load", opened_at="t0", basis="b", severity="warning",
                         consecutive_checks=1, opened_with={"reading": 97.0, "bounds": {"warning": 95.0}})
        book.record_check(case, {"at": "t1", "findings": [], "reading": 96.0, "withdrawn": ["warning"]},
                          outcome="withdrawn", at="t1")
        assert case.resolved_by == {"by": "withdrawn", "reading": [97.0, 96.0], "bounds": {"warning": [95.0, None]}}
        assert resolution_of(case) == case.resolved_by

    def test_the_durable_book_reads_it_back(self):
        db = sqlite3.connect(":memory:")
        book = SqliteCaseBook(db)
        case = book.open(entity_id="u-1", indicator="load", opened_at="t0", basis="b", severity="warning",
                         consecutive_checks=1, opened_with={"reading": 97.0, "bounds": {"warning": 95.0}})
        book.record_check(case, {"at": "t1", "findings": [], "reading": 96.0, "withdrawn": ["warning"]},
                          outcome="withdrawn", at="t1")
        again = SqliteCaseBook(db).get(case.case_id)
        assert (again.status, again.resolved_by["by"]) == ("resolved", "withdrawn")
