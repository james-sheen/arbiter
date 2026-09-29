"""A confirmation is read back against the reading that settled it.

`case_book.confirmed` said, per confirmation, whether the reading the
ranking named "settled it", and computed that by asking whether the named
reading sat on the confirmed cause itself. The reading a ranking names is
chosen to SEPARATE the candidates, so it usually sits somewhere else: on the
chain below it is the tank's level, and a person who reads the tank, sees the
ranking turn round and confirms the pump was told the tank settled nothing.
The confirmation has always carried the answer -- `reading`, the one that
settled it -- and nothing read it.

`named_reading_settled_it` keeps its published name and meaning, because a
patch release may not change what a field means. Beside it, each row now
carries the `named_reading`, the `settling_reading` the person gave, and
`settling_reading_was_named`, which is `None` when either is missing: an
unasked question is not a no.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from arbiter_engine.mcp import server
from arbiter_engine import api

T0 = datetime(2026, 9, 29, 12, 0)
TANK = "tank-1.level_pct"


def _model():
    return {"domain": {
        "id": "settled_chain", "name": "settled chain",
        "entity_types": ["Pump", "Tank", "Basin"],
        "relationship_types": ["feeds", "spills"],
        "indicators": {
            "Pump": [{"name": "speed_rpm", "type": "NUMERIC",
                      "axioms": ["BOUNDEDNESS"], "critical": 4000}],
            "Tank": [{"name": "level_pct", "type": "NUMERIC",
                      "axioms": ["BOUNDEDNESS"], "warning": 85, "critical": 95}],
            "Basin": [{"name": "basin_level", "type": "NUMERIC",
                       "axioms": ["BOUNDEDNESS"], "warning": 40, "critical": 60}],
        },
        "relationship_rules": [
            {"type": "feeds", "source_type": "Pump", "target_type": "Tank",
             "edge_direction": "causal", "causal": {"weight": 0.8}},
            {"type": "spills", "source_type": "Tank", "target_type": "Basin",
             "edge_direction": "causal", "causal": {"weight": 0.7}},
        ],
        "cases": {"severity": "warning", "consecutive_checks": 2},
    }}


def _session():
    session = api.EngineSession()
    session.load_model(_model())
    session.add_entity("pump-1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("tank-1", "Tank", {"level_pct": 90.0})
    session.add_entity("basin-1", "Basin", {"basin_level": 65.0})
    session.add_relationship("pump-1", "feeds", "tank-1")
    session.add_relationship("tank-1", "spills", "basin-1")
    api.check(session)
    return session


def _case(session, *, ranked=True):
    case_id = api.open_case(session, "basin-1", "basin_level").to_dict()[
        "case"]["case_id"]
    if ranked:
        with api.as_of(T0 + timedelta(minutes=1)):
            api.attach_stage(session, case_id, "hypothesize",
                             api.hypothesize(session, "basin-1"))
    return case_id


def _confirm(session, case_id, reference):
    with api.as_of(T0 + timedelta(minutes=2)):
        api.attach_stage(session, case_id, "confirm", reference=reference)


def _confirmed(session):
    return api.case_book(session).to_dict()["cases"]["confirmed"]


class TestTheReadingThatSettledIt:

    def test_the_chain_names_the_tank(self):
        """The premise, measured: the reading this ranking rests on is the
        tank's, and the tank is not the cause the rows below confirm."""
        named = api.hypothesize(_session(), "basin-1").to_dict()[
            "hypothesis"]["most_discriminating"]
        assert named["reading"] == TANK and named["basis"] == "strengths"

    def test_the_named_reading_that_turned_the_ranking_is_counted(self):
        session = _session()
        case_id = _case(session)
        _confirm(session, case_id, {"cause": "pump-1", "reading": TANK,
                                    "basis": "site visit"})
        confirmed = _confirmed(session)
        [row] = confirmed["rows"]
        assert (row["named_reading"], row["settling_reading"],
                row["settling_reading_was_named"]) == (TANK, TANK, True)
        assert (confirmed["settling_reading_given"],
                confirmed["settling_reading_was_named"]) == (1, 1)

    def test_the_published_count_keeps_its_meaning(self):
        """The same confirmation, read by the published field: the named
        reading did not sit on the pump. A patch release may not change what a
        field means, so it still says so -- and the new field says the rest."""
        session = _session()
        _confirm(session, _case(session), {"cause": "pump-1", "reading": TANK})
        [row] = _confirmed(session)["rows"]
        assert row["named_reading_settled_it"] is False
        assert row["settling_reading_was_named"] is True

    def test_another_reading_is_not_the_named_one(self):
        session = _session()
        _confirm(session, _case(session),
                 {"cause": "pump-1", "reading": "pump-1.speed_rpm"})
        confirmed = _confirmed(session)
        assert confirmed["rows"][0]["settling_reading_was_named"] is False
        assert (confirmed["settling_reading_given"],
                confirmed["settling_reading_was_named"]) == (1, 0)

    def test_no_reading_given_is_counted_neither_way(self):
        session = _session()
        _confirm(session, _case(session), {"cause": "tank-1"})
        confirmed = _confirmed(session)
        [row] = confirmed["rows"]
        assert (row["settling_reading"], row["settling_reading_was_named"]) == (
            None, None)
        assert (confirmed["settling_reading_given"],
                confirmed["settling_reading_was_named"]) == (0, 0)
        # The published field answers from the cause alone, as it always has.
        assert row["named_reading_settled_it"] is True

    def test_with_no_ranking_before_it_the_question_stays_open(self):
        session = _session()
        _confirm(session, _case(session, ranked=False),
                 {"cause": "pump-1", "reading": TANK})
        [row] = _confirmed(session)["rows"]
        assert (row["named_reading"], row["settling_reading_was_named"]) == (
            None, None)

    def test_a_reading_that_is_not_text_is_not_one(self):
        session = _session()
        _confirm(session, _case(session), {"cause": "pump-1", "reading": "  "})
        [row] = _confirmed(session)["rows"]
        assert (row["settling_reading"], row["settling_reading_was_named"]) == (
            None, None)

    def test_the_counts_are_over_every_case(self):
        session = _session()
        for reading in (TANK, "pump-1.speed_rpm", None):
            reference = {"cause": "pump-1"}
            if reading:
                reference["reading"] = reading
            _confirm(session, _case(session), reference)
        confirmed = _confirmed(session)
        assert (confirmed["confirmations"], confirmed["settling_reading_given"],
                confirmed["settling_reading_was_named"]) == (3, 2, 1)


class TestOverTheTool:

    def test_the_book_the_tool_returns_carries_it(self):
        session = server.start_session()

        def call(name, **arguments):
            """One tool call as a client makes it: JSON in, JSON out."""
            return json.loads(json.dumps(server.dispatch(
                session, name, json.loads(json.dumps(arguments)))))

        call("load_model", model=_model())
        for entity_id, entity_type, properties in (
                ("pump-1", "Pump", {"speed_rpm": 1000.0}),
                ("tank-1", "Tank", {"level_pct": 90.0}),
                ("basin-1", "Basin", {"basin_level": 65.0})):
            call("add_entity", entity_id=entity_id, entity_type=entity_type,
                 properties=properties)
        call("add_relationship", source_id="pump-1", relation_type="feeds",
             target_id="tank-1")
        call("add_relationship", source_id="tank-1", relation_type="spills",
             target_id="basin-1")
        call("check")
        case_id = call("open_case", entity_id="basin-1",
                       indicator="basin_level")["case"]["case_id"]
        call("attach_stage", case_id=case_id, stage="hypothesize",
             envelope=call("hypothesize", entity_id="basin-1"))
        call("attach_stage", case_id=case_id, stage="confirm",
             reference={"cause": "pump-1", "reading": TANK})
        book = call("case_book")["cases"]["confirmed"]
        assert book["settling_reading_was_named"] == 1
        assert book["rows"][0]["settling_reading"] == TANK
