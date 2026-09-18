"""Every member of every discipline vocabulary can actually be emitted.

`subenvelope.py` states the rule itself, twice, while withdrawing members that
had no producer: *a member no input can reach makes the set a worse instrument
-- a reader counting refusal kinds counts one that cannot happen, and the enum
stops being evidence about the engine.* Nothing enforced it. Six members were
carried across five vocabularies with no producer anywhere in the package, and
the standing test asserted only that `internal_error` was PRESENT -- membership,
which is the one property a dead member has.

THE COUNT IS DERIVED, NOT LISTED. A hand-written list of expected reasons is a
second copy of the vocabulary, and the second copy is what drifts: this file
would keep passing while the real set grew a member nothing emits. So the test
reads `VOCABULARIES` and searches the tree, and a new member with no producer
turns it red on the commit that adds it.

WHY A STRING SEARCH IS THE RIGHT INSTRUMENT HERE. It would be the wrong one in
a codebase that assembles reason names, because an assembled name is invisible
to it. This package writes them as literals throughout -- the same assumption
`test_the_readme_decline_count_is_derived.py` already relies on -- and the
failure mode is safe in the direction that matters: a name this test cannot
find is a name a reader grepping for it cannot find either.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from arbiter_engine import api as _anchor
from arbiter_engine.subenvelope import VOCABULARIES

PACKAGE = pathlib.Path(_anchor.__file__).parent

#: Where the vocabularies are DEFINED. A definition is not a producer, so this
#: file is excluded from the search -- otherwise every member trivially finds
#: itself and the test can never fail.
DEFINITION = "subenvelope.py"

#: The shadow discipline inherits the axiom layer's own enum wholesale
#: (``{reason.value for reason in NotEvaluatedReason}``). Those members are
#: produced by the axiom checkers as enum ATTRIBUTES, not as string literals,
#: so the search below cannot see them and a red here would be about the
#: instrument rather than the engine. Their reachability is the axiom layer's
#: own property and is tested there.
from arbiter_engine.interfaces import NotEvaluatedReason

INHERITED = {reason.value for reason in NotEvaluatedReason}


def _sources() -> list[pathlib.Path]:
    return [p for p in PACKAGE.rglob("*.py") if p.name != DEFINITION]


def _producers(member: str) -> list[str]:
    """Files quoting `member` as a string literal, other than the definition."""
    pattern = re.compile(r"""["']""" + re.escape(member) + r"""["']""")
    return [str(p.relative_to(PACKAGE)) for p in _sources()
            if pattern.search(p.read_text(encoding="utf-8"))]


def _members() -> list[tuple[str, str]]:
    return sorted((kind, member)
                  for kind, vocabulary in VOCABULARIES.items()
                  for member in vocabulary
                  if member not in INHERITED)


class TestEveryMemberIsReachable:

    @pytest.mark.parametrize("kind,member", _members())
    def test_a_member_has_at_least_one_producer(self, kind, member):
        found = _producers(member)
        assert found, (
            f"{kind!r} declares the decline reason {member!r} and nothing in "
            f"the package emits it. Either wire a producer, or withdraw it "
            f"with a note saying what brings it back -- the file does both "
            f"already. A reader counting refusal kinds is counting one that "
            f"cannot happen.")

    def test_the_search_can_fail(self):
        """The guard on the guard.

        Every assertion above is `found is non-empty`, which is exactly the
        shape that passes when the instrument is broken -- a search returning
        everything looks identical to a vocabulary that is entirely reachable.
        A name no vocabulary contains must come back with nothing.
        """
        assert not _producers("a_reason_no_discipline_declares")


class TestInternalErrorIsProducedAndNotMerelyPresent:
    """The member the standing test was about, asserted the other way.

    `test_a_discipline_reports_its_own_denominator.py` asserts
    ``"internal_error" in VOCABULARIES[kind]`` for every kind. That was true
    for every release in which no verb had an exception boundary, so the
    assertion held while the thing it describes could not happen.
    """

    def test_every_vocabulary_carries_it(self):
        for kind, vocabulary in VOCABULARIES.items():
            assert "internal_error" in vocabulary, kind

    def test_and_something_emits_it(self):
        found = _producers("internal_error")
        assert found, "no producer for internal_error"
        assert any("api.py" in name for name in found), (
            f"the verbs are where a discipline's raise becomes a decline; "
            f"found producers only in {found}")
