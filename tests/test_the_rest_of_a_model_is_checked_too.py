"""The rest of a model is compared against what the engine reads, too.

the three places that an internal ruling measured beside a relationship rule
and left out. Each loaded clean with `unread_fields` empty:

  - the domain's OWN top level. `relationship_rule:` for `relationship_rules:`
    dropped every rule and nothing named the word. The orchestrator's keys --
    23 of them, each read by a module this package does not include -- pass by
    name, the ruling that an internal ruling gave a rule's `match:`; the two keys nothing reads
    anywhere are reported like any other;
  - `calendar:`. `sesions:` left the world always open, and a session's
    `timezone:` left its hours read as UTC;
  - an entailment rule written out, which took any extra key. A `transitive:`
    shorthand is left alone: `entail` refuses one carrying anything else, whole
    and by name.

And an entry of `rules:` or `action_templates:` that is not a mapping was
dropped with no row, as a relationship rule's was.
"""

from __future__ import annotations

import ast
import inspect
import logging
import pathlib
import textwrap

import pytest

from arbiter_engine import api
from arbiter_engine.ontology.domain_loader import (
    _KNOWN_CALENDAR_KEYS, _KNOWN_ENTAILMENT_RULE_KEYS, _KNOWN_SESSION_KEYS,
    _MODEL_KEYS, _NON_ENGINE_MODEL_KEYS, is_domain_model, load_domain)

SESSION = {"days": ["mon", "tue"], "open": "09:00", "close": "17:00", "tz": "UTC"}


def _rows(**domain):
    base = {"id": "d", "name": "d", "entity_types": ["A", "B"],
            "relationship_types": ["r"], "indicators": {}}
    base.update(domain)
    return load_domain({"domain": base}).unread_fields()


def _named(**domain):
    return {r["field"]: r.get("did_you_mean") for r in _rows(**domain)}


class TestTheTopLevelIsChecked:

    def test_a_misspelled_section_is_named_with_the_right_one(self):
        rules = [{"type": "r", "source_type": "A", "target_type": "B"}]
        assert _named(relationship_rule=rules) == {
            "relationship_rule": "relationship_rules"}

    def test_the_orchestrators_keys_pass_by_name(self):
        assert _named(property_schema={"A": {}}, classification_mappings={},
                      approval_chain=[]) == {}

    def test_a_key_nothing_reads_anywhere_is_reported(self):
        assert _named(flow_types=["mass"]) == {"flow_types": None}


class TestTheCalendarIsChecked:

    def test_a_misspelled_sessions_is_named(self):
        assert _named(calendar={"sesions": [SESSION]}) == {
            "calendar.sesions": "sessions"}

    def test_a_sessions_misnamed_zone_is_named(self):
        session = {k: v for k, v in SESSION.items() if k != "tz"}
        session["timezone"] = "UTC"
        assert _named(calendar={"sessions": [session]}) == {
            "calendar.sessions[0].timezone": None}

    def test_a_fully_declared_calendar_is_quiet(self):
        assert _named(calendar={"sessions": [SESSION],
                                "holidays": ["2026-12-25"]}) == {}


class TestAnEntailmentRuleIsChecked:

    def test_an_extra_key_is_named_with_its_rule(self):
        row, = _rows(rules=[{"name": "up", "head": "up(A, B)",
                             "body": ["r(A, B)"], "descripton": "x"}])
        assert (row["field"], row["rule"]) == ("rules.descripton", "up")

    def test_a_shorthand_is_left_to_the_refusal_entail_already_makes(self):
        rule = {"name": "up", "transitive": "r", "max_hops": 2,
                "body": ["r(A, B)"]}
        assert _named(rules=[rule]) == {}
        session = api.EngineSession()
        session.load_model({"domain": {
            "id": "d", "name": "d", "entity_types": ["A"],
            "relationship_types": ["r"], "indicators": {}, "rules": [rule]}})
        declined = api.entail(session).to_dict()["entailment"]["not_checked"]
        assert "malformed_rule" in {d["reason"] for d in declined}


class TestAnEntryThatIsNotAMappingIsReported:

    @pytest.mark.parametrize("section, entry", [
        ("rules", "up(A, B) :- r(A, B)"),
        ("action_templates", "restart"),
        ("relationship_rules", None),
    ])
    def test_it_is_named_by_its_position(self, section, entry):
        row, = [r for r in _rows(**{section: [entry]})
                if r["reason"] == "unknown_value"]
        assert row["field"] == f"{section}[0]"
        assert "not a mapping" in row["remedy"] or "empty" in row["remedy"]


def _literals(function, varname):
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == varname
                and node.args and isinstance(node.args[0], ast.Constant)):
            found.add(node.args[0].value)
    return found


class TestTheSetsAreWhatTheReadersRead:

    def test_the_calendar_sets_are_what_the_calendar_reads(self):
        from arbiter_engine.history.calendar import SessionCalendar
        reader = SessionCalendar.from_declaration
        assert _literals(reader, "declaration") == set(_KNOWN_CALENDAR_KEYS)
        assert _literals(reader, "entry") == set(_KNOWN_SESSION_KEYS)

    def test_the_rule_set_is_what_parse_rule_reads(self):
        from arbiter_engine.ontology.entail import parse_rule
        assert _literals(parse_rule, "raw") == set(_KNOWN_ENTAILMENT_RULE_KEYS)

    def test_a_key_let_through_by_name_is_not_one_the_loader_reads(self):
        assert not _MODEL_KEYS & _NON_ENGINE_MODEL_KEYS


def _model_files():
    here = pathlib.Path(__file__).resolve()
    examples, others = [], []
    for directory in (here.parents[1] / "examples", here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if directory.is_dir():
            examples += sorted(directory.glob("*.yaml"))
    domains = here.parents[2] / "domains"
    if domains.is_dir():
        others += sorted(domains.glob("*.yaml"))
    return ([p for p in examples if is_domain_model(p)],
            [p for p in others if is_domain_model(p)])


class TestWhatShipsIsQuiet:

    def test_every_example_reports_nothing(self):
        examples, _ = _model_files()
        assert examples, "no example model was found to check"
        logging.disable(logging.WARNING)
        try:
            for path in examples:
                assert load_domain(path).unread_fields() == [], path.name
        finally:
            logging.disable(logging.NOTSET)

    def test_the_model_files_beside_the_engine_are_quiet_too(self):
        """Where the orchestrator's model files sit beside this engine, they
        report nothing. Two did, when this check was written: `flow_types` in
        consulting and `connectivity_requirements` in rfp, keys nothing reads
        anywhere. Both are comments now -- the second a copy of the CONNECTIVITY
        indicator that does run, the first a balance nobody has decided to
        hold. Absent from a tree that ships no such files, where the
        test above is the check."""
        _, others = _model_files()
        logging.disable(logging.WARNING)
        try:
            named = {(path.name, row["field"]) for path in others
                     for row in load_domain(path).unread_fields()}
        finally:
            logging.disable(logging.NOTSET)
        assert named == set()
