"""A declaration the engine did not recognise is reported by `check`.

`axioms: [BOUNDEDNES]` on an indicator carrying a `critical:`, with an entity
reading past it, used to produce an envelope BYTE-IDENTICAL to declaring no
axioms at all: no finding, no decline, `invariants: 0`. The check the author
wrote never ran and the result could not say so. Reported from outside against
0.1.10.

FOUR OF THE FIVE TOOLS WERE SILENT, not one. `check`, `gaps`, `attest` and
`traverse` all returned identical envelopes between the misspelling and no
declaration; only `model_describe` reported it, and an agent that calls `check`
does not call `model_describe`.

THE FINDING PROPOSED DECLINING THE CELL AND THE SCHEMA FORBIDS IT.
`not_checked[].axiom` is a closed enum of the eight axiom names, so a decline
recording `BOUNDEDNES` cannot be written without moving the wire contract. A
payload can say it without changing what every tool satisfies, which is the same
trade `unread_properties` made one release earlier and for the same reason.

THE SIBLING VOCABULARY ALREADY GOT THIS TREATMENT. A misspelled `role:` on the
same indicator declines `missing_role` into `not_checked` with a remedy, keeps
its entry in `declared_axioms`, and appears in `unreachable_declarations`. Two
closed vocabularies, adjacent lines of one declaration, four surfaces against
one. This closes the gap from the side the schema leaves open.
"""
from __future__ import annotations

import contextlib
import io

import pytest

from arbiter_engine.api import (
    EngineSession, attest, check, gaps, model_describe, traverse)

MODEL = """
domain:
  id: dropped-declaration-probe
  name: Dropped declaration probe
  entity_types: [Rail]
  indicators:
    Rail:
      - name: load_pct
        type: NUMERIC
        role: {role}
        axioms: [{axioms}]
        warning: 80
        critical: 95
"""


def _session(axioms: str = "BOUNDEDNESS", role: str = "percentage"):
    """A loaded session, with the loader's warnings swallowed.

    The stderr line is a real signal and is deliberately NOT what these assert:
    a log line is not a surface a caller can query, and a long-running service
    emits it once at load and never again.
    """
    session = EngineSession()
    with contextlib.redirect_stderr(io.StringIO()):
        session.load_model(MODEL.format(axioms=axioms, role=role))
        session.add_entity("rail1", "Rail", properties={"load_pct": 99})
    return session


def _check(axioms: str = "BOUNDEDNESS", role: str = "percentage") -> dict:
    with contextlib.redirect_stderr(io.StringIO()):
        return check(_session(axioms, role)).to_dict()


class TestTheMisspellingIsNoLongerIndistinguishable:
    def test_a_dropped_axiom_is_reported(self):
        dropped = _check(axioms="BOUNDEDNES")["dropped_declarations"]
        assert len(dropped) == 1, dropped
        entry = dropped[0]
        assert entry["field"] == "axioms"
        assert entry["value"] == "BOUNDEDNES"
        assert entry["did_you_mean"] == "BOUNDEDNESS"
        assert entry["remedy"]

    def test_it_no_longer_matches_declaring_nothing(self):
        """The failure as reported: two different models, one envelope."""
        assert _check(axioms="BOUNDEDNES") != _check(axioms="")

    def test_a_correct_declaration_reports_nothing(self):
        """The other half. A report that fires on a clean model is one people
        turn off, and it would take this signal with it."""
        clean = _check()
        assert clean["dropped_declarations"] == []
        assert len(clean["findings"]) == 1, "the control model must actually fire"

    def test_a_dropped_role_is_reported_too(self):
        """The same key, the other vocabulary. `role` already declines into
        `not_checked`; this says the value was rejected, which the decline does
        not -- `missing_role` reads the same whether you misspelled it or never
        wrote one."""
        dropped = _check(axioms="CONSISTENCY", role="percentag")["dropped_declarations"]
        assert [(e["field"], e["value"]) for e in dropped] == [("role", "percentag")]


class TestTheReportIsNarrowerThanTheDescribeLeg:
    def test_it_carries_only_rejected_values(self):
        """`unread_fields` also lists fields whose consuming axiom was never
        declared. That answers a question `check` was not asked, and the report
        beside this one refused a fifth key on exactly that ground."""
        session = _session(axioms="BOUNDEDNESS")
        with contextlib.redirect_stderr(io.StringIO()):
            described = model_describe(session).to_dict()["model"]["unread_fields"]
            reported = check(session).to_dict()["dropped_declarations"]
        assert any(e["reason"] == "axiom_not_declared" for e in described), (
            "the control needs a describe entry of the kind this must exclude")
        assert reported == []

    def test_every_entry_is_a_subset_of_the_describe_leg(self):
        """Two readers of one fact, so the narrow one must not invent."""
        session = _session(axioms="BOUNDEDNES")
        with contextlib.redirect_stderr(io.StringIO()):
            described = model_describe(session).to_dict()["model"]["unread_fields"]
            reported = check(session).to_dict()["dropped_declarations"]
        for entry in reported:
            assert entry in described, entry


class TestTheOtherToolsAreUnchanged:
    """Only `check` gains the key, and that is a decision rather than an
    oversight: `gaps` answers what was never observed and `attest` answers what
    a finding rests on. Neither was asked whether a declaration took effect."""

    @pytest.mark.parametrize("verb", ("gaps", "attest", "traverse"))
    def test_no_other_verb_grew_the_key(self, verb):
        session = _session(axioms="BOUNDEDNES")
        with contextlib.redirect_stderr(io.StringIO()):
            check(session)
            envelope = {"gaps": lambda: gaps(session),
                        "attest": lambda: attest(session, "threshold_exceeded"),
                        "traverse": lambda: traverse(session, "rail1")}[verb]()
        assert "dropped_declarations" not in envelope.to_dict()

    def test_describe_still_carries_the_whole_list(self):
        session = _session(axioms="BOUNDEDNES")
        with contextlib.redirect_stderr(io.StringIO()):
            fields = model_describe(session).to_dict()["model"]["unread_fields"]
        assert any(e.get("value") == "BOUNDEDNES" for e in fields)


class TestTheCheckCouldFail:
    def test_the_probe_model_would_fire_if_the_axiom_resolved(self):
        """Without this the whole file could pass against a model whose reading
        never violated anything, and every assertion above would be about an
        envelope that was empty for an unrelated reason."""
        assert len(_check()["findings"]) == 1

    def test_an_unknown_value_is_what_the_loader_calls_it(self):
        """This filters on a reason string. If the loader renames it, the filter
        silently reports nothing -- which is the defect, restored."""
        session = _session(axioms="BOUNDEDNES")
        with contextlib.redirect_stderr(io.StringIO()):
            fields = model_describe(session).to_dict()["model"]["unread_fields"]
        assert {e["reason"] for e in fields} & {"unknown_value"}, (
            "the loader no longer reports rejected values as `unknown_value`; "
            "the filter in `dropped_declarations` is now looking for a reason "
            "nothing emits")
