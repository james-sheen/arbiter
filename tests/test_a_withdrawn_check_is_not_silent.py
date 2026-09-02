"""A check this engine stopped performing must still be visible on `check`.

The compatibility policy permits a patch release to withdraw a check when the
answer came from a guess, and forbids doing it quietly, in one sentence:
a check withdrawn without a word is indistinguishable from one that passed.

THE RELEASE THAT PROMPTED THIS ALMOST BROKE IT. A walk used to judge any numeric
property by the words in its name; removing it was right, and on its own it left
the previous release reporting three impossible values -- one of them critical --
where this one reported nothing, with the decline leg empty and the denominator
unmoved. Two envelopes, identical in every byte a reader compares, for a system
whose faults were still there.

THE FIX IS A REPORT, NOT A DECLINE, AND THE SCHEMA CHOSE THAT. A decline record
requires an indicator and an axiom; a property nobody declared has neither, and
inventing them would mean naming the axiom from the property's name -- the move
that was removed. So the population rides beside the legs, where the other
reports of input that goes nowhere already sit.

WHAT EACH TEST BELOW WOULD LOSE. Every one is written so that deleting the
payload line reddens it, and so does making the report fire for everything: a
row nobody can act on fails this rule exactly as silence does.
"""
from __future__ import annotations

import tempfile
import textwrap

from arbiter_engine.api import (
    EngineSession, check, gaps, model_describe)

MODEL = """
    domain:
      id: d
      name: D
      entity_types: [U]
      relationship_types: [f]
      indicators:
        U:
          - name: level_pct
            type: NUMERIC
            role: percentage
            axioms: [CONSISTENCY]
    """


def _session(props):
    path = tempfile.mktemp(suffix=".yaml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(MODEL))
    session = EngineSession()
    session.load_model(path)
    session.add_entity("u0", "U", props)
    return session


CLEAN = {"level_pct": 50}
# The value is impossible and the property is undeclared -- the exact cell the
# removed walk used to catch, and the one the previous release reported.
FAULTY = {"level_pct": 50, "saturation_pct": 150}


def test_the_two_envelopes_are_not_identical():
    """The whole claim, stated as the policy states it."""
    assert check(_session(CLEAN)).to_dict() != check(_session(FAULTY)).to_dict()


def test_the_withdrawn_check_is_named_on_the_check_surface():
    """`check` is the verb the rule is about, so it is the surface asserted."""
    reported = {r["property"]
                for r in check(_session(FAULTY)).to_dict()["unread_properties"]}
    assert reported == {"saturation_pct"}


def test_a_clean_model_reports_nothing():
    """Fires for everything and fires for nothing are the same defect."""
    assert check(_session(CLEAN)).to_dict()["unread_properties"] == []


def test_the_check_really_was_withdrawn():
    """The removal is not quietly undone -- the value is named, never judged."""
    envelope = check(_session(FAULTY)).to_dict()
    assert envelope["findings"] == []


def test_no_synthetic_decline_was_smuggled_in():
    """A record needs an indicator and an axiom; this population has neither."""
    assert check(_session(FAULTY)).to_dict()["not_checked"] == []


def test_the_declared_path_still_evaluates():
    """The neighbour, asserted apart: a declared indicator is untouched."""
    envelope = check(_session({"level_pct": 150})).to_dict()
    assert [f["problem_type"] for f in envelope["findings"]] == ["impossible_value"]
    assert envelope["unread_properties"] == []


def test_all_three_verbs_agree_on_the_population():
    """One population, three surfaces. A per-surface copy is a place to drift."""
    session_of = lambda: _session(FAULTY)
    seen = [tuple(sorted(r["property"] for r in verb(session_of()).to_dict()
                         ["unread_properties"]))
            for verb in (check, model_describe, gaps)]
    assert len(set(seen)) == 1, seen
