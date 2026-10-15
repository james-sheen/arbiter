"""A confirmation is read against the walk attached before it, whatever the clocks say.

found by the TSA case study, which replays twelve years of a workforce
month by month. The book read a confirmation against the last `hypothesize`
attached before it BY STAMP, and the stamps came from two clocks: a walk is stamped
at the instant its data describes (`as_of`), a confirmation when a person makes it.
On data older than now every walk stamped before every confirmation, so each
confirmation was read against the case's LAST walk: two causes ranked first on the
frontier of a traced walk when they were confirmed read, at the end of the replay, as
ranked 2 of 2, screened, on an unexplained walk 103 walks later. The Clinic meets the
same two clocks on every batch cluster fed past data.

Every entry now carries its place in the case's own history (`seq`), and the book
reads a confirmation by it.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from arbiter_engine import api
from arbiter_engine.residual.cases import Case, CaseBook, SqliteCaseBook, confirmed_causes

MARCH = datetime(2019, 3, 31)

MODEL = {"domain": {
    "id": "confirmed_in_order", "name": "confirmed in order",
    "entity_types": ["Pump", "Tank", "Basin"],
    "relationship_types": ["feeds", "spills"],
    "cases": {"severity": "warning", "consecutive_checks": 2},
    "indicators": {
        "Pump": [{"name": "speed_rpm", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"], "critical": 4000}],
        "Tank": [{"name": "level_pct", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                  "warning": 85, "critical": 95}],
        "Basin": [{"name": "basin_level", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                   "warning": 40, "critical": 60}]},
    "relationship_rules": [
        {"type": "feeds", "source_type": "Pump", "target_type": "Tank",
         "edge_direction": "causal", "causal": {"weight": 0.8}},
        {"type": "spills", "source_type": "Tank", "target_type": "Basin",
         "edge_direction": "causal", "causal": {"weight": 0.7}}]}}


def _session(tank, pump):
    session = api.EngineSession()
    session.load_model(MODEL)
    session.add_entity("pump-1", "Pump", {"speed_rpm": pump})
    session.add_entity("tank-1", "Tank", {"level_pct": tank})
    session.add_entity("basin-1", "Basin", {"basin_level": 65.0})
    session.add_relationship("pump-1", "feeds", "tank-1")
    session.add_relationship("tank-1", "spills", "basin-1")
    return session


def _open(session):
    return api.open_case(session, "basin-1", "basin_level",
                         basis="basin alarm").to_dict()["case"]["case_id"]


def _walk(session, case_id, at):
    with api.as_of(at):
        api.check(session)
        api.attach_stage(session, case_id, "hypothesize", api.hypothesize(session, "basin-1"))


def _row(session):
    rows = api.case_book(session).to_dict()["cases"]["confirmed"]["rows"]
    assert len(rows) == 1
    return {k: rows[0][k] for k in ("rank", "of", "standing", "walk_state", "walks_before")}


def _entries(session, case_id):
    case = next(c for c in api.case_book(session).to_dict()["cases"]["cases"] if c["case_id"] == case_id)
    return [(stage, entry) for stage, entries in case["stages"].items() for entry in entries]


class TestTheWalkBeforeIt:

    def test_a_confirmation_made_now_on_past_data_reads_the_walk_the_person_saw(self):
        session = _session(tank=90.0, pump=1000.0)
        case_id = _open(session)
        _walk(session, case_id, MARCH)                          # the tank on the frontier, the walk traced
        api.attach_stage(session, case_id, "confirm",           # on the wall clock, as the Clinic's route does
                         reference={"cause": "tank-1", "basis": "the shift log"})
        session.add_entity("tank-1", "Tank", {"level_pct": 50.0})
        _walk(session, case_id, MARCH + timedelta(days=30))     # the tank back in bounds: screened, unexplained
        assert _row(session) == {"rank": 1, "of": 2, "standing": "frontier", "walk_state": "traced",
                                 "walks_before": 1}

    def test_a_walk_attached_after_it_with_an_earlier_stamp_is_not_before_it(self):
        session = _session(tank=90.0, pump=1000.0)
        case_id = _open(session)
        _walk(session, case_id, MARCH)
        with api.as_of(MARCH + timedelta(days=1)):
            api.attach_stage(session, case_id, "confirm", reference={"cause": "tank-1", "basis": "the shift log"})
        session.add_entity("tank-1", "Tank", {"level_pct": 50.0})
        _walk(session, case_id, MARCH - timedelta(days=30))     # a back-filled month, attached later
        assert _row(session)["walks_before"] == 1
        assert _row(session)["standing"] == "frontier"

    def test_every_entry_carries_its_place_in_the_case(self):
        session = _session(tank=90.0, pump=1000.0)
        case_id = _open(session)
        _walk(session, case_id, MARCH)
        api.attach_stage(session, case_id, "confirm", reference={"cause": "tank-1", "basis": "the shift log"})
        _walk(session, case_id, MARCH + timedelta(days=30))
        order = sorted(((entry["seq"], stage) for stage, entry in _entries(session, case_id)))
        assert [seq for seq, _ in order] == list(range(1, len(order) + 1))
        assert [stage for _, stage in order] == ["check", "hypothesize", "confirm", "check", "hypothesize"]


def _legacy_case(entries):
    case = Case(case_id="c-1", entity_id="basin-1", indicator="basin_level", opened_at="2019-01-01T00:00:00",
                basis="test", severity="warning", consecutive_checks=2)
    for stage, entry in entries:
        case.stages[stage].append(entry)
    return case


def _ranking(first):
    return {"reference": {"causes": [{"cause": first}, {"cause": "other"}]}}


class TestABookWrittenBeforeEntriesCarriedAPlace:

    def test_a_confirmation_without_one_is_read_by_stamp_as_it_was(self):
        case = _legacy_case([("hypothesize", {"at": "2019-03-31T00:00:00", **_ranking("tank-1")}),
                             ("hypothesize", {"at": "2019-04-30T00:00:00", **_ranking("pump-1")}),
                             ("confirm", {"at": "2019-04-01T00:00:00", "reference": {"cause": "tank-1"}})])
        assert confirmed_causes([case])["rows"][0]["rank"] == 1

    def test_a_walk_without_one_is_before_a_confirmation_that_has_one(self):
        case = _legacy_case([("hypothesize", {"at": "2019-03-31T00:00:00", **_ranking("tank-1")})])
        CaseBook().attach(case, "confirm", {"at": "2018-01-01T00:00:00", "reference": {"cause": "tank-1"}})
        row = confirmed_causes([case])["rows"][0]
        assert (row["rank"], row["walks_before"]) == (1, 1)


class TestADurableBookKeepsTheOrder:

    def test_the_order_survives_a_reload(self):
        db = sqlite3.connect(":memory:")
        book = SqliteCaseBook(db)
        case = book.open(entity_id="basin-1", indicator="basin_level", opened_at="2019-03-31T00:00:00",
                         basis="test", severity="warning", consecutive_checks=2)
        book.attach(case, "hypothesize", {"at": "2019-03-31T00:00:00", **_ranking("tank-1")})
        book.attach(case, "confirm", {"at": "2026-10-08T00:00:00", "reference": {"cause": "tank-1"}})
        book.attach(case, "hypothesize", {"at": "2019-04-30T00:00:00", **_ranking("pump-1")})
        again = SqliteCaseBook(db).get(case.case_id)
        assert [e["seq"] for e in again.stages["hypothesize"]] == [1, 3]
        assert confirmed_causes([again])["rows"][0]["rank"] == 1
