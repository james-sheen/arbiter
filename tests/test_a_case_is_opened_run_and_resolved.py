"""The case book: a problem followed from the finding that opened it.

`Problem` is one check's verdict, and the loop's stages each answered in their
own envelope with nothing saying they were about the same thing. A case carries
that: it opens on a subject and a declared indicator, every check records itself
into it, the other stages are attached by reference -- declines included -- and
it resolves on the model's own criterion. The book records; it runs no stage.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from arbiter_engine import api
from arbiter_engine.residual.cases import STAGES, Case
from arbiter_engine.residual.sqlite_ledger import \
    SqlitePredictionLedger
from arbiter_engine.subenvelope import VOCABULARIES

def _examples() -> Path:
    """The shipped examples, in whichever tree this file runs in: the package
    keeps them in `examples/`, the repository in `docs/publication`."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples", here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / "pump_tank_planning.yaml").is_file():
            return candidate
    raise AssertionError("no examples directory in this tree carries them")


EXAMPLES = _examples()
CRITERION = {"severity": "warning", "consecutive_checks": 2}


def _model(cases=CRITERION, axioms=("BOUNDEDNESS",)):
    domain = {
        "id": "cases", "name": "one unit", "entity_types": ["Unit"],
        "indicators": {"Unit": [{"name": "load", "type": "NUMERIC",
                                 "axioms": list(axioms),
                                 "warning": 80, "critical": 95}]},
    }
    if cases is not None:
        domain["cases"] = cases
    return {"domain": domain}


def _session(ledger=None, load=97.0, **model):
    session = api.EngineSession(ledger=ledger)
    session.load_model(_model(**model))
    session.add_entity("u-1", "Unit", {"load": load})
    return session


def _open(session, **kwargs):
    return api.open_case(session, "u-1", "load", basis="alarm 4", **kwargs).to_dict()


def _outcomes(session, case_id):
    return [e["outcome"] for e in session.ledger.case_book.get(case_id).stages["check"]]


def _reasons(envelope, key="case"):
    return {d["reason"] for d in envelope[key]["not_checked"]}


class TestItResolvesOnTheDeclaredCriterion:

    def test_a_breach_then_two_clean_checks_resolve_it(self):
        session = _session()
        case_id = _open(session)["case"]["case_id"]
        api.check(session)
        session.entities["u-1"].properties["load"] = 50.0
        api.check(session)
        assert session.ledger.case_book.get(case_id).status == "open"
        api.check(session)
        case = session.ledger.case_book.get(case_id)
        assert _outcomes(session, case_id) == ["found", "clean", "clean"]
        assert (case.status, case.clean_streak) == ("resolved", 2)
        assert case.resolved_at is not None

    def test_a_breach_between_clean_checks_restarts_the_count(self):
        session = _session(load=50.0)
        case_id = _open(session)["case"]["case_id"]
        api.check(session)
        session.entities["u-1"].properties["load"] = 97.0
        api.check(session)
        session.entities["u-1"].properties["load"] = 50.0
        api.check(session)
        assert _outcomes(session, case_id) == ["clean", "found", "clean"]
        assert session.ledger.case_book.get(case_id).status == "open"

    def test_a_check_that_could_not_look_is_not_a_clean_one(self):
        """No reading, so every axiom on the indicator declined: nothing was
        judged, and a run of those must not close a case."""
        session = _session(load=50.0)
        case_id = _open(session)["case"]["case_id"]
        api.check(session)
        del session.entities["u-1"].properties["load"]
        api.check(session)
        api.check(session)
        assert _outcomes(session, case_id) == ["clean", "not_looked", "not_looked"]
        assert session.ledger.case_book.get(case_id).status == "open"

    def test_a_finding_below_the_declared_severity_does_not_hold_it_open(self):
        session = _session(load=85.0, cases={"severity": "critical",
                                             "consecutive_checks": 1})
        case_id = _open(session)["case"]["case_id"]
        envelope = api.check(session).to_dict()
        assert envelope["findings"], "the warning band should have produced a finding"
        assert session.ledger.case_book.get(case_id).status == "resolved"

    def test_a_resolved_case_records_nothing_more(self):
        session = _session(load=50.0, cases={"severity": "warning",
                                             "consecutive_checks": 1})
        case_id = _open(session)["case"]["case_id"]
        api.check(session)
        api.check(session)
        assert _outcomes(session, case_id) == ["clean"]

    def test_the_case_says_what_it_was_held_to(self):
        case = _open(_session())["case"]
        assert (case["severity"], case["consecutive_checks"]) == ("warning", 2)
        assert set(case["stages"]) == set(STAGES)
        assert all(entries == [] for entries in case["stages"].values())


class TestItDeclinesByName:

    def test_no_criterion_is_missing_config(self):
        session = _session(cases=None)
        envelope = _open(session)
        assert _reasons(envelope) == {"missing_config"}
        assert "case_id" not in envelope["case"]
        assert session.ledger.case_book.cases() == []

    @pytest.mark.parametrize("block", [
        {"severity": "loud", "consecutive_checks": 2},
        {"severity": "warning", "consecutive_checks": 0},
        {"severity": "warning", "consecutive_checks": True},
        {"severity": "warning"},
    ])
    def test_a_criterion_nobody_can_read_is_missing_config_too(self, block):
        detail = next(d["detail"] for d in _open(_session(cases=block))
                      ["case"]["not_checked"])
        assert "cases." in detail

    def test_an_unknown_key_in_the_block_is_reported(self):
        session = _session(cases={**CRITERION, "grace": 3})
        assert "cases.grace" in {row["field"] for row in session.model.unread_fields()}

    def test_a_subject_or_indicator_the_model_cannot_place(self):
        session = _session()
        assert "missing_entity" in _reasons(
            api.open_case(session, "u-9", "load").to_dict())
        assert "malformed_request" in _reasons(
            api.open_case(session, "u-1", "temperature").to_dict())

    @pytest.mark.parametrize("case_id, stage, kwargs", [
        ("no-such-case", "plan", {"reference": {}}),
        (None, "check", {"reference": {}}),
        (None, "dispatch", {"reference": {}}),
        (None, "learn", {}),
    ])
    def test_an_attachment_it_cannot_make(self, case_id, stage, kwargs):
        session = _session()
        real = _open(session)["case"]["case_id"]
        envelope = api.attach_stage(session, case_id or real, stage, **kwargs).to_dict()
        assert _reasons(envelope) == {"malformed_request"}

    def test_every_reason_is_one_the_simulation_vocabulary_publishes(self):
        session = _session(cases=None)
        reasons = _reasons(_open(session))
        reasons |= _reasons(api.open_case(session, "u-9", "x").to_dict())
        reasons |= _reasons(api.attach_stage(session, "x", "check").to_dict())
        assert reasons and reasons <= VOCABULARIES["simulation"]

    def test_a_wrong_argument_type_is_a_caller_bug(self):
        with pytest.raises(TypeError):
            api.open_case(_session(), "u-1", 7)


def _planning_session(model):
    session = api.EngineSession()
    session.load_model(model)
    session.add_entity("pump1", "Pump", {"speed_rpm": 3700.0})
    session.add_entity("tank1", "Tank", {"level_pct": 97.0})
    session.add_entity("valve1", "Valve", {"open_pct": 0.0})
    session.add_relationship("pump1", "feeds", "tank1")
    session.add_relationship("valve1", "drains", "tank1")
    return session


def _planning_model(**changes):
    model = yaml.safe_load((EXAMPLES / "pump_tank_planning.yaml").read_text())
    model["domain"]["cases"] = CRITERION
    model["domain"].update(changes)
    return model


class TestTheStagesAttachByReference:

    def test_each_stage_keeps_a_reference_and_its_declines(self):
        session = _planning_session(_planning_model())
        case_id = api.open_case(session, "tank1", "level_pct").to_dict()["case"]["case_id"]
        api.check(session)
        api.attach_stage(session, case_id, "hypothesize",
                         api.hypothesize(session, "tank1"))
        api.attach_stage(session, case_id, "plan",
                         api.plan(session, horizon_s=600, step_s=60))
        with api.as_of(api.now_utc()):
            filed = api.file_action(session, {"template": "throttle_pump",
                                              "entity_id": "pump1",
                                              "parameters": {"speed_rpm": 1500}},
                                    api.now_utc(), "operator log 17",
                                    horizon_s=600, step_s=300)
        api.attach_stage(session, case_id, "act", filed)
        api.attach_stage(session, case_id, "learn",
                         reference={"adopted": None, "why": "no fitted gain yet"})
        stages = session.ledger.case_book.get(case_id).stages
        assert stages["hypothesize"][0]["declined"] == ["not_identifiable"]
        assert stages["plan"][0]["reference"]["best"]
        assert stages["act"][0]["reference"]["execution_id"] == \
            filed.to_dict()["execution"]["id"]
        assert stages["learn"][0]["reference"]["why"] == "no fitted gain yet"
        assert [e["outcome"] for e in stages["check"]] == ["found"]

    def test_a_stage_that_declined_is_present_with_its_decline(self):
        model = _planning_model()
        del model["domain"]["planning"]
        session = _planning_session(model)
        case_id = api.open_case(session, "tank1", "level_pct").to_dict()["case"]["case_id"]
        api.attach_stage(session, case_id, "plan",
                         api.plan(session, horizon_s=600, step_s=60))
        entry = session.ledger.case_book.get(case_id).stages["plan"][0]
        assert "no_objective" in entry["declined"]


class TestTheBookIsKeptBesideTheLedger:

    def test_a_case_outlives_the_session_on_the_durable_ledger(self, tmp_path):
        path = str(tmp_path / "predictions.db")
        first = _session(SqlitePredictionLedger(path))
        case_id = _open(first)["case"]["case_id"]
        api.check(first)
        second = _session(SqlitePredictionLedger(path), load=50.0)
        api.check(second)
        api.check(second)
        third = _session(SqlitePredictionLedger(path))
        case = third.ledger.case_book.get(case_id)
        assert case is not None and case.status == "resolved"
        assert [e["outcome"] for e in case.stages["check"]] == ["found", "clean", "clean"]

    def test_the_counts_are_derived_from_the_cases(self):
        session = _session(load=50.0, cases={"severity": "warning",
                                             "consecutive_checks": 1})
        for _ in range(3):
            _open(session)
        api.check(session)
        session.entities["u-1"].properties["load"] = 97.0
        _open(session)
        api.check(session)
        book = api.case_book(session).to_dict()["cases"]
        rows = book["cases"]
        resolved = sum(1 for row in rows if row["status"] == "resolved")
        assert (book["opened"], book["resolved"], book["open"]) == (len(rows), resolved,
                                                                    len(rows) - resolved)
        assert resolved / len(rows) == pytest.approx(3 / 4)

    def test_a_case_is_a_supported_type_and_round_trips(self):
        case = _session().ledger.case_book.open(
            entity_id="u-1", indicator="load", opened_at="t", basis="b",
            severity="warning", consecutive_checks=2)
        assert isinstance(case, Case)
        assert Case(**copy.deepcopy(case.to_dict())) == case


class TestModelDescribeSaysWhatEachStageReads:

    def _stages(self, model):
        session = api.EngineSession()
        session.load_model(model)
        return {name: row["declared"] for name, row in
                api.model_describe(session).to_dict()["model"]["stages"].items()}

    def test_the_planning_example(self):
        model = yaml.safe_load((EXAMPLES / "pump_tank_planning.yaml").read_text())
        assert self._stages(model) == {"check": True, "hypothesize": False,
                                       "plan": True, "act": True, "learn": True,
                                       "case": False}

    def test_the_causal_example(self):
        model = yaml.safe_load((EXAMPLES / "substation_feeder.yaml").read_text())
        assert self._stages(model)["hypothesize"] is True

    def test_the_report_matches_what_the_run_did(self):
        """Undeclared stages decline by name when run; declared ones answer."""
        model = _planning_model()
        del model["domain"]["cases"]
        session = _planning_session(model)
        api.check(session)
        stages = api.model_describe(session).to_dict()["model"]["stages"]
        assert not stages["hypothesize"]["declared"]
        assert api.hypothesize(session, "tank1").to_dict()["hypothesis"]["not_checked"]
        assert not stages["case"]["declared"]
        assert _reasons(api.open_case(session, "tank1", "level_pct").to_dict()) == {
            "missing_config"}
        assert stages["plan"]["declared"]
        assert api.plan(session, horizon_s=600, step_s=60).to_dict()["plan"]["best"]
