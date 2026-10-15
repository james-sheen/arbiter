""" -- a case says whether the reading crossed the line or the line crossed the reading.

A bound read off the entity (`{from_property:...}`) moves when its property does. On the FAA case the 2026
staffing model lowered most facility targets, and the book recorded a line that moved below a unit exactly as
it recorded a unit that recovered: cases closed on a target that fell while the controllers did not rise. A
check now records the reading and the declared bounds it was judged against, a case that resolves says which
crossed, the book counts each kind, and a plan marks an option whose writes move a line.

One unit whose load is held to a limit it carries itself. No domain.
"""

from __future__ import annotations

from arbiter_engine import api
from arbiter_engine.residual.cases import Case, resolution_of

TEMPLATES = [
    {"name": "raise_limit", "applies_to": "Unit", "effect": "set", "settle_s": 0, "source": "a test",
     "parameters_schema": {"limit": {"type": "number", "entity_property": "limit", "candidates": [200]}}},
    {"name": "raise_capacity", "applies_to": "Unit", "effect": "set", "settle_s": 0, "source": "a test",
     "parameters_schema": {"capacity": {"type": "number", "entity_property": "capacity",
                                        "candidates": [400]}}},
    {"name": "shed_load", "applies_to": "Unit", "effect": "set", "settle_s": 0, "source": "a test",
     "parameters_schema": {"load": {"type": "number", "entity_property": "load", "candidates": [10]}}},
]


def _model(planning: bool = False, derived: bool = False) -> dict:
    limit = ({"name": "limit", "derived": "capacity / 2", "axioms": []} if derived
             else {"name": "limit", "type": "NUMERIC", "axioms": []})
    domain = {
        "id": "lines", "name": "one unit held to its own limit", "entity_types": ["Unit"],
        "indicators": {"Unit": [
            {"name": "load", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"], "window": "1d",
             "critical": {"from_property": "limit"}},
            limit,
            {"name": "capacity", "type": "NUMERIC", "axioms": []}]},
        "cases": {"severity": "critical", "consecutive_checks": 1},
    }
    if planning:
        domain["action_templates"] = TEMPLATES
        domain["planning"] = {"objective": "expected_findings"}
    return {"domain": domain}


def _session(load: float = 97.0, limit: float = 95.0, **model) -> api.EngineSession:
    session = api.EngineSession()
    session.load_model(_model(**model))
    session.add_entity("u-1", "Unit", {"load": load, "limit": limit, "capacity": 2 * limit})
    return session


def _closed(load_after: float, limit_after: float, load: float = 97.0, limit: float = 95.0) -> Case:
    """Found at `load` against `limit`, then checked again at the new pair."""
    session = _session(load, limit)
    case_id = api.open_case(session, "u-1", "load", basis="alarm 4").to_dict()["case"]["case_id"]
    api.check(session)
    session.entities["u-1"].properties.update(load=load_after, limit=limit_after)
    api.check(session)
    return session.ledger.case_book.get(case_id)


class TestACaseSaysWhatCrossed:

    def test_the_reading_crossed_the_line(self):
        case = _closed(load_after=50.0, limit_after=95.0)
        assert case.status == "resolved"
        assert case.resolved_by == {"by": "reading", "reading": [97.0, 50.0], "bounds": {"critical": [95.0, 95.0]}}

    def test_the_line_crossed_the_reading(self):
        """The FAA's own case: the target fell and the controllers did not rise."""
        case = _closed(load_after=97.0, limit_after=120.0)
        assert case.resolved_by["by"] == "bound"

    def test_each_would_have_done_it_alone(self):
        assert _closed(load_after=50.0, limit_after=200.0).resolved_by["by"] == "both"

    def test_only_the_two_together(self):
        """Neither alone: 96 is still across 95, and 97 across 96.5."""
        assert _closed(load_after=96.0, limit_after=96.5).resolved_by["by"] == "both"

    def test_opened_after_the_check_that_found_it(self):
        """As a walk opens one -- the check first, the case after it -- and closed by the next check."""
        session = _session()
        api.check(session)
        case_id = api.open_case(session, "u-1", "load", basis="alarm 4").to_dict()["case"]["case_id"]
        session.entities["u-1"].properties.update(limit=120.0)
        api.check(session)
        case = session.ledger.case_book.get(case_id)
        assert (case.status, case.resolved_by["by"], case.resolved_by["reading"]) == ("resolved", "bound", [97.0, 97.0])

    def test_a_reading_on_the_line_is_across_it(self):
        """BOUNDEDNESS reads a reading ON a line as across it, so the case stays open."""
        assert _closed(load_after=95.0, limit_after=95.0).status == "open"


class TestTheRecordItRestsOn:

    def test_each_check_records_its_reading_and_lines(self):
        case = _closed(load_after=50.0, limit_after=120.0)
        assert [(c["outcome"], c["reading"], c["bounds"]) for c in case.stages["check"]] == [
            ("found", 97.0, {"critical": 95.0}), ("clean", 50.0, {"critical": 120.0})]

    def test_with_no_line_recorded_it_says_nothing(self):
        """A case a statistical baseline or a trend decided has no line to have crossed."""
        case = Case(case_id="c", entity_id="u-1", indicator="load", opened_at="t0", basis="b",
                    severity="critical", consecutive_checks=1)
        case.stages["check"] = [{"outcome": "found", "findings": ["x"]}, {"outcome": "clean", "findings": []}]
        assert resolution_of(case) is None

    def test_the_book_counts_each_kind(self):
        session = _session()
        book = session.ledger.case_book
        for load_after, limit_after in ((50.0, 95.0), (97.0, 120.0), (97.0, 130.0)):
            session.entities["u-1"].properties.update(load=97.0, limit=95.0)
            api.open_case(session, "u-1", "load", basis="alarm 4")
            api.check(session)
            session.entities["u-1"].properties.update(load=load_after, limit=limit_after)
            api.check(session)
        # A line withdrawn and a unit retired, none here.
        assert book.summary()["resolved_by"] == {"reading": 1, "bound": 2, "both": 0, "withdrawn": 0, "retired": 0}


class TestAPlanMarksAnOptionThatMovesALine:

    @staticmethod
    def _marks(**model) -> dict:
        leg = api.plan(_session(planning=True, **model)).to_dict()["plan"]
        return {c["actions"][0]["template"]: c["moves_bounds"] for c in leg["candidates"] if c["actions"]}

    def test_the_property_a_line_is_read_off(self):
        marks = self._marks()
        assert marks["raise_limit"] == [{"template": "raise_limit", "entity_id": "u-1", "indicator": "load",
                                         "bound": "critical", "through": ["limit"]}]
        assert marks["shed_load"] == []

    def test_through_a_derived_indicator(self):
        """As the FAA's staffing model writes the target its derived floors are computed from."""
        marks = self._marks(derived=True)
        assert marks["raise_capacity"][0]["through"] == ["capacity", "limit"]
        assert marks["shed_load"] == []
