"""A confirmed cause is read back against the ranking the case held before it.

the one number that says whether `hypothesize` is worth reading is
how often the cause a person later confirms was at the top of it, and whether
the reading it named as most discriminating was the one that settled it.
Nothing could count that: a case kept its ranking and never learned the
answer. `confirm` is the stage a person supplies -- a reference naming the
cause -- and `case_book` returns, per confirmation, the cause's rank in the
last ranking attached before it, beside the counts. Never a rate: the
denominator is a handful of cases, and a rate would hide that.

`gaps` attaches too, so a case carries what the declaration could not explain
beside what it ranked.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from arbiter_engine.mcp import server
from arbiter_engine import api

T0 = datetime(2026, 9, 28, 12, 0)


def _model(cases=True):
    domain = {
        "id": "confirmed_chain", "name": "confirmed chain",
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
    }
    if cases:
        domain["cases"] = {"severity": "warning", "consecutive_checks": 2}
    return {"domain": domain}


def _session(tank=90.0):
    session = api.EngineSession()
    session.load_model(_model())
    session.add_entity("pump-1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("tank-1", "Tank", {"level_pct": tank})
    session.add_entity("basin-1", "Basin", {"basin_level": 65.0})
    session.add_relationship("pump-1", "feeds", "tank-1")
    session.add_relationship("tank-1", "spills", "basin-1")
    api.check(session)
    return session


def _open(session):
    return api.open_case(session, "basin-1", "basin_level",
                         basis="basin alarm").to_dict()["case"]["case_id"]


def _rank(session, case_id, minutes):
    with api.as_of(T0 + timedelta(minutes=minutes)):
        api.attach_stage(session, case_id, "hypothesize",
                         api.hypothesize(session, "basin-1"))


def _confirm(session, case_id, minutes, reference):
    with api.as_of(T0 + timedelta(minutes=minutes)):
        return api.attach_stage(session, case_id, "confirm",
                                reference=reference).to_dict()["case"]


def _confirmed(session):
    return api.case_book(session).to_dict()["cases"]["confirmed"]


class TestWhereTheConfirmedCauseStood:

    def test_the_first_ranked_cause_confirmed_counts_as_first(self):
        session = _session()
        case_id = _open(session)
        _rank(session, case_id, 1)
        _confirm(session, case_id, 2, {"cause": "tank-1",
                                       "reading": "tank-1.level_pct",
                                       "basis": "site visit"})
        assert _confirmed(session) == {
            "confirmations": 1, "ranked_first": 1, "ranked": 1, "not_ranked": 0,
            "named_reading_settled_it": 1,
            "settling_reading_given": 1, "settling_reading_was_named": 1,
            "rows": [{"case_id": case_id, "cause": "tank-1", "rank": 1, "of": 2,
                      "named_reading_settled_it": True,
                      "named_reading": "tank-1.level_pct",
                      "settling_reading": "tank-1.level_pct",
                      "settling_reading_was_named": True}]}

    def test_a_lower_ranked_cause_counts_at_its_rank(self):
        session = _session()
        case_id = _open(session)
        _rank(session, case_id, 1)
        _confirm(session, case_id, 2, {"cause": "pump-1"})
        confirmed = _confirmed(session)
        assert confirmed["rows"][0]["rank"] == 2
        assert confirmed["rows"][0]["named_reading_settled_it"] is False
        assert (confirmed["ranked_first"], confirmed["ranked"]) == (0, 1)

    def test_a_cause_the_ranking_never_named_is_not_ranked(self):
        session = _session()
        case_id = _open(session)
        _rank(session, case_id, 1)
        _confirm(session, case_id, 2, {"cause": "valve-9"})
        confirmed = _confirmed(session)
        assert confirmed["rows"][0]["rank"] is None
        assert (confirmed["ranked"], confirmed["not_ranked"]) == (0, 1)

    def test_with_no_ranking_before_it_nothing_is_ranked(self):
        session = _session()
        case_id = _open(session)
        _confirm(session, case_id, 1, {"cause": "tank-1"})
        _rank(session, case_id, 2)
        row = _confirmed(session)["rows"][0]
        assert (row["rank"], row["of"]) == (None, 0), (
            "a ranking attached after the confirmation was read as though it "
            "had come first")

    def test_each_confirmation_reads_the_last_ranking_before_it(self):
        """The tank read faulty reverses the ranking; a confirmation made
        before that reading and one made after read different rankings."""
        session = _session()
        case_id = _open(session)
        _rank(session, case_id, 1)
        _confirm(session, case_id, 2, {"cause": "tank-1"})
        session.entities["tank-1"].properties["level_pct"] = 97.0
        api.check(session)
        _rank(session, case_id, 3)
        _confirm(session, case_id, 4, {"cause": "tank-1"})
        assert [row["rank"] for row in _confirmed(session)["rows"]] == [1, 2]

    def test_the_counts_are_printed_and_no_rate_is(self):
        session = _session()
        _confirm(session, _open(session), 1, {"cause": "tank-1"})
        confirmed = _confirmed(session)
        # An internal ruling added the two counts of the reading that settled it.
        assert set(confirmed) == {"confirmations", "ranked_first", "ranked",
                                  "not_ranked", "named_reading_settled_it",
                                  "settling_reading_given",
                                  "settling_reading_was_named", "rows"}
        assert not any(isinstance(v, float) for v in confirmed.values())


class TestAConfirmationNamesItsCause:

    @pytest.mark.parametrize("reference", [
        {}, {"cause": ""}, {"cause": "   "}, {"cause": 3},
        {"reading": "tank-1.level_pct"}, ["tank-1"]])
    def test_without_one_it_is_refused_by_name(self, reference):
        session = _session()
        case = _confirm(session, _open(session), 1, reference)
        assert case["checked"]["stages_attached"] == 0
        assert {d["reason"] for d in case["not_checked"]} == {"malformed_request"}
        assert _confirmed(session)["confirmations"] == 0

    def test_what_a_person_gives_is_kept_as_given(self):
        session = _session()
        given = {"cause": "tank-1", "reading": "tank-1.level_pct",
                 "basis": "site visit, float stuck"}
        case = _confirm(session, _open(session), 1, given)
        assert case["stages"]["confirm"][-1]["reference"] == given


class TestTheGapsStageAttaches:

    def test_the_located_hypotheses_ride_on_the_case(self):
        session = api.EngineSession()
        session.load_model({"domain": {
            "id": "unit_gap", "name": "unit gap", "entity_types": ["Unit"],
            "indicators": {"Unit": [
                {"name": "inflow", "type": "NUMERIC", "axioms": ["CONSERVATION"],
                 "conservation": {"input_property": "inflow",
                                  "output_properties": ["outflow", "overflow"]}},
                {"name": "outflow", "type": "NUMERIC", "axioms": []},
                {"name": "overflow", "type": "NUMERIC", "axioms": []}]},
            "cases": {"severity": "medium", "consecutive_checks": 2}}})
        session.add_entity("u-1", "Unit", {"inflow": 50.0, "outflow": 10.0})
        for prop, value in (("inflow", 50.0), ("outflow", 10.0)):
            session.add_observations("u-1", prop, [value] * 40, interval_seconds=10)
        api.check(session)
        case_id = api.open_case(session, "u-1", "inflow").to_dict()["case"]["case_id"]
        envelope = api.gaps(session)
        case = api.attach_stage(session, case_id, "gaps", envelope).to_dict()["case"]
        entry = case["stages"]["gaps"][-1]
        assert entry["reference"]["hypotheses"] == [{
            "kind": "unaccounted_flow", "at": "u-1", "basis": "CONSERVATION",
            "between": ["inflow", "outflow", "overflow"],
            "evidence_needed": "u-1.overflow"}]
        assert entry["declined"] == sorted({
            d["reason"] for d in envelope.to_dict()["residuals"]["not_checked"]})

    def test_another_verbs_envelope_is_refused(self):
        session = _session()
        case = api.attach_stage(session, _open(session), "gaps",
                                api.check(session)).to_dict()["case"]
        assert {d["reason"] for d in case["not_checked"]} == {"malformed_request"}


def _call(session, name, **arguments):
    """One tool call as a client makes it: JSON in, JSON out."""
    return json.loads(json.dumps(
        server.dispatch(session, name, json.loads(json.dumps(arguments)))))


class TestOverTheTransport:

    def test_the_tool_advertises_both_stages(self):
        spec = next(s for s in server.TOOL_SPECS if s["name"] == "attach_stage")
        stages = spec["inputSchema"]["properties"]["stage"]["enum"]
        assert {"gaps", "confirm"} <= set(stages)
        assert "confirm" in spec["description"] and "cause" in spec["description"]

    def test_a_case_runs_from_finding_to_confirmation(self):
        session = server.start_session()
        _call(session, "load_model", model=_model())
        for entity_id, entity_type, properties in (
                ("pump-1", "Pump", {"speed_rpm": 1000.0}),
                ("tank-1", "Tank", {"level_pct": 90.0}),
                ("basin-1", "Basin", {"basin_level": 65.0})):
            _call(session, "add_entity", entity_id=entity_id,
                  entity_type=entity_type, properties=properties)
        _call(session, "add_relationship", source_id="pump-1",
              relation_type="feeds", target_id="tank-1")
        _call(session, "add_relationship", source_id="tank-1",
              relation_type="spills", target_id="basin-1")
        _call(session, "check")
        case_id = _call(session, "open_case", entity_id="basin-1",
                        indicator="basin_level")["case"]["case_id"]
        ranking = _call(session, "hypothesize", entity_id="basin-1")
        _call(session, "attach_stage", case_id=case_id, stage="hypothesize",
              envelope=ranking)
        located = _call(session, "gaps")
        attached = _call(session, "attach_stage", case_id=case_id, stage="gaps",
                         envelope=located)
        assert attached["case"]["checked"]["stages_attached"] == 1
        confirmed = _call(session, "attach_stage", case_id=case_id,
                          stage="confirm", reference={"cause": "tank-1"})
        assert confirmed["case"]["checked"]["stages_attached"] == 1
        book = _call(session, "case_book")["cases"]["confirmed"]
        assert (book["confirmations"], book["ranked_first"]) == (1, 1)
