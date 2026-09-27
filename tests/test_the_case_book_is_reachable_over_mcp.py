"""The case book over MCP: three verbs a client could not reach, and a book
that outlives the server when the server is started on a durable file.

`hypothesize` and `file_action` became tools a release before the case book
shipped, and the case book's verbs did not follow them -- so a client could run
every stage of the loop except the one that holds the stages together. And the
server's session never took a ledger argument, so even with the verbs a case
would have lasted exactly as long as the process that opened it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from arbiter_engine.mcp import server
from arbiter_engine.residual.sqlite_ledger import \
    SqlitePredictionLedger

CASE_VERBS = ("open_case", "attach_stage", "case_book")

MODEL = {"domain": {
    "id": "cases", "name": "one unit", "entity_types": ["Unit"],
    "indicators": {"Unit": [{"name": "load", "type": "NUMERIC",
                             "axioms": ["BOUNDEDNESS"],
                             "warning": 80, "critical": 95}]},
    "cases": {"severity": "warning", "consecutive_checks": 2},
}}


def _call(session, name, **arguments):
    """One tool call as a client makes it: JSON in, JSON out."""
    return json.loads(json.dumps(
        server.dispatch(session, name, json.loads(json.dumps(arguments)))))


def _loaded(session, load=97.0):
    _call(session, "load_model", model=MODEL)
    _call(session, "add_entity", entity_id="u-1", entity_type="Unit",
          properties={"load": load})
    return session


class TestTheThreeVerbsAreTools:

    def test_each_is_declared_and_routed(self):
        names = [spec["name"] for spec in server.TOOL_SPECS]
        for verb in CASE_VERBS:
            assert names.count(verb) == 1, verb
            assert verb in server._HANDLERS, verb

    def test_a_description_says_how_long_the_book_lasts(self):
        """Without a durable ledger the book is in memory, and an agent
        reading the tool list is the one reader who cannot find that out."""
        spec = next(s for s in server.TOOL_SPECS if s["name"] == "open_case")
        assert "--ledger" in spec["description"]
        assert "as long as the server process" in spec["description"]


class TestACaseRunsEndToEndOverTheTransport:

    def test_opened_attached_and_resolved(self):
        session = _loaded(server.start_session())
        opened = _call(session, "open_case", entity_id="u-1", indicator="load",
                       basis="alarm 4")
        case_id = opened["case"]["case_id"]
        _call(session, "check")

        ranking = _call(session, "hypothesize", entity_id="u-1")
        attached = _call(session, "attach_stage", case_id=case_id,
                         stage="hypothesize", envelope=ranking)
        assert attached["case"]["checked"]["stages_attached"] == 1

        _call(session, "add_entity", entity_id="u-1", entity_type="Unit",
              properties={"load": 50.0})
        _call(session, "check")
        _call(session, "check")
        book = _call(session, "case_book")
        assert book["cases"]["checked"]["cases"] == 1
        case = book["cases"]["cases"][0]
        assert case["status"] == "resolved"
        assert case["stages"]["hypothesize"][0]["declined"]
        assert [e["outcome"] for e in case["stages"]["check"]] == [
            "found", "clean", "clean"]

    def test_learn_attaches_by_reference_and_another_verbs_envelope_does_not(self):
        session = _loaded(server.start_session())
        case_id = _call(session, "open_case", entity_id="u-1",
                        indicator="load")["case"]["case_id"]
        learned = _call(session, "attach_stage", case_id=case_id, stage="learn",
                        reference={"adopted": None, "why": "no fitted gain yet"})
        assert learned["case"]["checked"]["stages_attached"] == 1
        wrong = _call(session, "attach_stage", case_id=case_id, stage="plan",
                      envelope=_call(session, "check"))
        assert wrong["case"]["checked"]["stages_attached"] == 0
        assert {d["reason"] for d in wrong["case"]["not_checked"]} == {
            "malformed_request"}

    def test_a_refusal_arrives_by_name_not_as_an_error(self):
        session = server.start_session()
        _call(session, "load_model", model={"domain": {
            k: v for k, v in MODEL["domain"].items() if k != "cases"}})
        _call(session, "add_entity", entity_id="u-1", entity_type="Unit",
              properties={"load": 97.0})
        refused = _call(session, "open_case", entity_id="u-1", indicator="load")
        assert {d["reason"] for d in refused["case"]["not_checked"]} == {
            "missing_config"}


class TestTheBookOutlivesTheServerOnADurableLedger:

    def test_a_second_server_on_the_same_file_reads_the_same_case(self, tmp_path):
        path = str(tmp_path / "book.db")
        first = _loaded(server.start_session(path))
        case_id = _call(first, "open_case", entity_id="u-1", indicator="load",
                        basis="alarm 4")["case"]["case_id"]
        assert isinstance(first.ledger, SqlitePredictionLedger)

        second = server.start_session(path)
        book = _call(second, "case_book")
        assert [c["case_id"] for c in book["cases"]["cases"]] == [case_id]

    def test_without_one_the_book_is_the_processes_own(self, tmp_path):
        first = _loaded(server.start_session())
        _call(first, "open_case", entity_id="u-1", indicator="load")
        assert _call(server.start_session(), "case_book")["cases"]["checked"][
            "cases"] == 0

    def test_the_server_refuses_a_ledger_it_cannot_open(self, tmp_path, capsys):
        """A launcher is the one place a bad path cannot be reported through
        an envelope, so it fails there, loudly, like a bad `--model`."""
        assert server.main(["--ledger", str(tmp_path / "no" / "such" / "dir.db")]) == 2
        assert "could not open the ledger" in capsys.readouterr().err


def _changelog() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / "CHANGELOG.md",
                      here.parents[2] / "docs" / "publication" / "engine-changelog"
                      / "CHANGELOG.md"):
        if candidate.is_file():
            return candidate
    raise AssertionError("no CHANGELOG.md in this tree")


def _newest_stated_count(text: str):
    """The tool count the newest section to state one gives, as a number."""
    words = {"seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
             "twenty-one": 21, "twenty-two": 22, "twenty-three": 23}
    match = re.search(r"MCP tools\*?\*?,\s+([\w-]+) in all", text)
    return (words.get(match.group(1).lower()) if match else None,
            match.group(1) if match else None)


class TestTheChangelogCountsTheRegistry:
    """The newest changelog entry that states how many tools there are states
    the registry's count. Older sections keep the count they shipped with."""

    def test_the_newest_stated_count_is_the_registrys(self):
        count, word = _newest_stated_count(_changelog().read_text(encoding="utf-8"))
        assert count is not None, f"no tool count stated, or written as {word!r}"
        assert count == len(server.TOOL_SPECS), (
            f"the changelog's newest count is {word!r}; TOOL_SPECS has "
            f"{len(server.TOOL_SPECS)}")

    @pytest.mark.parametrize("off_by", [-1, 1])
    def test_it_would_fail_one_either_side(self, off_by):
        count, _ = _newest_stated_count(_changelog().read_text(encoding="utf-8"))
        assert count != len(server.TOOL_SPECS) + off_by
