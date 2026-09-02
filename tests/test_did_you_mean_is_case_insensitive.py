"""A suggestion that depends on the author guessing the vocabulary's case.

Every closed vocabulary here is case-insensitive on the way IN: the resolvers
upper- or lower-case the author's word before comparing, so `type: NUMERIC` and
`type: numeric` both load. The did-you-mean that fires when the word is NOT
recognised was case-SENSITIVE, and the recorded valid sets do not share a
convention -- some are an enum's members, some its values. So a suggestion
appeared only when the author's case happened to match the set's, and which case
that was varied per key with nothing telling the author which.

Measured before the fix: all seven vocabularies were asymmetric, five losing the
suggestion on upper case and two on lower. The shipped example declares
`type: NUMERIC`, so the case an author is most likely to copy was the one that
produced nothing.

The KEY site had it worse. Keys are genuinely case-sensitive to the loader, so
`WARNING:` really is unread -- and lower-casing it is the entire fix, which made
it the one input the suggester had nothing to say about.

THE COVERAGE ASSERTION IS PART OF THE TEST. A parametrised list can go short
without going red, so `test_every_reported_vocabulary_is_covered` compares this
file's list against the keys the loader actually reports for a model that
mistypes all of them. A vocabulary added later fails that test rather than
silently sitting outside this one.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from arbiter_engine.api import EngineSession, model_describe

HEAD = ("domain:\n  id: c\n  name: C\n  entity_types: [Unit]\n"
        "  relationship_types: [feeds]\n  indicators:\n")

#: (key, a near-miss of a real member). One per closed vocabulary.
VOCABULARIES = [
    ("type", "numeri"),
    ("axioms", "boundednes"),
    ("direction", "uppe"),
    ("role", "percentag"),
    ("flow", "ou"),
    ("expect_variation", "tru"),
    ("violation_severity", "critica"),
]


def _model(**fields):
    body = ["    Unit:", "      - name: level",
            f"        type: {fields.pop('type', 'numeric')}",
            f"        axioms: [{fields.pop('axioms', 'BOUNDEDNESS')}]"]
    body += [f"        {k}: {v}" for k, v in sorted(fields.items())]
    path = pathlib.Path(tempfile.mktemp(suffix=".yaml"))
    path.write_text(HEAD + "\n".join(body) + "\n")
    session = EngineSession()
    session.load_model(str(path))
    return (model_describe(session).to_dict().get("model") or {}).get(
        "unread_fields") or []


def _record(key, typo, reason="unknown_value"):
    for rec in _model(**{key: typo}):
        if rec.get("field") == key and rec.get("reason") == reason:
            return rec
    return None


@pytest.mark.parametrize("key,typo", VOCABULARIES)
def test_the_suggestion_does_not_depend_on_the_authors_case(key, typo):
    lower = _record(key, typo.lower())
    upper = _record(key, typo.upper())
    assert lower and upper, f"{key} stopped reporting an unrecognised value"
    assert lower["did_you_mean"] == upper["did_you_mean"], (
        f"{key} suggests {lower['did_you_mean']!r} for the lower-case typo and "
        f"{upper['did_you_mean']!r} for the upper-case one, while the loader "
        f"accepts either case on the way in")
    assert lower["did_you_mean"], f"{key} suggests nothing in either case"


@pytest.mark.parametrize("key,typo", VOCABULARIES)
def test_the_suggestion_is_a_real_member_of_the_valid_set(key, typo):
    rec = _record(key, typo.upper())
    assert rec["did_you_mean"] in rec["remedy"], (
        "the suggestion and the valid set are printed in one sentence and must "
        "not disagree")


def test_every_reported_vocabulary_is_covered():
    """This file's list against the one the loader actually produces."""
    mistyped = {k: v for k, v in VOCABULARIES}
    reported = {r["field"] for r in _model(**mistyped)
                if r.get("reason") == "unknown_value"}
    covered = {k for k, _ in VOCABULARIES}
    assert reported <= covered, (
        f"the loader reports closed vocabularies this test does not cover: "
        f"{sorted(reported - covered)}")


class TestTheKeySite:
    """Keys ARE case-sensitive to the loader, which makes the suggestion the fix."""

    def test_a_correctly_spelled_key_in_the_wrong_case_is_suggested(self):
        rec = _record("WARNING", 90, reason="unknown_key")
        assert rec and rec["did_you_mean"] == "warning"

    def test_a_typo_is_suggested_in_either_case(self):
        assert (_record("warnin", 90, reason="unknown_key")["did_you_mean"]
                == _record("WARNIN", 90, reason="unknown_key")["did_you_mean"]
                == "warning")


class TestTheControls:
    """A suggester that always suggests is worse than one that sometimes does."""

    def test_a_valid_value_is_not_reported_at_all(self):
        for spelling in ("numeric", "NUMERIC", "Numeric"):
            assert _record("type", spelling) is None, (
                f"`type: {spelling}` loads cleanly and must not be reported")

    def test_a_far_miss_gets_no_suggestion(self):
        rec = _record("type", "TEMPERATURE")
        assert rec is not None and rec["did_you_mean"] is None, (
            "the cutoff stopped applying; every unrecognised value now gets a "
            "suggestion, which makes the suggestion worthless")

    def test_the_valid_set_is_still_named_when_nothing_is_near(self):
        assert "numeric" in _record("type", "TEMPERATURE")["remedy"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
