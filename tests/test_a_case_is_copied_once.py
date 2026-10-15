""" -- a case is copied once, and an attachment can answer without the case.

`Case.to_dict` was `copy.deepcopy(asdict(self))`: `asdict` already builds every container anew and
deep-copies every leaf, so a case's whole history was copied twice per call. `attach_stage` answered
each attachment with the case so copied, and a walk attaches three stages to every case a finding
names -- on the unemployment case, cases open for years, 70 percent of a late walk went to copies
nobody read. Now `to_dict` copies once, and `include_case=False` answers an attachment with the
case's id and status.

One unit held to a line, with a case open on it. No domain.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from arbiter_engine import api
from arbiter_engine.residual import cases as case_module
from arbiter_engine.residual.cases import Case

MODEL = {"domain": {
    "id": "one-line", "name": "one unit held to a line", "entity_types": ["Unit"],
    "indicators": {"Unit": [{"name": "load", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                             "window": "1d", "critical": 95}]},
    "cases": {"severity": "critical", "consecutive_checks": 3}}}


def _open_case():
    session = api.EngineSession()
    session.load_model(MODEL)
    session.add_entity("u-1", "Unit", {"load": 97.0})
    api.check(session)
    case_id = api.open_case(session, "u-1", "load", basis="alarm").to_dict()["case"]["case_id"]
    return session, case_id


@pytest.fixture
def copies(monkeypatch):
    """How many times a case was turned into a dict."""
    counted = {"n": 0}
    real = Case.to_dict

    def counting(self):
        counted["n"] += 1
        return real(self)
    monkeypatch.setattr(case_module.Case, "to_dict", counting)
    return counted


class TestACaseIsCopiedOnce:

    def test_the_copy_shares_nothing_with_the_case(self):
        case = Case(case_id="c", entity_id="u-1", indicator="load", opened_at="t0", basis="b",
                    severity="critical", consecutive_checks=1)
        case.stages["check"].append({"outcome": "found", "bounds": {"critical": 95.0}})
        copied = case.to_dict()
        assert copied == asdict(case)
        copied["stages"]["check"][0]["bounds"]["critical"] = 0.0
        copied["stages"]["check"].append({"outcome": "clean"})
        assert case.stages["check"] == [{"outcome": "found", "bounds": {"critical": 95.0}}]


class TestAnAttachmentCanAnswerWithoutTheCase:

    def test_it_copies_no_case(self, copies):
        session, case_id = _open_case()
        copies["n"] = 0                     # opening answers with the new case, once
        reply = api.attach_stage(session, case_id, "confirm", reference={"cause": "u-1", "basis": "a test"},
                                 include_case=False).to_dict()["case"]
        assert copies["n"] == 0
        assert (reply["case_id"], reply["status"], reply["checked"]["stages_attached"]) == (case_id, "open", 1)
        assert "stages" not in reply
        assert len(session.ledger.case_book.get(case_id).stages["confirm"]) == 1

    def test_by_default_the_case_comes_back_whole(self):
        session, case_id = _open_case()
        reply = api.attach_stage(session, case_id, "confirm",
                                 reference={"cause": "u-1", "basis": "a test"}).to_dict()["case"]
        assert reply["case_id"] == case_id and len(reply["stages"]["confirm"]) == 1

    def test_a_refused_attachment_says_why_either_way(self):
        session, _case_id = _open_case()
        for include in (True, False):
            reply = api.attach_stage(session, "no-such-case", "confirm", reference={"cause": "u-1"},
                                     include_case=include).to_dict()["case"]
            assert [d["reason"] for d in reply["not_checked"]] == ["malformed_request"]
            assert reply["checked"]["stages_attached"] == 0
